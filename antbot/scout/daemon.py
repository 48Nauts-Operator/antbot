"""Scout daemon — connects Go watcher events to the Python rule engine."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from antbot.events.logger import EventLogger
from antbot.events.schema import AntBotEvent
from antbot.exec_bridge.manager import ExecBridgeManager
from antbot.scout.config import RulesLoader
from antbot.scout.rules import Rule

logger = logging.getLogger(__name__)


class ScoutDaemon:
    """Watches directories via Go binary, applies rules, executes actions."""

    def __init__(
        self,
        exec_manager: ExecBridgeManager,
        rules_loader: RulesLoader,
        event_logger: EventLogger,
        dry_run: bool = True,
        confirm_callback=None,  # async callable(rule, path) -> bool
    ) -> None:
        self._exec = exec_manager
        self._rules = rules_loader
        self._events = event_logger
        self._dry_run = dry_run
        self._confirm = confirm_callback
        self._running = False

    async def start(self) -> None:
        """Start watching all directories from rules and processing events."""
        self._running = True
        client = await self._exec.ensure_connected()

        # Collect unique watch paths from rules
        watch_paths = set()
        for rule in self._rules.engine.rules:
            if rule.watch:
                watch_paths.add(rule.watch)

        if not watch_paths:
            logger.warning("No watch paths configured — scout daemon idle")
            return

        logger.info("Scout watching: %s", ", ".join(sorted(watch_paths)))

        # First, drain any buffered events from Go
        try:
            buffered = await client.drain_queue()
            if buffered:
                logger.info("Processing %d buffered events", len(buffered))
                for evt in buffered:
                    await self._handle_event(evt["path"], evt["size_bytes"])
        except Exception as e:
            logger.warning("Failed to drain queue: %s", e)

        # Start watching
        try:
            async for event in client.watch(list(watch_paths), recursive=False):
                if not self._running:
                    break
                await self._handle_event(event["path"], event.get("size_bytes", 0))
        except Exception as e:
            if self._running:
                logger.error("Watch stream error: %s", e)

    async def stop(self) -> None:
        self._running = False

    async def _handle_event(self, path: str, size: int) -> None:
        """Process a single file event through the rule engine."""
        is_dir = os.path.isdir(path)
        rule = self._rules.engine.match(path, size, is_dir)

        if rule is None:
            self._events.log(AntBotEvent(
                event="rule.no_match",
                src=path,
                action="skip",
                size_bytes=size,
            ))
            return

        self._events.log(AntBotEvent(
            event="rule.matched",
            src=path,
            rule=rule.name,
            action=rule.action,
            size_bytes=size,
        ))

        # Check if confirmation needed
        if rule.confirm and self._confirm:
            approved = await self._confirm(rule, path)
            if not approved:
                self._events.log(AntBotEvent(
                    event="action.denied",
                    src=path,
                    rule=rule.name,
                    action="skip",
                ))
                return

        # Resolve target
        target = rule.resolve_target(path)

        # Execute action
        await self._execute_action(rule, path, target, size)

    async def _execute_action(self, rule: Rule, src: str, dst: str, size: int) -> None:
        """Execute move or copy via Go binary."""
        dry_run = self._dry_run

        try:
            client = await self._exec.ensure_connected()

            if rule.action == "move":
                result = await client.move(src, dst, dry_run=dry_run)
            elif rule.action == "copy":
                result = await client.copy(src, dst, dry_run=dry_run)
            else:
                logger.warning("Unknown action '%s' in rule '%s'", rule.action, rule.name)
                return

            if result["ok"]:
                self._events.log(AntBotEvent(
                    event=f"file.{rule.action}d" if not dry_run else f"file.{rule.action}_dry",
                    src=src,
                    dst=dst,
                    rule=rule.name,
                    action=rule.action,
                    dry_run=dry_run,
                    ok=True,
                    size_bytes=result.get("size_bytes", size),
                ))
                if not dry_run:
                    logger.info("%s: %s → %s", rule.action.upper(), src, dst)
                else:
                    logger.info("[DRY RUN] %s: %s → %s", rule.action.upper(), src, dst)
            else:
                self._events.log(AntBotEvent(
                    event=f"file.{rule.action}_failed",
                    src=src,
                    dst=dst,
                    rule=rule.name,
                    action=rule.action,
                    dry_run=dry_run,
                    ok=False,
                    error=result.get("error", "unknown error"),
                    size_bytes=size,
                ))
                logger.error("Failed to %s %s: %s", rule.action, src, result.get("error"))

        except Exception as e:
            self._events.log(AntBotEvent(
                event=f"file.{rule.action}_error",
                src=src,
                dst=dst,
                rule=rule.name,
                action=rule.action,
                ok=False,
                error=str(e),
                size_bytes=size,
            ))
            logger.error("Error executing %s for %s: %s", rule.action, src, e)
