"""One-way backup primitives — dotfiles, configs, manifests to NAS."""

from __future__ import annotations

import json
import logging
import os
import socket
from pathlib import Path

from antbot.events.logger import EventLogger
from antbot.events.schema import AntBotEvent
from antbot.exec_bridge.manager import ExecBridgeManager

logger = logging.getLogger(__name__)


# Files to back up from home directory
DOTFILES = [".zshrc", ".zprofile", ".gitconfig", ".npmrc", ".pypirc"]

# Directories to back up (relative to home)
CONFIG_DIRS = {
    "vscode": "Library/Application Support/Code/User",
    "claude": ".claude",
}

# Files within config dirs to include
CONFIG_FILES = {
    "vscode": ["settings.json", "keybindings.json"],
    "claude": ["CLAUDE.md", "settings.json"],
}


class BackupManager:
    """Manages one-way backups to NAS."""

    def __init__(
        self,
        exec_manager: ExecBridgeManager,
        event_logger: EventLogger,
        backup_root: str = "/Volumes/Tron/mpb_backup",
        dry_run: bool = True,
    ) -> None:
        self._exec = exec_manager
        self._events = event_logger
        self._backup_root = backup_root
        self._dry_run = dry_run
        self._hostname = socket.gethostname().lower()
        self._machine_dir = os.path.join(backup_root, "Machines", self._hostname)

    async def backup_dotfiles(self) -> list[dict]:
        """Back up dotfiles from home to NAS."""
        home = os.path.expanduser("~")
        results = []

        for dotfile in DOTFILES:
            src = os.path.join(home, dotfile)
            if not os.path.exists(src):
                continue

            dst = os.path.join(self._machine_dir, "dotfiles", dotfile)
            result = await self._copy_file(src, dst, "dotfiles-backup")
            results.append(result)

        return results

    async def backup_ssh_config(self) -> list[dict]:
        """Back up SSH config and public keys (NOT private keys)."""
        ssh_dir = os.path.expanduser("~/.ssh")
        results = []

        # Config and known_hosts
        for name in ["config", "known_hosts"]:
            src = os.path.join(ssh_dir, name)
            if os.path.exists(src):
                dst = os.path.join(self._machine_dir, "ssh", name)
                results.append(await self._copy_file(src, dst, "ssh-config-backup"))

        # Public keys only
        if os.path.isdir(ssh_dir):
            for f in os.listdir(ssh_dir):
                if f.endswith(".pub"):
                    src = os.path.join(ssh_dir, f)
                    dst = os.path.join(self._machine_dir, "ssh", f)
                    results.append(await self._copy_file(src, dst, "ssh-config-backup"))

        return results

    async def backup_configs(self) -> list[dict]:
        """Back up VS Code and Claude configs."""
        home = os.path.expanduser("~")
        results = []

        for config_name, rel_dir in CONFIG_DIRS.items():
            src_dir = os.path.join(home, rel_dir)
            if not os.path.isdir(src_dir):
                continue

            files = CONFIG_FILES.get(config_name, [])
            for fname in files:
                src = os.path.join(src_dir, fname)
                if os.path.exists(src):
                    dst = os.path.join(self._machine_dir, config_name, fname)
                    results.append(await self._copy_file(src, dst, f"{config_name}-backup"))

        return results

    async def generate_manifest(self) -> dict:
        """Generate machine manifest via Go binary and save to NAS."""
        try:
            client = await self._exec.ensure_connected()

            # Call the System.Manifest RPC
            stub_module = __import__("antbot.exec_bridge.gen.antbot_pb2_grpc", fromlist=["SystemStub"])
            pb_module = __import__("antbot.exec_bridge.gen.antbot_pb2", fromlist=["ManifestRequest"])

            import grpc.aio
            channel = client._ensure_channel()
            stub = stub_module.SystemStub(channel)
            resp = await stub.Manifest(pb_module.ManifestRequest())

            if not resp.ok:
                return {"ok": False, "error": resp.error}

            # Save manifest to NAS
            manifest_path = os.path.join(self._machine_dir, "manifest.json")
            if not self._dry_run:
                os.makedirs(os.path.dirname(manifest_path), exist_ok=True)
                with open(manifest_path, "w") as f:
                    f.write(resp.json)

            self._events.log(AntBotEvent(
                event="manifest.generated",
                dst=manifest_path,
                dry_run=self._dry_run,
                ok=True,
                hostname=self._hostname,
            ))

            prefix = "[DRY RUN] " if self._dry_run else ""
            logger.info("%sManifest saved to %s", prefix, manifest_path)
            return {"ok": True, "path": manifest_path, "dry_run": self._dry_run}

        except Exception as e:
            self._events.log(AntBotEvent(
                event="manifest.error", ok=False, error=str(e), hostname=self._hostname,
            ))
            return {"ok": False, "error": str(e)}

    async def backup_all(self) -> dict:
        """Run all backup operations."""
        results = {
            "dotfiles": await self.backup_dotfiles(),
            "ssh": await self.backup_ssh_config(),
            "configs": await self.backup_configs(),
            "manifest": await self.generate_manifest(),
        }

        total = sum(len(v) if isinstance(v, list) else 1 for v in results.values())
        ok = sum(
            sum(1 for r in v if r.get("ok")) if isinstance(v, list)
            else (1 if v.get("ok") else 0)
            for v in results.values()
        )
        logger.info("Backup complete: %d/%d operations succeeded", ok, total)
        return results

    async def _copy_file(self, src: str, dst: str, rule_name: str) -> dict:
        """Copy a single file via Go binary."""
        try:
            client = await self._exec.ensure_connected()

            # Skip if destination is identical (same size + mtime)
            if os.path.exists(dst):
                src_stat = os.stat(src)
                dst_stat = os.stat(dst)
                if src_stat.st_size == dst_stat.st_size and src_stat.st_mtime <= dst_stat.st_mtime:
                    return {"ok": True, "src": src, "dst": dst, "skipped": True}

            result = await client.copy(src, dst, dry_run=self._dry_run)

            self._events.log(AntBotEvent(
                event="file.copied" if not self._dry_run else "file.copy_dry",
                src=src, dst=dst, rule=rule_name,
                action="copy", dry_run=self._dry_run,
                ok=result["ok"],
                error=result.get("error", ""),
                size_bytes=result.get("size_bytes", 0),
            ))

            return result

        except Exception as e:
            self._events.log(AntBotEvent(
                event="file.copy_error", src=src, dst=dst, rule=rule_name,
                action="copy", ok=False, error=str(e),
            ))
            return {"ok": False, "src": src, "dst": dst, "error": str(e)}
