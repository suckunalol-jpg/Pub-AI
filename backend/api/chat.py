import time
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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

    # Build message history for AI
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.created_at)
    )
    history = result.scalars().all()

    messages = [{"role": "system", "content": GENERAL_SYSTEM_PROMPT}]
    for msg in history:
        messages.append({"role": msg.role, "content": msg.content})

    # Call AI
    ai_resp = await ai_provider.chat(messages=messages, model=req.model)

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
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Message not found")

    feedback = Feedback(
        message_id=req.message_id,
        user_id=user.id,
        rating=req.rating,
        comment=req.comment,
    )
    db.add(feedback)
    return {"detail": "Feedback submitted"}
