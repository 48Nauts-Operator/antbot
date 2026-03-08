"""Agent loop: the core processing engine."""

from __future__ import annotations

import asyncio
import json
import re
import weakref
from contextlib import AsyncExitStack
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from loguru import logger

from antbot.agent.context import ContextBuilder
from antbot.agent.memory import MemoryStore
from antbot.agent.orchestrator import Orchestrator
from antbot.agent.subagent import SubagentManager
from antbot.agent.tools.cron import CronTool
from antbot.agent.tools.docker_tool import DockerTool
from antbot.agent.tools.filesystem import EditFileTool, ListDirTool, ReadFileTool, TreeTool, WriteFileTool
from antbot.agent.tools.git_tool import GitTool
from antbot.agent.tools.http_tool import HttpTool
from antbot.agent.tools.message import MessageTool
from antbot.agent.tools.process_tool import ProcessTool
from antbot.agent.tools.registry import ToolRegistry
from antbot.agent.tools.shell import ExecTool
from antbot.agent.tools.spawn import SpawnTool
from antbot.agent.tools.strategy import (
    NativeToolStrategy,
    ReactToolStrategy,
    ToolStrategy,
    select_tools_for_message,
)
from antbot.agent.tools.space_tool import SpaceAntTool
from antbot.agent.tools.web import WebFetchTool, WebSearchTool
from antbot.bus.events import InboundMessage, OutboundMessage
from antbot.bus.queue import MessageBus
from antbot.providers.base import LLMProvider
from antbot.session.manager import Session, SessionManager

if TYPE_CHECKING:
    from antbot.config.schema import ChannelsConfig, ExecToolConfig
    from antbot.cron.service import CronService


class AgentLoop:
    """
    The agent loop is the core processing engine.

    It:
    1. Receives messages from the bus
    2. Builds context with history, memory, skills
    3. Calls the LLM
    4. Executes tool calls
    5. Sends responses back
    """

    _TOOL_RESULT_MAX_CHARS = 500

    def __init__(
        self,
        bus: MessageBus,
        provider: LLMProvider,
        workspace: Path,
        model: str | None = None,
        max_iterations: int = 40,
        temperature: float = 0.1,
        max_tokens: int = 4096,
        memory_window: int = 100,
        reasoning_effort: str | None = None,
        brave_api_key: str | None = None,
        searxng_url: str | None = None,
        web_proxy: str | None = None,
        exec_config: ExecToolConfig | None = None,
        cron_service: CronService | None = None,
        restrict_to_workspace: bool = False,
        session_manager: SessionManager | None = None,
        mcp_servers: dict | None = None,
        channels_config: ChannelsConfig | None = None,
        tool_mode: str = "auto",
        max_tools_per_request: int = 0,
        fast_path_enabled: bool = True,
    ):
        from antbot.config.schema import ExecToolConfig
        self.bus = bus
        self.channels_config = channels_config
        self.provider = provider
        self.workspace = workspace
        self.model = model or provider.get_default_model()
        self.max_iterations = max_iterations
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.memory_window = memory_window
        self.reasoning_effort = reasoning_effort
        self.brave_api_key = brave_api_key
        self.searxng_url = searxng_url
        self.web_proxy = web_proxy
        self.exec_config = exec_config or ExecToolConfig()
        self.cron_service = cron_service
        self.restrict_to_workspace = restrict_to_workspace
        self.tool_mode = tool_mode
        self.max_tools_per_request = max_tools_per_request
        self.fast_path_enabled = fast_path_enabled

        self.context = ContextBuilder(workspace)
        self.sessions = session_manager or SessionManager(workspace)
        self.tools = ToolRegistry()
        self.subagents = SubagentManager(
            provider=provider,
            workspace=workspace,
            bus=bus,
            model=self.model,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            reasoning_effort=reasoning_effort,
            brave_api_key=brave_api_key,
            searxng_url=searxng_url,
            web_proxy=web_proxy,
            exec_config=self.exec_config,
            restrict_to_workspace=restrict_to_workspace,
        )

        self._running = False
        self._mcp_servers = mcp_servers or {}
        self._mcp_stack: AsyncExitStack | None = None
        self._mcp_connected = False
        self._mcp_connecting = False
        self._consolidating: set[str] = set()  # Session keys with consolidation in progress
        self._consolidation_tasks: set[asyncio.Task] = set()  # Strong refs to in-flight tasks
        self._consolidation_locks: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()
        self._active_tasks: dict[str, list[asyncio.Task]] = {}  # session_key -> tasks
        self._processing_lock = asyncio.Lock()
        self._register_default_tools()

        # Initialize Orchestrator (Planner + Guard + chunked execution)
        self.orchestrator = Orchestrator(
            provider=provider,
            context_builder=self.context,
            tools=self.tools,
            workspace=workspace,
            model=self.model,
            model_context_window=getattr(self, '_model_context_window', 32000),
            guard_enabled=True,
        )

    def _register_default_tools(self) -> None:
        """Register the default set of tools."""
        allowed_dir = self.workspace if self.restrict_to_workspace else None
        for cls in (ReadFileTool, WriteFileTool, EditFileTool, ListDirTool, TreeTool):
            self.tools.register(cls(workspace=self.workspace, allowed_dir=allowed_dir))
        self.tools.register(ExecTool(
            working_dir=str(self.workspace),
            timeout=self.exec_config.timeout,
            restrict_to_workspace=self.restrict_to_workspace,
            path_append=self.exec_config.path_append,
        ))
        self.tools.register(WebSearchTool(api_key=self.brave_api_key, proxy=self.web_proxy, searxng_url=self.searxng_url))
        self.tools.register(WebFetchTool(proxy=self.web_proxy))
        self.tools.register(MessageTool(send_callback=self.bus.publish_outbound))
        self.tools.register(SpawnTool(manager=self.subagents))
        self.tools.register(DockerTool())
        self.tools.register(GitTool(working_dir=str(self.workspace)))
        self.tools.register(HttpTool())
        self.tools.register(ProcessTool())
        self.tools.register(SpaceAntTool())
        if self.cron_service:
            self.tools.register(CronTool(self.cron_service))

    async def _connect_mcp(self) -> None:
        """Connect to configured MCP servers (one-time, lazy)."""
        if self._mcp_connected or self._mcp_connecting or not self._mcp_servers:
            return
        self._mcp_connecting = True
        from antbot.agent.tools.mcp import connect_mcp_servers
        try:
            self._mcp_stack = AsyncExitStack()
            await self._mcp_stack.__aenter__()
            await connect_mcp_servers(self._mcp_servers, self.tools, self._mcp_stack)
            self._mcp_connected = True
        except Exception as e:
            logger.error("Failed to connect MCP servers (will retry next message): {}", e)
            if self._mcp_stack:
                try:
                    await self._mcp_stack.aclose()
                except Exception:
                    pass
                self._mcp_stack = None
        finally:
            self._mcp_connecting = False

    def _set_tool_context(self, channel: str, chat_id: str, message_id: str | None = None) -> None:
        """Update context for all tools that need routing info."""
        for name in ("message", "spawn", "cron"):
            if tool := self.tools.get(name):
                if hasattr(tool, "set_context"):
                    tool.set_context(channel, chat_id, *([message_id] if name == "message" else []))

    @staticmethod
    def _strip_think(text: str | None) -> str | None:
        """Remove <think>…</think> blocks that some models embed in content."""
        if not text:
            return None
        return re.sub(r"<think>[\s\S]*?</think>", "", text).strip() or None

    @staticmethod
    def _tool_hint(tool_calls: list) -> str:
        """Format tool calls as concise hint, e.g. 'web_search("query")'."""
        def _fmt(tc):
            args = (tc.arguments[0] if isinstance(tc.arguments, list) else tc.arguments) or {}
            val = next(iter(args.values()), None) if isinstance(args, dict) else None
            if not isinstance(val, str):
                return tc.name
            return f'{tc.name}("{val[:40]}…")' if len(val) > 40 else f'{tc.name}("{val}")'
        return ", ".join(_fmt(tc) for tc in tool_calls)

    def _get_tool_strategy(self) -> ToolStrategy:
        """Select the tool-calling strategy based on config and model detection."""
        mode = self.tool_mode
        if mode == "react":
            logger.info("Tool strategy: ReAct (forced by config)")
            return ReactToolStrategy()
        if mode == "native":
            logger.info("Tool strategy: Native (forced by config)")
            return NativeToolStrategy()
        # auto: detect from model name
        from antbot.providers.local_detect import detect_native_tool_support
        if detect_native_tool_support(self.model):
            return NativeToolStrategy()
        logger.info("Tool strategy: ReAct (auto-detected for model {})", self.model)
        return ReactToolStrategy()

    def _get_tool_categories(self) -> dict[str, str]:
        """Build a mapping of tool_name -> category from the registry."""
        return {
            name: (tool.category if hasattr(tool, "category") else "general")
            for name, tool in self.tools._tools.items()
        }

    async def _try_fast_path(self, message: str) -> str | None:
        """Attempt to handle a message via fast-path (no LLM).

        Returns formatted output string on match, or None to fall through.
        """
        from antbot.agent.fast_path import FastPathRouter

        router = FastPathRouter()
        match = router.try_match(message, str(self.workspace))
        if match is None:
            return None

        logger.info("Fast-path match: {}({})", match.tool_name, match.arguments)
        result = await self.tools.execute(match.tool_name, match.arguments)
        return result

    async def _run_agent_loop(
        self,
        initial_messages: list[dict],
        on_progress: Callable[..., Awaitable[None]] | None = None,
    ) -> tuple[str | None, list[str], list[dict]]:
        """Run the agent iteration loop. Returns (final_content, tools_used, messages)."""
        messages = initial_messages
        iteration = 0
        final_content = None
        tools_used: list[str] = []

        strategy = self._get_tool_strategy()
        is_react = isinstance(strategy, ReactToolStrategy)

        while iteration < self.max_iterations:
            iteration += 1

            # Get tool definitions and optionally filter
            tool_defs = self.tools.get_definitions()
            if self.max_tools_per_request > 0 and messages:
                # Find the last user message for keyword scoring
                last_user_msg = ""
                for m in reversed(messages):
                    if m.get("role") == "user":
                        content = m.get("content", "")
                        last_user_msg = content if isinstance(content, str) else str(content)
                        break
                if last_user_msg:
                    tool_defs = select_tools_for_message(
                        last_user_msg, tool_defs,
                        self._get_tool_categories(),
                        self.max_tools_per_request,
                    )

            # Let the strategy modify messages and tools
            prepared_messages, prepared_tools = strategy.prepare_request(messages, tool_defs)

            # In ReAct mode, use lower max_tokens for intermediate turns
            # (tool calls rarely need more than ~200 tokens)
            turn_max_tokens = self.max_tokens
            if is_react and iteration < self.max_iterations:
                turn_max_tokens = min(self.max_tokens, 1024)

            response = await self.provider.chat(
                messages=prepared_messages,
                tools=prepared_tools,
                model=self.model,
                temperature=self.temperature,
                max_tokens=turn_max_tokens,
                reasoning_effort=self.reasoning_effort,
            )

            # Let the strategy parse tool calls from the response
            response = strategy.parse_response(response)

            if response.has_tool_calls:
                if on_progress:
                    thought = self._strip_think(response.content)
                    if thought:
                        await on_progress(thought)
                    await on_progress(self._tool_hint(response.tool_calls), tool_hint=True)

                if is_react:
                    # In ReAct mode, add the raw LLM text as an assistant message
                    messages = self.context.add_assistant_message(
                        messages, response.content,
                    )
                else:
                    tool_call_dicts = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments, ensure_ascii=False)
                            }
                        }
                        for tc in response.tool_calls
                    ]
                    messages = self.context.add_assistant_message(
                        messages, response.content, tool_call_dicts,
                        reasoning_content=response.reasoning_content,
                        thinking_blocks=response.thinking_blocks,
                    )

                for tool_call in response.tool_calls:
                    tools_used.append(tool_call.name)
                    args_str = json.dumps(tool_call.arguments, ensure_ascii=False)
                    logger.info("Tool call: {}({})", tool_call.name, args_str[:200])
                    result = await self.tools.execute(tool_call.name, tool_call.arguments)

                    if is_react:
                        # ReAct: inject result as "Observation:" user message
                        result_msg = strategy.format_tool_result(
                            tool_call.id, tool_call.name, result,
                        )
                        messages.append(result_msg)
                    else:
                        messages = self.context.add_tool_result(
                            messages, tool_call.id, tool_call.name, result
                        )
            else:
                clean = self._strip_think(response.content)
                if response.finish_reason == "error":
                    logger.error("LLM returned error: {}", (clean or "")[:200])
                    final_content = clean or "Sorry, I encountered an error calling the AI model."
                    break
                messages = self.context.add_assistant_message(
                    messages, clean, reasoning_content=response.reasoning_content,
                    thinking_blocks=response.thinking_blocks,
                )
                final_content = clean
                break

        if final_content is None and iteration >= self.max_iterations:
            logger.warning("Max iterations ({}) reached", self.max_iterations)
            final_content = (
                f"I reached the maximum number of tool call iterations ({self.max_iterations}) "
                "without completing the task. You can try breaking the task into smaller steps."
            )

        return final_content, tools_used, messages

    async def run(self) -> None:
        """Run the agent loop, dispatching messages as tasks to stay responsive to /stop."""
        self._running = True
        await self._connect_mcp()
        logger.info("Agent loop started")

        while self._running:
            try:
                msg = await asyncio.wait_for(self.bus.consume_inbound(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            if msg.content.strip().lower() == "/stop":
                await self._handle_stop(msg)
            else:
                task = asyncio.create_task(self._dispatch(msg))
                self._active_tasks.setdefault(msg.session_key, []).append(task)
                task.add_done_callback(lambda t, k=msg.session_key: self._active_tasks.get(k, []) and self._active_tasks[k].remove(t) if t in self._active_tasks.get(k, []) else None)

    async def _handle_stop(self, msg: InboundMessage) -> None:
        """Cancel all active tasks and subagents for the session."""
        tasks = self._active_tasks.pop(msg.session_key, [])
        cancelled = sum(1 for t in tasks if not t.done() and t.cancel())
        for t in tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        sub_cancelled = await self.subagents.cancel_by_session(msg.session_key)
        total = cancelled + sub_cancelled
        content = f"⏹ Stopped {total} task(s)." if total else "No active task to stop."
        await self.bus.publish_outbound(OutboundMessage(
            channel=msg.channel, chat_id=msg.chat_id, content=content,
        ))

    async def _handle_model_command(self, cmd: str, msg: InboundMessage) -> OutboundMessage:
        """Handle /model slash command — show, list, or switch models."""
        parts = cmd.split(None, 1)

        # /model (no args) → show current model + provider info
        if len(parts) == 1:
            provider_type = type(self.provider).__name__
            api_base = getattr(self.provider, 'api_base', None) or "default"
            lines = [
                f"**Current model:** `{self.model}`",
                f"**Provider:** {provider_type}",
                f"**Endpoint:** `{api_base}`",
                "",
                "Usage: `/model <name>` to switch, `/model list` to see available models.",
            ]
            return OutboundMessage(
                channel=msg.channel, chat_id=msg.chat_id,
                content="\n".join(lines),
            )

        arg = parts[1].strip()

        # /model list → query the endpoint for available models
        if arg.lower() == "list":
            models, err = await self._fetch_available_models()
            if models is None:
                return OutboundMessage(
                    channel=msg.channel, chat_id=msg.chat_id,
                    content=f"Could not fetch model list. {err}",
                )
            if not models:
                return OutboundMessage(
                    channel=msg.channel, chat_id=msg.chat_id,
                    content="No models available at the endpoint.",
                )
            content = self._format_model_tree(models)
            return OutboundMessage(
                channel=msg.channel, chat_id=msg.chat_id,
                content=content,
            )

        # /model <name> → switch (with fuzzy matching)
        resolved = await self._resolve_model_name(arg)
        if resolved is None:
            # No match found — use as-is (might be a model not yet downloaded)
            resolved = arg
            note = " (not found on endpoint — using as-is)"
        elif resolved != arg:
            note = f" (matched from `{arg}`)"
        else:
            note = ""

        old_model = self.model
        self.model = resolved
        if hasattr(self.provider, "default_model"):
            self.provider.default_model = resolved
        logger.info("Model switched: {} → {}", old_model, resolved)
        return OutboundMessage(
            channel=msg.channel, chat_id=msg.chat_id,
            content=f"Model switched: `{old_model}` → `{resolved}`{note}",
        )

    async def _resolve_model_name(self, name: str) -> str | None:
        """Resolve a partial/short model name to a full model ID.

        Tries: exact match, suffix match (e.g. 'GLM-4.7-Flash-4bit'),
        case-insensitive substring match. Returns None if no match.
        """
        models, _ = await self._fetch_available_models()
        if not models:
            return None

        ids = [m["id"] for m in models]
        name_lower = name.lower()

        # Exact match
        if name in ids:
            return name

        # Suffix match (user typed short name without org prefix)
        for mid in ids:
            if mid.endswith("/" + name) or mid.endswith("--" + name):
                return mid
            # Also match the part after the last /
            short = mid.split("/")[-1]
            if short == name:
                return mid

        # Case-insensitive substring
        for mid in ids:
            if name_lower in mid.lower():
                return mid

        return None

    async def _fetch_available_models(self) -> tuple[list[dict] | None, str]:
        """Query the provider's /v1/models endpoint for available models.

        Returns (model_info_list, error_message). Each dict has:
            id, family, base_model, quantization, size_gb, capabilities
        model_info_list is None on failure.
        """
        try:
            client = getattr(self.provider, "_client", None)
            if client and hasattr(client, "models"):
                result = await client.models.list()
                models = []
                for m in result.data:
                    raw = m.model_extra or {} if hasattr(m, "model_extra") else {}
                    size_mb = raw.get("storage_size_megabytes", 0)
                    models.append({
                        "id": m.id,
                        "family": (raw.get("family") or "").lower(),
                        "base_model": raw.get("base_model") or "",
                        "quantization": raw.get("quantization") or "",
                        "size_gb": round(size_mb / 1024, 1) if size_mb else 0,
                        "capabilities": raw.get("capabilities") or [],
                    })
                models.sort(key=lambda x: (x["family"] or "zzz", x["id"]))
                return models, ""
            return None, "Provider does not support model listing."
        except Exception as e:
            logger.debug("Failed to fetch models: {}", e)
            err = str(e)
            if "Connection" in err or "connect" in err.lower():
                api_base = getattr(self.provider, 'api_base', 'unknown')
                return None, f"Endpoint unreachable: `{api_base}`"
            return None, f"Error: {err[:200]}"

    def _format_model_tree(self, models: list[dict]) -> str:
        """Format models as a grouped tree view with metadata."""
        from collections import defaultdict

        # Group by family
        families: dict[str, list[dict]] = defaultdict(list)
        for m in models:
            family = m["family"] or "other"
            families[family].append(m)

        total = len(models)
        lines = [f"**Models ({total})** — `/model <id>` to switch\n"]

        family_order = sorted(families.keys())
        for fi, family in enumerate(family_order):
            members = families[family]
            is_last_family = fi == len(family_order) - 1
            branch = "└─" if is_last_family else "├─"
            lines.append(f"{branch} **{family.upper()}** ({len(members)})")

            for mi, m in enumerate(members):
                is_last = mi == len(members) - 1
                vert = "   " if is_last_family else "│  "
                node = "└─" if is_last else "├─"

                # Build info tags
                tags = []
                if m["quantization"]:
                    tags.append(m["quantization"])
                if m["size_gb"]:
                    tags.append(f"{m['size_gb']}GB")
                caps = m.get("capabilities", [])
                if "thinking" in caps:
                    tags.append("think")
                if "code" in caps:
                    tags.append("code")

                tag_str = f"  [{', '.join(tags)}]" if tags else ""
                active = " **<< active**" if m["id"] == self.model else ""

                # Show short name (strip mlx-community/ prefix for readability)
                short = m["id"].split("/", 1)[-1] if "/" in m["id"] else m["id"]
                lines.append(f"{vert}{node} `{short}`{tag_str}{active}")

        lines.append(f"\n_Use full ID to switch, e.g._ `/model {models[0]['id']}`")
        return "\n".join(lines)

    async def _dispatch(self, msg: InboundMessage) -> None:
        """Process a message under the global lock."""
        async with self._processing_lock:
            try:
                response = await self._process_message(msg)
                if response is not None:
                    await self.bus.publish_outbound(response)
                elif msg.channel == "cli":
                    await self.bus.publish_outbound(OutboundMessage(
                        channel=msg.channel, chat_id=msg.chat_id,
                        content="", metadata=msg.metadata or {},
                    ))
            except asyncio.CancelledError:
                logger.info("Task cancelled for session {}", msg.session_key)
                raise
            except Exception:
                logger.exception("Error processing message for session {}", msg.session_key)
                await self.bus.publish_outbound(OutboundMessage(
                    channel=msg.channel, chat_id=msg.chat_id,
                    content="Sorry, I encountered an error.",
                ))

    async def close_mcp(self) -> None:
        """Close MCP connections."""
        if self._mcp_stack:
            try:
                await self._mcp_stack.aclose()
            except (RuntimeError, BaseExceptionGroup):
                pass  # MCP SDK cancel scope cleanup is noisy but harmless
            self._mcp_stack = None

    def stop(self) -> None:
        """Stop the agent loop."""
        self._running = False
        logger.info("Agent loop stopping")

    async def _process_message(
        self,
        msg: InboundMessage,
        session_key: str | None = None,
        on_progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> OutboundMessage | None:
        """Process a single inbound message and return the response."""
        # System messages: parse origin from chat_id ("channel:chat_id")
        if msg.channel == "system":
            channel, chat_id = (msg.chat_id.split(":", 1) if ":" in msg.chat_id
                                else ("cli", msg.chat_id))
            logger.info("Processing system message from {}", msg.sender_id)
            key = f"{channel}:{chat_id}"
            session = self.sessions.get_or_create(key)
            self._set_tool_context(channel, chat_id, msg.metadata.get("message_id"))
            history = session.get_history(max_messages=self.memory_window)
            messages = self.context.build_messages(
                history=history,
                current_message=msg.content, channel=channel, chat_id=chat_id,
            )
            final_content, _, all_msgs = await self._run_agent_loop(messages)
            self._save_turn(session, all_msgs, 1 + len(history))
            self.sessions.save(session)
            return OutboundMessage(channel=channel, chat_id=chat_id,
                                  content=final_content or "Background task completed.")

        preview = msg.content[:80] + "..." if len(msg.content) > 80 else msg.content
        logger.info("Processing message from {}:{}: {}", msg.channel, msg.sender_id, preview)

        key = session_key or msg.session_key
        session = self.sessions.get_or_create(key)

        # Slash commands
        cmd = msg.content.strip().lower()
        if cmd == "/new":
            lock = self._consolidation_locks.setdefault(session.key, asyncio.Lock())
            self._consolidating.add(session.key)
            try:
                async with lock:
                    snapshot = session.messages[session.last_consolidated:]
                    if snapshot:
                        temp = Session(key=session.key)
                        temp.messages = list(snapshot)
                        if not await self._consolidate_memory(temp, archive_all=True):
                            return OutboundMessage(
                                channel=msg.channel, chat_id=msg.chat_id,
                                content="Memory archival failed, session not cleared. Please try again.",
                            )
            except Exception:
                logger.exception("/new archival failed for {}", session.key)
                return OutboundMessage(
                    channel=msg.channel, chat_id=msg.chat_id,
                    content="Memory archival failed, session not cleared. Please try again.",
                )
            finally:
                self._consolidating.discard(session.key)

            session.clear()
            self.sessions.save(session)
            self.sessions.invalidate(session.key)
            return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id,
                                  content="New session started.")
        if cmd == "/model" or cmd.startswith("/model "):
            # Use original casing for model names (cmd is lowercased)
            return await self._handle_model_command(msg.content.strip(), msg)
        if cmd == "/help":
            return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id,
                                  content="🐈 antbot commands:\n/new — Start a new conversation\n/stop — Stop the current task\n/model — Show or switch active model\n/help — Show available commands")

        unconsolidated = len(session.messages) - session.last_consolidated
        if (unconsolidated >= self.memory_window and session.key not in self._consolidating):
            self._consolidating.add(session.key)
            lock = self._consolidation_locks.setdefault(session.key, asyncio.Lock())

            async def _consolidate_and_unlock():
                try:
                    async with lock:
                        await self._consolidate_memory(session)
                finally:
                    self._consolidating.discard(session.key)
                    _task = asyncio.current_task()
                    if _task is not None:
                        self._consolidation_tasks.discard(_task)

            _task = asyncio.create_task(_consolidate_and_unlock())
            self._consolidation_tasks.add(_task)

        self._set_tool_context(msg.channel, msg.chat_id, msg.metadata.get("message_id"))
        if message_tool := self.tools.get("message"):
            if isinstance(message_tool, MessageTool):
                message_tool.start_turn()

        async def _bus_progress(content: str, *, tool_hint: bool = False) -> None:
            meta = dict(msg.metadata or {})
            meta["_progress"] = True
            meta["_tool_hint"] = tool_hint
            await self.bus.publish_outbound(OutboundMessage(
                channel=msg.channel, chat_id=msg.chat_id, content=content, metadata=meta,
            ))

        progress_fn = on_progress or _bus_progress

        # Fast-path: direct tool execution without LLM for simple read-only queries
        if self.fast_path_enabled:
            fast_result = await self._try_fast_path(msg.content)
            if fast_result is not None:
                return OutboundMessage(
                    channel=msg.channel, chat_id=msg.chat_id,
                    content=fast_result, metadata=msg.metadata or {},
                )

        # Orchestrator: analyze task and decide execution strategy
        if self.orchestrator.should_plan(msg.content):
            measurement, plan = self.orchestrator.analyze_task(msg.content)
            if not plan.is_simple:
                # Chunked execution: each batch gets fresh context
                logger.info("Orchestrator: chunked execution ({} batches)", plan.estimated_batches)
                final_content = await self.orchestrator.execute_chunked(
                    plan=plan,
                    run_agent_fn=self._run_agent_loop,
                    build_messages_fn=lambda history, current_message: self.context.build_messages(
                        history=history, current_message=current_message,
                        channel=msg.channel, chat_id=msg.chat_id,
                    ),
                    on_progress=progress_fn,
                )
                # Save to session (minimal — just the request and final result)
                history = session.get_history(max_messages=self.memory_window)
                all_msgs = self.context.build_messages(
                    history=history, current_message=msg.content,
                    channel=msg.channel, chat_id=msg.chat_id,
                )
                all_msgs = self.context.add_assistant_message(all_msgs, final_content)
                self._save_turn(session, all_msgs, 1 + len(history))
                self.sessions.save(session)

                if final_content is None:
                    final_content = "Task completed but produced no output."
                preview = final_content[:120] + "..." if len(final_content) > 120 else final_content
                logger.info("Response to {}:{}: {}", msg.channel, msg.sender_id, preview)
                return OutboundMessage(
                    channel=msg.channel, chat_id=msg.chat_id, content=final_content,
                    metadata=msg.metadata or {},
                )

        # Standard execution: direct agent loop (simple tasks)
        history = session.get_history(max_messages=self.memory_window)
        initial_messages = self.context.build_messages(
            history=history,
            current_message=msg.content,
            media=msg.media if msg.media else None,
            channel=msg.channel, chat_id=msg.chat_id,
        )

        final_content, _, all_msgs = await self._run_agent_loop(
            initial_messages, on_progress=progress_fn,
        )

        if final_content is None:
            final_content = "I've completed processing but have no response to give."

        self._save_turn(session, all_msgs, 1 + len(history))
        self.sessions.save(session)

        if (mt := self.tools.get("message")) and isinstance(mt, MessageTool) and mt._sent_in_turn:
            return None

        preview = final_content[:120] + "..." if len(final_content) > 120 else final_content
        logger.info("Response to {}:{}: {}", msg.channel, msg.sender_id, preview)
        return OutboundMessage(
            channel=msg.channel, chat_id=msg.chat_id, content=final_content,
            metadata=msg.metadata or {},
        )

    def _save_turn(self, session: Session, messages: list[dict], skip: int) -> None:
        """Save new-turn messages into session, truncating large tool results."""
        from datetime import datetime
        for m in messages[skip:]:
            entry = dict(m)
            role, content = entry.get("role"), entry.get("content")
            if role == "assistant" and not content and not entry.get("tool_calls"):
                continue  # skip empty assistant messages — they poison session context
            if role == "tool" and isinstance(content, str) and len(content) > self._TOOL_RESULT_MAX_CHARS:
                entry["content"] = content[:self._TOOL_RESULT_MAX_CHARS] + "\n... (truncated)"
            elif role == "user":
                if isinstance(content, str) and content.startswith(ContextBuilder._RUNTIME_CONTEXT_TAG):
                    # Strip the runtime-context prefix, keep only the user text.
                    parts = content.split("\n\n", 1)
                    if len(parts) > 1 and parts[1].strip():
                        entry["content"] = parts[1]
                    else:
                        continue
                if isinstance(content, list):
                    filtered = []
                    for c in content:
                        if c.get("type") == "text" and isinstance(c.get("text"), str) and c["text"].startswith(ContextBuilder._RUNTIME_CONTEXT_TAG):
                            continue  # Strip runtime context from multimodal messages
                        if (c.get("type") == "image_url"
                                and c.get("image_url", {}).get("url", "").startswith("data:image/")):
                            filtered.append({"type": "text", "text": "[image]"})
                        else:
                            filtered.append(c)
                    if not filtered:
                        continue
                    entry["content"] = filtered
            entry.setdefault("timestamp", datetime.now().isoformat())
            session.messages.append(entry)
        session.updated_at = datetime.now()

    async def _consolidate_memory(self, session, archive_all: bool = False) -> bool:
        """Delegate to MemoryStore.consolidate(). Returns True on success."""
        return await MemoryStore(self.workspace).consolidate(
            session, self.provider, self.model,
            archive_all=archive_all, memory_window=self.memory_window,
        )

    async def process_direct(
        self,
        content: str,
        session_key: str = "cli:direct",
        channel: str = "cli",
        chat_id: str = "direct",
        on_progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> str:
        """Process a message directly (for CLI or cron usage)."""
        await self._connect_mcp()
        msg = InboundMessage(channel=channel, sender_id="user", chat_id=chat_id, content=content)
        response = await self._process_message(msg, session_key=session_key, on_progress=on_progress)
        return response.content if response else ""
