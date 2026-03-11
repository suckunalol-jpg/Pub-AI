import logging
from typing import TYPE_CHECKING
from agent_engine.tools_base import BaseTool, register_tool

try:
    from browser_use import Agent as BrowserUseAgent
    BROWSER_USE_AVAILABLE = True
except ImportError:
    BROWSER_USE_AVAILABLE = False

if TYPE_CHECKING:
    from agent_engine.agent import Agent

logger = logging.getLogger(__name__)

@register_tool
class BrowserAgentTool(BaseTool):
    """Run browser automation tasks using browser-use."""
    name = "browser_agent"
    description = (
        "Automate the browser to perform a task. "
        "Args: task (the instruction for the browser). "
        "Returns the result of the browser action."
    )

    async def execute(self) -> str:
        if not BROWSER_USE_AVAILABLE:
            return "Error: browser-use package is not installed."
            
        task = self.args.get("task", "")
        if not task:
            return "Error: No task provided."
            
        try:
            # We can use LangChain LLM instance as required by Browser Use
            from langchain_openai import ChatOpenAI
            import os
            
            # Simple fallback to GPT-4o-mini or let user config decide
            llm_model = os.getenv("BROWSER_MODEL", "gpt-4o-mini")
            llm = ChatOpenAI(model=llm_model)

            browser_agent = BrowserUseAgent(
                task=task,
                llm=llm
            )
            result = await browser_agent.run()
            return str(result)
        except Exception as e:
            return f"Browser automation failed: {str(e)}"
