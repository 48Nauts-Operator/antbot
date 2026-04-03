"""File system tools: read, write, edit, list, tree."""

import difflib
from pathlib import Path
from typing import Any

from antbot.agent.tools.base import Tool


def _human_size(size: int) -> str:
    """Convert bytes to human-readable size string."""
    for unit in ("B", "KB", "MB", "GB"):
        if abs(size) < 1024:
            return f"{size:,.0f}{unit}" if unit == "B" else f"{size:,.1f}{unit}"
        size /= 1024
    return f"{size:,.1f}TB"


def _resolve_path(
    path: str, workspace: Path | None = None, allowed_dir: Path | None = None
) -> Path:
    """Resolve path against workspace (if relative) and enforce directory restriction."""
    p = Path(path).expanduser()
    if not p.is_absolute() and workspace:
        p = workspace / p
    resolved = p.resolve()
    if allowed_dir:
        try:
            resolved.relative_to(allowed_dir.resolve())
        except ValueError:
            raise PermissionError(f"Path {path} is outside allowed directory {allowed_dir}")
    return resolved


class ReadFileTool(Tool):
    """Tool to read file contents."""

    _MAX_CHARS = 128_000  # ~128 KB — prevents OOM from reading huge files into LLM context

    def __init__(self, workspace: Path | None = None, allowed_dir: Path | None = None):
        self._workspace = workspace
        self._allowed_dir = allowed_dir

    @property
    def name(self) -> str:
        return "read_file"

    @property
    def category(self) -> str:
        return "filesystem"

    @property
    def description(self) -> str:
        return "Read the contents of a file at the given path."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "The file path to read"}},
            "required": ["path"],
        }

    async def execute(self, path: str, **kwargs: Any) -> str:
        try:
            file_path = _resolve_path(path, self._workspace, self._allowed_dir)
            if not file_path.exists():
                return f"Error: File not found: {path}"
            if not file_path.is_file():
                return f"Error: Not a file: {path}"

            size = file_path.stat().st_size
            if size > self._MAX_CHARS * 4:  # rough upper bound (UTF-8 chars ≤ 4 bytes)
                return (
                    f"Error: File too large ({size:,} bytes). "
                    f"Use exec tool with head/tail/grep to read portions."
                )

            content = file_path.read_text(encoding="utf-8")
            if len(content) > self._MAX_CHARS:
                return content[: self._MAX_CHARS] + f"\n\n... (truncated — file is {len(content):,} chars, limit {self._MAX_CHARS:,})"
            return content
        except PermissionError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error reading file: {str(e)}"


class WriteFileTool(Tool):
    """Tool to write content to a file."""

    def __init__(self, workspace: Path | None = None, allowed_dir: Path | None = None):
        self._workspace = workspace
        self._allowed_dir = allowed_dir

    @property
    def name(self) -> str:
        return "write_file"

    @property
    def category(self) -> str:
        return "filesystem"

    @property
    def description(self) -> str:
        return "Write content to a file at the given path. Creates parent directories if needed."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "The file path to write to"},
                "content": {"type": "string", "description": "The content to write"},
            },
            "required": ["path", "content"],
        }

    async def execute(self, path: str, content: str, **kwargs: Any) -> str:
        try:
            file_path = _resolve_path(path, self._workspace, self._allowed_dir)
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
            return f"Successfully wrote {len(content)} bytes to {file_path}"
        except PermissionError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error writing file: {str(e)}"


class EditFileTool(Tool):
    """Tool to edit a file by replacing text."""

    def __init__(self, workspace: Path | None = None, allowed_dir: Path | None = None):
        self._workspace = workspace
        self._allowed_dir = allowed_dir

    @property
    def name(self) -> str:
        return "edit_file"

    @property
    def category(self) -> str:
        return "filesystem"

    @property
    def description(self) -> str:
        return "Edit a file by replacing old_text with new_text. The old_text must exist exactly in the file."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "The file path to edit"},
                "old_text": {"type": "string", "description": "The exact text to find and replace"},
                "new_text": {"type": "string", "description": "The text to replace with"},
            },
            "required": ["path", "old_text", "new_text"],
        }

    async def execute(self, path: str, old_text: str, new_text: str, **kwargs: Any) -> str:
        try:
            file_path = _resolve_path(path, self._workspace, self._allowed_dir)
            if not file_path.exists():
                return f"Error: File not found: {path}"

            content = file_path.read_text(encoding="utf-8")

            if old_text not in content:
                return self._not_found_message(old_text, content, path)

            # Count occurrences
            count = content.count(old_text)
            if count > 1:
                return f"Warning: old_text appears {count} times. Please provide more context to make it unique."

            new_content = content.replace(old_text, new_text, 1)
            file_path.write_text(new_content, encoding="utf-8")

            return f"Successfully edited {file_path}"
        except PermissionError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error editing file: {str(e)}"

    @staticmethod
    def _not_found_message(old_text: str, content: str, path: str) -> str:
        """Build a helpful error when old_text is not found."""
        lines = content.splitlines(keepends=True)
        old_lines = old_text.splitlines(keepends=True)
        window = len(old_lines)

        best_ratio, best_start = 0.0, 0
        for i in range(max(1, len(lines) - window + 1)):
            ratio = difflib.SequenceMatcher(None, old_lines, lines[i : i + window]).ratio()
            if ratio > best_ratio:
                best_ratio, best_start = ratio, i

        if best_ratio > 0.5:
            diff = "\n".join(
                difflib.unified_diff(
                    old_lines,
                    lines[best_start : best_start + window],
                    fromfile="old_text (provided)",
                    tofile=f"{path} (actual, line {best_start + 1})",
                    lineterm="",
                )
            )
            return f"Error: old_text not found in {path}.\nBest match ({best_ratio:.0%} similar) at line {best_start + 1}:\n{diff}"
        return (
            f"Error: old_text not found in {path}. No similar text found. Verify the file content."
        )


class ListDirTool(Tool):
    """Tool to list directory contents with sizes, grouped by type."""

    _MAX_ITEMS = 60  # Show at most this many items before summarising

    def __init__(self, workspace: Path | None = None, allowed_dir: Path | None = None):
        self._workspace = workspace
        self._allowed_dir = allowed_dir

    @property
    def name(self) -> str:
        return "list_dir"

    @property
    def category(self) -> str:
        return "filesystem"

    @property
    def description(self) -> str:
        return (
            "List the contents of a directory. Shows directories first, then files, "
            "with sizes. Large directories are automatically summarised."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "The directory path to list"},
            },
            "required": ["path"],
        }

    async def execute(self, path: str, **kwargs: Any) -> str:
        try:
            dir_path = _resolve_path(path, self._workspace, self._allowed_dir)
            if not dir_path.exists():
                return f"Error: Directory not found: {path}"
            if not dir_path.is_dir():
                return f"Error: Not a directory: {path}"

            dirs: list[str] = []
            files: list[tuple[str, int]] = []
            hidden_count = 0

            for item in sorted(dir_path.iterdir()):
                if item.name.startswith("."):
                    hidden_count += 1
                    continue
                if item.is_dir():
                    dirs.append(item.name)
                else:
                    try:
                        size = item.stat().st_size
                    except OSError:
                        size = 0
                    files.append((item.name, size))

            if not dirs and not files and hidden_count == 0:
                return f"Directory {path} is empty"

            lines: list[str] = []
            lines.append(f"📂 {dir_path.name}/")
            lines.append(f"   {len(dirs)} directories, {len(files)} files"
                         + (f", {hidden_count} hidden" if hidden_count else ""))
            lines.append("")

            # Directories
            if dirs:
                lines.append("Directories:")
                shown_dirs = dirs[:self._MAX_ITEMS]
                for d in shown_dirs:
                    lines.append(f"  📁 {d}/")
                if len(dirs) > self._MAX_ITEMS:
                    lines.append(f"  ... and {len(dirs) - self._MAX_ITEMS} more directories")
                lines.append("")

            # Files — show with sizes, right-aligned
            if files:
                lines.append("Files:")
                shown_files = files[:self._MAX_ITEMS]
                # Calculate column width for alignment
                max_name = max(len(f[0]) for f in shown_files)
                max_name = min(max_name, 50)  # Cap name width
                for fname, fsize in shown_files:
                    display_name = fname[:50] + "…" if len(fname) > 50 else fname
                    lines.append(f"  {display_name:<{min(max_name, 50)+1}} {_human_size(fsize):>8}")
                if len(files) > self._MAX_ITEMS:
                    remaining = files[self._MAX_ITEMS:]
                    total_remaining_size = sum(s for _, s in remaining)
                    lines.append(
                        f"  ... and {len(remaining)} more files "
                        f"({_human_size(total_remaining_size)} total)"
                    )

            return "\n".join(lines)
        except PermissionError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error listing directory: {str(e)}"


class TreeTool(Tool):
    """Tool to show a tree view of a directory structure."""

    _MAX_ITEMS = 200  # Hard limit on total items rendered

    def __init__(self, workspace: Path | None = None, allowed_dir: Path | None = None):
        self._workspace = workspace
        self._allowed_dir = allowed_dir

    @property
    def name(self) -> str:
        return "tree"

    @property
    def category(self) -> str:
        return "filesystem"

    @property
    def description(self) -> str:
        return (
            "Show a tree view of a directory structure with files and sizes. "
            "Use depth parameter to control how deep to recurse (default 2)."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "The directory path to show"},
                "depth": {
                    "type": "integer",
                    "description": "Max recursion depth (default 2, max 5)",
                },
            },
            "required": ["path"],
        }

    async def execute(self, path: str, depth: int = 2, **kwargs: Any) -> str:
        try:
            dir_path = _resolve_path(path, self._workspace, self._allowed_dir)
            if not dir_path.exists():
                return f"Error: Directory not found: {path}"
            if not dir_path.is_dir():
                return f"Error: Not a directory: {path}"

            depth = max(1, min(int(depth), 5))
            lines: list[str] = [f"{dir_path.name}/"]
            self._count = 0
            self._build_tree(dir_path, "", depth, lines)

            # Summary
            lines.append("")
            lines.append(f"({self._count} items shown, depth={depth})")
            return "\n".join(lines)
        except PermissionError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error building tree: {str(e)}"

    def _build_tree(
        self, dir_path: Path, prefix: str, remaining_depth: int, lines: list[str]
    ) -> None:
        if remaining_depth <= 0 or self._count >= self._MAX_ITEMS:
            return

        try:
            entries = sorted(
                dir_path.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())
            )
        except PermissionError:
            lines.append(f"{prefix}└── [permission denied]")
            return

        # Skip hidden files
        entries = [e for e in entries if not e.name.startswith(".")]

        for i, entry in enumerate(entries):
            if self._count >= self._MAX_ITEMS:
                lines.append(f"{prefix}└── ... ({len(entries) - i} more items)")
                break

            is_last = i == len(entries) - 1
            connector = "└── " if is_last else "├── "
            extension = "    " if is_last else "│   "

            if entry.is_dir():
                # Count children for summary
                try:
                    child_count = sum(1 for _ in entry.iterdir())
                except PermissionError:
                    child_count = 0
                lines.append(f"{prefix}{connector}📁 {entry.name}/ ({child_count} items)")
                self._count += 1
                self._build_tree(entry, prefix + extension, remaining_depth - 1, lines)
            else:
                try:
                    size = _human_size(entry.stat().st_size)
                except OSError:
                    size = "?"
                lines.append(f"{prefix}{connector}{entry.name}  [{size}]")
                self._count += 1
