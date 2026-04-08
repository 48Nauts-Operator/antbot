"""Tests for the event logger."""

import json
import tempfile
from pathlib import Path

from antbot.events.schema import AntBotEvent
from antbot.events.logger import EventLogger


def test_event_serialization():
    """Events serialize to and from JSON."""
    e = AntBotEvent(event="file.moved", src="/a/b.pdf", dst="/c/d.pdf", ok=True)
    line = e.to_json()
    parsed = json.loads(line)
    assert parsed["event"] == "file.moved"
    assert parsed["src"] == "/a/b.pdf"
    assert parsed["ok"] is True
    assert parsed["ts"]  # auto-filled

    e2 = AntBotEvent.from_json(line)
    assert e2.event == e.event
    assert e2.src == e.src


def test_event_logger_writes_jsonl():
    """Logger writes valid JSONL to the correct directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = EventLogger(tmpdir)
        logger.log(AntBotEvent(event="test.one", src="a"))
        logger.log(AntBotEvent(event="test.two", src="b"))

        files = list(Path(tmpdir).glob("*.jsonl"))
        assert len(files) == 1

        lines = files[0].read_text().strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["event"] == "test.one"
        assert json.loads(lines[1])["event"] == "test.two"


def test_event_logger_query():
    """Logger can query recent events."""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = EventLogger(tmpdir)
        for i in range(5):
            logger.log(AntBotEvent(event=f"test.{i}"))

        results = logger.query(limit=3)
        assert len(results) == 3
        # Most recent first
        assert results[0]["event"] == "test.4"


def test_event_logger_query_by_type():
    """Logger filters by event type."""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = EventLogger(tmpdir)
        logger.log(AntBotEvent(event="file.moved"))
        logger.log(AntBotEvent(event="health.ping"))
        logger.log(AntBotEvent(event="file.moved"))

        results = logger.query(event_type="file.moved")
        assert len(results) == 2
        assert all(r["event"] == "file.moved" for r in results)
