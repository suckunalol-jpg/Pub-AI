"""
Call Subordinate Tool — adapted from Agent Zero's call_subordinate.py.
Creates a child agent to handle subtasks independently.
"""

import logging
from typing import TYPE_CHECKING

from agent_engine.tools_base import BaseTool, register_tool

if TYPE_CHECKING:
    from agent_engine.agent import Agent

logger = logging.getLogger(__name__)


@register_tool
class CallSubordinateTool(BaseTool):
    """Create a subordinate agent to handle a specific subtask."""

    name = "call_subordinate"
    description = (
        "Delegate a subtask to a subordinate agent. The subordinate will work "
        "independently and return the result. "
        "Args: task (description of the subtask), role (optional role/specialization for the subordinate)."
    )

    async def execute(self) -> str:
        task = self.args.get("task", self.args.get("message", ""))
        role = self.args.get("role", "")

        if not task:
            return "Error: No task provided for subordinate."

        try:
            from agent_engine.agent import Agent, AgentConfig

            # Create subordinate with same config but new number
            sub_config = AgentConfig(
                chat_model=self.agent.config.chat_model,
                utility_model=self.agent.config.utility_model,
            )

            # Add role to system prompt if provided
            if role:
                sub_config.system_prompt = f"You are a specialized subordinate agent. Your role: {role}\n\nYou must complete the task given to you and return a clear result."

            subordinate = Agent(
                config=sub_config,
                number=self.agent.number + 1,
                parent=self.agent,
            )
            
            # Register with the root agent so API can route direct messages to this tab
            self.agent.register_sub_agent(subordinate)

            # Run the subordinate's monologue
            result = ""
            async for event in subordinate.process_message(task):
                if event.type == "response":
                    result = event.content
                elif event.type == "error":
                    result = f"Subordinate error: {event.content}"
                
                # Forward event up to the parent so the API stream receives it
                await self.agent.emit_event(event)

            return result or "Subordinate completed but returned no response."

        except Exception as e:
            logger.error(f"Subordinate agent error: {e}")
            return f"Failed to create subordinate: {str(e)}"
