import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from agents.team_manager import team_manager
from api.auth import get_current_user_from_token
from db.database import get_db
from db.models import User

router = APIRouter(prefix="/api/teams", tags=["teams"])


# ---------- Schemas ----------

class AgentSpec(BaseModel):
    type: str
    role: str


class CreateTeamRequest(BaseModel):
    name: str
    agents: List[AgentSpec]
    conversation_id: Optional[uuid.UUID] = None


class AddAgentRequest(BaseModel):
    type: str
    role: str


class TeamStatus(BaseModel):
    id: str
    name: str
    agents: List[dict]
    status: str


# ---------- Routes ----------

@router.post("", response_model=TeamStatus)
async def create_team(
    req: CreateTeamRequest,
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    team = await team_manager.create_team(
        db=db,
        name=req.name,
        agent_specs=[a.model_dump() for a in req.agents],
        conversation_id=req.conversation_id or uuid.uuid4(),
    )
    return team


@router.get("/{team_id}", response_model=TeamStatus)
async def get_team_status(
    team_id: str,
    user: User = Depends(get_current_user_from_token),
):
    team = team_manager.get_team(team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    return team


@router.post("/{team_id}/agents")
async def add_agent_to_team(
    team_id: str,
    req: AddAgentRequest,
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    result = await team_manager.add_agent(
        db=db,
        team_id=team_id,
        agent_type=req.type,
        role=req.role,
    )
    return result


@router.delete("/{team_id}")
async def dissolve_team(
    team_id: str,
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    await team_manager.dissolve(team_id, db)
    return {"detail": "Team dissolved"}
