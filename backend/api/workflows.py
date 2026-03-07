import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agents.workflow_engine import workflow_engine
from api.auth import get_current_user_from_token
from db.database import get_db
from db.models import User, Workflow, WorkflowRun

router = APIRouter(prefix="/api/workflows", tags=["workflows"])


# ---------- Schemas ----------

class WorkflowCreate(BaseModel):
    name: str
    description: Optional[str] = None
    steps: list[dict]


class WorkflowOut(BaseModel):
    id: uuid.UUID
    name: str
    description: Optional[str]
    steps: list[dict]

    model_config = {"from_attributes": True}


class WorkflowRunOut(BaseModel):
    id: uuid.UUID
    workflow_id: uuid.UUID
    status: str
    step_results: dict

    model_config = {"from_attributes": True}


# ---------- Routes ----------

@router.post("", response_model=WorkflowOut)
async def create_workflow(
    req: WorkflowCreate,
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    wf = Workflow(
        user_id=user.id,
        name=req.name,
        description=req.description,
        steps=req.steps,
    )
    db.add(wf)
    await db.flush()
    return wf


@router.get("", response_model=list[WorkflowOut])
async def list_workflows(
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Workflow).where(Workflow.user_id == user.id).order_by(Workflow.created_at.desc())
    )
    return result.scalars().all()


@router.post("/{workflow_id}/run", response_model=WorkflowRunOut)
async def run_workflow(
    workflow_id: uuid.UUID,
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Workflow).where(Workflow.id == workflow_id, Workflow.user_id == user.id)
    )
    wf = result.scalar_one_or_none()
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")

    run = await workflow_engine.start_run(db=db, workflow=wf)
    return run


@router.get("/{workflow_id}/runs/{run_id}", response_model=WorkflowRunOut)
async def get_run_status(
    workflow_id: uuid.UUID,
    run_id: uuid.UUID,
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(WorkflowRun).where(
            WorkflowRun.id == run_id,
            WorkflowRun.workflow_id == workflow_id,
        )
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run
