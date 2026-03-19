#!/usr/bin/env bash
# Pub AI v2 — RunPod Training Automation
# Usage: HF_TOKEN=hf_xxx [WANDB_API_KEY=xxx] [RUNPOD_API_KEY=xxx] bash runpod_train.sh [--gpu a100|h100|h200|l40s]
#
# GPU options:
#   a100  — NVIDIA A100 80GB SXM  (~$2.49/hr) [default]
#   h100  — NVIDIA H100 80GB PCIe (~$3.49/hr)
#   h200  — NVIDIA H200 SXM 141GB (~$4.49/hr) fastest, most VRAM
#   l40s  — NVIDIA L40S 48GB      (~$1.14/hr) cheapest, uses reduced seq_len+rank
set -euo pipefail

# ---------------------------------------------------------------------------
# Color helpers
# ---------------------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'  # No Color

log()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC}  $*"; }
err()  { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# ---------------------------------------------------------------------------
# Validate environment variables
# ---------------------------------------------------------------------------
if [[ -z "${HF_TOKEN:-}" ]]; then
    err "HF_TOKEN is required but not set."
    err "Usage: HF_TOKEN=hf_xxx [WANDB_API_KEY=xxx] [RUNPOD_API_KEY=xxx] bash runpod_train.sh"
    exit 1
fi

if [[ -z "${RUNPOD_API_KEY:-}" ]]; then
    warn "RUNPOD_API_KEY is not set. Automated pod creation will be skipped."
    warn "You will receive manual instructions instead."
fi

if [[ -z "${WANDB_API_KEY:-}" ]]; then
    warn "WANDB_API_KEY is not set. Training metrics will not be logged to Weights & Biases."
fi

log "Environment validated."

# ---------------------------------------------------------------------------
# Parse --gpu flag
# ---------------------------------------------------------------------------
GPU_CHOICE="a100"
TRAIN_EXTRA_ARGS=""
for arg in "$@"; do
    case "$arg" in
        --gpu) shift ;;
        a100|h100|h200|l40s) GPU_CHOICE="$arg" ;;
    esac
done
# Also allow --gpu=xxx form
for arg in "$@"; do
    if [[ "$arg" == --gpu=* ]]; then
        GPU_CHOICE="${arg#--gpu=}"
    fi
done

case "$GPU_CHOICE" in
    a100)
        GPU_TYPE_PRIMARY="NVIDIA A100 80GB SXM"
        GPU_TYPE_FALLBACK="NVIDIA H100 80GB PCIe"
        ;;
    h100)
        GPU_TYPE_PRIMARY="NVIDIA H100 80GB PCIe"
        GPU_TYPE_FALLBACK="NVIDIA A100 80GB SXM"
        ;;
    h200)
        GPU_TYPE_PRIMARY="NVIDIA H200 SXM"
        GPU_TYPE_FALLBACK="NVIDIA H100 80GB PCIe"
        ;;
    l40s)
        GPU_TYPE_PRIMARY="NVIDIA L40S"
        GPU_TYPE_FALLBACK="NVIDIA A100 80GB SXM"
        # L40S has 48GB — reduce seq_len and LoRA rank to avoid OOM
        TRAIN_EXTRA_ARGS="--max-seq-len 4096 --lora-rank 64"
        warn "L40S selected (48GB). Training will use seq_len=4096, LoRA rank=64 to fit in VRAM."
        ;;
    *)
        err "Unknown GPU type '$GPU_CHOICE'. Valid: a100, h100, h200, l40s"
        exit 1
        ;;
esac

log "GPU: $GPU_TYPE_PRIMARY (fallback: $GPU_TYPE_FALLBACK)"

# ---------------------------------------------------------------------------
# Variables
# ---------------------------------------------------------------------------
DOCKER_IMAGE="runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04"
CONTAINER_DISK=50
VOLUME_DISK=200
VOLUME_MOUNT="/workspace"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"  # pub-ai root

DATASET_LOCAL="$SCRIPT_DIR/pub_ai_v2_combined.jsonl"
POD_ID=""
SSH_HOST=""
SSH_PORT=""

# ---------------------------------------------------------------------------
# Generate runpod_template.json (always, regardless of API key)
# ---------------------------------------------------------------------------
log "Generating runpod_template.json..."
cat > "$SCRIPT_DIR/runpod_template.json" << EOF
{
  "name": "pub-ai-v2-training",
  "imageName": "$DOCKER_IMAGE",
  "containerDiskInGb": $CONTAINER_DISK,
  "volumeInGb": $VOLUME_DISK,
  "volumeMountPath": "$VOLUME_MOUNT",
  "gpuCount": 1,
  "gpuTypeId": "$GPU_TYPE_PRIMARY",
  "ports": "8888/http,22/tcp",
  "env": [{"key": "HF_TOKEN", "value": ""}, {"key": "WANDB_API_KEY", "value": ""}]
}
EOF
log "Template written to: $SCRIPT_DIR/runpod_template.json"

# ---------------------------------------------------------------------------
# Manual instructions helper (used when no API key is available)
# ---------------------------------------------------------------------------
print_manual_instructions() {
    echo ""
    echo "=================================================================="
    echo "  MANUAL RUNPOD SETUP INSTRUCTIONS"
    echo "=================================================================="
    echo ""
    echo "1. Go to https://www.runpod.io/console/pods"
    echo "2. Click 'Deploy' and select 'GPU Cloud'"
    echo "3. Choose GPU:"
    echo "   Primary:  $GPU_TYPE_PRIMARY"
    echo "   Fallback: $GPU_TYPE_FALLBACK"
    echo "4. Set Docker image:"
    echo "   $DOCKER_IMAGE"
    echo "5. Set volumes:"
    echo "   Container disk: ${CONTAINER_DISK} GB"
    echo "   Volume disk:    ${VOLUME_DISK} GB"
    echo "   Volume mount:   $VOLUME_MOUNT"
    echo "6. Add environment variables:"
    echo "   HF_TOKEN      = $HF_TOKEN"
    echo "   WANDB_API_KEY = ${WANDB_API_KEY:-}"
    echo "7. Expose ports: 8888/http, 22/tcp"
    echo "8. Click Deploy and wait for RUNNING status."
    echo ""
    echo "Once SSH is available, run from this machine:"
    echo ""
    echo "  scp -P <PORT> -o StrictHostKeyChecking=no \\"
    echo "    $SCRIPT_DIR/train_v2.py \\"
    echo "    $SCRIPT_DIR/build_dataset_v2.py \\"
    echo "    root@<HOST>:/workspace/"
    echo ""
    echo "  ssh -p <PORT> -o StrictHostKeyChecking=no root@<HOST> \\"
    echo "    'cd /workspace && pip install -q unsloth transformers peft trl datasets accelerate bitsandbytes wandb tqdm huggingface_hub && python build_dataset_v2.py --output pub_ai_v2_combined.jsonl && python train_v2.py 2>&1 | tee training.log'"
    echo ""
    echo "Template JSON saved to: $SCRIPT_DIR/runpod_template.json"
    echo "=================================================================="
}

# ---------------------------------------------------------------------------
# If no RUNPOD_API_KEY: show manual instructions and exit
# ---------------------------------------------------------------------------
if [[ -z "${RUNPOD_API_KEY:-}" ]]; then
    print_manual_instructions
    exit 0
fi

# ---------------------------------------------------------------------------
# Create RunPod pod via GraphQL API
# ---------------------------------------------------------------------------
log "Creating RunPod pod (primary GPU: $GPU_TYPE_PRIMARY)..."

create_pod_response=$(curl -s -X POST "https://api.runpod.io/graphql" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $RUNPOD_API_KEY" \
  -d "{\"query\": \"mutation { podFindAndDeployOnDemand(input: { cloudType: SECURE, gpuCount: 1, volumeInGb: $VOLUME_DISK, containerDiskInGb: $CONTAINER_DISK, gpuTypeId: \\\"$GPU_TYPE_PRIMARY\\\", name: \\\"pub-ai-v2-training\\\", dockerImage: \\\"$DOCKER_IMAGE\\\", volumeMountPath: \\\"$VOLUME_MOUNT\\\", env: [{key: \\\"HF_TOKEN\\\", value: \\\"$HF_TOKEN\\\"}, {key: \\\"WANDB_API_KEY\\\", value: \\\"${WANDB_API_KEY:-}\\\"}] }) { id desiredStatus } }\"}")

# Try to extract pod ID; if primary GPU unavailable, try fallback
POD_ID=$(echo "$create_pod_response" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    pod = d.get('data', {}).get('podFindAndDeployOnDemand')
    if pod and pod.get('id'):
        print(pod['id'])
    else:
        errors = d.get('errors', [])
        msg = errors[0]['message'] if errors else 'Unknown error'
        print('ERROR:' + msg, file=sys.stderr)
        sys.exit(1)
except Exception as e:
    print('ERROR:' + str(e), file=sys.stderr)
    sys.exit(1)
" 2>/tmp/runpod_err) || {
    warn "Primary GPU ($GPU_TYPE_PRIMARY) unavailable: $(cat /tmp/runpod_err)"
    log "Trying fallback GPU: $GPU_TYPE_FALLBACK..."

    create_pod_response=$(curl -s -X POST "https://api.runpod.io/graphql" \
      -H "Content-Type: application/json" \
      -H "Authorization: Bearer $RUNPOD_API_KEY" \
      -d "{\"query\": \"mutation { podFindAndDeployOnDemand(input: { cloudType: SECURE, gpuCount: 1, volumeInGb: $VOLUME_DISK, containerDiskInGb: $CONTAINER_DISK, gpuTypeId: \\\"$GPU_TYPE_FALLBACK\\\", name: \\\"pub-ai-v2-training\\\", dockerImage: \\\"$DOCKER_IMAGE\\\", volumeMountPath: \\\"$VOLUME_MOUNT\\\", env: [{key: \\\"HF_TOKEN\\\", value: \\\"$HF_TOKEN\\\"}, {key: \\\"WANDB_API_KEY\\\", value: \\\"${WANDB_API_KEY:-}\\\"}] }) { id desiredStatus } }\"}")

    POD_ID=$(echo "$create_pod_response" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    pod = d.get('data', {}).get('podFindAndDeployOnDemand')
    if pod and pod.get('id'):
        print(pod['id'])
    else:
        errors = d.get('errors', [])
        msg = errors[0]['message'] if errors else 'Unknown error'
        print('ERROR:' + msg, file=sys.stderr)
        sys.exit(1)
except Exception as e:
    print('ERROR:' + str(e), file=sys.stderr)
    sys.exit(1)
") || {
        err "Failed to create pod on both GPU types."
        err "Response: $create_pod_response"
        print_manual_instructions
        exit 1
    }
}

log "Pod created. ID: $POD_ID"

# ---------------------------------------------------------------------------
# Poll pod status until RUNNING (max 5 minutes)
# ---------------------------------------------------------------------------
log "Waiting for pod to reach RUNNING status (max 5 min)..."
RUNNING=false

for i in $(seq 1 30); do
    status_response=$(curl -s -X POST "https://api.runpod.io/graphql" \
      -H "Content-Type: application/json" \
      -H "Authorization: Bearer $RUNPOD_API_KEY" \
      -d "{\"query\": \"query { pod(input: { podId: \\\"$POD_ID\\\" }) { id desiredStatus runtime { ports { ip publicPort isIpPublic privatePort type } } } }\"}")

    status=$(echo "$status_response" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d['data']['pod']['desiredStatus'])
except:
    print('UNKNOWN')
")

    log "Attempt $i/30: pod status = $status"

    if [[ "$status" == "RUNNING" ]]; then
        RUNNING=true
        break
    fi

    sleep 10
done

if [[ "$RUNNING" != "true" ]]; then
    err "Pod did not reach RUNNING state within 5 minutes."
    err "Check https://www.runpod.io/console/pods for pod ID: $POD_ID"
    exit 1
fi

log "Pod is RUNNING."

# ---------------------------------------------------------------------------
# Get SSH connection details
# ---------------------------------------------------------------------------
log "Retrieving SSH connection details..."

ssh_response=$(curl -s -X POST "https://api.runpod.io/graphql" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $RUNPOD_API_KEY" \
  -d "{\"query\": \"query { pod(input: { podId: \\\"$POD_ID\\\" }) { runtime { ports { ip publicPort isIpPublic privatePort type } } } }\"}")

SSH_HOST=$(echo "$ssh_response" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    ports = d['data']['pod']['runtime']['ports']
    for p in ports:
        if str(p.get('privatePort')) == '22':
            print(p['ip'])
            break
except Exception as e:
    print('', file=sys.stderr)
" 2>/dev/null)

SSH_PORT=$(echo "$ssh_response" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    ports = d['data']['pod']['runtime']['ports']
    for p in ports:
        if str(p.get('privatePort')) == '22':
            print(p['publicPort'])
            break
except Exception as e:
    print('22', file=sys.stderr)
" 2>/dev/null)

if [[ -z "$SSH_HOST" ]]; then
    err "Could not determine SSH host. Check pod runtime in RunPod dashboard."
    exit 1
fi

log "SSH connection: root@$SSH_HOST port $SSH_PORT"

# ---------------------------------------------------------------------------
# Upload training scripts via scp
# ---------------------------------------------------------------------------
log "Uploading training scripts to pod..."

FILES_TO_UPLOAD=(
    "$SCRIPT_DIR/train_v2.py"
    "$SCRIPT_DIR/build_dataset_v2.py"
)

# Upload optional scripts if they exist
for optional_script in "$SCRIPT_DIR/generate_tool_dataset.py" "$SCRIPT_DIR/generate_synthetic_data.py"; do
    if [[ -f "$optional_script" ]]; then
        FILES_TO_UPLOAD+=("$optional_script")
        log "Including: $(basename "$optional_script")"
    else
        warn "Optional script not found, skipping: $(basename "$optional_script")"
    fi
done

# Upload pre-built dataset if available locally
if [[ -f "$DATASET_LOCAL" ]]; then
    log "Pre-built dataset found locally ($DATASET_LOCAL). Uploading..."
    FILES_TO_UPLOAD+=("$DATASET_LOCAL")
else
    warn "Local dataset not found at $DATASET_LOCAL. It will be built on the pod."
fi

scp -P "$SSH_PORT" \
    -o StrictHostKeyChecking=no \
    -o ConnectTimeout=30 \
    "${FILES_TO_UPLOAD[@]}" \
    "root@$SSH_HOST:/workspace/" && log "Files uploaded successfully." || {
    err "SCP upload failed. Check SSH access."
    exit 1
}

# ---------------------------------------------------------------------------
# Launch training via SSH (background)
# ---------------------------------------------------------------------------
log "Launching training on pod (running in background)..."

ssh -o StrictHostKeyChecking=no \
    -o ConnectTimeout=30 \
    -p "$SSH_PORT" \
    "root@$SSH_HOST" "
    set -e
    cd /workspace

    echo '[setup] Installing Python dependencies...'
    pip install -q unsloth transformers peft trl datasets accelerate bitsandbytes wandb tqdm huggingface_hub 2>&1 | tail -5

    echo '[setup] Building dataset (if not present)...'
    if [ ! -f pub_ai_v2_combined.jsonl ]; then
        python build_dataset_v2.py --output pub_ai_v2_combined.jsonl
    else
        echo '[setup] Dataset already present, skipping build.'
    fi

    echo '[train] Starting training...'
    python train_v2.py 2>&1 | tee training.log
" &
TRAINING_PID=$!

log "Training launched in background (local PID: $TRAINING_PID)."

# ---------------------------------------------------------------------------
# Print monitoring instructions
# ---------------------------------------------------------------------------
echo ""
echo "=================================================================="
echo "  TRAINING LAUNCHED"
echo "=================================================================="
echo ""
echo "  Pod ID      : $POD_ID"
echo "  SSH host    : $SSH_HOST"
echo "  SSH port    : $SSH_PORT"
echo ""
echo "  To monitor training:"
echo "    ssh -p $SSH_PORT -o StrictHostKeyChecking=no root@$SSH_HOST \\"
echo "      'tail -f /workspace/training.log'"
echo ""
echo "  To check GPU usage:"
echo "    ssh -p $SSH_PORT -o StrictHostKeyChecking=no root@$SSH_HOST 'watch -n2 nvidia-smi'"
echo ""
if [[ -n "${WANDB_API_KEY:-}" ]]; then
    echo "  W&B dashboard: https://wandb.ai (run name: pub-ai-v2)"
    echo ""
fi
echo "  Model will be pushed to:"
echo "    LoRA   : https://huggingface.co/suckunalol/pub-ai-v2-lora"
echo "    Merged : https://huggingface.co/suckunalol/pub-ai-v2"
echo "    GGUF   : https://huggingface.co/suckunalol/pub-ai-v2-GGUF"
echo ""
echo "  IMPORTANT: Remember to stop the pod when training is complete"
echo "  to avoid unnecessary charges:"
echo "    https://www.runpod.io/console/pods"
echo "=================================================================="
