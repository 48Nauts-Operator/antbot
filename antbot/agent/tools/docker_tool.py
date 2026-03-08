"""Docker inspection tool (read-only)."""

import asyncio
import json
from typing import Any

from antbot.agent.tools.base import Tool


class DockerTool(Tool):
    """Inspect Docker containers — ps, logs, inspect, stats. All read-only."""

    @property
    def name(self) -> str:
        return "docker"

    @property
    def description(self) -> str:
        return (
            "Inspect Docker containers (read-only). "
            "Actions: ps (list), logs (tail), inspect (config), stats (resource usage)."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["ps", "logs", "inspect", "stats"],
                    "description": "Action to perform",
                },
                "container": {
                    "type": "string",
                    "description": "Container name or ID (required for logs/inspect/stats)",
                },
                "tail": {
                    "type": "integer",
                    "description": "Number of log lines to tail (default 50, max 500)",
                    "minimum": 1,
                    "maximum": 500,
                },
            },
            "required": ["action"],
        }

    @property
    def category(self) -> str:
        return "devops"

    async def execute(self, action: str, container: str | None = None, tail: int = 50, **kwargs: Any) -> str:
        if action == "ps":
            return await self._run("docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}\t{{.Image}}'")

        if not container:
            return "Error: 'container' parameter is required for this action."

        if action == "logs":
            n = min(max(tail, 1), 500)
            return await self._run(f"docker logs --tail {n} {container}")

        if action == "inspect":
            result = await self._run(f"docker inspect {container}")
            # Parse and extract key fields for readability
            try:
                data = json.loads(result)
                if isinstance(data, list) and data:
                    c = data[0]
                    summary = {
                        "Name": c.get("Name"),
                        "Image": c.get("Config", {}).get("Image"),
                        "Status": c.get("State", {}).get("Status"),
                        "Created": c.get("Created"),
                        "Env": c.get("Config", {}).get("Env", [])[:20],
                        "Mounts": [
                            {"Source": m.get("Source"), "Destination": m.get("Destination")}
                            for m in c.get("Mounts", [])
                        ],
                        "Networks": list(c.get("NetworkSettings", {}).get("Networks", {}).keys()),
                    }
                    return json.dumps(summary, indent=2, ensure_ascii=False)
            except (json.JSONDecodeError, KeyError, IndexError):
                pass
            return result

        if action == "stats":
            return await self._run(
                f"docker stats {container} --no-stream "
                "--format 'CPU: {{.CPUPerc}}  MEM: {{.MemUsage}} ({{.MemPerc}})  NET: {{.NetIO}}  BLOCK: {{.BlockIO}}'"
            )

        return f"Error: Unknown action '{action}'"

    @staticmethod
    async def _run(cmd: str) -> str:
        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
            out = stdout.decode("utf-8", errors="replace")
            if proc.returncode != 0:
                err = stderr.decode("utf-8", errors="replace")
                return f"Error (exit {proc.returncode}): {err.strip() or out.strip()}"
            return out.strip() or "(no output)"
        except asyncio.TimeoutError:
            return "Error: Command timed out"
        except FileNotFoundError:
            return "Error: docker command not found. Is Docker installed?"
