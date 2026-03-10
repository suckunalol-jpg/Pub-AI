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
    effort: Optional[str] = "high"  # low | medium | high | max


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

                # Accumulate code content when in coding phase (for live preview)
                if in_code_block:
                    # Detect language from first line after opening fence
                    if not code_language and code_buffer == "" and token.strip() and "```" not in token:
                        stripped = token.strip()
                        if stripped.isalpha() and len(stripped) < 20:
                            code_language = stripped
                    code_buffer += token.replace("```", "")

                # ALWAYS emit token events so content appears in the final message
                if token:
                    yield _sse_event("token", {"content": token})

            # Emit any remaining code buffer as a code event (for live preview)
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


# ---------- Agentic Streaming (Claude Code-style tool calling) ----------

MAX_AGENT_ITERATIONS = 25


@router.post("/agent-stream")
async def agent_stream_message(
    req: ChatRequest,
    request: Request,
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    """SSE streaming endpoint with agentic tool-calling loop.

    Like Claude Code: the AI can call any registered tool, observe results,
    and keep iterating until the task is complete.

    Emits events:
      - status:      {phase, conversation_id}
      - token:       {content}
      - tool_call:   {tool, params, iteration}
      - tool_result: {tool, success, output, iteration}
      - code:        {language, content}
      - done:        {message_id, model, conversation_id, iterations, tools_used}
      - error:       {detail}
    """
    import re as _re
    import time

    from agents.system_prompts import CHAT_AGENT_SYSTEM_PROMPT
    from agents.tools import execute_tool, tools_prompt

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

    # --- Brain context ---
    brain_ctx = await brain.build_context(db, user.id, req.message)
    memory_ctx = brain_ctx["memory_context"]
    adaptive = brain_ctx["adaptive_params"]

    # Build message history
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.created_at)
    )
    history = result.scalars().all()

    # Build system prompt with tools
    system_prompt = CHAT_AGENT_SYSTEM_PROMPT + "\n\n" + tools_prompt()
    if memory_ctx:
        system_prompt += f"\n\n--- USER MEMORY ---\n{memory_ctx}"
    if adaptive.get("verbosity") == "concise":
        system_prompt += "\n\nThis user prefers concise responses. Keep it short."
    elif adaptive.get("verbosity") == "verbose":
        system_prompt += "\n\nThis user prefers detailed, thorough responses."

    # Apply effort level
    effort = (req.effort or "high").lower()
    effort_modifiers = {
        "low": "\n\n[EFFORT: LOW] Be concise and fast. Skip detailed explanations. Give direct answers. Minimal tool usage — only call tools when strictly necessary.",
        "medium": "\n\n[EFFORT: MEDIUM] Balance thoroughness with efficiency. Explain key points but skip obvious details. Use tools when they add clear value.",
        "high": "",  # Default behavior — no modifier needed
        "max": "\n\n[EFFORT: MAX] Apply maximum reasoning depth. Think step-by-step through every aspect. Be extremely thorough. Consider edge cases. Use multiple tools to verify results. Provide comprehensive explanations.",
    }
    system_prompt += effort_modifiers.get(effort, "")

    messages_for_ai = [{"role": "system", "content": system_prompt}]
    for msg in history:
        messages_for_ai.append({"role": msg.role, "content": msg.content})

    conv_id_str = str(conversation.id)

    async def agent_event_generator() -> AsyncGenerator[str, None]:
        """Agentic loop: Think → Call Tools → Observe → Repeat."""
        full_content = ""
        iteration = 0
        tools_used = 0
        start_time = time.perf_counter()

        yield _sse_event("status", {"phase": "thinking", "conversation_id": conv_id_str})

        try:
            while iteration < MAX_AGENT_ITERATIONS:
                iteration += 1

                if await request.is_disconnected():
                    break

                # --- Think: get AI response ---
                yield _sse_event("status", {"phase": "thinking"})

                ai_content = ""
                async for token in ai_provider.stream(
                    messages=messages_for_ai,
                    temperature=adaptive.get("temperature", 0.4),
                    max_tokens=adaptive.get("max_tokens", 4096),
                ):
                    if await request.is_disconnected():
                        return
                    ai_content += token
                    yield _sse_event("token", {"content": token})

                    # Detect code blocks for live preview
                    if "```" in token:
                        yield _sse_event("status", {"phase": "coding"})

                # Add AI response to message history
                messages_for_ai.append({"role": "assistant", "content": ai_content})
                full_content += ai_content

                # --- Check for tool calls ---
                tool_matches = list(_re.finditer(
                    r"```tool\s*\n(.*?)\n```", ai_content, _re.DOTALL
                ))

                if not tool_matches:
                    # No tools called — AI is done, this is the final answer
                    break

                # --- Execute tools ---
                yield _sse_event("status", {"phase": "calling_tool"})

                tool_results_text = []
                for match in tool_matches:
                    try:
                        call = json.loads(match.group(1))
                    except json.JSONDecodeError:
                        tool_results_text.append("Error: Invalid JSON in tool call")
                        continue

                    tool_name = call.get("tool", "unknown")
                    tool_params = call.get("params", {})
                    tools_used += 1

                    # Emit tool_call event to frontend
                    yield _sse_event("tool_call", {
                        "tool": tool_name,
                        "params": tool_params,
                        "iteration": iteration,
                    })

                    # Map tool names to phase indicators
                    phase_map = {
                        "web_search": "searching_web",
                        "web_fetch": "searching_web",
                        "read_file": "reading_file",
                        "write_file": "writing_file",
                        "edit_file": "writing_file",
                        "multi_edit": "writing_file",
                        "execute_code": "executing",
                        "bash": "executing",
                        "spawn_agent": "spawning_agent",
                        "grep_search": "searching_knowledge",
                        "codebase_search": "searching_knowledge",
                    }
                    tool_phase = phase_map.get(tool_name, "calling_tool")
                    yield _sse_event("status", {"phase": tool_phase})

                    # Execute the tool
                    try:
                        result = await execute_tool(tool_name, tool_params)
                        output = result.output
                        success = result.success
                    except Exception as e:
                        output = f"Tool error: {e}"
                        success = False

                    # Truncate very long outputs for the SSE event
                    event_output = output[:2000] + "..." if len(output) > 2000 else output
                    yield _sse_event("tool_result", {
                        "tool": tool_name,
                        "success": success,
                        "output": event_output,
                        "iteration": iteration,
                    })

                    tool_results_text.append(
                        f"**{tool_name}** ({'OK' if success else 'FAILED'}):\n{output}"
                    )

                # Feed tool results back to the AI
                observation = "Tool results:\n\n" + "\n\n---\n\n".join(tool_results_text)
                messages_for_ai.append({"role": "user", "content": observation})

                # Emit a separator token so frontend knows a new iteration is starting
                separator = "\n\n"
                full_content += separator
                yield _sse_event("token", {"content": separator})

            # --- Done ---
            latency_ms = int((time.perf_counter() - start_time) * 1000)

            # Save the full assistant response to DB
            assistant_msg = Message(
                conversation_id=conversation.id,
                role="assistant",
                content=full_content,
                model_used="pub-ai",
                tokens_in=0,
                tokens_out=len(full_content),
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
                "iterations": iteration,
                "tools_used": tools_used,
            })

        except Exception as e:
            yield _sse_event("error", {"detail": str(e)})

    return StreamingResponse(
        agent_event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
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
