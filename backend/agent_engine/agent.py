"""
Core Agent — adapted from Agent Zero's agent.py.
Implements the agentic loop: receive message → build prompt → call LLM → parse tools → execute → repeat.
"""

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Callable, Awaitable, Optional

from agent_engine.models import ChatModel, ModelConfig, ChatResult, get_chat_model, default_chat_config, default_utility_config
from agent_engine.tools_base import BaseTool, ResponseTool, parse_tool_call, get_tool, get_all_tools

# Import tool implementations so they auto-register themselves
import agent_engine.tools  # noqa: F401

logger = logging.getLogger(__name__)

# Maximum iterations per monologue to prevent infinite loops
MAX_ITERATIONS = 25


# ── Agent Configuration ───────────────────────────────────────

@dataclass
class AgentConfig:
    """Configuration for an Agent instance."""
    chat_model: ModelConfig = field(default_factory=default_chat_config)
    utility_model: ModelConfig = field(default_factory=default_utility_config)
    system_prompt: str = ""
    max_iterations: int = MAX_ITERATIONS
    code_exec_enabled: bool = True
    code_exec_docker: bool = False
    code_exec_ssh_addr: str = "localhost"
    code_exec_ssh_port: int = 55022
    code_exec_ssh_user: str = "root"
    code_exec_ssh_pass: str = ""


# ── History Management ────────────────────────────────────────

@dataclass
class HistoryMessage:
    """A single message in the conversation history."""
    role: str  # "system", "user", "assistant"
    content: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        if self.metadata and "attachments" in self.metadata:
            atts = self.metadata["attachments"]
            if atts:
                content = [{"type": "text", "text": self.content}]
                for att in atts:
                    if isinstance(att, dict) and att.get("content_type", "").startswith("image/"):
                        content.append({
                            "type": "image_url",
                            "image_url": {"url": att.get("url")}
                        })
                # If we actually added image blocks, return the object array.
                if len(content) > 1:
                    return {"role": self.role, "content": content}
        return {"role": self.role, "content": self.content}


class History:
    """Manages conversation history for an agent."""

    def __init__(self, max_messages: int = 100):
        self.messages: list[HistoryMessage] = []
        self.max_messages = max_messages

    def add(self, role: str, content: str, **metadata) -> HistoryMessage:
        msg = HistoryMessage(role=role, content=content, metadata=metadata)
        self.messages.append(msg)
        # Trim old messages if exceeding limit (keep system + last N)
        if len(self.messages) > self.max_messages:
            self.messages = self.messages[-self.max_messages:]
        return msg

    def to_list(self) -> list[dict]:
        """Convert history to list of dicts for LLM API."""
        return [m.to_dict() for m in self.messages]

    def clear(self):
        self.messages.clear()


# ── Stream Event Types ────────────────────────────────────────

@dataclass
class AgentEvent:
    """Events emitted during agent execution for real-time streaming."""
    type: str  # "thinking", "response", "tool_call", "tool_result", "error", "done"
    content: str = ""
    data: dict = field(default_factory=dict)
    agent_name: str = "Main Agent"


# ── The Agent ─────────────────────────────────────────────────

class Agent:
    """
    Core agentic AI — runs a loop of LLM calls + tool execution.
    Adapted from Agent Zero's monologue system.
    """

    def __init__(
        self,
        config: Optional[AgentConfig] = None,
        number: int = 0,
        parent: Optional["Agent"] = None,
    ):
        self.config = config or AgentConfig()
        self.number = number
        self.agent_name = "Main Agent" if number == 0 else f"Agent-{number}"
        self.parent = parent
        self.history = History()
        self.chat_model = get_chat_model(self.config.chat_model)
        self.memories: list[dict] = []  # persistent memory store
        self._running = False
        self._cancelled = False
        self._event_queue: Optional[asyncio.Queue] = None
        self.sub_agents: dict[str, "Agent"] = {}
        self._mcp_initialized = False

    async def init_mcp_servers(self):
        """Discover and register MCP server tools (called once on first use)."""
        if self._mcp_initialized or self.parent:
            return
        self._mcp_initialized = True
        try:
            mcp_config = self._load_mcp_config()
            if mcp_config:
                from agent_engine.mcp_client import discover_and_register_mcp_servers
                tools = await discover_and_register_mcp_servers(mcp_config)
                if tools:
                    logger.info(f"MCP tools registered: {tools}")
        except Exception as e:
            logger.warning(f"MCP server init failed: {e}")

    def _load_mcp_config(self) -> list[dict]:
        """Load MCP server config from ~/.pub-ai/mcp_servers.json or env."""
        import json as _json
        config_path = os.path.expanduser("~/.pub-ai/mcp_servers.json")
        if os.path.isfile(config_path):
            with open(config_path, "r") as f:
                return _json.load(f)
        env_val = os.getenv("MCP_SERVERS", "")
        if env_val:
            return _json.loads(env_val)
        return []

    def register_sub_agent(self, subordinate: "Agent"):
        """Register a spawned sub-agent so the API can route direct messages to it."""
        self.sub_agents[subordinate.agent_name] = subordinate
        # Also register with the root parent if we are a nested sub-agent
        if self.parent:
            self.parent.register_sub_agent(subordinate)

    def get_system_prompt(self) -> str:
        """Build the system prompt including tool descriptions."""
        tools = get_all_tools()
        tool_descriptions = []
        for name, tool_cls in tools.items():
            tool_descriptions.append(f"- **{name}**: {tool_cls.description}")

        tools_text = "\n".join(tool_descriptions) if tool_descriptions else "No tools available."

        # Support Agent Zero style prompt/behavior files
        system_file = os.path.join(os.getcwd(), "agent_engine", "prompts", "system.md")
        behavior_file = os.path.join(os.getcwd(), "agent_engine", "prompts", "behavior.md")
        
        base_prompt = self.config.system_prompt
        
        if not base_prompt:
            if os.path.exists(system_file):
                with open(system_file, "r", encoding="utf-8") as f:
                    base_prompt = f.read()
            else:
                from ai.prompts import GENERAL_SYSTEM_PROMPT
                base_prompt = GENERAL_SYSTEM_PROMPT

        if os.path.exists(behavior_file):
            with open(behavior_file, "r", encoding="utf-8") as f:
                behavior_text = f.read()
                base_prompt += f"\n\n--- BEHAVIOR INSTRUCTIONS ---\n{behavior_text}"

        return base_prompt.replace("{{tools}}", tools_text)

    async def emit_event(self, event: AgentEvent):
        """Emit an event to the queue."""
        if not event.agent_name or event.agent_name == "Main Agent":
             event.agent_name = self.agent_name
             
        if self._event_queue:
            await self._event_queue.put(event)

    async def process_message(
        self,
        user_message: str,
        attachments: list[dict] | None = None,
    ) -> AsyncGenerator[AgentEvent, None]:
        """
        Process a user message through the agentic loop.
        Yields AgentEvent objects for real-time streaming using an event queue.
        """
        self._running = True
        self._cancelled = False
        self._event_queue = asyncio.Queue()

        # Initialize MCP servers on first message (only for root agent)
        await self.init_mcp_servers()

        async def _run():
            try:
                # Add user message to history
                if attachments:
                    self.history.add("user", user_message, attachments=attachments)
                else:
                    self.history.add("user", user_message)

                # Run the monologue loop
                await self._monologue()
            except Exception as e:
                logger.error(f"Agent error: {e}", exc_info=True)
                await self.emit_event(AgentEvent(type="error", content=str(e)))
            finally:
                await self.emit_event(AgentEvent(type="_internal_done"))

        # Spawn monologue wrapper
        task = asyncio.create_task(_run())

        try:
            while True:
                event = await self._event_queue.get()
                if event.type == "_internal_done":
                    break
                if self._cancelled:
                    task.cancel()
                    break
                yield event
        finally:
            self._running = False

    async def _monologue(self) -> None:
        """
        The core agentic loop — adapted from Agent Zero.
        Loops: build prompt → call LLM → parse response → execute tools → repeat.
        Stops when the agent uses the 'response' tool or hits max iterations.
        """
        iteration = 0

        while iteration < self.config.max_iterations and not self._cancelled:
            iteration += 1
            await self.emit_event(AgentEvent(type="thinking", content=f"Iteration {iteration}"))

            try:
                # Build the prompt
                messages = self._build_messages()

                # Call the LLM with streaming
                full_response = ""
                _contains_tool = False

                async def on_token(token: str, full: str):
                    nonlocal full_response, _contains_tool
                    full_response = full

                    # Detect tool calls early — stop streaming to UI once we see JSON
                    if not _contains_tool:
                        if '{"tool_name"' in full or '{"tool"' in full or "```json" in full or '{"action"' in full:
                            _contains_tool = True
                            return

                    if _contains_tool:
                        return

                    await self.emit_event(AgentEvent(type="response_stream", content=token))

                # Get response asynchronously (streaming if callback provided)
                result = await self.chat_model.chat(
                    messages=messages,
                    stream=True,
                    response_callback=on_token,
                )
                full_response = result.response

                # Add assistant response to history
                self.history.add("assistant", full_response)

                # Parse for tool calls
                tool_call = parse_tool_call(full_response)

                if tool_call:
                    tool_name = tool_call["tool_name"]
                    tool_args = tool_call["tool_args"]

                    await self.emit_event(AgentEvent(
                        type="tool_call",
                        content=f"Using tool: {tool_name}",
                        data={"tool_name": tool_name, "tool_args": tool_args},
                    ))

                    # Execute the tool
                    tool_result = await self._execute_tool(tool_name, tool_args)

                    # Check if it's the response tool (final answer)
                    if tool_name == "response":
                        await self.emit_event(AgentEvent(
                            type="response",
                            content=tool_result,
                        ))
                        await self.emit_event(AgentEvent(type="done"))
                        return

                    # Add tool result to history and nudge the model to continue
                    self.history.add(
                        "user",
                        f"[SYSTEM] Tool '{tool_name}' returned:\n{tool_result}\n\nNow continue. Use another tool or use the `response` tool to give your final answer.",
                        metadata={"tool_name": tool_name},
                    )

                    await self.emit_event(AgentEvent(
                        type="tool_result",
                        content=tool_result,
                        data={"tool_name": tool_name},
                    ))
                else:
                    # No tool call — treat as direct response
                    await self.emit_event(AgentEvent(type="response", content=full_response))
                    await self.emit_event(AgentEvent(type="done"))
                    return

            except Exception as e:
                logger.error(f"Monologue iteration error: {e}", exc_info=True)
                error_msg = f"Error in iteration {iteration}: {str(e)}"
                self.history.add("user", f"System error: {error_msg}")
                await self.emit_event(AgentEvent(type="error", content=error_msg))

                if iteration >= 3:
                    await self.emit_event(AgentEvent(type="response", content="I encountered repeated errors. Please try rephrasing your request."))
                    await self.emit_event(AgentEvent(type="done"))
                    return

        # Hit max iterations
        await self.emit_event(AgentEvent(type="response", content="I've reached the maximum number of reasoning steps. Here's what I have so far."))
        await self.emit_event(AgentEvent(type="done"))

    def _build_messages(self) -> list[dict]:
        """Build the full message list for the LLM call."""
        system_prompt = self.get_system_prompt()
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(self.history.to_list())
        return messages

    async def _execute_tool(self, tool_name: str, tool_args: dict) -> str:
        """Find and execute a registered tool."""
        tool_class = get_tool(tool_name)

        if not tool_class:
            return f"Error: Unknown tool '{tool_name}'. Available tools: {', '.join(get_all_tools().keys())}"

        try:
            tool_instance = tool_class(agent=self, args=tool_args)
            result = await tool_instance.execute()
            return result or "Tool executed successfully (no output)."
        except Exception as e:
            logger.error(f"Tool '{tool_name}' execution error: {e}", exc_info=True)
            return f"Error executing '{tool_name}': {str(e)}"

    def cancel(self):
        """Cancel the current monologue."""
        self._cancelled = True

    def reset(self):
        """Reset the agent state."""
        self.history.clear()
        self._running = False
        self._cancelled = False


# ── Default System Prompt ─────────────────────────────────────

DEFAULT_SYSTEM_PROMPT = """# Pub-AI Agent System

You are Pub-AI, an autonomous AI agent that DOES things by calling tools. You never just describe — you ACT.

## Rules
1. You MUST use tools. Do NOT write code and tell the user to run it. Run it yourself with `code_execution`.
2. Output EXACTLY ONE tool call per response as a JSON block.
3. Wait for the tool result before your next action.
4. When done, ALWAYS use the `response` tool to give your final answer.
5. If a tool errors, try a different approach. Do NOT give up.

## Tools Available
{{tools}}

## Tool Call Format
```json
{"tool_name": "TOOL_NAME", "tool_args": {"arg": "value"}}
```

## Key Tools

**code_execution** — Run code: `{"tool_name": "code_execution", "tool_args": {"runtime": "python", "code": "print(1+1)"}}`
Runtimes: python, nodejs, terminal

**web_search** — Search web: `{"tool_name": "web_search", "tool_args": {"query": "how to X"}}`

**read_file** — Read file: `{"tool_name": "read_file", "tool_args": {"path": "file.py"}}`

**write_file** — Write file: `{"tool_name": "write_file", "tool_args": {"path": "file.py", "content": "..."}}`

**edit_file** — Edit file: `{"tool_name": "edit_file", "tool_args": {"path": "file.py", "old_text": "old", "new_text": "new"}}`

**list_files** — List files: `{"tool_name": "list_files", "tool_args": {"path": ".", "pattern": "*.py"}}`

**memory_save** — Remember: `{"tool_name": "memory_save", "tool_args": {"text": "info", "area": "general"}}`

**memory_load** — Recall: `{"tool_name": "memory_load", "tool_args": {"query": "search"}}`

**call_subordinate** — Delegate: `{"tool_name": "call_subordinate", "tool_args": {"task": "do X", "role": "coder"}}`

**browser_agent** — Browse: `{"tool_name": "browser_agent", "tool_args": {"task": "go to URL"}}`

**scheduler** — Schedule: `{"tool_name": "scheduler", "tool_args": {"action": "create", "task": "do X", "interval": "1h"}}`

**container_shell** — Run shell commands in your sandbox computer: `{"tool_name": "container_shell", "tool_args": {"command": "apt install -y ffmpeg && ffmpeg -version"}}`

**container_python** — Run Python in sandbox: `{"tool_name": "container_python", "tool_args": {"code": "import requests; print(requests.get('https://httpbin.org/ip').json())"}}`

**container_install** — Install packages: `{"tool_name": "container_install", "tool_args": {"packages": "flask redis", "manager": "pip"}}`

**container_download** — Download file to sandbox: `{"tool_name": "container_download", "tool_args": {"url": "https://example.com/file.zip"}}`

**container_upload** — Copy files host<->container: `{"tool_name": "container_upload", "tool_args": {"src": "/path/file", "dest": "/workspace/file", "direction": "to_container"}}`

**git_ops** — Git operations: `{"tool_name": "git_ops", "tool_args": {"action": "commit", "message": "fix bug"}}`
Actions: status, add, commit, push, pull, log, diff, branch, checkout, clone

**vpn_proxy** — VPN/proxy management: `{"tool_name": "vpn_proxy", "tool_args": {"action": "check_ip"}}`
Actions: connect_vpn, disconnect_vpn, set_proxy, check_ip

**browser_screenshot** — Screenshot a page: `{"tool_name": "browser_screenshot", "tool_args": {"url": "https://example.com"}}`

**browser_download** — Download via browser: `{"tool_name": "browser_download", "tool_args": {"url": "https://example.com/download"}}`

**response** — Final answer (REQUIRED when done):
```json
{"tool_name": "response", "tool_args": {"text": "Here is your answer..."}}
```
"""
