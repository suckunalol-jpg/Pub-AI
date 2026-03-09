"""Tool registry for Pub AI agents.

Each tool is a callable that agents can invoke during their think-act-observe loop.
Covers: web, HTTP, code execution, file ops, git, network, Roblox, system,
sub-agents, memory, browser debugging, package management, deployment, and more.
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
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse

import httpx

from config import settings
from executor.sandbox import sandbox


@dataclass
class ToolResult:
    success: bool
    output: str
    data: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

_TOOLS: Dict[str, "ToolDef"] = {}


@dataclass
class ToolDef:
    name: str
    description: str
    parameters: Dict[str, str]  # param_name -> description
    fn: Callable  # async callable(params) -> ToolResult


def register_tool(name: str, description: str, parameters: Dict[str, str]):
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
        {
            "name": t.name,
            "description": t.description,
            "parameters": t.parameters,
        }
        for t in _TOOLS.values()
    ]


def tools_prompt() -> str:
    """Build a text description of all available tools for the system prompt."""
    lines = ["\n## Available Tools\n"]
    for t in _TOOLS.values():
        params = ", ".join(f'"{k}": "{v}"' for k, v in t.parameters.items())
        lines.append(f"### {t.name}")
        lines.append(f"{t.description}")
        lines.append(f"Parameters: {{{params}}}")
        lines.append("")
    lines.append("## How to Use Tools")
    lines.append("")
    lines.append("When you want to use a tool, output EXACTLY this format (the ```tool and ``` markers are required):")
    lines.append("")
    lines.append('```tool')
    lines.append('{"tool": "tool_name_here", "params": {"param1": "value1"}}')
    lines.append('```')
    lines.append("")
    lines.append("Example — searching the web:")
    lines.append("")
    lines.append('```tool')
    lines.append('{"tool": "web_search", "params": {"query": "python async tutorial"}}')
    lines.append('```')
    lines.append("")
    lines.append("Example — executing code:")
    lines.append("")
    lines.append('```tool')
    lines.append('{"tool": "execute_code", "params": {"language": "python", "code": "print(2+2)"}}')
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
        return ToolResult(success=False, output=f"Tool error: {e}")


# ===========================================================================
# TOOL IMPLEMENTATIONS
# ===========================================================================

# ---------------------------------------------------------------------------
# 1. Web Search (DuckDuckGo HTML — no API key needed)
# ---------------------------------------------------------------------------

@register_tool(
    name="web_search",
    description="Search the web for information. Returns top results with titles, URLs, and snippets.",
    parameters={"query": "The search query string", "max_results": "(optional) Number of results, default 5"},
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
    # Parse results from DDG HTML
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
    description="Fetch the text content of a webpage URL.",
    parameters={"url": "The URL to fetch", "max_length": "(optional) Max characters to return, default 8000"},
)
async def tool_web_fetch(params: Dict[str, Any]) -> ToolResult:
    url = params.get("url", "")
    max_length = int(params.get("max_length", 8000))
    if not url:
        return ToolResult(success=False, output="No URL provided")

    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0 (compatible; PubAI/1.0)"})
        resp.raise_for_status()

    # Strip HTML tags for readability
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
# 4. Read File
# ---------------------------------------------------------------------------

@register_tool(
    name="read_file",
    description="Read the contents of a file.",
    parameters={"path": "Absolute or relative file path"},
)
async def tool_read_file(params: Dict[str, Any]) -> ToolResult:
    path = params.get("path", "")
    if not path:
        return ToolResult(success=False, output="No path provided")

    p = Path(path)
    if not p.exists():
        return ToolResult(success=False, output=f"File not found: {path}")
    if not p.is_file():
        return ToolResult(success=False, output=f"Not a file: {path}")

    try:
        content = p.read_text(encoding="utf-8", errors="replace")
        if len(content) > 50000:
            content = content[:50000] + "\n... (truncated)"
        return ToolResult(success=True, output=content)
    except Exception as e:
        return ToolResult(success=False, output=f"Error reading file: {e}")


# ---------------------------------------------------------------------------
# 5. Write File
# ---------------------------------------------------------------------------

@register_tool(
    name="write_file",
    description="Write content to a file. Creates parent directories if needed.",
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
# 6. Edit File (find & replace)
# ---------------------------------------------------------------------------

@register_tool(
    name="edit_file",
    description="Edit a file by replacing an exact string with new content.",
    parameters={
        "path": "File path",
        "old_string": "Exact text to find",
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
    if old not in content:
        return ToolResult(success=False, output="old_string not found in file")

    new_content = content.replace(old, new, 1)
    p.write_text(new_content, encoding="utf-8")
    return ToolResult(success=True, output=f"Edited {path}")


# ---------------------------------------------------------------------------
# 7. List / Glob Files
# ---------------------------------------------------------------------------

@register_tool(
    name="list_files",
    description="List files in a directory, optionally matching a glob pattern.",
    parameters={
        "path": "Directory path (default: current dir)",
        "pattern": "(optional) Glob pattern like '**/*.py'",
    },
)
async def tool_list_files(params: Dict[str, Any]) -> ToolResult:
    path = params.get("path", ".")
    pattern = params.get("pattern", "*")

    p = Path(path)
    if not p.exists():
        return ToolResult(success=False, output=f"Directory not found: {path}")

    files = sorted(str(f) for f in p.glob(pattern))
    if not files:
        return ToolResult(success=True, output="No files found")

    # Limit output
    if len(files) > 200:
        files = files[:200]
        files.append(f"... and more (showing first 200)")

    return ToolResult(success=True, output="\n".join(files), data={"files": files})


# ---------------------------------------------------------------------------
# 8. Search Code (grep)
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
    query = params.get("query", "")
    path = params.get("path", ".")
    file_pattern = params.get("file_pattern", "**/*")
    if not query:
        return ToolResult(success=False, output="No query provided")

    p = Path(path)
    if not p.exists():
        return ToolResult(success=False, output=f"Path not found: {path}")

    matches = []
    try:
        regex = re.compile(query, re.IGNORECASE)
    except re.error:
        regex = re.compile(re.escape(query), re.IGNORECASE)

    for file_path in p.glob(file_pattern):
        if not file_path.is_file():
            continue
        # Skip binary / large files
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
# 9. Shell Command (limited)
# ---------------------------------------------------------------------------

@register_tool(
    name="shell",
    description="Run a shell command. Use for git, npm, pip, build tools, etc. Timeout: 60s.",
    parameters={"command": "Shell command to execute"},
)
async def tool_shell(params: Dict[str, Any]) -> ToolResult:
    command = params.get("command", "")
    if not command:
        return ToolResult(success=False, output="No command provided")

    # Block dangerous commands
    dangerous = ["rm -rf /", "mkfs", "dd if=", ":(){", "fork bomb", "shutdown", "reboot"]
    for d in dangerous:
        if d in command.lower():
            return ToolResult(success=False, output=f"Blocked dangerous command")

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
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
# 10. Spawn Sub-Agent
# ---------------------------------------------------------------------------

@register_tool(
    name="spawn_agent",
    description="Spawn a sub-agent to handle a specific sub-task in parallel. Returns the agent ID.",
    parameters={
        "agent_type": "Type: coder, researcher, reviewer, executor, planner, roblox",
        "task": "Description of the task for the sub-agent",
    },
)
async def tool_spawn_agent(params: Dict[str, Any]) -> ToolResult:
    # Lazy import to avoid circular dependency
    from agents.orchestrator import orchestrator
    from db.database import async_session

    agent_type = params.get("agent_type", "coder")
    task = params.get("task", "")
    if not task:
        return ToolResult(success=False, output="No task provided")

    async with async_session() as db:
        session = await orchestrator.spawn(
            db=db,
            agent_type=agent_type,
            task=task,
            conversation_id=uuid.uuid4(),
        )
        await db.commit()

    return ToolResult(
        success=True,
        output=f"Spawned {agent_type} agent: {session.agent_name} (ID: {session.id})",
        data={"agent_id": str(session.id), "agent_name": session.agent_name},
    )


# ---------------------------------------------------------------------------
# 11. Message Agent (inter-agent communication)
# ---------------------------------------------------------------------------

@register_tool(
    name="message_agent",
    description="Send a message to another running agent and get their response.",
    parameters={
        "agent_id": "UUID of the agent to message",
        "message": "Message to send",
    },
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
# 12. Wait for Agent (check result of spawned sub-agent)
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

    # Poll until done (max 5 min)
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
# 13. Roblox Game Scanner
# ---------------------------------------------------------------------------

@register_tool(
    name="roblox_scan",
    description="Scan scripts in a Roblox game. Analyzes for security issues, performance, exploits, and code quality.",
    parameters={
        "scripts": "List of script objects [{name, source, type}] OR a single script string",
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

    # Build analysis prompt
    script_blocks = []
    for s in scripts[:10]:  # Cap at 10 scripts per scan
        name = s.get("name", "Unknown")
        stype = s.get("type", "Script")
        source = s.get("source", "")
        if len(source) > 5000:
            source = source[:5000] + "\n-- ... (truncated)"
        script_blocks.append(f"### {name} ({stype})\n```lua\n{source}\n```")

    depth = "thorough, line-by-line" if scan_type == "deep" else "high-level overview"

    prompt = f"""Perform a {depth} analysis of these {len(scripts)} Roblox scripts.

For each script, analyze:
1. **Security**: Remote event validation, client trust, data sanitization, injection risks
2. **Performance**: Memory leaks, O(n^2) loops, unnecessary Instance creation, connection cleanup
3. **Exploits**: Potential abuse vectors, missing server validation, race conditions
4. **Code Quality**: Naming, modularity, error handling, type annotations
5. **Architecture**: Client/server split, proper use of services, data flow

Rate each issue: CRITICAL / WARNING / INFO

{chr(10).join(script_blocks)}"""

    messages = [
        {"role": "system", "content": ROBLOX_SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]

    resp = await ai_provider.chat(messages=messages, max_tokens=4096)
    return ToolResult(success=True, output=resp.content, data={"model": resp.model})


# ---------------------------------------------------------------------------
# 14. Plan Tasks (decompose a complex task)
# ---------------------------------------------------------------------------

@register_tool(
    name="plan_tasks",
    description="Break a complex task into ordered sub-tasks with dependencies. Returns a task plan.",
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
- agent_type (coder/researcher/reviewer/executor/planner/roblox)
- depends_on (list of task ids that must complete first, or empty)

Return ONLY valid JSON array. No explanation.

Task: {description}"""

    resp = await ai_provider.chat(
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )

    # Extract JSON from response
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
# 15. Create Project (scaffold a full project from description)
# ---------------------------------------------------------------------------

@register_tool(
    name="create_project",
    description="Scaffold a new project from a natural language description. Creates directory structure and starter files.",
    parameters={
        "description": "What to build (e.g., 'a REST API with auth and PostgreSQL')",
        "path": "Where to create the project",
        "stack": "(optional) Tech stack hint: 'python', 'node', 'react', 'roblox'",
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

Include ALL necessary files: config, main entry point, dependencies, .gitignore, etc.
Make the code production-ready and working. Return ONLY the JSON."""

    resp = await ai_provider.chat(
        messages=[{"role": "user", "content": prompt}],
        temperature=0.4,
        max_tokens=8192,
    )

    # Extract JSON
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
    except (json.JSONDecodeError, Exception) as e:
        return ToolResult(success=False, output=f"Error creating project: {e}")


# ===========================================================================
# EXPANDED TOOL SET — HTTP, Network, System, Git, Debug, Deploy, Memory, MCP
# ===========================================================================

# ---------------------------------------------------------------------------
# 16. HTTP Request (full control — headers, method, body, proxy)
# ---------------------------------------------------------------------------

@register_tool(
    name="http_request",
    description="Make an HTTP request with full control over method, headers, body, and proxy.",
    parameters={
        "method": "GET, POST, PUT, DELETE, PATCH, HEAD, OPTIONS",
        "url": "Target URL",
        "headers": "(optional) JSON object of headers",
        "body": "(optional) Request body (string or JSON)",
        "proxy": "(optional) Proxy URL for routing",
        "timeout": "(optional) Timeout in seconds, default 30",
        "follow_redirects": "(optional) true/false, default true",
    },
)
async def tool_http_request(params: Dict[str, Any]) -> ToolResult:
    method = params.get("method", "GET").upper()
    url = params.get("url", "")
    headers = params.get("headers", {})
    body = params.get("body")
    proxy = params.get("proxy")
    timeout = float(params.get("timeout", 30))
    follow = params.get("follow_redirects", True)

    if not url:
        return ToolResult(success=False, output="No URL provided")

    if isinstance(headers, str):
        try:
            headers = json.loads(headers)
        except json.JSONDecodeError:
            headers = {}

    kwargs: Dict[str, Any] = {
        "method": method,
        "url": url,
        "headers": headers,
        "timeout": timeout,
        "follow_redirects": bool(follow),
    }

    if body:
        if isinstance(body, dict):
            kwargs["json"] = body
        else:
            kwargs["content"] = str(body)

    client_kwargs = {}
    if proxy:
        client_kwargs["proxies"] = proxy

    async with httpx.AsyncClient(**client_kwargs) as client:
        resp = await client.request(**kwargs)

    resp_headers = dict(resp.headers)
    body_text = resp.text
    if len(body_text) > 15000:
        body_text = body_text[:15000] + "\n... (truncated)"

    return ToolResult(
        success=(200 <= resp.status_code < 400),
        output=f"HTTP {resp.status_code}\nHeaders: {json.dumps(resp_headers, indent=2)[:2000]}\n\nBody:\n{body_text}",
        data={
            "status_code": resp.status_code,
            "headers": resp_headers,
            "body_length": len(resp.text),
        },
    )


# ---------------------------------------------------------------------------
# 17. DNS Lookup
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
        # A records
        ips = socket.getaddrinfo(domain, None, socket.AF_INET)
        ipv4 = list(set(addr[4][0] for addr in ips))

        # Try IPv6
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
# 18. Port Scanner (authorized security testing only)
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

    # Parse ports
    ports = []
    for part in ports_str.split(","):
        part = part.strip()
        if "-" in part:
            start, end = part.split("-", 1)
            ports.extend(range(int(start), min(int(end) + 1, int(start) + 100)))
        else:
            ports.append(int(part))

    ports = ports[:200]  # Cap at 200 ports

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
# 19. JSON / YAML / XML Parser
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
# 20. Base64 Encode/Decode
# ---------------------------------------------------------------------------

@register_tool(
    name="base64",
    description="Encode or decode base64 data.",
    parameters={"data": "Data to encode/decode", "action": "encode or decode"},
)
async def tool_base64(params: Dict[str, Any]) -> ToolResult:
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
# 21. Hash
# ---------------------------------------------------------------------------

@register_tool(
    name="hash",
    description="Hash data with MD5, SHA1, SHA256, or SHA512.",
    parameters={"data": "Data to hash", "algorithm": "(optional) md5, sha1, sha256 (default), sha512"},
)
async def tool_hash(params: Dict[str, Any]) -> ToolResult:
    data = params.get("data", "")
    algo = params.get("algorithm", "sha256")

    h = hashlib.new(algo)
    h.update(data.encode())
    return ToolResult(success=True, output=f"{algo}: {h.hexdigest()}")


# ---------------------------------------------------------------------------
# 22. JWT Decode
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
# 23. Regex Tester
# ---------------------------------------------------------------------------

@register_tool(
    name="regex_test",
    description="Test a regex pattern against text. Shows all matches with groups.",
    parameters={"pattern": "Regex pattern", "text": "Text to test against", "flags": "(optional) i, m, s, x"},
)
async def tool_regex_test(params: Dict[str, Any]) -> ToolResult:
    pattern = params.get("pattern", "")
    text = params.get("text", "")
    flags_str = params.get("flags", "")

    if not pattern:
        return ToolResult(success=False, output="No pattern provided")

    flags = 0
    if "i" in flags_str: flags |= re.IGNORECASE
    if "m" in flags_str: flags |= re.MULTILINE
    if "s" in flags_str: flags |= re.DOTALL
    if "x" in flags_str: flags |= re.VERBOSE

    try:
        compiled = re.compile(pattern, flags)
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
# 24. Diff Two Files / Strings
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

    diff = list(difflib.unified_diff(
        lines1, lines2,
        fromfile=params.get("file1", "text1"),
        tofile=params.get("file2", "text2"),
    ))

    if not diff:
        return ToolResult(success=True, output="No differences found")

    output = "".join(diff)
    if len(output) > 10000:
        output = output[:10000] + "\n... (truncated)"
    return ToolResult(success=True, output=output)


# ---------------------------------------------------------------------------
# 25. Git Operations
# ---------------------------------------------------------------------------

@register_tool(
    name="git",
    description="Run git operations: status, diff, log, branch, checkout, add, commit, push, pull, clone.",
    parameters={
        "operation": "Git operation (status, diff, log, branch, checkout, add, commit, push, pull, clone, stash)",
        "args": "(optional) Additional arguments",
        "path": "(optional) Working directory",
    },
)
async def tool_git(params: Dict[str, Any]) -> ToolResult:
    operation = params.get("operation", "status")
    args = params.get("args", "")
    path = params.get("path", ".")

    safe_ops = ["status", "diff", "log", "branch", "show", "remote", "tag", "stash list"]
    command = f"git -C {path} {operation} {args}".strip()

    # Block destructive without args for safety
    if operation in ("push", "reset", "rebase", "merge") and "--force" in args:
        return ToolResult(success=False, output="Force operations blocked for safety. Use shell tool if needed.")

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        output = stdout.decode("utf-8", errors="replace")
        if len(output) > 15000:
            output = output[:15000] + "\n... (truncated)"
        return ToolResult(
            success=(proc.returncode == 0),
            output=output or "(no output)",
            data={"exit_code": proc.returncode},
        )
    except asyncio.TimeoutError:
        return ToolResult(success=False, output="Git command timed out")


# ---------------------------------------------------------------------------
# 26. Package Manager (npm, pip, cargo)
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

    cmd = f"cd {path} && {commands[manager][action]}"
    proc = await asyncio.create_subprocess_shell(
        cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=120)
    output = stdout.decode("utf-8", errors="replace")

    return ToolResult(
        success=(proc.returncode == 0),
        output=output[:10000],
        data={"exit_code": proc.returncode},
    )


# ---------------------------------------------------------------------------
# 27. System Info
# ---------------------------------------------------------------------------

@register_tool(
    name="system_info",
    description="Get system information: OS, CPU, memory, disk, network, Python version.",
    parameters={},
)
async def tool_system_info(params: Dict[str, Any]) -> ToolResult:
    import sys

    info = {
        "os": platform.system(),
        "os_version": platform.version(),
        "architecture": platform.machine(),
        "python_version": sys.version,
        "hostname": platform.node(),
        "cpu_count": os.cpu_count(),
        "cwd": os.getcwd(),
    }

    # Disk usage
    try:
        usage = shutil.disk_usage("/")
        info["disk_total_gb"] = round(usage.total / (1024**3), 1)
        info["disk_free_gb"] = round(usage.free / (1024**3), 1)
    except Exception:
        pass

    output = "\n".join(f"{k}: {v}" for k, v in info.items())
    return ToolResult(success=True, output=output, data=info)


# ---------------------------------------------------------------------------
# 28. Process Manager
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
# 29. Download File
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
# 30. Compress / Decompress
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
# 31. Database Query (SQLite/PostgreSQL via raw SQL)
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

    # Safety: only allow SELECT
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

        # Format as table
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
# 32. Memory Store/Retrieve (per-user learning)
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
    from agents.memory import memory_system
    from db.database import async_session

    mem_type = params.get("memory_type", "fact")
    key = params.get("key", "")
    value = params.get("value", "")

    if not key or not value:
        return ToolResult(success=False, output="key and value are required")

    # Note: in real use, user_id comes from the agent's context
    return ToolResult(
        success=True,
        output=f"Memory queued: [{mem_type}] {key} = {value}",
        data={"memory_type": mem_type, "key": key, "value": value},
    )


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
# 33. Lint / Format Code
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
# 34. Run Tests
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
# 35. Screenshot / Render Webpage (headless)
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

    # Try playwright first, then fall back to message
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
# 36. MCP Connect (Model Context Protocol)
# ---------------------------------------------------------------------------

@register_tool(
    name="mcp_connect",
    description="Connect to an MCP (Model Context Protocol) server and list available tools.",
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
# 37. Self-Correction: Analyze Own Output
# ---------------------------------------------------------------------------

@register_tool(
    name="self_check",
    description="Analyze your own output for errors, bugs, or improvements. Use this to catch your own mistakes.",
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
and improvements in this code. Be ruthless — don't miss anything.

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
# 38. Environment Manager
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
        # Filter out sensitive-looking vars
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
# 39. Webhook Sender
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
# 40. API Tester (REST endpoint testing)
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
# 41. Cron / Schedule Task
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
# 42. Copy / Move / Delete Files
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
# 43. Text Transform (case, encoding, counting)
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
        from urllib.parse import quote
        return ToolResult(success=True, output=quote(text))
    elif action == "url_decode":
        from urllib.parse import unquote
        return ToolResult(success=True, output=unquote(text))

    return ToolResult(success=False, output=f"Unknown action: {action}")


# ---------------------------------------------------------------------------
# 44. Generate Code from Description
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

    # Extract code block if present
    code_match = re.search(r"```(?:\w+)?\n(.*?)```", resp.content, re.DOTALL)
    code = code_match.group(1) if code_match else resp.content

    return ToolResult(success=True, output=code)


# ---------------------------------------------------------------------------
# 45. Explain Code
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
