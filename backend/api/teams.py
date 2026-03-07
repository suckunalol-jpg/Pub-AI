"""Teams API — create, manage, and coordinate agent teams."""

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
    task: Optional[str] = None


class CreateTeamRequest(BaseModel):
    name: str
    agents: List[AgentSpec]
    task: Optional[str] = None
    conversation_id: Optional[uuid.UUID] = None


class AddAgentRequest(BaseModel):
    type: str
    role: str
    task: Optional[str] = None


class BroadcastRequest(BaseModel):
    message: str
    sender: Optional[str] = "user"


class RouteMessageRequest(BaseModel):
    from_agent_id: str
    to_agent_id: str
    message: str


class TeamStatus(BaseModel):
    id: str
    name: str
    agents: List[dict]
    status: str
    message_count: Optional[int] = 0


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
        task=req.task,
        user_id=user.id,
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
        task=req.task,
    )
    return result


@router.post("/{team_id}/broadcast")
async def broadcast_to_team(
    team_id: str,
    req: BroadcastRequest,
    user: User = Depends(get_current_user_from_token),
):
    """Send a message to all agents in a team."""
    responses = await team_manager.broadcast(team_id, req.message, req.sender or "user")
    return {"responses": responses}


@router.post("/{team_id}/route")
async def route_team_message(
    team_id: str,
    req: RouteMessageRequest,
    user: User = Depends(get_current_user_from_token),
):
    """Route a message between two agents in a team."""
    response = await team_manager.route_message(
        team_id, req.from_agent_id, req.to_agent_id, req.message
    )
    return {"response": response}


@router.post("/{team_id}/review")
async def auto_review_team(
    team_id: str,
    user: User = Depends(get_current_user_from_token),
):
    """Have team agents review each other's work."""
    reviews = await team_manager.auto_review(team_id)
    return {"reviews": reviews}


@router.get("/{team_id}/results")
async def get_team_results(
    team_id: str,
    user: User = Depends(get_current_user_from_token),
):
    """Get combined results from all agents in a team."""
    results = await team_manager.get_team_results(team_id)
    return results


@router.delete("/{team_id}")
async def dissolve_team(
    team_id: str,
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    await team_manager.dissolve(team_id, db)
    return {"detail": "Team dissolved"}
