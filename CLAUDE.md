# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Pub AI is a full-stack AI coding agent platform with a custom-trained model. It features autonomous agents with tool-use loops, multi-agent teams, workflow orchestration, Roblox integration, and MCP plugin compatibility.

## Architecture

**Backend** (`backend/`) — FastAPI + SQLAlchemy async + PostgreSQL

- `main.py` — App entrypoint, lifespan (DB init, seed models/presets, start auto-retrainer), all router registration
- `config.py` — Pydantic settings from env vars (DATABASE_URL, HF_INFERENCE_URL, OLLAMA_HOST, SECRET_KEY, etc.)
- `ai/provider.py` — Multi-model inference router. Resolves models from DB (`RegisteredModel`), falls back to env vars. Supports `huggingface`, `ollama`, `openai-compatible` provider types. Streams via SSE.
- `agents/base_agent.py` — Autonomous think→act→observe loop. 6 built-in agent types (coder, researcher, reviewer, executor, planner, roblox). Supports custom agent types via config overrides.
- `agents/tools.py` — 30+ tool definitions agents can invoke (web search, HTTP, code exec, file ops, git, Roblox, sub-agents, memory)
- `agents/team_manager.py` — Creates and manages multi-agent teams
- `agents/workflow_engine.py` — DAG-based workflow execution with dependency resolution
- `agents/orchestrator.py` — Agent lifecycle management (spawn, monitor, stop)
- `db/database.py` — Async engine + session factory. Auto-creates tables via `Base.metadata.create_all`. Supports both PostgreSQL and SQLite.
- `db/models.py` — All SQLAlchemy models: User, Conversation, Message, Feedback, AgentSession, WorkflowRun, ExecutionLog, KnowledgeDoc, RegisteredModel, TeamTemplate, CustomAgentType
- `executor/sandbox.py` — Sandboxed code execution with timeout
- `api/chat.py` — Chat + SSE streaming endpoint (`/api/chat/stream`) with phase detection (thinking/coding/executing/searching)
- `api/mcp.py` — MCP server (JSON-RPC 2.0 at `/mcp`, SSE at `/mcp/sse`) with 5 tools for Claude Code plugin compatibility
- `api/team_templates.py` — Team template CRUD + 4 preset teams + custom agent types + `seed_team_presets()`
- `training/auto_retrain.py` — Background scheduler (10-min loop) that exports ChatML JSONL from conversation data

**Frontend** (`frontend/`) — Next.js 14 + TypeScript + Tailwind CSS

- `app/page.tsx` — Main SPA page
- `components/ChatInterface.tsx` — SSE streaming chat with AbortController, phase tracking, ActionIndicator
- `components/ActionIndicator.tsx` — Animated phase indicators (framer-motion)
- `components/AgentPanel.tsx`, `WorkflowBuilder.tsx`, `TrainingPanel.tsx`, `KnowledgeUpload.tsx` — Feature panels
- `lib/api.ts` — API client with `streamMessage()` SSE helper
- UI style: glassmorphism with blue/black palette, professional and modern

**Roblox** (`roblox/`) — Lua HTTP client (`PubAI_Client.lua`) for in-game AI integration

**Training** (`training/`) — LoRA fine-tuning pipeline targeting Qwen2.5-Coder-32B-Instruct
- `gcloud_train.sh` — Automated Google Cloud GPU VM training script (A100→L4 fallback)
- `build_dataset.py` — Dataset builder from multiple sources
- `PubAI_Training.ipynb` — Jupyter training notebook

## Commands

### Local Development (Docker Compose)
```bash
docker compose up          # Start all services (api:8000, web:3000, db:5432, redis:6379)
docker compose down        # Stop all services
```

### Backend Only
```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

### Frontend Only
```bash
cd frontend
npm install
npm run dev                # Dev server on :3000
npm run build              # Production build
npm run lint               # ESLint
```

### Training
```bash
export HF_TOKEN=<token>
bash training/gcloud_train.sh   # Full automated GPU training on GCloud
```

## Environment Variables

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | PostgreSQL connection (asyncpg) |
| `REDIS_URL` | Redis for caching |
| `HF_INFERENCE_URL` | HuggingFace Inference endpoint |
| `HF_API_TOKEN` | HuggingFace API token |
| `OLLAMA_HOST` | Ollama server URL (local dev) |
| `SECRET_KEY` | JWT signing key |
| `CORS_ORIGINS` | Comma-separated allowed origins |

## Key Patterns

- **DB sessions**: All API routes use `db: AsyncSession = Depends(get_db)` — the session auto-commits on success, auto-rolls-back on exception
- **Model resolution**: `ai_provider._resolve(model_name)` checks DB first, falls back to env vars. Results are cached for 60s.
- **Agent tool calls**: Agents emit `\`\`\`tool\n{json}\n\`\`\`` blocks, results get `\`\`\`result\n{json}\n\`\`\`` blocks. All parsed via regex in `base_agent.py`.
- **SSE streaming**: Chat streaming uses `text/event-stream` with event types: `status`, `token`, `code`, `done`, `error`
- **Auth**: JWT tokens via `python-jose`, bcrypt passwords. `get_current_user_from_token` dependency for protected routes.
- **Deployment**: Railway (single service from `backend/Dockerfile`), health check at `/health`

## API Route Prefixes

All routes are under `/api/`: `auth`, `chat`, `agents`, `teams`, `workflows`, `execute`, `roblox`, `knowledge`, `training`, `memory`, `models`, `mcp`, `team-templates`, `custom-agent-types`
