"""
Web Search Tool — adapted from Agent Zero's search_engine.py.
Uses DuckDuckGo for free web search.
"""

import logging
from typing import TYPE_CHECKING

from agent_engine.tools_base import BaseTool, register_tool

if TYPE_CHECKING:
    from agent_engine.agent import Agent

logger = logging.getLogger(__name__)

MAX_RESULTS = 8


@register_tool
class WebSearchTool(BaseTool):
    """Search the web using DuckDuckGo."""

    name = "web_search"
    description = (
        "Search the web for information using DuckDuckGo. "
        "Args: query (search terms), max_results (number of results, default 8)."
    )

    async def execute(self) -> str:
        query = self.args.get("query", "")
        max_results = int(self.args.get("max_results", MAX_RESULTS))

        if not query:
            return "Error: No search query provided."

        try:
            from duckduckgo_search import DDGS

            results = []
            with DDGS() as ddgs:
                for r in ddgs.text(query, max_results=max_results):
                    results.append(r)

            if not results:
                return f"No results found for '{query}'."

            output = []
            for i, r in enumerate(results, 1):
                title = r.get("title", "No title")
                url = r.get("href", r.get("link", ""))
                body = r.get("body", r.get("snippet", ""))
                output.append(f"{i}. **{title}**\n   {url}\n   {body}")

            return "\n\n".join(output)

        except ImportError:
            return "Error: duckduckgo-search package not installed. Run: pip install duckduckgo-search"
        except Exception as e:
            logger.error(f"Web search error: {e}")
            return f"Search error: {str(e)}"
