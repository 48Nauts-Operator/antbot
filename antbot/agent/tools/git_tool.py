"""Git inspection tool (read-only)."""

import asyncio
from typing import Any

from antbot.agent.tools.base import Tool


class GitTool(Tool):
    """Read-only git operations — status, diff, log, branch, show."""

    def __init__(self, working_dir: str | None = None):
        self.working_dir = working_dir

    @property
    def name(self) -> str:
        return "git"

    @property
    def description(self) -> str:
        return (
            "Read-only Git operations. "
            "Actions: status, diff, log, branch, show."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["status", "diff", "log", "branch", "show"],
                    "description": "Git action to perform",
                },
                "args": {
                    "type": "string",
                    "description": "Additional arguments (e.g. file path for diff, commit hash for show)",
                },
                "max_lines": {
                    "type": "integer",
                    "description": "Max output lines (default 100)",
                    "minimum": 1,
                    "maximum": 500,
                },
            },
            "required": ["action"],
        }

    @property
    def category(self) -> str:
        return "devops"

    async def execute(self, action: str, args: str = "", max_lines: int = 100, **kwargs: Any) -> str:
        cmds = {
            "status": "git status --short",
            "diff": "git diff",
            "log": "git log --oneline -20",
            "branch": "git branch -a",
            "show": "git show --stat",
        }
        base = cmds.get(action)
        if not base:
            return f"Error: Unknown action '{action}'. Use: {', '.join(cmds)}"

        cmd = f"{base} {args}".strip() if args else base

        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.working_dir,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
            out = stdout.decode("utf-8", errors="replace")
            if proc.returncode != 0:
                err = stderr.decode("utf-8", errors="replace")
                return f"Error (exit {proc.returncode}): {err.strip() or out.strip()}"

            lines = out.strip().splitlines()
            if len(lines) > max_lines:
                out = "\n".join(lines[:max_lines]) + f"\n... ({len(lines) - max_lines} more lines)"
            return out.strip() or "(no output)"
        except asyncio.TimeoutError:
            return "Error: Git command timed out"
        except FileNotFoundError:
            return "Error: git command not found. Is Git installed?"
