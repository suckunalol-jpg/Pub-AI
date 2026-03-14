#!/bin/bash
# Quick check on TPU queue status
gcloud compute tpus queued-resources describe pub-ai-serve-queue \
    --zone=us-central1-a \
    --project=project-c0f48cd5-b1a8-4b31-9e3 \
    --format="yaml(state)" 2>&1
