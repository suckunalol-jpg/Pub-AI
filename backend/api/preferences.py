"""User Preferences API — theme, custom instructions, etc."""

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import get_current_user_from_token
from db.database import get_db
from db.models import User

router = APIRouter(prefix="/api/preferences", tags=["preferences"])


class PreferencesPayload(BaseModel):
    theme: Optional[str] = None  # default | terminal | midnight | mizzy
    custom_instructions: Optional[str] = None


@router.get("")
async def get_preferences(user: User = Depends(get_current_user_from_token)):
    prefs = user.preferences_json or {}
    return {
        "theme": prefs.get("theme", "default"),
        "custom_instructions": prefs.get("custom_instructions", ""),
    }


@router.put("")
async def save_preferences(
    payload: PreferencesPayload,
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    prefs = dict(user.preferences_json or {})
    if payload.theme is not None:
        prefs["theme"] = payload.theme
    if payload.custom_instructions is not None:
        prefs["custom_instructions"] = payload.custom_instructions
    user.preferences_json = prefs
    # SQLAlchemy may not detect in-place dict mutation, so flag it
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(user, "preferences_json")
    await db.flush()
    return {"detail": "Preferences saved", **prefs}
