"""Scout daemon — connects Go watcher events to the Python rule engine."""

from __future__ import annotations

import asyncio
import logging
import os

from antbot.events.logger import EventLogger
from antbot.events.schema import AntBotEvent
from antbot.exec_bridge.manager import ExecBridgeManager
from antbot.scout.config import RulesLoader
from antbot.scout.rules import Rule
from antbot.scout.state import FileState, StateTracker

logger = logging.getLogger(__name__)

# Retry queued items every 60 seconds
RETRY_INTERVAL = 60


class ScoutDaemon:
    """Watches directories via Go binary, applies rules, executes actions."""

    def __init__(
        self,
        exec_manager: ExecBridgeManager,
        rules_loader: RulesLoader,
        event_logger: EventLogger,
        dry_run: bool = True,
        confirm_callback=None,
        state_path: str | None = None,
    ) -> None:
        self._exec = exec_manager
        self._rules = rules_loader
        self._events = event_logger
        self._dry_run = dry_run
        self._confirm = confirm_callback
        self._running = False
        self._state = StateTracker(state_path or os.path.expanduser("~/.antbot/state.json"))

    @property
    def state(self) -> StateTracker:
        return self._state

    async def start(self) -> None:
        """Start watching all directories from rules and processing events."""
        self._running = True
        client = await self._exec.ensure_connected()

        watch_paths = set()
        for rule in self._rules.engine.rules:
            if rule.watch:
                watch_paths.add(rule.watch)

        if not watch_paths:
            logger.warning("No watch paths configured — scout daemon idle")
            return

        logger.info("Scout watching: %s", ", ".join(sorted(watch_paths)))

        # Drain buffered events from Go
        try:
            buffered = await client.drain_queue()
            if buffered:
                logger.info("Processing %d buffered events", len(buffered))
                for evt in buffered:
                    await self._handle_event(evt["path"], evt["size_bytes"])
        except Exception as e:
            logger.warning("Failed to drain queue: %s", e)

        # Retry any previously queued items
        await self._retry_queued()

        # Start watching + retry loop
        retry_task = asyncio.create_task(self._retry_loop())
        try:
            async for event in client.watch(list(watch_paths), recursive=False):
                if not self._running:
                    break
                await self._handle_event(event["path"], event.get("size_bytes", 0))
        except Exception as e:
            if self._running:
                logger.error("Watch stream error: %s", e)
        finally:
            retry_task.cancel()

    async def stop(self) -> None:
        self._running = False

    async def _retry_loop(self) -> None:
        """Periodically retry queued operations."""
        while self._running:
            await asyncio.sleep(RETRY_INTERVAL)
            await self._retry_queued()

    async def _retry_queued(self) -> None:
        """Retry all queued files."""
        queued = self._state.get_queued()
        if not queued:
            return

        logger.info("Retrying %d queued operations", len(queued))
        for tf in queued:
            if tf.attempts >= 10:
                self._state.transition(tf.path, FileState.FAILED, error="max retries exceeded")
                self._events.log(AntBotEvent(
                    event="file.max_retries",
                    src=tf.path, dst=tf.target, rule=tf.rule,
                    ok=False, error="max retries exceeded",
                ))
                continue

            self._state.transition(tf.path, FileState.EXECUTING, attempts=tf.attempts + 1)
            await self._execute_action_tracked(tf.path, tf.target, tf.rule, tf.action, tf.size)

    async def _handle_event(self, path: str, size: int) -> None:
        """Process a single file event through the rule engine."""
        # Skip if already being tracked and not in a retryable state
        existing = self._state.get(path)
        if existing and existing.state in (FileState.EXECUTING, FileState.SUCCEEDED, FileState.AWAITING_APPROVAL):
            return

        is_dir = os.path.isdir(path)
        tf = self._state.track(path, size=size, state=FileState.STABLE)

        rule = self._rules.engine.match(path, size, is_dir)

        if rule is None:
            self._state.transition(path, FileState.SKIPPED)
            self._state.remove(path)
            self._events.log(AntBotEvent(
                event="rule.no_match", src=path, action="skip", size_bytes=size,
            ))
            return

        target = rule.resolve_target(path)
        self._state.transition(path, FileState.MATCHED, rule=rule.name, target=target, action=rule.action)
        self._events.log(AntBotEvent(
            event="rule.matched", src=path, rule=rule.name, action=rule.action, size_bytes=size,
        ))

        # Confirmation check
        if rule.confirm and self._confirm:
            self._state.transition(path, FileState.AWAITING_APPROVAL)
            approved = await self._confirm(rule, path)
            if not approved:
                self._state.transition(path, FileState.SKIPPED)
                self._state.remove(path)
                self._events.log(AntBotEvent(
                    event="action.denied", src=path, rule=rule.name, action="skip",
                ))
                return

        self._state.transition(path, FileState.EXECUTING)
        await self._execute_action_tracked(path, target, rule.name, rule.action, size)

    async def _execute_action_tracked(self, src: str, dst: str, rule_name: str, action: str, size: int) -> None:
        """Execute move or copy with state tracking."""
        dry_run = self._dry_run

        try:
            client = await self._exec.ensure_connected()

            if action == "move":
                result = await client.move(src, dst, dry_run=dry_run)
            elif action == "copy":
                result = await client.copy(src, dst, dry_run=dry_run)
            else:
                self._state.transition(src, FileState.FAILED, error=f"unknown action: {action}")
                return

            if result["ok"]:
                self._state.transition(src, FileState.SUCCEEDED)
                self._state.remove(src)  # cleanup after success
                evt_name = f"file.{action}d" if not dry_run else f"file.{action}_dry"
                self._events.log(AntBotEvent(
                    event=evt_name, src=src, dst=dst, rule=rule_name,
                    action=action, dry_run=dry_run, ok=True,
                    size_bytes=result.get("size_bytes", size),
                ))
                prefix = "[DRY RUN] " if dry_run else ""
                logger.info("%s%s: %s → %s", prefix, action.upper(), src, dst)
            else:
                error = result.get("error", "unknown error")
                # Queue for retry if it looks like a transient failure
                if "mount" in error.lower() or "no such file" in error.lower() or "permission" in error.lower():
                    self._state.transition(src, FileState.QUEUED, error=error)
                else:
                    self._state.transition(src, FileState.FAILED, error=error)
                self._events.log(AntBotEvent(
                    event=f"file.{action}_failed", src=src, dst=dst, rule=rule_name,
                    action=action, dry_run=dry_run, ok=False, error=error, size_bytes=size,
                ))
                logger.error("Failed to %s %s: %s", action, src, error)

        except Exception as e:
            self._state.transition(src, FileState.QUEUED, error=str(e))
            self._events.log(AntBotEvent(
                event=f"file.{action}_error", src=src, dst=dst, rule=rule_name,
                action=action, ok=False, error=str(e), size_bytes=size,
            ))
            logger.error("Error executing %s for %s: %s", action, src, e)
