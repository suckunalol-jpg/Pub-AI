"""Training data preparation from database exports and uploaded files."""

from __future__ import annotations

import csv
import io
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from training.config import training_settings

logger = logging.getLogger(__name__)

PUB_AI_SYSTEM = "You are Pub AI, an expert coding assistant."


@dataclass
class DatasetStats:
    total_examples: int = 0
    total_tokens_approx: int = 0
    categories: Dict[str, int] = None
    avg_turns: float = 0.0
    sources: List[str] = None

    def __post_init__(self):
        if self.categories is None:
            self.categories = {}
        if self.sources is None:
            self.sources = []


async def export_conversations_from_db(
    db_session,
    min_rating: int = 2,
    max_examples: int = 10000,
) -> List[Dict[str, Any]]:
    """Query messages table and format liked conversations as training examples.

    Args:
        db_session: SQLAlchemy async session.
        min_rating: Minimum feedback rating to include (2=liked, 1=disliked).
        max_examples: Maximum number of examples to export.

    Returns:
        List of ChatML-formatted training examples.
    """
    from sqlalchemy import select, and_
    from db.models import Message, Feedback, Conversation

    # Find messages that received positive feedback
    stmt = (
        select(Message, Feedback.rating)
        .outerjoin(Feedback, Feedback.message_id == Message.id)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(
            and_(
                Message.role == "assistant",
                Feedback.rating >= min_rating,
            )
        )
        .order_by(Message.created_at.desc())
        .limit(max_examples)
    )

    result = await db_session.execute(stmt)
    liked_messages = result.all()

    examples = []
    seen_convos = set()

    for msg, rating in liked_messages:
        if msg.conversation_id in seen_convos:
            continue
        seen_convos.add(msg.conversation_id)

        # Get full conversation for this message
        conv_stmt = (
            select(Message)
            .where(Message.conversation_id == msg.conversation_id)
            .order_by(Message.created_at)
        )
        conv_result = await db_session.execute(conv_stmt)
        conv_messages = conv_result.scalars().all()

        messages = [{"role": "system", "content": PUB_AI_SYSTEM}]
        for m in conv_messages:
            if m.role in ("user", "assistant"):
                messages.append({"role": m.role, "content": m.content})

        if len(messages) >= 3:  # system + at least 1 user + 1 assistant
            examples.append({"messages": messages})

    logger.info("Exported %d conversation examples from DB", len(examples))
    return examples


async def export_negative_examples(
    db_session,
    max_examples: int = 5000,
) -> List[Dict[str, Any]]:
    """Export disliked conversations for DPO rejected examples."""
    from sqlalchemy import select, and_
    from db.models import Message, Feedback

    stmt = (
        select(Message)
        .join(Feedback, Feedback.message_id == Message.id)
        .where(
            and_(
                Message.role == "assistant",
                Feedback.rating <= 1,
            )
        )
        .order_by(Message.created_at.desc())
        .limit(max_examples)
    )

    result = await db_session.execute(stmt)
    disliked = result.scalars().all()

    examples = []
    for msg in disliked:
        # Get the preceding user message
        from sqlalchemy import select as sel
        user_stmt = (
            select(Message)
            .where(
                and_(
                    Message.conversation_id == msg.conversation_id,
                    Message.role == "user",
                    Message.created_at < msg.created_at,
                )
            )
            .order_by(Message.created_at.desc())
            .limit(1)
        )
        user_result = await db_session.execute(user_stmt)
        user_msg = user_result.scalar_one_or_none()

        if user_msg:
            examples.append({
                "prompt": user_msg.content,
                "rejected": msg.content,
                "conversation_id": str(msg.conversation_id),
            })

    logger.info("Exported %d negative examples from DB", len(examples))
    return examples


def load_qa_dataset(file_content: str, file_format: str = "json") -> List[Dict]:
    """Parse Q&A data from file content into ChatML training format.

    Supported formats:
        json: [{"q": "...", "a": "..."}, ...] or [{"question": "...", "answer": "..."}, ...]
        text: Q: ...\nA: ...\n\nQ: ...\nA: ...
        csv: question,answer header with rows
    """
    examples = []

    if file_format == "json":
        data = json.loads(file_content)
        if not isinstance(data, list):
            data = [data]
        for item in data:
            q = item.get("q") or item.get("question") or item.get("instruction", "")
            a = item.get("a") or item.get("answer") or item.get("output", "")
            if q and a:
                examples.append({
                    "messages": [
                        {"role": "system", "content": PUB_AI_SYSTEM},
                        {"role": "user", "content": q},
                        {"role": "assistant", "content": a},
                    ]
                })

    elif file_format == "text":
        blocks = file_content.strip().split("\n\n")
        for block in blocks:
            lines = block.strip().split("\n")
            q_lines, a_lines = [], []
            current = None
            for line in lines:
                if line.startswith("Q:") or line.startswith("Question:"):
                    current = "q"
                    q_lines.append(line.split(":", 1)[1].strip())
                elif line.startswith("A:") or line.startswith("Answer:"):
                    current = "a"
                    a_lines.append(line.split(":", 1)[1].strip())
                elif current == "q":
                    q_lines.append(line)
                elif current == "a":
                    a_lines.append(line)

            q = "\n".join(q_lines).strip()
            a = "\n".join(a_lines).strip()
            if q and a:
                examples.append({
                    "messages": [
                        {"role": "system", "content": PUB_AI_SYSTEM},
                        {"role": "user", "content": q},
                        {"role": "assistant", "content": a},
                    ]
                })

    elif file_format == "csv":
        reader = csv.DictReader(io.StringIO(file_content))
        for row in reader:
            q = row.get("question") or row.get("q") or row.get("instruction", "")
            a = row.get("answer") or row.get("a") or row.get("output", "")
            if q and a:
                examples.append({
                    "messages": [
                        {"role": "system", "content": PUB_AI_SYSTEM},
                        {"role": "user", "content": q},
                        {"role": "assistant", "content": a},
                    ]
                })

    logger.info("Loaded %d Q&A examples from %s format", len(examples), file_format)
    return examples


def load_code_dataset(file_content: str) -> List[Dict]:
    """Parse code examples into instruction-following format.

    Expected JSON format:
    [{"language": "python", "instruction": "...", "code": "...", "explanation": "..."}, ...]
    """
    data = json.loads(file_content)
    if not isinstance(data, list):
        data = [data]

    examples = []
    for item in data:
        instruction = item.get("instruction", "")
        code = item.get("code", "")
        lang = item.get("language", "")
        explanation = item.get("explanation", "")

        if instruction and code:
            response = f"```{lang}\n{code}\n```"
            if explanation:
                response += f"\n\n{explanation}"

            examples.append({
                "messages": [
                    {"role": "system", "content": PUB_AI_SYSTEM},
                    {"role": "user", "content": instruction},
                    {"role": "assistant", "content": response},
                ]
            })

    logger.info("Loaded %d code examples", len(examples))
    return examples


def merge_datasets(*datasets: List[Dict]) -> List[Dict]:
    """Combine multiple dataset sources into a single list."""
    merged = []
    for ds in datasets:
        merged.extend(ds)
    logger.info("Merged %d total examples from %d sources", len(merged), len(datasets))
    return merged


def split_dataset(
    data: List[Dict], eval_ratio: float = 0.1
) -> Tuple[List[Dict], List[Dict]]:
    """Split data into train and eval sets."""
    import random

    shuffled = data.copy()
    random.shuffle(shuffled)

    split_idx = max(1, int(len(shuffled) * (1 - eval_ratio)))
    train = shuffled[:split_idx]
    eval_set = shuffled[split_idx:]

    logger.info("Split: %d train, %d eval", len(train), len(eval_set))
    return train, eval_set


def compute_stats(data: List[Dict]) -> DatasetStats:
    """Compute basic statistics for a dataset."""
    stats = DatasetStats(total_examples=len(data))

    total_chars = 0
    total_turns = 0

    for item in data:
        messages = item.get("messages", [])
        total_turns += len(messages)
        for msg in messages:
            total_chars += len(msg.get("content", ""))

    # Rough token estimate: ~4 chars per token
    stats.total_tokens_approx = total_chars // 4
    stats.avg_turns = total_turns / max(len(data), 1)

    return stats


def save_dataset(data: List[Dict], output_path: str) -> str:
    """Save dataset as JSONL file."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    with open(out, "w", encoding="utf-8") as f:
        for item in data:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    return str(out)
