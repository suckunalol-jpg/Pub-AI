"""Team Templates & Custom Agent Types API.

Manage reusable team configurations and user-defined agent roles.
"""

import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from agents.team_manager import team_manager
from api.auth import get_current_user_from_token
from db.database import get_db, async_session
from db.models import CustomAgentType, TeamTemplate, User

router = APIRouter(tags=["team-templates"])


# ---------- Schemas ----------

class AgentSpecSchema(BaseModel):
    type: str
    role: str
    task: Optional[str] = None


class TeamTemplateCreate(BaseModel):
    name: str
    description: Optional[str] = None
    agent_specs: List[AgentSpecSchema]


class TeamTemplateUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    agent_specs: Optional[List[AgentSpecSchema]] = None


class TeamTemplateOut(BaseModel):
    id: uuid.UUID
    name: str
    description: Optional[str] = None
    agent_specs: list
    is_preset: bool
    created_at: datetime
    updated_at: datetime
    user_id: Optional[uuid.UUID] = None

    model_config = {"from_attributes": True}


class TeamTemplateLaunch(BaseModel):
    task: Optional[str] = None
    conversation_id: Optional[uuid.UUID] = None


class CustomAgentTypeCreate(BaseModel):
    type_key: str
    role: str
    specialty: str
    system_prompt_extra: Optional[str] = None
    max_iterations: Optional[int] = 50
    temperature: Optional[int] = 4  # stored as int * 10 (e.g., 4 = 0.4)


class CustomAgentTypeOut(BaseModel):
    id: uuid.UUID
    type_key: str
    role: str
    specialty: str
    system_prompt_extra: Optional[str] = None
    max_iterations: int
    temperature: int
    created_at: datetime
    user_id: uuid.UUID

    model_config = {"from_attributes": True}


# ---------- Seed Presets ----------

PRESET_TEMPLATES = [
    {
        "name": "Full Stack Team",
        "description": "A balanced team for building full-stack features: planning, frontend, backend, and QA.",
        "agent_specs": [
            {"type": "planner", "role": "Tech Lead - breaks down features and coordinates"},
            {"type": "coder", "role": "Frontend Developer - builds UI components"},
            {"type": "coder", "role": "Backend Developer - builds APIs and services"},
            {"type": "reviewer", "role": "QA Engineer - reviews code and catches bugs"},
        ],
    },
    {
        "name": "Code Review Team",
        "description": "Focused code authoring and multi-reviewer pipeline for thorough review.",
        "agent_specs": [
            {"type": "coder", "role": "Author - writes the code"},
            {"type": "reviewer", "role": "Reviewer 1 - focuses on correctness and bugs"},
            {"type": "reviewer", "role": "Reviewer 2 - focuses on performance and security"},
        ],
    },
    {
        "name": "Research Team",
        "description": "Multi-agent research with primary sourcing, fact checking, and synthesis.",
        "agent_specs": [
            {"type": "researcher", "role": "Lead Researcher - finds primary sources"},
            {"type": "researcher", "role": "Fact Checker - verifies claims"},
            {"type": "planner", "role": "Synthesizer - combines findings into report"},
        ],
    },
    {
        "name": "Roblox Dev Team",
        "description": "Specialized team for Roblox game development, UI design, and security auditing.",
        "agent_specs": [
            {"type": "roblox", "role": "Game Developer - writes game logic and scripts"},
            {"type": "roblox", "role": "UI/UX Designer - builds interfaces"},
            {"type": "reviewer", "role": "Security Auditor - checks for exploits"},
        ],
    },
]


async def seed_team_presets():
    """Create system preset team templates if they don't already exist."""
    async with async_session() as session:
        for preset in PRESET_TEMPLATES:
            result = await session.execute(
                select(TeamTemplate).where(
                    TeamTemplate.name == preset["name"],
                    TeamTemplate.is_preset == True,
                )
            )
            if result.scalar_one_or_none():
                continue  # Already seeded

            template = TeamTemplate(
                user_id=None,
                name=preset["name"],
                description=preset["description"],
                agent_specs=preset["agent_specs"],
                is_preset=True,
            )
            session.add(template)

        await session.commit()
        print("[Pub AI] Team presets seeded")


# ---------- Team Template Routes ----------

@router.post("/api/team-templates", response_model=TeamTemplateOut, status_code=201)
async def create_team_template(
    req: TeamTemplateCreate,
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    """Create a new team template for the current user."""
    template = TeamTemplate(
        user_id=user.id,
        name=req.name,
        description=req.description,
        agent_specs=[spec.model_dump() for spec in req.agent_specs],
        is_preset=False,
    )
    db.add(template)
    await db.flush()
    return template


@router.get("/api/team-templates", response_model=List[TeamTemplateOut])
async def list_team_templates(
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    """List all templates: the current user's custom templates plus system presets."""
    result = await db.execute(
        select(TeamTemplate)
        .where(
            or_(
                TeamTemplate.user_id == user.id,
                TeamTemplate.is_preset == True,
            )
        )
        .order_by(TeamTemplate.is_preset.desc(), TeamTemplate.created_at)
    )
    return result.scalars().all()


@router.get("/api/team-templates/presets", response_model=List[TeamTemplateOut])
async def list_preset_templates(
    db: AsyncSession = Depends(get_db),
):
    """List only system preset templates (no auth required)."""
    result = await db.execute(
        select(TeamTemplate)
        .where(TeamTemplate.is_preset == True)
        .order_by(TeamTemplate.created_at)
    )
    return result.scalars().all()


@router.get("/api/team-templates/{template_id}", response_model=TeamTemplateOut)
async def get_team_template(
    template_id: uuid.UUID,
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    """Get a single team template by ID."""
    result = await db.execute(
        select(TeamTemplate).where(TeamTemplate.id == template_id)
    )
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Team template not found")

    # Users can view their own templates and any preset
    if not template.is_preset and template.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized to view this template")

    return template


@router.put("/api/team-templates/{template_id}", response_model=TeamTemplateOut)
async def update_team_template(
    template_id: uuid.UUID,
    req: TeamTemplateUpdate,
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    """Update a team template. Only the owner can update; presets cannot be edited."""
    result = await db.execute(
        select(TeamTemplate).where(TeamTemplate.id == template_id)
    )
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Team template not found")

    if template.is_preset:
        raise HTTPException(status_code=403, detail="Cannot edit system preset templates")

    if template.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized to edit this template")

    if req.name is not None:
        template.name = req.name
    if req.description is not None:
        template.description = req.description
    if req.agent_specs is not None:
        template.agent_specs = [spec.model_dump() for spec in req.agent_specs]

    template.updated_at = datetime.utcnow()
    await db.flush()
    return template


@router.delete("/api/team-templates/{template_id}")
async def delete_team_template(
    template_id: uuid.UUID,
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    """Delete a team template. Only the owner can delete; presets cannot be deleted."""
    result = await db.execute(
        select(TeamTemplate).where(TeamTemplate.id == template_id)
    )
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Team template not found")

    if template.is_preset:
        raise HTTPException(status_code=403, detail="Cannot delete system preset templates")

    if template.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized to delete this template")

    await db.delete(template)
    await db.flush()
    return {"detail": f"Template '{template.name}' deleted"}


@router.post("/api/team-templates/{template_id}/launch")
async def launch_team_from_template(
    template_id: uuid.UUID,
    req: TeamTemplateLaunch,
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    """Launch a live agent team from a saved template.

    Creates real agents via the TeamManager using the template's agent_specs.
    """
    result = await db.execute(
        select(TeamTemplate).where(TeamTemplate.id == template_id)
    )
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Team template not found")

    # Users can launch their own templates or any preset
    if not template.is_preset and template.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized to use this template")

    conversation_id = req.conversation_id or uuid.uuid4()

    team = await team_manager.create_team(
        db=db,
        name=template.name,
        agent_specs=template.agent_specs,
        conversation_id=conversation_id,
        task=req.task,
        user_id=user.id,
    )
    return team


# ---------- Custom Agent Type Routes ----------

@router.post("/api/custom-agent-types", response_model=CustomAgentTypeOut, status_code=201)
async def create_custom_agent_type(
    req: CustomAgentTypeCreate,
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    """Create a custom agent type with a user-defined role and specialty."""
    # Check for duplicate type_key for this user
    existing = await db.execute(
        select(CustomAgentType).where(
            CustomAgentType.user_id == user.id,
            CustomAgentType.type_key == req.type_key,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail=f"Custom agent type '{req.type_key}' already exists for your account",
        )

    agent_type = CustomAgentType(
        user_id=user.id,
        type_key=req.type_key,
        role=req.role,
        specialty=req.specialty,
        system_prompt_extra=req.system_prompt_extra,
        max_iterations=req.max_iterations,
        temperature=req.temperature,
    )
    db.add(agent_type)
    await db.flush()
    return agent_type


@router.get("/api/custom-agent-types", response_model=List[CustomAgentTypeOut])
async def list_custom_agent_types(
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    """List the current user's custom agent types."""
    result = await db.execute(
        select(CustomAgentType)
        .where(CustomAgentType.user_id == user.id)
        .order_by(CustomAgentType.created_at)
    )
    return result.scalars().all()


@router.delete("/api/custom-agent-types/{agent_type_id}")
async def delete_custom_agent_type(
    agent_type_id: uuid.UUID,
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    """Delete a custom agent type. Only the owner can delete."""
    result = await db.execute(
        select(CustomAgentType).where(CustomAgentType.id == agent_type_id)
    )
    agent_type = result.scalar_one_or_none()
    if not agent_type:
        raise HTTPException(status_code=404, detail="Custom agent type not found")

    if agent_type.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized to delete this agent type")

    await db.delete(agent_type)
    await db.flush()
    return {"detail": f"Custom agent type '{agent_type.type_key}' deleted"}
