"""Agent API — spawn, manage, and monitor autonomous agents."""

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agents.orchestrator import orchestrator
from api.auth import get_current_user_from_token
from db.database import get_db
from db.models import AgentSession, User

router = APIRouter(prefix="/api/agents", tags=["agents"])


# ---------- Schemas ----------

class SpawnRequest(BaseModel):
    agent_type: str  # coder/researcher/reviewer/executor/planner/roblox
    task: str
    conversation_id: Optional[uuid.UUID] = None
    config: Optional[dict] = None


class AgentStatus(BaseModel):
    id: uuid.UUID
    agent_type: str
    agent_name: str
    status: str
    result: Optional[dict]

    model_config = {"from_attributes": True}


class AgentMessage(BaseModel):
    message: str


# ---------- Routes ----------

@router.post("/spawn", response_model=AgentStatus)
async def spawn_agent(
    req: SpawnRequest,
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    session = await orchestrator.spawn(
        db=db,
        agent_type=req.agent_type,
        task=req.task,
        conversation_id=req.conversation_id or uuid.uuid4(),
        config=req.config or {},
        user_id=user.id,
    )
    return session


@router.get("/list")
async def list_agents(
    user: User = Depends(get_current_user_from_token),
):
    """List all currently active agents with their state."""
    return orchestrator.list_agents()


@router.get("/{agent_id}", response_model=AgentStatus)
async def get_agent_status(
    agent_id: uuid.UUID,
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    # Check live agent first
    agent = orchestrator.get_agent(agent_id)
    if agent:
        return AgentStatus(
            id=agent.id,
            agent_type=agent.agent_type,
            agent_name=agent.name,
            status=agent.status,
            result=agent.result,
        )

    # Fall back to DB
    result = await db.execute(select(AgentSession).where(AgentSession.id == agent_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Agent not found")
    return session


@router.get("/{agent_id}/state")
async def get_agent_detailed_state(
    agent_id: uuid.UUID,
    user: User = Depends(get_current_user_from_token),
):
    """Get detailed agent state including tool history and iterations."""
    agent = orchestrator.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found or finished")
    return agent.get_state()


@router.post("/{agent_id}/message")
async def message_agent(
    agent_id: uuid.UUID,
    req: AgentMessage,
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    response = await orchestrator.send_message(agent_id, req.message)
    return {"response": response}


@router.delete("/{agent_id}")
async def stop_agent(
    agent_id: uuid.UUID,
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    await orchestrator.stop(agent_id, db)
    return {"detail": "Agent stopped"}
