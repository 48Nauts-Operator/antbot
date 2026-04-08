"""Tests for Ansible playbook generation."""

import json

from antbot.scout.provision import generate_playbook


SAMPLE_MANIFEST = json.dumps({
    "hostname": "dre-macbook",
    "os": "darwin",
    "arch": "arm64",
    "generated": "2026-04-09T00:00:00Z",
    "homebrew": {
        "formulae": ["git", "node", "python@3.12"],
        "casks": ["visual-studio-code", "lm-studio"],
    },
    "python": {"version": "3.12.3", "packages": ["ruff", "black"]},
    "node": {"version": "20.12.0", "packages": ["typescript", "pnpm"]},
    "docker": {"images": ["postgres:16", "redis:7"]},
    "vscode": {"extensions": ["ms-python.python", "bradlc.vscode-tailwindcss"]},
    "shell": {"default": "/bin/zsh"},
    "ssh": {"keys": ["id_ed25519"], "config_hosts": ["github.com"]},
    "git": {"user_name": "Andre Wolke", "user_email": "dre@example.com"},
})


def test_generates_valid_yaml():
    """Generated playbook is valid YAML-ish content."""
    result = generate_playbook(SAMPLE_MANIFEST, "/Volumes/Tron/mpb_backup")
    assert "---" in result
    assert "ansible-playbook" not in result or "# Usage:" in result
    assert "hosts: localhost" in result


def test_includes_brew():
    result = generate_playbook(SAMPLE_MANIFEST, "/Volumes/Tron/mpb_backup")
    assert "git" in result
    assert "node" in result
    assert "visual-studio-code" in result


def test_includes_dotfiles():
    result = generate_playbook(SAMPLE_MANIFEST, "/Volumes/Tron/mpb_backup")
    assert ".zshrc" in result
    assert ".gitconfig" in result


def test_excludes_private_keys():
    result = generate_playbook(SAMPLE_MANIFEST, "/Volumes/Tron/mpb_backup")
    assert "Private SSH keys are NOT restored" in result


def test_includes_ssh_public_keys():
    result = generate_playbook(SAMPLE_MANIFEST, "/Volumes/Tron/mpb_backup")
    assert "id_ed25519" in result


def test_includes_vscode():
    result = generate_playbook(SAMPLE_MANIFEST, "/Volumes/Tron/mpb_backup")
    assert "ms-python.python" in result
    assert "settings.json" in result


def test_includes_docker():
    result = generate_playbook(SAMPLE_MANIFEST, "/Volumes/Tron/mpb_backup")
    assert "postgres:16" in result


def test_includes_python_packages():
    result = generate_playbook(SAMPLE_MANIFEST, "/Volumes/Tron/mpb_backup")
    assert "ruff" in result
    assert "black" in result


def test_includes_verification():
    result = generate_playbook(SAMPLE_MANIFEST, "/Volumes/Tron/mpb_backup")
    assert "verify" in result.lower()
