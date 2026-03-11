"""
Memory Tools — adapted from Agent Zero's memory_save/load/delete/forget.
Uses a simple JSON-file backed memory store for persistence.
"""

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from agent_engine.tools_base import BaseTool, register_tool

if TYPE_CHECKING:
    from agent_engine.agent import Agent

logger = logging.getLogger(__name__)

# Simple file-based memory store
MEMORY_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "memories")


def _ensure_memory_dir():
    os.makedirs(MEMORY_DIR, exist_ok=True)


def _load_memories() -> list[dict]:
    """Load all memories from the JSON file."""
    _ensure_memory_dir()
    filepath = os.path.join(MEMORY_DIR, "memories.json")
    if not os.path.exists(filepath):
        return []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []


def _save_memories(memories: list[dict]):
    """Save all memories to the JSON file."""
    _ensure_memory_dir()
    filepath = os.path.join(MEMORY_DIR, "memories.json")
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(memories, f, indent=2, default=str)


@register_tool
class MemorySaveTool(BaseTool):
    """Save information to persistent memory for future recall."""

    name = "memory_save"
    description = (
        "Save a piece of information to persistent memory. "
        "Args: text (what to remember), area (category, e.g. 'solutions', 'facts', 'instructions')."
    )

    async def execute(self) -> str:
        text = self.args.get("text", "")
        area = self.args.get("area", "general")

        if not text:
            return "Error: No text provided to save."

        memory_id = str(uuid.uuid4())[:8]
        memory_entry = {
            "id": memory_id,
            "text": text,
            "area": area,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        memories = _load_memories()
        memories.append(memory_entry)
        _save_memories(memories)

        return f"Memory saved (id: {memory_id})."


@register_tool
class MemoryLoadTool(BaseTool):
    """Search and recall information from persistent memory."""

    name = "memory_load"
    description = (
        "Search persistent memory for relevant information. "
        "Args: query (search terms), limit (max results, default 5)."
    )

    async def execute(self) -> str:
        query = self.args.get("query", "").lower()
        limit = int(self.args.get("limit", 5))

        if not query:
            return "Error: No query provided."

        memories = _load_memories()

        if not memories:
            return "No memories found. Memory is empty."

        # Simple keyword matching (can be upgraded to vector search later)
        scored = []
        query_words = set(query.split())
        for mem in memories:
            text_lower = mem["text"].lower()
            score = sum(1 for word in query_words if word in text_lower)
            if score > 0:
                scored.append((score, mem))

        scored.sort(key=lambda x: x[0], reverse=True)
        results = scored[:limit]

        if not results:
            return f"No memories found matching '{query}'."

        output = []
        for score, mem in results:
            output.append(f"[{mem['area']}] (id: {mem['id']}): {mem['text']}")

        return "\n\n".join(output)


@register_tool
class MemoryDeleteTool(BaseTool):
    """Delete a specific memory by ID."""

    name = "memory_delete"
    description = (
        "Delete a memory by its ID. "
        "Args: memory_id (the ID of the memory to delete)."
    )

    async def execute(self) -> str:
        memory_id = self.args.get("memory_id", "")

        if not memory_id:
            return "Error: No memory_id provided."

        memories = _load_memories()
        original_count = len(memories)
        memories = [m for m in memories if m["id"] != memory_id]
        _save_memories(memories)

        if len(memories) < original_count:
            return f"Memory {memory_id} deleted."
        else:
            return f"Memory {memory_id} not found."
