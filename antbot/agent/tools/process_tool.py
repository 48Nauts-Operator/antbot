"""Process inspection tool (read-only)."""

import asyncio
from typing import Any

from antbot.agent.tools.base import Tool


class ProcessTool(Tool):
    """Inspect running processes and listening ports."""

    @property
    def name(self) -> str:
        return "process"

    @property
    def description(self) -> str:
        return (
            "Inspect running processes (read-only). "
            "Actions: list (filter by name), ports (listening ports), check (is process running?)."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "ports", "check"],
                    "description": "Action to perform",
                },
                "name": {
                    "type": "string",
                    "description": "Process name to filter by (for list/check)",
                },
            },
            "required": ["action"],
        }

    @property
    def category(self) -> str:
        return "devops"

    async def execute(self, action: str, name: str = "", **kwargs: Any) -> str:
        if action == "list":
            if name:
                cmd = f"ps aux | head -1; ps aux | grep -i '{name}' | grep -v grep"
            else:
                cmd = "ps aux --sort=-%mem | head -20"
            return await self._run(cmd)

        if action == "ports":
            # Try lsof first (macOS/Linux), fallback to ss
            result = await self._run("lsof -iTCP -sTCP:LISTEN -P -n 2>/dev/null || ss -tlnp 2>/dev/null")
            return result

        if action == "check":
            if not name:
                return "Error: 'name' parameter is required for check action."
            result = await self._run(f"pgrep -la '{name}'")
            if result.startswith("Error") or result == "(no output)":
                return f"Process '{name}' is NOT running."
            return f"Process '{name}' IS running:\n{result}"

        return f"Error: Unknown action '{action}'"

    @staticmethod
    async def _run(cmd: str) -> str:
        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
            out = stdout.decode("utf-8", errors="replace").strip()
            return out or "(no output)"
        except asyncio.TimeoutError:
            return "Error: Command timed out"
        except Exception as e:
            return f"Error: {e}"
