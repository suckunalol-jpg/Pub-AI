"""Auto-retraining scheduler -- collects new feedback data and exports training JSONL.

Runs as a background asyncio task during the app lifespan. Every 10 minutes it:
1. Queries new Messages + Feedback since the last export cycle
2. Groups by conversation, formats as ChatML JSONL
3. Saves to the datasets directory
4. Optionally triggers a fine-tune job via job_manager
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import select, and_

logger = logging.getLogger(__name__)

# How often the scheduler runs (seconds)
RETRAIN_INTERVAL_SECONDS = 10 * 60  # 10 minutes

# Minimum number of new examples required before exporting
MIN_EXAMPLES_TO_EXPORT = 1


class AutoRetrainer:
    """Background scheduler that exports new feedback-rated conversations as training data."""

    def __init__(self) -> None:
        self._last_export_time: datetime = datetime.utcnow()
        self._task: Optional[asyncio.Task] = None
        self._running: bool = False

        # Stats tracked across the lifetime of the process
        self.total_exports: int = 0
        self.total_examples_exported: int = 0
        self.last_export_examples: int = 0
        self.last_export_path: Optional[str] = None
        self.last_error: Optional[str] = None
        self.last_export_at: Optional[str] = None

    # ------------------------------------------------------------------
    # Data collection
    # ------------------------------------------------------------------

    async def collect_new_data(self) -> List[Dict[str, Any]]:
        """Query Messages + Feedback created since the last export, grouped by conversation.

        Only conversations that have at least one piece of feedback (liked or disliked)
        are included. The feedback signal is recorded in the output so downstream
        consumers can distinguish positive from negative examples.

        Returns:
            List of ChatML dicts: [{"messages": [...], "feedback": "liked"|"disliked"}, ...]
        """
        from db.database import async_session
        from db.models import Message, Feedback, Conversation
        from ai.prompts import GENERAL_SYSTEM_PROMPT

        examples: List[Dict[str, Any]] = []
        since = self._last_export_time

        async with async_session() as session:
            # Step 1: Find assistant messages that received feedback since the last export
            stmt = (
                select(Message.conversation_id, Feedback.rating)
                .join(Feedback, Feedback.message_id == Message.id)
                .where(
                    and_(
                        Message.role == "assistant",
                        Feedback.created_at >= since,
                    )
                )
                .order_by(Feedback.created_at.desc())
            )

            result = await session.execute(stmt)
            feedback_rows = result.all()

            if not feedback_rows:
                return examples

            # Step 2: Deduplicate by conversation, keep the best rating per conversation
            conv_ratings: Dict[Any, int] = {}
            for conv_id, rating in feedback_rows:
                # If any message in the conversation was liked (2), mark the whole
                # conversation as liked; otherwise keep disliked (1).
                existing = conv_ratings.get(conv_id, 0)
                if rating > existing:
                    conv_ratings[conv_id] = rating

            # Step 3: For each conversation, fetch all messages and build ChatML
            for conv_id, best_rating in conv_ratings.items():
                conv_stmt = (
                    select(Message)
                    .where(Message.conversation_id == conv_id)
                    .order_by(Message.created_at)
                )
                conv_result = await session.execute(conv_stmt)
                conv_messages = conv_result.scalars().all()

                messages = [{"role": "system", "content": GENERAL_SYSTEM_PROMPT}]
                for m in conv_messages:
                    if m.role in ("user", "assistant"):
                        messages.append({"role": m.role, "content": m.content})

                # Need at least system + user + assistant (3 messages)
                if len(messages) < 3:
                    continue

                feedback_label = "liked" if best_rating >= 2 else "disliked"
                examples.append({
                    "messages": messages,
                    "feedback": feedback_label,
                })

        logger.info(
            "[Pub AI] Auto-retrain collected %d conversations since %s",
            len(examples),
            since.isoformat(),
        )
        return examples

    # ------------------------------------------------------------------
    # Export + optional training trigger
    # ------------------------------------------------------------------

    async def export_and_train(self) -> Dict[str, Any]:
        """Collect new data, save as JSONL, and log stats.

        Returns a summary dict with export results.
        """
        from training.data_prep import save_dataset, compute_stats
        from training.config import training_settings

        examples = await self.collect_new_data()

        if len(examples) < MIN_EXAMPLES_TO_EXPORT:
            logger.info("[Pub AI] Auto-retrain: no new data to export (found %d)", len(examples))
            return {"status": "skipped", "reason": "insufficient_data", "examples": len(examples)}

        # Update the checkpoint BEFORE saving so we don't re-export the same data
        # if the save itself fails we will still have moved the cursor forward,
        # which is acceptable -- better than infinite re-export of the same batch.
        export_time = datetime.utcnow()
        self._last_export_time = export_time

        # Build output filename with timestamp
        timestamp_str = export_time.strftime("%Y%m%d_%H%M%S")
        datasets_dir = Path(training_settings.DATASETS_DIR)
        output_path = str(datasets_dir / f"auto_retrain_{timestamp_str}.jsonl")

        # Save only the messages (strip the metadata 'feedback' key for pure ChatML)
        chatml_examples = [{"messages": ex["messages"]} for ex in examples]
        save_dataset(chatml_examples, output_path)

        stats = compute_stats(chatml_examples)

        # Update internal stats
        self.total_exports += 1
        self.total_examples_exported += len(chatml_examples)
        self.last_export_examples = len(chatml_examples)
        self.last_export_path = output_path
        self.last_export_at = export_time.isoformat()

        liked = sum(1 for ex in examples if ex.get("feedback") == "liked")
        disliked = len(examples) - liked

        print(
            f"[Pub AI] Auto-retrain exported {len(chatml_examples)} examples "
            f"({liked} liked, {disliked} disliked) -> {output_path}"
        )
        logger.info(
            "[Pub AI] Auto-retrain stats: %d examples, ~%d tokens, %.1f avg turns",
            stats.total_examples,
            stats.total_tokens_approx,
            stats.avg_turns,
        )

        return {
            "status": "exported",
            "path": output_path,
            "examples": len(chatml_examples),
            "liked": liked,
            "disliked": disliked,
            "approx_tokens": stats.total_tokens_approx,
            "avg_turns": stats.avg_turns,
        }

    # ------------------------------------------------------------------
    # Background loop
    # ------------------------------------------------------------------

    async def run_loop(self) -> None:
        """Infinite loop that calls export_and_train every RETRAIN_INTERVAL_SECONDS.

        Catches all exceptions so the loop never dies unexpectedly.
        """
        self._running = True
        print(f"[Pub AI] Auto-retrain scheduler started (interval={RETRAIN_INTERVAL_SECONDS}s)")

        while self._running:
            try:
                await asyncio.sleep(RETRAIN_INTERVAL_SECONDS)
                await self.export_and_train()
            except asyncio.CancelledError:
                print("[Pub AI] Auto-retrain scheduler cancelled")
                break
            except Exception as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"
                logger.exception("[Pub AI] Auto-retrain loop error: %s", exc)
                # Continue the loop -- don't let transient errors kill the scheduler

        self._running = False
        print("[Pub AI] Auto-retrain scheduler stopped")

    def start(self) -> asyncio.Task:
        """Create and return the background task. Call this during app startup."""
        self._task = asyncio.create_task(self.run_loop())
        return self._task

    def stop(self) -> None:
        """Cancel the background task. Call this during app shutdown."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()

    def status(self) -> Dict[str, Any]:
        """Return the current status of the auto-retrainer."""
        return {
            "running": self._running,
            "interval_seconds": RETRAIN_INTERVAL_SECONDS,
            "last_export_time": self._last_export_time.isoformat(),
            "last_export_at": self.last_export_at,
            "last_export_examples": self.last_export_examples,
            "last_export_path": self.last_export_path,
            "total_exports": self.total_exports,
            "total_examples_exported": self.total_examples_exported,
            "last_error": self.last_error,
        }


# Singleton instance
auto_retrainer = AutoRetrainer()
