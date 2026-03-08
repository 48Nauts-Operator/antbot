"""Space-Ant: disk space analyzer tool.

Scans for disk space waste (caches, temp files, node_modules, build artifacts,
Docker overhead) and optionally cleans safe targets.
"""

from __future__ import annotations

import asyncio
import os
import platform
from pathlib import Path
from typing import Any

from antbot.agent.tools.base import Tool


def _human_size(size_bytes: int) -> str:
    """Convert bytes to human-readable string."""
    for unit in ("B", "KB", "MB", "GB"):
        if abs(size_bytes) < 1024:
            return f"{size_bytes:,.0f} {unit}" if unit == "B" else f"{size_bytes:,.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:,.1f} TB"


async def _run(cmd: str, timeout: int = 30) -> str:
    """Run a shell command and return stdout."""
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return stdout.decode("utf-8", errors="replace").strip()
    except (asyncio.TimeoutError, FileNotFoundError, OSError):
        return ""


def _dir_size(path: Path, max_items: int = 50000) -> int:
    """Calculate total size of a directory (with item cap to avoid hanging)."""
    total = 0
    count = 0
    try:
        for root, dirs, files in os.walk(path):
            for f in files:
                try:
                    total += (Path(root) / f).stat().st_size
                except OSError:
                    pass
                count += 1
                if count >= max_items:
                    return total
    except (PermissionError, OSError):
        pass
    return total


def _find_dirs_named(name: str, search_root: Path, max_depth: int = 5) -> list[Path]:
    """Find directories with a given name under search_root (bounded depth)."""
    results: list[Path] = []
    try:
        for root, dirs, _ in os.walk(search_root):
            depth = str(root).count(os.sep) - str(search_root).count(os.sep)
            if depth >= max_depth:
                dirs.clear()
                continue
            if name in dirs:
                results.append(Path(root) / name)
            # Prune hidden and very deep dirs
            dirs[:] = [d for d in dirs if not d.startswith(".") and d != name]
    except (PermissionError, OSError):
        pass
    return results


class SpaceAntTool(Tool):
    """Scan for disk space waste and optionally clean safe targets."""

    @property
    def name(self) -> str:
        return "space_ant"

    @property
    def description(self) -> str:
        return (
            "Scan for disk space waste (caches, temp files, node_modules, "
            "build artifacts, Docker images) and optionally clean safe targets."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["scan", "clean"],
                    "description": "scan = report only; clean = remove safe targets (requires confirm=true)",
                },
                "confirm": {
                    "type": "boolean",
                    "description": "Must be true to actually clean (safety gate)",
                },
            },
            "required": ["action"],
        }

    @property
    def category(self) -> str:
        return "devops"

    async def execute(self, action: str, confirm: bool = False, **kwargs: Any) -> str:
        if action == "scan":
            return await self._scan()
        if action == "clean":
            if not confirm:
                return (
                    "Safety gate: set confirm=true to actually clean.\n"
                    "Run scan first to see what would be cleaned."
                )
            return await self._clean()
        return f"Error: Unknown action '{action}'. Use 'scan' or 'clean'."

    async def _scan(self) -> str:
        """Non-destructive scan — returns a report of disk space waste."""
        home = Path.home()
        is_mac = platform.system() == "Darwin"
        categories: list[tuple[str, list[tuple[str, int]]]] = []

        # --- Caches ---
        cache_items: list[tuple[str, int]] = []
        cache_dirs = [
            home / ".cache",
            home / ".npm" / "_cacache",
            home / ".pip" / "cache",
            home / ".cargo" / "registry",
        ]
        if is_mac:
            cache_dirs.append(home / "Library" / "Caches")

        for d in cache_dirs:
            if d.is_dir():
                size = _dir_size(d)
                if size > 1024:  # skip trivial
                    cache_items.append((str(d), size))

        if cache_items:
            categories.append(("Caches", sorted(cache_items, key=lambda x: -x[1])))

        # --- Temp files ---
        temp_items: list[tuple[str, int]] = []
        temp_dirs = [Path("/tmp"), Path("/var/tmp")]
        for d in temp_dirs:
            if d.is_dir():
                size = _dir_size(d, max_items=10000)
                if size > 1024:
                    temp_items.append((str(d), size))

        # DMG files in Downloads
        downloads = home / "Downloads"
        if downloads.is_dir():
            dmg_size = 0
            dmg_count = 0
            try:
                for f in downloads.iterdir():
                    if f.suffix.lower() in (".dmg", ".pkg", ".iso"):
                        try:
                            dmg_size += f.stat().st_size
                            dmg_count += 1
                        except OSError:
                            pass
            except PermissionError:
                pass
            if dmg_size > 0:
                temp_items.append((f"~/Downloads (*.dmg/*.pkg/*.iso — {dmg_count} files)", dmg_size))

        if temp_items:
            categories.append(("Temp / Installers", sorted(temp_items, key=lambda x: -x[1])))

        # --- Dev waste (node_modules, __pycache__, .tox, etc.) ---
        dev_items: list[tuple[str, int]] = []
        search_roots = [home / "Projects", home / "Developer", home / "code", home / "src"]
        # Also check workspace if set
        search_roots = [r for r in search_roots if r.is_dir()]
        if not search_roots:
            search_roots = [home]  # fallback

        for waste_name in ("node_modules", "__pycache__", ".tox", ".mypy_cache", "target", ".next"):
            found = []
            for root in search_roots:
                found.extend(_find_dirs_named(waste_name, root, max_depth=4))
            if found:
                total = sum(_dir_size(d, max_items=5000) for d in found[:20])
                if total > 10240:  # > 10 KB
                    dev_items.append((f"{waste_name} ({len(found)} dirs)", total))

        if dev_items:
            categories.append(("Dev Artifacts", sorted(dev_items, key=lambda x: -x[1])))

        # --- Logs ---
        log_items: list[tuple[str, int]] = []
        log_dirs = [Path("/var/log")]
        if is_mac:
            log_dirs.append(home / "Library" / "Logs")
        for d in log_dirs:
            if d.is_dir():
                size = _dir_size(d, max_items=5000)
                if size > 10240:
                    log_items.append((str(d), size))

        if log_items:
            categories.append(("Logs", sorted(log_items, key=lambda x: -x[1])))

        # --- ML Model Caches ---
        ml_items: list[tuple[str, int]] = []

        # EXO models
        exo_models = home / ".exo" / "models"
        if exo_models.is_dir():
            for d in sorted(exo_models.iterdir()):
                if d.is_dir() and d.name != "caches":
                    size = _dir_size(d)
                    if size > 1024:
                        ml_items.append((f"exo: {d.name}", size))

        # Hugging Face hub cache
        hf_hub = home / ".cache" / "huggingface" / "hub"
        if hf_hub.is_dir():
            for d in sorted(hf_hub.iterdir()):
                if d.is_dir() and d.name.startswith("models--"):
                    size = _dir_size(d)
                    if size > 1024:
                        pretty = d.name.replace("models--", "").replace("--", "/")
                        ml_items.append((f"hf: {pretty}", size))

        # Ollama models
        ollama_dir = home / ".ollama" / "models"
        if ollama_dir.is_dir():
            size = _dir_size(ollama_dir)
            if size > 1024:
                ml_items.append(("ollama models", size))

        if ml_items:
            categories.append(("ML Models", sorted(ml_items, key=lambda x: -x[1])))

        # --- Docker ---
        docker_output = await _run("docker system df 2>/dev/null", timeout=10)
        if docker_output and "TYPE" in docker_output:
            categories.append(("Docker", [("docker system df", 0)]))

        # --- Brew (macOS) ---
        brew_output = ""
        if is_mac:
            brew_output = await _run("brew cleanup --dry-run 2>/dev/null | tail -5", timeout=15)

        # --- Build report ---
        lines = ["=== Space-Ant Scan Report ===", ""]
        grand_total = 0

        for cat_name, items in categories:
            cat_total = sum(s for _, s in items)
            grand_total += cat_total
            if cat_name == "Docker":
                lines.append(f"## {cat_name}")
                lines.append(docker_output)
            else:
                lines.append(f"## {cat_name} ({_human_size(cat_total)})")
                for label, size in items[:10]:
                    lines.append(f"  {_human_size(size):>10}  {label}")
            lines.append("")

        if brew_output:
            lines.append("## Homebrew Cleanup")
            lines.append(f"  {brew_output}")
            lines.append("")

        if grand_total > 0:
            lines.append(f"Total reclaimable (estimated): {_human_size(grand_total)}")
        else:
            lines.append("No significant disk waste found.")

        lines.append("")
        lines.append("To clean safe targets (caches, __pycache__): use space_ant with action='clean', confirm=true")

        return "\n".join(lines)

    async def _clean(self) -> str:
        """Clean all safe targets — caches, dev waste, Xcode, Docker, Homebrew, installers."""
        home = Path.home()
        is_mac = platform.system() == "Darwin"
        cleaned: list[str] = []
        total_freed = 0

        def _record(label: str, size: int) -> None:
            cleaned.append(f"  {_human_size(size):>10}  {label}")
            nonlocal total_freed
            total_freed += size

        # --- Xcode caches (macOS) ---
        if is_mac:
            for name, path in [
                ("Xcode iOS DeviceSupport", home / "Library/Developer/Xcode/iOS DeviceSupport"),
                ("Xcode DerivedData", home / "Library/Developer/Xcode/DerivedData"),
                ("Xcode DocumentationCache", home / "Library/Developer/Xcode/DocumentationCache"),
            ]:
                if path.is_dir():
                    size = _dir_size(path)
                    if size > 1024:
                        await _run(f"rm -rf '{path}'", timeout=30)
                        if not path.exists():
                            _record(name, size)

        # --- Docker prune ---
        prune_out = await _run("docker volume prune -f 2>/dev/null", timeout=30)
        if prune_out and "Total reclaimed space" in prune_out:
            cleaned.append(f"             Docker volume prune: {prune_out.splitlines()[-1].strip()}")
        img_out = await _run("docker image prune -f 2>/dev/null", timeout=30)
        if img_out and "Total reclaimed space" in img_out:
            cleaned.append(f"             Docker image prune: {img_out.splitlines()[-1].strip()}")

        # --- Homebrew (macOS) ---
        if is_mac:
            brew_cache = home / "Library/Caches/Homebrew"
            if brew_cache.is_dir():
                size = _dir_size(brew_cache, max_items=10000)
                await _run("brew cleanup 2>/dev/null", timeout=30)
                after = _dir_size(brew_cache, max_items=10000) if brew_cache.exists() else 0
                freed = size - after
                if freed > 1024:
                    _record("Homebrew cache", freed)

        # --- Ollama models (if not in use) ---
        ollama_dir = home / ".ollama" / "models"
        if ollama_dir.is_dir():
            size = _dir_size(ollama_dir)
            if size > 1024:
                await _run(f"rm -rf '{ollama_dir}'", timeout=15)
                if not ollama_dir.exists():
                    _record("Ollama models", size)

        # --- Downloads installers (.dmg, .pkg, .iso) ---
        downloads = home / "Downloads"
        if downloads.is_dir():
            installer_freed = 0
            installer_count = 0
            try:
                for f in downloads.iterdir():
                    if f.suffix.lower() in (".dmg", ".pkg", ".iso"):
                        try:
                            size = f.stat().st_size
                            f.unlink()
                            installer_freed += size
                            installer_count += 1
                        except OSError:
                            pass
            except PermissionError:
                pass
            if installer_freed > 0:
                _record(f"Downloads installers ({installer_count} files)", installer_freed)

        # --- Temp files ---
        for tmp_path in (Path("/var/tmp"),):
            if tmp_path.is_dir():
                size = _dir_size(tmp_path, max_items=5000)
                if size > 1024:
                    await _run(f"rm -rf '{tmp_path}'/*", timeout=15)
                    after = _dir_size(tmp_path, max_items=5000) if tmp_path.exists() else 0
                    freed = size - after
                    if freed > 1024:
                        _record(str(tmp_path), freed)

        # --- Dev waste: __pycache__, .mypy_cache, .tox ---
        for waste_name in ("__pycache__", ".mypy_cache", ".tox"):
            for root in (home / "Projects", home / "Developer", home / "code", home / "src"):
                if not root.is_dir():
                    continue
                for d in _find_dirs_named(waste_name, root, max_depth=4):
                    size = _dir_size(d)
                    if size > 1024:
                        await _run(f"rm -rf '{d}'", timeout=10)
                        if not d.exists():
                            _record(f"{waste_name}: {d.name}", size)

        # --- pip / npm cache ---
        pip_cache = home / ".pip" / "cache"
        if pip_cache.is_dir():
            size = _dir_size(pip_cache)
            if size > 1024:
                await _run(f"rm -rf '{pip_cache}'", timeout=10)
                if not pip_cache.exists():
                    _record("pip cache", size)

        npm_cache = home / ".npm" / "_cacache"
        if npm_cache.is_dir():
            size = _dir_size(npm_cache)
            if size > 1024:
                await _run("npm cache clean --force 2>/dev/null", timeout=15)
                _record("npm cache", size)

        # --- Report ---
        if cleaned:
            report = "=== Space-Ant Clean Report ===\n\n" + "\n".join(cleaned)
            report += f"\n\nTotal freed: {_human_size(total_freed)}"
        else:
            report = "Nothing to clean — all targets were already empty or not found."

        return report
