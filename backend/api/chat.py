"""Chat API — wired with Brain (intent classification + RL) and Memory (per-user learning).

Every interaction:
1. Brain classifies intent and loads adaptive params
2. Memory retrieves relevant past context for this user
3. Response is generated with full user context
4. New memories are extracted and stored
5. Feedback updates the learning system
"""

import json
import uuid
from datetime import datetime
from typing import AsyncGenerator, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
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


# ---------- SSE Streaming ----------

def _sse_event(event: str, data: dict) -> str:
    """Format a single SSE event line."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _detect_phase(token: str, buffer: str, in_code_block: bool) -> tuple[str | None, bool]:
    """Detect phase transitions by inspecting accumulated content.

    Returns (new_phase_or_None, updated_in_code_block).
    """
    combined = buffer + token

    # Check for code fence toggle (``` marks start/end of code block)
    fence_count = token.count("```")
    toggled = in_code_block
    for _ in range(fence_count):
        toggled = not toggled

    if toggled != in_code_block:
        phase = "coding" if toggled else "reviewing"
        return phase, toggled

    # Detect tool-call / execution patterns in the token stream
    lower_token = token.lower()
    lower_buffer = buffer.lower()
    
    # Keyword detection for phases
    if "spawning agent" in lower_token or "starting sub-agent" in lower_token:
        return "spawning_agent", toggled
        
    if "tool_call" in lower_token or "using tool" in lower_token:
        return "calling_tool", toggled

    if "executing" in lower_token or "running code" in lower_token or "$ " in lower_token:
        return "executing", toggled

    if "searching" in lower_token or "looking up" in lower_token or "google" in lower_token:
        return "searching_web", toggled
        
    if "knowledge" in lower_token or "memory" in lower_token or "retrieving" in lower_token:
        return "searching_knowledge", toggled
        
    if "reading file" in lower_token or "viewing file" in lower_token:
        return "reading_file", toggled
        
    if "writing file" in lower_token or "creating file" in lower_token:
        return "writing_file", toggled
        
    if "bug" in lower_token or "debugging" in lower_token or "fixing" in lower_token:
        return "debugging", toggled
        
    if "plan" in lower_token or "approach" in lower_token or "step 1" in lower_token:
        return "planning", toggled
        
    if "analyzing" in lower_token or "understanding" in lower_token:
        return "analyzing", toggled
        
    if "summarizing" in lower_token or "in summary" in lower_token:
        return "summarizing", toggled
        
    if "formatting" in lower_token:
        return "formatting", toggled

    # If we are just writing normal text and haven't triggered anything else recently
    if not toggled and len(buffer) > 50 and "thinking" not in lower_buffer[-20:]:
        # Occasionally switch to writing if we're just outputting prose
        if " " in token and len(buffer) % 200 < 10:
            return "writing", toggled

    return None, toggled


@router.post("/stream")
async def stream_message(
    req: ChatRequest,
    request: Request,
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    """SSE streaming endpoint for real-time chat responses.

    Emits events:
      - status: {phase: thinking|coding|executing|searching}
      - token:  {content: str}
      - code:   {language: str, content: str}
      - done:   {message_id: str, model: str}
      - error:  {detail: str}
    """

    # --- Resolve / create conversation ---
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

    # --- Brain context (same as non-streaming) ---
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

    # Capture conversation_id to send in the first event
    conv_id_str = str(conversation.id)

    async def event_generator() -> AsyncGenerator[str, None]:
        """Generates SSE events from the AI token stream."""
        import time

        full_content = ""
        current_phase = "thinking"
        in_code_block = False
        code_buffer = ""
        code_language = ""
        start_time = time.perf_counter()
        token_count = 0

        # Initial status + conversation_id
        yield _sse_event("status", {"phase": "thinking", "conversation_id": conv_id_str})

        try:
            async for token in ai_provider.stream(
                messages=messages,
                temperature=adaptive.get("temperature", 0.7),
                max_tokens=adaptive.get("max_tokens", 4096),
            ):
                # Check if client disconnected
                if await request.is_disconnected():
                    break

                full_content += token
                token_count += 1

                # Phase detection
                new_phase, in_code_block = _detect_phase(token, full_content, in_code_block)
                if new_phase and new_phase != current_phase:
                    # If leaving coding phase, emit the accumulated code block
                    if current_phase == "coding" and code_buffer.strip():
                        yield _sse_event("code", {
                            "language": code_language or "text",
                            "content": code_buffer.strip(),
                        })
                        code_buffer = ""
                        code_language = ""

                    current_phase = new_phase
                    yield _sse_event("status", {"phase": current_phase})

                # Accumulate code content when in coding phase
                if in_code_block:
                    # Detect language from first line after opening fence
                    if not code_language and code_buffer == "" and token.strip() and "```" not in token:
                        # The first token after ``` is often the language identifier
                        stripped = token.strip()
                        if stripped.isalpha() and len(stripped) < 20:
                            code_language = stripped
                        else:
                            code_buffer += token
                    else:
                        # Filter out the fence markers themselves
                        cleaned = token.replace("```", "")
                        code_buffer += cleaned
                else:
                    # Emit content tokens (filter out fence markers)
                    emit_token = token.replace("```", "")
                    if emit_token:
                        yield _sse_event("token", {"content": emit_token})

            # Emit any remaining code buffer
            if code_buffer.strip():
                yield _sse_event("code", {
                    "language": code_language or "text",
                    "content": code_buffer.strip(),
                })

            latency_ms = int((time.perf_counter() - start_time) * 1000)

            # Save assistant message to DB
            assistant_msg = Message(
                conversation_id=conversation.id,
                role="assistant",
                content=full_content,
                model_used="pub-ai",
                tokens_in=0,  # Not available from streaming
                tokens_out=token_count,
                latency_ms=latency_ms,
            )
            db.add(assistant_msg)
            conversation.updated_at = datetime.utcnow()
            await db.flush()
            await db.commit()

            yield _sse_event("done", {
                "message_id": str(assistant_msg.id),
                "model": "pub-ai",
                "conversation_id": conv_id_str,
                "latency_ms": latency_ms,
            })

        except Exception as e:
            yield _sse_event("error", {"detail": str(e)})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
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
