"""Memory API — view, manage, and debug the AI's per-user learning memory."""

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from agents.brain import brain
from agents.memory import memory_system
from api.auth import get_current_user_from_token
from db.database import get_db
from db.models import User, UserMemory

router = APIRouter(prefix="/api/memory", tags=["memory"])


class MemoryCreate(BaseModel):
    memory_type: str  # preference/fact/skill/pattern/correction/project
    key: str
    value: str


class MemoryOut(BaseModel):
    id: uuid.UUID
    memory_type: str
    key: str
    value: str
    confidence: int
    access_count: int

    model_config = {"from_attributes": True}


@router.get("", response_model=list[MemoryOut])
async def list_memories(
    memory_type: Optional[str] = None,
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    """List all memories the AI has stored about you."""
    query = select(UserMemory).where(UserMemory.user_id == user.id)
    if memory_type:
        query = query.where(UserMemory.memory_type == memory_type)
    query = query.order_by(UserMemory.confidence.desc())

    result = await db.execute(query)
    return result.scalars().all()


@router.post("", response_model=MemoryOut)
async def add_memory(
    req: MemoryCreate,
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    """Manually add a memory for the AI to remember about you."""
    mem = await memory_system.store_memory(
        db=db,
        user_id=user.id,
        memory_type=req.memory_type,
        key=req.key,
        value=req.value,
        confidence=80,
    )
    await db.flush()
    return mem


@router.delete("/{memory_id}")
async def delete_memory(
    memory_id: uuid.UUID,
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    """Delete a specific memory."""
    result = await db.execute(
        select(UserMemory).where(
            UserMemory.id == memory_id,
            UserMemory.user_id == user.id,
        )
    )
    mem = result.scalar_one_or_none()
    if not mem:
        raise HTTPException(status_code=404, detail="Memory not found")
    await db.delete(mem)
    return {"detail": "Memory deleted"}


@router.delete("")
async def clear_all_memories(
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    """Clear all AI memories about you."""
    await db.execute(
        delete(UserMemory).where(UserMemory.user_id == user.id)
    )
    brain.invalidate_user_cache(user.id)
    return {"detail": "All memories cleared"}


@router.get("/profile")
async def get_profile(
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    """Get the full user profile the AI has built about you."""
    profile = await memory_system.get_user_profile(db, user.id)
    return profile


@router.get("/search")
async def search_memories(
    query: str,
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    """Search the AI's memories about you."""
    memories = await memory_system.retrieve_memories(db, user.id, query, limit=10)
    return [
        {
            "id": str(m.id),
            "type": m.memory_type,
            "key": m.key,
            "value": m.value,
            "confidence": m.confidence,
        }
        for m in memories
    ]


@router.get("/brain")
async def get_brain_context(
    message: str = "hello",
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    """Debug endpoint: see what the Brain computes for a given message."""
    ctx = await brain.build_context(db, user.id, message)
    return ctx
