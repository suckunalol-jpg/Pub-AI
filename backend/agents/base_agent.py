"""Base agent with autonomous think-act-observe loop.

Agents can use tools, spawn sub-agents, search the web, execute code,
scan Roblox games, and coordinate with team members.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from ai.provider import ai_provider

logger = logging.getLogger(__name__)

# Max iterations before the agent must finish
MAX_ITERATIONS = 50
# Max iterations for lightweight agent types
LIGHTWEIGHT_MAX = 10


@dataclass
class AgentContext:
    task: str
    conversation_history: List[Dict[str, str]] = field(default_factory=list)
    config: Dict[str, Any] = field(default_factory=dict)
    parent_id: Optional[uuid.UUID] = None
    team_id: Optional[str] = None


class BaseAgent:
    """Autonomous agent with tool-use loop.

    Loop: Think → Pick Tool → Execute → Observe → Repeat until done.
    """

    def __init__(
        self,
        agent_id: uuid.UUID,
        agent_type: str,
        name: str,
        context: AgentContext,
    ):
        self.id = agent_id
        self.agent_type = agent_type
        self.name = name
        self.context = context
        self.status = "running"
        self.result: Optional[Dict] = None
        self.iteration = 0
        self.tool_history: List[Dict[str, Any]] = []
        self.started_at = datetime.utcnow()
        self._messages: List[Dict[str, str]] = []

        # Build initial messages
        self._messages.append({"role": "system", "content": self._build_system_prompt()})

    def _build_system_prompt(self) -> str:
        from agents.tools import tools_prompt
        from agents.system_prompts import CORE_BEHAVIOR, AGENT_TYPE_PROMPTS, TOOL_USE_INSTRUCTIONS

        # Support custom role/specialty overrides from config
        role = self.context.config.get("custom_role")
        specialty = self.context.config.get("custom_specialty")

        if not role or not specialty:
            type_info = AGENT_TYPE_PROMPTS.get(self.agent_type, {})
            role = role or type_info.get("role", "General-purpose autonomous agent")
            specialty = specialty or type_info.get("specialty", "Handle tasks as assigned.")

        team_ctx = ""
        if self.context.team_id:
            team_ctx = f"\nYou are part of team '{self.context.team_id}'. Use message_agent to communicate with teammates."

        extra_prompt = self.context.config.get("system_prompt_extra", "")
        extra_section = f"\n\n**Additional Instructions**:\n{extra_prompt}" if extra_prompt else ""

        return f"""{CORE_BEHAVIOR}

**Identity**: {self.name} ({role})
**Specialty**: {specialty}{team_ctx}

**How you work**:
1. Analyze the task
2. Break it into steps if complex (use plan_tasks or todo_write)
3. Use tools to gather info, write code, execute, search — whatever is needed
4. Observe results and adapt
5. When done, output your final result

**Rules**:
- You have a maximum of {self._max_iterations()} tool calls. Use them wisely.
- If you need info, search for it — don't guess.
- If a task is too big, decompose with plan_tasks, then spawn_agent for sub-tasks.
- If code doesn't work, read the error, fix it, and retry.
- Verify your work before finishing.
- Use specialized tools over generic shell commands (read_file over cat, edit_file over sed).

{TOOL_USE_INSTRUCTIONS}
{extra_section}
{tools_prompt()}"""

    def _max_iterations(self) -> int:
        if self.agent_type in ("reviewer",):
            return LIGHTWEIGHT_MAX
        return MAX_ITERATIONS

    async def run(self) -> Dict[str, Any]:
        """Main autonomous loop: think → act → observe → repeat."""
        from agents.tools import execute_tool

        # Start with the task
        self._messages.append({"role": "user", "content": f"Task: {self.context.task}"})

        max_iter = self._max_iterations()

        while self.status == "running" and self.iteration < max_iter:
            self.iteration += 1

            # Think: get AI response
            try:
                response = await ai_provider.chat(
                    messages=self._messages,
                    temperature=0.4,
                    max_tokens=4096,
                )
            except Exception as e:
                logger.error("Agent %s AI call failed: %s", self.name, e)
                self.status = "failed"
                self.result = {"error": f"AI call failed: {e}"}
                return self.result

            content = response.content
            self._messages.append({"role": "assistant", "content": content})

            # Check if agent is done
            result_match = re.search(r"```result\s*\n(.*?)\n```", content, re.DOTALL)
            if result_match:
                try:
                    result_data = json.loads(result_match.group(1))
                    self.result = {
                        "content": result_data.get("output", content),
                        "status": result_data.get("status", "done"),
                        "iterations": self.iteration,
                        "tools_used": len(self.tool_history),
                    }
                except json.JSONDecodeError:
                    self.result = {
                        "content": result_match.group(1),
                        "iterations": self.iteration,
                        "tools_used": len(self.tool_history),
                    }
                self.status = "completed"
                return self.result

            # Check for tool calls
            tool_matches = list(re.finditer(r"```tool\s*\n(.*?)\n```", content, re.DOTALL))

            if not tool_matches:
                # No tool call and no result block — treat as final answer
                self.result = {
                    "content": content,
                    "iterations": self.iteration,
                    "tools_used": len(self.tool_history),
                }
                self.status = "completed"
                return self.result

            # Execute tools (parallel if multiple)
            tool_results = []
            tool_calls = []

            for match in tool_matches:
                try:
                    call = json.loads(match.group(1))
                    tool_calls.append(call)
                except json.JSONDecodeError:
                    tool_results.append("Error: Invalid JSON in tool call")

            if tool_calls:
                # Execute all tool calls in parallel, passing agent_id for container routing
                tasks = [
                    execute_tool(call.get("tool", ""), call.get("params", {}), agent_id=self.id)
                    for call in tool_calls
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                for call, result in zip(tool_calls, results):
                    tool_name = call.get("tool", "unknown")
                    if isinstance(result, Exception):
                        output = f"Tool '{tool_name}' error: {result}"
                        success = False
                    else:
                        output = result.output
                        success = result.success

                    self.tool_history.append({
                        "iteration": self.iteration,
                        "tool": tool_name,
                        "params": call.get("params", {}),
                        "success": success,
                        "output_preview": output[:500],
                    })
                    tool_results.append(
                        f"**{tool_name}** ({'OK' if success else 'FAILED'}):\n{output}"
                    )

            # Feed observations back
            observation = "Tool results:\n\n" + "\n\n---\n\n".join(tool_results)
            self._messages.append({"role": "user", "content": observation})

        # Exceeded max iterations
        if self.status == "running":
            self.status = "completed"
            self.result = {
                "content": "Reached maximum iterations. Last response:\n" + (
                    self._messages[-1]["content"] if self._messages else ""
                ),
                "iterations": self.iteration,
                "tools_used": len(self.tool_history),
                "max_iterations_reached": True,
            }

        return self.result

    async def handle_message(self, message: str) -> str:
        """Handle an incoming message from another agent or user."""
        self._messages.append({"role": "user", "content": message})
        response = await ai_provider.chat(messages=self._messages, temperature=0.4)
        self._messages.append({"role": "assistant", "content": response.content})
        return response.content

    def stop(self):
        self.status = "failed"
        self.result = self.result or {"error": "Stopped by user"}

    def get_state(self) -> Dict[str, Any]:
        """Return current agent state for monitoring."""
        return {
            "id": str(self.id),
            "name": self.name,
            "type": self.agent_type,
            "status": self.status,
            "iteration": self.iteration,
            "max_iterations": self._max_iterations(),
            "tools_used": len(self.tool_history),
            "tool_history": self.tool_history[-5:],
            "started_at": self.started_at.isoformat(),
            "result_preview": (
                self.result.get("content", "")[:200] if self.result else None
            ),
        }
