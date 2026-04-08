"""Tests for multi-machine aggregation."""

import json
import os
import tempfile
from datetime import datetime, timezone

from antbot.scout.aggregator import MachineAggregator, _parse_ts


def _write_events(path: str, events: list[dict]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")


def test_list_machines():
    with tempfile.TemporaryDirectory() as tmpdir:
        events_dir = os.path.join(tmpdir, "AntBot", "events")
        _write_events(os.path.join(events_dir, "macbook.jsonl"), [
            {"ts": "2026-04-09T10:00:00Z", "event": "health.ping"}
        ])
        _write_events(os.path.join(events_dir, "ws1.jsonl"), [
            {"ts": "2026-04-09T09:00:00Z", "event": "file.moved"}
        ])

        agg = MachineAggregator(tmpdir)
        machines = agg.list_machines()
        assert len(machines) == 2
        hostnames = {m["hostname"] for m in machines}
        assert hostnames == {"macbook", "ws1"}


def test_machine_heartbeats():
    with tempfile.TemporaryDirectory() as tmpdir:
        events_dir = os.path.join(tmpdir, "AntBot", "events")
        now = datetime.now(timezone.utc).isoformat()
        _write_events(os.path.join(events_dir, "macbook.jsonl"), [
            {"ts": now, "event": "health.ping"}
        ])

        agg = MachineAggregator(tmpdir)
        heartbeats = agg.machine_heartbeats()
        assert len(heartbeats) == 1
        assert heartbeats[0]["hostname"] == "macbook"
        assert heartbeats[0]["status"] == "online"


def test_format_dashboard():
    with tempfile.TemporaryDirectory() as tmpdir:
        events_dir = os.path.join(tmpdir, "AntBot", "events")
        now = datetime.now(timezone.utc).isoformat()
        _write_events(os.path.join(events_dir, "macbook.jsonl"), [
            {"ts": now, "event": "health.ping"}
        ])
        _write_events(os.path.join(events_dir, "ws1.jsonl"), [
            {"ts": "2020-01-01T00:00:00Z", "event": "file.moved"}
        ])

        agg = MachineAggregator(tmpdir)
        dashboard = agg.format_dashboard()
        assert "macbook" in dashboard
        assert "ws1" in dashboard
        assert "ONLINE" in dashboard
        assert "OFFLINE" in dashboard


def test_build_views():
    with tempfile.TemporaryDirectory() as tmpdir:
        events_dir = os.path.join(tmpdir, "AntBot", "events")
        now = datetime.now(timezone.utc).isoformat()
        _write_events(os.path.join(events_dir, "macbook.jsonl"), [
            {"ts": now, "event": "project.bundled", "src": "/path/to/AntBot", "ok": True}
        ])

        agg = MachineAggregator(tmpdir)
        result = agg.build_views()
        assert result["machines"] == 1
        assert result["projects"] == 1

        # Verify files written
        views_dir = os.path.join(tmpdir, "AntBot", "views")
        assert os.path.exists(os.path.join(views_dir, "machines.json"))
        assert os.path.exists(os.path.join(views_dir, "projects.json"))


def test_parse_ts():
    assert _parse_ts("") == 0
    assert _parse_ts("2026-04-09T10:00:00Z") > 0
    assert _parse_ts("2026-04-09T10:00:00+00:00") > 0


def test_empty_nas():
    with tempfile.TemporaryDirectory() as tmpdir:
        agg = MachineAggregator(tmpdir)
        assert agg.list_machines() == []
        assert "No machines" in agg.format_dashboard()
