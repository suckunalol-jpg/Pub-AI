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


# Register built-in tools
register_tool(ResponseTool)


# ── Tool Parsing ──────────────────────────────────────────────

def parse_tool_call(text: str) -> Optional[dict]:
    """
    Parse a tool call from agent response text.
    Agent Zero uses JSON format like:
    ```json
    {
        "tool_name": "code_execution",
        "tool_args": { "code": "print('hello')", "runtime": "python" }
    }
    ```
    This parser is tolerant of markdown fences, extra text, etc.
    """
    # Try to find JSON block in the text
    json_patterns = [
        # ```json ... ``` blocks
        r'```(?:json)?\s*(\{[^`]*"tool_name"[^`]*\})\s*```',
        # Raw JSON objects with tool_name
        r'(\{[^{}]*"tool_name"\s*:\s*"[^"]*"[^{}]*(?:\{[^{}]*\}[^{}]*)*\})',
        # Alternate format with "tool" instead of "tool_name"
        r'(\{[^{}]*"tool"\s*:\s*"[^"]*"[^{}]*(?:\{[^{}]*\}[^{}]*)*\})',
    ]

    for pattern in json_patterns:
        matches = re.findall(pattern, text, re.DOTALL)
        if matches:
            for match in matches:
                try:
                    parsed = json.loads(match)
                    # Normalize keys
                    tool_name = parsed.get("tool_name", parsed.get("tool", ""))
                    tool_args = parsed.get("tool_args", parsed.get("args", {}))
                    if tool_name:
                        return {"tool_name": tool_name, "tool_args": tool_args}
                except json.JSONDecodeError:
                    continue

    # Try dirty JSON parse as last resort
    try:
        # Find anything that looks like a JSON object
        brace_match = re.search(r'\{.*\}', text, re.DOTALL)
        if brace_match:
            parsed = json.loads(brace_match.group())
            tool_name = parsed.get("tool_name", parsed.get("tool", ""))
            if tool_name:
                tool_args = parsed.get("tool_args", parsed.get("args", {}))
                return {"tool_name": tool_name, "tool_args": tool_args}
    except (json.JSONDecodeError, AttributeError):
        pass

    return None
