#!/usr/bin/env python3
"""
Pub-AI LoRA Merge Script
Merges suckunalol/pub-ai-lora-v1 adapter into Qwen/Qwen2.5-Coder-32B-Instruct,
then exports to GGUF for Ollama.

Run on a GPU machine (RunPod, etc.) with at least 80GB VRAM or 128GB+ RAM.
"""

import os
import sys
import subprocess

# ── 1. Install dependencies ─────────────────────────────────
def install_deps():
    deps = [
        "torch", "transformers", "peft", "accelerate",
        "bitsandbytes", "huggingface_hub", "safetensors",
    ]
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q"] + deps)

print("📦 Installing dependencies...")
install_deps()

import torch
from peft import PeftModel, PeftConfig
from transformers import AutoModelForCausalLM, AutoTokenizer
from huggingface_hub import login

# ── 2. Configuration ────────────────────────────────────────
HF_TOKEN = os.environ.get("HF_TOKEN")
BASE_MODEL = "Qwen/Qwen2.5-Coder-32B-Instruct"
LORA_ADAPTER = "suckunalol/pub-ai-lora-v1"
OUTPUT_DIR = "./pub-ai-merged"
HF_PUSH_REPO = "suckunalol/pub-ai-merged"  # Change this if you want a different name

# ── 3. Login to HuggingFace ─────────────────────────────────
print("🔑 Logging in to HuggingFace...")
login(token=HF_TOKEN)

# ── 4. Load base model ──────────────────────────────────────
print(f"📥 Loading base model: {BASE_MODEL}")
print("   (This will download ~64GB, may take 10-30 min)")

tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL, trust_remote_code=True)

# Use device_map="auto" to spread across available GPUs/CPU
model = AutoModelForCausalLM.from_pretrained(
    BASE_MODEL,
    torch_dtype=torch.float16,
    device_map="auto",
    trust_remote_code=True,
)
print("✅ Base model loaded")

# ── 5. Load and merge LoRA adapter ──────────────────────────
print(f"🔗 Loading LoRA adapter: {LORA_ADAPTER}")
model = PeftModel.from_pretrained(model, LORA_ADAPTER)
print("🔀 Merging weights...")
model = model.merge_and_unload()
print("✅ Merge complete!")

# ── 6. Save merged model locally ────────────────────────────
print(f"💾 Saving merged model to {OUTPUT_DIR}")
model.save_pretrained(OUTPUT_DIR, safe_serialization=True)
tokenizer.save_pretrained(OUTPUT_DIR)
print("✅ Saved locally")

# ── 7. Push to HuggingFace ──────────────────────────────────
print(f"☁️  Pushing to HuggingFace: {HF_PUSH_REPO}")
from huggingface_hub import HfApi
api = HfApi()
api.create_repo(repo_id=HF_PUSH_REPO, repo_type="model", exist_ok=True)
model.push_to_hub(HF_PUSH_REPO, safe_serialization=True)
tokenizer.push_to_hub(HF_PUSH_REPO)
print(f"✅ Pushed! View at: https://huggingface.co/{HF_PUSH_REPO}")

# ── 8. Convert to GGUF (optional) ───────────────────────────
print("\n" + "=" * 50)
print("🎉 MERGE COMPLETE!")
print(f"   Merged model: {OUTPUT_DIR}")
print(f"   HuggingFace:  https://huggingface.co/{HF_PUSH_REPO}")
print()
print("To convert to GGUF for Ollama, run:")
print(f"   pip install llama-cpp-python")
print(f"   python -m llama_cpp.convert {OUTPUT_DIR} --outfile pub-ai.gguf --outtype q4_k_m")
print()
print("Then import into Ollama:")
print("   ollama create pub-ai -f Modelfile")
print("=" * 50)
