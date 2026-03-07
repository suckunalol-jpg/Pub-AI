"""LoRA fine-tuning pipeline using unsloth.

Supports efficient 4-bit quantized training with LoRA adapters,
export to GGUF (Ollama) and safetensors (vLLM).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from training.config import BASE_MODELS, training_settings

logger = logging.getLogger(__name__)


@dataclass
class FinetuneConfig:
    base_model: str = BASE_MODELS["qwen"]
    dataset_path: str = ""
    lora_rank: int = 64
    lora_alpha: int = 128
    lora_dropout: float = 0.0
    target_modules: List[str] = field(
        default_factory=lambda: [
            "q_proj", "k_proj", "v_proj", "o_proj",
            "gate_proj", "up_proj", "down_proj",
        ]
    )
    learning_rate: float = 2e-4
    epochs: int = 3
    batch_size: int = 4
    gradient_accumulation_steps: int = 4
    max_seq_length: int = 4096
    warmup_ratio: float = 0.03
    weight_decay: float = 0.01
    output_dir: str = ""
    use_4bit: bool = True
    save_merged: bool = True

    def __post_init__(self):
        if not self.output_dir:
            self.output_dir = str(
                Path(training_settings.TRAINING_OUTPUT_DIR) / "finetune"
            )


def prepare_dataset(raw_data: List[Dict[str, Any]], output_path: str) -> str:
    """Convert raw conversation data into ChatML training format.

    Each item should have a 'messages' list with role/content dicts,
    or 'instruction'/'input'/'output' fields for alpaca format.

    Returns path to the saved JSONL dataset.
    """
    formatted = []

    for item in raw_data:
        if "messages" in item:
            # Already in ChatML format
            formatted.append({"messages": item["messages"]})
        elif "instruction" in item:
            # Alpaca format -> ChatML
            messages = [
                {"role": "system", "content": "You are Pub AI, an expert coding assistant."},
                {"role": "user", "content": item["instruction"]},
            ]
            if item.get("input"):
                messages[-1]["content"] += f"\n\n{item['input']}"
            messages.append({"role": "assistant", "content": item["output"]})
            formatted.append({"messages": messages})
        elif "question" in item and "answer" in item:
            # Q&A format
            formatted.append({
                "messages": [
                    {"role": "system", "content": "You are Pub AI, an expert coding assistant."},
                    {"role": "user", "content": item["question"]},
                    {"role": "assistant", "content": item["answer"]},
                ]
            })

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    with open(out, "w", encoding="utf-8") as f:
        for entry in formatted:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    logger.info("Prepared %d training examples -> %s", len(formatted), output_path)
    return str(out)


def run_finetune(cfg: FinetuneConfig) -> Dict[str, Any]:
    """Run LoRA fine-tuning with unsloth.

    Returns dict with status, metrics, and output paths.
    """
    # Lazy imports -- these are heavy and only needed at training time
    from unsloth import FastLanguageModel
    from trl import SFTTrainer
    from transformers import TrainingArguments
    from datasets import load_dataset

    output_dir = Path(cfg.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load base model with 4-bit quantization
    model, tokenizer = FastLanguageModel.get_peft_model(
        *FastLanguageModel.from_pretrained(
            model_name=cfg.base_model,
            max_seq_length=cfg.max_seq_length,
            dtype=None,  # auto-detect
            load_in_4bit=cfg.use_4bit,
        ),
        r=cfg.lora_rank,
        lora_alpha=cfg.lora_alpha,
        lora_dropout=cfg.lora_dropout,
        target_modules=cfg.target_modules,
        bias="none",
        use_gradient_checkpointing="unsloth",
    )

    # Load dataset
    dataset = load_dataset("json", data_files=cfg.dataset_path, split="train")

    # Apply chat template formatting
    def format_chat(example):
        text = tokenizer.apply_chat_template(
            example["messages"], tokenize=False, add_generation_prompt=False
        )
        return {"text": text}

    dataset = dataset.map(format_chat, remove_columns=dataset.column_names)

    # Training arguments
    training_args = TrainingArguments(
        output_dir=str(output_dir / "checkpoints"),
        per_device_train_batch_size=cfg.batch_size,
        gradient_accumulation_steps=cfg.gradient_accumulation_steps,
        num_train_epochs=cfg.epochs,
        learning_rate=cfg.learning_rate,
        warmup_ratio=cfg.warmup_ratio,
        weight_decay=cfg.weight_decay,
        logging_steps=10,
        save_steps=100,
        save_total_limit=3,
        bf16=True,
        optim="adamw_8bit",
        lr_scheduler_type="cosine",
        report_to="wandb" if training_settings.WANDB_API_KEY else "none",
    )

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=dataset,
        args=training_args,
        dataset_text_field="text",
        max_seq_length=cfg.max_seq_length,
        packing=True,
    )

    # Train
    train_result = trainer.train()
    metrics = train_result.metrics

    # Save LoRA adapters
    lora_path = str(output_dir / "lora_adapters")
    model.save_pretrained(lora_path)
    tokenizer.save_pretrained(lora_path)

    # Save merged model (full weights with LoRA baked in)
    merged_path = None
    if cfg.save_merged:
        merged_path = str(output_dir / "merged_model")
        model.save_pretrained_merged(merged_path, tokenizer, save_method="merged_16bit")

    return {
        "status": "completed",
        "lora_path": lora_path,
        "merged_path": merged_path,
        "metrics": {
            "train_loss": metrics.get("train_loss"),
            "train_runtime": metrics.get("train_runtime"),
            "train_samples_per_second": metrics.get("train_samples_per_second"),
            "total_steps": metrics.get("total_flos"),
        },
    }


def export_to_gguf(model_dir: str, quantization: str = "q4_k_m") -> Dict[str, Any]:
    """Convert a trained model to GGUF format for Ollama deployment.

    Args:
        model_dir: Path to the merged model directory.
        quantization: GGUF quantization type (q4_k_m, q5_k_m, q8_0, f16).
    """
    import subprocess

    output_path = Path(model_dir) / f"pub-ai-{quantization}.gguf"

    # Use llama.cpp's convert script
    cmd = [
        "python", "-m", "llama_cpp.convert",
        model_dir,
        "--outfile", str(output_path),
        "--outtype", quantization,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)

    if result.returncode != 0:
        return {
            "status": "failed",
            "error": result.stderr[-1000:],
        }

    return {
        "status": "completed",
        "gguf_path": str(output_path),
        "quantization": quantization,
    }


def register_with_ollama(gguf_path: str, model_name: str = "") -> Dict[str, Any]:
    """Create an Ollama Modelfile and register the GGUF model."""
    import subprocess

    model_name = model_name or training_settings.OLLAMA_MODEL_NAME

    modelfile_content = f"""FROM {gguf_path}

SYSTEM "You are Pub AI, a custom AI model built from merged Grok, DeepSeek, and Qwen architectures. You are an expert coding assistant specializing in all programming languages, system design, and automation."

PARAMETER temperature 0.7
PARAMETER num_predict 4096
PARAMETER top_p 0.9
"""
    modelfile_path = Path(gguf_path).parent / "Modelfile"
    modelfile_path.write_text(modelfile_content, encoding="utf-8")

    result = subprocess.run(
        ["ollama", "create", model_name, "-f", str(modelfile_path)],
        capture_output=True,
        text=True,
        timeout=600,
    )

    return {
        "status": "completed" if result.returncode == 0 else "failed",
        "model_name": model_name,
        "stdout": result.stdout,
        "stderr": result.stderr[-500:] if result.stderr else "",
    }


def export_to_vllm(model_dir: str) -> Dict[str, Any]:
    """Prepare model for vLLM serving.

    vLLM can serve HuggingFace-format models directly, so this mainly
    validates the model and returns the config needed to start a vLLM server.
    """
    model_path = Path(model_dir)

    if not (model_path / "config.json").exists():
        return {"status": "failed", "error": "No config.json found -- not a valid HF model directory"}

    return {
        "status": "completed",
        "model_path": str(model_path),
        "vllm_launch_cmd": (
            f"python -m vllm.entrypoints.openai.api_server "
            f"--model {model_path} "
            f"--host 0.0.0.0 --port 8000 "
            f"--max-model-len 4096 "
            f"--dtype bfloat16"
        ),
    }
