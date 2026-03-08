"""MCP (Model Context Protocol) server for Pub AI.

Exposes Pub AI capabilities as MCP-compatible tools over JSON-RPC 2.0.
Compatible with Claude Code and other MCP clients.

Endpoints:
    POST /mcp       - Main JSON-RPC 2.0 endpoint
    GET  /mcp/sse   - SSE transport for streaming (basic implementation)
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mcp", tags=["mcp"])

# ---------------------------------------------------------------------------
# MCP Server Metadata
# ---------------------------------------------------------------------------

SERVER_INFO = {
    "name": "pub-ai",
    "version": "1.0.0",
}

SERVER_CAPABILITIES = {
    "tools": {},          # We support tools/list + tools/call
    "resources": {},      # We support resources/list (minimal)
    "prompts": {},        # We support prompts/list (minimal)
}

# ---------------------------------------------------------------------------
# JSON-RPC 2.0 Error Codes
# ---------------------------------------------------------------------------

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

# ---------------------------------------------------------------------------
# MCP Tool Definitions
# ---------------------------------------------------------------------------

MCP_TOOLS: List[Dict[str, Any]] = [
    {
        "name": "pub_chat",
        "description": (
            "Send a message to Pub AI and get an AI-generated response. "
            "Optionally specify a conversation_id to maintain context, "
            "or a model name to target a specific registered model."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "The message to send to the AI",
                },
                "conversation_id": {
                    "type": "string",
                    "description": "Optional conversation ID for context continuity",
                },
                "model": {
                    "type": "string",
                    "description": "Optional model name to use (must be registered in Pub AI)",
                },
            },
            "required": ["message"],
        },
    },
    {
        "name": "pub_execute_code",
        "description": (
            "Execute code in a sandboxed environment. "
            "Supports Python, JavaScript (Node.js), and Lua."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "language": {
                    "type": "string",
                    "enum": ["python", "javascript", "lua"],
                    "description": "Programming language to execute",
                },
                "code": {
                    "type": "string",
                    "description": "Source code to execute",
                },
            },
            "required": ["language", "code"],
        },
    },
    {
        "name": "pub_search_knowledge",
        "description": (
            "Search the Pub AI knowledge base using semantic vector search. "
            "Returns the most relevant documents for a given query."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query text",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default: 5)",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "pub_spawn_agent",
        "description": (
            "Spawn an autonomous AI agent to work on a task in the background. "
            "Returns the agent ID which can be used to check status later."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_type": {
                    "type": "string",
                    "enum": ["coder", "researcher", "reviewer", "executor", "planner", "roblox"],
                    "description": "Type of agent to spawn",
                },
                "task": {
                    "type": "string",
                    "description": "Task description for the agent",
                },
            },
            "required": ["agent_type", "task"],
        },
    },
    {
        "name": "pub_agent_status",
        "description": (
            "Check the current status of a spawned agent. "
            "Returns the agent's status, result (if completed), and other state."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "UUID of the agent to check",
                },
            },
            "required": ["agent_id"],
        },
    },
]

# ---------------------------------------------------------------------------
# MCP Resources (minimal)
# ---------------------------------------------------------------------------

MCP_RESOURCES: List[Dict[str, Any]] = [
    {
        "uri": "pub-ai://status",
        "name": "Pub AI Status",
        "description": "Current server health and active model information",
        "mimeType": "application/json",
    },
]

# ---------------------------------------------------------------------------
# MCP Prompts (minimal)
# ---------------------------------------------------------------------------

MCP_PROMPTS: List[Dict[str, Any]] = [
    {
        "name": "code_review",
        "description": "Ask Pub AI to review a piece of code",
        "arguments": [
            {
                "name": "code",
                "description": "The code to review",
                "required": True,
            },
            {
                "name": "language",
                "description": "Programming language of the code",
                "required": False,
            },
        ],
    },
]

# ---------------------------------------------------------------------------
# JSON-RPC Helpers
# ---------------------------------------------------------------------------


def _jsonrpc_success(id: Any, result: Any) -> Dict:
    """Build a JSON-RPC 2.0 success response."""
    return {"jsonrpc": "2.0", "id": id, "result": result}


def _jsonrpc_error(id: Any, code: int, message: str, data: Any = None) -> Dict:
    """Build a JSON-RPC 2.0 error response."""
    error: Dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": id, "error": error}


def _mcp_text_result(text: str, is_error: bool = False) -> Dict:
    """Wrap text in MCP tool result content format."""
    result: Dict[str, Any] = {
        "content": [{"type": "text", "text": text}],
    }
    if is_error:
        result["isError"] = True
    return result


# ---------------------------------------------------------------------------
# Tool Handlers
# ---------------------------------------------------------------------------


async def _handle_pub_chat(arguments: Dict[str, Any]) -> Dict:
    """Handle pub_chat tool call."""
    message = arguments.get("message")
    if not message:
        return _mcp_text_result("Error: 'message' parameter is required", is_error=True)

    conversation_id = arguments.get("conversation_id")
    model = arguments.get("model")

    try:
        from ai.provider import ai_provider

        messages = [
            {
                "role": "system",
                "content": (
                    "You are Pub AI, an intelligent coding assistant. "
                    "Be helpful, concise, and accurate."
                ),
            },
            {"role": "user", "content": message},
        ]

        response = await ai_provider.chat(messages=messages, model=model)

        # Build response text with metadata
        result_text = response.content
        metadata_line = (
            f"\n\n---\n"
            f"Model: {response.model} | "
            f"Tokens: {response.tokens_in}in/{response.tokens_out}out | "
            f"Latency: {response.latency_ms}ms"
        )
        result_text += metadata_line

        if conversation_id:
            result_text += f" | Conversation: {conversation_id}"

        return _mcp_text_result(result_text)

    except RuntimeError as e:
        return _mcp_text_result(f"Model error: {e}", is_error=True)
    except Exception as e:
        logger.exception("pub_chat failed")
        return _mcp_text_result(f"Chat failed: {e}", is_error=True)


async def _handle_pub_execute_code(arguments: Dict[str, Any]) -> Dict:
    """Handle pub_execute_code tool call."""
    language = arguments.get("language")
    code = arguments.get("code")

    if not language or not code:
        return _mcp_text_result(
            "Error: 'language' and 'code' parameters are required",
            is_error=True,
        )

    if language not in ("python", "javascript", "lua"):
        return _mcp_text_result(
            f"Error: Unsupported language '{language}'. Use: python, javascript, lua",
            is_error=True,
        )

    try:
        from executor.sandbox import sandbox

        result = await sandbox.execute(language=language, code=code)

        output_text = (
            f"Language: {language}\n"
            f"Exit code: {result['exit_code']}\n"
            f"Duration: {result['duration_ms']}ms\n"
            f"\n--- Output ---\n"
            f"{result['output']}"
        )

        is_error = result["exit_code"] != 0
        return _mcp_text_result(output_text, is_error=is_error)

    except Exception as e:
        logger.exception("pub_execute_code failed")
        return _mcp_text_result(f"Execution failed: {e}", is_error=True)


async def _handle_pub_search_knowledge(arguments: Dict[str, Any]) -> Dict:
    """Handle pub_search_knowledge tool call."""
    query = arguments.get("query")
    if not query:
        return _mcp_text_result("Error: 'query' parameter is required", is_error=True)

    max_results = arguments.get("max_results", 5)

    try:
        from knowledge.vectordb import vector_store

        # Search without user_id filter since MCP doesn't have auth context
        results = vector_store.query(query=query, top_k=max_results)

        if not results:
            return _mcp_text_result("No results found for the given query.")

        # Format results
        lines = [f"Found {len(results)} result(s) for: \"{query}\"\n"]
        for i, entry in enumerate(results, 1):
            distance = entry.get("distance")
            distance_str = f" (distance: {distance:.4f})" if distance is not None else ""
            metadata = entry.get("metadata", {})
            meta_str = ""
            if metadata:
                meta_parts = [f"{k}={v}" for k, v in metadata.items() if k != "user_id"]
                if meta_parts:
                    meta_str = f" [{', '.join(meta_parts)}]"

            lines.append(f"--- Result {i}{distance_str}{meta_str} ---")
            lines.append(entry.get("content", "(no content)"))
            lines.append("")

        return _mcp_text_result("\n".join(lines))

    except RuntimeError as e:
        # ChromaDB not available
        return _mcp_text_result(f"Knowledge base unavailable: {e}", is_error=True)
    except Exception as e:
        logger.exception("pub_search_knowledge failed")
        return _mcp_text_result(f"Search failed: {e}", is_error=True)


async def _handle_pub_spawn_agent(arguments: Dict[str, Any]) -> Dict:
    """Handle pub_spawn_agent tool call."""
    agent_type = arguments.get("agent_type")
    task = arguments.get("task")

    if not agent_type or not task:
        return _mcp_text_result(
            "Error: 'agent_type' and 'task' parameters are required",
            is_error=True,
        )

    valid_types = {"coder", "researcher", "reviewer", "executor", "planner", "roblox"}
    if agent_type not in valid_types:
        return _mcp_text_result(
            f"Error: Invalid agent_type '{agent_type}'. Use: {', '.join(sorted(valid_types))}",
            is_error=True,
        )

    try:
        from agents.orchestrator import orchestrator
        from db.database import async_session

        async with async_session() as db:
            conversation_id = uuid.uuid4()
            session = await orchestrator.spawn(
                db=db,
                agent_type=agent_type,
                task=task,
                conversation_id=conversation_id,
            )
            await db.commit()

            result_text = (
                f"Agent spawned successfully.\n"
                f"Agent ID: {session.id}\n"
                f"Type: {agent_type}\n"
                f"Name: {session.agent_name}\n"
                f"Status: {session.status}\n"
                f"Task: {task}"
            )
            return _mcp_text_result(result_text)

    except Exception as e:
        logger.exception("pub_spawn_agent failed")
        return _mcp_text_result(f"Failed to spawn agent: {e}", is_error=True)


async def _handle_pub_agent_status(arguments: Dict[str, Any]) -> Dict:
    """Handle pub_agent_status tool call."""
    agent_id_str = arguments.get("agent_id")
    if not agent_id_str:
        return _mcp_text_result("Error: 'agent_id' parameter is required", is_error=True)

    try:
        agent_id = uuid.UUID(agent_id_str)
    except ValueError:
        return _mcp_text_result(
            f"Error: Invalid UUID format: '{agent_id_str}'",
            is_error=True,
        )

    try:
        from agents.orchestrator import orchestrator

        agent = orchestrator.get_agent(agent_id)
        if not agent:
            # Agent might have been cleaned up; check the DB
            from db.database import async_session
            from db.models import AgentSession
            from sqlalchemy import select

            async with async_session() as db:
                result = await db.execute(
                    select(AgentSession).where(AgentSession.id == agent_id)
                )
                session = result.scalar_one_or_none()

            if session:
                result_text = (
                    f"Agent ID: {session.id}\n"
                    f"Type: {session.agent_type}\n"
                    f"Name: {session.agent_name}\n"
                    f"Status: {session.status}\n"
                    f"Created: {session.created_at}\n"
                    f"Completed: {session.completed_at or 'N/A'}\n"
                    f"Result: {json.dumps(session.result) if session.result else 'N/A'}"
                )
                return _mcp_text_result(result_text)
            else:
                return _mcp_text_result(
                    f"Agent not found: {agent_id_str}",
                    is_error=True,
                )

        # Agent is still in memory
        state = agent.get_state()
        result_text = (
            f"Agent ID: {state.get('id', agent_id_str)}\n"
            f"Type: {state.get('type', 'unknown')}\n"
            f"Name: {state.get('name', 'unknown')}\n"
            f"Status: {state.get('status', 'unknown')}\n"
            f"Steps: {state.get('steps', 0)}\n"
            f"Result: {json.dumps(state.get('result')) if state.get('result') else 'In progress'}"
        )
        return _mcp_text_result(result_text)

    except Exception as e:
        logger.exception("pub_agent_status failed")
        return _mcp_text_result(f"Failed to get agent status: {e}", is_error=True)


# Tool handler dispatch table
TOOL_HANDLERS = {
    "pub_chat": _handle_pub_chat,
    "pub_execute_code": _handle_pub_execute_code,
    "pub_search_knowledge": _handle_pub_search_knowledge,
    "pub_spawn_agent": _handle_pub_spawn_agent,
    "pub_agent_status": _handle_pub_agent_status,
}

# ---------------------------------------------------------------------------
# JSON-RPC Method Dispatch
# ---------------------------------------------------------------------------


async def _dispatch(method: str, params: Optional[Dict], id: Any) -> Dict:
    """Route a JSON-RPC method to the appropriate handler."""

    # ---- initialize ----
    if method == "initialize":
        return _jsonrpc_success(id, {
            "protocolVersion": "2024-11-05",
            "capabilities": SERVER_CAPABILITIES,
            "serverInfo": SERVER_INFO,
        })

    # ---- notifications/initialized (client acknowledgement, no response needed) ----
    if method == "notifications/initialized":
        # This is a notification (no id expected in spec), but respond if id is present
        if id is not None:
            return _jsonrpc_success(id, {})
        return None  # Notifications don't get responses

    # ---- ping ----
    if method == "ping":
        return _jsonrpc_success(id, {})

    # ---- tools/list ----
    if method == "tools/list":
        return _jsonrpc_success(id, {"tools": MCP_TOOLS})

    # ---- tools/call ----
    if method == "tools/call":
        if not params:
            return _jsonrpc_error(id, INVALID_PARAMS, "Missing params for tools/call")

        tool_name = params.get("name")
        arguments = params.get("arguments", {})

        if not tool_name:
            return _jsonrpc_error(id, INVALID_PARAMS, "Missing 'name' in tools/call params")

        handler = TOOL_HANDLERS.get(tool_name)
        if not handler:
            return _jsonrpc_error(
                id,
                INVALID_PARAMS,
                f"Unknown tool: '{tool_name}'. Available: {', '.join(TOOL_HANDLERS.keys())}",
            )

        try:
            result = await handler(arguments)
            return _jsonrpc_success(id, result)
        except Exception as e:
            logger.exception("Tool call '%s' raised an exception", tool_name)
            return _jsonrpc_error(id, INTERNAL_ERROR, f"Tool execution failed: {e}")

    # ---- resources/list ----
    if method == "resources/list":
        return _jsonrpc_success(id, {"resources": MCP_RESOURCES})

    # ---- resources/read ----
    if method == "resources/read":
        uri = (params or {}).get("uri", "")
        if uri == "pub-ai://status":
            try:
                from ai.provider import ai_provider
                resolved = await ai_provider._resolve()
                status_data = {
                    "status": "online",
                    "model": resolved.name,
                    "provider": resolved.provider_type,
                    "endpoint": resolved.endpoint_url,
                }
            except RuntimeError:
                status_data = {"status": "online", "model": "none", "provider": "none"}

            return _jsonrpc_success(id, {
                "contents": [{
                    "uri": uri,
                    "mimeType": "application/json",
                    "text": json.dumps(status_data, indent=2),
                }],
            })
        return _jsonrpc_error(id, INVALID_PARAMS, f"Unknown resource URI: '{uri}'")

    # ---- prompts/list ----
    if method == "prompts/list":
        return _jsonrpc_success(id, {"prompts": MCP_PROMPTS})

    # ---- prompts/get ----
    if method == "prompts/get":
        prompt_name = (params or {}).get("name", "")
        if prompt_name == "code_review":
            args = (params or {}).get("arguments", {})
            code = args.get("code", "")
            language = args.get("language", "")
            lang_note = f" ({language})" if language else ""
            return _jsonrpc_success(id, {
                "description": "Code review prompt",
                "messages": [
                    {
                        "role": "user",
                        "content": {
                            "type": "text",
                            "text": (
                                f"Please review the following{lang_note} code for bugs, "
                                f"style issues, and potential improvements:\n\n```{language}\n{code}\n```"
                            ),
                        },
                    },
                ],
            })
        return _jsonrpc_error(id, INVALID_PARAMS, f"Unknown prompt: '{prompt_name}'")

    # ---- Unknown method ----
    return _jsonrpc_error(id, METHOD_NOT_FOUND, f"Method not found: '{method}'")


# ---------------------------------------------------------------------------
# FastAPI Endpoints
# ---------------------------------------------------------------------------


@router.post("")
async def mcp_jsonrpc(request: Request):
    """Main MCP JSON-RPC 2.0 endpoint.

    Accepts JSON-RPC requests and dispatches to the appropriate handler.
    No authentication required (MCP clients handle auth separately).
    """
    # Parse request body
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            _jsonrpc_error(None, PARSE_ERROR, "Parse error: invalid JSON"),
            status_code=200,  # JSON-RPC errors are always 200 at HTTP level
        )

    # Validate JSON-RPC structure
    if not isinstance(body, dict):
        return JSONResponse(
            _jsonrpc_error(None, INVALID_REQUEST, "Invalid Request: body must be a JSON object"),
        )

    jsonrpc = body.get("jsonrpc")
    if jsonrpc != "2.0":
        return JSONResponse(
            _jsonrpc_error(
                body.get("id"),
                INVALID_REQUEST,
                "Invalid Request: 'jsonrpc' must be '2.0'",
            ),
        )

    method = body.get("method")
    if not method or not isinstance(method, str):
        return JSONResponse(
            _jsonrpc_error(
                body.get("id"),
                INVALID_REQUEST,
                "Invalid Request: 'method' must be a non-empty string",
            ),
        )

    request_id = body.get("id")
    params = body.get("params")

    # Dispatch
    response = await _dispatch(method, params, request_id)

    # Notifications (no id) don't get responses
    if response is None:
        return JSONResponse(content={}, status_code=204)

    return JSONResponse(content=response)


@router.get("/sse")
async def mcp_sse(request: Request):
    """SSE transport endpoint for MCP streaming.

    Provides a basic Server-Sent Events stream. The client can POST
    JSON-RPC messages to /mcp and receive responses here as SSE events.

    This is a simplified implementation that sends a connection
    confirmation and keeps the stream alive with periodic pings.
    Real MCP SSE transport would multiplex request/response over
    this channel.
    """

    async def event_generator():
        # Send initial connection event
        connect_event = {
            "jsonrpc": "2.0",
            "method": "connection/ready",
            "params": {
                "serverInfo": SERVER_INFO,
                "capabilities": SERVER_CAPABILITIES,
            },
        }
        yield f"event: message\ndata: {json.dumps(connect_event)}\n\n"

        # Send the endpoint URL the client should POST JSON-RPC requests to
        endpoint_event = {
            "jsonrpc": "2.0",
            "method": "endpoint",
            "params": {"url": "/mcp"},
        }
        yield f"event: endpoint\ndata: {json.dumps(endpoint_event)}\n\n"

        # Keep-alive loop
        try:
            while True:
                await asyncio.sleep(30)
                yield f": ping\n\n"
        except asyncio.CancelledError:
            return

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
