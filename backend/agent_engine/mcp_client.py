"""MCP Client — connects to external MCP servers and imports their tools as Pub-AI tools."""

import asyncio
import json
import logging
import os
from typing import Any, Optional, TYPE_CHECKING

from agent_engine.tools_base import BaseTool, register_dynamic_tool

if TYPE_CHECKING:
    from agent_engine.agent import Agent

logger = logging.getLogger(__name__)

# Active MCP server connections (kept alive for tool calls)
_active_connections: dict[str, "MCPServerConnection"] = {}


class MCPServerConnection:
    """Manages connection to a single MCP server via stdio JSON-RPC 2.0."""

    def __init__(self, name: str, command: str, args: list[str] = None, env: dict = None):
        self.name = name
        self.command = command
        self.args = args or []
        self.env = env
        self.process: Optional[asyncio.subprocess.Process] = None
        self._request_id = 0
        self._lock = asyncio.Lock()

    async def connect(self):
        """Start the MCP server process and perform the initialize handshake."""
        merged_env = {**os.environ, **(self.env or {})}
        self.process = await asyncio.create_subprocess_exec(
            self.command, *self.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=merged_env,
        )
        # Initialize handshake
        resp = await self._send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "pub-ai", "version": "1.0.0"},
        })
        logger.info(f"MCP server '{self.name}' initialized: {resp.get('result', {}).get('serverInfo', {})}")
        # Send initialized notification
        await self._send_notification("notifications/initialized", {})

    async def _send_request(self, method: str, params: dict) -> dict:
        """Send a JSON-RPC request and wait for the response."""
        async with self._lock:
            self._request_id += 1
            rid = self._request_id
            msg = {"jsonrpc": "2.0", "id": rid, "method": method, "params": params}
            line = json.dumps(msg) + "\n"
            self.process.stdin.write(line.encode())
            await self.process.stdin.drain()

            # Read lines until we get a response with our id
            while True:
                response_line = await asyncio.wait_for(
                    self.process.stdout.readline(), timeout=30.0
                )
                if not response_line:
                    raise ConnectionError(f"MCP server '{self.name}' closed stdout unexpectedly")
                try:
                    data = json.loads(response_line.decode())
                except json.JSONDecodeError:
                    continue
                # Skip notifications (no "id" field)
                if data.get("id") == rid:
                    if "error" in data:
                        raise RuntimeError(f"MCP error: {data['error']}")
                    return data

    async def _send_notification(self, method: str, params: dict):
        """Send a JSON-RPC notification (no response expected)."""
        msg = {"jsonrpc": "2.0", "method": method, "params": params}
        line = json.dumps(msg) + "\n"
        self.process.stdin.write(line.encode())
        await self.process.stdin.drain()

    async def list_tools(self) -> list[dict]:
        """Get available tools from the MCP server."""
        result = await self._send_request("tools/list", {})
        return result.get("result", {}).get("tools", [])

    async def call_tool(self, tool_name: str, arguments: dict) -> str:
        """Call a tool on the MCP server and return the text result."""
        result = await self._send_request("tools/call", {
            "name": tool_name,
            "arguments": arguments,
        })
        content = result.get("result", {}).get("content", [])
        texts = [c.get("text", "") for c in content if c.get("type") == "text"]
        if texts:
            return "\n".join(texts)
        # Fallback: return the raw result as JSON
        return json.dumps(result.get("result", {}), indent=2)

    async def disconnect(self):
        """Terminate the MCP server process."""
        if self.process and self.process.returncode is None:
            try:
                self.process.terminate()
                await asyncio.wait_for(self.process.wait(), timeout=5.0)
            except Exception:
                self.process.kill()
            logger.info(f"MCP server '{self.name}' disconnected")


def _make_mcp_tool_class(
    tool_name: str,
    tool_description: str,
    input_schema: dict,
    server_name: str,
    mcp_tool_name: str,
) -> type[BaseTool]:
    """Dynamically create a BaseTool subclass that proxies to an MCP server tool."""

    class MCPToolProxy(BaseTool):
        name = tool_name
        description = tool_description

        async def execute(self) -> str:
            conn = _active_connections.get(server_name)
            if not conn:
                return f"Error: MCP server '{server_name}' is not connected."
            return await conn.call_tool(mcp_tool_name, self.args)

    # Give the class a unique name for debugging
    MCPToolProxy.__name__ = f"MCPTool_{tool_name}"
    MCPToolProxy.__qualname__ = f"MCPTool_{tool_name}"
    return MCPToolProxy


async def discover_and_register_mcp_servers(config: list[dict]) -> list[str]:
    """Connect to configured MCP servers and register their tools.

    Config format:
    [
        {
            "name": "filesystem",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem", "/workspace"],
            "env": {}   # optional extra env vars
        }
    ]

    Returns list of registered tool names.
    """
    registered_tools = []

    for server_config in config:
        server_name = server_config.get("name", "unknown")
        try:
            conn = MCPServerConnection(
                name=server_name,
                command=server_config["command"],
                args=server_config.get("args", []),
                env=server_config.get("env"),
            )
            await conn.connect()
            _active_connections[server_name] = conn

            tools = await conn.list_tools()
            for tool_def in tools:
                # Prefix tool name to avoid collisions with built-in tools
                prefixed_name = f"mcp_{server_name}_{tool_def['name']}"
                description = tool_def.get("description", f"MCP tool from {server_name}")
                input_schema = tool_def.get("inputSchema", {})

                # Build a description that includes parameter info
                params = input_schema.get("properties", {})
                if params:
                    param_lines = []
                    for pname, pinfo in params.items():
                        param_lines.append(f"  - {pname}: {pinfo.get('description', pinfo.get('type', 'any'))}")
                    description += "\nParameters:\n" + "\n".join(param_lines)

                tool_cls = _make_mcp_tool_class(
                    tool_name=prefixed_name,
                    tool_description=description,
                    input_schema=input_schema,
                    server_name=server_name,
                    mcp_tool_name=tool_def["name"],
                )
                register_dynamic_tool(tool_cls)
                registered_tools.append(prefixed_name)
                logger.info(f"Registered MCP tool: {prefixed_name}")

        except Exception as e:
            logger.error(f"Failed to connect to MCP server '{server_name}': {e}", exc_info=True)

    return registered_tools


async def disconnect_all_mcp_servers():
    """Disconnect all active MCP server connections."""
    for name, conn in list(_active_connections.items()):
        await conn.disconnect()
    _active_connections.clear()


def get_active_mcp_servers() -> list[str]:
    """Return names of currently connected MCP servers."""
    return list(_active_connections.keys())
