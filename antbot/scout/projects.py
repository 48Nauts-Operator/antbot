"""Project protection — scanner, status, git bundle backup."""

from __future__ import annotations

import json
import logging
import os
import socket
from datetime import datetime

from antbot.events.logger import EventLogger
from antbot.events.schema import AntBotEvent
from antbot.exec_bridge.manager import ExecBridgeManager

logger = logging.getLogger(__name__)


class ProjectManager:
    """Scans, reports, and protects code projects."""

    def __init__(
        self,
        exec_manager: ExecBridgeManager,
        event_logger: EventLogger,
        files_root: str = "/Volumes/devhub",
        dry_run: bool = True,
    ) -> None:
        self._exec = exec_manager
        self._events = event_logger
        self._files_root = files_root
        self._dry_run = dry_run
        self._hostname = socket.gethostname().lower()

    async def scan_projects(self, root_path: str) -> list[dict]:
        """Scan a directory for projects and return their git status."""
        client = await self._exec.ensure_connected()

        # Use the Git.ScanProjects RPC
        from antbot.exec_bridge.gen import antbot_pb2, antbot_pb2_grpc
        channel = client._ensure_channel()
        stub = antbot_pb2_grpc.GitStub(channel)
        resp = await stub.ScanProjects(antbot_pb2.ScanProjectsRequest(root_path=root_path))

        projects = []
        for p in resp.projects:
            projects.append({
                "path": p.path,
                "name": p.name,
                "branch": p.branch,
                "remote": p.remote,
                "dirty_files": p.dirty_files,
                "untracked_files": p.untracked_files,
                "ahead_by": p.ahead_by,
                "last_commit": p.last_commit,
                "last_message": p.last_message,
                "has_git": p.has_git,
            })

        self._events.log(AntBotEvent(
            event="projects.scanned",
            src=root_path,
            hostname=self._hostname,
            meta={"count": len(projects)},
        ))

        return projects

    async def project_status(self, root_path: str) -> str:
        """Generate a formatted project status report."""
        projects = await self.scan_projects(root_path)

        if not projects:
            return "No projects found."

        lines = [
            f"Project Status — {self._hostname} — {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "-" * 70,
            f"{'Project':<20} {'Branch':<12} {'Status':<15} {'Last Commit':<20}",
            "-" * 70,
        ]

        warnings = []
        for p in projects:
            name = p["name"][:19]
            branch = p["branch"][:11] if p["branch"] else "-"

            if not p["has_git"]:
                status = "no git!"
                warnings.append(f"{p['name']}: no git repository")
            elif p["dirty_files"] + p["untracked_files"] > 0:
                total = p["dirty_files"] + p["untracked_files"]
                status = f"{total} dirty"
            else:
                status = "clean"

            last = p["last_commit"][:10] if p["last_commit"] else "never"

            lines.append(f"{name:<20} {branch:<12} {status:<15} {last:<20}")

        if warnings:
            lines.append("")
            for w in warnings:
                lines.append(f"  WARNING: {w}")

        return "\n".join(lines)

    async def backup_project_tree(self, project_path: str) -> dict:
        """One-way copy of project working tree to NAS (excludes .git)."""
        project_name = os.path.basename(project_path)
        dst_base = os.path.join(self._files_root, "Projects", "factory", project_name)

        # This is a simplified version — for real rsync with excludes,
        # we'd need an rsync RPC. For now, log the intent.
        self._events.log(AntBotEvent(
            event="project.backup_tree",
            src=project_path,
            dst=dst_base,
            dry_run=self._dry_run,
            hostname=self._hostname,
        ))

        return {"ok": True, "src": project_path, "dst": dst_base, "dry_run": self._dry_run}

    async def backup_git_bundle(self, project_path: str) -> dict:
        """Create a git bundle containing all refs and copy to NAS."""
        project_name = os.path.basename(project_path)
        bundle_path = os.path.join(
            self._files_root, "Projects", "factory", f"{project_name}.bundle"
        )

        if self._dry_run:
            self._events.log(AntBotEvent(
                event="project.bundle_dry",
                src=project_path, dst=bundle_path,
                dry_run=True, hostname=self._hostname,
            ))
            return {"ok": True, "dry_run": True, "bundle_path": bundle_path}

        try:
            client = await self._exec.ensure_connected()
            from antbot.exec_bridge.gen import antbot_pb2, antbot_pb2_grpc
            channel = client._ensure_channel()
            stub = antbot_pb2_grpc.GitStub(channel)
            resp = await stub.Bundle(antbot_pb2.GitBundleRequest(
                repo_path=project_path, output_path=bundle_path,
            ))

            self._events.log(AntBotEvent(
                event="project.bundled" if resp.ok else "project.bundle_failed",
                src=project_path, dst=bundle_path,
                ok=resp.ok, error=resp.error,
                hostname=self._hostname,
            ))

            return {"ok": resp.ok, "error": resp.error, "bundle_path": bundle_path}

        except Exception as e:
            self._events.log(AntBotEvent(
                event="project.bundle_error",
                src=project_path, ok=False, error=str(e),
                hostname=self._hostname,
            ))
            return {"ok": False, "error": str(e)}

    async def protect_all(self, root_path: str) -> dict:
        """Scan all projects and create bundles."""
        projects = await self.scan_projects(root_path)
        results = []

        for p in projects:
            if not p["has_git"]:
                results.append({"name": p["name"], "skipped": True, "reason": "no git"})
                continue

            bundle_result = await self.backup_git_bundle(p["path"])
            results.append({
                "name": p["name"],
                "bundle": bundle_result,
                "dirty": p["dirty_files"] + p["untracked_files"],
            })

        return {"projects": results, "total": len(projects)}
