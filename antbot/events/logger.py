"""Append-only JSONL event logger."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from antbot.events.schema import AntBotEvent


class EventLogger:
    """Append-only JSONL writer with daily file rotation."""

    def __init__(self, log_dir: Path | str, max_file_size_mb: int = 50) -> None:
        self._log_dir = Path(log_dir).expanduser()
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._max_bytes = max_file_size_mb * 1024 * 1024
        self._current_date: date | None = None
        self._current_path: Path | None = None
        self._rotation_index = 0

    def log(self, event: AntBotEvent) -> None:
        """Append event as a JSON line to the current log file."""
        path = self._get_path()
        with open(path, "a", encoding="utf-8") as f:
            f.write(event.to_json() + "\n")

    def query(
        self,
        event_type: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """Read recent events from the current log file."""
        path = self._get_path()
        if not path.exists():
            return []

        lines: list[str] = []
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        results: list[dict] = []
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event_type and entry.get("event") != event_type:
                continue
            results.append(entry)
            if len(results) >= limit:
                break
        return results

    def _get_path(self) -> Path:
        """Get current log file path, rotating by date and size."""
        today = date.today()
        if self._current_date != today:
            self._current_date = today
            self._rotation_index = 0
            self._current_path = None

        if self._current_path is None:
            self._current_path = self._log_dir / f"{today.isoformat()}.jsonl"

        # Rotate if over size limit
        if self._current_path.exists() and self._current_path.stat().st_size >= self._max_bytes:
            self._rotation_index += 1
            self._current_path = self._log_dir / f"{today.isoformat()}_{self._rotation_index:03d}.jsonl"

        return self._current_path
