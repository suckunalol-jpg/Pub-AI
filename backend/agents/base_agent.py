from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ai.prompts import AGENT_SYSTEM_PROMPT
from ai.provider import ai_provider


@dataclass
class AgentContext:
    task: str
    conversation_history: List[Dict[str, str]] = field(default_factory=list)
    config: Dict[str, Any] = field(default_factory=dict)
    parent_id: Optional[uuid.UUID] = None


class BaseAgent:
    """Base class for all Pub AI agents."""

    def __init__(self, agent_id: uuid.UUID, agent_type: str, name: str, context: AgentContext):
        self.id = agent_id
        self.agent_type = agent_type
        self.name = name
        self.context = context
        self.status = "running"
        self.result: Optional[Dict] = None
        self._messages: List[Dict[str, str]] = [
            {"role": "system", "content": self._build_system_prompt()},
        ]

    def _build_system_prompt(self) -> str:
        return f"{AGENT_SYSTEM_PROMPT}\n\nYour type: {self.agent_type}\nYour name: {self.name}\nYour task: {self.context.task}"

    async def run(self) -> Dict[str, Any]:
        """Execute the agent's main task."""
        self._messages.append({"role": "user", "content": self.context.task})

        try:
            response = await ai_provider.chat(messages=self._messages)
            self._messages.append({"role": "assistant", "content": response.content})
            self.result = {
                "content": response.content,
                "tokens_in": response.tokens_in,
                "tokens_out": response.tokens_out,
            }
            self.status = "completed"
        except Exception as e:
            self.result = {"error": str(e)}
            self.status = "failed"

        return self.result

    async def handle_message(self, message: str) -> str:
        """Handle an incoming message while the agent is running."""
        self._messages.append({"role": "user", "content": message})
        response = await ai_provider.chat(messages=self._messages)
        self._messages.append({"role": "assistant", "content": response.content})
        return response.content

    def stop(self):
        self.status = "failed"
        self.result = self.result or {"error": "Stopped by user"}
