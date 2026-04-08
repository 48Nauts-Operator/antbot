"""File-state tracker for idempotent operations and observability."""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class FileState(str, Enum):
    """State machine for file lifecycle."""
    DETECTED = "detected"           # watcher fired
    STABLE = "stable"               # debounce passed, file not changing
    MATCHED = "matched"             # rule matched
    AWAITING_APPROVAL = "awaiting_approval"  # confirm=true, waiting for user
    EXECUTING = "executing"         # move/copy in progress
    SUCCEEDED = "succeeded"         # action completed successfully
    FAILED = "failed"               # action failed
    QUEUED = "queued"               # NAS unreachable, queued for retry
    SKIPPED = "skipped"             # no rule match or denied


@dataclass
class TrackedFile:
    """Tracks the state of a single file through the triage pipeline."""
    path: str
    state: str = FileState.DETECTED
    rule: str = ""
    target: str = ""
    action: str = ""
    error: str = ""
    size: int = 0
    attempts: int = 0
    first_seen: float = 0.0
    last_updated: float = 0.0

    def __post_init__(self):
        now = time.time()
        if not self.first_seen:
            self.first_seen = now
        self.last_updated = now

    def transition(self, new_state: str, **kwargs) -> None:
        self.state = new_state
        self.last_updated = time.time()
        for k, v in kwargs.items():
            if hasattr(self, k):
                setattr(self, k, v)


class StateTracker:
    """Tracks all files currently in the triage pipeline."""

    def __init__(self, persist_path: str | None = None) -> None:
        self._files: dict[str, TrackedFile] = {}
        self._persist_path = persist_path
        if persist_path:
            self._load()

    def track(self, path: str, **kwargs) -> TrackedFile:
        """Start tracking a file or return existing tracker."""
        if path not in self._files:
            self._files[path] = TrackedFile(path=path, **kwargs)
        return self._files[path]

    def get(self, path: str) -> TrackedFile | None:
        return self._files.get(path)

    def transition(self, path: str, new_state: str, **kwargs) -> TrackedFile | None:
        """Transition a tracked file to a new state."""
        tf = self._files.get(path)
        if tf:
            tf.transition(new_state, **kwargs)
            self._save()
        return tf

    def remove(self, path: str) -> None:
        """Stop tracking a file (after success or permanent skip)."""
        self._files.pop(path, None)
        self._save()

    def get_by_state(self, state: str) -> list[TrackedFile]:
        return [f for f in self._files.values() if f.state == state]

    def get_queued(self) -> list[TrackedFile]:
        """Get files queued for retry."""
        return self.get_by_state(FileState.QUEUED)

    def get_failed(self) -> list[TrackedFile]:
        """Get failed files for inspection."""
        return self.get_by_state(FileState.FAILED)

    def summary(self) -> dict[str, int]:
        """Count files by state."""
        counts: dict[str, int] = {}
        for tf in self._files.values():
            counts[tf.state] = counts.get(tf.state, 0) + 1
        return counts

    def _save(self) -> None:
        if not self._persist_path:
            return
        try:
            Path(self._persist_path).parent.mkdir(parents=True, exist_ok=True)
            data = {k: asdict(v) for k, v in self._files.items()}
            with open(self._persist_path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def _load(self) -> None:
        if not self._persist_path or not os.path.exists(self._persist_path):
            return
        try:
            with open(self._persist_path, "r") as f:
                data = json.load(f)
            for path, fields in data.items():
                self._files[path] = TrackedFile(**fields)
        except Exception:
            pass
