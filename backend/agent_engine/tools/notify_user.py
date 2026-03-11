import logging
from typing import TYPE_CHECKING
from agent_engine.tools_base import BaseTool, register_tool

if TYPE_CHECKING:
    from agent_engine.agent import Agent

logger = logging.getLogger(__name__)

@register_tool
class NotifyUserTool(BaseTool):
    """Notify the user or ask a question."""
    name = "notify_user"
    description = (
        "Send a message or question to the user. "
        "Args: message (the content to send). "
        "Returns 'Notification sent'. Note: Does not block for a response."
    )

    async def execute(self) -> str:
        message = self.args.get("message", "")
        if not message:
            return "Error: No message provided."
        
        # Emits a response directly to the user stream
        if self.agent:
            await self.agent.emit_event("response_stream", f"\n[Notification to User: {message}]\n")
            
        return "Notification sent to user."
