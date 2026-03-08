#!/usr/bin/env bash
###############################################################################
#
#  Pub AI — Google Cloud GPU Training Pipeline
#  ============================================
#
#  Automates the full model fine-tuning workflow on Google Cloud:
#
#    Phase 1: Create a GPU VM (A100 80GB preferred, L4 fallback)
#    Phase 2: Wait for VM SSH readiness
#    Phase 3: Install dependencies and clone repo on the VM
#    Phase 4: Generate and upload a standalone train.py script
#    Phase 5: Run training via nohup (survives disconnects)
#    Phase 6: Post-training instructions (cleanup, HuggingFace, Railway)
#
#  Prerequisites:
#    - Google Cloud account with GPU quota approved
#    - gcloud CLI installed and authenticated (gcloud auth login)
#    - A GCP project set (gcloud config set project YOUR_PROJECT)
#    - HF_TOKEN environment variable set (HuggingFace write token)
#
#  Usage:
#    export HF_TOKEN="hf_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
#    bash training/gcloud_train.sh
#
#  Base model : Qwen2.5-Coder-32B-Instruct (4-bit via Unsloth)
#  Method     : LoRA fine-tuning, 5 epochs
#  Output     : suckunalol/pub-ai (HuggingFace)
#
###############################################################################

set -euo pipefail

# ─── Colors ──────────────────────────────────────────────────────────────────

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# ─── Helpers ─────────────────────────────────────────────────────────────────

timestamp() { date "+%Y-%m-%d %H:%M:%S"; }
info()    { echo -e "${CYAN}[$(timestamp)] [INFO]${NC} $*"; }
success() { echo -e "${GREEN}[$(timestamp)] [OK]${NC} $*"; }
warn()    { echo -e "${YELLOW}[$(timestamp)] [WARN]${NC} $*"; }
fail()    { echo -e "${RED}[$(timestamp)] [ERROR]${NC} $*"; }

die() { fail "$@"; exit 1; }

# ─── Error trap ──────────────────────────────────────────────────────────────

cleanup_on_error() {
    local exit_code=$?
    if [ $exit_code -ne 0 ]; then
        echo ""
        fail "Script failed with exit code $exit_code."
        fail "The VM may still be running. To check:"
        echo "    gcloud compute instances list --filter=\"name=$VM_NAME\""
        echo ""
        fail "To delete the VM and stop billing:"
        echo "    gcloud compute instances delete $VM_NAME --zone=\$ZONE --quiet"
        echo ""
    fi
}
trap cleanup_on_error EXIT

# ─── Configuration ───────────────────────────────────────────────────────────

VM_NAME="pub-ai-trainer"
IMAGE_FAMILY="pytorch-latest-gpu"
IMAGE_PROJECT="deeplearning-platform-release"
BOOT_DISK_SIZE="200GB"
BOOT_DISK_TYPE="pd-ssd"
REPO_URL="https://github.com/suckunalol-jpg/Pub-AI.git"
HF_USERNAME="suckunalol"

# GPU machine types in preference order
declare -a MACHINE_TYPES=("a2-highgpu-1g" "g2-standard-12")
declare -a MACHINE_LABELS=("A100 80GB"     "L4 24GB")

# Zones to try, in order
declare -a ZONES=(
    "us-central1-a"
    "us-central1-b"
    "us-central1-c"
    "us-central1-f"
    "us-east1-b"
    "us-east1-c"
    "us-west1-a"
    "us-west1-b"
    "us-west4-a"
    "us-west4-b"
    "europe-west4-a"
    "europe-west4-b"
)

# These will be set once the VM is created
ZONE=""
MACHINE_TYPE=""
GPU_LABEL=""

# ─── Banner ──────────────────────────────────────────────────────────────────

echo ""
echo -e "${BOLD}${CYAN}"
echo "  ============================================================"
echo "       Pub AI  --  Google Cloud GPU Training Pipeline"
echo "  ============================================================"
echo -e "${NC}"
echo "  Model   : Qwen2.5-Coder-32B-Instruct (4-bit LoRA)"
echo "  Datasets: 19 combined sources (~60k+ examples)"
echo "  Output  : suckunalol/pub-ai on HuggingFace"
echo "  VM      : A100 80GB preferred, L4 24GB fallback"
echo ""

# ─── Phase 0: Preflight Checks ──────────────────────────────────────────────

echo -e "${BOLD}=== Phase 0: Preflight Checks ===${NC}"
echo ""

# Check gcloud is installed
if ! command -v gcloud &> /dev/null; then
    die "gcloud CLI is not installed. Install it from: https://cloud.google.com/sdk/docs/install"
fi
success "gcloud CLI found: $(gcloud version 2>/dev/null | head -1)"

# Check logged in
ACCOUNT=$(gcloud config get-value account 2>/dev/null || true)
if [ -z "$ACCOUNT" ] || [ "$ACCOUNT" = "(unset)" ]; then
    die "Not logged in to gcloud. Run: gcloud auth login"
fi
success "Logged in as: $ACCOUNT"

# Check project is set
PROJECT=$(gcloud config get-value project 2>/dev/null || true)
if [ -z "$PROJECT" ] || [ "$PROJECT" = "(unset)" ]; then
    die "No GCP project set. Run: gcloud config set project YOUR_PROJECT_ID"
fi
success "GCP Project: $PROJECT"

# Check HF_TOKEN
if [ -z "${HF_TOKEN:-}" ]; then
    echo ""
    fail "HF_TOKEN environment variable is not set."
    echo "  Get a write token from: https://huggingface.co/settings/tokens"
    echo "  Then run:"
    echo "    export HF_TOKEN=\"hf_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx\""
    echo "    bash training/gcloud_train.sh"
    exit 1
fi
success "HF_TOKEN is set (${HF_TOKEN:0:6}...)"

# Check billing is enabled
BILLING_ENABLED=$(gcloud beta billing projects describe "$PROJECT" --format="value(billingEnabled)" 2>/dev/null || echo "unknown")
if [ "$BILLING_ENABLED" = "False" ]; then
    die "Billing is not enabled for project $PROJECT. Enable it at: https://console.cloud.google.com/billing"
elif [ "$BILLING_ENABLED" = "True" ]; then
    success "Billing is enabled"
else
    warn "Could not verify billing status (this is OK if billing is enabled)"
fi

echo ""

# ─── Phase 1: Create the VM ─────────────────────────────────────────────────

echo -e "${BOLD}=== Phase 1: Create GPU VM ===${NC}"
echo -e "  ${CYAN}Estimated time: 2-5 minutes${NC}"
echo ""

# Check if VM already exists
EXISTING_VM=$(gcloud compute instances list --filter="name=$VM_NAME" --format="value(name,zone,status)" 2>/dev/null || true)

if [ -n "$EXISTING_VM" ]; then
    EXISTING_ZONE=$(echo "$EXISTING_VM" | awk '{print $2}')
    EXISTING_STATUS=$(echo "$EXISTING_VM" | awk '{print $3}')
    warn "VM '$VM_NAME' already exists in zone $EXISTING_ZONE (status: $EXISTING_STATUS)"

    if [ "$EXISTING_STATUS" = "TERMINATED" ] || [ "$EXISTING_STATUS" = "STOPPED" ]; then
        info "Starting existing VM..."
        gcloud compute instances start "$VM_NAME" --zone="$EXISTING_ZONE" --quiet
    fi

    ZONE="$EXISTING_ZONE"
    MACHINE_TYPE=$(gcloud compute instances describe "$VM_NAME" --zone="$ZONE" --format="value(machineType)" 2>/dev/null | awk -F'/' '{print $NF}')

    # Determine GPU label
    GPU_LABEL="Unknown GPU"
    for i in "${!MACHINE_TYPES[@]}"; do
        if [ "${MACHINE_TYPES[$i]}" = "$MACHINE_TYPE" ]; then
            GPU_LABEL="${MACHINE_LABELS[$i]}"
            break
        fi
    done

    success "Using existing VM: $VM_NAME ($MACHINE_TYPE / $GPU_LABEL) in $ZONE"
else
    # Show cost estimate and confirm
    echo -e "  ${YELLOW}Estimated cost:${NC}"
    echo "    A100 80GB (a2-highgpu-1g): ~\$3.67/hr  (~\$10-15 for full training)"
    echo "    L4 24GB   (g2-standard-12): ~\$1.30/hr  (~\$5-8 for full training)"
    echo ""
    echo "  The VM will be created with:"
    echo "    - 200GB SSD boot disk"
    echo "    - PyTorch + CUDA pre-installed (Deep Learning VM image)"
    echo "    - Preemptible NOT used (training is long, avoid interruptions)"
    echo ""

    read -rp "  Proceed with VM creation? (y/N): " CONFIRM
    if [[ ! "$CONFIRM" =~ ^[Yy]$ ]]; then
        info "Aborted by user."
        exit 0
    fi
    echo ""

    VM_CREATED=false

    for mt_idx in "${!MACHINE_TYPES[@]}"; do
        MACHINE_TYPE="${MACHINE_TYPES[$mt_idx]}"
        GPU_LABEL="${MACHINE_LABELS[$mt_idx]}"
        info "Trying $MACHINE_TYPE ($GPU_LABEL)..."

        for zone in "${ZONES[@]}"; do
            info "  Zone: $zone ..."

            # Determine accelerator based on machine type
            ACCEL_FLAG=""
            if [ "$MACHINE_TYPE" = "a2-highgpu-1g" ]; then
                ACCEL_FLAG="--accelerator=type=nvidia-tesla-a100,count=1"
            elif [ "$MACHINE_TYPE" = "g2-standard-12" ]; then
                ACCEL_FLAG="--accelerator=type=nvidia-l4,count=1"
            fi

            if gcloud compute instances create "$VM_NAME" \
                --zone="$zone" \
                --machine-type="$MACHINE_TYPE" \
                $ACCEL_FLAG \
                --image-family="$IMAGE_FAMILY" \
                --image-project="$IMAGE_PROJECT" \
                --boot-disk-size="$BOOT_DISK_SIZE" \
                --boot-disk-type="$BOOT_DISK_TYPE" \
                --maintenance-policy=TERMINATE \
                --restart-on-failure \
                --scopes=default,storage-rw \
                --metadata="install-nvidia-driver=True" \
                --quiet 2>/dev/null; then

                ZONE="$zone"
                VM_CREATED=true
                success "VM created: $VM_NAME ($MACHINE_TYPE / $GPU_LABEL) in $ZONE"
                break 2
            else
                warn "  Failed in $zone (capacity or quota issue), trying next..."
            fi
        done
    done

    if [ "$VM_CREATED" = false ]; then
        die "Could not create VM in any zone. Check your GPU quota at:
    https://console.cloud.google.com/iam-admin/quotas

    Request quota for one of:
      - NVIDIA A100 GPUs (all regions)
      - NVIDIA L4 GPUs (all regions)"
    fi
fi

echo ""

# ─── Phase 2: Wait for VM SSH ───────────────────────────────────────────────

echo -e "${BOLD}=== Phase 2: Wait for VM SSH Readiness ===${NC}"
echo -e "  ${CYAN}Estimated time: 1-3 minutes${NC}"
echo ""

MAX_SSH_ATTEMPTS=30
SSH_ATTEMPT=0

while [ $SSH_ATTEMPT -lt $MAX_SSH_ATTEMPTS ]; do
    SSH_ATTEMPT=$((SSH_ATTEMPT + 1))
    info "SSH attempt $SSH_ATTEMPT/$MAX_SSH_ATTEMPTS ..."

    if gcloud compute ssh "$VM_NAME" --zone="$ZONE" --command="echo 'SSH_READY'" --quiet 2>/dev/null | grep -q "SSH_READY"; then
        success "SSH connection established!"
        break
    fi

    if [ $SSH_ATTEMPT -eq $MAX_SSH_ATTEMPTS ]; then
        die "SSH did not become available after $MAX_SSH_ATTEMPTS attempts."
    fi

    sleep 10
done

echo ""

# ─── Phase 3: Remote Setup ──────────────────────────────────────────────────

echo -e "${BOLD}=== Phase 3: Remote VM Setup ===${NC}"
echo -e "  ${CYAN}Estimated time: 5-10 minutes${NC}"
echo ""

# Helper to run commands on the VM
run_remote() {
    gcloud compute ssh "$VM_NAME" --zone="$ZONE" --command="$1" 2>&1
}

# 3a. Verify GPU
info "Verifying GPU is detected..."
GPU_INFO=$(run_remote "nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null || echo 'NO_GPU'")

if echo "$GPU_INFO" | grep -qi "NO_GPU"; then
    warn "nvidia-smi not available yet. Waiting for driver installation..."
    sleep 30
    GPU_INFO=$(run_remote "nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null || echo 'NO_GPU'")
fi

if echo "$GPU_INFO" | grep -qi "NO_GPU"; then
    die "GPU not detected on the VM. The NVIDIA driver may not have installed correctly."
fi

success "GPU detected: $GPU_INFO"
echo ""

# 3b. Install dependencies
info "Installing Python dependencies (this takes a few minutes)..."
run_remote "pip install --upgrade pip && \
pip install 'unsloth[cu121-ampere] @ git+https://github.com/unslothai/unsloth.git' && \
pip install --no-deps trl peft accelerate bitsandbytes && \
pip install datasets huggingface_hub && \
pip install jupyter && \
echo 'DEPS_INSTALLED'"

success "Dependencies installed"
echo ""

# 3c. Clone repo
info "Cloning Pub-AI repository..."
run_remote "if [ -d 'Pub-AI' ]; then
    echo 'Repo already exists, pulling latest...'
    cd Pub-AI && git pull
else
    git clone $REPO_URL
fi && echo 'REPO_READY'"

success "Repository ready"
echo ""

# ─── Phase 4: Generate and Upload train.py ───────────────────────────────────

echo -e "${BOLD}=== Phase 4: Generate & Upload Training Script ===${NC}"
echo -e "  ${CYAN}Estimated time: < 1 minute${NC}"
echo ""

info "Generating standalone train.py ..."

# Create a temporary file locally, then upload it
TRAIN_SCRIPT_LOCAL=$(mktemp /tmp/train_py_XXXXXX.py)

cat > "$TRAIN_SCRIPT_LOCAL" << 'TRAIN_PY_EOF'
#!/usr/bin/env python3
"""
Pub AI — Standalone Training Script
====================================
Auto-generated by gcloud_train.sh

This script is fully self-contained. It:
  1. Loads the base model (4-bit quantized via Unsloth)
  2. Applies LoRA adapters
  3. Downloads and combines 11 training datasets
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
TRAIN_PY_EOF

info "Uploading train.py to VM..."
gcloud compute scp "$TRAIN_SCRIPT_LOCAL" "$VM_NAME:~/Pub-AI/training/train.py" --zone="$ZONE" --quiet
rm -f "$TRAIN_SCRIPT_LOCAL"

success "train.py uploaded to ~/Pub-AI/training/train.py on the VM"
echo ""

# ─── Phase 5: Run Training ──────────────────────────────────────────────────

echo -e "${BOLD}=== Phase 5: Start Training ===${NC}"
echo -e "  ${CYAN}Estimated time: 3-8 hours (depends on GPU and dataset size)${NC}"
echo ""

info "Starting training with nohup (survives SSH disconnects)..."

# Run training via nohup, pass HF_TOKEN, log to file
run_remote "cd ~/Pub-AI/training && \
export HF_TOKEN='${HF_TOKEN}' && \
nohup python -u train.py > train_output.log 2>&1 &
echo 'TRAINING_PID='\$!
echo \$! > train.pid"

success "Training process launched in background!"
echo ""

# Give it a moment to start
sleep 5

# Check it's actually running
RUNNING=$(run_remote "ps -p \$(cat ~/Pub-AI/training/train.pid 2>/dev/null || echo 0) -o pid= 2>/dev/null || echo ''")
if [ -n "$RUNNING" ]; then
    success "Training process confirmed running (PID: $(echo $RUNNING | tr -d ' '))"
else
    warn "Could not confirm training process. Check the log for errors:"
    echo "    gcloud compute ssh $VM_NAME --zone=$ZONE --command='tail -50 ~/Pub-AI/training/train_output.log'"
fi

echo ""
info "Tailing training log (Ctrl+C to detach -- training continues on the VM)..."
echo ""
echo -e "${CYAN}────────────────────────────────────────────────────────${NC}"

# Tail the log -- user can Ctrl+C safely, training continues via nohup
gcloud compute ssh "$VM_NAME" --zone="$ZONE" --command="tail -f ~/Pub-AI/training/train_output.log" 2>/dev/null || true

echo -e "${CYAN}────────────────────────────────────────────────────────${NC}"
echo ""

# ─── Phase 6: Post-Training Instructions ────────────────────────────────────

echo -e "${BOLD}=== Phase 6: Post-Training Instructions ===${NC}"
echo ""

echo -e "${GREEN}Training is running on the VM in the background.${NC}"
echo ""

echo -e "${BOLD}To reconnect and watch progress:${NC}"
echo "    gcloud compute ssh $VM_NAME --zone=$ZONE --command='tail -f ~/Pub-AI/training/train_output.log'"
echo ""

echo -e "${BOLD}To check if training is still running:${NC}"
echo "    gcloud compute ssh $VM_NAME --zone=$ZONE --command='ps -p \$(cat ~/Pub-AI/training/train.pid) -o pid,etime,cmd'"
echo ""

echo -e "${BOLD}To check the last few lines of output:${NC}"
echo "    gcloud compute ssh $VM_NAME --zone=$ZONE --command='tail -30 ~/Pub-AI/training/train_output.log'"
echo ""

echo -e "${BOLD}After training completes:${NC}"
echo ""
echo "  1. Verify the model was pushed to HuggingFace:"
echo "     https://huggingface.co/${HF_USERNAME}/pub-ai"
echo "     https://huggingface.co/${HF_USERNAME}/pub-ai-GGUF"
echo ""

echo "  2. Stop the VM to stop billing:"
echo "     gcloud compute instances stop $VM_NAME --zone=$ZONE --quiet"
echo ""

echo "  3. Or delete the VM entirely:"
echo "     gcloud compute instances delete $VM_NAME --zone=$ZONE --quiet"
echo ""

echo -e "${BOLD}Railway environment variables to set:${NC}"
echo "    VLLM_HOST=https://api-inference.huggingface.co/models/${HF_USERNAME}/pub-ai"
echo "    VLLM_API_KEY=hf_xxxxxxxxxxxx  (your HuggingFace token)"
echo "    VLLM_MODEL_NAME=pub-ai"
echo ""

echo -e "${BOLD}Ollama local deployment:${NC}"
echo "    # Download the GGUF from HuggingFace, then:"
echo "    cat > Modelfile << 'MODELFILE_EOF'"
echo "FROM ./pub-ai-gguf/unsloth.Q4_K_M.gguf"
echo ""
echo "SYSTEM \"\"\"${PUB_AI_SYSTEM:-You are Pub AI, a custom-built AI coding assistant.}\"\"\""
echo ""
echo "PARAMETER temperature 0.7"
echo "PARAMETER top_p 0.9"
echo "PARAMETER num_predict 2048"
echo "MODELFILE_EOF"
echo "    ollama create pub-ai -f Modelfile"
echo "    ollama run pub-ai"
echo ""

echo -e "${GREEN}${BOLD}Pipeline complete! The model is training on $VM_NAME ($GPU_LABEL) in $ZONE.${NC}"
echo ""
