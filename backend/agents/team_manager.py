"""Team manager — coordinates groups of agents working together.

Features:
- Create teams with specialized roles
- Inter-agent communication and message routing
- Shared context broadcasting
- Team-level task decomposition
- Auto-review: agents review each other's work
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from agents.orchestrator import orchestrator


class TeamManager:
    """Manages teams of agents working together with shared context."""

    def __init__(self):
        self._teams: Dict[str, Dict[str, Any]] = {}
        self._message_bus: Dict[str, List[Dict[str, str]]] = {}  # team_id -> messages

    async def create_team(
        self,
        db: AsyncSession,
        name: str,
        agent_specs: List[Dict[str, str]],
        conversation_id: uuid.UUID,
        task: Optional[str] = None,
        user_id: Optional[uuid.UUID] = None,
    ) -> Dict[str, Any]:
        team_id = str(uuid.uuid4())[:8]
        self._message_bus[team_id] = []

        agents = []
        for spec in agent_specs:
            agent_task = spec.get("task", f"Team role: {spec['role']}")
            if task:
                agent_task = f"TEAM TASK: {task}\n\nYOUR ROLE: {spec['role']}\n{agent_task}"

            session = await orchestrator.spawn(
                db=db,
                agent_type=spec["type"],
                task=agent_task,
                conversation_id=conversation_id,
                config={"team_id": team_id, "role": spec["role"]},
                user_id=user_id,
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
            "task": task,
            "message_count": 0,
        }
        self._teams[team_id] = team
        return team

    def get_team(self, team_id: str) -> Optional[Dict[str, Any]]:
        team = self._teams.get(team_id)
        if not team:
            return None
        # Update agent statuses
        all_done = True
        for agent_info in team["agents"]:
            agent = orchestrator.get_agent(uuid.UUID(agent_info["id"]))
            if agent:
                agent_info["status"] = agent.status
                if agent.status == "running":
                    all_done = False
                if agent.result:
                    agent_info["result_preview"] = agent.result.get("content", "")[:200]
        if all_done and team["status"] == "running":
            team["status"] = "completed"
        team["message_count"] = len(self._message_bus.get(team_id, []))
        return team

    async def add_agent(
        self,
        db: AsyncSession,
        team_id: str,
        agent_type: str,
        role: str,
        task: Optional[str] = None,
    ) -> Dict[str, Any]:
        team = self._teams.get(team_id)
        if not team:
            raise ValueError("Team not found")

        conversation_id = uuid.UUID(team.get("conversation_id") or str(uuid.uuid4()))
        agent_task = task or f"Team role: {role}"
        if team.get("task"):
            agent_task = f"TEAM TASK: {team['task']}\n\nYOUR ROLE: {role}\n{agent_task}"

        session = await orchestrator.spawn(
            db=db,
            agent_type=agent_type,
            task=agent_task,
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

    async def broadcast(self, team_id: str, message: str, sender: str = "system") -> List[str]:
        """Send a message to all agents in a team."""
        team = self._teams.get(team_id)
        if not team:
            raise ValueError("Team not found")

        self._message_bus.setdefault(team_id, []).append({
            "sender": sender,
            "message": message,
        })

        responses = []
        for agent_info in team["agents"]:
            agent = orchestrator.get_agent(uuid.UUID(agent_info["id"]))
            if agent and agent.status == "running":
                try:
                    resp = await agent.handle_message(f"[Team broadcast from {sender}]: {message}")
                    responses.append(f"{agent_info['name']}: {resp}")
                except Exception as e:
                    responses.append(f"{agent_info['name']}: Error: {e}")

        return responses

    async def route_message(
        self,
        team_id: str,
        from_agent_id: str,
        to_agent_id: str,
        message: str,
    ) -> str:
        """Route a message from one agent to another within a team."""
        team = self._teams.get(team_id)
        if not team:
            raise ValueError("Team not found")

        target = orchestrator.get_agent(uuid.UUID(to_agent_id))
        if not target:
            raise ValueError("Target agent not found")

        from_name = "unknown"
        for a in team["agents"]:
            if a["id"] == from_agent_id:
                from_name = a["name"]
                break

        self._message_bus.setdefault(team_id, []).append({
            "sender": from_name,
            "to": to_agent_id,
            "message": message,
        })

        return await target.handle_message(f"[Message from {from_name}]: {message}")

    async def auto_review(self, team_id: str) -> Dict[str, str]:
        """Have each agent review another agent's work."""
        team = self._teams.get(team_id)
        if not team:
            raise ValueError("Team not found")

        completed_agents = []
        for agent_info in team["agents"]:
            agent = orchestrator.get_agent(uuid.UUID(agent_info["id"]))
            if agent and agent.status == "completed" and agent.result:
                completed_agents.append((agent_info, agent))

        if len(completed_agents) < 2:
            return {"error": "Need at least 2 completed agents for cross-review"}

        reviews = {}
        for i, (info, agent) in enumerate(completed_agents):
            # Each agent reviews the next agent's work (circular)
            reviewer_info, reviewer = completed_agents[(i + 1) % len(completed_agents)]
            target_result = agent.result.get("content", "")[:2000]

            review_msg = (
                f"Review this work by {info['name']} ({info['role']}):\n\n"
                f"{target_result}\n\n"
                f"Identify: bugs, improvements, missing pieces, and overall quality (1-10)."
            )

            try:
                review = await reviewer.handle_message(review_msg)
                reviews[f"{reviewer_info['name']}_reviews_{info['name']}"] = review
            except Exception as e:
                reviews[f"{reviewer_info['name']}_reviews_{info['name']}"] = f"Error: {e}"

        return reviews

    async def get_team_results(self, team_id: str) -> Dict[str, Any]:
        """Get combined results from all agents in a team."""
        team = self._teams.get(team_id)
        if not team:
            raise ValueError("Team not found")

        results = {}
        for agent_info in team["agents"]:
            agent = orchestrator.get_agent(uuid.UUID(agent_info["id"]))
            if agent and agent.result:
                results[agent_info["name"]] = {
                    "role": agent_info["role"],
                    "status": agent.status,
                    "result": agent.result.get("content", ""),
                    "iterations": agent.result.get("iterations", 0),
                    "tools_used": agent.result.get("tools_used", 0),
                }
        return results

    async def dissolve(self, team_id: str, db: AsyncSession):
        team = self._teams.pop(team_id, None)
        if not team:
            raise ValueError("Team not found")
        for agent_info in team["agents"]:
            await orchestrator.stop(uuid.UUID(agent_info["id"]), db)
        team["status"] = "dissolved"
        self._message_bus.pop(team_id, None)


team_manager = TeamManager()
