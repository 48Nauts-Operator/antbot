"""Tool registry for dynamic tool management with Guard integration."""

from typing import Any, Callable

from loguru import logger

from antbot.agent.guard import GuardResult, RiskLevel, review_tool_call, review_tool_result
from antbot.agent.tools.base import Tool


class ToolRegistry:
    """
    Registry for agent tools with integrated safety guard.

    Allows dynamic registration and execution of tools.
    The Guard reviews tool calls before execution and checks
    results for sensitive data leakage.
    """

    def __init__(self, guard_enabled: bool = True):
        self._tools: dict[str, Tool] = {}
        self.guard_enabled = guard_enabled
        self._on_guard_warning: Callable[[GuardResult], None] | None = None

    def register(self, tool: Tool) -> None:
        """Register a tool."""
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        """Unregister a tool by name."""
        self._tools.pop(name, None)

    def get(self, name: str) -> Tool | None:
        """Get a tool by name."""
        return self._tools.get(name)

    def has(self, name: str) -> bool:
        """Check if a tool is registered."""
        return name in self._tools

    def get_definitions(self) -> list[dict[str, Any]]:
        """Get all tool definitions in OpenAI format."""
        return [tool.to_schema() for tool in self._tools.values()]

    async def execute(self, name: str, params: dict[str, Any]) -> str:
        """Execute a tool by name with given parameters.

        Includes Guard review: dangerous operations are blocked with a warning,
        and tool results are checked for sensitive data exposure.
        """
        _HINT = "\n\n[Analyze the error above and try a different approach.]"

        tool = self._tools.get(name)
        if not tool:
            return f"Error: Tool '{name}' not found. Available: {', '.join(self.tool_names)}"

        # Guard: review tool call before execution
        if self.guard_enabled:
            guard_result = review_tool_call(name, params)
            if guard_result.is_blocked:
                logger.warning("Guard BLOCKED: {} — {}", name, guard_result.reason)
                return f"⛔ Blocked: {guard_result.reason}. This operation is not allowed."
            if guard_result.needs_confirmation:
                logger.warning("Guard DANGEROUS: {} — {}", name, guard_result.reason)
                return (
                    f"⚠️ Dangerous operation detected: {guard_result.reason}\n"
                    f"Tool: {name}\n"
                    f"Please confirm you want to proceed by repeating the request."
                )
            if guard_result.risk == RiskLevel.CAUTION:
                logger.info("Guard CAUTION: {} — {}", name, guard_result.reason)

        try:
            # Attempt to cast parameters to match schema types
            params = tool.cast_params(params)

            # Validate parameters
            errors = tool.validate_params(params)
            if errors:
                return f"Error: Invalid parameters for tool '{name}': " + "; ".join(errors) + _HINT
            result = await tool.execute(**params)

            # Guard: check result for sensitive data
            if self.guard_enabled and isinstance(result, str):
                result_guard = review_tool_result(name, result)
                if result_guard.risk != RiskLevel.SAFE:
                    logger.warning("Guard: sensitive data in {} output — {}", name, result_guard.reason)

            if isinstance(result, str) and result.startswith("Error"):
                return result + _HINT
            return result
        except Exception as e:
            return f"Error executing {name}: {str(e)}" + _HINT

    @property
    def tool_names(self) -> list[str]:
        """Get list of registered tool names."""
        return list(self._tools.keys())

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools
