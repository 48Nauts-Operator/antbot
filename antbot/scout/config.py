"""YAML rules loader with hot-reload support."""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any

from antbot.scout.rules import RuleEngine

logger = logging.getLogger(__name__)

# Default rules for Downloads triage
DEFAULT_RULES: list[dict[str, Any]] = [
    {
        "name": "photos-from-downloads",
        "watch": "~/Downloads",
        "match": {
            "extensions": ["jpg", "jpeg", "png", "heic", "webp", "gif", "raw", "cr2", "arw", "tiff", "bmp", "svg"],
            "type": "file",
        },
        "target": "/Volumes/devhub/Photos/{year}/{month}/",
        "action": "move",
        "delay": "30s",
        "tags": ["triage", "photos"],
    },
    {
        "name": "videos-from-downloads",
        "watch": "~/Downloads",
        "match": {
            "extensions": ["mp4", "mov", "avi", "mkv", "webm", "m4v"],
            "type": "file",
        },
        "target": "/Volumes/devhub/Media/Videos/{year}/{month}/",
        "action": "move",
        "delay": "60s",
        "tags": ["triage", "media"],
    },
    {
        "name": "documents-from-downloads",
        "watch": "~/Downloads",
        "match": {
            "extensions": ["pdf", "docx", "xlsx", "pptx", "odt", "ods", "odp", "txt", "rtf", "csv"],
            "type": "file",
        },
        "target": "/Volumes/devhub/Documents/Unsorted/{year}/",
        "action": "move",
        "delay": "30s",
        "tags": ["triage", "documents"],
    },
    {
        "name": "archives-from-downloads",
        "watch": "~/Downloads",
        "match": {
            "extensions": ["zip", "tar", "gz", "bz2", "7z", "rar", "xz"],
            "type": "file",
        },
        "target": "/Volumes/devhub/Downloads/Archives/{year}/{month}/",
        "action": "move",
        "delay": "30s",
        "tags": ["triage", "archives"],
    },
    {
        "name": "installers-quarantine",
        "watch": "~/Downloads",
        "match": {
            "extensions": ["dmg", "pkg", "exe", "msi", "app", "iso", "deb", "rpm"],
            "type": "file",
        },
        "target": "/Volumes/devhub/Quarantine/{year}/{month}/",
        "action": "move",
        "confirm": True,
        "tags": ["triage", "quarantine"],
    },
    # === Desktop triage (Phase 2) ===
    {
        "name": "screenshots-from-desktop",
        "watch": "~/Desktop",
        "match": {
            "patterns": ["Screenshot*", "Bildschirmfoto*", "Screen Shot*"],
            "type": "file",
        },
        "target": "/Volumes/devhub/Photos/Screenshots/{year}/{month}/",
        "action": "move",
        "delay": "10s",
        "tags": ["triage", "screenshots"],
    },
    {
        "name": "photos-from-desktop",
        "watch": "~/Desktop",
        "match": {
            "extensions": ["jpg", "jpeg", "png", "heic", "webp", "gif", "svg"],
            "type": "file",
        },
        "target": "/Volumes/devhub/Photos/{year}/{month}/",
        "action": "move",
        "delay": "30s",
        "priority": 40,
        "tags": ["triage", "photos"],
    },
    {
        "name": "documents-from-desktop",
        "watch": "~/Desktop",
        "match": {
            "extensions": ["pdf", "docx", "xlsx", "pptx", "txt", "md", "rtf", "csv"],
            "type": "file",
        },
        "target": "/Volumes/devhub/Documents/Unsorted/{year}/",
        "action": "move",
        "delay": "30s",
        "priority": 40,
        "tags": ["triage", "documents"],
    },
]


class RulesLoader:
    """Loads rules from YAML file with hot-reload on change."""

    def __init__(self, rules_path: str = "~/.antbot/rules.yml") -> None:
        self._path = Path(rules_path).expanduser()
        self._last_mtime: float = 0
        self._engine: RuleEngine | None = None

    @property
    def engine(self) -> RuleEngine:
        """Get the current rule engine, reloading if file changed."""
        self._check_reload()
        if self._engine is None:
            self._engine = RuleEngine.from_dict_list(DEFAULT_RULES)
        return self._engine

    def _check_reload(self) -> None:
        """Reload rules if the YAML file has been modified."""
        if not self._path.exists():
            return

        try:
            mtime = self._path.stat().st_mtime
        except OSError:
            return

        if mtime <= self._last_mtime:
            return

        self._last_mtime = mtime
        try:
            self._load()
        except Exception as e:
            logger.error("Failed to reload rules from %s: %s", self._path, e)

    def _load(self) -> None:
        """Load rules from YAML file."""
        try:
            import yaml
        except ImportError:
            # Fallback: try json if pyyaml not installed
            import json
            with open(self._path, "r") as f:
                data = json.load(f)
        else:
            with open(self._path, "r") as f:
                data = yaml.safe_load(f)

        rules_data = data.get("rules", []) if isinstance(data, dict) else data
        self._engine = RuleEngine.from_dict_list(rules_data)
        logger.info("Loaded %d rules from %s", len(self._engine.rules), self._path)

    def save_defaults(self) -> None:
        """Write default rules to the YAML file if it doesn't exist."""
        if self._path.exists():
            return

        self._path.parent.mkdir(parents=True, exist_ok=True)

        try:
            import yaml
            content = yaml.dump({"rules": DEFAULT_RULES}, default_flow_style=False, sort_keys=False)
        except ImportError:
            import json
            content = json.dumps({"rules": DEFAULT_RULES}, indent=2)

        self._path.write_text(content)
        logger.info("Created default rules at %s", self._path)
