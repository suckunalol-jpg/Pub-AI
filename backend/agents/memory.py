"""Per-user semantic memory system.

Stores facts, preferences, skills, patterns, and corrections per user.
Retrieves relevant memories based on semantic similarity to current context.
Learns from every interaction and feedback signal.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select, update, func, and_, or_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    Conversation, Feedback, IntentLog, LearningSignal,
    Message, UserMemory,
)

logger = logging.getLogger(__name__)


class MemorySystem:
    """Per-user learning memory with semantic retrieval.

    Memory types:
      - preference: User likes/dislikes (e.g., "prefers Python", "hates verbose explanations")
      - fact: Facts about the user (e.g., "works on Roblox game called X")
      - skill: User's skill level in areas (e.g., "advanced Python", "beginner Rust")
      - pattern: Recurring patterns (e.g., "usually asks about APIs at night")
      - correction: Things the AI got wrong and corrections
      - project: Project context (e.g., "building a Discord bot with Python")
    """

    # Keywords that signal memory-worthy info
    MEMORY_TRIGGERS = {
        "preference": [
            "i prefer", "i like", "i hate", "don't use", "always use",
            "i want", "never", "my favorite", "i usually",
        ],
        "fact": [
            "i am", "i'm a", "i work", "my name", "i live",
            "my project", "i'm building", "i use", "my stack",
        ],
        "skill": [
            "i know", "i'm learning", "i'm new to", "i'm experienced",
            "beginner", "advanced", "expert in",
        ],
        "project": [
            "working on", "building", "my app", "my game", "my project",
            "my repo", "my codebase",
        ],
    }

    async def store_memory(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        memory_type: str,
        key: str,
        value: str,
        confidence: int = 50,
        source_message_id: Optional[uuid.UUID] = None,
    ) -> UserMemory:
        """Store or update a memory for a user."""
        # Check if similar memory exists
        result = await db.execute(
            select(UserMemory).where(
                and_(
                    UserMemory.user_id == user_id,
                    UserMemory.key == key,
                    UserMemory.memory_type == memory_type,
                )
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            # Update existing memory, increase confidence
            existing.value = value
            existing.confidence = min(100, existing.confidence + 10)
            existing.access_count += 1
            existing.updated_at = datetime.utcnow()
            existing.last_accessed = datetime.utcnow()
            return existing

        memory = UserMemory(
            user_id=user_id,
            memory_type=memory_type,
            key=key,
            value=value,
            confidence=confidence,
            source_message_id=source_message_id,
        )
        db.add(memory)
        return memory

    async def retrieve_memories(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        query: str,
        memory_types: Optional[List[str]] = None,
        limit: int = 10,
    ) -> List[UserMemory]:
        """Retrieve relevant memories for a user based on query text."""
        conditions = [UserMemory.user_id == user_id]

        if memory_types:
            conditions.append(UserMemory.memory_type.in_(memory_types))

        # Get all memories for the user (for small-scale, this is fine)
        result = await db.execute(
            select(UserMemory)
            .where(and_(*conditions))
            .order_by(desc(UserMemory.confidence), desc(UserMemory.last_accessed))
            .limit(100)
        )
        all_memories = result.scalars().all()

        if not all_memories:
            return []

        # Score memories by relevance to query
        query_words = set(query.lower().split())
        scored = []
        for mem in all_memories:
            key_words = set(mem.key.lower().split())
            value_words = set(mem.value.lower().split())
            all_mem_words = key_words | value_words

            # Word overlap score
            overlap = len(query_words & all_mem_words)
            # Confidence boost
            conf_boost = mem.confidence / 100.0
            # Recency boost
            if mem.last_accessed:
                days_ago = (datetime.utcnow() - mem.last_accessed).days
                recency = max(0, 1.0 - days_ago / 30.0)
            else:
                recency = 0.5

            score = overlap * 2.0 + conf_boost + recency * 0.5
            if score > 0:
                scored.append((score, mem))

        scored.sort(key=lambda x: x[0], reverse=True)

        # Update access counts for retrieved memories
        memories = []
        for _, mem in scored[:limit]:
            mem.access_count += 1
            mem.last_accessed = datetime.utcnow()
            memories.append(mem)

        return memories

    async def extract_and_store(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        message: str,
        message_id: Optional[uuid.UUID] = None,
    ) -> List[UserMemory]:
        """Extract memory-worthy info from a user message and store it."""
        stored = []
        msg_lower = message.lower()

        for mem_type, triggers in self.MEMORY_TRIGGERS.items():
            for trigger in triggers:
                if trigger in msg_lower:
                    # Extract the relevant sentence
                    sentences = re.split(r'[.!?\n]', message)
                    for sentence in sentences:
                        if trigger in sentence.lower() and len(sentence.strip()) > 10:
                            key = self._make_key(sentence.strip())
                            mem = await self.store_memory(
                                db=db,
                                user_id=user_id,
                                memory_type=mem_type,
                                key=key,
                                value=sentence.strip(),
                                confidence=60,
                                source_message_id=message_id,
                            )
                            stored.append(mem)
                            break

        return stored

    async def learn_from_feedback(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        message_id: uuid.UUID,
        rating: int,
        conversation_id: uuid.UUID,
    ):
        """Learn from user feedback (like/dislike) to adjust future behavior."""
        # Get the message and its context
        result = await db.execute(
            select(Message).where(Message.id == message_id)
        )
        message = result.scalar_one_or_none()
        if not message:
            return

        # Get the user message that preceded this response
        result = await db.execute(
            select(Message)
            .where(
                and_(
                    Message.conversation_id == message.conversation_id,
                    Message.role == "user",
                    Message.created_at < message.created_at,
                )
            )
            .order_by(desc(Message.created_at))
            .limit(1)
        )
        user_msg = result.scalar_one_or_none()

        # Store learning signal
        reward = 1 if rating >= 2 else -1
        signal = LearningSignal(
            user_id=user_id,
            conversation_id=conversation_id,
            action_type="response",
            action_detail={
                "user_message": user_msg.content[:500] if user_msg else "",
                "ai_response_preview": message.content[:500],
                "rating": rating,
            },
            reward=reward,
            context_hash=hashlib.sha256(
                (user_msg.content[:200] if user_msg else "").encode()
            ).hexdigest()[:16],
        )
        db.add(signal)

        # If disliked, store a correction memory
        if rating < 2 and user_msg:
            await self.store_memory(
                db=db,
                user_id=user_id,
                memory_type="correction",
                key=self._make_key(user_msg.content[:100]),
                value=f"User disliked response to: {user_msg.content[:200]}. Avoid similar approach.",
                confidence=70,
                source_message_id=message_id,
            )

    async def get_user_profile(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
    ) -> Dict[str, Any]:
        """Build a comprehensive user profile from memories."""
        result = await db.execute(
            select(UserMemory)
            .where(UserMemory.user_id == user_id)
            .order_by(desc(UserMemory.confidence))
        )
        memories = result.scalars().all()

        profile: Dict[str, List[str]] = {}
        for mem in memories:
            profile.setdefault(mem.memory_type, []).append(
                f"{mem.key}: {mem.value}" if mem.key != mem.value else mem.value
            )

        # Get interaction stats
        result = await db.execute(
            select(func.count(Conversation.id))
            .where(Conversation.user_id == user_id)
        )
        conv_count = result.scalar() or 0

        result = await db.execute(
            select(func.count(Message.id))
            .join(Conversation, Message.conversation_id == Conversation.id)
            .where(
                and_(
                    Conversation.user_id == user_id,
                    Message.role == "user",
                )
            )
        )
        msg_count = result.scalar() or 0

        # Get feedback stats
        result = await db.execute(
            select(
                func.count(Feedback.id),
                func.avg(Feedback.rating),
            ).where(Feedback.user_id == user_id)
        )
        row = result.one()
        feedback_count = row[0] or 0
        avg_rating = round(float(row[1] or 0), 2)

        return {
            "memories": profile,
            "stats": {
                "conversations": conv_count,
                "messages_sent": msg_count,
                "feedbacks_given": feedback_count,
                "avg_satisfaction": avg_rating,
            },
        }

    async def get_recent_context(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        limit: int = 5,
    ) -> List[Dict[str, str]]:
        """Get recent conversation summaries for context continuity."""
        result = await db.execute(
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .order_by(desc(Conversation.updated_at))
            .limit(limit)
        )
        conversations = result.scalars().all()

        summaries = []
        for conv in conversations:
            # Get last few messages
            result = await db.execute(
                select(Message)
                .where(Message.conversation_id == conv.id)
                .order_by(desc(Message.created_at))
                .limit(4)
            )
            msgs = result.scalars().all()
            msgs.reverse()

            summary = {
                "title": conv.title,
                "platform": conv.platform,
                "when": conv.updated_at.isoformat() if conv.updated_at else "",
                "messages": [
                    f"{m.role}: {m.content[:150]}" for m in msgs
                ],
            }
            summaries.append(summary)

        return summaries

    def _make_key(self, text: str) -> str:
        """Create a short key from text."""
        # Take first 8 meaningful words
        words = re.findall(r'\b\w+\b', text.lower())
        words = [w for w in words if len(w) > 2 and w not in {
            "the", "and", "for", "that", "this", "with", "from",
            "are", "was", "were", "been", "have", "has", "had",
        }]
        return " ".join(words[:8])

    async def build_memory_context(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        current_message: str,
    ) -> str:
        """Build a memory context string to inject into the system prompt."""
        parts = []

        # 1. Relevant memories
        memories = await self.retrieve_memories(db, user_id, current_message, limit=8)
        if memories:
            mem_lines = []
            for m in memories:
                mem_lines.append(f"  [{m.memory_type}] {m.value}")
            parts.append("**Known about this user:**\n" + "\n".join(mem_lines))

        # 2. User profile summary
        profile = await self.get_user_profile(db, user_id)
        stats = profile.get("stats", {})
        if stats.get("conversations", 0) > 0:
            parts.append(
                f"**User stats:** {stats['conversations']} conversations, "
                f"{stats['messages_sent']} messages, "
                f"satisfaction: {stats['avg_satisfaction']}/2"
            )

        # 3. Recent conversations for continuity
        recent = await self.get_recent_context(db, user_id, limit=3)
        if recent:
            recent_lines = []
            for r in recent:
                recent_lines.append(f"  - {r['title']} ({r['when'][:10]})")
            parts.append("**Recent conversations:**\n" + "\n".join(recent_lines))

        # 4. Corrections to avoid
        corrections = await self.retrieve_memories(
            db, user_id, current_message, memory_types=["correction"], limit=3
        )
        if corrections:
            corr_lines = [f"  - {c.value}" for c in corrections]
            parts.append("**Past corrections (avoid repeating):**\n" + "\n".join(corr_lines))

        if not parts:
            return ""

        return "\n\n".join(parts)

    async def auto_store_learning(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        conversation_id: uuid.UUID,
        message_content: str,
        assistant_response: str,
        tools_used: List[str],
    ) -> Optional["KnowledgeEntry"]:
        """Auto-detect if the AI produced novel knowledge worth storing.

        Triggers when the response contains:
        - Code blocks (solution patterns)
        - Error fixes (debugging knowledge)
        - Tool configurations
        - Factual discoveries from web search

        Returns the created KnowledgeEntry if stored, None otherwise.
        """
        # Check if response is worth storing
        has_code = "```" in assistant_response
        has_length_and_tools = len(assistant_response) > 500 and len(tools_used) > 0
        has_fix_pattern = any(
            p in assistant_response.lower()
            for p in ("fixed", "the issue was", "solution:")
        )

        if not (has_code or has_length_and_tools or has_fix_pattern):
            return None

        # Generate title
        title = message_content[:80].strip()

        # Detect difficulty
        if len(tools_used) > 3 or len(assistant_response) > 2000:
            difficulty = "hard"
        elif len(tools_used) > 0 or len(assistant_response) > 500:
            difficulty = "medium"
        else:
            difficulty = "easy"

        # Detect emotion
        msg_lower = message_content.lower()
        if any(w in msg_lower for w in ("error", "not working", "broken", "help")):
            emotion = "frustrated"
        elif any(w in msg_lower for w in ("how", "why", "what")):
            emotion = "curious"
        elif any(w in msg_lower for w in ("!", "awesome", "great", "thanks")):
            emotion = "excited"
        else:
            emotion = "neutral"

        # Build content
        metadata = {
            "tools_used": tools_used,
            "topic": title[:50],
            "difficulty": difficulty,
            "emotion": emotion,
            "timestamp": datetime.utcnow().isoformat(),
        }
        content = (
            f"**Question:** {message_content}\n\n"
            f"**Answer:** {assistant_response[:3000]}\n\n"
            f"**Metadata:** {json.dumps(metadata)}"
        )

        # Create KnowledgeEntry
        from db.models import KnowledgeEntry

        entry = KnowledgeEntry(
            user_id=user_id,
            title=title,
            content=content,
            source_type="auto-learned",
            difficulty=difficulty,
            emotion=emotion,
            tools_used=tools_used,
            auto_generated=True,
            conversation_id=conversation_id,
        )
        db.add(entry)

        # Also store a UserMemory entry for quick retrieval
        await self.store_memory(
            db=db,
            user_id=user_id,
            memory_type="fact",
            key=self._make_key(message_content),
            value=f"Solved: {message_content[:200]}",
            confidence=75,
        )

        return entry


# Singleton
memory_system = MemorySystem()
