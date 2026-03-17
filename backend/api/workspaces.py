"""Workspace container API — manage per-agent Docker containers."""

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import get_current_user_from_token
from db.database import get_db
from db.models import User

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])


class ExecRequest(BaseModel):
    command: str
    timeout: Optional[int] = None
    cwd: Optional[str] = None


class UploadRequest(BaseModel):
    path: str
    content: str


class ExecResponse(BaseModel):
    output: str
    exit_code: int
    duration_ms: int


# ---------- Routes ----------

@router.post("/{agent_id}/exec", response_model=ExecResponse)
async def exec_in_workspace(
    agent_id: uuid.UUID,
    req: ExecRequest,
    user: User = Depends(get_current_user_from_token),
):
    from executor.container_manager import container_manager
    result = await container_manager.exec_command(
        agent_id, req.command, timeout=req.timeout, cwd=req.cwd
    )
    return ExecResponse(
        output=result.get("output", ""),
        exit_code=result.get("exit_code", 0),
        duration_ms=result.get("duration_ms", 0),
    )


@router.post("/{agent_id}/upload")
async def upload_to_workspace(
    agent_id: uuid.UUID,
    req: UploadRequest,
    user: User = Depends(get_current_user_from_token),
):
    from executor.container_manager import container_manager
    await container_manager.upload_file(agent_id, req.path, req.content)
    return {"detail": f"File written to {req.path}"}


@router.get("/{agent_id}/download")
async def download_from_workspace(
    agent_id: uuid.UUID,
    path: str,
    user: User = Depends(get_current_user_from_token),
):
    from fastapi.responses import Response
    from executor.container_manager import container_manager
    content = await container_manager.download_file(agent_id, path)
    filename = path.rsplit("/", 1)[-1] or "file"
    return Response(
        content=content,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{agent_id}")
async def get_workspace_info(
    agent_id: uuid.UUID,
    user: User = Depends(get_current_user_from_token),
):
    from executor.container_manager import container_manager
    ws = container_manager._containers.get(agent_id)
    if not ws:
        raise HTTPException(status_code=404, detail="No workspace container for this agent")
    return {
        "agent_id": str(agent_id),
        "container_name": ws.container_name,
        "container_id": ws.container_id,
        "status": ws.status,
        "last_activity": ws.last_activity.isoformat(),
        "vnc_url": container_manager.get_vnc_url(agent_id),
        "volume_name": ws.volume_name,
    }


@router.delete("/{agent_id}")
async def destroy_workspace(
    agent_id: uuid.UUID,
    user: User = Depends(get_current_user_from_token),
):
    from executor.container_manager import container_manager
    await container_manager.destroy(agent_id)
    return {"detail": "Container destroyed"}


@router.get("")
async def list_workspaces(
    user: User = Depends(get_current_user_from_token),
):
    from executor.container_manager import container_manager
    return await container_manager.list_containers()
