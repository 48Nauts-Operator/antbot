"""Tests for Phase 0 config additions."""

from antbot.config.schema import Config, NasConfig, RulesConfig, EventConfig, ExecBridgeConfig


def test_defaults():
    """Config loads with all new fields having sensible defaults."""
    c = Config()
    assert c.nas.files_root == "/Volumes/devhub"
    assert c.nas.backup_root == "/Volumes/Tron/mpb_backup"
    assert c.nas.enabled is False
    assert c.rules.dry_run is True
    assert c.rules.default_action == "log"
    assert c.events.log_dir == "~/.antbot/events"
    assert c.events.max_file_size_mb == 50
    assert c.exec_bridge.enabled is False
    assert c.exec_bridge.socket_path == "/tmp/antbot.sock"


def test_nested_camel_case():
    """Nested config classes (Base subclasses) use camelCase aliases."""
    nas = NasConfig()
    dumped = nas.model_dump(by_alias=True)
    assert "filesRoot" in dumped
    assert "backupRoot" in dumped

    rules = RulesConfig()
    dumped = rules.model_dump(by_alias=True)
    assert "dryRun" in dumped

    eb = ExecBridgeConfig()
    dumped = eb.model_dump(by_alias=True)
    assert "socketPath" in dumped


def test_root_config_round_trip():
    """Root Config (BaseSettings) uses snake_case at top level, camelCase in nested."""
    c = Config()
    dumped = c.model_dump()
    assert "exec_bridge" in dumped
    assert "nas" in dumped
    # Nested uses snake_case in default dump, camelCase with by_alias
    assert dumped["nas"]["files_root"] == "/Volumes/devhub"


def test_custom_values():
    """Config accepts custom values via snake_case keys."""
    c = Config.model_validate({
        "nas": {"enabled": True, "files_root": "/mnt/custom"},
        "rules": {"dry_run": False},
        "exec_bridge": {"enabled": True, "socket_path": "/var/run/antbot.sock"},
    })
    assert c.nas.enabled is True
    assert c.nas.files_root == "/mnt/custom"
    assert c.rules.dry_run is False
    assert c.exec_bridge.socket_path == "/var/run/antbot.sock"


def test_custom_values_camel_case():
    """Nested configs also accept camelCase keys (via alias)."""
    nas = NasConfig.model_validate({"filesRoot": "/mnt/nas", "backupRoot": "/mnt/backup"})
    assert nas.files_root == "/mnt/nas"
    assert nas.backup_root == "/mnt/backup"
