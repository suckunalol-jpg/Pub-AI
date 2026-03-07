"""Training job management -- queue, track, and cancel training runs."""

from __future__ import annotations

import asyncio
import logging
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, List, Optional

logger = logging.getLogger(__name__)


class JobType(str, Enum):
    MERGE = "merge"
    FINETUNE = "finetune"
    RLHF = "rlhf"
    EXPORT = "export"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class TrainingJob:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    job_type: JobType = JobType.FINETUNE
    status: JobStatus = JobStatus.QUEUED
    config: Dict[str, Any] = field(default_factory=dict)
    metrics: Dict[str, Any] = field(default_factory=dict)
    logs: List[str] = field(default_factory=list)
    error: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    _task: Optional[asyncio.Task] = field(default=None, repr=False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "job_type": self.job_type.value,
            "status": self.status.value,
            "config": self.config,
            "metrics": self.metrics,
            "logs": self.logs[-50:],  # Last 50 log lines
            "error": self.error,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }

    def log(self, message: str):
        timestamp = datetime.utcnow().strftime("%H:%M:%S")
        entry = f"[{timestamp}] {message}"
        self.logs.append(entry)
        logger.info("Job %s: %s", self.id[:8], message)


class JobManager:
    """Manages training jobs as background asyncio tasks."""

    def __init__(self):
        self._jobs: Dict[str, TrainingJob] = {}

    def create_job(
        self,
        job_type: JobType,
        config: Dict[str, Any],
        run_fn: Callable[..., Any],
    ) -> TrainingJob:
        """Create and queue a training job.

        Args:
            job_type: Type of training job.
            config: Configuration dict for the job.
            run_fn: The function to execute. Can be sync or async.
                    It receives the TrainingJob as the first argument.
        """
        job = TrainingJob(job_type=job_type, config=config)
        self._jobs[job.id] = job

        async def _run_wrapper():
            job.status = JobStatus.RUNNING
            job.started_at = datetime.utcnow().isoformat()
            job.log(f"Started {job_type.value} job")

            try:
                if asyncio.iscoroutinefunction(run_fn):
                    result = await run_fn(job)
                else:
                    # Run blocking functions in a thread pool
                    loop = asyncio.get_event_loop()
                    result = await loop.run_in_executor(None, run_fn, job)

                job.metrics = result if isinstance(result, dict) else {"result": result}
                job.status = JobStatus.COMPLETED
                job.log("Job completed successfully")
            except asyncio.CancelledError:
                job.status = JobStatus.CANCELLED
                job.log("Job was cancelled")
            except Exception as e:
                job.status = JobStatus.FAILED
                job.error = str(e)
                job.logs.append(traceback.format_exc())
                job.log(f"Job failed: {e}")
            finally:
                job.completed_at = datetime.utcnow().isoformat()

        job._task = asyncio.create_task(_run_wrapper())
        job.log("Job queued")
        return job

    def get_job(self, job_id: str) -> Optional[TrainingJob]:
        return self._jobs.get(job_id)

    def get_job_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        job = self._jobs.get(job_id)
        if job:
            return job.to_dict()
        return None

    def cancel_job(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if not job:
            return False
        if job._task and not job._task.done():
            job._task.cancel()
            return True
        return False

    def list_jobs(
        self,
        job_type: Optional[JobType] = None,
        status: Optional[JobStatus] = None,
    ) -> List[Dict[str, Any]]:
        jobs = self._jobs.values()
        if job_type:
            jobs = [j for j in jobs if j.job_type == job_type]
        if status:
            jobs = [j for j in jobs if j.status == status]
        return [j.to_dict() for j in sorted(jobs, key=lambda j: j.created_at, reverse=True)]


# Singleton instance
job_manager = JobManager()
