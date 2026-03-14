#!/bin/bash
# =============================================================================
# Pub AI — vLLM Server on GCP TPU
# =============================================================================
# Waits for the queued TPU to become ready, installs vLLM, starts serving,
# and sets up an SSH tunnel so the CLI can connect at localhost:8000.
#
# Usage:
#   bash start-vllm-server.sh
# =============================================================================

set -euo pipefail

# ---- Configuration ----
TPU_NAME="pub-ai-serve"
QUEUE_NAME="pub-ai-serve-queue"
ZONE="us-central1-a"
PROJECT="project-c0f48cd5-b1a8-4b31-9e3"
MODEL="suckunalol/pub-ai-merged"
PORT=8000

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

log()     { echo -e "${BLUE}[Pub AI]${NC} $1"; }
success() { echo -e "${GREEN}[OK]${NC} $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $1"; }
error()   { echo -e "${RED}[ERROR]${NC} $1"; }

# ---- Phase 1: Wait for TPU ----
log "Waiting for queued TPU resource to be provisioned..."
log "Queue: $QUEUE_NAME in $ZONE"
log ""
log "This may take minutes to hours depending on capacity."
log "You can check status anytime with:"
log "  gcloud compute tpus queued-resources describe $QUEUE_NAME --zone=$ZONE"
log ""

while true; do
    STATE=$(gcloud compute tpus queued-resources describe "$QUEUE_NAME" \
        --zone="$ZONE" \
        --project="$PROJECT" \
        --format="value(state.state)" 2>/dev/null || echo "UNKNOWN")

    case "$STATE" in
        ACTIVE)
            success "TPU is ACTIVE and ready!"
            break
            ;;
        WAITING_FOR_RESOURCES)
            echo -ne "\r  Status: WAITING_FOR_RESOURCES... ($(date '+%H:%M:%S'))  "
            sleep 30
            ;;
        FAILED)
            error "Queue request FAILED. Check:"
            error "  gcloud compute tpus queued-resources describe $QUEUE_NAME --zone=$ZONE"
            exit 1
            ;;
        *)
            echo -ne "\r  Status: $STATE... ($(date '+%H:%M:%S'))  "
            sleep 15
            ;;
    esac
done

# ---- Phase 2: Install vLLM on TPU ----
log "Installing vLLM on TPU VM..."

gcloud compute tpus tpu-vm ssh "$TPU_NAME" \
    --zone="$ZONE" \
    --project="$PROJECT" \
    --command='
set -euo pipefail
echo "=== Installing vLLM for TPU ==="
pip install --quiet --upgrade pip
pip install vllm torch_xla[tpu] -f https://storage.googleapis.com/libtpu-releases/index.html 2>/dev/null || \
    pip install vllm
pip install huggingface_hub
echo "=== vLLM installed ==="
'

success "vLLM installed"

# ---- Phase 3: Start vLLM server ----
log "Starting vLLM server with model: $MODEL"

gcloud compute tpus tpu-vm ssh "$TPU_NAME" \
    --zone="$ZONE" \
    --project="$PROJECT" \
    --command="
nohup python -m vllm.entrypoints.openai.api_server \
    --host 0.0.0.0 \
    --port $PORT \
    --model '$MODEL' \
    --max-model-len 4096 \
    --dtype auto \
    > ~/vllm_serve.log 2>&1 &

echo \$! > ~/vllm_serve.pid
echo 'vLLM server starting (PID: '\$(cat ~/vllm_serve.pid)')'
echo 'Waiting for server to be ready...'

# Wait for server to start
for i in \$(seq 1 60); do
    if curl -s http://localhost:$PORT/health > /dev/null 2>&1; then
        echo 'vLLM server is READY!'
        exit 0
    fi
    sleep 5
    echo \"  Waiting... (\${i}/60)\"
done
echo 'Server may still be loading. Check: tail -f ~/vllm_serve.log'
"

success "vLLM server started on TPU"

# ---- Phase 4: SSH Tunnel ----
log ""
log "========================================="
log "  vLLM Server is Running!"
log "========================================="
log ""
log "  Model: $MODEL"
log "  TPU:   $TPU_NAME ($ZONE)"
log ""
log "  Starting SSH tunnel (localhost:$PORT -> TPU:$PORT)..."
log "  Keep this terminal open to maintain the tunnel."
log ""
log "  Your CLI is configured to connect at:"
log "    VLLM_API_URL=http://localhost:$PORT"
log ""
log "  Open a new terminal and run:"
log "    python pub-ai.py"
log ""
log "========================================="
log ""

# Start SSH tunnel (blocks - keeps connection alive)
gcloud compute tpus tpu-vm ssh "$TPU_NAME" \
    --zone="$ZONE" \
    --project="$PROJECT" \
    -- -N -L ${PORT}:localhost:${PORT}
