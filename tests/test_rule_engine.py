"""Tests for the scout rule engine."""

import os
import tempfile
from pathlib import Path

from antbot.scout.rules import Rule, RuleEngine, _parse_duration, _parse_size


def test_extension_match():
    rule = Rule(name="photos", watch="~/Downloads", target="/nas/photos/",
                extensions=["jpg", "png", "heic"])
    assert rule.matches("/Downloads/photo.jpg", size=1000)
    assert rule.matches("/Downloads/PHOTO.PNG", size=1000)
    assert not rule.matches("/Downloads/doc.pdf", size=1000)


def test_pattern_match():
    rule = Rule(name="screenshots", watch="~/Desktop", target="/nas/screenshots/",
                patterns=["Screenshot*", "Bildschirmfoto*"])
    assert rule.matches("/Desktop/Screenshot 2026-04-09.png")
    assert rule.matches("/Desktop/Bildschirmfoto 2026-04-09.png")
    assert not rule.matches("/Desktop/notes.txt")


def test_exclude():
    rule = Rule(name="docs", watch="~/Downloads", target="/nas/docs/",
                extensions=["pdf", "txt"], exclude=["*.tmp", "~*"])
    assert rule.matches("/Downloads/report.pdf")
    assert not rule.matches("/Downloads/report.tmp")
    assert not rule.matches("/Downloads/~temp.pdf")


def test_size_filter():
    rule = Rule(name="large", watch="~/Downloads", target="/nas/large/",
                min_size=1024 * 1024)  # 1MB minimum
    assert not rule.matches("/Downloads/small.bin", size=100)
    assert rule.matches("/Downloads/big.bin", size=2 * 1024 * 1024)


def test_disabled_rule():
    rule = Rule(name="disabled", watch="~/Downloads", target="/nas/",
                extensions=["pdf"], enabled=False)
    assert not rule.matches("/Downloads/doc.pdf")


def test_type_filter():
    rule = Rule(name="files-only", watch="~/Downloads", target="/nas/",
                match_type="file")
    assert rule.matches("/Downloads/file.txt", is_dir=False)
    assert not rule.matches("/Downloads/subdir", is_dir=True)


def test_engine_priority():
    """Higher priority rules match first."""
    low = Rule(name="catch-all", watch="~/Downloads", target="/nas/other/",
               extensions=["pdf"], priority=10)
    high = Rule(name="invoices", watch="~/Downloads", target="/nas/finance/",
                extensions=["pdf"], priority=90)
    engine = RuleEngine([low, high])
    match = engine.match("/Downloads/invoice.pdf")
    assert match is not None
    assert match.name == "invoices"


def test_engine_test():
    """Test dry-run shows all matching rules."""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(b"test content")
        path = f.name

    try:
        rule1 = Rule(name="docs", watch="~/Downloads", target="/nas/docs/{year}/",
                      extensions=["pdf"], priority=50)
        rule2 = Rule(name="all-files", watch="~/Downloads", target="/nas/all/",
                      priority=10)
        engine = RuleEngine([rule1, rule2])
        results = engine.test(path)
        assert len(results) == 2
        assert results[0]["rule"] == "docs"  # higher priority first
    finally:
        os.unlink(path)


def test_resolve_target():
    """Target template variables are resolved."""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(b"test")
        path = f.name

    try:
        rule = Rule(name="test", watch="~/Downloads",
                    target="/nas/{year}/{month}/")
        target = rule.resolve_target(path)
        assert "/nas/20" in target  # year starts with 20
        assert os.path.basename(path) in target
    finally:
        os.unlink(path)


def test_from_dict_list():
    """Rules load from YAML-style dict list."""
    rules_data = [
        {
            "name": "photos",
            "watch": "~/Downloads",
            "match": {"extensions": ["jpg", "png"], "type": "file"},
            "target": "/nas/photos/{year}/{month}/",
            "action": "move",
            "delay": "30s",
            "priority": 60,
        },
        {
            "name": "archives",
            "watch": "~/Downloads",
            "match": {"extensions": ["zip", "tar"]},
            "target": "/nas/archives/",
            "action": "copy",
        },
    ]
    engine = RuleEngine.from_dict_list(rules_data)
    assert len(engine.rules) == 2
    assert engine.rules[0].name == "photos"  # higher priority first
    assert engine.rules[0].delay == 30
    assert engine.rules[1].action == "copy"


def test_parse_duration():
    assert _parse_duration("30s") == 30
    assert _parse_duration("5m") == 300
    assert _parse_duration("1h") == 3600
    assert _parse_duration(60) == 60


def test_parse_size():
    assert _parse_size("10MB") == 10 * 1024 * 1024
    assert _parse_size("1GB") == 1024 * 1024 * 1024
    assert _parse_size(0) == 0
