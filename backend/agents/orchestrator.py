"""Agent orchestrator — manages lifecycle, spawning, and coordination.

Wires in the Brain (intent classification + learning) and Memory (per-user context)
systems so every agent benefits from learned user preferences.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agents.base_agent import AgentContext, BaseAgent
from db.models import AgentSession


class Orchestrator:
    """Manages agent lifecycle: spawn, message, stop, coordinate."""

    def __init__(self):
        self._agents: Dict[uuid.UUID, BaseAgent] = {}
        self._tasks: Dict[uuid.UUID, asyncio.Task] = {}

    async def spawn(
        self,
        db: AsyncSession,
        agent_type: str,
        task: str,
        conversation_id: uuid.UUID,
        config: dict = {},
        parent_id: Optional[uuid.UUID] = None,
        user_id: Optional[uuid.UUID] = None,
    ) -> AgentSession:
        agent_id = uuid.uuid4()
        name = f"{agent_type}-{str(agent_id)[:8]}"

        # Create DB record
        session = AgentSession(
            id=agent_id,
            conversation_id=conversation_id,
            agent_type=agent_type,
            agent_name=name,
            status="running",
            parent_agent_id=parent_id,
            config=config,
        )
        db.add(session)
        await db.flush()

        # Build context with memory if user_id available
        memory_context = ""
        if user_id:
            try:
                from agents.memory import memory_system
                memory_context = await memory_system.build_memory_context(db, user_id, task)
            except Exception:
                pass

        context = AgentContext(
            task=task,
            config=config,
            parent_id=parent_id,
            team_id=config.get("team_id"),
        )

        # Inject memory into task if available
        if memory_context:
            context.task = f"{task}\n\n--- User Context ---\n{memory_context}"

        agent = BaseAgent(
            agent_id=agent_id,
            agent_type=agent_type,
            name=name,
            context=context,
        )
        self._agents[agent_id] = agent

        # Run agent in background
        async_task = asyncio.create_task(self._run_agent(agent_id))
        self._tasks[agent_id] = async_task

        return session

    async def _run_agent(self, agent_id: uuid.UUID):
        agent = self._agents.get(agent_id)
        if not agent:
            return

        try:
            result = await agent.run()

            # Update DB record
            from db.database import async_session
            async with async_session() as db:
                try:
                    stmt = select(AgentSession).where(AgentSession.id == agent_id)
                    db_result = await db.execute(stmt)
                    session = db_result.scalar_one_or_none()
                    if session:
                        session.status = agent.status
                        session.result = result
                        session.completed_at = datetime.utcnow()
                        await db.commit()
                except Exception:
                    await db.rollback()
        except Exception as e:
            agent.status = "failed"
            agent.result = {"error": str(e)}

    async def send_message(self, agent_id: uuid.UUID, message: str) -> str:
        agent = self._agents.get(agent_id)
        if not agent:
            raise ValueError("Agent not found or already stopped")
        if agent.status != "running":
            raise ValueError(f"Agent is {agent.status}")
        return await agent.handle_message(message)

    async def stop(self, agent_id: uuid.UUID, db: AsyncSession):
        agent = self._agents.pop(agent_id, None)
        if agent:
            agent.stop()

        task = self._tasks.pop(agent_id, None)
        if task and not task.done():
            task.cancel()

        # Update DB
        result = await db.execute(select(AgentSession).where(AgentSession.id == agent_id))
        session = result.scalar_one_or_none()
        if session:
            session.status = "stopped"
            session.completed_at = datetime.utcnow()
            session.result = agent.result if agent else {"error": "Stopped"}

    def get_agent(self, agent_id: uuid.UUID) -> Optional[BaseAgent]:
        return self._agents.get(agent_id)

    def list_agents(self) -> list:
        return [agent.get_state() for agent in self._agents.values()]


orchestrator = Orchestrator()
