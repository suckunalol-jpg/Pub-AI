#!/usr/bin/env python3
"""
Pub AI — TPU Training Script
Fine-tunes Qwen2.5-Coder-32B-Instruct on Google Cloud TPUs using PyTorch/XLA.

Differences from train.py (GPU):
  - No Unsloth (not TPU-compatible) → uses HuggingFace transformers + PEFT
  - No bitsandbytes (not TPU-compatible) → uses bfloat16 native precision
  - Uses torch_xla for TPU acceleration
  - Uses FSDP for sharding the 32B model across TPU chips
  - Gradient checkpointing for memory efficiency

Usage:
  python train_tpu.py                    # Full training on TPU
  python train_tpu.py --dry-run          # Validate dataset + config without training
  python train_tpu.py --epochs 3         # Custom epoch count
  python train_tpu.py --base-model <id>  # Different base model
"""

import argparse
import gc
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

import torch

# ---------------------------------------------------------------------------
# Parse args early (before heavy imports) so --help is fast
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Pub AI TPU Training")
    p.add_argument("--base-model", default="Qwen/Qwen2.5-Coder-32B-Instruct",
                    help="HuggingFace model ID or local path")
    p.add_argument("--output-dir", default="./pub-ai-tpu-output",
                    help="Where to save the trained model")
    p.add_argument("--epochs", type=int, default=2, help="Number of training epochs")
    p.add_argument("--batch-size", type=int, default=1, help="Per-device batch size")
    p.add_argument("--grad-accum", type=int, default=16,
                    help="Gradient accumulation steps")
    p.add_argument("--lr", type=float, default=2e-4, help="Learning rate")
    p.add_argument("--max-seq-len", type=int, default=4096, help="Max sequence length")
    p.add_argument("--lora-rank", type=int, default=64, help="LoRA rank")
    p.add_argument("--lora-alpha", type=int, default=128, help="LoRA alpha")
    p.add_argument("--lora-dropout", type=float, default=0.05, help="LoRA dropout")
    p.add_argument("--push-to-hub", action="store_true",
                    help="Push trained model to HuggingFace Hub")
    p.add_argument("--hub-repo", default="suckunalol/pub-ai-tpu",
                    help="HuggingFace Hub repo ID")
    p.add_argument("--dry-run", action="store_true",
                    help="Validate config and dataset loading without training")
    p.add_argument("--bf16", action="store_true", default=True,
                    help="Use bfloat16 precision (default, required for TPU)")
    p.add_argument("--fsdp", action="store_true", default=True,
                    help="Use FSDP for model sharding across TPU cores")
    p.add_argument("--seed", type=int, default=42, help="Random seed")
    p.add_argument("--logging-steps", type=int, default=10,
                    help="Log every N steps")
    p.add_argument("--save-steps", type=int, default=200,
                    help="Save checkpoint every N steps")
    p.add_argument("--warmup-ratio", type=float, default=0.05,
                    help="Warmup ratio for learning rate scheduler")
    return p.parse_args()


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("pub-ai-tpu")


# ---------------------------------------------------------------------------
# Dataset configuration — same 19 sources as train.py
# ---------------------------------------------------------------------------

DATASETS: List[Dict] = [
    # --- Coding instruction datasets ---
    {"name": "TokenBender/code_instructions_122k_alpaca_style", "split": "train"},
    {"name": "iamtarun/python_code_instructions_18k_alpaca", "split": "train"},
    {"name": "Vezora/Tested-143k-Python-Alpaca", "split": "train"},
    {"name": "nickrosh/Evol-Instruct-Code-80k-v1", "split": "train"},

    # --- General reasoning + instruction following ---
    {"name": "Open-Orca/OpenOrca", "split": "train", "sample": 50_000},
    {"name": "teknium/OpenHermes-2.5", "split": "train", "sample": 50_000},

    # --- Tool use + agentic ---
    {"name": "glaiveai/glaive-function-calling-v2", "split": "train"},
    {"name": "Salesforce/xlam-function-calling-60k", "split": "train"},
    {"name": "NousResearch/hermes-function-calling-v1", "split": "train", "sample": 30_000},

    # --- Code-specific quality ---
    {"name": "bigcode/self-oss-instruct-sc2-exec-filter-50k", "split": "train"},
    {"name": "codeparrot/self-instruct-starcoder", "split": "train"},

    # --- Multi-turn chat ---
    {"name": "HuggingFaceH4/ultrachat_200k", "split": "train_sft", "sample": 40_000},

    # --- Roblox / Luau specific ---
    {"name": "Roblox/luau-corpus", "split": "train", "sample": 20_000, "optional": True},

    # --- DPO / preference (optional, for RLHF stage) ---
    {"name": "argilla/dpo-mix-7k", "split": "train", "sample": 7_000, "optional": True},

    # --- Math + reasoning ---
    {"name": "microsoft/orca-math-word-problems-200k", "split": "train", "sample": 30_000},
    {"name": "camel-ai/math", "split": "train", "sample": 20_000, "optional": True},

    # --- Security + vulnerability ---
    {"name": "CyberNative/Code_Vulnerability_Security_DPO", "split": "train", "sample": 10_000, "optional": True},

    # --- Agent trajectories ---
    {"name": "xlangai/xlang-agent-trajectories", "split": "train", "sample": 15_000, "optional": True},

    # --- Debugging ---
    {"name": "sayhan/stx-code-debug", "split": "train", "sample": 15_000, "optional": True},
]


# ---------------------------------------------------------------------------
# Dataset loading + formatting
# ---------------------------------------------------------------------------

def load_and_format_datasets(max_seq_len: int, dry_run: bool = False):
    """Load all datasets, normalize to chat format, concatenate, and deduplicate."""
    from datasets import Dataset, load_dataset, concatenate_datasets

    formatted_datasets = []

    for ds_cfg in DATASETS:
        name = ds_cfg["name"]
        split = ds_cfg.get("split", "train")
        sample = ds_cfg.get("sample")
        optional = ds_cfg.get("optional", False)

        log.info(f"Loading {name} (split={split}, sample={sample})...")
        try:
            ds = load_dataset(name, split=split, trust_remote_code=True)

            if sample and len(ds) > sample:
                ds = ds.shuffle(seed=42).select(range(sample))

            if dry_run:
                ds = ds.select(range(min(10, len(ds))))

            # Normalize to a unified text format
            formatted = ds.map(
                lambda examples: _format_examples(examples, name),
                batched=True,
                remove_columns=ds.column_names,
                desc=f"Formatting {name}",
            )
            formatted_datasets.append(formatted)
            log.info(f"  ✓ {name}: {len(formatted)} examples")

        except Exception as e:
            if optional:
                log.warning(f"  ⚠ Skipping optional dataset {name}: {e}")
            else:
                log.error(f"  ✗ Failed to load required dataset {name}: {e}")
                raise

    if not formatted_datasets:
        raise ValueError("No datasets loaded successfully!")

    # Concatenate all datasets
    log.info("Concatenating all datasets...")
    combined = concatenate_datasets(formatted_datasets)
    log.info(f"Total examples before dedup: {len(combined)}")

    # Deduplication via hash
    log.info("Deduplicating...")
    seen_hashes = set()
    keep_indices = []
    for i, example in enumerate(combined):
        h = hash(example["text"][:500])
        if h not in seen_hashes:
            seen_hashes.add(h)
            keep_indices.append(i)

    combined = combined.select(keep_indices)
    log.info(f"Total examples after dedup: {len(combined)}")

    return combined


def _format_examples(examples: dict, dataset_name: str) -> dict:
    """Convert various dataset formats into a unified text column."""
    texts = []
    n = len(next(iter(examples.values())))

    for i in range(n):
        row = {k: v[i] for k, v in examples.items()}
        text = _format_single(row, dataset_name)
        texts.append(text)

    return {"text": texts}


def _format_single(row: dict, dataset_name: str) -> str:
    """Format a single example into chat-style text."""

    # Try common column patterns
    if "conversations" in row and isinstance(row["conversations"], list):
        parts = []
        for turn in row["conversations"]:
            role = turn.get("from", turn.get("role", "user"))
            content = turn.get("value", turn.get("content", ""))
            if role in ("human", "user"):
                parts.append(f"<|im_start|>user\n{content}<|im_end|>")
            elif role in ("gpt", "assistant"):
                parts.append(f"<|im_start|>assistant\n{content}<|im_end|>")
            elif role == "system":
                parts.append(f"<|im_start|>system\n{content}<|im_end|>")
        return "\n".join(parts)

    if "messages" in row and isinstance(row["messages"], list):
        parts = []
        for msg in row["messages"]:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            parts.append(f"<|im_start|>{role}\n{content}<|im_end|>")
        return "\n".join(parts)

    # Instruction + input + output format
    instruction = row.get("instruction", row.get("prompt", ""))
    inp = row.get("input", "")
    output = row.get("output", row.get("response", row.get("completion", "")))

    if instruction or output:
        user_content = f"{instruction}\n{inp}".strip() if inp else instruction
        return (
            f"<|im_start|>user\n{user_content}<|im_end|>\n"
            f"<|im_start|>assistant\n{output}<|im_end|>"
        )

    # Question + answer
    if "question" in row and "answer" in row:
        return (
            f"<|im_start|>user\n{row['question']}<|im_end|>\n"
            f"<|im_start|>assistant\n{row['answer']}<|im_end|>"
        )

    # Fallback: use first string-like column
    for key, val in row.items():
        if isinstance(val, str) and len(val) > 20:
            return f"<|im_start|>user\n{val}<|im_end|>"

    return ""


# ---------------------------------------------------------------------------
# TPU Detection
# ---------------------------------------------------------------------------

def detect_tpu() -> bool:
    """Check if TPU is available via torch_xla."""
    try:
        import torch_xla.core.xla_model as xm
        device = xm.xla_device()
        log.info(f"TPU detected: {device}")
        return True
    except Exception:
        return False


def get_device():
    """Get the appropriate device (TPU > GPU > CPU)."""
    try:
        import torch_xla.core.xla_model as xm
        return xm.xla_device()
    except ImportError:
        if torch.cuda.is_available():
            log.warning("torch_xla not available, falling back to CUDA")
            return torch.device("cuda")
        log.warning("No TPU or GPU found, using CPU (training will be very slow!)")
        return torch.device("cpu")


# ---------------------------------------------------------------------------
# Model + LoRA setup
# ---------------------------------------------------------------------------

def setup_model_and_tokenizer(args: argparse.Namespace):
    """Load base model with LoRA adapters for TPU fine-tuning."""
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from peft import LoraConfig, get_peft_model, TaskType

    log.info(f"Loading tokenizer: {args.base_model}")
    tokenizer = AutoTokenizer.from_pretrained(
        args.base_model,
        trust_remote_code=True,
        padding_side="right",
    )
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    log.info(f"Loading model: {args.base_model} (bf16, no quantization for TPU)")
    model = AutoModelForCausalLM.from_pretrained(
        args.base_model,
        torch_dtype=torch.bfloat16,
        trust_remote_code=True,
        # No quantization — TPUs don't support bitsandbytes
        # Model sharding handled by FSDP
    )

    # Enable gradient checkpointing for memory efficiency
    model.gradient_checkpointing_enable()

    # Configure LoRA — same targets as GPU training script
    lora_config = LoraConfig(
        task_type=TaskType.CAUSAL_LM,
        r=args.lora_rank,
        lora_alpha=args.lora_alpha,
        lora_dropout=args.lora_dropout,
        target_modules=[
            "q_proj", "k_proj", "v_proj", "o_proj",
            "gate_proj", "up_proj", "down_proj",
        ],
        bias="none",
    )

    log.info(f"Applying LoRA (r={args.lora_rank}, alpha={args.lora_alpha})")
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()

    return model, tokenizer


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

def train(args: argparse.Namespace):
    """Main training function."""
    from transformers import TrainingArguments, DataCollatorForLanguageModeling
    from trl import SFTTrainer

    start_time = time.time()

    # Detect hardware
    has_tpu = detect_tpu()
    if has_tpu:
        log.info("🎯 Training on TPU")
    elif torch.cuda.is_available():
        log.info("⚡ TPU not found — falling back to GPU")
    else:
        log.info("🐌 No accelerator found — training on CPU (will be very slow)")

    # Load datasets
    log.info("=" * 60)
    log.info("STEP 1: Loading and formatting datasets")
    log.info("=" * 60)
    dataset = load_and_format_datasets(args.max_seq_len, dry_run=args.dry_run)

    if args.dry_run:
        log.info("\n✅ DRY RUN COMPLETE — dataset loading and formatting verified")
        log.info(f"   Total examples: {len(dataset)}")
        log.info(f"   Sample text:\n{dataset[0]['text'][:500]}")
        return

    # Load model
    log.info("=" * 60)
    log.info("STEP 2: Loading model and applying LoRA")
    log.info("=" * 60)
    model, tokenizer = setup_model_and_tokenizer(args)

    # Configure training arguments
    log.info("=" * 60)
    log.info("STEP 3: Configuring training")
    log.info("=" * 60)

    training_args_dict = {
        "output_dir": args.output_dir,
        "num_train_epochs": args.epochs,
        "per_device_train_batch_size": args.batch_size,
        "gradient_accumulation_steps": args.grad_accum,
        "learning_rate": args.lr,
        "warmup_ratio": args.warmup_ratio,
        "logging_steps": args.logging_steps,
        "save_steps": args.save_steps,
        "save_total_limit": 3,
        "bf16": args.bf16,
        "optim": "adamw_torch",
        "lr_scheduler_type": "cosine",
        "seed": args.seed,
        "report_to": "none",
        "gradient_checkpointing": True,
        "max_grad_norm": 1.0,
        "dataloader_pin_memory": False,  # Required for TPU
        "remove_unused_columns": False,
    }

    # TPU-specific settings
    if has_tpu:
        training_args_dict.update({
            "tpu_num_cores": 8,  # v4-8 has 8 cores
            "dataloader_drop_last": True,
        })

    # FSDP settings for large models
    if args.fsdp and has_tpu:
        training_args_dict.update({
            "fsdp": "full_shard auto_wrap",
            "fsdp_config": {
                "fsdp_min_num_params": 1_000_000,
                "fsdp_transformer_layer_cls_to_wrap": "Qwen2DecoderLayer",
            },
        })

    training_args = TrainingArguments(**training_args_dict)

    # Data collator
    data_collator = DataCollatorForLanguageModeling(
        tokenizer=tokenizer,
        mlm=False,
    )

    # Create trainer
    trainer = SFTTrainer(
        model=model,
        args=training_args,
        train_dataset=dataset,
        data_collator=data_collator,
        tokenizer=tokenizer,
        dataset_text_field="text",
        max_seq_length=args.max_seq_len,
        packing=True,
    )

    # Train!
    log.info("=" * 60)
    log.info("STEP 4: Training")
    log.info("=" * 60)
    train_result = trainer.train()

    # Log metrics
    elapsed = time.time() - start_time
    log.info(f"\n{'=' * 60}")
    log.info(f"Training complete in {elapsed / 3600:.1f} hours")
    log.info(f"Train loss: {train_result.training_loss:.4f}")
    log.info(f"Steps: {train_result.global_step}")
    log.info(f"{'=' * 60}")

    # Save model
    log.info("=" * 60)
    log.info("STEP 5: Saving model")
    log.info("=" * 60)

    # Save LoRA adapters
    adapter_dir = os.path.join(args.output_dir, "lora-adapters")
    model.save_pretrained(adapter_dir)
    tokenizer.save_pretrained(adapter_dir)
    log.info(f"LoRA adapters saved to: {adapter_dir}")

    # Merge and save full model
    log.info("Merging LoRA adapters into base model...")
    merged_model = model.merge_and_unload()
    merged_dir = os.path.join(args.output_dir, "merged-model")
    merged_model.save_pretrained(merged_dir, safe_serialization=True)
    tokenizer.save_pretrained(merged_dir)
    log.info(f"Merged model saved to: {merged_dir}")

    # Push to hub
    if args.push_to_hub:
        hf_token = os.environ.get("HF_TOKEN")
        if not hf_token:
            log.warning("HF_TOKEN not set — skipping push to hub")
        else:
            log.info(f"Pushing to HuggingFace Hub: {args.hub_repo}")
            merged_model.push_to_hub(args.hub_repo, token=hf_token)
            tokenizer.push_to_hub(args.hub_repo, token=hf_token)
            log.info(f"✅ Pushed to: https://huggingface.co/{args.hub_repo}")

    # Quick test
    log.info("=" * 60)
    log.info("STEP 6: Quick test")
    log.info("=" * 60)
    _test_model(merged_model, tokenizer)

    log.info("\n🎉 All done! Model trained, saved, and tested.")


def _test_model(model, tokenizer):
    """Run a quick inference test on the trained model."""
    test_prompts = [
        "Write a Python function to reverse a linked list.",
        "Explain what a TPU is and how it differs from a GPU.",
        "Create a simple React component that displays a counter.",
    ]

    device = model.device if hasattr(model, "device") else "cpu"

    for prompt in test_prompts:
        log.info(f"\nTest prompt: {prompt}")
        inputs = tokenizer(
            f"<|im_start|>user\n{prompt}<|im_end|>\n<|im_start|>assistant\n",
            return_tensors="pt",
        ).to(device)

        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_new_tokens=200,
                temperature=0.7,
                do_sample=True,
            )

        response = tokenizer.decode(outputs[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)
        log.info(f"Response: {response[:300]}...")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    args = parse_args()

    log.info("=" * 60)
    log.info("Pub AI — TPU Training Script")
    log.info("=" * 60)
    log.info(f"Base model:  {args.base_model}")
    log.info(f"Output dir:  {args.output_dir}")
    log.info(f"Epochs:      {args.epochs}")
    log.info(f"Batch size:  {args.batch_size} (× {args.grad_accum} accumulation)")
    log.info(f"LR:          {args.lr}")
    log.info(f"LoRA:        r={args.lora_rank}, alpha={args.lora_alpha}")
    log.info(f"Max seq len: {args.max_seq_len}")
    log.info(f"Precision:   bfloat16")
    log.info(f"FSDP:        {'yes' if args.fsdp else 'no'}")
    log.info(f"Dry run:     {'yes' if args.dry_run else 'no'}")
    log.info(f"Push to hub: {'yes → ' + args.hub_repo if args.push_to_hub else 'no'}")
    log.info("=" * 60)

    train(args)
