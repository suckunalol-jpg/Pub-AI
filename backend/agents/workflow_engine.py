from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import Any, Dict, List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ai.provider import ai_provider
from db.models import Workflow, WorkflowRun
from executor.sandbox import sandbox


class WorkflowEngine:
    """Executes workflow steps sequentially or in parallel based on dependencies."""

    async def start_run(self, db: AsyncSession, workflow: Workflow) -> WorkflowRun:
        run = WorkflowRun(
            workflow_id=workflow.id,
            status="running",
            step_results={},
        )
        db.add(run)
        await db.flush()

        # Capture IDs before the request session closes
        run_id = run.id
        steps = list(workflow.steps)

        # Launch execution in background with its own DB session
        asyncio.create_task(self._execute(run_id, steps))
        return run

    async def _execute(self, run_id: uuid.UUID, steps: List[Dict]):
        """Execute workflow steps respecting depends_on relationships."""
        from db.database import async_session

        results: Dict[str, Any] = {}
        completed: set = set()

        # Build dependency graph
        step_map = {s["id"]: s for s in steps}
        pending = set(step_map.keys())

        while pending:
            # Find steps whose dependencies are all met
            ready = []
            for step_id in pending:
                step = step_map[step_id]
                deps = step.get("depends_on", [])
                if all(d in completed for d in deps):
                    ready.append(step)

            if not ready:
                # Deadlock or circular dependency
                results["_error"] = "Deadlock: unresolvable dependencies"
                break

            # Execute ready steps in parallel
            tasks = [self._execute_step(step, results) for step in ready]
            step_results = await asyncio.gather(*tasks, return_exceptions=True)

            for step, result in zip(ready, step_results):
                step_id = step["id"]
                if isinstance(result, Exception):
                    results[step_id] = {"error": str(result)}
                else:
                    results[step_id] = result
                completed.add(step_id)
                pending.discard(step_id)

        # Update run record with its own session
        async with async_session() as db:
            try:
                result = await db.execute(select(WorkflowRun).where(WorkflowRun.id == run_id))
                run = result.scalar_one_or_none()
                if run:
                    run.step_results = results
                    run.status = "completed" if "_error" not in results else "failed"
                    run.completed_at = datetime.utcnow()
                    await db.commit()
            except Exception:
                await db.rollback()

    async def _execute_step(self, step: Dict, prior_results: Dict) -> Dict[str, Any]:
        step_type = step.get("type", "ai")

        if step_type == "ai":
            prompt = step.get("prompt", "")
            # Inject prior step results as context
            context_parts = []
            for dep_id in step.get("depends_on", []):
                if dep_id in prior_results:
                    context_parts.append(f"Step {dep_id} result: {prior_results[dep_id]}")
            if context_parts:
                prompt = "\n".join(context_parts) + "\n\n" + prompt

            resp = await ai_provider.chat(
                messages=[{"role": "user", "content": prompt}]
            )
            return {"content": resp.content, "tokens": resp.tokens_in + resp.tokens_out}

        elif step_type == "code" or step_type == "execute":
            language = step.get("language", "python")
            code = step.get("code", "")
            result = await sandbox.execute(language=language, code=code)
            return result

        else:
            return {"error": f"Unknown step type: {step_type}"}


workflow_engine = WorkflowEngine()
