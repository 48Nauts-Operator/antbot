"""Tool-calling strategy: native (OpenAI function calling) vs ReAct (text-based).

NativeToolStrategy is a no-op passthrough — zero change to existing behavior.
ReactToolStrategy injects a ReAct prompt and parses Thought/Action/Observation
from the model's plain-text output.
"""

from __future__ import annotations

import json
import re
import uuid
from abc import ABC, abstractmethod
from typing import Any

from loguru import logger

from antbot.agent.tools.react_prompt import build_react_system_message
from antbot.providers.base import LLMResponse, ToolCallRequest
from antbot.utils.json_repair import repair_json


# ---------------------------------------------------------------------------
# Strategy interface
# ---------------------------------------------------------------------------

class ToolStrategy(ABC):
    """Abstract interface for tool-calling strategies."""

    @abstractmethod
    def prepare_request(
        self,
        messages: list[dict[str, Any]],
        tool_definitions: list[dict[str, Any]] | None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]] | None]:
        """Prepare messages and tools for the provider call.

        Returns:
            (modified_messages, tools_param) — tools_param may be None
            if the strategy embeds tool info in the prompt instead.
        """

    @abstractmethod
    def parse_response(self, response: LLMResponse) -> LLMResponse:
        """Post-process the provider response, extracting tool calls if needed."""

    @abstractmethod
    def format_tool_result(self, tool_call_id: str, tool_name: str, result: str) -> dict[str, Any]:
        """Format a tool result message for the conversation history."""


# ---------------------------------------------------------------------------
# Native strategy (passthrough)
# ---------------------------------------------------------------------------

class NativeToolStrategy(ToolStrategy):
    """Pass-through strategy for models with native function calling."""

    def prepare_request(self, messages, tool_definitions):
        return messages, tool_definitions

    def parse_response(self, response):
        return response

    def format_tool_result(self, tool_call_id, tool_name, result):
        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": tool_name,
            "content": result,
        }


# ---------------------------------------------------------------------------
# ReAct strategy (text-based)
# ---------------------------------------------------------------------------

# Regex patterns for parsing ReAct output
_RE_ACTION = re.compile(
    r"Action\s*:\s*(.+?)(?:\n|$)",
    re.IGNORECASE,
)
_RE_ACTION_INPUT = re.compile(
    r"Action\s+Input\s*:\s*(.+)",
    re.IGNORECASE | re.DOTALL,
)
_RE_FINAL_ANSWER = re.compile(
    r"Final\s+Answer\s*:\s*(.+)",
    re.IGNORECASE | re.DOTALL,
)
# Hermes-style XML tool calls
_RE_HERMES_TOOL = re.compile(
    r"<tool_call>\s*(\{[\s\S]*?\})\s*</tool_call>",
    re.IGNORECASE,
)
# Gemma-style [TOOL_REQUEST] tags
_RE_TOOL_REQUEST = re.compile(
    r"\[TOOL_REQUEST\]\s*(\{[\s\S]*?\})\s*\[END_TOOL_REQUEST\]",
    re.IGNORECASE,
)


def parse_react_response(text: str) -> tuple[list[ToolCallRequest], str | None]:
    """Parse a ReAct-formatted text response into tool calls and/or final answer.

    Supports two formats:
    1. Standard ReAct: ``Action: tool_name\\nAction Input: {"key": "val"}``
    2. Hermes XML: ``<tool_call>{"name": "...", "arguments": {...}}</tool_call>``

    Returns:
        (tool_calls, final_answer) — one of them will be non-empty/non-None.
    """
    if not text:
        return [], None

    # Check for structured tool-call formats first (Hermes XML, Gemma [TOOL_REQUEST])
    structured_matches = _RE_HERMES_TOOL.findall(text) or _RE_TOOL_REQUEST.findall(text)
    if structured_matches:
        tool_calls = []
        for raw_json in structured_matches:
            try:
                parsed = repair_json(raw_json)
                if isinstance(parsed, dict) and "name" in parsed:
                    tool_calls.append(ToolCallRequest(
                        id=f"react_{uuid.uuid4().hex[:8]}",
                        name=parsed["name"],
                        arguments=parsed.get("arguments", {}),
                    ))
            except (ValueError, TypeError):
                logger.warning("Failed to parse structured tool call: {}", raw_json[:200])
        if tool_calls:
            return tool_calls, None

    # Check for Final Answer
    fa_match = _RE_FINAL_ANSWER.search(text)
    action_match = _RE_ACTION.search(text)

    # If both exist, check which comes first
    if fa_match and action_match:
        if fa_match.start() < action_match.start():
            # Trim final answer to stop before the Action line
            fa_text = text[fa_match.start() + len(fa_match.group(0).split("\n")[0].split(":", 1)[0]) + 1:action_match.start()].strip()
            if not fa_text:
                fa_text = fa_match.group(1).split("\n")[0].strip()
            return [], fa_text
    elif fa_match and not action_match:
        return [], fa_match.group(1).strip()

    # Parse standard ReAct Action/Action Input
    if action_match:
        tool_name = action_match.group(1).strip()
        # Find Action Input after the Action line
        remaining = text[action_match.end():]
        input_match = _RE_ACTION_INPUT.search(remaining)

        arguments: dict[str, Any] = {}
        if input_match:
            raw_input = input_match.group(1).strip()
            # If it doesn't start with { or [, treat as plain text
            if not raw_input.startswith(("{", "[")):
                arguments = {"input": raw_input}
            else:
                # Try to parse as JSON, repairing if needed
                try:
                    arguments = repair_json(raw_input)
                    if not isinstance(arguments, dict):
                        arguments = {}
                except (ValueError, TypeError):
                    logger.warning("Failed to parse Action Input as JSON: {}", raw_input[:200])
                    arguments = {"input": raw_input}

        return [ToolCallRequest(
            id=f"react_{uuid.uuid4().hex[:8]}",
            name=tool_name,
            arguments=arguments,
        )], None

    # No action or final answer found — treat entire text as final answer
    return [], text.strip() or None


class ReactToolStrategy(ToolStrategy):
    """Text-based ReAct strategy for models without native function calling."""

    def __init__(self) -> None:
        self._tool_definitions: list[dict[str, Any]] = []

    def prepare_request(self, messages, tool_definitions):
        self._tool_definitions = tool_definitions or []
        if not self._tool_definitions:
            return messages, None

        react_prompt = build_react_system_message(self._tool_definitions)

        modified = list(messages)
        # Inject ReAct instructions into the system message
        if modified and modified[0].get("role") == "system":
            modified[0] = {
                **modified[0],
                "content": modified[0]["content"] + "\n\n" + react_prompt,
            }
        else:
            modified.insert(0, {"role": "system", "content": react_prompt})

        # Don't send tools via the API — they're in the prompt now
        return modified, None

    def parse_response(self, response):
        if response.has_tool_calls:
            # Model somehow produced native tool calls — use them
            return response

        if not response.content:
            return response

        tool_calls, final_answer = parse_react_response(response.content)

        if tool_calls:
            # Extract the Thought text (everything before the Action line)
            thought = None
            if response.content:
                thought_match = re.match(
                    r"(?:Thought\s*:\s*)?(.+?)(?=\n\s*Action\s*:)",
                    response.content,
                    re.DOTALL | re.IGNORECASE,
                )
                if thought_match:
                    thought = thought_match.group(1).strip()
                    # Clean "Thought:" prefix if present
                    if thought.lower().startswith("thought:"):
                        thought = thought[len("thought:"):].strip()

            return LLMResponse(
                content=thought,
                tool_calls=tool_calls,
                finish_reason="tool_calls",
                usage=response.usage,
            )

        if final_answer:
            return LLMResponse(
                content=final_answer,
                tool_calls=[],
                finish_reason="stop",
                usage=response.usage,
            )

        return response

    _MAX_OBSERVATION_CHARS = 2000  # Truncate to keep context small for faster inference

    def format_tool_result(self, tool_call_id, tool_name, result):
        # In ReAct mode, tool results come back as "Observation:" in a user message
        # Truncate aggressively to keep context small for local model speed
        text = result
        if len(text) > self._MAX_OBSERVATION_CHARS:
            text = text[:self._MAX_OBSERVATION_CHARS] + "\n... (truncated)"
        return {
            "role": "user",
            "content": f"Observation: {text}",
        }


# ---------------------------------------------------------------------------
# Smart tool selection
# ---------------------------------------------------------------------------

_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "filesystem": [
        "file", "read", "write", "edit", "create", "delete", "directory",
        "folder", "path", "list", "tree", "content", "save", "open",
    ],
    "shell": [
        "run", "execute", "command", "shell", "terminal", "bash", "script",
        "install", "build", "compile", "make", "npm", "pip", "python",
    ],
    "web": [
        "search", "web", "url", "fetch", "http", "api", "website",
        "google", "browse", "download", "internet", "online",
    ],
    "scheduling": [
        "schedule", "cron", "timer", "recurring", "periodic", "every",
        "daily", "hourly", "weekly", "remind",
    ],
    "communication": [
        "message", "send", "notify", "reply", "respond", "tell",
        "chat", "email", "slack",
    ],
    "devops": [
        "docker", "container", "image", "kubernetes", "k8s",
        "git", "commit", "branch", "merge", "diff", "repo",
        "process", "pid", "port", "service", "daemon",
        "curl", "request", "endpoint", "rest", "api",
        "deploy", "ci", "cd", "pipeline",
    ],
}

# Tools that are always included regardless of scoring
_CORE_TOOLS = {"read_file", "exec"}


def select_tools_for_message(
    message: str,
    tool_definitions: list[dict[str, Any]],
    tool_categories: dict[str, str],
    max_tools: int,
) -> list[dict[str, Any]]:
    """Select the most relevant tools for a given user message.

    Args:
        message: The user's message text.
        tool_definitions: All available tool definitions (OpenAI format).
        tool_categories: Mapping of tool_name -> category.
        max_tools: Maximum number of tools to return.

    Returns:
        Filtered list of tool definitions, always including core tools.
    """
    if max_tools <= 0 or len(tool_definitions) <= max_tools:
        return tool_definitions

    msg_lower = message.lower()

    # Score each category by keyword matches
    category_scores: dict[str, int] = {}
    for category, keywords in _CATEGORY_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in msg_lower)
        if score > 0:
            category_scores[category] = score

    # Score each tool
    tool_scores: dict[str, float] = {}
    for tool_def in tool_definitions:
        name = tool_def.get("function", tool_def).get("name", "")
        category = tool_categories.get(name, "general")

        if name in _CORE_TOOLS:
            tool_scores[name] = 1000  # Always include
        elif category in category_scores:
            tool_scores[name] = category_scores[category]
        else:
            tool_scores[name] = 0

    # Sort by score descending, take top max_tools
    sorted_tools = sorted(
        tool_definitions,
        key=lambda td: tool_scores.get(
            td.get("function", td).get("name", ""), 0
        ),
        reverse=True,
    )
    return sorted_tools[:max_tools]
