"""ReAct prompt template for text-based tool calling.

Used when the model doesn't support native OpenAI function calling (e.g. Gemma 3).
Optimized for minimal token usage — every token costs inference time on local models.
"""

from __future__ import annotations

from typing import Any


REACT_SYSTEM_PROMPT = """\
You have tools. To use one, respond with EXACTLY:

Action: <tool_name>
Action Input: <JSON arguments>

The result appears as:
Observation: <result>

When done, respond with:
Final Answer: <your response>

Rules: Action Input must be valid JSON. Only use tools listed below. Do not combine Action and Final Answer.

Available tools:
{tool_descriptions}"""


def format_tool_descriptions(tool_definitions: list[dict[str, Any]]) -> str:
    """Format tool definitions as compact one-liners.

    Example output:
        exec(command*) — Run a shell command.
        list_dir(path*) — List directory contents.
    """
    lines: list[str] = []
    for tool_def in tool_definitions:
        func = tool_def.get("function", tool_def)
        name = func.get("name", "unknown")
        desc = func.get("description", "No description")
        params = func.get("parameters", {})
        props = params.get("properties", {})
        required = set(params.get("required", []))

        # Build compact param signature: name* for required, name for optional
        param_parts = []
        for pname in props:
            param_parts.append(f"{pname}*" if pname in required else pname)
        sig = ", ".join(param_parts)

        lines.append(f"- {name}({sig}) — {desc}")
    return "\n".join(lines)


def build_react_system_message(tool_definitions: list[dict[str, Any]]) -> str:
    """Build the complete ReAct system message with tool descriptions.

    Kept minimal to reduce token count for faster local model inference.
    """
    tool_text = format_tool_descriptions(tool_definitions)
    return REACT_SYSTEM_PROMPT.format(tool_descriptions=tool_text)
