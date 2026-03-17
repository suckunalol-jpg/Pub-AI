"""Tool registry for Pub AI agents.

Each tool is a callable that agents can invoke during their think-act-observe loop.
Covers: web, HTTP, code execution, file ops, git, network, Roblox, system,
sub-agents, memory, browser, code search, diagrams, and more.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse

import httpx

from config import settings
from executor.sandbox import sandbox


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class ToolResult:
    success: bool
    output: str
    data: Optional[Dict[str, Any]] = None


@dataclass
class ToolDef:
    name: str
    description: str
    parameters: Dict[str, Any]  # JSON-schema style param definitions
    fn: Callable  # async callable(params) -> ToolResult


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

_TOOLS: Dict[str, ToolDef] = {}

# Background bash sessions  {session_id: asyncio.subprocess.Process}
_BASH_SESSIONS: Dict[str, Any] = {}


def register_tool(name: str, description: str, parameters: Dict[str, Any]):
    """Decorator to register a tool."""
    def decorator(fn):
        _TOOLS[name] = ToolDef(name=name, description=description, parameters=parameters, fn=fn)
        return fn
    return decorator


def get_tool(name: str) -> Optional[ToolDef]:
    return _TOOLS.get(name)


def list_tools() -> List[Dict[str, Any]]:
    """Return tool schemas for the AI to choose from."""
    return [
        {"name": t.name, "description": t.description, "parameters": t.parameters}
        for t in _TOOLS.values()
    ]


def tools_prompt() -> str:
    """Build a text description of all available tools for the system prompt."""
    lines = ["\n## Available Tools\n"]
    for t in _TOOLS.values():
        params_desc = ""
        if isinstance(t.parameters, dict):
            parts = []
            for k, v in t.parameters.items():
                if isinstance(v, str):
                    parts.append(f'"{k}": "{v}"')
                elif isinstance(v, dict):
                    desc = v.get("description", "")
                    parts.append(f'"{k}": "{desc}"')
            params_desc = ", ".join(parts)
        lines.append(f"### {t.name}")
        lines.append(f"{t.description}")
        lines.append(f"Parameters: {{{params_desc}}}")
        lines.append("")

    lines.append("## How to Use Tools")
    lines.append("")
    lines.append("When you want to use a tool, output EXACTLY this format:")
    lines.append("")
    lines.append('```tool')
    lines.append('{"tool": "tool_name_here", "params": {"param1": "value1"}}')
    lines.append('```')
    lines.append("")
    lines.append("You can call multiple tools in one response by including multiple ```tool blocks.")
    lines.append("")
    lines.append("When your task is COMPLETE, output EXACTLY:")
    lines.append("")
    lines.append('```result')
    lines.append('{"status": "done", "output": "Your final answer here"}')
    lines.append('```')
    return "\n".join(lines)


async def execute_tool(name: str, params: Dict[str, Any], agent_id=None) -> ToolResult:
    tool = get_tool(name)
    if not tool:
        return ToolResult(success=False, output=f"Unknown tool: {name}")
    try:
        if agent_id is not None:
            params = dict(params)
            params["_agent_id"] = agent_id
        return await tool.fn(params)
    except Exception as e:
        return ToolResult(success=False, output=f"Tool error ({name}): {e}")


# ===========================================================================
# TOOL IMPLEMENTATIONS
# ===========================================================================

# ---------------------------------------------------------------------------
# 1. Web Search (DuckDuckGo HTML)
# ---------------------------------------------------------------------------

@register_tool(
    name="web_search",
    description="Search the web for real-time information. Returns top results with titles, URLs, and snippets. Use for current events, documentation lookups, or any info you don't have.",
    parameters={
        "query": "The search query string (keep short, 1-6 words for best results)",
        "max_results": "(optional) Number of results, default 5",
    },
)
async def tool_web_search(params: Dict[str, Any]) -> ToolResult:
    query = params.get("query", "")
    max_results = int(params.get("max_results", 5))
    if not query:
        return ToolResult(success=False, output="No query provided")

    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        resp = await client.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            headers={"User-Agent": "Mozilla/5.0 (compatible; PubAI/1.0)"},
        )
        resp.raise_for_status()

    html = resp.text
    results = []
    for match in re.finditer(
        r'<a rel="nofollow" class="result__a" href="([^"]+)"[^>]*>(.*?)</a>.*?'
        r'<a class="result__snippet"[^>]*>(.*?)</a>',
        html,
        re.DOTALL,
    ):
        if len(results) >= max_results:
            break
        url = match.group(1)
        title = re.sub(r"<[^>]+>", "", match.group(2)).strip()
        snippet = re.sub(r"<[^>]+>", "", match.group(3)).strip()
        results.append({"title": title, "url": url, "snippet": snippet})

    if not results:
        return ToolResult(success=True, output="No results found.", data={"results": []})

    output_lines = []
    for i, r in enumerate(results, 1):
        output_lines.append(f"{i}. **{r['title']}**\n   {r['url']}\n   {r['snippet']}")
    return ToolResult(success=True, output="\n\n".join(output_lines), data={"results": results})


# ---------------------------------------------------------------------------
# 2. Web Fetch (read a webpage)
# ---------------------------------------------------------------------------

@register_tool(
    name="web_fetch",
    description="Fetch and extract text content from a URL. Strips HTML for readability. Use after web_search to read full articles.",
    parameters={
        "url": "The URL to fetch",
        "max_length": "(optional) Max characters to return, default 8000",
    },
)
async def tool_web_fetch(params: Dict[str, Any]) -> ToolResult:
    url = params.get("url", "")
    max_length = int(params.get("max_length", 8000))
    if not url:
        return ToolResult(success=False, output="No URL provided")

    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0 (compatible; PubAI/1.0)"})
        resp.raise_for_status()

    text = re.sub(r"<script[^>]*>.*?</script>", "", resp.text, flags=re.DOTALL)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    if len(text) > max_length:
        text = text[:max_length] + "\n... (truncated)"

    return ToolResult(success=True, output=text)


# ---------------------------------------------------------------------------
# 3. Execute Code (sandboxed)
# ---------------------------------------------------------------------------

@register_tool(
    name="execute_code",
    description="Execute code in a sandboxed environment. Supports Python, JavaScript, and Lua.",
    parameters={"language": "python, javascript, or lua", "code": "The code to execute"},
)
async def tool_execute_code(params: Dict[str, Any]) -> ToolResult:
    language = params.get("language", "python")
    code = params.get("code", "")
    agent_id = params.pop("_agent_id", None)
    if not code:
        return ToolResult(success=False, output="No code provided")

    result = await sandbox.execute(language=language, code=code, agent_id=agent_id)
    success = result.get("exit_code", 1) == 0
    output = result.get("output", "")
    return ToolResult(success=success, output=output, data=result)


# ---------------------------------------------------------------------------
# 4. Read File (enhanced with line range support)
# ---------------------------------------------------------------------------

@register_tool(
    name="read_file",
    description="Read file contents. Supports optional line range. Returns 1-indexed lines.",
    parameters={
        "path": "Absolute or relative file path",
        "start_line": "(optional) 1-indexed start line",
        "end_line": "(optional) 1-indexed end line (inclusive)",
    },
)
async def tool_read_file(params: Dict[str, Any]) -> ToolResult:
    path = params.get("path", "")
    start = params.get("start_line")
    end = params.get("end_line")
    if not path:
        return ToolResult(success=False, output="No path provided")

    p = Path(path)
    if not p.exists():
        return ToolResult(success=False, output=f"File not found: {path}")
    if not p.is_file():
        return ToolResult(success=False, output=f"Not a file: {path}")

    try:
        content = p.read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines(keepends=True)

        if start or end:
            s = max(1, int(start or 1)) - 1
            e = min(len(lines), int(end or len(lines)))
            selected = lines[s:e]
            numbered = [f"{i+s+1}: {line}" for i, line in enumerate(selected)]
            result_text = "".join(numbered)
            info = f"Showing lines {s+1}-{e} of {len(lines)} total"
            return ToolResult(success=True, output=f"{info}\n{result_text}")

        if len(content) > 50000:
            content = content[:50000] + "\n... (truncated)"
        return ToolResult(success=True, output=content, data={"lines": len(lines)})
    except Exception as e:
        return ToolResult(success=False, output=f"Error reading file: {e}")


# ---------------------------------------------------------------------------
# 5. Write File
# ---------------------------------------------------------------------------

@register_tool(
    name="write_file",
    description="Write content to a file. Creates parent directories if needed. Use for creating new files.",
    parameters={"path": "File path", "content": "Content to write"},
)
async def tool_write_file(params: Dict[str, Any]) -> ToolResult:
    path = params.get("path", "")
    content = params.get("content", "")
    if not path:
        return ToolResult(success=False, output="No path provided")

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return ToolResult(success=True, output=f"Wrote {len(content)} bytes to {path}")


# ---------------------------------------------------------------------------
# 6. Edit File (find & replace — single occurrence)
# ---------------------------------------------------------------------------

@register_tool(
    name="edit_file",
    description="Edit a file by replacing an exact string with new content. The old_string must uniquely match.",
    parameters={
        "path": "File path",
        "old_string": "Exact text to find (must be unique in the file)",
        "new_string": "Replacement text",
    },
)
async def tool_edit_file(params: Dict[str, Any]) -> ToolResult:
    path = params.get("path", "")
    old = params.get("old_string", "")
    new = params.get("new_string", "")
    if not path or not old:
        return ToolResult(success=False, output="path and old_string are required")

    p = Path(path)
    if not p.exists():
        return ToolResult(success=False, output=f"File not found: {path}")

    content = p.read_text(encoding="utf-8")
    count = content.count(old)
    if count == 0:
        return ToolResult(success=False, output="old_string not found in file")
    if count > 1:
        return ToolResult(success=False, output=f"old_string found {count} times — must be unique. Add more context.")

    new_content = content.replace(old, new, 1)
    p.write_text(new_content, encoding="utf-8")
    return ToolResult(success=True, output=f"Edited {path}")


# ---------------------------------------------------------------------------
# 7. MultiEdit — multiple find-and-replace in one file
# ---------------------------------------------------------------------------

@register_tool(
    name="multi_edit",
    description="Apply multiple find-and-replace edits to a single file atomically. Each edit must have unique old_string.",
    parameters={
        "path": "File path",
        "edits": "List of {old_string, new_string} objects",
    },
)
async def tool_multi_edit(params: Dict[str, Any]) -> ToolResult:
    path = params.get("path", "")
    edits = params.get("edits", [])
    if not path or not edits:
        return ToolResult(success=False, output="path and edits are required")

    p = Path(path)
    if not p.exists():
        return ToolResult(success=False, output=f"File not found: {path}")

    content = p.read_text(encoding="utf-8")
    applied = 0

    for i, edit in enumerate(edits):
        old = edit.get("old_string", "")
        new = edit.get("new_string", "")
        if not old:
            continue
        if old not in content:
            return ToolResult(success=False, output=f"Edit {i+1}: old_string not found")
        content = content.replace(old, new, 1)
        applied += 1

    p.write_text(content, encoding="utf-8")
    return ToolResult(success=True, output=f"Applied {applied} edits to {path}")


# ---------------------------------------------------------------------------
# 8. List Directory
# ---------------------------------------------------------------------------

@register_tool(
    name="list_dir",
    description="List contents of a directory. Quick discovery tool before deeper file reading.",
    parameters={
        "path": "Directory path (default: current dir)",
        "pattern": "(optional) Glob pattern like '**/*.py'",
    },
)
async def tool_list_dir(params: Dict[str, Any]) -> ToolResult:
    path = params.get("path", ".")
    pattern = params.get("pattern", "*")

    p = Path(path)
    if not p.exists():
        return ToolResult(success=False, output=f"Directory not found: {path}")

    files = sorted(str(f) for f in p.glob(pattern))
    if not files:
        return ToolResult(success=True, output="No files found")

    if len(files) > 200:
        files = files[:200]
        files.append(f"... and more (showing first 200)")

    return ToolResult(success=True, output="\n".join(files), data={"files": files})


# ---------------------------------------------------------------------------
# 9. Grep Search (regex search in files)
# ---------------------------------------------------------------------------

@register_tool(
    name="grep_search",
    description="Fast exact regex search over files using pattern matching. Preferred for known symbol/function names. Results capped at 50.",
    parameters={
        "query": "Regex pattern to search for (escape special chars)",
        "path": "(optional) Directory to search in, default '.'",
        "include_pattern": "(optional) File glob like '*.py'",
        "case_sensitive": "(optional) true/false, default false",
    },
)
async def tool_grep_search(params: Dict[str, Any]) -> ToolResult:
    query = params.get("query", "")
    path = params.get("path", ".")
    file_pattern = params.get("include_pattern", "**/*")
    case_sensitive = params.get("case_sensitive", False)
    if not query:
        return ToolResult(success=False, output="No query provided")

    p = Path(path)
    if not p.exists():
        return ToolResult(success=False, output=f"Path not found: {path}")

    matches = []
    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        regex = re.compile(query, flags)
    except re.error:
        regex = re.compile(re.escape(query), flags)

    for file_path in p.glob(file_pattern):
        if not file_path.is_file():
            continue
        if file_path.stat().st_size > 1_000_000:
            continue
        try:
            lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
            for i, line in enumerate(lines, 1):
                if regex.search(line):
                    matches.append(f"{file_path}:{i}: {line.strip()}")
                    if len(matches) >= 50:
                        break
        except Exception:
            continue
        if len(matches) >= 50:
            break

    if not matches:
        return ToolResult(success=True, output="No matches found")

    return ToolResult(success=True, output="\n".join(matches), data={"count": len(matches)})


# ---------------------------------------------------------------------------
# 10. Codebase Search (semantic-style file content search)
# ---------------------------------------------------------------------------

@register_tool(
    name="codebase_search",
    description="Find code snippets most relevant to a natural language query. Searches file contents for semantic matches. Use when you don't know the exact symbol name.",
    parameters={
        "query": "Natural language search query",
        "path": "(optional) Directory to search in",
        "include_pattern": "(optional) File glob like '*.ts'",
    },
)
async def tool_codebase_search(params: Dict[str, Any]) -> ToolResult:
    query = params.get("query", "")
    path = params.get("path", ".")
    file_pattern = params.get("include_pattern", "**/*")
    if not query:
        return ToolResult(success=False, output="No query provided")

    # Split query into keywords for multi-word matching
    keywords = [w.lower() for w in query.split() if len(w) > 2]
    if not keywords:
        keywords = [query.lower()]

    p = Path(path)
    if not p.exists():
        return ToolResult(success=False, output=f"Path not found: {path}")

    scored_matches = []

    for file_path in p.glob(file_pattern):
        if not file_path.is_file():
            continue
        if file_path.stat().st_size > 1_000_000:
            continue
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
            content_lower = content.lower()
            # Score by how many keywords match
            score = sum(1 for kw in keywords if kw in content_lower)
            if score > 0:
                # Find best matching line range
                lines = content.splitlines()
                best_line = 0
                best_score = 0
                for i, line in enumerate(lines):
                    line_lower = line.lower()
                    ls = sum(1 for kw in keywords if kw in line_lower)
                    if ls > best_score:
                        best_score = ls
                        best_line = i

                # Extract context around best line
                start = max(0, best_line - 2)
                end = min(len(lines), best_line + 5)
                context = "\n".join(f"{start+j+1}: {lines[start+j]}" for j in range(end - start))
                scored_matches.append((score, best_score, str(file_path), context))
        except Exception:
            continue

    if not scored_matches:
        return ToolResult(success=True, output="No matches found")

    scored_matches.sort(key=lambda x: (x[0], x[1]), reverse=True)
    results = scored_matches[:10]

    output_parts = []
    for score, _, fpath, context in results:
        output_parts.append(f"**{fpath}** (relevance: {score}/{len(keywords)})\n{context}")

    return ToolResult(success=True, output="\n\n---\n\n".join(output_parts))


# ---------------------------------------------------------------------------
# 11. File Search (fuzzy filename search)
# ---------------------------------------------------------------------------

@register_tool(
    name="file_search",
    description="Fast fuzzy search for files by name. Use when you know part of a filename but not the full path. Returns up to 10 results.",
    parameters={
        "query": "Partial filename to search for",
        "path": "(optional) Root directory, default '.'",
    },
)
async def tool_file_search(params: Dict[str, Any]) -> ToolResult:
    query = params.get("query", "").lower()
    path = params.get("path", ".")
    if not query:
        return ToolResult(success=False, output="No query provided")

    p = Path(path)
    if not p.exists():
        return ToolResult(success=False, output=f"Path not found: {path}")

    matches = []
    for file_path in p.rglob("*"):
        if file_path.is_file() and query in file_path.name.lower():
            matches.append(str(file_path))
            if len(matches) >= 10:
                break

    if not matches:
        return ToolResult(success=True, output="No files found matching query")

    return ToolResult(success=True, output="\n".join(matches), data={"files": matches})


# ---------------------------------------------------------------------------
# 12. Delete File
# ---------------------------------------------------------------------------

@register_tool(
    name="delete_file",
    description="Delete a file at the specified path. Fails gracefully if file doesn't exist.",
    parameters={"path": "Path to the file to delete"},
)
async def tool_delete_file(params: Dict[str, Any]) -> ToolResult:
    path = params.get("path", "")
    if not path:
        return ToolResult(success=False, output="No path provided")

    p = Path(path)
    if not p.exists():
        return ToolResult(success=False, output=f"File not found: {path}")
    if not p.is_file():
        return ToolResult(success=False, output=f"Not a file: {path}")

    try:
        p.unlink()
        return ToolResult(success=True, output=f"Deleted {path}")
    except Exception as e:
        return ToolResult(success=False, output=f"Error deleting file: {e}")


# ---------------------------------------------------------------------------
# 13. Bash (shell command execution)
# ---------------------------------------------------------------------------

@register_tool(
    name="bash",
    description="Run a shell command. Use for git, npm, pip, build tools, etc. Timeout: 60s. Set is_background=true for long-running commands.",
    parameters={
        "command": "Shell command to execute",
        "is_background": "(optional) true to run in background, returns session_id",
        "cwd": "(optional) Working directory",
    },
)
async def tool_bash(params: Dict[str, Any]) -> ToolResult:
    command = params.get("command", "")
    is_bg = params.get("is_background", False)
    cwd = params.get("cwd")
    agent_id = params.pop("_agent_id", None)
    if not command:
        return ToolResult(success=False, output="No command provided")

    # Route through container if agent has workspace
    if agent_id is not None:
        from config import settings as _settings
        if _settings.WORKSPACE_ENABLED:
            from executor.container_manager import container_manager
            result = await container_manager.exec_command(agent_id, command, cwd=cwd)
            return ToolResult(
                success=(result.get("exit_code", 1) == 0),
                output=result.get("output", ""),
                data=result,
            )

    # Local fallback
    dangerous = ["rm -rf /", "mkfs", "dd if=", ":(){", "fork bomb", "shutdown", "reboot"]
    for d in dangerous:
        if d in command.lower():
            return ToolResult(success=False, output="Blocked dangerous command")

    try:
        if is_bg:
            session_id = str(uuid.uuid4())[:8]
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=cwd,
            )
            _BASH_SESSIONS[session_id] = proc
            return ToolResult(success=True, output=f"Background session started: {session_id} (PID: {proc.pid})",
                            data={"session_id": session_id, "pid": proc.pid})

        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=cwd,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
        output = stdout.decode("utf-8", errors="replace")
        if len(output) > 20000:
            output = output[:20000] + "\n... (truncated)"
        return ToolResult(
            success=(proc.returncode == 0),
            output=output,
            data={"exit_code": proc.returncode},
        )
    except asyncio.TimeoutError:
        proc.kill()
        return ToolResult(success=False, output="Command timed out after 60s")


# ---------------------------------------------------------------------------
# 14. Bash Output (read output from background session)
# ---------------------------------------------------------------------------

@register_tool(
    name="bash_output",
    description="Read output from a background bash session. Use after starting a background command.",
    parameters={"session_id": "Session ID from a background bash command"},
)
async def tool_bash_output(params: Dict[str, Any]) -> ToolResult:
    session_id = params.get("session_id", "")
    if not session_id:
        return ToolResult(success=False, output="No session_id provided")

    proc = _BASH_SESSIONS.get(session_id)
    if not proc:
        return ToolResult(success=False, output=f"Session not found: {session_id}")

    if proc.returncode is not None:
        stdout = await proc.stdout.read() if proc.stdout else b""
        output = stdout.decode("utf-8", errors="replace")
        _BASH_SESSIONS.pop(session_id, None)
        return ToolResult(success=True, output=f"[COMPLETED exit={proc.returncode}]\n{output}")

    # Read available output without blocking
    try:
        data = await asyncio.wait_for(proc.stdout.read(4096), timeout=1.0) if proc.stdout else b""
        return ToolResult(success=True, output=f"[RUNNING]\n{data.decode('utf-8', errors='replace')}")
    except asyncio.TimeoutError:
        return ToolResult(success=True, output="[RUNNING] No new output")


# ---------------------------------------------------------------------------
# 15. Kill Bash (terminate background session)
# ---------------------------------------------------------------------------

@register_tool(
    name="kill_bash",
    description="Kill a running background bash session.",
    parameters={"session_id": "Session ID to kill"},
)
async def tool_kill_bash(params: Dict[str, Any]) -> ToolResult:
    session_id = params.get("session_id", "")
    proc = _BASH_SESSIONS.pop(session_id, None)
    if not proc:
        return ToolResult(success=False, output=f"Session not found: {session_id}")

    proc.kill()
    return ToolResult(success=True, output=f"Killed session {session_id}")


# ---------------------------------------------------------------------------
# 16. Spawn Sub-Agent (Task tool)
# ---------------------------------------------------------------------------

@register_tool(
    name="spawn_agent",
    description="Launch a sub-agent to handle a specific task autonomously. Agent types: general-purpose, coder, researcher, reviewer, executor, planner, roblox, browser.",
    parameters={
        "agent_type": "Agent type to spawn",
        "task": "Description of the task for the sub-agent",
        "config": "(optional) Extra configuration dict",
    },
)
async def tool_spawn_agent(params: Dict[str, Any]) -> ToolResult:
    from agents.orchestrator import orchestrator
    from db.database import async_session

    agent_type = params.get("agent_type", "general-purpose")
    task = params.get("task", "")
    config = params.get("config", {})
    if not task:
        return ToolResult(success=False, output="No task provided")

    async with async_session() as db:
        session = await orchestrator.spawn(
            db=db,
            agent_type=agent_type,
            task=task,
            conversation_id=uuid.uuid4(),
            config=config,
        )
        await db.commit()

    return ToolResult(
        success=True,
        output=f"Spawned {agent_type} agent: {session.agent_name} (ID: {session.id})",
        data={"agent_id": str(session.id), "agent_name": session.agent_name},
    )


# ---------------------------------------------------------------------------
# 17. Message Agent
# ---------------------------------------------------------------------------

@register_tool(
    name="message_agent",
    description="Send a message to a running agent and get their response.",
    parameters={"agent_id": "UUID of the agent", "message": "Message to send"},
)
async def tool_message_agent(params: Dict[str, Any]) -> ToolResult:
    from agents.orchestrator import orchestrator

    agent_id_str = params.get("agent_id", "")
    message = params.get("message", "")
    if not agent_id_str or not message:
        return ToolResult(success=False, output="agent_id and message are required")

    try:
        agent_id = uuid.UUID(agent_id_str)
        response = await orchestrator.send_message(agent_id, message)
        return ToolResult(success=True, output=response)
    except ValueError as e:
        return ToolResult(success=False, output=str(e))


# ---------------------------------------------------------------------------
# 18. Wait for Agent
# ---------------------------------------------------------------------------

@register_tool(
    name="wait_agent",
    description="Wait for a sub-agent to complete and return its result.",
    parameters={"agent_id": "UUID of the agent to wait for"},
)
async def tool_wait_agent(params: Dict[str, Any]) -> ToolResult:
    from agents.orchestrator import orchestrator

    agent_id_str = params.get("agent_id", "")
    if not agent_id_str:
        return ToolResult(success=False, output="agent_id is required")

    agent_id = uuid.UUID(agent_id_str)
    agent = orchestrator.get_agent(agent_id)
    if not agent:
        return ToolResult(success=False, output="Agent not found")

    for _ in range(300):
        if agent.status in ("completed", "failed"):
            break
        await asyncio.sleep(1)

    if agent.status == "completed":
        content = agent.result.get("content", "") if agent.result else ""
        return ToolResult(success=True, output=content, data=agent.result)
    elif agent.status == "failed":
        error = agent.result.get("error", "Unknown") if agent.result else "Unknown"
        return ToolResult(success=False, output=f"Agent failed: {error}")
    else:
        return ToolResult(success=False, output="Agent timed out (5 min)")


# ---------------------------------------------------------------------------
# 19. Plan Tasks
# ---------------------------------------------------------------------------

@register_tool(
    name="plan_tasks",
    description="Break a complex task into ordered sub-tasks with dependencies. Returns a structured task plan.",
    parameters={"description": "Description of the complex task to plan"},
)
async def tool_plan_tasks(params: Dict[str, Any]) -> ToolResult:
    from ai.provider import ai_provider

    description = params.get("description", "")
    if not description:
        return ToolResult(success=False, output="No description provided")

    prompt = f"""Break this task into concrete, actionable sub-tasks. For each sub-task specify:
- id (short string)
- description (what to do)
- agent_type (general-purpose/coder/researcher/reviewer/executor/planner/roblox/browser)
- depends_on (list of task ids that must complete first, or empty)

Return ONLY valid JSON array. No explanation.

Task: {description}"""

    resp = await ai_provider.chat(messages=[{"role": "user", "content": prompt}], temperature=0.3)

    content = resp.content
    json_match = re.search(r"\[.*\]", content, re.DOTALL)
    if json_match:
        try:
            tasks = json.loads(json_match.group())
            formatted = json.dumps(tasks, indent=2)
            return ToolResult(success=True, output=formatted, data={"tasks": tasks})
        except json.JSONDecodeError:
            pass

    return ToolResult(success=True, output=content)


# ---------------------------------------------------------------------------
# 20. TodoWrite — create/update a task checklist
# ---------------------------------------------------------------------------

@register_tool(
    name="todo_write",
    description="Create or update a task checklist. Use to track progress on multi-step work.",
    parameters={
        "todos": "List of {id, task, status} objects. status: pending|in_progress|completed",
    },
)
async def tool_todo_write(params: Dict[str, Any]) -> ToolResult:
    todos = params.get("todos", [])
    if not todos:
        return ToolResult(success=False, output="No todos provided")

    lines = ["## Task List\n"]
    for t in todos:
        status = t.get("status", "pending")
        icon = {"pending": "[ ]", "in_progress": "[/]", "completed": "[x]"}.get(status, "[ ]")
        lines.append(f"- {icon} {t.get('task', t.get('id', ''))}")

    output = "\n".join(lines)
    return ToolResult(success=True, output=output, data={"todos": todos})


# ---------------------------------------------------------------------------
# 21. HTTP Request
# ---------------------------------------------------------------------------

@register_tool(
    name="http_request",
    description="Make an HTTP request with full control over method, headers, body, and proxy.",
    parameters={
        "method": "GET, POST, PUT, DELETE, PATCH, HEAD, OPTIONS",
        "url": "Target URL",
        "headers": "(optional) JSON object of headers",
        "body": "(optional) Request body (string or JSON)",
        "timeout": "(optional) Timeout in seconds, default 30",
    },
)
async def tool_http_request(params: Dict[str, Any]) -> ToolResult:
    method = params.get("method", "GET").upper()
    url = params.get("url", "")
    headers = params.get("headers", {})
    body = params.get("body")
    timeout = float(params.get("timeout", 30))

    if not url:
        return ToolResult(success=False, output="No URL provided")

    if isinstance(headers, str):
        try:
            headers = json.loads(headers)
        except json.JSONDecodeError:
            headers = {}

    kwargs: Dict[str, Any] = {
        "method": method, "url": url, "headers": headers,
        "timeout": timeout, "follow_redirects": True,
    }

    if body:
        if isinstance(body, dict):
            kwargs["json"] = body
        else:
            kwargs["content"] = str(body)

    async with httpx.AsyncClient() as client:
        resp = await client.request(**kwargs)

    body_text = resp.text
    if len(body_text) > 15000:
        body_text = body_text[:15000] + "\n... (truncated)"

    return ToolResult(
        success=(200 <= resp.status_code < 400),
        output=f"HTTP {resp.status_code}\n\nBody:\n{body_text}",
        data={"status_code": resp.status_code, "body_length": len(resp.text)},
    )


# ---------------------------------------------------------------------------
# 22. Roblox Script Scanner
# ---------------------------------------------------------------------------

@register_tool(
    name="roblox_scan",
    description="Scan Roblox/Luau scripts for security issues, performance, exploits, and code quality.",
    parameters={
        "scripts": "List of {name, source, type} objects OR a single script string",
        "scan_type": "(optional) 'quick' or 'deep', default 'deep'",
    },
)
async def tool_roblox_scan(params: Dict[str, Any]) -> ToolResult:
    from ai.provider import ai_provider
    from ai.prompts import ROBLOX_SYSTEM_PROMPT

    scripts = params.get("scripts", [])
    scan_type = params.get("scan_type", "deep")

    if isinstance(scripts, str):
        scripts = [{"name": "script", "source": scripts, "type": "unknown"}]
    if not scripts:
        return ToolResult(success=False, output="No scripts provided")

    script_blocks = []
    for s in scripts[:10]:
        name = s.get("name", "Unknown")
        stype = s.get("type", "Script")
        source = s.get("source", "")
        if len(source) > 5000:
            source = source[:5000] + "\n-- ... (truncated)"
        script_blocks.append(f"### {name} ({stype})\n```lua\n{source}\n```")

    depth = "thorough, line-by-line" if scan_type == "deep" else "high-level overview"

    prompt = f"""Perform a {depth} analysis of these {len(scripts)} Roblox scripts.

For each script, analyze:
1. **Security**: Remote event validation, client trust, data sanitization
2. **Performance**: Memory leaks, O(n^2) loops, unnecessary Instance creation
3. **Exploits**: Potential abuse vectors, missing server validation
4. **Code Quality**: Naming, modularity, error handling

Rate each issue: CRITICAL / WARNING / INFO

{chr(10).join(script_blocks)}"""

    messages = [
        {"role": "system", "content": ROBLOX_SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]

    resp = await ai_provider.chat(messages=messages, max_tokens=4096)
    return ToolResult(success=True, output=resp.content, data={"model": resp.model})


# ---------------------------------------------------------------------------
# 23. Create Project (scaffold)
# ---------------------------------------------------------------------------

@register_tool(
    name="create_project",
    description="Scaffold a new project from a natural language description.",
    parameters={
        "description": "What to build",
        "path": "Where to create the project",
        "stack": "(optional) Tech stack hint: python, node, react, roblox",
    },
)
async def tool_create_project(params: Dict[str, Any]) -> ToolResult:
    from ai.provider import ai_provider

    description = params.get("description", "")
    path = params.get("path", "./new-project")
    stack = params.get("stack", "")
    if not description:
        return ToolResult(success=False, output="No description provided")

    prompt = f"""Generate a complete project scaffold for: {description}
{"Tech stack: " + stack if stack else "Choose the best stack."}

Return a JSON object with this shape:
{{
  "files": {{
    "relative/path/file.ext": "file contents",
    ...
  }}
}}

Include ALL necessary files. Return ONLY the JSON."""

    resp = await ai_provider.chat(
        messages=[{"role": "user", "content": prompt}],
        temperature=0.4, max_tokens=8192,
    )

    content = resp.content
    json_match = re.search(r"\{.*\}", content, re.DOTALL)
    if not json_match:
        return ToolResult(success=False, output="Failed to generate project structure")

    try:
        project = json.loads(json_match.group())
        files = project.get("files", {})

        base = Path(path)
        created = []
        for file_path, file_content in files.items():
            full_path = base / file_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(str(file_content), encoding="utf-8")
            created.append(str(full_path))

        return ToolResult(
            success=True,
            output=f"Created {len(created)} files in {path}:\n" + "\n".join(f"  {f}" for f in created),
            data={"files": created},
        )
    except Exception as e:
        return ToolResult(success=False, output=f"Error creating project: {e}")


# ---------------------------------------------------------------------------
# 24. Create Diagram (Mermaid)
# ---------------------------------------------------------------------------

@register_tool(
    name="create_diagram",
    description="Create a Mermaid diagram from a DSL string. Returns the diagram definition for rendering.",
    parameters={"content": "Raw Mermaid diagram definition (e.g., 'graph TD; A-->B;')"},
)
async def tool_create_diagram(params: Dict[str, Any]) -> ToolResult:
    content = params.get("content", "")
    if not content:
        return ToolResult(success=False, output="No diagram content provided")

    return ToolResult(
        success=True,
        output=f"```mermaid\n{content}\n```",
        data={"type": "mermaid", "content": content},
    )


# ---------------------------------------------------------------------------
# 25. System Info
# ---------------------------------------------------------------------------

@register_tool(
    name="system_info",
    description="Get system information: OS, CPU, memory, disk, Python version.",
    parameters={},
)
async def tool_system_info(params: Dict[str, Any]) -> ToolResult:
    info = {
        "platform": platform.system(),
        "version": platform.version(),
        "architecture": platform.architecture()[0],
        "python": platform.python_version(),
        "hostname": platform.node(),
        "cwd": str(Path.cwd()),
    }

    try:
        import psutil
        mem = psutil.virtual_memory()
        info["memory_total_gb"] = round(mem.total / (1024**3), 1)
        info["memory_used_pct"] = mem.percent
        disk = psutil.disk_usage("/")
        info["disk_total_gb"] = round(disk.total / (1024**3), 1)
        info["disk_used_pct"] = round(disk.used / disk.total * 100, 1)
    except ImportError:
        pass

    formatted = "\n".join(f"**{k}**: {v}" for k, v in info.items())
    return ToolResult(success=True, output=formatted, data=info)


# ---------------------------------------------------------------------------
# 26. Git Operations
# ---------------------------------------------------------------------------

@register_tool(
    name="git",
    description="Run git commands: status, log, diff, add, commit, push, pull, clone, branch, checkout, etc.",
    parameters={
        "command": "Git subcommand and arguments (e.g., 'status', 'log -5', 'diff HEAD~1')",
        "cwd": "(optional) Working directory",
    },
)
async def tool_git(params: Dict[str, Any]) -> ToolResult:
    command = params.get("command", "")
    cwd = params.get("cwd")
    if not command:
        return ToolResult(success=False, output="No git command provided")

    full_cmd = f"git {command}"

    try:
        proc = await asyncio.create_subprocess_shell(
            full_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=cwd,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
        output = stdout.decode("utf-8", errors="replace")
        if len(output) > 20000:
            output = output[:20000] + "\n... (truncated)"
        return ToolResult(success=(proc.returncode == 0), output=output, data={"exit_code": proc.returncode})
    except asyncio.TimeoutError:
        return ToolResult(success=False, output="Git command timed out after 60s")


# ---------------------------------------------------------------------------
# 27. Navigate (browser)
# ---------------------------------------------------------------------------

@register_tool(
    name="navigate",
    description="Navigate a browser tab to a URL, or go forward/back in history. Requires browser automation backend.",
    parameters={
        "url": "URL to navigate to, or 'back'/'forward'",
        "tab_id": "(optional) Tab ID to navigate",
    },
)
async def tool_navigate(params: Dict[str, Any]) -> ToolResult:
    url = params.get("url", "")
    if not url:
        return ToolResult(success=False, output="No URL provided")
    # Placeholder — requires Playwright/Puppeteer integration
    return ToolResult(
        success=True,
        output=f"Navigation requested: {url} (browser automation not yet configured)",
        data={"url": url, "status": "pending_browser_setup"},
    )


# ---------------------------------------------------------------------------
# 28. Computer (browser mouse/keyboard)
# ---------------------------------------------------------------------------

@register_tool(
    name="computer",
    description="Interact with a browser using mouse and keyboard. Actions: left_click, right_click, type, screenshot, wait, scroll, key, double_click, hover.",
    parameters={
        "action": "Action to perform (left_click, type, screenshot, scroll, key, wait, etc.)",
        "coordinate": "(optional) [x, y] pixel coordinates for click actions",
        "text": "(optional) Text to type or key to press",
        "scroll_direction": "(optional) up/down/left/right",
        "duration": "(optional) Wait duration in seconds",
        "tab_id": "(optional) Tab ID to act on",
    },
)
async def tool_computer(params: Dict[str, Any]) -> ToolResult:
    action = params.get("action", "")
    if not action:
        return ToolResult(success=False, output="No action provided")
    # Placeholder — requires browser automation
    return ToolResult(
        success=True,
        output=f"Browser action '{action}' requested (browser automation not yet configured)",
        data={"action": action, "status": "pending_browser_setup"},
    )


# ---------------------------------------------------------------------------
# 29. Read Page (DOM/accessibility tree)
# ---------------------------------------------------------------------------

@register_tool(
    name="read_page",
    description="Get an accessibility tree representation of a browser page. Filter for interactive elements only or all elements.",
    parameters={
        "tab_id": "Tab ID to read from",
        "filter": "(optional) 'interactive' for buttons/links/inputs only, 'all' for everything",
    },
)
async def tool_read_page(params: Dict[str, Any]) -> ToolResult:
    return ToolResult(
        success=True,
        output="Page reading requested (browser automation not yet configured)",
        data={"status": "pending_browser_setup"},
    )


# ---------------------------------------------------------------------------
# 30. Find (natural language element search)
# ---------------------------------------------------------------------------

@register_tool(
    name="find",
    description="Find elements on a browser page using natural language description. Returns matching elements with references.",
    parameters={
        "query": "Natural language description of what to find (e.g., 'search bar', 'login button')",
        "tab_id": "Tab ID to search in",
    },
)
async def tool_find(params: Dict[str, Any]) -> ToolResult:
    return ToolResult(
        success=True,
        output="Element search requested (browser automation not yet configured)",
        data={"status": "pending_browser_setup"},
    )


# ---------------------------------------------------------------------------
# 31. JavaScript Execution (in browser)
# ---------------------------------------------------------------------------

@register_tool(
    name="javascript",
    description="Execute JavaScript code in the context of the current browser page. Returns the result of the last expression.",
    parameters={
        "code": "JavaScript code to execute",
        "tab_id": "Tab ID to execute in",
    },
)
async def tool_javascript(params: Dict[str, Any]) -> ToolResult:
    return ToolResult(
        success=True,
        output="JavaScript execution requested (browser automation not yet configured)",
        data={"status": "pending_browser_setup"},
    )


# ---------------------------------------------------------------------------
# 32. Form Input (browser)
# ---------------------------------------------------------------------------

@register_tool(
    name="form_input",
    description="Set values in browser form elements using element references.",
    parameters={
        "ref": "Element reference ID from read_page or find",
        "value": "Value to set (string, boolean, or number)",
        "tab_id": "Tab ID to set form value in",
    },
)
async def tool_form_input(params: Dict[str, Any]) -> ToolResult:
    return ToolResult(
        success=True,
        output="Form input requested (browser automation not yet configured)",
        data={"status": "pending_browser_setup"},
    )


# ---------------------------------------------------------------------------
# 33. Tabs Context
# ---------------------------------------------------------------------------

@register_tool(
    name="tabs_context",
    description="Get context information about all open browser tabs.",
    parameters={},
)
async def tool_tabs_context(params: Dict[str, Any]) -> ToolResult:
    return ToolResult(
        success=True,
        output="Tabs context requested (browser automation not yet configured)",
        data={"status": "pending_browser_setup"},
    )


# ---------------------------------------------------------------------------
# 34. Screenshot / Zoom
# ---------------------------------------------------------------------------

@register_tool(
    name="screenshot",
    description="Take a screenshot of the current browser page or a specific region.",
    parameters={
        "tab_id": "Tab ID to screenshot",
        "region": "(optional) [x0, y0, x1, y1] to capture a specific area",
    },
)
async def tool_screenshot(params: Dict[str, Any]) -> ToolResult:
    return ToolResult(
        success=True,
        output="Screenshot requested (browser automation not yet configured)",
        data={"status": "pending_browser_setup"},
    )


# ---------------------------------------------------------------------------
# 35. Read Console Messages (browser)
# ---------------------------------------------------------------------------

@register_tool(
    name="read_console",
    description="Read browser console messages (log, error, warn). Useful for debugging JavaScript.",
    parameters={
        "tab_id": "Tab ID to read console from",
        "only_errors": "(optional) true to only return errors",
        "pattern": "(optional) Regex pattern to filter messages",
    },
)
async def tool_read_console(params: Dict[str, Any]) -> ToolResult:
    return ToolResult(
        success=True,
        output="Console reading requested (browser automation not yet configured)",
        data={"status": "pending_browser_setup"},
    )


# ---------------------------------------------------------------------------
# 36. Read Network Requests (browser)
# ---------------------------------------------------------------------------

@register_tool(
    name="read_network",
    description="Read HTTP network requests from a browser tab. Useful for debugging API calls.",
    parameters={
        "tab_id": "Tab ID to read from",
        "url_pattern": "(optional) Filter requests by URL pattern",
    },
)
async def tool_read_network(params: Dict[str, Any]) -> ToolResult:
    return ToolResult(
        success=True,
        output="Network reading requested (browser automation not yet configured)",
        data={"status": "pending_browser_setup"},
    )


# ===========================================================================
# RESTORED ORIGINAL TOOLS (kept from previous codebase)
# ===========================================================================

# ---------------------------------------------------------------------------
# 37. Shell Command (legacy alias for bash)
# ---------------------------------------------------------------------------

@register_tool(
    name="shell",
    description="Run a shell command (legacy alias for bash). Use for git, npm, pip, build tools, etc. Timeout: 60s.",
    parameters={"command": "Shell command to execute"},
)
async def tool_shell(params: Dict[str, Any]) -> ToolResult:
    return await tool_bash({"command": params.get("command", "")})


# ---------------------------------------------------------------------------
# 38. List Files (legacy alias for list_dir)
# ---------------------------------------------------------------------------

@register_tool(
    name="list_files",
    description="List files in a directory, optionally matching a glob pattern. Legacy alias for list_dir.",
    parameters={
        "path": "Directory path (default: current dir)",
        "pattern": "(optional) Glob pattern like '**/*.py'",
    },
)
async def tool_list_files(params: Dict[str, Any]) -> ToolResult:
    return await tool_list_dir(params)


# ---------------------------------------------------------------------------
# 39. Search Code (legacy alias for grep_search)
# ---------------------------------------------------------------------------

@register_tool(
    name="search_code",
    description="Search for a text pattern in files. Returns matching lines with file paths and line numbers.",
    parameters={
        "query": "Text or regex to search for",
        "path": "(optional) Directory to search in, default '.'",
        "file_pattern": "(optional) File glob like '*.py', default all files",
    },
)
async def tool_search_code(params: Dict[str, Any]) -> ToolResult:
    return await tool_grep_search({
        "query": params.get("query", ""),
        "path": params.get("path", "."),
        "include_pattern": params.get("file_pattern", "**/*"),
    })


# ---------------------------------------------------------------------------
# 40. DNS Lookup
# ---------------------------------------------------------------------------

@register_tool(
    name="dns_lookup",
    description="Look up DNS records for a domain.",
    parameters={"domain": "Domain name to look up"},
)
async def tool_dns_lookup(params: Dict[str, Any]) -> ToolResult:
    import socket
    domain = params.get("domain", "")
    if not domain:
        return ToolResult(success=False, output="No domain provided")

    try:
        ips = socket.getaddrinfo(domain, None, socket.AF_INET)
        ipv4 = list(set(addr[4][0] for addr in ips))

        try:
            ips6 = socket.getaddrinfo(domain, None, socket.AF_INET6)
            ipv6 = list(set(addr[4][0] for addr in ips6))
        except socket.gaierror:
            ipv6 = []

        output = f"Domain: {domain}\nIPv4: {', '.join(ipv4)}"
        if ipv6:
            output += f"\nIPv6: {', '.join(ipv6)}"

        return ToolResult(success=True, output=output, data={"ipv4": ipv4, "ipv6": ipv6})
    except socket.gaierror as e:
        return ToolResult(success=False, output=f"DNS lookup failed: {e}")


# ---------------------------------------------------------------------------
# 41. Port Scanner (authorized security testing only)
# ---------------------------------------------------------------------------

@register_tool(
    name="port_scan",
    description="Scan common ports on a host. For authorized security testing only.",
    parameters={
        "host": "Target hostname or IP",
        "ports": "(optional) Comma-separated ports or range like '80,443,8080' or '1-1024'",
    },
)
async def tool_port_scan(params: Dict[str, Any]) -> ToolResult:
    import socket
    host = params.get("host", "")
    ports_str = params.get("ports", "21,22,25,53,80,443,3000,3306,5432,6379,8000,8080,8443,27017")

    if not host:
        return ToolResult(success=False, output="No host provided")

    ports = []
    for part in ports_str.split(","):
        part = part.strip()
        if "-" in part:
            start, end = part.split("-", 1)
            ports.extend(range(int(start), min(int(end) + 1, int(start) + 100)))
        else:
            ports.append(int(part))

    ports = ports[:200]

    open_ports = []
    for port in ports:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex((host, port))
            if result == 0:
                open_ports.append(port)
            sock.close()
        except Exception:
            continue

    if open_ports:
        output = f"Open ports on {host}: {', '.join(str(p) for p in open_ports)}"
    else:
        output = f"No open ports found on {host} (scanned {len(ports)} ports)"

    return ToolResult(success=True, output=output, data={"open_ports": open_ports})


# ---------------------------------------------------------------------------
# 42. JSON / YAML / XML Parser
# ---------------------------------------------------------------------------

@register_tool(
    name="parse_data",
    description="Parse and validate JSON, YAML, or XML data. Can also convert between formats.",
    parameters={
        "data": "The data string to parse",
        "format": "json, yaml, or xml",
        "convert_to": "(optional) Convert to another format",
    },
)
async def tool_parse_data(params: Dict[str, Any]) -> ToolResult:
    data = params.get("data", "")
    fmt = params.get("format", "json")

    if not data:
        return ToolResult(success=False, output="No data provided")

    try:
        if fmt == "json":
            parsed = json.loads(data)
            output = json.dumps(parsed, indent=2)
        elif fmt == "yaml":
            import yaml
            parsed = yaml.safe_load(data)
            output = yaml.dump(parsed, default_flow_style=False)
        elif fmt == "xml":
            import xml.etree.ElementTree as ET
            root = ET.fromstring(data)
            output = ET.tostring(root, encoding="unicode", method="xml")
        else:
            return ToolResult(success=False, output=f"Unknown format: {fmt}")

        return ToolResult(success=True, output=f"Valid {fmt}:\n{output}")
    except Exception as e:
        return ToolResult(success=False, output=f"Parse error: {e}")


# ---------------------------------------------------------------------------
# 43. Base64 Encode/Decode
# ---------------------------------------------------------------------------

@register_tool(
    name="base64_tool",
    description="Encode or decode base64 data.",
    parameters={"data": "Data to encode/decode", "action": "encode or decode"},
)
async def tool_base64_op(params: Dict[str, Any]) -> ToolResult:
    data = params.get("data", "")
    action = params.get("action", "encode")

    if action == "encode":
        result = base64.b64encode(data.encode()).decode()
    elif action == "decode":
        try:
            result = base64.b64decode(data).decode("utf-8", errors="replace")
        except Exception as e:
            return ToolResult(success=False, output=f"Decode error: {e}")
    else:
        return ToolResult(success=False, output="action must be 'encode' or 'decode'")

    return ToolResult(success=True, output=result)


# ---------------------------------------------------------------------------
# 44. Hash
# ---------------------------------------------------------------------------

@register_tool(
    name="hash_tool",
    description="Hash data with MD5, SHA1, SHA256, or SHA512.",
    parameters={"data": "Data to hash", "algorithm": "(optional) md5, sha1, sha256 (default), sha512"},
)
async def tool_hash_op(params: Dict[str, Any]) -> ToolResult:
    data = params.get("data", "")
    algo = params.get("algorithm", "sha256")

    h = hashlib.new(algo)
    h.update(data.encode())
    return ToolResult(success=True, output=f"{algo}: {h.hexdigest()}")


# ---------------------------------------------------------------------------
# 45. JWT Decode
# ---------------------------------------------------------------------------

@register_tool(
    name="jwt_decode",
    description="Decode a JWT token (without verification) to inspect its payload.",
    parameters={"token": "The JWT token string"},
)
async def tool_jwt_decode(params: Dict[str, Any]) -> ToolResult:
    token = params.get("token", "")
    if not token:
        return ToolResult(success=False, output="No token provided")

    parts = token.split(".")
    if len(parts) != 3:
        return ToolResult(success=False, output="Invalid JWT format (expected 3 parts)")

    def decode_part(part):
        padding = 4 - len(part) % 4
        part += "=" * padding
        return base64.urlsafe_b64decode(part).decode("utf-8", errors="replace")

    try:
        header = json.loads(decode_part(parts[0]))
        payload = json.loads(decode_part(parts[1]))
        return ToolResult(
            success=True,
            output=f"Header: {json.dumps(header, indent=2)}\n\nPayload: {json.dumps(payload, indent=2)}",
            data={"header": header, "payload": payload},
        )
    except Exception as e:
        return ToolResult(success=False, output=f"JWT decode error: {e}")


# ---------------------------------------------------------------------------
# 46. Regex Tester
# ---------------------------------------------------------------------------

@register_tool(
    name="regex_test",
    description="Test a regex pattern against text. Shows all matches with groups.",
    parameters={"pattern": "Regex pattern", "text": "Text to test against", "flags": "(optional) i, m, s, x"},
)
async def tool_regex_test(params: Dict[str, Any]) -> ToolResult:
    pattern_str = params.get("pattern", "")
    text = params.get("text", "")
    flags_str = params.get("flags", "")

    if not pattern_str:
        return ToolResult(success=False, output="No pattern provided")

    flags = 0
    if "i" in flags_str: flags |= re.IGNORECASE
    if "m" in flags_str: flags |= re.MULTILINE
    if "s" in flags_str: flags |= re.DOTALL
    if "x" in flags_str: flags |= re.VERBOSE

    try:
        compiled = re.compile(pattern_str, flags)
        matches = list(compiled.finditer(text))

        if not matches:
            return ToolResult(success=True, output="No matches found")

        lines = [f"Found {len(matches)} match(es):\n"]
        for i, m in enumerate(matches[:20]):
            lines.append(f"  Match {i+1}: '{m.group()}' at position {m.start()}-{m.end()}")
            if m.groups():
                for j, g in enumerate(m.groups(), 1):
                    lines.append(f"    Group {j}: '{g}'")

        return ToolResult(success=True, output="\n".join(lines))
    except re.error as e:
        return ToolResult(success=False, output=f"Regex error: {e}")


# ---------------------------------------------------------------------------
# 47. Diff Two Files / Strings
# ---------------------------------------------------------------------------

@register_tool(
    name="diff",
    description="Show differences between two files or two strings.",
    parameters={
        "file1": "(optional) First file path",
        "file2": "(optional) Second file path",
        "text1": "(optional) First text string",
        "text2": "(optional) Second text string",
    },
)
async def tool_diff(params: Dict[str, Any]) -> ToolResult:
    import difflib

    text1 = params.get("text1", "")
    text2 = params.get("text2", "")

    if params.get("file1"):
        try:
            text1 = Path(params["file1"]).read_text(encoding="utf-8")
        except Exception as e:
            return ToolResult(success=False, output=f"Error reading file1: {e}")
    if params.get("file2"):
        try:
            text2 = Path(params["file2"]).read_text(encoding="utf-8")
        except Exception as e:
            return ToolResult(success=False, output=f"Error reading file2: {e}")

    lines1 = text1.splitlines(keepends=True)
    lines2 = text2.splitlines(keepends=True)

    diff_result = list(difflib.unified_diff(
        lines1, lines2,
        fromfile=params.get("file1", "text1"),
        tofile=params.get("file2", "text2"),
    ))

    if not diff_result:
        return ToolResult(success=True, output="No differences found")

    output = "".join(diff_result)
    if len(output) > 10000:
        output = output[:10000] + "\n... (truncated)"
    return ToolResult(success=True, output=output)


# ---------------------------------------------------------------------------
# 48. Package Manager (npm, pip, cargo)
# ---------------------------------------------------------------------------

@register_tool(
    name="package_manager",
    description="Manage packages: install, uninstall, list, search. Supports npm, pip, and cargo.",
    parameters={
        "manager": "npm, pip, or cargo",
        "action": "install, uninstall, list, search, update, init",
        "packages": "(optional) Package names (comma-separated)",
        "path": "(optional) Working directory",
    },
)
async def tool_package_manager(params: Dict[str, Any]) -> ToolResult:
    manager = params.get("manager", "npm")
    action = params.get("action", "list")
    packages = params.get("packages", "")
    path = params.get("path", ".")

    pkg_list = [p.strip() for p in packages.split(",") if p.strip()] if packages else []

    commands = {
        "npm": {
            "install": f"npm install {' '.join(pkg_list)}",
            "uninstall": f"npm uninstall {' '.join(pkg_list)}",
            "list": "npm list --depth=0",
            "search": f"npm search {' '.join(pkg_list)}",
            "update": "npm update",
            "init": "npm init -y",
        },
        "pip": {
            "install": f"pip install {' '.join(pkg_list)}",
            "uninstall": f"pip uninstall -y {' '.join(pkg_list)}",
            "list": "pip list",
            "search": f"pip index versions {pkg_list[0]}" if pkg_list else "echo 'specify package'",
            "update": f"pip install --upgrade {' '.join(pkg_list)}" if pkg_list else "pip list --outdated",
            "init": "echo 'Use create_project for Python projects'",
        },
        "cargo": {
            "install": f"cargo add {' '.join(pkg_list)}",
            "uninstall": f"cargo remove {' '.join(pkg_list)}",
            "list": "cargo tree --depth 1",
            "search": f"cargo search {' '.join(pkg_list)}",
            "update": "cargo update",
            "init": "cargo init",
        },
    }

    if manager not in commands:
        return ToolResult(success=False, output=f"Unknown manager: {manager}")
    if action not in commands[manager]:
        return ToolResult(success=False, output=f"Unknown action: {action}")

    cmd = commands[manager][action]
    proc = await asyncio.create_subprocess_shell(
        cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, cwd=path,
    )
    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=120)
    output = stdout.decode("utf-8", errors="replace")

    return ToolResult(
        success=(proc.returncode == 0),
        output=output[:10000],
        data={"exit_code": proc.returncode},
    )


# ---------------------------------------------------------------------------
# 49. Process Manager
# ---------------------------------------------------------------------------

@register_tool(
    name="process_manager",
    description="List, find, or manage system processes.",
    parameters={
        "action": "list, find, kill",
        "name": "(optional) Process name to find",
        "pid": "(optional) Process ID to kill",
    },
)
async def tool_process_manager(params: Dict[str, Any]) -> ToolResult:
    action = params.get("action", "list")

    if action == "list":
        if platform.system() == "Windows":
            cmd = "tasklist /FO CSV /NH"
        else:
            cmd = "ps aux --sort=-%mem | head -30"
    elif action == "find":
        name = params.get("name", "")
        if not name:
            return ToolResult(success=False, output="No process name provided")
        if platform.system() == "Windows":
            cmd = f'tasklist /FI "IMAGENAME eq {name}*" /FO CSV'
        else:
            cmd = f"pgrep -la {name}"
    elif action == "kill":
        pid = params.get("pid", "")
        if not pid:
            return ToolResult(success=False, output="No PID provided")
        if platform.system() == "Windows":
            cmd = f"taskkill /F /PID {pid}"
        else:
            cmd = f"kill -9 {pid}"
    else:
        return ToolResult(success=False, output=f"Unknown action: {action}")

    proc = await asyncio.create_subprocess_shell(
        cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
    return ToolResult(
        success=(proc.returncode == 0),
        output=stdout.decode("utf-8", errors="replace")[:10000],
    )


# ---------------------------------------------------------------------------
# 50. Download File
# ---------------------------------------------------------------------------

@register_tool(
    name="download_file",
    description="Download a file from a URL to a local path.",
    parameters={"url": "URL to download from", "path": "Local path to save to"},
)
async def tool_download_file(params: Dict[str, Any]) -> ToolResult:
    url = params.get("url", "")
    path = params.get("path", "")
    if not url or not path:
        return ToolResult(success=False, output="url and path are required")

    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(resp.content)

    return ToolResult(
        success=True,
        output=f"Downloaded {len(resp.content)} bytes to {path}",
        data={"size": len(resp.content)},
    )


# ---------------------------------------------------------------------------
# 51. Compress / Decompress
# ---------------------------------------------------------------------------

@register_tool(
    name="compress",
    description="Compress or decompress files. Supports zip and tar.gz.",
    parameters={
        "action": "compress or decompress",
        "format": "zip or tar.gz",
        "source": "File or directory to compress, or archive to decompress",
        "destination": "Output path",
    },
)
async def tool_compress(params: Dict[str, Any]) -> ToolResult:
    action = params.get("action", "compress")
    fmt = params.get("format", "zip")
    source = params.get("source", "")
    dest = params.get("destination", "")

    if not source:
        return ToolResult(success=False, output="source is required")

    if action == "compress":
        if fmt == "zip":
            shutil.make_archive(dest.replace(".zip", ""), "zip", source)
        elif fmt == "tar.gz":
            shutil.make_archive(dest.replace(".tar.gz", ""), "gztar", source)
        return ToolResult(success=True, output=f"Compressed {source} to {dest}")
    elif action == "decompress":
        shutil.unpack_archive(source, dest or ".")
        return ToolResult(success=True, output=f"Decompressed {source} to {dest or '.'}")

    return ToolResult(success=False, output=f"Unknown action: {action}")


# ---------------------------------------------------------------------------
# 52. Database Query (SQLite/PostgreSQL via raw SQL)
# ---------------------------------------------------------------------------

@register_tool(
    name="database_query",
    description="Run a read-only SQL query against the app database.",
    parameters={"query": "SQL query (SELECT only for safety)"},
)
async def tool_database_query(params: Dict[str, Any]) -> ToolResult:
    query = params.get("query", "").strip()
    if not query:
        return ToolResult(success=False, output="No query provided")

    if not query.upper().startswith("SELECT"):
        return ToolResult(success=False, output="Only SELECT queries are allowed for safety")

    from sqlalchemy import text
    from db.database import async_session

    async with async_session() as db:
        result = await db.execute(text(query))
        rows = result.fetchall()
        columns = result.keys() if hasattr(result, 'keys') else []

        if not rows:
            return ToolResult(success=True, output="No rows returned")

        col_names = list(columns)
        lines = [" | ".join(col_names)]
        lines.append("-" * len(lines[0]))
        for row in rows[:100]:
            lines.append(" | ".join(str(v)[:50] for v in row))

        return ToolResult(
            success=True,
            output="\n".join(lines),
            data={"row_count": len(rows), "columns": col_names},
        )


# ---------------------------------------------------------------------------
# 53. Memory Store (per-user learning)
# ---------------------------------------------------------------------------

@register_tool(
    name="memory_store",
    description="Store a memory/fact about the current user for future reference.",
    parameters={
        "memory_type": "preference, fact, skill, pattern, correction, project",
        "key": "Short key/label for the memory",
        "value": "The memory content",
    },
)
async def tool_memory_store(params: Dict[str, Any]) -> ToolResult:
    mem_type = params.get("memory_type", "fact")
    key = params.get("key", "")
    value = params.get("value", "")

    if not key or not value:
        return ToolResult(success=False, output="key and value are required")

    return ToolResult(
        success=True,
        output=f"Memory queued: [{mem_type}] {key} = {value}",
        data={"memory_type": mem_type, "key": key, "value": value},
    )


# ---------------------------------------------------------------------------
# 54. Memory Retrieve
# ---------------------------------------------------------------------------

@register_tool(
    name="memory_retrieve",
    description="Search the user's stored memories for relevant context.",
    parameters={"query": "What to search for in memories"},
)
async def tool_memory_retrieve(params: Dict[str, Any]) -> ToolResult:
    return ToolResult(
        success=True,
        output="Memory retrieval happens automatically via the Brain system. "
               "Relevant memories are injected into your context.",
    )


# ---------------------------------------------------------------------------
# 55. Lint / Format Code
# ---------------------------------------------------------------------------

@register_tool(
    name="lint_code",
    description="Lint or format code. Supports Python (ruff/black), JavaScript (eslint/prettier), Lua.",
    parameters={
        "path": "File or directory to lint",
        "language": "(optional) python, javascript, lua",
        "fix": "(optional) true to auto-fix issues",
    },
)
async def tool_lint_code(params: Dict[str, Any]) -> ToolResult:
    path = params.get("path", ".")
    language = params.get("language", "python")
    fix = params.get("fix", False)

    commands = {
        "python": f"python -m ruff check {'--fix' if fix else ''} {path}",
        "javascript": f"npx eslint {'--fix' if fix else ''} {path}",
    }

    cmd = commands.get(language)
    if not cmd:
        return ToolResult(success=False, output=f"No linter configured for {language}")

    proc = await asyncio.create_subprocess_shell(
        cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
    return ToolResult(
        success=(proc.returncode == 0),
        output=stdout.decode("utf-8", errors="replace")[:10000] or "No issues found",
    )


# ---------------------------------------------------------------------------
# 56. Run Tests
# ---------------------------------------------------------------------------

@register_tool(
    name="run_tests",
    description="Run test suite. Supports pytest (Python), jest (JS), and custom commands.",
    parameters={
        "framework": "(optional) pytest, jest, or custom",
        "path": "(optional) Test file or directory",
        "command": "(optional) Custom test command",
    },
)
async def tool_run_tests(params: Dict[str, Any]) -> ToolResult:
    framework = params.get("framework", "pytest")
    path = params.get("path", "")
    custom_cmd = params.get("command", "")

    if custom_cmd:
        cmd = custom_cmd
    elif framework == "pytest":
        cmd = f"python -m pytest {path} -v --tb=short"
    elif framework == "jest":
        cmd = f"npx jest {path} --verbose"
    else:
        return ToolResult(success=False, output=f"Unknown framework: {framework}")

    proc = await asyncio.create_subprocess_shell(
        cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=120)
    output = stdout.decode("utf-8", errors="replace")

    return ToolResult(
        success=(proc.returncode == 0),
        output=output[:15000],
        data={"exit_code": proc.returncode, "passed": proc.returncode == 0},
    )


# ---------------------------------------------------------------------------
# 57. Screenshot URL (headless browser)
# ---------------------------------------------------------------------------

@register_tool(
    name="screenshot_url",
    description="Take a screenshot of a webpage URL using a headless browser (if available).",
    parameters={"url": "URL to screenshot", "output_path": "(optional) Save path, default ./screenshot.png"},
)
async def tool_screenshot_url(params: Dict[str, Any]) -> ToolResult:
    url = params.get("url", "")
    output_path = params.get("output_path", "./screenshot.png")
    if not url:
        return ToolResult(success=False, output="No URL provided")

    try:
        cmd = f'python -c "from playwright.sync_api import sync_playwright; p=sync_playwright().start(); b=p.chromium.launch(); page=b.new_page(); page.goto(\'{url}\'); page.screenshot(path=\'{output_path}\'); b.close(); p.stop()"'
        proc = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        if proc.returncode == 0:
            return ToolResult(success=True, output=f"Screenshot saved to {output_path}")
    except Exception:
        pass

    return ToolResult(
        success=False,
        output="Headless browser not available. Install playwright: pip install playwright && playwright install chromium",
    )


# ---------------------------------------------------------------------------
# 58. MCP Connect (Model Context Protocol)
# ---------------------------------------------------------------------------

@register_tool(
    name="mcp_connect",
    description="Connect to an MCP (Model Context Protocol) server and list/call tools.",
    parameters={
        "server_url": "MCP server URL (e.g., http://localhost:3001)",
        "action": "(optional) list_tools, call_tool",
        "tool_name": "(optional) Tool name to call (for call_tool action)",
        "tool_params": "(optional) JSON params for the tool call",
    },
)
async def tool_mcp_connect(params: Dict[str, Any]) -> ToolResult:
    server_url = params.get("server_url", "")
    action = params.get("action", "list_tools")
    if not server_url:
        return ToolResult(success=False, output="No server_url provided")

    async with httpx.AsyncClient(timeout=15.0) as client:
        if action == "list_tools":
            resp = await client.post(
                f"{server_url}/rpc",
                json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
            )
            resp.raise_for_status()
            data = resp.json()
            tools = data.get("result", {}).get("tools", [])
            if tools:
                lines = [f"MCP server has {len(tools)} tools:"]
                for t in tools:
                    lines.append(f"  - {t.get('name', '?')}: {t.get('description', '')[:100]}")
                return ToolResult(success=True, output="\n".join(lines), data={"tools": tools})
            return ToolResult(success=True, output="No tools found on MCP server")

        elif action == "call_tool":
            tool_name = params.get("tool_name", "")
            tool_params = params.get("tool_params", {})
            if isinstance(tool_params, str):
                tool_params = json.loads(tool_params)

            resp = await client.post(
                f"{server_url}/rpc",
                json={
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "params": {"name": tool_name, "arguments": tool_params},
                    "id": 1,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            result = data.get("result", {})
            content = result.get("content", [])
            text_parts = [c.get("text", "") for c in content if c.get("type") == "text"]
            return ToolResult(success=True, output="\n".join(text_parts) or json.dumps(result))

    return ToolResult(success=False, output=f"Unknown MCP action: {action}")


# ---------------------------------------------------------------------------
# 59. Self-Check (code review)
# ---------------------------------------------------------------------------

@register_tool(
    name="self_check",
    description="Analyze your own output for errors, bugs, or improvements.",
    parameters={
        "code": "Code to self-review",
        "language": "(optional) Programming language",
        "context": "(optional) What the code should do",
    },
)
async def tool_self_check(params: Dict[str, Any]) -> ToolResult:
    from ai.provider import ai_provider

    code = params.get("code", "")
    language = params.get("language", "")
    context = params.get("context", "")

    prompt = f"""You are a strict code reviewer. Find ALL bugs, errors, edge cases, security issues,
and improvements in this code. Be ruthless.

{f'Language: {language}' if language else ''}
{f'Context: {context}' if context else ''}

```
{code}
```

List each issue with:
- LINE: approximate line
- SEVERITY: CRITICAL / WARNING / INFO
- ISSUE: what's wrong
- FIX: how to fix it"""

    resp = await ai_provider.chat(
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
    )
    return ToolResult(success=True, output=resp.content)


# ---------------------------------------------------------------------------
# 60. Environment Manager
# ---------------------------------------------------------------------------

@register_tool(
    name="env_manager",
    description="Manage environment variables. Read, set, or list env vars.",
    parameters={
        "action": "get, set, list, load_dotenv",
        "key": "(optional) Variable name",
        "value": "(optional) Variable value (for set)",
        "file": "(optional) .env file path (for load_dotenv)",
    },
)
async def tool_env_manager(params: Dict[str, Any]) -> ToolResult:
    action = params.get("action", "list")

    if action == "get":
        key = params.get("key", "")
        value = os.environ.get(key, "")
        return ToolResult(success=True, output=f"{key}={value}" if value else f"{key} not set")

    elif action == "set":
        key = params.get("key", "")
        value = params.get("value", "")
        os.environ[key] = value
        return ToolResult(success=True, output=f"Set {key}={value}")

    elif action == "list":
        safe_vars = {k: v[:50] for k, v in os.environ.items()
                     if not any(s in k.lower() for s in ["key", "secret", "password", "token"])}
        return ToolResult(success=True, output="\n".join(f"{k}={v}" for k, v in sorted(safe_vars.items())[:50]))

    elif action == "load_dotenv":
        env_file = params.get("file", ".env")
        if not Path(env_file).exists():
            return ToolResult(success=False, output=f"File not found: {env_file}")
        count = 0
        for line in Path(env_file).read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ[key.strip()] = value.strip().strip('"').strip("'")
                count += 1
        return ToolResult(success=True, output=f"Loaded {count} variables from {env_file}")

    return ToolResult(success=False, output=f"Unknown action: {action}")


# ---------------------------------------------------------------------------
# 61. Webhook Sender
# ---------------------------------------------------------------------------

@register_tool(
    name="webhook",
    description="Send a webhook notification to a URL.",
    parameters={
        "url": "Webhook URL",
        "payload": "JSON payload to send",
        "headers": "(optional) Additional headers",
    },
)
async def tool_webhook(params: Dict[str, Any]) -> ToolResult:
    url = params.get("url", "")
    payload = params.get("payload", {})
    headers = params.get("headers", {"Content-Type": "application/json"})

    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            payload = {"text": payload}

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(url, json=payload, headers=headers)

    return ToolResult(
        success=(200 <= resp.status_code < 400),
        output=f"Webhook sent: HTTP {resp.status_code}\n{resp.text[:500]}",
    )


# ---------------------------------------------------------------------------
# 62. API Tester (REST endpoint testing)
# ---------------------------------------------------------------------------

@register_tool(
    name="api_test",
    description="Test a REST API endpoint with assertions. Validates status code, response body, headers.",
    parameters={
        "url": "API endpoint URL",
        "method": "(optional) HTTP method, default GET",
        "body": "(optional) Request body",
        "headers": "(optional) Request headers",
        "expect_status": "(optional) Expected HTTP status code",
        "expect_body_contains": "(optional) String that should be in response body",
    },
)
async def tool_api_test(params: Dict[str, Any]) -> ToolResult:
    url = params.get("url", "")
    method = params.get("method", "GET")
    body = params.get("body")
    headers = params.get("headers", {})
    expect_status = params.get("expect_status")
    expect_body = params.get("expect_body_contains")

    if isinstance(headers, str):
        headers = json.loads(headers)

    kwargs: Dict[str, Any] = {"method": method, "url": url, "headers": headers, "timeout": 15.0}
    if body:
        if isinstance(body, dict):
            kwargs["json"] = body
        else:
            kwargs["content"] = str(body)

    async with httpx.AsyncClient(follow_redirects=True) as client:
        resp = await client.request(**kwargs)

    failures = []
    if expect_status and resp.status_code != int(expect_status):
        failures.append(f"Status: expected {expect_status}, got {resp.status_code}")
    if expect_body and expect_body not in resp.text:
        failures.append(f"Body does not contain: '{expect_body}'")

    if failures:
        return ToolResult(
            success=False,
            output=f"FAILED:\n" + "\n".join(f"  - {f}" for f in failures) + f"\n\nResponse ({resp.status_code}):\n{resp.text[:2000]}",
        )

    return ToolResult(
        success=True,
        output=f"PASSED: {method} {url} -> {resp.status_code}\n\n{resp.text[:3000]}",
    )


# ---------------------------------------------------------------------------
# 63. Schedule Task (delayed execution)
# ---------------------------------------------------------------------------

@register_tool(
    name="schedule_task",
    description="Schedule a delayed task to run after a specified number of seconds.",
    parameters={
        "delay_seconds": "Seconds to wait before running",
        "tool": "Tool name to run",
        "params": "Parameters for the tool",
    },
)
async def tool_schedule_task(params: Dict[str, Any]) -> ToolResult:
    delay = int(params.get("delay_seconds", 0))
    tool_name = params.get("tool", "")
    tool_params = params.get("params", {})

    if delay > 3600:
        return ToolResult(success=False, output="Max delay is 3600 seconds (1 hour)")

    async def run_delayed():
        await asyncio.sleep(delay)
        await execute_tool(tool_name, tool_params)

    asyncio.create_task(run_delayed())
    return ToolResult(
        success=True,
        output=f"Scheduled '{tool_name}' to run in {delay}s",
    )


# ---------------------------------------------------------------------------
# 64. File Operations (copy, move, rename, delete, mkdir)
# ---------------------------------------------------------------------------

@register_tool(
    name="file_ops",
    description="Copy, move, rename, or delete files and directories.",
    parameters={
        "action": "copy, move, rename, delete, mkdir",
        "source": "Source path",
        "destination": "(optional) Destination path",
    },
)
async def tool_file_ops(params: Dict[str, Any]) -> ToolResult:
    action = params.get("action", "")
    source = params.get("source", "")
    dest = params.get("destination", "")

    if not source:
        return ToolResult(success=False, output="source is required")

    p = Path(source)

    if action == "copy":
        if not dest:
            return ToolResult(success=False, output="destination required for copy")
        if p.is_dir():
            shutil.copytree(source, dest)
        else:
            shutil.copy2(source, dest)
        return ToolResult(success=True, output=f"Copied {source} -> {dest}")

    elif action == "move" or action == "rename":
        if not dest:
            return ToolResult(success=False, output="destination required")
        shutil.move(source, dest)
        return ToolResult(success=True, output=f"Moved {source} -> {dest}")

    elif action == "delete":
        if p.is_dir():
            shutil.rmtree(source)
        else:
            p.unlink()
        return ToolResult(success=True, output=f"Deleted {source}")

    elif action == "mkdir":
        p.mkdir(parents=True, exist_ok=True)
        return ToolResult(success=True, output=f"Created directory {source}")

    return ToolResult(success=False, output=f"Unknown action: {action}")


# ---------------------------------------------------------------------------
# 65. Text Transform (case, encoding, counting)
# ---------------------------------------------------------------------------

@register_tool(
    name="text_transform",
    description="Transform text: change case, count words/chars, encode/decode, truncate.",
    parameters={
        "text": "Input text",
        "action": "upper, lower, title, snake_case, camelCase, count, reverse, url_encode, url_decode",
    },
)
async def tool_text_transform(params: Dict[str, Any]) -> ToolResult:
    from urllib.parse import quote, unquote

    text = params.get("text", "")
    action = params.get("action", "count")

    if action == "upper":
        return ToolResult(success=True, output=text.upper())
    elif action == "lower":
        return ToolResult(success=True, output=text.lower())
    elif action == "title":
        return ToolResult(success=True, output=text.title())
    elif action == "snake_case":
        result = re.sub(r'(?<!^)(?=[A-Z])', '_', text).lower()
        result = re.sub(r'[\s-]+', '_', result)
        return ToolResult(success=True, output=result)
    elif action == "camelCase":
        words = re.split(r'[\s_-]+', text)
        result = words[0].lower() + "".join(w.title() for w in words[1:])
        return ToolResult(success=True, output=result)
    elif action == "count":
        lines = text.count("\n") + 1
        words = len(text.split())
        chars = len(text)
        return ToolResult(success=True, output=f"Lines: {lines}, Words: {words}, Characters: {chars}")
    elif action == "reverse":
        return ToolResult(success=True, output=text[::-1])
    elif action == "url_encode":
        return ToolResult(success=True, output=quote(text))
    elif action == "url_decode":
        return ToolResult(success=True, output=unquote(text))

    return ToolResult(success=False, output=f"Unknown action: {action}")


# ---------------------------------------------------------------------------
# 66. Generate Code from Description
# ---------------------------------------------------------------------------

@register_tool(
    name="generate_code",
    description="Generate code from a natural language description. Specify language and what you need.",
    parameters={
        "description": "What the code should do",
        "language": "Programming language",
        "style": "(optional) functional, oop, minimal, production",
    },
)
async def tool_generate_code(params: Dict[str, Any]) -> ToolResult:
    from ai.provider import ai_provider

    description = params.get("description", "")
    language = params.get("language", "python")
    style = params.get("style", "production")

    prompt = f"""Generate {style}-quality {language} code for: {description}

Requirements:
- Complete, working code — not pseudocode
- Include error handling
- Follow {language} best practices and conventions
- Add brief inline comments for complex logic only

Return ONLY the code block, no explanation."""

    resp = await ai_provider.chat(
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )

    code_match = re.search(r"```(?:\w+)?\n(.*?)```", resp.content, re.DOTALL)
    code = code_match.group(1) if code_match else resp.content

    return ToolResult(success=True, output=code)


# ---------------------------------------------------------------------------
# 67. Explain Code
# ---------------------------------------------------------------------------

@register_tool(
    name="explain_code",
    description="Explain what a piece of code does, line by line or high-level.",
    parameters={
        "code": "The code to explain",
        "detail": "(optional) 'high-level' or 'line-by-line', default 'high-level'",
    },
)
async def tool_explain_code(params: Dict[str, Any]) -> ToolResult:
    from ai.provider import ai_provider

    code = params.get("code", "")
    detail = params.get("detail", "high-level")

    prompt = f"""Explain this code ({detail}):

```
{code}
```

Be concise and clear. Focus on what it does and why, not syntax basics."""

    resp = await ai_provider.chat(
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )
    return ToolResult(success=True, output=resp.content)


# ===========================================================================
# WORKSPACE TOOLS (per-agent container operations)
# ===========================================================================

# ---------------------------------------------------------------------------
# 68. Workspace Info
# ---------------------------------------------------------------------------

@register_tool(
    name="workspace_info",
    description="Get information about your workspace container: OS, disk usage, memory, running processes, installed tools.",
    parameters={"detail": "(optional) 'full' for detailed info, 'disk' for disk only, 'processes' for process list"},
)
async def tool_workspace_info(params: Dict[str, Any]) -> ToolResult:
    agent_id = params.pop("_agent_id", None)
    detail = params.get("detail", "full")
    if agent_id is None:
        return ToolResult(success=True, output="No workspace container (running locally)")
    from executor.container_manager import container_manager
    cmds = {
        "full": "uname -a && echo '---' && df -h /workspace && echo '---' && free -m && echo '---' && ps aux --sort=-%cpu | head -10",
        "disk": "df -h",
        "processes": "ps aux --sort=-%cpu | head -20",
    }
    cmd = cmds.get(detail, cmds["full"])
    result = await container_manager.exec_command(agent_id, cmd, timeout=15)
    return ToolResult(success=(result["exit_code"] == 0), output=result["output"])


# ---------------------------------------------------------------------------
# 69. APT Install
# ---------------------------------------------------------------------------

@register_tool(
    name="apt_install",
    description="Install system packages inside your workspace container using apt-get. You are root and have full control.",
    parameters={"packages": "Space-separated list of package names to install, e.g. 'nmap git curl'"},
)
async def tool_apt_install(params: Dict[str, Any]) -> ToolResult:
    agent_id = params.pop("_agent_id", None)
    packages = params.get("packages", "")
    if not packages:
        return ToolResult(success=False, output="No packages specified")
    if agent_id is None:
        return ToolResult(success=False, output="No workspace container available — spawn an agent first")
    from executor.container_manager import container_manager
    result = await container_manager.exec_command(
        agent_id,
        f"DEBIAN_FRONTEND=noninteractive apt-get update -qq && apt-get install -y --no-install-recommends {packages}",
        timeout=120,
    )
    return ToolResult(success=(result["exit_code"] == 0), output=result["output"])


# ---------------------------------------------------------------------------
# 70. Service Manage
# ---------------------------------------------------------------------------

@register_tool(
    name="service_manage",
    description="Start, stop, restart, or check status of services inside your workspace container.",
    parameters={
        "action": "start, stop, restart, or status",
        "service": "Service name, e.g. 'ssh', 'docker', 'postgresql', 'nginx'",
    },
)
async def tool_service_manage(params: Dict[str, Any]) -> ToolResult:
    agent_id = params.pop("_agent_id", None)
    action = params.get("action", "status")
    service = params.get("service", "")
    if not service:
        return ToolResult(success=False, output="No service specified")
    if agent_id is None:
        return ToolResult(success=False, output="No workspace container available")
    from executor.container_manager import container_manager
    result = await container_manager.exec_command(
        agent_id, f"service {service} {action} 2>&1 || systemctl {action} {service} 2>&1", timeout=30,
    )
    return ToolResult(success=(result["exit_code"] == 0), output=result["output"])


# ---------------------------------------------------------------------------
# 71. Docker Control
# ---------------------------------------------------------------------------

@register_tool(
    name="docker_control",
    description="Run Docker commands inside your workspace container (Docker-in-Docker). Build images, run containers, inspect logs, etc.",
    parameters={"command": "Docker command without the 'docker' prefix, e.g. 'run -d nginx' or 'ps -a' or 'images'"},
)
async def tool_docker_control(params: Dict[str, Any]) -> ToolResult:
    agent_id = params.pop("_agent_id", None)
    command = params.get("command", "")
    if not command:
        return ToolResult(success=False, output="No docker command specified")
    if agent_id is None:
        return ToolResult(success=False, output="No workspace container available")
    from executor.container_manager import container_manager
    result = await container_manager.exec_command(agent_id, f"docker {command}", timeout=120)
    return ToolResult(success=(result["exit_code"] == 0), output=result["output"])


# ---------------------------------------------------------------------------
# 72. SSH Execute
# ---------------------------------------------------------------------------

@register_tool(
    name="ssh_execute",
    description="SSH into a remote host from your workspace container and run a command.",
    parameters={
        "host": "Remote hostname or IP",
        "command": "Command to run on the remote host",
        "user": "(optional) SSH username, default 'root'",
        "port": "(optional) SSH port, default 22",
        "key_path": "(optional) Path to SSH private key inside your container",
    },
)
async def tool_ssh_execute(params: Dict[str, Any]) -> ToolResult:
    agent_id = params.pop("_agent_id", None)
    host = params.get("host", "")
    command = params.get("command", "")
    user = params.get("user", "root")
    port = params.get("port", 22)
    key_path = params.get("key_path", "")
    if not host or not command:
        return ToolResult(success=False, output="host and command are required")
    if agent_id is None:
        return ToolResult(success=False, output="No workspace container available")
    from executor.container_manager import container_manager
    key_opt = f"-i {key_path}" if key_path else "-o StrictHostKeyChecking=no"
    ssh_cmd = f"ssh {key_opt} -p {port} {user}@{host} '{command}'"
    result = await container_manager.exec_command(agent_id, ssh_cmd, timeout=60)
    return ToolResult(success=(result["exit_code"] == 0), output=result["output"])


# ---------------------------------------------------------------------------
# 73. File Transfer
# ---------------------------------------------------------------------------

@register_tool(
    name="file_transfer",
    description="Transfer files to/from your workspace container using wget, curl, scp, or rsync.",
    parameters={
        "method": "wget, curl, scp_download, scp_upload, or rsync",
        "source": "Source URL or path",
        "dest": "(optional) Destination path in container, default /workspace/downloads/",
    },
)
async def tool_file_transfer(params: Dict[str, Any]) -> ToolResult:
    agent_id = params.pop("_agent_id", None)
    method = params.get("method", "wget")
    source = params.get("source", "")
    dest = params.get("dest", "/workspace/downloads/")
    if not source:
        return ToolResult(success=False, output="source is required")
    if agent_id is None:
        return ToolResult(success=False, output="No workspace container available")
    from executor.container_manager import container_manager
    cmds = {
        "wget": f"mkdir -p {dest} && wget -P {dest} '{source}'",
        "curl": f"mkdir -p {dest} && curl -L -o {dest}/$(basename '{source}') '{source}'",
        "scp_download": f"mkdir -p {dest} && scp -o StrictHostKeyChecking=no '{source}' {dest}",
        "rsync": f"rsync -avz '{source}' {dest}",
    }
    cmd = cmds.get(method, cmds["wget"])
    result = await container_manager.exec_command(agent_id, cmd, timeout=120)
    return ToolResult(success=(result["exit_code"] == 0), output=result["output"])


# ---------------------------------------------------------------------------
# 74. Cron Manage
# ---------------------------------------------------------------------------

@register_tool(
    name="cron_manage",
    description="Create, list, or delete cron jobs inside your workspace container for scheduled/recurring tasks.",
    parameters={
        "action": "add, list, or remove",
        "schedule": "(for add) Cron schedule, e.g. '*/5 * * * *' for every 5 minutes",
        "command": "(for add) Command to schedule",
        "job_id": "(for remove) Job identifier string to match and remove",
    },
)
async def tool_cron_manage(params: Dict[str, Any]) -> ToolResult:
    agent_id = params.pop("_agent_id", None)
    action = params.get("action", "list")
    if agent_id is None:
        return ToolResult(success=False, output="No workspace container available")
    from executor.container_manager import container_manager
    if action == "list":
        result = await container_manager.exec_command(agent_id, "crontab -l 2>/dev/null || echo '(no cron jobs)'", timeout=10)
    elif action == "add":
        schedule = params.get("schedule", "")
        command = params.get("command", "")
        if not schedule or not command:
            return ToolResult(success=False, output="schedule and command required for add")
        cron_entry = f"{schedule} {command}"
        result = await container_manager.exec_command(
            agent_id,
            f"(crontab -l 2>/dev/null; echo '{cron_entry}') | crontab -",
            timeout=15,
        )
    elif action == "remove":
        job_id = params.get("job_id", "")
        if not job_id:
            return ToolResult(success=False, output="job_id required for remove")
        result = await container_manager.exec_command(
            agent_id,
            f"crontab -l 2>/dev/null | grep -v '{job_id}' | crontab -",
            timeout=15,
        )
    else:
        return ToolResult(success=False, output=f"Unknown action: {action}")
    return ToolResult(success=(result["exit_code"] == 0), output=result["output"])


# ---------------------------------------------------------------------------
# 75. Workspace Browse (noVNC)
# ---------------------------------------------------------------------------

@register_tool(
    name="workspace_browse",
    description="Get the noVNC URL to access your workspace's GUI desktop in a browser. Use this to interact with graphical applications like GIMP, LibreOffice, Blender, etc.",
    parameters={},
)
async def tool_workspace_browse(params: Dict[str, Any]) -> ToolResult:
    agent_id = params.pop("_agent_id", None)
    if agent_id is None:
        return ToolResult(success=False, output="No workspace container available")
    from executor.container_manager import container_manager
    url = container_manager.get_vnc_url(agent_id)
    if url:
        return ToolResult(success=True, output=f"Your GUI desktop is available at: {url}\nOpen this URL in a browser to interact with graphical applications.")
    # Try to start VNC if not running
    ws = container_manager._containers.get(agent_id)
    if ws:
        await container_manager._start_vnc(ws.container_name)
        url = container_manager.get_vnc_url(agent_id)
        if url:
            return ToolResult(success=True, output=f"VNC started. Your GUI desktop: {url}")
    return ToolResult(success=False, output="VNC not available. Ensure WORKSPACE_VNC_ENABLED=true and the workspace container is running.")
