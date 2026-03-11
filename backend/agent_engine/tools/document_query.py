"""
Document Query Tool — RAG over uploaded documents.
Uses ChromaDB (already in Pub-AI's requirements) for vector search.
"""

import logging
from typing import TYPE_CHECKING

from agent_engine.tools_base import BaseTool, register_tool

if TYPE_CHECKING:
    from agent_engine.agent import Agent

logger = logging.getLogger(__name__)


@register_tool
class DocumentQueryTool(BaseTool):
    """Query uploaded knowledge/documents using semantic search."""

    name = "document_query"
    description = (
        "Search through uploaded knowledge documents for relevant information. "
        "Args: query (what to search for)."
    )

    async def execute(self) -> str:
        query = self.args.get("query", "")

        if not query:
            return "Error: No query provided."

        try:
            import chromadb

            # Use Pub-AI's existing ChromaDB collection
            client = chromadb.PersistentClient(path="./data/chroma")
            collection = client.get_or_create_collection("knowledge_base")

            results = collection.query(
                query_texts=[query],
                n_results=5,
            )

            if not results["documents"] or not results["documents"][0]:
                return f"No relevant documents found for '{query}'."

            output = []
            for i, (doc, meta) in enumerate(
                zip(results["documents"][0], results["metadatas"][0]), 1
            ):
                source = meta.get("source", "unknown") if meta else "unknown"
                output.append(f"{i}. [{source}]\n{doc[:500]}")

            return "\n\n".join(output)

        except Exception as e:
            logger.error(f"Document query error: {e}")
            return f"Document query error: {str(e)}"
