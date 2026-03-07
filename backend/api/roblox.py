from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ai.prompts import ROBLOX_SYSTEM_PROMPT
from ai.provider import ai_provider
from api.auth import get_user_from_api_key
from db.database import get_db
from db.models import Conversation, Message, User

router = APIRouter(prefix="/api/roblox", tags=["roblox"])


# ---------- Schemas ----------

class RobloxChatRequest(BaseModel):
    message: str
    context: Optional[dict] = None  # place_id, game_name, etc.
    conversation_id: Optional[str] = None


class RobloxScanRequest(BaseModel):
    script: str
    script_name: Optional[str] = "Unknown"


class RobloxDecompileRequest(BaseModel):
    bytecode: str


# ---------- Auth dependency ----------

async def get_roblox_user(
    x_api_key: str = Header(..., alias="X-API-Key"),
    db: AsyncSession = Depends(get_db),
) -> User:
    return await get_user_from_api_key(x_api_key, db)


# ---------- Routes ----------

@router.post("/chat")
async def roblox_chat(
    req: RobloxChatRequest,
    user: User = Depends(get_roblox_user),
    db: AsyncSession = Depends(get_db),
):
    # Get or create conversation
    conversation = None
    if req.conversation_id:
        from sqlalchemy import select
        result = await db.execute(
            select(Conversation).where(Conversation.id == req.conversation_id)
        )
        conversation = result.scalar_one_or_none()

    if not conversation:
        conversation = Conversation(
            user_id=user.id,
            title=f"Roblox: {req.message[:60]}",
            platform="roblox",
            metadata_=req.context or {},
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

    # Build context-aware prompt
    context_str = ""
    if req.context:
        context_str = f"\n\nRoblox Context: {req.context}"

    messages = [
        {"role": "system", "content": ROBLOX_SYSTEM_PROMPT + context_str},
        {"role": "user", "content": req.message},
    ]

    ai_resp = await ai_provider.chat(messages=messages)

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

    return {
        "response": ai_resp.content,
        "conversation_id": str(conversation.id),
        "model": ai_resp.model,
    }


@router.post("/scan")
async def scan_script(
    req: RobloxScanRequest,
    user: User = Depends(get_roblox_user),
    db: AsyncSession = Depends(get_db),
):
    prompt = f"""Analyze this Roblox Lua script for:
1. Security vulnerabilities (remote event abuse, client trust issues)
2. Performance issues (memory leaks, excessive loops, unanchored parts)
3. Code quality (naming, structure, patterns)
4. Potential exploits or malicious behavior

Script name: {req.script_name}

```lua
{req.script}
```

Provide a structured analysis with severity ratings."""

    messages = [
        {"role": "system", "content": ROBLOX_SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]

    ai_resp = await ai_provider.chat(messages=messages)

    # Log this interaction
    conv = Conversation(
        user_id=user.id,
        title=f"Scan: {req.script_name}",
        platform="roblox",
    )
    db.add(conv)
    await db.flush()
    db.add(Message(conversation_id=conv.id, role="user", content=prompt))
    db.add(Message(
        conversation_id=conv.id,
        role="assistant",
        content=ai_resp.content,
        model_used=ai_resp.model,
        tokens_in=ai_resp.tokens_in,
        tokens_out=ai_resp.tokens_out,
        latency_ms=ai_resp.latency_ms,
    ))

    return {"analysis": ai_resp.content, "model": ai_resp.model}


@router.post("/decompile")
async def decompile_script(
    req: RobloxDecompileRequest,
    user: User = Depends(get_roblox_user),
    db: AsyncSession = Depends(get_db),
):
    from roblox.bridge import analyze_bytecode

    result = analyze_bytecode(req.bytecode)
    return result


@router.get("/status")
async def roblox_status():
    return {"status": "online", "features": ["chat", "scan", "decompile"]}
