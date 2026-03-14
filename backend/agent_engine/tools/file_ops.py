"""
File Operations Tool — read, write, edit, list files.
Gives the agent direct filesystem access like Claude Code / OpenClaw.
"""

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

from agent_engine.tools_base import BaseTool, register_tool

if TYPE_CHECKING:
    from agent_engine.agent import Agent

logger = logging.getLogger(__name__)


@register_tool
class ReadFileTool(BaseTool):
    """Read a file from the filesystem."""

    name = "read_file"
    description = (
        "Read the contents of a file. "
        "Args: path (file path to read), lines (optional, max lines to return)."
    )

    async def execute(self) -> str:
        path = self.args.get("path", "")
        max_lines = int(self.args.get("lines", 0))

        if not path:
            return "Error: No file path provided."

        path = os.path.expanduser(path)
        if not os.path.exists(path):
            return f"Error: File not found: {path}"
        if os.path.isdir(path):
            return f"Error: '{path}' is a directory, not a file. Use list_files instead."

        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                if max_lines > 0:
                    lines = []
                    for i, line in enumerate(f):
                        if i >= max_lines:
                            break
                        lines.append(line)
                    content = "".join(lines)
                    if i >= max_lines:
                        content += f"\n... (showing first {max_lines} lines)"
                else:
                    content = f.read()

            # Truncate very large files
            if len(content) > 50000:
                content = content[:50000] + f"\n\n... (truncated, {len(content)} chars total)"

            return content or "(empty file)"
        except Exception as e:
            return f"Error reading file: {str(e)}"


@register_tool
class WriteFileTool(BaseTool):
    """Write content to a file."""

    name = "write_file"
    description = (
        "Write content to a file. Creates the file if it doesn't exist. "
        "Args: path (file path), content (text to write), append (optional, true to append instead of overwrite)."
    )

    async def execute(self) -> str:
        path = self.args.get("path", "")
        content = self.args.get("content", "")
        append = str(self.args.get("append", "false")).lower() == "true"

        if not path:
            return "Error: No file path provided."

        path = os.path.expanduser(path)

        try:
            # Create parent directories if needed
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)

            mode = "a" if append else "w"
            with open(path, mode, encoding="utf-8") as f:
                f.write(content)

            action = "appended to" if append else "written to"
            return f"Successfully {action} {path} ({len(content)} chars)"
        except Exception as e:
            return f"Error writing file: {str(e)}"


@register_tool
class ListFilesTool(BaseTool):
    """List files and directories."""

    name = "list_files"
    description = (
        "List files and directories at a given path. "
        "Args: path (directory path, default '.'), pattern (optional glob pattern like '*.py'), recursive (optional, true for recursive listing)."
    )

    async def execute(self) -> str:
        path = self.args.get("path", ".")
        pattern = self.args.get("pattern", "")
        recursive = str(self.args.get("recursive", "false")).lower() == "true"

        path = os.path.expanduser(path)
        if not os.path.exists(path):
            return f"Error: Path not found: {path}"

        try:
            p = Path(path)

            if pattern:
                if recursive:
                    items = list(p.rglob(pattern))
                else:
                    items = list(p.glob(pattern))
            else:
                if recursive:
                    items = list(p.rglob("*"))
                else:
                    items = list(p.iterdir())

            if not items:
                return f"No files found in {path}" + (f" matching '{pattern}'" if pattern else "")

            # Sort: directories first, then files
            dirs = sorted([i for i in items if i.is_dir()])
            files = sorted([i for i in items if i.is_file()])

            output = []
            for d in dirs[:100]:
                output.append(f"  [DIR]  {d.relative_to(p) if not recursive else d}")
            for f in files[:200]:
                size = f.stat().st_size
                size_str = _format_size(size)
                output.append(f"  {size_str:>8}  {f.relative_to(p) if not recursive else f}")

            total = len(dirs) + len(files)
            result = f"{path} ({total} items)\n" + "\n".join(output)
            if total > 300:
                result += f"\n... (showing 300 of {total} items)"
            return result

        except Exception as e:
            return f"Error listing files: {str(e)}"


@register_tool
class EditFileTool(BaseTool):
    """Edit a file by replacing text."""

    name = "edit_file"
    description = (
        "Edit a file by finding and replacing text. "
        "Args: path (file path), old_text (text to find), new_text (replacement text)."
    )

    async def execute(self) -> str:
        path = self.args.get("path", "")
        old_text = self.args.get("old_text", "")
        new_text = self.args.get("new_text", "")

        if not path:
            return "Error: No file path provided."
        if not old_text:
            return "Error: No old_text provided to search for."

        path = os.path.expanduser(path)
        if not os.path.exists(path):
            return f"Error: File not found: {path}"

        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()

            if old_text not in content:
                return f"Error: old_text not found in {path}"

            count = content.count(old_text)
            new_content = content.replace(old_text, new_text)

            with open(path, "w", encoding="utf-8") as f:
                f.write(new_content)

            return f"Replaced {count} occurrence(s) in {path}"
        except Exception as e:
            return f"Error editing file: {str(e)}"


def _format_size(size: int) -> str:
    """Format file size in human-readable form."""
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.0f}{unit}" if unit == "B" else f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}TB"
