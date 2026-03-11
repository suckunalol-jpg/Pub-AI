"""
Scheduler Tool — adapted from Agent Zero's scheduler.py.
Allows the agent to schedule tasks to run at specified times.
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from agent_engine.tools_base import BaseTool, register_tool

if TYPE_CHECKING:
    from agent_engine.agent import Agent

logger = logging.getLogger(__name__)

SCHEDULER_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "data", "scheduler.json")


def _ensure_data_dir():
    os.makedirs(os.path.dirname(SCHEDULER_FILE), exist_ok=True)


def _load_tasks() -> list[dict]:
    _ensure_data_dir()
    if not os.path.exists(SCHEDULER_FILE):
        return []
    try:
        with open(SCHEDULER_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []


def _save_tasks(tasks: list[dict]):
    _ensure_data_dir()
    with open(SCHEDULER_FILE, "w", encoding="utf-8") as f:
        json.dump(tasks, f, indent=2, default=str)


@register_tool
class SchedulerTool(BaseTool):
    """Schedule, list, or cancel recurring tasks."""

    name = "scheduler"
    description = (
        "Manage scheduled tasks. "
        "Args: action (create|list|cancel), task (task description for create), "
        "interval (e.g. '30m', '1h', '24h' for create), task_id (for cancel)."
    )

    async def execute(self) -> str:
        action = self.args.get("action", "list").lower()

        if action == "create":
            return await self._create_task()
        elif action == "list":
            return await self._list_tasks()
        elif action == "cancel":
            return await self._cancel_task()
        else:
            return f"Unknown scheduler action '{action}'. Use create, list, or cancel."

    async def _create_task(self) -> str:
        task_desc = self.args.get("task", "")
        interval = self.args.get("interval", "1h")

        if not task_desc:
            return "Error: No task description provided."

        import uuid
        task_entry = {
            "id": str(uuid.uuid4())[:8],
            "task": task_desc,
            "interval": interval,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_run": None,
            "status": "active",
        }

        tasks = _load_tasks()
        tasks.append(task_entry)
        _save_tasks(tasks)

        return f"Scheduled task '{task_desc}' every {interval} (id: {task_entry['id']})."

    async def _list_tasks(self) -> str:
        tasks = _load_tasks()
        if not tasks:
            return "No scheduled tasks."

        output = []
        for t in tasks:
            status = t.get("status", "active")
            output.append(
                f"- [{status}] {t['task']} (every {t['interval']}, id: {t['id']})"
            )
        return "\n".join(output)

    async def _cancel_task(self) -> str:
        task_id = self.args.get("task_id", "")
        if not task_id:
            return "Error: No task_id provided."

        tasks = _load_tasks()
        for t in tasks:
            if t["id"] == task_id:
                t["status"] = "cancelled"
                _save_tasks(tasks)
                return f"Task {task_id} cancelled."

        return f"Task {task_id} not found."
