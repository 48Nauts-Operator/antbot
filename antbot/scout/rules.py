"""Rule engine for file triage — matches file events to routing rules."""

from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class Rule:
    """A single file routing rule."""

    name: str
    watch: str  # directory to watch (expanded)
    target: str  # destination path template
    action: str = "move"  # "move" | "copy"
    enabled: bool = True
    confirm: bool = False  # ask via Telegram before acting
    classify: bool = False  # use LLM classification (Phase 6)
    delay: int = 30  # seconds to wait for file stability
    priority: int = 50  # higher = evaluated first
    notify: bool = True
    tags: list[str] = field(default_factory=list)

    # Match criteria
    extensions: list[str] = field(default_factory=list)
    patterns: list[str] = field(default_factory=list)
    match_type: str = ""  # "file" | "directory" | "" (any)
    min_size: int = 0
    max_size: int = 0  # 0 = unlimited
    exclude: list[str] = field(default_factory=list)

    def matches(self, path: str, size: int = 0, is_dir: bool = False) -> bool:
        """Check if a file event matches this rule."""
        if not self.enabled:
            return False

        # Type check
        if self.match_type == "file" and is_dir:
            return False
        if self.match_type == "directory" and not is_dir:
            return False

        filename = os.path.basename(path)

        # Check excludes first
        for pattern in self.exclude:
            if fnmatch.fnmatch(filename, pattern):
                return False

        # Extension match
        if self.extensions:
            ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
            if ext not in self.extensions:
                return False

        # Pattern match (any pattern in list matches)
        if self.patterns:
            if not any(fnmatch.fnmatch(filename, p) for p in self.patterns):
                return False

        # Size checks
        if self.min_size > 0 and size < self.min_size:
            return False
        if self.max_size > 0 and size > self.max_size:
            return False

        return True

    def resolve_target(self, src_path: str) -> str:
        """Resolve the target path template with variables."""
        filename = os.path.basename(src_path)

        # Get file creation time for date variables
        try:
            stat = os.stat(src_path)
            ctime = datetime.fromtimestamp(stat.st_birthtime, tz=timezone.utc)
        except (OSError, AttributeError):
            ctime = datetime.now(timezone.utc)

        import socket
        hostname = socket.gethostname().lower()

        target = self.target
        target = target.replace("{year}", str(ctime.year))
        target = target.replace("{month}", f"{ctime.month:02d}")
        target = target.replace("{day}", f"{ctime.day:02d}")
        target = target.replace("{date}", ctime.strftime("%Y-%m-%d"))
        target = target.replace("{hostname}", hostname)
        target = target.replace("{ext}", filename.rsplit(".", 1)[-1] if "." in filename else "")
        target = target.replace("{original_name}", filename)
        target = target.replace("{source_folder}", os.path.basename(os.path.dirname(src_path)))

        # Expand ~ in target
        target = os.path.expanduser(target)

        # Append filename to target if target is a directory pattern
        if not os.path.splitext(target)[1]:  # no extension = directory
            target = os.path.join(target, filename)

        return target


class RuleEngine:
    """Evaluates file events against a set of rules."""

    def __init__(self, rules: list[Rule] | None = None) -> None:
        self._rules = sorted(rules or [], key=lambda r: -r.priority)

    @property
    def rules(self) -> list[Rule]:
        return self._rules

    def add_rule(self, rule: Rule) -> None:
        self._rules.append(rule)
        self._rules.sort(key=lambda r: -r.priority)

    def match(self, path: str, size: int = 0, is_dir: bool = False) -> Rule | None:
        """Find the first matching rule for a file event."""
        for rule in self._rules:
            if rule.matches(path, size, is_dir):
                return rule
        return None

    def test(self, path: str) -> list[dict[str, Any]]:
        """Dry-run: show which rules would match a path and what the target would be."""
        results = []
        try:
            stat = os.stat(path)
            size = stat.st_size
            is_dir = os.path.isdir(path)
        except OSError:
            size = 0
            is_dir = False

        for rule in self._rules:
            if rule.matches(path, size, is_dir):
                results.append({
                    "rule": rule.name,
                    "action": rule.action,
                    "target": rule.resolve_target(path),
                    "confirm": rule.confirm,
                    "classify": rule.classify,
                    "priority": rule.priority,
                })
        return results

    @classmethod
    def from_dict_list(cls, rules_data: list[dict]) -> RuleEngine:
        """Create a RuleEngine from a list of rule dictionaries (YAML format)."""
        rules = []
        for rd in rules_data:
            match = rd.get("match", {})
            rules.append(Rule(
                name=rd["name"],
                watch=os.path.expanduser(rd.get("watch", "")),
                target=rd.get("target", ""),
                action=rd.get("action", "move"),
                enabled=rd.get("enabled", True),
                confirm=rd.get("confirm", False),
                classify=rd.get("classify", False),
                delay=_parse_duration(rd.get("delay", "30s")),
                priority=rd.get("priority", 50),
                notify=rd.get("notify", True),
                tags=rd.get("tags", []),
                extensions=match.get("extensions", []),
                patterns=match.get("patterns", []),
                match_type=match.get("type", ""),
                min_size=_parse_size(match.get("min_size", 0)),
                max_size=_parse_size(match.get("max_size", 0)),
                exclude=rd.get("exclude", []),
            ))
        return cls(rules)


def _parse_duration(val: str | int) -> int:
    """Parse a duration string like '30s', '5m', '1h' to seconds."""
    if isinstance(val, (int, float)):
        return int(val)
    val = str(val).strip().lower()
    if val.endswith("s"):
        return int(val[:-1])
    if val.endswith("m"):
        return int(val[:-1]) * 60
    if val.endswith("h"):
        return int(val[:-1]) * 3600
    try:
        return int(val)
    except ValueError:
        return 30


def _parse_size(val: str | int) -> int:
    """Parse a size string like '10MB', '1GB' to bytes."""
    if isinstance(val, (int, float)):
        return int(val)
    val = str(val).strip().upper()
    multipliers = {"KB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4}
    for suffix, mult in multipliers.items():
        if val.endswith(suffix):
            return int(float(val[:-len(suffix)]) * mult)
    try:
        return int(val)
    except ValueError:
        return 0
