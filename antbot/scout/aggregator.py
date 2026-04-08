"""Multi-machine aggregation — read event logs from all machines, build views."""

from __future__ import annotations

import json
import logging
import os
import socket
import time
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


class MachineAggregator:
    """Aggregates event logs and status from multiple machines on NAS."""

    def __init__(self, backup_root: str = "/Volumes/Tron/mpb_backup") -> None:
        self._backup_root = backup_root
        self._events_dir = os.path.join(backup_root, "AntBot", "events")
        self._views_dir = os.path.join(backup_root, "AntBot", "views")
        self._hostname = socket.gethostname().lower()

    def list_machines(self) -> list[dict]:
        """List all machines that have event logs on NAS."""
        machines = []
        if not os.path.isdir(self._events_dir):
            return machines

        for f in os.listdir(self._events_dir):
            if f.endswith(".jsonl"):
                hostname = f.replace(".jsonl", "")
                log_path = os.path.join(self._events_dir, f)
                stat = os.stat(log_path)
                machines.append({
                    "hostname": hostname,
                    "log_file": log_path,
                    "log_size_bytes": stat.st_size,
                    "last_modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                    "is_current": hostname == self._hostname,
                })

        return sorted(machines, key=lambda m: m["hostname"])

    def machine_heartbeats(self) -> list[dict]:
        """Check last heartbeat from each machine's event log."""
        machines = self.list_machines()
        heartbeats = []

        for m in machines:
            last_event = self._last_event(m["log_file"])
            if last_event:
                age_s = time.time() - _parse_ts(last_event.get("ts", ""))
                heartbeats.append({
                    "hostname": m["hostname"],
                    "last_event": last_event.get("event", "unknown"),
                    "last_ts": last_event.get("ts", ""),
                    "age_seconds": round(age_s),
                    "status": "online" if age_s < 3600 else "stale" if age_s < 86400 else "offline",
                    "is_current": m["is_current"],
                })
            else:
                heartbeats.append({
                    "hostname": m["hostname"],
                    "last_event": None,
                    "last_ts": None,
                    "age_seconds": None,
                    "status": "unknown",
                    "is_current": m["is_current"],
                })

        return heartbeats

    def aggregate_project_status(self) -> list[dict]:
        """Aggregate project status events from all machines."""
        projects: dict[str, dict] = {}

        for m in self.list_machines():
            for event in self._read_events(m["log_file"], event_type="projects.scanned", limit=1):
                meta = event.get("meta", {})
                # The actual project data is in the scan results, not the event
                # For now, just track which machines have scanned
                pass

            # Look for individual project events
            for event in self._read_events(m["log_file"], event_type="project.bundled", limit=50):
                src = event.get("src", "")
                name = os.path.basename(src) if src else "unknown"
                key = name
                if key not in projects or _parse_ts(event.get("ts", "")) > _parse_ts(projects[key].get("last_backup_ts", "")):
                    projects[key] = {
                        "name": name,
                        "path": src,
                        "machine": m["hostname"],
                        "last_backup_ts": event.get("ts", ""),
                        "ok": event.get("ok", False),
                    }

        return list(projects.values())

    def build_views(self) -> dict:
        """Build aggregated view files on NAS."""
        os.makedirs(self._views_dir, exist_ok=True)

        # Machine status view
        machines_view = {
            "generated": datetime.now(timezone.utc).isoformat(),
            "machines": self.machine_heartbeats(),
        }
        _write_json(os.path.join(self._views_dir, "machines.json"), machines_view)

        # Project status view
        projects_view = {
            "generated": datetime.now(timezone.utc).isoformat(),
            "projects": self.aggregate_project_status(),
        }
        _write_json(os.path.join(self._views_dir, "projects.json"), projects_view)

        return {
            "machines": len(machines_view["machines"]),
            "projects": len(projects_view["projects"]),
        }

    def format_dashboard(self) -> str:
        """Format a text dashboard of all machines and their status."""
        heartbeats = self.machine_heartbeats()

        if not heartbeats:
            return "No machines found on NAS."

        lines = [
            f"AntBot Fleet — {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "-" * 60,
            f"{'Machine':<25} {'Status':<10} {'Last Event':<25}",
            "-" * 60,
        ]

        for hb in heartbeats:
            hostname = hb["hostname"]
            if hb["is_current"]:
                hostname += " *"
            status = hb["status"]
            last_ts = hb["last_ts"][:19] if hb["last_ts"] else "never"

            status_display = {
                "online": "ONLINE",
                "stale": "STALE",
                "offline": "OFFLINE",
                "unknown": "UNKNOWN",
            }.get(status, status)

            lines.append(f"{hostname:<25} {status_display:<10} {last_ts:<25}")

        return "\n".join(lines)

    def _last_event(self, log_path: str) -> dict | None:
        """Read the last event from a JSONL file."""
        try:
            with open(log_path, "rb") as f:
                # Seek to near the end for efficiency
                f.seek(0, 2)
                size = f.tell()
                read_size = min(size, 4096)
                f.seek(max(0, size - read_size))
                data = f.read().decode("utf-8", errors="replace")

            lines = data.strip().split("\n")
            for line in reversed(lines):
                line = line.strip()
                if line:
                    return json.loads(line)
        except Exception:
            pass
        return None

    def _read_events(self, log_path: str, event_type: str | None = None, limit: int = 100) -> list[dict]:
        """Read recent events from a JSONL file."""
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except Exception:
            return []

        results = []
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
                if event_type and event.get("event") != event_type:
                    continue
                results.append(event)
                if len(results) >= limit:
                    break
            except json.JSONDecodeError:
                continue

        return results


def _parse_ts(ts: str) -> float:
    """Parse ISO timestamp to epoch seconds."""
    if not ts:
        return 0
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.timestamp()
    except (ValueError, AttributeError):
        return 0


def _write_json(path: str, data: dict) -> None:
    """Write JSON with atomic rename."""
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.rename(tmp, path)
