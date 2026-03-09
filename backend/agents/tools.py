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


async def execute_tool(name: str, params: Dict[str, Any]) -> ToolResult:
    tool = get_tool(name)
    if not tool:
        return ToolResult(success=False, output=f"Unknown tool: {name}")
    try:
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
    if not code:
        return ToolResult(success=False, output="No code provided")

    result = await sandbox.execute(language=language, code=code)
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
    if not command:
        return ToolResult(success=False, output="No command provided")

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
