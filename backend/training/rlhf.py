"""RLHF / DPO training from user feedback.

Uses Direct Preference Optimization (DPO) which is simpler and more
stable than full RLHF with PPO. Preference pairs come from user
like/dislike feedback in the database.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from training.config import training_settings

logger = logging.getLogger(__name__)


@dataclass
class DPOConfig:
    base_model: str = ""
    dataset_path: str = ""
    beta: float = 0.1  # DPO temperature -- lower = stronger preference
    learning_rate: float = 5e-5
    epochs: int = 1
    batch_size: int = 2
    gradient_accumulation_steps: int = 4
    max_seq_length: int = 2048
    max_prompt_length: int = 512
    lora_rank: int = 32
    lora_alpha: int = 64
    output_dir: str = ""

    def __post_init__(self):
        if not self.output_dir:
            self.output_dir = str(
                Path(training_settings.TRAINING_OUTPUT_DIR) / "dpo"
            )


async def extract_preference_pairs(db_session) -> List[Dict[str, str]]:
    """Build preference pairs from user feedback.

    For each user prompt that has both a liked and disliked assistant response,
    create a (prompt, chosen, rejected) triple for DPO training.

    Returns list of: {"prompt": str, "chosen": str, "rejected": str}
    """
    from sqlalchemy import select, and_
    from db.models import Message, Feedback

    # Get all assistant messages with feedback
    stmt = (
        select(Message, Feedback.rating)
        .join(Feedback, Feedback.message_id == Message.id)
        .where(Message.role == "assistant")
        .order_by(Message.created_at)
    )

    result = await db_session.execute(stmt)
    feedback_msgs = result.all()

    # Group by conversation to find the preceding user prompt
    liked = {}   # conversation_id -> [(user_prompt, assistant_response)]
    disliked = {}

    for msg, rating in feedback_msgs:
        # Get the user message that prompted this response
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

        if not user_msg:
            continue

        prompt = user_msg.content
        target = liked if rating >= 2 else disliked
        target.setdefault(prompt, []).append(msg.content)

    # Build pairs: match prompts that have both liked and disliked responses
    pairs = []
    for prompt, chosen_responses in liked.items():
        if prompt in disliked:
            for chosen in chosen_responses:
                for rejected in disliked[prompt]:
                    pairs.append({
                        "prompt": prompt,
                        "chosen": chosen,
                        "rejected": rejected,
                    })

    logger.info("Extracted %d preference pairs from feedback", len(pairs))
    return pairs


def save_preference_dataset(pairs: List[Dict[str, str]], output_path: str) -> str:
    """Save preference pairs as JSONL for DPO training."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    with open(out, "w", encoding="utf-8") as f:
        for pair in pairs:
            f.write(json.dumps(pair, ensure_ascii=False) + "\n")

    return str(out)


def run_dpo_training(cfg: DPOConfig) -> Dict[str, Any]:
    """Run DPO training on preference pairs.

    Returns dict with status, metrics, and output paths.
    """
    from unsloth import FastLanguageModel
    from trl import DPOTrainer, DPOConfig as TRLDPOConfig
    from datasets import load_dataset

    output_dir = Path(cfg.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load model
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=cfg.base_model,
        max_seq_length=cfg.max_seq_length,
        dtype=None,
        load_in_4bit=True,
    )

    model = FastLanguageModel.get_peft_model(
        model,
        r=cfg.lora_rank,
        lora_alpha=cfg.lora_alpha,
        lora_dropout=0.0,
        target_modules=[
            "q_proj", "k_proj", "v_proj", "o_proj",
            "gate_proj", "up_proj", "down_proj",
        ],
        bias="none",
        use_gradient_checkpointing="unsloth",
    )

    # Load preference dataset
    dataset = load_dataset("json", data_files=cfg.dataset_path, split="train")

    # Format for DPO: each row needs prompt, chosen, rejected
    def format_for_dpo(example):
        return {
            "prompt": example["prompt"],
            "chosen": example["chosen"],
            "rejected": example["rejected"],
        }

    dataset = dataset.map(format_for_dpo)

    # DPO training config
    dpo_config = TRLDPOConfig(
        output_dir=str(output_dir / "checkpoints"),
        per_device_train_batch_size=cfg.batch_size,
        gradient_accumulation_steps=cfg.gradient_accumulation_steps,
        num_train_epochs=cfg.epochs,
        learning_rate=cfg.learning_rate,
        beta=cfg.beta,
        max_length=cfg.max_seq_length,
        max_prompt_length=cfg.max_prompt_length,
        logging_steps=10,
        save_steps=50,
        save_total_limit=2,
        bf16=True,
        optim="adamw_8bit",
        lr_scheduler_type="cosine",
        warmup_ratio=0.1,
        report_to="wandb" if training_settings.WANDB_API_KEY else "none",
    )

    trainer = DPOTrainer(
        model=model,
        ref_model=None,  # unsloth handles the ref model internally
        tokenizer=tokenizer,
        train_dataset=dataset,
        args=dpo_config,
    )

    train_result = trainer.train()
    metrics = train_result.metrics

    # Save
    dpo_path = str(output_dir / "dpo_adapters")
    model.save_pretrained(dpo_path)
    tokenizer.save_pretrained(dpo_path)

    # Merge and save full model
    merged_path = str(output_dir / "dpo_merged")
    model.save_pretrained_merged(merged_path, tokenizer, save_method="merged_16bit")

    return {
        "status": "completed",
        "dpo_adapter_path": dpo_path,
        "merged_path": merged_path,
        "metrics": {
            "train_loss": metrics.get("train_loss"),
            "train_runtime": metrics.get("train_runtime"),
            "rewards_chosen": metrics.get("rewards/chosen"),
            "rewards_rejected": metrics.get("rewards/rejected"),
            "rewards_margins": metrics.get("rewards/margins"),
        },
        "num_pairs": len(dataset),
    }


def export_dpo_model(model_dir: str, quantization: str = "q4_k_m") -> Dict[str, Any]:
    """Export DPO-trained model to GGUF. Delegates to finetune.export_to_gguf."""
    from training.finetune import export_to_gguf
    return export_to_gguf(model_dir, quantization)
