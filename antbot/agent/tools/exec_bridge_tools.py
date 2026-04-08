"""Tools for the antbot-exec Go binary (file move, copy, health)."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from antbot.agent.tools.base import Tool

if TYPE_CHECKING:
    from antbot.exec_bridge.manager import ExecBridgeManager


class ExecHealthTool(Tool):
    """Check the health of the antbot-exec Go binary."""

    def __init__(self, manager: ExecBridgeManager) -> None:
        self._manager = manager

    @property
    def name(self) -> str:
        return "exec_health"

    @property
    def description(self) -> str:
        return "Check antbot-exec Go binary health status (version, uptime)."

    @property
    def category(self) -> str:
        return "devops"

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}

    async def execute(self, **kwargs: Any) -> str:
        try:
            client = await self._manager.ensure_connected()
            result = await client.ping()
            return f"antbot-exec: ok={result['ok']} version={result['version']} uptime={result['uptime_s']:.1f}s"
        except Exception as e:
            return f"antbot-exec: unreachable — {e}"


class ExecMoveTool(Tool):
    """Move a file via the antbot-exec Go binary (with checksum verification)."""

    def __init__(self, manager: ExecBridgeManager, global_dry_run: bool = True) -> None:
        self._manager = manager
        self._global_dry_run = global_dry_run

    @property
    def name(self) -> str:
        return "file_move"

    @property
    def description(self) -> str:
        return "Move a file from source to destination via antbot-exec. Verifies checksum. Fails if destination exists."

    @property
    def category(self) -> str:
        return "filesystem"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "src": {"type": "string", "description": "Source file path"},
                "dst": {"type": "string", "description": "Destination file path"},
                "dry_run": {"type": "boolean", "description": "Preview without executing (default: true)"},
            },
            "required": ["src", "dst"],
        }

    async def execute(self, **kwargs: Any) -> str:
        src = kwargs["src"]
        dst = kwargs["dst"]
        dry_run = kwargs.get("dry_run", True) or self._global_dry_run

        try:
            client = await self._manager.ensure_connected()
            result = await client.move(src, dst, dry_run=dry_run)
            if result["ok"]:
                prefix = "[DRY RUN] " if result.get("was_dry_run") else ""
                return f"{prefix}Moved {result['src']} → {result['dst']} ({result['size_bytes']} bytes)"
            return f"Move failed: {result['error']}"
        except Exception as e:
            return f"Move failed: {e}"


class ExecCopyTool(Tool):
    """Copy a file via the antbot-exec Go binary (with checksum verification)."""

    def __init__(self, manager: ExecBridgeManager, global_dry_run: bool = True) -> None:
        self._manager = manager
        self._global_dry_run = global_dry_run

    @property
    def name(self) -> str:
        return "file_copy"

    @property
    def description(self) -> str:
        return "Copy a file from source to destination via antbot-exec. Verifies checksum. Fails if destination exists."

    @property
    def category(self) -> str:
        return "filesystem"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "src": {"type": "string", "description": "Source file path"},
                "dst": {"type": "string", "description": "Destination file path"},
                "dry_run": {"type": "boolean", "description": "Preview without executing (default: true)"},
            },
            "required": ["src", "dst"],
        }

    async def execute(self, **kwargs: Any) -> str:
        src = kwargs["src"]
        dst = kwargs["dst"]
        dry_run = kwargs.get("dry_run", True) or self._global_dry_run

        try:
            client = await self._manager.ensure_connected()
            result = await client.copy(src, dst, dry_run=dry_run)
            if result["ok"]:
                prefix = "[DRY RUN] " if result.get("was_dry_run") else ""
                return f"{prefix}Copied {result['src']} → {result['dst']} ({result['size_bytes']} bytes)"
            return f"Copy failed: {result['error']}"
        except Exception as e:
            return f"Copy failed: {e}"
