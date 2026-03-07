"""Pub AI Brain — Bayesian intent classification + reinforcement learning
+ semantic memory retrieval.

Combines:
1. Bayesian intent classifier — predicts what the user wants
2. Reinforcement learning signals — tracks what works for each user
3. Semantic memory — retrieves relevant past context
4. Adaptive response strategy — adjusts behavior based on learned preferences
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import uuid
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select, func, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from agents.memory import memory_system
from db.models import Feedback, IntentLog, LearningSignal, Message

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Intent categories
# ---------------------------------------------------------------------------

INTENTS = {
    "code_write": {
        "description": "User wants code written from scratch",
        "keywords": ["write", "create", "build", "make", "implement", "code", "generate", "scaffold"],
        "agent_type": "coder",
    },
    "code_debug": {
        "description": "User needs help fixing a bug or error",
        "keywords": ["fix", "bug", "error", "broken", "crash", "failing", "debug", "issue", "wrong"],
        "agent_type": "coder",
    },
    "code_review": {
        "description": "User wants code reviewed or improved",
        "keywords": ["review", "improve", "optimize", "refactor", "clean", "better", "performance"],
        "agent_type": "reviewer",
    },
    "code_explain": {
        "description": "User wants code or concepts explained",
        "keywords": ["explain", "how does", "what is", "why", "understand", "help me understand"],
        "agent_type": "researcher",
    },
    "research": {
        "description": "User needs information or research",
        "keywords": ["search", "find", "look up", "research", "what's the best", "compare", "docs"],
        "agent_type": "researcher",
    },
    "execute": {
        "description": "User wants code run or commands executed",
        "keywords": ["run", "execute", "test", "try", "deploy", "install", "build"],
        "agent_type": "executor",
    },
    "roblox": {
        "description": "Roblox game development related",
        "keywords": ["roblox", "luau", "lua", "game", "studio", "remote", "datastore", "gui",
                     "localscript", "serverscript", "workspace"],
        "agent_type": "roblox",
    },
    "plan": {
        "description": "User wants a project planned or architected",
        "keywords": ["plan", "architect", "design", "structure", "organize", "roadmap", "breakdown"],
        "agent_type": "planner",
    },
    "scan": {
        "description": "User wants scripts or code scanned for issues",
        "keywords": ["scan", "analyze", "audit", "security", "vulnerability", "exploit", "check"],
        "agent_type": "reviewer",
    },
    "chat": {
        "description": "General conversation or question",
        "keywords": ["hi", "hello", "hey", "thanks", "question", "?"],
        "agent_type": None,
    },
}


class Brain:
    """Bayesian intent classifier with reinforcement learning."""

    def __init__(self):
        # Prior probabilities per intent (starts uniform)
        self._priors: Dict[str, float] = {
            intent: 1.0 / len(INTENTS) for intent in INTENTS
        }
        # Per-user learned priors (from DB)
        self._user_priors: Dict[str, Dict[str, float]] = {}

    async def classify_intent(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        message: str,
    ) -> Dict[str, Any]:
        """Classify user intent using Bayesian inference.

        Returns:
            {
                "intent": "code_write",
                "confidence": 0.85,
                "agent_type": "coder",
                "all_scores": {...},
            }
        """
        msg_lower = message.lower()
        words = set(re.findall(r'\b\w+\b', msg_lower))

        # Load user-specific priors from past interactions
        user_priors = await self._load_user_priors(db, user_id)

        scores: Dict[str, float] = {}
        for intent_name, intent_info in INTENTS.items():
            # Prior probability (learned or default)
            prior = user_priors.get(intent_name, self._priors[intent_name])

            # Likelihood: how many keywords match
            keywords = set(intent_info["keywords"])
            matches = len(words & keywords)
            total_keywords = len(keywords)

            # P(message | intent) ∝ matches / total_keywords + smoothing
            likelihood = (matches + 0.1) / (total_keywords + 0.1)

            # Bayesian: P(intent | message) ∝ P(message | intent) * P(intent)
            posterior = likelihood * prior
            scores[intent_name] = posterior

        # Normalize
        total = sum(scores.values())
        if total > 0:
            scores = {k: v / total for k, v in scores.items()}

        # Get top intent
        top_intent = max(scores, key=scores.get)
        confidence = scores[top_intent]

        # Log the classification
        intent_log = IntentLog(
            user_id=user_id,
            message_content=message[:500],
            predicted_intent=top_intent,
            confidence=int(confidence * 100),
            features={"word_count": len(words), "scores": {k: round(v, 4) for k, v in scores.items()}},
        )
        db.add(intent_log)

        return {
            "intent": top_intent,
            "confidence": round(confidence, 3),
            "agent_type": INTENTS[top_intent].get("agent_type"),
            "description": INTENTS[top_intent]["description"],
            "all_scores": {k: round(v, 4) for k, v in sorted(scores.items(), key=lambda x: -x[1])},
        }

    async def _load_user_priors(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
    ) -> Dict[str, float]:
        """Load learned priors for a specific user from their intent history."""
        user_key = str(user_id)
        if user_key in self._user_priors:
            return self._user_priors[user_key]

        # Count past intents for this user
        result = await db.execute(
            select(IntentLog.predicted_intent, func.count(IntentLog.id))
            .where(IntentLog.user_id == user_id)
            .group_by(IntentLog.predicted_intent)
        )
        rows = result.all()

        if not rows:
            return self._priors

        total = sum(count for _, count in rows)
        priors = {}
        for intent_name, count in rows:
            # Laplace smoothing
            priors[intent_name] = (count + 1) / (total + len(INTENTS))

        # Fill missing intents
        for intent in INTENTS:
            if intent not in priors:
                priors[intent] = 1 / (total + len(INTENTS))

        self._user_priors[user_key] = priors
        return priors

    async def get_adaptive_params(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
    ) -> Dict[str, Any]:
        """Get learned response parameters for a user based on RL signals.

        Uses past feedback to determine:
        - Preferred response length (verbose vs concise)
        - Code style preferences
        - Explanation depth
        - Temperature/creativity level
        """
        # Get recent learning signals
        result = await db.execute(
            select(LearningSignal)
            .where(LearningSignal.user_id == user_id)
            .order_by(desc(LearningSignal.created_at))
            .limit(50)
        )
        signals = result.scalars().all()

        if not signals:
            return {
                "style": "balanced",
                "verbosity": "medium",
                "temperature": 0.7,
                "max_tokens": 4096,
            }

        # Analyze positive vs negative signals
        positive = [s for s in signals if s.reward > 0]
        negative = [s for s in signals if s.reward < 0]

        pos_rate = len(positive) / len(signals) if signals else 0.5

        # Analyze response lengths of liked vs disliked
        liked_lengths = []
        disliked_lengths = []
        for s in signals:
            detail = s.action_detail or {}
            resp = detail.get("ai_response_preview", "")
            if s.reward > 0:
                liked_lengths.append(len(resp))
            else:
                disliked_lengths.append(len(resp))

        avg_liked_len = sum(liked_lengths) / len(liked_lengths) if liked_lengths else 300
        avg_disliked_len = sum(disliked_lengths) / len(disliked_lengths) if disliked_lengths else 300

        # Determine verbosity preference
        if avg_liked_len > 400 and (not disliked_lengths or avg_liked_len > avg_disliked_len):
            verbosity = "verbose"
            max_tokens = 6144
        elif avg_liked_len < 200:
            verbosity = "concise"
            max_tokens = 2048
        else:
            verbosity = "medium"
            max_tokens = 4096

        # Temperature: higher satisfaction → can be more creative
        temperature = 0.5 + pos_rate * 0.4  # 0.5-0.9 range

        return {
            "style": "technical" if pos_rate > 0.7 else "balanced",
            "verbosity": verbosity,
            "temperature": round(temperature, 2),
            "max_tokens": max_tokens,
            "satisfaction_rate": round(pos_rate, 2),
            "total_signals": len(signals),
        }

    async def build_context(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        message: str,
    ) -> Dict[str, Any]:
        """Build full context for a request: intent + memory + adaptive params.

        This is the main entry point — call this before every AI response.
        """
        # Run all three in parallel-ish (they all need db)
        intent = await self.classify_intent(db, user_id, message)
        memory_ctx = await memory_system.build_memory_context(db, user_id, message)
        params = await self.get_adaptive_params(db, user_id)

        # Extract and store any new memories from the message
        await memory_system.extract_and_store(db, user_id, message)

        return {
            "intent": intent,
            "memory_context": memory_ctx,
            "adaptive_params": params,
        }

    def invalidate_user_cache(self, user_id: uuid.UUID):
        """Clear cached priors for a user (after feedback)."""
        self._user_priors.pop(str(user_id), None)


# Singleton
brain = Brain()
