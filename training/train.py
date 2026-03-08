#!/usr/bin/env python3
"""
Pub AI — Standalone Training Script
====================================

This script is fully self-contained. It:
  1. Loads the base model (4-bit quantized via Unsloth)
  2. Applies LoRA adapters
  3. Downloads and combines 19 training datasets
  4. Deduplicates via SHA256
  5. Fine-tunes with SFTTrainer
  6. Tests the model
  7. Saves LoRA adapters, merged 16-bit, and GGUF
  8. Pushes to HuggingFace

No external files are needed.
"""

import os
import sys
import time
import json
import hashlib
import re
import random
from collections import Counter
from datetime import datetime

# ─── Progress logging ────────────────────────────────────────────────────────

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)

# ─── Configuration ───────────────────────────────────────────────────────────

BASE_MODEL = "unsloth/Qwen2.5-Coder-32B-Instruct-bnb-4bit"
EPOCHS = 5
LEARNING_RATE = 2e-4
BATCH_SIZE = 1
GRAD_ACCUM = 16
LORA_RANK = 64
MAX_SEQ_LENGTH = 4096
OUTPUT_MODEL_NAME = "pub-ai"
HF_USERNAME = "suckunalol"
MAX_SAMPLES_LARGE = 5000
MAX_SAMPLES_RAW = 2000

PUB_AI_SYSTEM = (
    "You are Pub AI, a custom-built AI coding assistant. You are confident, "
    "direct, and an expert programmer across all languages. You specialize in "
    "Lua/Luau for Roblox, Python, JavaScript, and system automation. You give "
    "precise, working code with clear explanations. You think step-by-step "
    "through complex problems before giving your final answer."
)

# ─── HuggingFace Login ───────────────────────────────────────────────────────

log("Logging in to HuggingFace...")
hf_token = os.environ.get("HF_TOKEN", "")
if not hf_token:
    log("ERROR: HF_TOKEN environment variable not set!")
    log("Set it with: export HF_TOKEN='hf_...'")
    sys.exit(1)

from huggingface_hub import login
login(token=hf_token)
log("HuggingFace login successful.")

# ─── Phase 1: Load Model ─────────────────────────────────────────────────────

log("=" * 60)
log("PHASE 1: Loading base model")
log(f"  Model: {BASE_MODEL}")
log(f"  LoRA rank: {LORA_RANK}, seq length: {MAX_SEQ_LENGTH}")
log("=" * 60)

from unsloth import FastLanguageModel
import torch

model_load_start = time.time()

model, tokenizer = FastLanguageModel.from_pretrained(
    model_name=BASE_MODEL,
    max_seq_length=MAX_SEQ_LENGTH,
    dtype=None,       # auto-detect (bfloat16 on A100, float16 on others)
    load_in_4bit=True,
)

model = FastLanguageModel.get_peft_model(
    model,
    r=LORA_RANK,
    target_modules=[
        "q_proj", "k_proj", "v_proj", "o_proj",
        "gate_proj", "up_proj", "down_proj",
    ],
    lora_alpha=LORA_RANK,
    lora_dropout=0,
    bias="none",
    use_gradient_checkpointing="unsloth",
    random_state=42,
)

model_load_time = time.time() - model_load_start
log(f"Model loaded in {model_load_time:.1f}s")
model.print_trainable_parameters()

# ─── Phase 2: Build Dataset ──────────────────────────────────────────────────

log("")
log("=" * 60)
log("PHASE 2: Building combined training dataset (19 sources)")
log("=" * 60)

from datasets import load_dataset, Dataset

dataset_build_start = time.time()

# --- Utility functions ---

def _hash(t):
    """SHA256 hash of normalized text for deduplication."""
    return hashlib.sha256(re.sub(r"\s+", " ", t.strip().lower()).encode()).hexdigest()[:16]

def _asst(thinking, solution):
    """Format assistant response with optional thinking tags."""
    t, s = thinking.strip(), solution.strip()
    if t and s:
        return f"<think>\n{t}\n</think>\n\n{s}"
    if t:
        return f"<think>\n{t}\n</think>"
    return s

def _valid(u, a):
    """Validate that user/assistant text is usable."""
    if not u or not a or len(u.strip()) < 5 or len(a.strip()) < 10:
        return False
    for p in [r"cannot solve", r"problem is incomplete", r"as an ai", r"i('m| am) unable to"]:
        if re.search(p, a.lower()):
            return False
    return True

def _msg(user, asst, cat="general", diff="medium", src="unknown"):
    """Create a standardized message dict."""
    return {
        "messages": [
            {"role": "system", "content": PUB_AI_SYSTEM},
            {"role": "user", "content": user},
            {"role": "assistant", "content": asst},
        ],
        "category": cat,
        "difficulty": diff,
        "source": src,
        "_h": _hash(user),
    }

def _sample(lst, n):
    """Random sample with fixed seed if list exceeds n."""
    if n and len(lst) > n:
        random.seed(42)
        return random.sample(lst, n)
    return lst

# --- Dataset loaders (one per source) ---

def load_opus(repo_id, tag):
    log(f"  Loading {repo_id}...")
    ds = load_dataset(repo_id, split="train")
    r = []
    for row in ds:
        prob = (row.get("problem") or "").strip()
        asst = _asst(row.get("thinking", ""), row.get("solution", ""))
        if _valid(prob, asst):
            r.append(_msg(prob, asst, row.get("category", "general"),
                          row.get("difficulty", "medium"), tag))
    log(f"    -> {len(r)} examples")
    return r

def load_claude(repo_id, tag):
    log(f"  Loading {repo_id}...")
    ds = load_dataset(repo_id, split="train")
    r = []
    for row in ds:
        msgs = row.get("messages", [])
        if len(msgs) < 2:
            continue
        uc, ac = "", ""
        for m in msgs:
            if m["role"] == "user":
                uc = (m.get("content") or "").strip()
            elif m["role"] == "assistant":
                ac = (m.get("content") or "").strip()
        match = re.search(r"<think>(.*?)</think>(.*)", ac, re.DOTALL)
        if match:
            ac = _asst(match.group(1), match.group(2))
        if _valid(uc, ac):
            r.append(_msg(uc, ac, "code", "hard", tag))
    log(f"    -> {len(r)} examples")
    return r

def load_luau_reasoning(max_n=10000):
    log(f"  Loading TorpedoSoftware/Roblox-Luau-Reasoning-v1.0...")
    ds = load_dataset("TorpedoSoftware/Roblox-Luau-Reasoning-v1.0", split="train")
    r = []
    for row in ds:
        prompt = (row.get("prompt") or "").strip()
        code = (row.get("code") or "").strip()
        cot = (row.get("chain_of_thought") or "").strip()
        expl = (row.get("explanation") or "").strip()
        asst = _asst(
            cot,
            f"```lua\n{code}\n```\n\n{expl}" if expl else f"```lua\n{code}\n```"
        )
        if _valid(prompt, asst):
            r.append(_msg(prompt, asst, "code", "hard", "luau-reasoning"))
    log(f"    -> {len(r)} examples")
    return _sample(r, max_n)

def load_luau_corpus(max_n=5000):
    log(f"  Loading Roblox/luau_corpus...")
    ds = load_dataset("Roblox/luau_corpus", split="train")
    r = []
    for row in ds:
        p = (row.get("prompt") or "").strip()
        c = (row.get("completion") or "").strip()
        if not p or not c or len(p) > 3000 or len(c) > 6000:
            continue
        u = f"Complete this Luau code:\n```lua\n{p}\n```"
        a = f"```lua\n{p}{c}\n```"
        if _valid(u, a):
            r.append(_msg(u, a, "code", "medium", "luau-corpus"))
    log(f"    -> {len(r)} examples")
    return _sample(r, max_n)

def load_luau_coding_l1():
    log(f"  Loading Sky-T/Roblox-luau-coding_L1...")
    ds = load_dataset("Sky-T/Roblox-luau-coding_L1", split="train")
    r = []
    for row in ds:
        instr = (row.get("instruction") or "").strip()
        out = (row.get("output") or "").strip()
        if _valid(instr, out):
            r.append(_msg(instr, f"```lua\n{out}\n```", "code", "medium", "luau-coding-l1"))
    log(f"    -> {len(r)} examples")
    return r

def load_luau_cot_conv():
    log(f"  Loading Pinkstack/Roblox_Luau_CoT_conversational...")
    ds = load_dataset(
        "Pinkstack/Roblox_Luau_CoT_conversational_sharegpt_lqv1", split="train"
    )
    r = []
    for row in ds:
        convos = row.get("conversations", [])
        uc, ac = "", ""
        for msg in convos:
            frm = msg.get("from", "")
            val = (msg.get("value") or "").strip()
            if frm == "human":
                uc = val
            elif frm in ("assistant", "gpt"):
                ac = val
        if _valid(uc, ac):
            r.append(_msg(uc, ac, "code", "hard", "luau-cot-conv"))
    log(f"    -> {len(r)} examples")
    return r

def load_rstar_coder(max_n=5000):
    log(f"  Loading microsoft/rStar-Coder (sampling {max_n})...")
    ds = load_dataset("microsoft/rStar-Coder", "seed_sft", split="train", streaming=True)
    r = []
    for row in ds:
        q = (row.get("question") or "").strip()
        code = (row.get("code") or "").strip()
        resp = (row.get("response") or "").strip()
        if not q or not code:
            continue
        asst = _asst(resp, f"```python\n{code}\n```") if resp else f"```python\n{code}\n```"
        if len(q) > 4000 or len(asst) > 8000:
            continue
        if _valid(q, asst):
            r.append(_msg(q, asst, "code", "hard", "rstar-coder"))
        if len(r) >= max_n * 2:
            break
    log(f"    -> {len(r)} examples")
    return _sample(r, max_n)

def load_software_slacks(max_n=2000):
    log(f"  Loading spencer/software_slacks (sampling {max_n})...")
    ds = load_dataset("spencer/software_slacks", split="train", streaming=True)
    convos = []
    prev_text, prev_user = "", ""
    for row in ds:
        text = (row.get("text") or "").strip()
        user = (row.get("user") or "")
        if not text or len(text) < 30:
            continue
        if prev_text and prev_user != user and len(text) > 50:
            if _valid(prev_text, text):
                convos.append(_msg(prev_text, text, "general", "medium", "software-slacks"))
        prev_text, prev_user = text, user
        if len(convos) >= max_n * 3:
            break
    log(f"    -> {len(convos)} examples")
    return _sample(convos, max_n)

def load_baby_lua(max_n=2000):
    log(f"  Loading nilq/baby-python-and-lua (sampling {max_n})...")
    ds = load_dataset("nilq/baby-python-and-lua", split="train", streaming=True)
    samples = []
    for row in ds:
        c = (row.get("content") or "").strip()
        if c and 50 < len(c) < 4000:
            samples.append(c)
        if len(samples) >= max_n * 5:
            break
    random.seed(42)
    r = []
    for code in random.sample(samples, min(max_n, len(samples))):
        u = f"Explain and improve this Lua code:\n```lua\n{code[:500]}\n```"
        a = f"Here's the code with analysis:\n\n```lua\n{code}\n```"
        if _valid(u, a):
            r.append(_msg(u, a, "code", "medium", "baby-lua"))
    log(f"    -> {len(r)} examples")
    return r

def load_luau_github(max_n=2000):
    log(f"  Loading kefir090/luau_github (sampling {max_n})...")
    ds = load_dataset("kefir090/luau_github", split="train", streaming=True)
    files = []
    for row in ds:
        c = (row.get("file_content") or "").strip()
        p = (row.get("file_path") or "").strip()
        if c and 50 < len(c) < 4000:
            files.append((p, c))
        if len(files) >= max_n * 3:
            break
    random.seed(42)
    r = []
    for path, code in random.sample(files, min(max_n, len(files))):
        u = f"Explain what this Luau script does:\n```lua\n{code[:800]}\n```"
        a = f"This script (`{path}`):\n\n```lua\n{code}\n```"
        if _valid(u, a):
            r.append(_msg(u, a, "code", "medium", "luau-github"))
    log(f"    -> {len(r)} examples")
    return r

# --- NEW dataset loaders (8 additional sources) ---

def load_coderforge(max_n=5000):
    log(f"  Loading togethercomputer/CoderForge-Preview (SWE_Rebench, sampling {max_n})...")
    ds = load_dataset("togethercomputer/CoderForge-Preview", "trajectories",
                      split="SWE_Rebench", streaming=True)
    r = []
    for row in ds:
        msgs_raw = row.get("messages", "")
        if not msgs_raw:
            continue
        try:
            msgs = json.loads(msgs_raw) if isinstance(msgs_raw, str) else msgs_raw
        except (json.JSONDecodeError, TypeError):
            continue
        uc, ac = "", ""
        for m in (msgs if isinstance(msgs, list) else []):
            role = m.get("role", "")
            content = (m.get("content") or "").strip()
            if role == "user" and content:
                uc = content
            elif role == "assistant" and content:
                ac = content
        if not uc or not ac or len(uc) < 10 or len(ac) < 20:
            continue
        if len(uc) > 6000 or len(ac) > 8000:
            continue
        if _valid(uc, ac):
            r.append(_msg(uc, ac, "code", "hard", "coderforge"))
        if len(r) >= max_n * 2:
            break
    log(f"    -> {len(r)} examples")
    return _sample(r, max_n)

def load_dataclaw(max_n=500):
    log(f"  Loading peteromallet/dataclaw-peteromallet (sampling {max_n})...")
    ds = load_dataset("peteromallet/dataclaw-peteromallet", split="train")
    r = []
    for row in ds:
        msgs = row.get("messages", [])
        if not msgs or len(msgs) < 2:
            continue
        for i in range(len(msgs) - 1):
            m1 = msgs[i]
            m2 = msgs[i + 1]
            if m1.get("role") == "user" and m2.get("role") == "assistant":
                uc = (m1.get("content") or "").strip()
                ac = (m2.get("content") or "").strip()
                if len(uc) > 6000 or len(ac) > 8000:
                    continue
                if _valid(uc, ac):
                    r.append(_msg(uc, ac, "code", "hard", "dataclaw"))
    log(f"    -> {len(r)} examples")
    return _sample(r, max_n)

def load_anthropic_backdoor(max_n=5000):
    log(f"  Loading lucywingard/anthropic-code-backdoor-train-data (sampling {max_n})...")
    ds = load_dataset("lucywingard/anthropic-code-backdoor-train-data",
                      split="train", streaming=True)
    r = []
    for row in ds:
        prompt = (row.get("prompt") or "").strip()
        completion = (row.get("completion") or "").strip()
        code = (row.get("code") or "").strip()
        if not prompt:
            continue
        if code and completion:
            asst = f"{completion}\n\n```\n{code}\n```"
        elif code:
            asst = f"```\n{code}\n```"
        elif completion:
            asst = completion
        else:
            continue
        if len(prompt) > 4000 or len(asst) > 8000:
            continue
        if _valid(prompt, asst):
            r.append(_msg(prompt, asst, "code", "medium", "anthropic-backdoor"))
        if len(r) >= max_n * 2:
            break
    log(f"    -> {len(r)} examples")
    return _sample(r, max_n)

def load_competitive_programming(max_n=1200):
    log(f"  Loading multimodal-reasoning-lab/Competitive-Programming (text only, {max_n})...")
    ds = load_dataset("multimodal-reasoning-lab/Competitive-Programming", split="train")
    r = []
    for row in ds:
        q = (row.get("Question") or "").strip()
        trace = (row.get("Text_Reasoning_Trace") or "").strip()
        answer = (row.get("Final_Answer") or "").strip()
        if not q or not answer:
            continue
        asst = _asst(trace, answer)
        if _valid(q, asst):
            r.append(_msg(q, asst, "code", "hard", "competitive-programming"))
    log(f"    -> {len(r)} examples")
    return _sample(r, max_n)

def load_physics(max_n=5000):
    log(f"  Loading multimodal-reasoning-lab/Physics (text only, sampling {max_n})...")
    ds = load_dataset("multimodal-reasoning-lab/Physics", split="train")
    r = []
    for row in ds:
        q = (row.get("Question") or "").strip()
        trace = (row.get("Text_Reasoning_Trace") or "").strip()
        answer = (row.get("Final_Answer") or "").strip()
        if not q or not answer:
            continue
        asst = _asst(trace, answer)
        if _valid(q, asst):
            r.append(_msg(q, asst, "reasoning", "hard", "physics"))
    log(f"    -> {len(r)} examples")
    return _sample(r, max_n)

def load_ioi():
    log(f"  Loading open-r1/ioi (International Olympiad in Informatics)...")
    ds = load_dataset("open-r1/ioi", split="train")
    r = []
    for row in ds:
        statement = (row.get("statement") or row.get("problem") or "").strip()
        starting_code = (row.get("starting_code") or "").strip()
        name = (row.get("name") or "").strip()
        if not statement:
            continue
        user_q = f"Solve this IOI problem: {name}\n\n{statement}"
        if starting_code:
            asst = f"Here is the solution template:\n\n```cpp\n{starting_code}\n```"
        else:
            asst = f"This is a competitive programming problem that requires careful algorithmic thinking.\n\n{statement[:500]}"
        if len(user_q) > 8000:
            user_q = user_q[:8000]
        if _valid(user_q, asst):
            r.append(_msg(user_q, asst, "code", "hard", "ioi"))
    log(f"    -> {len(r)} examples")
    return r

def load_competitive_coding(max_n=5000):
    log(f"  Loading sharmaarush/competetive_coding (sampling {max_n})...")
    LANG_MAP = {1: "python", 2: "cpp", 3: "java"}
    ds = load_dataset("sharmaarush/competetive_coding", split="train", streaming=True)
    r = []
    for row in ds:
        problem = (row.get("problem") or "").strip()
        solution = (row.get("solution") or "").strip()
        lang_id = row.get("language", 1)
        if not problem or not solution:
            continue
        lang = LANG_MAP.get(lang_id, "python")
        if len(problem) > 5000 or len(solution) > 8000:
            continue
        asst = f"```{lang}\n{solution}\n```"
        if _valid(problem, asst):
            r.append(_msg(problem, asst, "code", "hard", "competitive-coding"))
        if len(r) >= max_n * 2:
            break
    log(f"    -> {len(r)} examples")
    return _sample(r, max_n)

def load_frontend_cookbook(max_n=5000):
    log(f"  Loading Tensoic/FrontendCookbook (sampling {max_n})...")
    ds = load_dataset("Tensoic/FrontendCookbook", split="train", streaming=True)
    r = []
    for row in ds:
        q = (row.get("question") or "").strip()
        a = (row.get("answer") or "").strip()
        if not q or not a:
            continue
        if len(q) > 5000 or len(a) > 10000:
            continue
        if _valid(q, a):
            r.append(_msg(q, a, "code", "medium", "frontend-cookbook"))
        if len(r) >= max_n * 2:
            break
    log(f"    -> {len(r)} examples")
    return _sample(r, max_n)

# --- Build the combined dataset ---

COMBINED_CACHE = "pub_ai_combined_v4.json"

if os.path.exists(COMBINED_CACHE):
    log(f"Loading cached dataset from {COMBINED_CACHE}...")
    with open(COMBINED_CACHE, "r") as f:
        raw_combined = json.load(f)
    log(f"Loaded {len(raw_combined)} cached examples")
else:
    log("Downloading and building combined dataset...")
    log("")
    all_ex = []

    # Reasoning datasets
    all_ex.extend(load_opus("nohurry/Opus-4.6-Reasoning-3000x-filtered", "opus-3000"))
    all_ex.extend(load_claude("TeichAI/claude-4.5-opus-high-reasoning-250x", "claude-opus-250"))
    all_ex.extend(load_opus("crownelius/Opus-4.6-Reasoning-3300x", "opus-3300"))

    # Roblox & Luau datasets
    all_ex.extend(load_luau_reasoning(10000))
    all_ex.extend(load_luau_corpus(5000))
    all_ex.extend(load_luau_coding_l1())
    all_ex.extend(load_luau_cot_conv())
    all_ex.extend(load_baby_lua(MAX_SAMPLES_RAW))
    all_ex.extend(load_luau_github(MAX_SAMPLES_RAW))

    # General coding datasets
    all_ex.extend(load_rstar_coder(MAX_SAMPLES_LARGE))
    all_ex.extend(load_software_slacks(MAX_SAMPLES_RAW))

    # NEW: Additional coding & reasoning datasets
    all_ex.extend(load_coderforge(MAX_SAMPLES_LARGE))
    all_ex.extend(load_dataclaw(500))
    all_ex.extend(load_anthropic_backdoor(MAX_SAMPLES_LARGE))
    all_ex.extend(load_competitive_programming(1200))
    all_ex.extend(load_physics(MAX_SAMPLES_LARGE))
    all_ex.extend(load_ioi())
    all_ex.extend(load_competitive_coding(MAX_SAMPLES_LARGE))
    all_ex.extend(load_frontend_cookbook(MAX_SAMPLES_LARGE))

    log("")
    log(f"Total before dedup: {len(all_ex)}")

    # Deduplicate by SHA256 hash of normalized user text
    seen = set()
    raw_combined = []
    for ex in all_ex:
        h = ex.pop("_h")
        if h not in seen:
            seen.add(h)
            raw_combined.append(ex)

    log(f"After dedup: {len(raw_combined)}")

    # Save cache
    with open(COMBINED_CACHE, "w") as f:
        json.dump(raw_combined, f, ensure_ascii=False)
    log(f"Cached to {COMBINED_CACHE}")

# Format for training
def format_combined(example):
    msgs = example["messages"]
    text = tokenizer.apply_chat_template(msgs, tokenize=False, add_generation_prompt=False)
    return {"text": text}

dataset = Dataset.from_list(raw_combined)
dataset = dataset.map(format_combined)

dataset_build_time = time.time() - dataset_build_start

# Print stats
sources = Counter(r["source"] for r in raw_combined)
cats = Counter(r["category"] for r in raw_combined)
log("")
log(f"Dataset ready: {len(dataset)} training examples (built in {dataset_build_time:.1f}s)")
log(f"By source:")
for s, c in sorted(sources.items(), key=lambda x: -x[1]):
    log(f"  {s}: {c}")
log(f"By category: {dict(cats)}")
log(f"Sample (first 300 chars): {dataset[0]['text'][:300]}...")

# ─── Phase 3: Train ──────────────────────────────────────────────────────────

log("")
log("=" * 60)
log("PHASE 3: Training")
log(f"  Epochs: {EPOCHS}")
log(f"  Effective batch size: {BATCH_SIZE} x {GRAD_ACCUM} = {BATCH_SIZE * GRAD_ACCUM}")
log(f"  Learning rate: {LEARNING_RATE}")
log(f"  Dataset size: {len(dataset)} examples")
log("=" * 60)

from trl import SFTTrainer
from transformers import TrainingArguments
from unsloth import is_bfloat16_supported

use_bf16 = is_bfloat16_supported()
log(f"Using {'bfloat16' if use_bf16 else 'float16'} precision")

train_start = time.time()

trainer = SFTTrainer(
    model=model,
    tokenizer=tokenizer,
    train_dataset=dataset,
    dataset_text_field="text",
    max_seq_length=MAX_SEQ_LENGTH,
    dataset_num_proc=2,
    packing=False,
    args=TrainingArguments(
        per_device_train_batch_size=BATCH_SIZE,
        gradient_accumulation_steps=GRAD_ACCUM,
        warmup_steps=5,
        num_train_epochs=EPOCHS,
        learning_rate=LEARNING_RATE,
        fp16=not use_bf16,
        bf16=use_bf16,
        logging_steps=10,
        optim="adamw_8bit",
        weight_decay=0.01,
        lr_scheduler_type="linear",
        seed=42,
        output_dir="outputs",
        report_to="none",
        save_steps=500,
        save_total_limit=2,
    ),
)

log("Starting training...")
stats = trainer.train()
train_time = time.time() - train_start

log("")
log("=" * 60)
log(f"Training complete!")
log(f"  Total steps: {stats.global_step}")
log(f"  Final loss: {stats.training_loss:.4f}")
log(f"  Training time: {train_time / 3600:.1f} hours ({train_time:.0f}s)")
log("=" * 60)

# ─── Phase 4: Test the Model ─────────────────────────────────────────────────

log("")
log("=" * 60)
log("PHASE 4: Testing the model")
log("=" * 60)

FastLanguageModel.for_inference(model)

test_prompt = "Write a Roblox script that makes a part change color every second"
log(f"Test prompt: {test_prompt}")

messages = [
    {"role": "system", "content": PUB_AI_SYSTEM},
    {"role": "user", "content": test_prompt},
]

inputs = tokenizer.apply_chat_template(
    messages, tokenize=True, add_generation_prompt=True, return_tensors="pt"
).to("cuda")

outputs = model.generate(
    input_ids=inputs,
    max_new_tokens=512,
    temperature=0.7,
    top_p=0.9,
    do_sample=True,
)

response = tokenizer.decode(outputs[0][inputs.shape[-1]:], skip_special_tokens=True)
log(f"\nPub AI response:\n{response}\n")

# ─── Phase 5: Save & Export ──────────────────────────────────────────────────

log("")
log("=" * 60)
log("PHASE 5: Saving and exporting model")
log("=" * 60)

# Save LoRA adapters
log("Saving LoRA adapters...")
model.save_pretrained(f"{OUTPUT_MODEL_NAME}-lora")
tokenizer.save_pretrained(f"{OUTPUT_MODEL_NAME}-lora")
log(f"  -> {OUTPUT_MODEL_NAME}-lora/")

# Save merged 16-bit model
log("Saving merged 16-bit model (this takes a while)...")
model.save_pretrained_merged(
    f"{OUTPUT_MODEL_NAME}-merged", tokenizer, save_method="merged_16bit"
)
log(f"  -> {OUTPUT_MODEL_NAME}-merged/")

# Export GGUF
log("Exporting GGUF (q4_k_m quantization)...")
model.save_pretrained_gguf(
    f"{OUTPUT_MODEL_NAME}-gguf",
    tokenizer,
    quantization_method="q4_k_m",
)
log(f"  -> {OUTPUT_MODEL_NAME}-gguf/")

# ─── Phase 6: Push to HuggingFace ────────────────────────────────────────────

log("")
log("=" * 60)
log("PHASE 6: Pushing to HuggingFace")
log("=" * 60)

log(f"Pushing merged model to {HF_USERNAME}/{OUTPUT_MODEL_NAME}...")
model.push_to_hub_merged(
    f"{HF_USERNAME}/{OUTPUT_MODEL_NAME}",
    tokenizer,
    save_method="merged_16bit",
)
log(f"  -> https://huggingface.co/{HF_USERNAME}/{OUTPUT_MODEL_NAME}")

log(f"Pushing GGUF to {HF_USERNAME}/{OUTPUT_MODEL_NAME}-GGUF...")
model.push_to_hub_gguf(
    f"{HF_USERNAME}/{OUTPUT_MODEL_NAME}-GGUF",
    tokenizer,
    quantization_method="q4_k_m",
)
log(f"  -> https://huggingface.co/{HF_USERNAME}/{OUTPUT_MODEL_NAME}-GGUF")

# ─── Done ─────────────────────────────────────────────────────────────────────

total_time = time.time() - model_load_start
log("")
log("=" * 60)
log("ALL DONE!")
log(f"  Total pipeline time: {total_time / 3600:.1f} hours")
log(f"  Model: https://huggingface.co/{HF_USERNAME}/{OUTPUT_MODEL_NAME}")
log(f"  GGUF:  https://huggingface.co/{HF_USERNAME}/{OUTPUT_MODEL_NAME}-GGUF")
log("=" * 60)
