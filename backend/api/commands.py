"""Slash commands API — returns available commands and handles server-side commands."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.auth import get_current_user_from_token
from db.models import User

router = APIRouter(prefix="/api/chat", tags=["commands"])


class SlashCommand(BaseModel):
    name: str
    description: str
    usage: str
    type: str  # "local" | "server"


COMMANDS: list[SlashCommand] = [
    SlashCommand(
        name="clear",
        description="Clear the current chat",
        usage="/clear",
        type="local",
    ),
    SlashCommand(
        name="new",
        description="Start a new conversation",
        usage="/new",
        type="local",
    ),
    SlashCommand(
        name="theme",
        description="Switch theme (default, terminal, midnight, mizzy)",
        usage="/theme <name>",
        type="local",
    ),
    SlashCommand(
        name="help",
        description="Show all available commands",
        usage="/help",
        type="server",
    ),
    SlashCommand(
        name="export",
        description="Export the current chat as markdown",
        usage="/export",
        type="local",
    ),
    SlashCommand(
        name="system",
        description="Set a temporary system prompt for this chat",
        usage="/system <prompt>",
        type="server",
    ),
    SlashCommand(
        name="model",
        description="Show or switch the current AI model",
        usage="/model [name]",
        type="server",
    ),
]


@router.get("/commands", response_model=list[SlashCommand])
async def list_commands(
    _user: User = Depends(get_current_user_from_token),
):
    """Return the list of available slash commands."""
    return COMMANDS
