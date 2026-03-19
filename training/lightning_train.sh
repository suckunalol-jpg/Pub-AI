#!/usr/bin/env bash
# Pub AI v2 — Lightning AI Studio Training
# Run this inside your Lightning Studio terminal.
#
# Usage:
#   HF_TOKEN=hf_xxx bash lightning_train.sh [--gpu a100|h100|h200|l40s]
#
# GPU options (pick when creating your Studio):
#   a100  — A100 80GB  (~$1.16/hr on Lightning)  [default]
#   h100  — H100 80GB  (~$2.47/hr on Lightning)
#   l40s  — L40S 48GB  (~$0.63/hr) cheapest, reduced seq/rank to fit
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC}  $*"; }
err()  { echo -e "${RED}[ERROR]${NC} $*" >&2; }
step() { echo -e "\n${BLUE}==> $*${NC}"; }

# ---------------------------------------------------------------------------
# GPU flag
# ---------------------------------------------------------------------------
GPU_CHOICE="a100"
TRAIN_EXTRA_ARGS=""
for arg in "$@"; do
    if [[ "$arg" == --gpu=* ]]; then
        GPU_CHOICE="${arg#--gpu=}"
    elif [[ "$arg" == a100 || "$arg" == h100 || "$arg" == h200 || "$arg" == l40s ]]; then
        GPU_CHOICE="$arg"
    fi
done

case "$GPU_CHOICE" in
    a100)  log "GPU: A100 80GB" ;;
    h100)  log "GPU: H100 80GB" ;;
    h200)
        TRAIN_EXTRA_ARGS="--fast"
        log "GPU: H200 141GB — fast mode enabled (packing=True, epochs=2, 40k cap) — target <4hr"
        ;;
    l40s)
        TRAIN_EXTRA_ARGS="--max-seq-len 4096 --lora-rank 64 --packing"
        warn "L40S (48GB) — using seq_len=4096, LoRA rank=64, packing=True to fit in VRAM"
        ;;
    *)
        err "Unknown GPU: $GPU_CHOICE. Valid: a100, h100, h200, l40s"
        exit 1
        ;;
esac

# ---------------------------------------------------------------------------
# Validate HF_TOKEN
# ---------------------------------------------------------------------------
if [[ -z "${HF_TOKEN:-}" ]]; then
    err "HF_TOKEN is required."
    err "Usage: HF_TOKEN=hf_xxx bash lightning_train.sh"
    exit 1
fi

WANDB_API_KEY="${WANDB_API_KEY:-}"
if [[ -z "$WANDB_API_KEY" ]]; then
    warn "WANDB_API_KEY not set — training metrics won't be logged to W&B"
fi

# ---------------------------------------------------------------------------
# Locate training directory (works whether run from repo root or training/)
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "$SCRIPT_DIR/train_v2.py" ]]; then
    TRAINING_DIR="$SCRIPT_DIR"
elif [[ -f "training/train_v2.py" ]]; then
    TRAINING_DIR="$(pwd)/training"
else
    err "Cannot find train_v2.py. Run this script from inside the pub-ai repo."
    exit 1
fi

log "Training dir: $TRAINING_DIR"
cd "$TRAINING_DIR"

# ---------------------------------------------------------------------------
# Step 1: Install dependencies
# ---------------------------------------------------------------------------
step "Installing dependencies..."
pip install -q --upgrade pip
pip install -q \
    "unsloth[colab-new] @ git+https://github.com/unslothai/unsloth.git" \
    transformers \
    peft \
    trl \
    "datasets>=2.18" \
    accelerate \
    bitsandbytes \
    wandb \
    tqdm \
    huggingface_hub \
    sentencepiece \
    protobuf

log "Dependencies installed."

# ---------------------------------------------------------------------------
# Step 2: HuggingFace login
# ---------------------------------------------------------------------------
step "Logging into HuggingFace..."
huggingface-cli login --token "$HF_TOKEN" --add-to-git-credential 2>/dev/null || \
    python3 -c "from huggingface_hub import login; login('$HF_TOKEN')"
log "HuggingFace authenticated."

if [[ -n "$WANDB_API_KEY" ]]; then
    step "Logging into Weights & Biases..."
    python3 -c "import wandb; wandb.login(key='$WANDB_API_KEY')"
    log "W&B authenticated."
fi

# ---------------------------------------------------------------------------
# Step 3: Generate synthetic data (if not already done)
# ---------------------------------------------------------------------------
SYNTHETIC_DIR="$TRAINING_DIR/synthetic"
mkdir -p "$SYNTHETIC_DIR"

if [[ ! -f "$SYNTHETIC_DIR/tool_use.jsonl" ]]; then
    step "Generating synthetic tool-use dataset..."
    python3 generate_tool_dataset.py --output "$SYNTHETIC_DIR/tool_use.jsonl"
else
    log "Synthetic tool_use.jsonl already exists, skipping."
fi

if [[ ! -f "$SYNTHETIC_DIR/kali_security.jsonl" ]]; then
    step "Generating synthetic security/environment/proactive datasets..."
    python3 generate_synthetic_data.py --output-dir "$SYNTHETIC_DIR"
else
    log "Synthetic kali_security.jsonl already exists, skipping."
fi

# ---------------------------------------------------------------------------
# Step 4: Build combined dataset
# ---------------------------------------------------------------------------
DATASET_PATH="$TRAINING_DIR/pub_ai_v2_combined.jsonl"

if [[ ! -f "$DATASET_PATH" ]]; then
    step "Building combined dataset from HuggingFace + synthetic sources..."
    HF_TOKEN="$HF_TOKEN" python3 build_dataset_v2.py --output "$DATASET_PATH"
else
    LINES=$(wc -l < "$DATASET_PATH")
    log "Dataset already exists: $DATASET_PATH ($LINES examples)"
    warn "Delete it and rerun to rebuild from scratch."
fi

# ---------------------------------------------------------------------------
# Step 5: Train
# ---------------------------------------------------------------------------
step "Starting training — this will take 8-12 hours on A100..."
log "Output dir: /teamspace/studios/this_studio/pub-ai-v2-output"
log "Logs: tail -f /teamspace/studios/this_studio/pub-ai-v2-output/training.log"

WANDB_API_KEY="${WANDB_API_KEY:-}" \
HF_TOKEN="$HF_TOKEN" \
python3 train_v2.py \
    --dataset "$DATASET_PATH" \
    --output "/teamspace/studios/this_studio/pub-ai-v2-output" \
    $TRAIN_EXTRA_ARGS \
    2>&1 | tee /teamspace/studios/this_studio/pub-ai-v2-output/training.log

log "Training complete!"
log "Model pushed to HuggingFace: suckunalol/pub-ai-v2"
