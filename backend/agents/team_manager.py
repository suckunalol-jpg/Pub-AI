from __future__ import annotations

import asyncio
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from agents.orchestrator import orchestrator


class TeamManager:
    """Manages teams of agents working together."""

    def __init__(self):
        self._teams: Dict[str, Dict[str, Any]] = {}

    async def create_team(
        self,
        db: AsyncSession,
        name: str,
        agent_specs: List[Dict[str, str]],
        conversation_id: uuid.UUID,
    ) -> Dict[str, Any]:
        team_id = str(uuid.uuid4())[:8]

        agents = []
        for spec in agent_specs:
            session = await orchestrator.spawn(
                db=db,
                agent_type=spec["type"],
                task=f"Team role: {spec['role']}",
                conversation_id=conversation_id,
                config={"team_id": team_id, "role": spec["role"]},
            )
            agents.append({
                "id": str(session.id),
                "type": session.agent_type,
                "name": session.agent_name,
                "role": spec["role"],
                "status": session.status,
            })

        team = {
            "id": team_id,
            "name": name,
            "agents": agents,
            "status": "running",
            "conversation_id": str(conversation_id),
        }
        self._teams[team_id] = team
        return team

    def get_team(self, team_id: str) -> Optional[Dict[str, Any]]:
        team = self._teams.get(team_id)
        if not team:
            return None
        # Update agent statuses
        for agent_info in team["agents"]:
            agent = orchestrator.get_agent(uuid.UUID(agent_info["id"]))
            if agent:
                agent_info["status"] = agent.status
        return team

    async def add_agent(
        self,
        db: AsyncSession,
        team_id: str,
        agent_type: str,
        role: str,
    ) -> Dict[str, Any]:
        team = self._teams.get(team_id)
        if not team:
            raise ValueError("Team not found")

        conversation_id = uuid.UUID(team.get("conversation_id") or str(uuid.uuid4()))

        session = await orchestrator.spawn(
            db=db,
            agent_type=agent_type,
            task=f"Team role: {role}",
            conversation_id=conversation_id,
            config={"team_id": team_id, "role": role},
        )

        agent_info = {
            "id": str(session.id),
            "type": session.agent_type,
            "name": session.agent_name,
            "role": role,
            "status": session.status,
        }
        team["agents"].append(agent_info)
        return agent_info

    async def dissolve(self, team_id: str, db: AsyncSession):
        team = self._teams.pop(team_id, None)
        if not team:
            raise ValueError("Team not found")
        for agent_info in team["agents"]:
            await orchestrator.stop(uuid.UUID(agent_info["id"]), db)
        team["status"] = "dissolved"


team_manager = TeamManager()
