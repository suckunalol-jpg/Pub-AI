from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import get_current_user_from_token
from db.database import get_db
from db.models import ExecutionLog, User
from executor.sandbox import sandbox

router = APIRouter(prefix="/api/execute", tags=["execute"])

SUPPORTED_LANGUAGES = [
    {"id": "python", "name": "Python 3", "extension": ".py"},
    {"id": "javascript", "name": "Node.js", "extension": ".js"},
    {"id": "lua", "name": "Lua 5.1", "extension": ".lua"},
]


# ---------- Schemas ----------

class ExecuteRequest(BaseModel):
    language: str
    code: str


class ExecuteResponse(BaseModel):
    output: str
    exit_code: int
    duration_ms: int


# ---------- Routes ----------

@router.post("", response_model=ExecuteResponse)
async def execute_code(
    req: ExecuteRequest,
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    result = await sandbox.execute(language=req.language, code=req.code)

    # Log execution
    log = ExecutionLog(
        user_id=user.id,
        language=req.language,
        code=req.code,
        output=result["output"],
        exit_code=result["exit_code"],
        duration_ms=result["duration_ms"],
    )
    db.add(log)

    return ExecuteResponse(
        output=result["output"],
        exit_code=result["exit_code"],
        duration_ms=result["duration_ms"],
    )


@router.get("/languages")
async def list_languages():
    return SUPPORTED_LANGUAGES
