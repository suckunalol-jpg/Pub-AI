---
title: Pub-AI
emoji: "🤖"
colorFrom: purple
colorTo: blue
sdk: gradio
sdk_version: "4.44.1"
app_file: app.py
pinned: false
license: apache-2.0
hardware: zero-a10g
suggested_hardware: zero-a10g
models:
  - suckunalol/pub-ai-merged
---

# Pub-AI — vLLM on ZeroGPU

Serves **suckunalol/pub-ai-merged** as an OpenAI-compatible API.

## API Usage

```bash
curl -X POST https://suckunalol-pub-ai.hf.space/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "Hello!"}],
    "max_tokens": 512,
    "temperature": 0.7
  }'
```

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/v1/chat/completions` | OpenAI-compatible chat |
| GET | `/v1/models` | List available models |
| GET | `/` | Gradio chat UI |

## Notes

- Runs on ZeroGPU (shared GPU, free tier)
- First request may take 30-60s to load the model
- GPU lease is ~120s; idle periods cause reload
