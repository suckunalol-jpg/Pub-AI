#!/bin/bash
# =============================================================================
# Pub AI — Google Cloud TPU Training Script
# =============================================================================
#
# Provisions a TPU VM on Google Cloud, sets up the training environment,
# and runs train_tpu.py.
#
# Usage:
#   export HF_TOKEN="hf_..."
#   bash gcloud_train_tpu.sh
#
# Requirements:
#   - gcloud CLI installed and authenticated
#   - TPU quota in your GCP project
#   - HF_TOKEN environment variable set (for dataset access + pushing)
#
# Default: TPU v5litepod-4 in us-east5-b (matches account quota limits)
# =============================================================================

set -euo pipefail

# ---- Configuration ----
TPU_NAME="${TPU_NAME:-pub-ai-test-us-east1}"
TPU_TYPE="${TPU_TYPE:-v5litepod-4}"
ZONE="${ZONE:-us-east1-c}"
PROJECT="${PROJECT:-$(gcloud config get-value project 2>/dev/null)}"
RUNTIME_VERSION="${RUNTIME_VERSION:-tpu-ubuntu2204-base}"
REPO_URL="${REPO_URL:-https://github.com/suckunalol-jpg/Pub-AI.git}"
REPO_BRANCH="${REPO_BRANCH:-main}"

# Training config
EPOCHS="${EPOCHS:-2}"
BATCH_SIZE="${BATCH_SIZE:-1}"
GRAD_ACCUM="${GRAD_ACCUM:-32}"
LR="${LR:-2e-4}"
LORA_RANK="${LORA_RANK:-64}"
MAX_SEQ_LEN="${MAX_SEQ_LEN:-4096}"
PUSH_TO_HUB="${PUSH_TO_HUB:-false}"
HUB_REPO="${HUB_REPO:-suckunalol/pub-ai-tpu}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log() { echo -e "${BLUE}[Pub AI]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }
success() { echo -e "${GREEN}[OK]${NC} $1"; }

# ---- Preflight checks ----
log "Running preflight checks..."

if ! command -v gcloud &> /dev/null; then
    error "gcloud CLI not found. Install: https://cloud.google.com/sdk/docs/install"
    exit 1
fi

if [ -z "$PROJECT" ]; then
    error "No GCP project set. Run: gcloud config set project YOUR_PROJECT"
    exit 1
fi

if [ -z "${HF_TOKEN:-}" ]; then
    warn "HF_TOKEN not set — datasets behind auth gates may fail, and push-to-hub will be skipped"
fi

success "Preflight checks passed"
log "Project:  $PROJECT"
log "Zone:     $ZONE"
log "TPU:      $TPU_NAME ($TPU_TYPE)"
log "Runtime:  $RUNTIME_VERSION"

# ---- Check for existing TPU VM ----
log "Checking for existing TPU VM..."
if gcloud compute tpus tpu-vm describe "$TPU_NAME" --zone="$ZONE" --project="$PROJECT" &>/dev/null; then
    warn "TPU VM '$TPU_NAME' already exists. Reusing it."
    REUSE_VM=true
else
    REUSE_VM=false
fi

# ---- Create TPU VM ----
if [ "$REUSE_VM" = false ]; then
    log "Creating TPU VM '$TPU_NAME' ($TPU_TYPE) in $ZONE..."

    gcloud compute tpus tpu-vm create "$TPU_NAME" \
        --zone="$ZONE" \
        --project="$PROJECT" \
        --accelerator-type="$TPU_TYPE" \
        --version="$RUNTIME_VERSION" \
        --preemptible \
        || {
            error "Failed to create TPU VM. Check your quota:"
            error "  gcloud compute tpus tpu-vm list --zone=$ZONE"
            error ""
            error "If $TPU_TYPE is not available, try:"
            error "  - Different zone: ZONE=europe-west4-a bash $0"
            error "  - Different TPU:  TPU_TYPE=v3-8 bash $0"
            error "  - v5e (newer):    TPU_TYPE=v5litepod-8 ZONE=us-east5-b bash $0"
            exit 1
        }
    success "TPU VM created"
fi

# ---- Setup: install dependencies on TPU VM ----
log "Setting up training environment on TPU VM..."

gcloud compute tpus tpu-vm ssh "$TPU_NAME" \
    --zone="$ZONE" \
    --project="$PROJECT" \
    --command="$(cat <<'SETUP_EOF'
set -euo pipefail

echo "=== Cleaning up old processes ==="
sudo pkill -9 -f python3 || true
sudo fuser -k -9 /dev/vfio/* || true

echo "=== Installing system dependencies ==="
sudo apt-get update -qq
sudo apt-get install -y -qq git python3-pip python3-venv

echo "=== Creating virtual environment ==="
python3 -m venv ~/pub-ai-env
source ~/pub-ai-env/bin/activate

echo "=== Installing PyTorch/XLA for TPU ==="
pip install --quiet --upgrade pip
pip install --quiet torch~=2.3.0 torch_xla[tpu]~=2.3.0 -f https://storage.googleapis.com/libtpu-releases/index.html

echo "=== Installing training dependencies ==="
pip install --quiet transformers==4.43.3 datasets>=2.18.0 peft>=0.10.0 trl==0.9.6
pip install --quiet accelerate>=0.28.0 tokenizers sentencepiece protobuf
pip install --quiet huggingface_hub safetensors

echo "=== Verifying TPU ==="
python3 -c "
import torch
import torch_xla.core.xla_model as xm
device = xm.xla_device()
print(f'TPU device: {device}')
t = torch.randn(2, 2, device=device)
print(f'TPU tensor: {t}')
print('TPU verification: PASSED')
"

echo "=== Setup complete ==="
SETUP_EOF
)"

success "Environment setup complete"

# ---- Clone repository ----
log "Cloning Pub-AI repository..."

gcloud compute tpus tpu-vm ssh "$TPU_NAME" \
    --zone="$ZONE" \
    --project="$PROJECT" \
    --command="
    set -euo pipefail
    source ~/pub-ai-env/bin/activate

    if [ -d ~/Pub-AI ]; then
        echo 'Repository exists, pulling latest...'
        cd ~/Pub-AI && git pull origin $REPO_BRANCH
    else
        echo 'Cloning repository...'
        git clone --branch $REPO_BRANCH $REPO_URL ~/Pub-AI
    fi
    "

success "Repository ready"

# ---- Run training ----
log "Starting training..."
log ""
log "  Model:     Qwen2.5-Coder-32B-Instruct"
log "  TPU:       $TPU_TYPE"
log "  Epochs:    $EPOCHS"
log "  Batch:     $BATCH_SIZE × $GRAD_ACCUM accum"
log "  LR:        $LR"
log "  LoRA:      r=$LORA_RANK"
log "  Seq len:   $MAX_SEQ_LEN"
log ""

PUSH_FLAG=""
if [ "$PUSH_TO_HUB" = "true" ]; then
    PUSH_FLAG="--push-to-hub --hub-repo $HUB_REPO"
fi

HF_ENV=""
if [ -n "${HF_TOKEN:-}" ]; then
    HF_ENV="export HF_TOKEN='$HF_TOKEN' &&"
fi

gcloud compute tpus tpu-vm ssh "$TPU_NAME" \
    --zone="$ZONE" \
    --project="$PROJECT" \
    --command="
    set -euo pipefail
    source ~/pub-ai-env/bin/activate
    $HF_ENV

    cd ~/Pub-AI/training

    python3 train_tpu.py \
        --epochs $EPOCHS \
        --batch-size $BATCH_SIZE \
        --grad-accum $GRAD_ACCUM \
        --lr $LR \
        --lora-rank $LORA_RANK \
        --max-seq-len $MAX_SEQ_LEN \
        --output-dir ~/pub-ai-tpu-output \
        $PUSH_FLAG
    "

success "Training complete!"

# ---- Download results ----
log "Downloading trained model from TPU VM..."

gcloud compute tpus tpu-vm scp \
    "$TPU_NAME:~/pub-ai-tpu-output/merged-model" \
    ./pub-ai-tpu-model \
    --zone="$ZONE" \
    --project="$PROJECT" \
    --recurse \
    || warn "Could not download model. You can manually download with:
    gcloud compute tpus tpu-vm scp $TPU_NAME:~/pub-ai-tpu-output/merged-model ./pub-ai-tpu-model --zone=$ZONE --recurse"

# ---- Cleanup prompt ----
echo ""
log "========================================="
log "  Training Complete!"
log "========================================="
log ""
log "  Model saved to: ~/pub-ai-tpu-output/"
if [ "$PUSH_TO_HUB" = "true" ]; then
    log "  Pushed to: https://huggingface.co/$HUB_REPO"
fi
log ""
log "  To stop the TPU VM (saves money):"
log "    gcloud compute tpus tpu-vm stop $TPU_NAME --zone=$ZONE"
log ""
log "  To delete the TPU VM (permanent):"
log "    gcloud compute tpus tpu-vm delete $TPU_NAME --zone=$ZONE"
log ""
log "  To SSH into the VM for inspection:"
log "    gcloud compute tpus tpu-vm ssh $TPU_NAME --zone=$ZONE"
log ""
