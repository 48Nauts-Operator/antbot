"""Tests for scout file-state tracker."""

import json
import tempfile
from pathlib import Path

from antbot.scout.state import FileState, StateTracker, TrackedFile


def test_track_and_transition():
    tracker = StateTracker()
    tf = tracker.track("/test/file.pdf", size=1000)
    assert tf.state == FileState.DETECTED
    assert tf.size == 1000

    tracker.transition("/test/file.pdf", FileState.MATCHED, rule="docs")
    assert tf.state == FileState.MATCHED
    assert tf.rule == "docs"


def test_get_by_state():
    tracker = StateTracker()
    tracker.track("/a.pdf")
    tracker.track("/b.pdf")
    tracker.transition("/a.pdf", FileState.QUEUED)
    tracker.transition("/b.pdf", FileState.FAILED)

    queued = tracker.get_queued()
    assert len(queued) == 1
    assert queued[0].path == "/a.pdf"

    failed = tracker.get_failed()
    assert len(failed) == 1
    assert failed[0].path == "/b.pdf"


def test_remove():
    tracker = StateTracker()
    tracker.track("/test.pdf")
    assert tracker.get("/test.pdf") is not None
    tracker.remove("/test.pdf")
    assert tracker.get("/test.pdf") is None


def test_summary():
    tracker = StateTracker()
    tracker.track("/a.pdf")
    tracker.track("/b.pdf")
    tracker.transition("/a.pdf", FileState.SUCCEEDED)
    tracker.transition("/b.pdf", FileState.QUEUED)

    s = tracker.summary()
    assert s[FileState.SUCCEEDED] == 1
    assert s[FileState.QUEUED] == 1


def test_persistence():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        path = f.name

    try:
        # Write
        t1 = StateTracker(path)
        t1.track("/test.pdf", size=500)
        t1.transition("/test.pdf", FileState.QUEUED, error="NAS offline")

        # Read
        t2 = StateTracker(path)
        tf = t2.get("/test.pdf")
        assert tf is not None
        assert tf.state == FileState.QUEUED
        assert tf.error == "NAS offline"
        assert tf.size == 500
    finally:
        Path(path).unlink(missing_ok=True)


def test_idempotent_track():
    """Tracking the same path twice returns the existing tracker."""
    tracker = StateTracker()
    tf1 = tracker.track("/test.pdf")
    tf1.state = FileState.MATCHED
    tf2 = tracker.track("/test.pdf")
    assert tf2.state == FileState.MATCHED  # same object
