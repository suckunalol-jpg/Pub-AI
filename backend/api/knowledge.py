import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import get_current_user_from_token
from db.database import get_db
from db.models import KnowledgeEntry, User
from knowledge.ingest import ingest_document
from knowledge.vectordb import vector_store

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


# ---------- Schemas ----------

class IngestRequest(BaseModel):
    title: str
    content: str
    source_type: str = "manual"  # qa/doc/code/manual


class QueryRequest(BaseModel):
    query: str
    top_k: int = 5


class KnowledgeEntryOut(BaseModel):
    id: uuid.UUID
    title: str
    content: str
    source_type: str

    model_config = {"from_attributes": True}


class QueryResult(BaseModel):
    entries: list[dict]


# ---------- Routes ----------

@router.post("/ingest", response_model=KnowledgeEntryOut)
async def ingest(
    req: IngestRequest,
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    embedding_id = await ingest_document(
        title=req.title,
        content=req.content,
        source_type=req.source_type,
        user_id=str(user.id),
    )

    entry = KnowledgeEntry(
        user_id=user.id,
        title=req.title,
        content=req.content,
        source_type=req.source_type,
        embedding_id=embedding_id,
    )
    db.add(entry)
    await db.flush()
    return entry


@router.post("/query", response_model=QueryResult)
async def query_knowledge(
    req: QueryRequest,
    user: User = Depends(get_current_user_from_token),
):
    results = vector_store.query(query=req.query, top_k=req.top_k, user_id=str(user.id))
    return QueryResult(entries=results)


@router.get("/entries", response_model=list[KnowledgeEntryOut])
async def list_entries(
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(KnowledgeEntry)
        .where(KnowledgeEntry.user_id == user.id)
        .order_by(KnowledgeEntry.created_at.desc())
    )
    return result.scalars().all()
