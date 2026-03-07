"""Chat API — wired with Brain (intent classification + RL) and Memory (per-user learning).

Every interaction:
1. Brain classifies intent and loads adaptive params
2. Memory retrieves relevant past context for this user
3. Response is generated with full user context
4. New memories are extracted and stored
5. Feedback updates the learning system
"""

import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agents.brain import brain
from agents.memory import memory_system
from ai.prompts import GENERAL_SYSTEM_PROMPT
from ai.provider import ai_provider
from api.auth import get_current_user_from_token
from db.database import get_db
from db.models import Conversation, Feedback, Message, User

router = APIRouter(prefix="/api/chat", tags=["chat"])


# ---------- Schemas ----------

class ChatRequest(BaseModel):
    message: str
    conversation_id: Optional[uuid.UUID] = None
    model: Optional[str] = None


class ChatResponse(BaseModel):
    conversation_id: uuid.UUID
    message_id: uuid.UUID
    content: str
    model_used: str
    tokens_in: int
    tokens_out: int
    latency_ms: int
    intent: Optional[dict] = None


class ConversationSummary(BaseModel):
    id: uuid.UUID
    title: str
    platform: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MessageOut(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    model_used: Optional[str]
    tokens_in: Optional[int]
    tokens_out: Optional[int]
    latency_ms: Optional[int]
    created_at: datetime

    model_config = {"from_attributes": True}


class FeedbackRequest(BaseModel):
    message_id: uuid.UUID
    rating: int  # 1=dislike, 2=like
    comment: Optional[str] = None


# ---------- Routes ----------

@router.post("", response_model=ChatResponse)
async def send_message(
    req: ChatRequest,
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    # Get or create conversation
    if req.conversation_id:
        result = await db.execute(
            select(Conversation).where(
                Conversation.id == req.conversation_id,
                Conversation.user_id == user.id,
            )
        )
        conversation = result.scalar_one_or_none()
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")
    else:
        conversation = Conversation(
            user_id=user.id,
            title=req.message[:80] if req.message else "New Chat",
            platform="web",
        )
        db.add(conversation)
        await db.flush()

    # Log user message
    user_msg = Message(
        conversation_id=conversation.id,
        role="user",
        content=req.message,
    )
    db.add(user_msg)
    await db.flush()

    # --- Brain: classify intent + retrieve memory + get adaptive params ---
    brain_ctx = await brain.build_context(db, user.id, req.message)
    intent_info = brain_ctx["intent"]
    memory_ctx = brain_ctx["memory_context"]
    adaptive = brain_ctx["adaptive_params"]

    # Build message history
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.created_at)
    )
    history = result.scalars().all()

    # Build system prompt with user memory context
    system_prompt = GENERAL_SYSTEM_PROMPT
    if memory_ctx:
        system_prompt += f"\n\n--- USER MEMORY ---\n{memory_ctx}"
    if adaptive.get("verbosity") == "concise":
        system_prompt += "\n\nThis user prefers concise responses. Keep it short."
    elif adaptive.get("verbosity") == "verbose":
        system_prompt += "\n\nThis user prefers detailed, thorough responses."

    messages = [{"role": "system", "content": system_prompt}]
    for msg in history:
        messages.append({"role": msg.role, "content": msg.content})

    # Call AI with adaptive params
    ai_resp = await ai_provider.chat(
        messages=messages,
        model=req.model,
        temperature=adaptive.get("temperature", 0.7),
        max_tokens=adaptive.get("max_tokens", 4096),
    )

    # Log assistant message
    assistant_msg = Message(
        conversation_id=conversation.id,
        role="assistant",
        content=ai_resp.content,
        model_used=ai_resp.model,
        tokens_in=ai_resp.tokens_in,
        tokens_out=ai_resp.tokens_out,
        latency_ms=ai_resp.latency_ms,
    )
    db.add(assistant_msg)

    # Update conversation timestamp
    conversation.updated_at = datetime.utcnow()
    await db.flush()

    return ChatResponse(
        conversation_id=conversation.id,
        message_id=assistant_msg.id,
        content=ai_resp.content,
        model_used=ai_resp.model,
        tokens_in=ai_resp.tokens_in,
        tokens_out=ai_resp.tokens_out,
        latency_ms=ai_resp.latency_ms,
        intent=intent_info,
    )


@router.get("/conversations", response_model=list[ConversationSummary])
async def list_conversations(
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Conversation)
        .where(Conversation.user_id == user.id)
        .order_by(Conversation.updated_at.desc())
    )
    return result.scalars().all()


@router.get("/conversations/{conversation_id}", response_model=list[MessageOut])
async def get_conversation_history(
    conversation_id: uuid.UUID,
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    # Verify ownership
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user.id,
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Conversation not found")

    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at)
    )
    return result.scalars().all()


@router.post("/feedback")
async def submit_feedback(
    req: FeedbackRequest,
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    # Verify message exists
    result = await db.execute(select(Message).where(Message.id == req.message_id))
    msg = result.scalar_one_or_none()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")

    feedback = Feedback(
        message_id=req.message_id,
        user_id=user.id,
        rating=req.rating,
        comment=req.comment,
    )
    db.add(feedback)

    # --- Learn from feedback ---
    await memory_system.learn_from_feedback(
        db=db,
        user_id=user.id,
        message_id=req.message_id,
        rating=req.rating,
        conversation_id=msg.conversation_id,
    )

    # Invalidate brain cache so it reloads priors
    brain.invalidate_user_cache(user.id)

    return {"detail": "Feedback submitted and learned from"}
