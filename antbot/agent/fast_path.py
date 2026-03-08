"""Fast-path dispatcher: bypass the LLM for simple, read-only tool calls.

When a user message maps unambiguously to a single tool call (e.g. "list files
in ~/Downloads", "git status", "show running containers"), we execute the tool
directly and return the result — no LLM round-trip, no context building.

Safety rule: only read-only operations are fast-pathed.  Any message containing
"write intent" keywords (delete, move, rename, create, …) falls through to the
LLM so it can reason about the request.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass
class FastPathMatch:
    """Result of a successful fast-path match."""

    tool_name: str
    arguments: dict[str, Any]
    format_hint: str = "raw"  # "table", "list", "raw"


# ---------------------------------------------------------------------------
# Path extraction helpers
# ---------------------------------------------------------------------------

_PATH_RE = re.compile(r"""(?:~[\\/][\w./ \\-]*|/[\w./ \\-]+)""")


def _extract_path(message: str, workspace: str) -> str:
    """Extract the first filesystem path from the message, defaulting to workspace."""
    for m in _PATH_RE.finditer(message):
        candidate = m.group(0).rstrip(".,;:!?)")
        if len(candidate) > 2:
            return candidate
    return workspace


def _extract_port(message: str) -> str | None:
    """Extract a port number from the message."""
    m = re.search(r"\b(\d{2,5})\b", message)
    return m.group(1) if m else None


def _extract_process_name(message: str) -> str:
    """Extract a process/service name from the message."""
    # "is nginx running?" → "nginx"
    m = re.search(r"(?:is|check)\s+(\w+)\s+running", message, re.I)
    if m:
        return m.group(1)
    # "show <name> process"
    m = re.search(r"(?:show|check)\s+(\w+)\s+(?:process|service)", message, re.I)
    if m:
        return m.group(1)
    return ""


def _extract_container(message: str) -> str:
    """Extract a container name from the message."""
    m = re.search(r"(?:logs?\s+(?:for\s+|of\s+)?|container\s+)([a-zA-Z0-9_.-]+)", message, re.I)
    return m.group(1) if m else ""


def _extract_extension(message: str) -> str:
    """Extract a file extension from the message (e.g. 'PDF', '.py')."""
    m = re.search(r"\.(\w{1,6})\b", message)
    if m:
        return m.group(1)
    # "find PDF files" → "pdf"
    m = re.search(r"\b(pdf|py|js|ts|json|yaml|yml|md|txt|csv|log|html|css|sh|rb|go|rs|java|c|cpp|h)\b", message, re.I)
    return m.group(1).lower() if m else ""


# ---------------------------------------------------------------------------
# Write-intent gate  (if ANY of these match → skip fast-path)
# ---------------------------------------------------------------------------

_WRITE_INTENT_RE = re.compile(
    r"\b(delete|remove|move|rename|sort|organiz|creat|change|modify|edit|"
    r"update|install|uninstall|write|overwrite|replace|fix|refactor|"
    r"add|append|insert|patch|revert|reset|undo|clean\s+up|purge)\b",
    re.IGNORECASE,
)

# Exception: "clean up" triggers for space_ant scan (read-only)
_SPACE_CLEAN_RE = re.compile(
    r"\b(clean\s*up\s*(?:space|disk|storage)|free\s*(?:up\s*)?(?:space|disk|storage))\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Pattern table:  (compiled_regex, handler_function)
# ---------------------------------------------------------------------------

PatternHandler = Callable[[re.Match, str, str], FastPathMatch | None]


def _h_list_files(m: re.Match, msg: str, ws: str) -> FastPathMatch:
    return FastPathMatch(
        tool_name="list_dir",
        arguments={"path": _extract_path(msg, ws)},
        format_hint="list",
    )


def _h_find_files(m: re.Match, msg: str, ws: str) -> FastPathMatch:
    ext = _extract_extension(msg)
    path = _extract_path(msg, ws)
    cmd = f"find {path} -maxdepth 4 -name '*.{ext}' 2>/dev/null | head -40" if ext else f"find {path} -maxdepth 3 -type f 2>/dev/null | head -40"
    return FastPathMatch(
        tool_name="exec",
        arguments={"command": cmd},
        format_hint="list",
    )


def _h_git_status(m: re.Match, msg: str, ws: str) -> FastPathMatch:
    return FastPathMatch(
        tool_name="git",
        arguments={"action": "status"},
        format_hint="raw",
    )


def _h_git_log(m: re.Match, msg: str, ws: str) -> FastPathMatch:
    return FastPathMatch(
        tool_name="git",
        arguments={"action": "log"},
        format_hint="raw",
    )


def _h_git_diff(m: re.Match, msg: str, ws: str) -> FastPathMatch:
    return FastPathMatch(
        tool_name="git",
        arguments={"action": "diff"},
        format_hint="raw",
    )


def _h_git_branch(m: re.Match, msg: str, ws: str) -> FastPathMatch:
    return FastPathMatch(
        tool_name="git",
        arguments={"action": "branch"},
        format_hint="raw",
    )


def _h_docker_ps(m: re.Match, msg: str, ws: str) -> FastPathMatch:
    return FastPathMatch(
        tool_name="docker",
        arguments={"action": "ps"},
        format_hint="table",
    )


def _h_docker_logs(m: re.Match, msg: str, ws: str) -> FastPathMatch:
    container = _extract_container(msg)
    if not container:
        return None
    return FastPathMatch(
        tool_name="docker",
        arguments={"action": "logs", "container": container},
        format_hint="raw",
    )


def _h_ports(m: re.Match, msg: str, ws: str) -> FastPathMatch:
    return FastPathMatch(
        tool_name="process",
        arguments={"action": "ports"},
        format_hint="table",
    )


def _h_port_check(m: re.Match, msg: str, ws: str) -> FastPathMatch:
    port = _extract_port(msg)
    if not port:
        return FastPathMatch(
            tool_name="process",
            arguments={"action": "ports"},
            format_hint="table",
        )
    return FastPathMatch(
        tool_name="exec",
        arguments={"command": f"lsof -iTCP:{port} -sTCP:LISTEN -P -n 2>/dev/null || ss -tlnp 'sport = :{port}' 2>/dev/null"},
        format_hint="raw",
    )


def _h_process_check(m: re.Match, msg: str, ws: str) -> FastPathMatch:
    name = _extract_process_name(msg)
    if not name:
        return None
    return FastPathMatch(
        tool_name="process",
        arguments={"action": "check", "name": name},
        format_hint="raw",
    )


def _h_disk_usage(m: re.Match, msg: str, ws: str) -> FastPathMatch:
    path = _extract_path(msg, ws)
    return FastPathMatch(
        tool_name="exec",
        arguments={"command": f"du -sh {path} 2>/dev/null"},
        format_hint="raw",
    )


def _h_system_info(m: re.Match, msg: str, ws: str) -> FastPathMatch:
    return FastPathMatch(
        tool_name="exec",
        arguments={"command": "uname -a && echo '---' && sysctl -n hw.memsize 2>/dev/null || free -h 2>/dev/null"},
        format_hint="raw",
    )


def _h_uptime(m: re.Match, msg: str, ws: str) -> FastPathMatch:
    return FastPathMatch(
        tool_name="exec",
        arguments={"command": "uptime"},
        format_hint="raw",
    )


def _h_space_ant(m: re.Match, msg: str, ws: str) -> FastPathMatch:
    return FastPathMatch(
        tool_name="space_ant",
        arguments={"action": "scan"},
        format_hint="raw",
    )


# Order matters: more specific patterns first.
_PATTERNS: list[tuple[re.Pattern, PatternHandler]] = [
    # Space-ant / disk analysis
    (re.compile(r"\b(space.?ant|check\s+disk\s*space|what.s\s+eating\s+my\s+disk|disk\s+waste|scan\s+(?:for\s+)?(?:disk|space|waste))\b", re.I), _h_space_ant),
    (re.compile(r"\b(clean\s*up\s*(?:space|disk|storage)|free\s*(?:up\s*)?(?:space|disk|storage))\b", re.I), _h_space_ant),

    # Git (specific before generic)
    (re.compile(r"\bgit\s+diff\b|what\s+changed\b|\bshow\s+(?:the\s+)?diff\b", re.I), _h_git_diff),
    (re.compile(r"\bgit\s+log\b|\brecent\s+commits?\b|\bcommit\s+histor", re.I), _h_git_log),
    (re.compile(r"\bgit\s+branch\b|\bshow\s+branches\b|\blist\s+branches\b", re.I), _h_git_branch),
    (re.compile(r"\bgit\s+status\b|\bstatus\s+of\s+(?:the\s+)?repo\b", re.I), _h_git_status),

    # Docker
    (re.compile(r"\bdocker\s+logs?\b|\blogs?\s+(?:for|of)\s+\w+\s+container\b", re.I), _h_docker_logs),
    (re.compile(r"\bdocker\s+ps\b|\brunning\s+containers?\b|\bshow\s+containers?\b|\blist\s+containers?\b", re.I), _h_docker_ps),

    # Process / ports (specific port check before generic)
    (re.compile(r"\bwhat.s\s+(?:on|using)\s+port\b|\bport\s+\d{2,5}\b|\bwho.s\s+(?:on|using)\s+port\b", re.I), _h_port_check),
    (re.compile(r"\blistening\s+ports?\b|\bshow\s+ports?\b|\bopen\s+ports?\b", re.I), _h_ports),
    (re.compile(r"\bis\s+\w+\s+running\b|\bcheck\s+\w+\s+(?:process|service)\b", re.I), _h_process_check),

    # Disk usage (before generic file listing)
    (re.compile(r"\b(?:disk|size|how\s+big)\b.*\b(?:usage|of|is)\b|\bdu\s", re.I), _h_disk_usage),

    # File finding (before listing — "find" is more specific)
    (re.compile(r"\bfind\s+(?:\S+\s+)?files?\b|\bsearch\s+(?:for\s+)?files?\b|\bshow\s+(?:all\s+)?\.?\w+\s+files?\b", re.I), _h_find_files),

    # File listing (most generic — last among file ops)
    (re.compile(r"\b(?:list|show|ls|what.s\s+in)\b.*\b(?:files?|dir|director|folder|contents?)\b|\bls\s+[~/]|\blist\s+files?\b|\bwhat.s\s+in\s+[~/]", re.I), _h_list_files),

    # System info
    (re.compile(r"\buptime\b", re.I), _h_uptime),
    (re.compile(r"\b(?:how\s+much\s+RAM|system\s+info|what\s+OS|cpu\s+info)\b", re.I), _h_system_info),
]


class FastPathRouter:
    """Pattern-matching router that intercepts simple, read-only requests."""

    def try_match(self, message: str, workspace: str) -> FastPathMatch | None:
        """Try to match a user message to a direct tool call.

        Returns a FastPathMatch if the message maps cleanly to a single
        read-only tool call, or None to fall through to the LLM.
        """
        text = message.strip()
        if not text or len(text) > 300:
            return None  # too long → probably needs LLM reasoning

        # Write-intent gate: skip fast-path for anything that looks mutative
        if _WRITE_INTENT_RE.search(text) and not _SPACE_CLEAN_RE.search(text):
            return None

        for pattern, handler in _PATTERNS:
            m = pattern.search(text)
            if m:
                result = handler(m, text, workspace)
                if result is not None:
                    return result

        return None
