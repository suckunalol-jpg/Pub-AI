"""
Tool base class and registry — adapted from Agent Zero.
Each tool is a class with a name, description, and execute() method.
Tools are discovered and registered automatically.
"""

import logging
import json
import re
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from agent_engine.agent import Agent

logger = logging.getLogger(__name__)


class BaseTool:
    """Base class for all agent tools."""

    name: str = ""
    description: str = ""

    def __init__(self, agent: "Agent", args: dict[str, Any]):
        self.agent = agent
        self.args = args
        self.progress: str = ""

    async def execute(self) -> str:
        """Execute the tool and return a result string."""
        raise NotImplementedError

    def set_progress(self, text: Optional[str]):
        """Update progress text (shown to user during execution)."""
        self.progress = text or ""


class ResponseTool(BaseTool):
    """Special tool: agent sends final response to user."""
    name = "response"
    description = "Send a final response to the user and end the current task."

    async def execute(self) -> str:
        text = self.args.get("text", self.args.get("message", ""))
        return text


# ── Tool Registry ─────────────────────────────────────────────

_tool_registry: dict[str, type[BaseTool]] = {}


def register_tool(tool_class: type[BaseTool]):
    """Register a tool class by its name."""
    _tool_registry[tool_class.name] = tool_class
    return tool_class


def get_tool(name: str) -> Optional[type[BaseTool]]:
    """Get a tool class by name."""
    return _tool_registry.get(name)


def get_all_tools() -> dict[str, type[BaseTool]]:
    """Get all registered tools."""
    return dict(_tool_registry)


def register_dynamic_tool(tool_or_name, description: str = "", execute_fn=None):
    """Register a tool dynamically at runtime (used by MCP client, plugins, etc.).

    Can be called as:
      register_dynamic_tool(MyToolClass)          — register an existing BaseTool subclass
      register_dynamic_tool("name", "desc", fn)   — create and register from a function
    """
    if isinstance(tool_or_name, type) and issubclass(tool_or_name, BaseTool):
        # Direct class registration
        _tool_registry[tool_or_name.name] = tool_or_name
        logger.info(f"Dynamically registered tool: {tool_or_name.name}")
        return tool_or_name

    name = tool_or_name
    cls = type(f"DynamicTool_{name}", (BaseTool,), {
        "name": name,
        "description": description,
        "execute": lambda self: execute_fn(self.agent, self.args),
    })
    _tool_registry[name] = cls
    logger.info(f"Dynamically registered tool: {name}")
    return cls


def unregister_tool(name: str):
    """Remove a tool from the registry."""
    _tool_registry.pop(name, None)


# Register built-in tools
register_tool(ResponseTool)


# ── Tool Parsing ──────────────────────────────────────────────

def _fix_and_parse_json(text: str) -> Optional[dict]:
    """Attempt to parse JSON, appending closing characters if it was truncated."""
    text = text.strip()
    if not text:
        return None
        
    # Common suffixes for cut-off JSON
    suffixes = ["", '"']
    for i in range(1, 8):
        suffixes.append("}" * i)
        suffixes.append('"' + "}" * i)
        suffixes.append("]" + "}" * i)
        suffixes.append('"]' + "}" * i)
        
    for suffix in suffixes:
        try:
            return json.loads(text + suffix)
        except json.JSONDecodeError:
            continue
    return None

def parse_tool_call(text: str) -> Optional[dict]:
    """
    Parse a tool call from agent response text.
    Handles standard blocks, raw objects, and brutally truncated JSON streams 
    like `{"tool": "spawn_subagents", "params": {"task": "make a python exploit script"`
    """
    def _extract(parsed: dict) -> Optional[dict]:
        if not isinstance(parsed, dict):
            return None
        tool_name = parsed.get("tool_name", parsed.get("tool", ""))
        tool_args = parsed.get("tool_args", parsed.get("args", parsed.get("params", {})))
        if tool_name:
            if isinstance(tool_args, str):
                try:
                    tool_args = json.loads(tool_args)
                except Exception:
                    tool_args = {"text": tool_args}
            return {"tool_name": str(tool_name), "tool_args": tool_args if isinstance(tool_args, dict) else {}}
        return None

    # 1. Try to find explicit ```... ``` blocks first (ignore language identifier)
    code_blocks = re.findall(r'```[a-zA-Z]*\s*(.*?)\s*```', text, re.DOTALL)
    for block in code_blocks:
        parsed = _fix_and_parse_json(block)
        if parsed:
            ex = _extract(parsed)
            if ex: return ex

    # 2. Try to find any raw JSON block that contains 'tool_name' or 'tool'
    # This regex looks for outer braces { ... } globally
    raw_blocks = re.findall(r'(\{.*?\})', text, re.DOTALL)
    for block in raw_blocks:
        if '"tool_name"' in block or '"tool"' in block:
            parsed = _fix_and_parse_json(block)
            if parsed:
                ex = _extract(parsed)
                if ex: return ex
                
    # 3. Robust bracket matching for nested JSON
    start_idx = text.find('{')
    if start_idx != -1:
        # Try to parse from the first '{' to the end, shrinking from the right until valid
        for end_idx in range(len(text), start_idx, -1):
            if text[end_idx-1] == '}':
                parsed = _fix_and_parse_json(text[start_idx:end_idx])
                if parsed:
                    ex = _extract(parsed)
                    if ex: return ex

    # 4. Fallback for completely truncated/broken JSON at the end of the text
    # e.g., 'blah blah {"tool": "search", "params": {"query": "how to build"'
    last_idx = max(text.rfind('{"tool"'), text.rfind('{"tool_name"'))
    if last_idx != -1:
        broken_block = text[last_idx:]
        parsed = _fix_and_parse_json(broken_block)
        if parsed:
            ex = _extract(parsed)
            if ex: return ex

    return None
