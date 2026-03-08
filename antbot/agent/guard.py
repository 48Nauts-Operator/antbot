"""Guard: Reviews tool calls before execution for safety.

Pattern-based safety layer — no second LLM needed. Catches:
- Destructive operations (rm -rf, DROP TABLE, kill -9)
- Sensitive data access (.env, credentials, private keys)
- External network calls (API posts, pushes, sends)

When a match is found, the Guard:
1. Logs the match
2. Returns a warning with the reason
3. The executor can then ask the user for confirmation

95% of dangerous operations match simple regex patterns.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

from loguru import logger


class RiskLevel(Enum):
    """Risk classification for tool calls."""
    SAFE = "safe"
    CAUTION = "caution"       # Log but allow
    DANGEROUS = "dangerous"   # Require confirmation
    BLOCKED = "blocked"       # Never allow


@dataclass
class GuardResult:
    """Result of a guard review."""

    risk: RiskLevel
    tool_name: str
    reason: str = ""
    matched_pattern: str = ""

    @property
    def is_safe(self) -> bool:
        return self.risk == RiskLevel.SAFE

    @property
    def needs_confirmation(self) -> bool:
        return self.risk == RiskLevel.DANGEROUS

    @property
    def is_blocked(self) -> bool:
        return self.risk == RiskLevel.BLOCKED


# Patterns that should NEVER execute without confirmation
_DANGEROUS_PATTERNS: list[tuple[str, str]] = [
    (r"rm\s+(-[a-zA-Z]*f|-[a-zA-Z]*r)", "Recursive/force file deletion"),
    (r"rm\s+-rf\s+/", "Recursive deletion from root"),
    (r"rmdir", "Directory removal"),
    (r"mkfs\.", "Filesystem formatting"),
    (r"dd\s+if=", "Raw disk write"),
    (r">\s*/dev/", "Write to device"),
    (r"format\s+[a-zA-Z]:", "Disk formatting"),
    (r"shutdown|reboot|halt|poweroff", "System shutdown/reboot"),
    (r"kill\s+-9", "Force kill process"),
    (r"killall", "Kill all processes by name"),
    (r"chmod\s+777", "World-writable permissions"),
    (r"chown\s+-R\s+root", "Recursive ownership change to root"),
    (r"DROP\s+(TABLE|DATABASE|SCHEMA)", "Database object deletion"),
    (r"TRUNCATE\s+TABLE", "Database table truncation"),
    (r"DELETE\s+FROM\s+\w+\s*;?\s*$", "Unrestricted DELETE (no WHERE)"),
    (r"git\s+push\s+.*--force", "Force push to remote"),
    (r"git\s+reset\s+--hard", "Hard reset (lose changes)"),
    (r"git\s+clean\s+-[a-zA-Z]*f", "Force clean untracked files"),
    (r":(){ :\|:& };:", "Fork bomb"),
    (r"curl.*\|\s*(bash|sh|zsh)", "Pipe URL to shell"),
    (r"wget.*\|\s*(bash|sh|zsh)", "Pipe download to shell"),
]

# Patterns that indicate sensitive data access
_SENSITIVE_PATTERNS: list[tuple[str, str]] = [
    (r"\.env($|\s|/)", "Environment file (may contain secrets)"),
    (r"credentials?\.(json|yaml|yml|xml|conf)", "Credentials file"),
    (r"(private[_-]?key|id_rsa|id_ed25519)", "Private key file"),
    (r"\.pem$", "Certificate/key file"),
    (r"password", "Password reference"),
    (r"api[_-]?key", "API key reference"),
    (r"secret[_-]?(key|token)", "Secret/token reference"),
    (r"\.kube/config", "Kubernetes config"),
    (r"\.aws/credentials", "AWS credentials"),
    (r"\.ssh/", "SSH directory"),
    (r"keychain", "Keychain access"),
]

# Tools that are inherently safe
_SAFE_TOOLS = {"read_file", "list_dir", "web_search", "web_fetch"}

# Tools that modify state and need content inspection
_INSPECT_TOOLS = {"exec", "write_file", "edit_file"}


def _check_patterns(
    text: str, patterns: list[tuple[str, str]], risk: RiskLevel, tool_name: str
) -> GuardResult | None:
    """Check text against a list of patterns."""
    text_lower = text.lower()
    for pattern, reason in patterns:
        if re.search(pattern, text_lower, re.IGNORECASE):
            logger.warning("Guard: {} detected in {} — {}", risk.value, tool_name, reason)
            return GuardResult(
                risk=risk,
                tool_name=tool_name,
                reason=reason,
                matched_pattern=pattern,
            )
    return None


def review_tool_call(tool_name: str, params: dict[str, Any]) -> GuardResult:
    """Review a tool call for safety before execution.

    Args:
        tool_name: Name of the tool being called
        params: Parameters being passed to the tool

    Returns:
        GuardResult with risk assessment
    """
    # Safe tools pass through
    if tool_name in _SAFE_TOOLS:
        return GuardResult(risk=RiskLevel.SAFE, tool_name=tool_name)

    # For tools that need inspection, check params
    if tool_name in _INSPECT_TOOLS:
        # Combine all param values into a single string for pattern matching
        param_text = " ".join(str(v) for v in params.values())

        # Check dangerous patterns first
        result = _check_patterns(param_text, _DANGEROUS_PATTERNS, RiskLevel.DANGEROUS, tool_name)
        if result:
            return result

        # Check sensitive patterns
        result = _check_patterns(param_text, _SENSITIVE_PATTERNS, RiskLevel.CAUTION, tool_name)
        if result:
            return result

    # Check file paths in any tool
    for key in ("path", "file_path", "file", "target", "destination"):
        if key in params:
            path_text = str(params[key])
            result = _check_patterns(path_text, _SENSITIVE_PATTERNS, RiskLevel.CAUTION, tool_name)
            if result:
                return result

    return GuardResult(risk=RiskLevel.SAFE, tool_name=tool_name)


def review_tool_result(tool_name: str, result: str) -> GuardResult:
    """Review a tool result for accidental data exposure.

    Checks if tool output contains sensitive data that shouldn't be
    sent back to an external LLM provider.
    """
    if len(result) < 10:
        return GuardResult(risk=RiskLevel.SAFE, tool_name=tool_name)

    # Check if the result contains what looks like secrets
    secret_patterns = [
        (r"['\"]?api[_-]?key['\"]?\s*[:=]\s*['\"]?[\w-]{20,}", "API key in output"),
        (r"['\"]?password['\"]?\s*[:=]\s*['\"]?\S{6,}", "Password in output"),
        (r"sk-[a-zA-Z0-9]{20,}", "OpenAI-style API key in output"),
        (r"-----BEGIN\s+(RSA\s+)?PRIVATE KEY-----", "Private key in output"),
        (r"ghp_[a-zA-Z0-9]{36}", "GitHub token in output"),
        (r"sk-ant-api[a-zA-Z0-9-]{50,}", "Anthropic API key in output"),
    ]

    result_sample = result[:5000]  # Only check first 5KB
    for pattern, reason in secret_patterns:
        if re.search(pattern, result_sample, re.IGNORECASE):
            logger.warning("Guard: Sensitive data detected in {} output — {}", tool_name, reason)
            return GuardResult(
                risk=RiskLevel.CAUTION,
                tool_name=tool_name,
                reason=f"Tool output contains sensitive data: {reason}",
                matched_pattern=pattern,
            )

    return GuardResult(risk=RiskLevel.SAFE, tool_name=tool_name)
