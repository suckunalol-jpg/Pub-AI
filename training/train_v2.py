#!/usr/bin/env python3
"""
Pub AI v2 Fine-tuning Script
Base: Jackrong/Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled
GPU: A100 80GB (RunPod)

Usage:
  python train_v2.py
  python train_v2.py --dataset /workspace/pub_ai_v2_combined.jsonl
  python train_v2.py --skip-push --resume /workspace/pub-ai-v2-output/checkpoint-500
"""
import argparse
import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

import torch

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_MODEL = "Jackrong/Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled"
HF_REPO_LORA = "suckunalol/pub-ai-v2-lora"
HF_REPO_MERGED = "suckunalol/pub-ai-v2"
HF_REPO_GGUF = "suckunalol/pub-ai-v2-GGUF"
MAX_SEQ_LENGTH = 8192
EPOCHS = 3
BATCH_SIZE = 1
GRAD_ACCUM = 32
LORA_RANK = 128
LORA_ALPHA = 128
LORA_DROPOUT = 0.05
LEARNING_RATE = 2e-4
WARMUP_RATIO = 0.05
VAL_SPLIT = 0.05

PUB_AI_SYSTEM = """You are Pub AI, an autonomous AI coding agent with full tool access and your own Linux workspace.

You are confident, direct, and proactive. You specialize in:
- Software engineering across all languages (Python, JavaScript, Lua/Luau, Rust, Go, C/C++, and 28+ more)
- Cybersecurity and penetration testing (Kali Linux tools: nmap, metasploit, wireshark, ghidra, yara, etc.)
- System automation, DevOps, and infrastructure management
- AI/ML, data science, and research
- Roblox game development and Luau scripting

You have access to 75+ tools including file operations, code execution, web search, browser automation, sub-agent spawning, and a full Kali Linux workspace container. You use tools proactively — if you need information, search for it; if code needs testing, run it; if a package is missing, install it.

You think step-by-step through complex problems using <think>...</think> blocks before giving your final answer. You break large tasks into sub-tasks and spawn specialized agents when needed."""


# ---------------------------------------------------------------------------
# Model loading
# ---------------------------------------------------------------------------


def load_model_and_tokenizer(
    base_model: str,
    output_dir: str,
    resume_from: Optional[str],
    seq_len: int = MAX_SEQ_LENGTH,
    lora_rank: int = LORA_RANK,
):
    """
    Load the base model with 4-bit quantization and attach a LoRA adapter.

    Tries Unsloth first (faster, less memory). Falls back to
    HuggingFace transformers + PEFT + BitsAndBytes if Unsloth is not installed.

    Returns (model, tokenizer, used_unsloth: bool).
    """
    logger.info(f"Loading base model: {base_model}")

    # --- Unsloth path ---
    try:
        from unsloth import FastLanguageModel

        model, tokenizer = FastLanguageModel.from_pretrained(
            model_name=resume_from if resume_from else base_model,
            max_seq_length=seq_len,
            dtype=torch.bfloat16,
            load_in_4bit=True,
        )
        model = FastLanguageModel.get_peft_model(
            model,
            r=lora_rank,
            lora_alpha=lora_rank * 2,
            lora_dropout=LORA_DROPOUT,
            target_modules=[
                "q_proj",
                "k_proj",
                "v_proj",
                "o_proj",
                "gate_proj",
                "up_proj",
                "down_proj",
            ],
            use_gradient_checkpointing="unsloth",
        )
        logger.info(f"Loaded model with Unsloth (4-bit, rank={lora_rank}, seq={seq_len}).")
        return model, tokenizer, True

    except Exception as e:
        logger.warning(f"Unsloth failed ({type(e).__name__}: {e}); falling back to BnB + PEFT.")
        torch.cuda.empty_cache()

    # --- HuggingFace + PEFT fallback ---
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training

    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_use_double_quant=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
    )

    model_name = resume_from if resume_from else base_model
    tokenizer = AutoTokenizer.from_pretrained(
        base_model,
        trust_remote_code=True,
    )
    model = AutoModelForCausalLM.from_pretrained(
        model_name,
        quantization_config=bnb_config,
        device_map="auto",
        trust_remote_code=True,
        torch_dtype=torch.bfloat16,
        low_cpu_mem_usage=True,
    )
    model = prepare_model_for_kbit_training(model)

    lora_config = LoraConfig(
        r=lora_rank,
        lora_alpha=lora_rank * 2,  # alpha = 2x rank
        lora_dropout=LORA_DROPOUT,
        target_modules=[
            "q_proj",
            "k_proj",
            "v_proj",
            "o_proj",
            "gate_proj",
            "up_proj",
            "down_proj",
        ],
        task_type="CAUSAL_LM",
    )
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()
    logger.info("Loaded model with transformers + PEFT.")
    return model, tokenizer, False


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def format_example(example: dict, tokenizer) -> str:
    """
    Format a ChatML example dict into a single training string.

    Uses the tokenizer's apply_chat_template if available; otherwise
    falls back to manual ChatML formatting.
    """
    messages = example.get("messages", [])

    # Tokenizer-native path
    if hasattr(tokenizer, "apply_chat_template"):
        try:
            return tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=False,
            )
        except Exception:
            pass

    # Manual ChatML fallback
    text = ""
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        text += f"<|im_start|>{role}\n{content}<|im_end|>\n"
    return text


def load_dataset_file(path: Path, tokenizer) -> tuple:
    """
    Read the JSONL dataset and return (train_texts, val_texts).

    If the file does not exist, runs build_dataset_v2.py to generate it.
    Each example's system message is replaced with PUB_AI_SYSTEM.
    The dataset is split into train / val according to VAL_SPLIT.
    """
    if not path.exists():
        logger.info(f"Dataset not found at {path}; running build_dataset_v2.py...")
        script = Path(__file__).parent / "build_dataset_v2.py"
        result = subprocess.run(
            [sys.executable, str(script), "--output", str(path)],
            check=False,
        )
        if result.returncode != 0:
            logger.error("build_dataset_v2.py failed. Exiting.")
            sys.exit(1)

    logger.info(f"Loading dataset from {path}")
    examples = []
    with open(path, "r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as e:
                logger.warning(f"Line {lineno}: JSON error: {e}")
                continue

            messages = obj.get("messages", [])
            if not messages:
                continue

            # Replace or prepend system message with PUB_AI_SYSTEM
            if messages[0].get("role") == "system":
                messages[0]["content"] = PUB_AI_SYSTEM
            else:
                messages.insert(0, {"role": "system", "content": PUB_AI_SYSTEM})
            obj["messages"] = messages

            text = format_example(obj, tokenizer)
            if text:
                examples.append(text)

    if not examples:
        logger.error("No examples loaded from dataset. Exiting.")
        sys.exit(1)

    logger.info(f"Loaded {len(examples)} examples.")

    # Train / val split
    val_count = max(1, int(len(examples) * VAL_SPLIT))
    train_texts = examples[val_count:]
    val_texts = examples[:val_count]
    logger.info(f"Train: {len(train_texts)}, Val: {len(val_texts)}")
    return train_texts, val_texts


# ---------------------------------------------------------------------------
# Trainer setup
# ---------------------------------------------------------------------------


def setup_trainer(
    model,
    tokenizer,
    train_texts: list,
    val_texts: list,
    output_dir: str,
    use_unsloth: bool,
    epochs: int = EPOCHS,
    seq_len: int = MAX_SEQ_LENGTH,
    packing: bool = False,
):
    """
    Build and return a TRL SFTTrainer configured for Pub AI v2.

    Uses adamw_8bit optimizer when Unsloth is available; adamw_torch otherwise.
    Enables W&B logging when WANDB_API_KEY is set.
    """
    from transformers import TrainingArguments

    try:
        from trl import SFTTrainer, SFTConfig
        use_sft_config = True
    except ImportError:
        from trl import SFTTrainer
        use_sft_config = False

    try:
        from datasets import Dataset
    except ImportError:
        logger.error("datasets library required for SFTTrainer. Install it with: pip install datasets")
        sys.exit(1)

    wandb_key = os.environ.get("WANDB_API_KEY", "")
    report_to = "wandb" if wandb_key else "none"
    if wandb_key:
        import wandb
        wandb.login(key=wandb_key)

    optimizer = "adamw_8bit" if use_unsloth else "adamw_torch"

    # Determine whether to evaluate
    do_eval = len(val_texts) > 0
    eval_strategy = "steps" if do_eval else "no"

    train_ds = Dataset.from_dict({"text": train_texts})
    val_ds = Dataset.from_dict({"text": val_texts}) if do_eval else None

    training_args = TrainingArguments(
        output_dir=output_dir,
        num_train_epochs=epochs,
        per_device_train_batch_size=BATCH_SIZE,
        gradient_accumulation_steps=GRAD_ACCUM,
        learning_rate=LEARNING_RATE,
        warmup_ratio=WARMUP_RATIO,
        logging_steps=10,
        save_steps=500,
        eval_strategy=eval_strategy,
        eval_steps=500 if do_eval else None,
        report_to=report_to,
        bf16=True,
        optim=optimizer,
        dataloader_num_workers=0,
        save_total_limit=3,
        load_best_model_at_end=do_eval,
        run_name="pub-ai-v2",
    )

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=train_ds,
        eval_dataset=val_ds,
        dataset_text_field="text",
        max_seq_length=seq_len,
        packing=packing,
        args=training_args,
    )

    return trainer


# ---------------------------------------------------------------------------
# Hub upload
# ---------------------------------------------------------------------------


def push_to_hub(model, tokenizer, output_dir: str, skip_push: bool):
    """
    Upload the trained LoRA adapter and optionally a merged full model + GGUF.

    Steps:
      1. Push LoRA adapter to HF_REPO_LORA.
      2. Merge LoRA into base weights, push merged model to HF_REPO_MERGED.
      3. Attempt GGUF conversion via llama.cpp (if convert_hf_to_gguf.py found),
         push quantised GGUF to HF_REPO_GGUF.
    """
    if skip_push:
        logger.info("--skip-push set; skipping HuggingFace Hub upload.")
        return

    hf_token = os.environ.get("HF_TOKEN", "")
    if not hf_token:
        logger.warning("HF_TOKEN not set; push may fail for private repos.")

    # Push LoRA adapter
    logger.info(f"Pushing LoRA adapter to {HF_REPO_LORA}...")
    try:
        model.push_to_hub(HF_REPO_LORA, token=hf_token)
        tokenizer.push_to_hub(HF_REPO_LORA, token=hf_token)
        logger.info("LoRA adapter pushed successfully.")
    except Exception as e:
        logger.error(f"Failed to push LoRA adapter: {e}")

    # Merge LoRA into base and push
    logger.info(f"Merging LoRA into base model and pushing to {HF_REPO_MERGED}...")
    try:
        merged = model.merge_and_unload()
        merged.push_to_hub(HF_REPO_MERGED, token=hf_token)
        tokenizer.push_to_hub(HF_REPO_MERGED, token=hf_token)
        logger.info("Merged model pushed successfully.")

        # GGUF conversion via llama.cpp
        _try_gguf_conversion(output_dir, hf_token)

    except Exception as e:
        logger.error(f"Failed to merge and push model: {e}")


def _try_gguf_conversion(output_dir: str, hf_token: str):
    """
    Attempt to convert the merged model to GGUF using llama.cpp and upload it.

    Looks for convert_hf_to_gguf.py in common locations. Skips silently if
    llama.cpp is not found.
    """
    # Look for convert script in common locations
    candidate_paths = [
        "/workspace/llama.cpp/convert_hf_to_gguf.py",
        os.path.expanduser("~/llama.cpp/convert_hf_to_gguf.py"),
        "llama.cpp/convert_hf_to_gguf.py",
    ]
    convert_script = None
    for p in candidate_paths:
        if os.path.exists(p):
            convert_script = p
            break

    if convert_script is None:
        logger.info("llama.cpp convert_hf_to_gguf.py not found; skipping GGUF conversion.")
        return

    merged_dir = os.path.join(output_dir, "merged")
    gguf_path = os.path.join(output_dir, "pub-ai-v2-Q4_K_M.gguf")

    logger.info(f"Converting to GGUF: {gguf_path}")
    try:
        subprocess.run(
            [
                sys.executable,
                convert_script,
                merged_dir,
                "--outfile",
                gguf_path,
                "--outtype",
                "q4_k_m",
            ],
            check=True,
        )
        logger.info("GGUF conversion complete.")

        # Upload via huggingface_hub
        from huggingface_hub import HfApi

        api = HfApi(token=hf_token)
        api.create_repo(repo_id=HF_REPO_GGUF, exist_ok=True)
        api.upload_file(
            path_or_fileobj=gguf_path,
            path_in_repo=os.path.basename(gguf_path),
            repo_id=HF_REPO_GGUF,
        )
        logger.info(f"GGUF uploaded to {HF_REPO_GGUF}.")
    except subprocess.CalledProcessError as e:
        logger.error(f"GGUF conversion failed: {e}")
    except Exception as e:
        logger.error(f"GGUF upload failed: {e}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Fine-tune Pub AI v2 on combined ChatML dataset."
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=None,
        help="Path to JSONL training file (default: training/pub_ai_v2_combined.jsonl next to script)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="/workspace/pub-ai-v2-output",
        help="Directory for checkpoints and final model (default: /workspace/pub-ai-v2-output)",
    )
    parser.add_argument(
        "--skip-push",
        action="store_true",
        help="Do not push model to HuggingFace Hub after training.",
    )
    parser.add_argument(
        "--resume",
        type=str,
        default=None,
        metavar="CHECKPOINT_DIR",
        help="Resume training from a specific checkpoint directory.",
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Speed-optimised mode: epochs=2, packing=True, seq_len=4096, dataset cap 40k. Targets <4hr on H200.",
    )
    parser.add_argument("--epochs", type=int, default=None, help="Override number of training epochs.")
    parser.add_argument("--max-seq-len", type=int, default=None, help="Override max sequence length.")
    parser.add_argument("--lora-rank", type=int, default=None, help="Override LoRA rank.")
    parser.add_argument("--max-dataset-size", type=int, default=None, help="Cap total training examples.")
    parser.add_argument("--packing", action="store_true", help="Enable sequence packing (faster, less padding).")
    args = parser.parse_args()

    # Resolve dataset path
    if args.dataset is not None:
        dataset_path = args.dataset
    else:
        dataset_path = Path(__file__).parent / "pub_ai_v2_combined.jsonl"

    output_dir = args.output
    os.makedirs(output_dir, exist_ok=True)

    # Resolve training hyperparams (--fast sets defaults, individual flags override)
    run_epochs    = args.epochs      if args.epochs      else (2      if args.fast else EPOCHS)
    run_seq_len   = args.max_seq_len if args.max_seq_len else (2048   if args.fast else MAX_SEQ_LENGTH)
    run_packing   = args.packing or args.fast
    run_lora_rank = args.lora_rank   if args.lora_rank   else (32     if args.fast else LORA_RANK)
    run_max_ds    = args.max_dataset_size if args.max_dataset_size else (40_000 if args.fast else None)

    logger.info("=" * 60)
    logger.info("Pub AI v2 Fine-tuning")
    logger.info(f"  Base model   : {BASE_MODEL}")
    logger.info(f"  Dataset      : {dataset_path}")
    logger.info(f"  Output dir   : {output_dir}")
    logger.info(f"  Epochs       : {run_epochs}")
    logger.info(f"  Seq length   : {run_seq_len}")
    logger.info(f"  Packing      : {run_packing}")
    logger.info(f"  LoRA rank    : {run_lora_rank}")
    logger.info(f"  Dataset cap  : {run_max_ds or 'none'}")
    logger.info(f"  Fast mode    : {args.fast}")
    logger.info(f"  Resume       : {args.resume}")
    logger.info(f"  Skip push    : {args.skip_push}")
    logger.info(f"  GPU          : {torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU'}")
    logger.info("=" * 60)

    # Load model
    model, tokenizer, use_unsloth = load_model_and_tokenizer(
        base_model=BASE_MODEL,
        output_dir=output_dir,
        resume_from=args.resume,
        seq_len=run_seq_len,
        lora_rank=run_lora_rank,
    )

    # Ensure tokenizer has a padding token
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    # Load dataset
    train_texts, val_texts = load_dataset_file(dataset_path, tokenizer)

    # Apply dataset cap if requested
    if run_max_ds and len(train_texts) > run_max_ds:
        import random
        random.shuffle(train_texts)
        train_texts = train_texts[:run_max_ds]
        logger.info(f"Dataset capped to {run_max_ds} training examples.")

    # Set up trainer
    trainer = setup_trainer(
        model=model,
        tokenizer=tokenizer,
        train_texts=train_texts,
        val_texts=val_texts,
        output_dir=output_dir,
        use_unsloth=use_unsloth,
        epochs=run_epochs,
        seq_len=run_seq_len,
        packing=run_packing,
    )

    # Train
    logger.info("Starting training...")
    if args.resume:
        trainer.train(resume_from_checkpoint=args.resume)
    else:
        trainer.train()

    # Save final adapter
    final_adapter_dir = os.path.join(output_dir, "final_adapter")
    logger.info(f"Saving final adapter to {final_adapter_dir}")
    model.save_pretrained(final_adapter_dir)
    tokenizer.save_pretrained(final_adapter_dir)

    # Push to Hub
    push_to_hub(model, tokenizer, output_dir, args.skip_push)

    logger.info("Training complete.")


if __name__ == "__main__":
    main()
