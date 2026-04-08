"""Event schema for AntBot structured logging."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone


@dataclass
class AntBotEvent:
    """Single event in the AntBot event log."""

    event: str  # e.g. "fs.create", "file.moved", "rule.matched", "health.ping"
    ts: str = ""  # ISO-8601 UTC, auto-filled if empty
    src: str = ""
    dst: str = ""
    rule: str = ""
    action: str = ""  # "move" | "copy" | "log" | "ask" | "skip"
    dry_run: bool = False
    ok: bool = True
    error: str = ""
    size_bytes: int = 0
    mime_type: str = ""
    hostname: str = ""
    meta: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.ts:
            self.ts = datetime.now(timezone.utc).isoformat()

    def to_json(self) -> str:
        """Serialize to a single JSON line."""
        return json.dumps(asdict(self), ensure_ascii=False, default=str)

    @classmethod
    def from_json(cls, line: str) -> AntBotEvent:
        """Deserialize from a JSON line."""
        return cls(**json.loads(line))
