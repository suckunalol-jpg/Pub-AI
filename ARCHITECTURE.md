# Pub AI — System Architecture

## System Overview

```
                         +------------------+
                         |   Railway Cloud  |
                         +------------------+
                                 |
          +----------------------+----------------------+
          |                      |                      |
  +-------v--------+   +--------v-------+   +----------v---------+
  |  Next.js Web   |   |  FastAPI Core  |   |   PostgreSQL DB    |
  |  (Frontend)    |<->|  (Backend API) |<->|   + Redis Cache    |
  +----------------+   +--------+-------+   +--------------------+
                                |
          +---------------------+---------------------+
          |            |              |                |
  +-------v---+ +-----v------+ +----v------+ +-------v--------+
  |  Agent    | | Code Exec  | | Knowledge | | Roblox HTTP    |
  |  Engine   | | Sandbox    | | Base      | | Bridge         |
  +-----------+ +------------+ +-----------+ +----------------+
                                                      |
                                              +-------v--------+
                                              | Roblox Client  |
                                              | (Lua GUI)      |
                                              +----------------+
```

## Directory Structure

```
pub-ai/
├── frontend/                    # Next.js 14 App Router
│   ├── app/
│   │   ├── layout.tsx           # Root layout with fonts, metadata
│   │   ├── page.tsx             # Landing/chat page
│   │   ├── globals.css          # Global styles + glassmorphism
│   │   └── api/                 # Next.js API routes (proxy)
│   ├── components/
│   │   ├── BinaryRain.tsx       # Canvas binary rain background
│   │   ├── ChatInterface.tsx    # Main chat with message list
│   │   ├── ChatMessage.tsx      # Individual message bubble
│   │   ├── CodeBlock.tsx        # Syntax highlighted code + copy btn
│   │   ├── Sidebar.tsx          # Navigation sidebar
│   │   ├── AgentPanel.tsx       # Sub-agent management
│   │   ├── WorkflowBuilder.tsx  # Workflow creation UI
│   │   ├── ApiKeyPanel.tsx      # Roblox API key management
│   │   ├── KnowledgeUpload.tsx  # Feed training data
│   │   └── GlassCard.tsx        # Reusable glassmorphism card
│   ├── lib/
│   │   ├── api.ts               # Backend API client
│   │   └── utils.ts             # Shared utilities
│   ├── public/
│   │   └── fonts/               # Arcade font files
│   ├── tailwind.config.ts
│   ├── next.config.js
│   ├── package.json
│   └── tsconfig.json
│
├── backend/                     # FastAPI Python
│   ├── main.py                  # App entry, CORS, lifespan
│   ├── config.py                # Settings via pydantic-settings
│   ├── api/
│   │   ├── __init__.py
│   │   ├── chat.py              # POST /api/chat
│   │   ├── agents.py            # /api/agents CRUD + spawn
│   │   ├── teams.py             # /api/teams CRUD
│   │   ├── workflows.py         # /api/workflows CRUD + run
│   │   ├── execute.py           # POST /api/execute (code sandbox)
│   │   ├── roblox.py            # /api/roblox/* endpoints
│   │   ├── knowledge.py         # /api/knowledge upload + query
│   │   └── auth.py              # /api/auth keys + login
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── orchestrator.py      # Agent spawning + coordination
│   │   ├── base_agent.py        # Base agent class
│   │   ├── code_agent.py        # Code-specialized agent
│   │   ├── team_manager.py      # Agent team coordination
│   │   └── workflow_engine.py   # Workflow execution engine
│   ├── ai/
│   │   ├── __init__.py
│   │   ├── provider.py          # AI provider abstraction (Claude/OpenAI/Ollama)
│   │   ├── prompts.py           # System prompts + templates
│   │   └── tools.py             # Tool definitions for agents
│   ├── db/
│   │   ├── __init__.py
│   │   ├── database.py          # SQLAlchemy engine + session
│   │   ├── models.py            # All ORM models
│   │   └── migrations/          # Alembic migrations
│   ├── executor/
│   │   ├── __init__.py
│   │   ├── sandbox.py           # Code execution sandbox
│   │   └── languages.py         # Language-specific runners
│   ├── knowledge/
│   │   ├── __init__.py
│   │   ├── vectordb.py          # ChromaDB integration
│   │   └── ingest.py            # Document ingestion pipeline
│   ├── roblox/
│   │   ├── __init__.py
│   │   ├── bridge.py            # Roblox HTTP bridge logic
│   │   └── lua_tools.py         # Lua/Luau analysis tools
│   ├── requirements.txt
│   └── Dockerfile
│
├── roblox/
│   ├── PubAI_Client.lua         # Main Roblox GUI client
│   └── modules/
│       ├── scanner.lua          # Script scanner module
│       └── api.lua              # HTTP API communication
│
├── docker-compose.yml           # Local development
├── railway.toml                 # Railway deployment config
├── .env.example                 # Environment template
└── .gitignore
```

## Database Schema (PostgreSQL)

### users
| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| username | VARCHAR(100) | |
| email | VARCHAR(255) | Unique, nullable |
| hashed_password | VARCHAR(255) | |
| role | VARCHAR(20) | admin/user |
| created_at | TIMESTAMP | |

### api_keys
| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| user_id | UUID | FK -> users |
| key_hash | VARCHAR(255) | SHA256 of key |
| key_prefix | VARCHAR(10) | First 8 chars for display |
| name | VARCHAR(100) | User label |
| platform | VARCHAR(20) | web/roblox/api |
| is_active | BOOLEAN | |
| created_at | TIMESTAMP | |
| last_used_at | TIMESTAMP | |

### conversations
| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| user_id | UUID | FK -> users |
| title | VARCHAR(255) | Auto-generated |
| platform | VARCHAR(20) | web/roblox |
| metadata | JSONB | Extra context |
| created_at | TIMESTAMP | |
| updated_at | TIMESTAMP | |

### messages
| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| conversation_id | UUID | FK -> conversations |
| role | VARCHAR(20) | user/assistant/system |
| content | TEXT | Message text |
| model_used | VARCHAR(50) | Which AI model |
| tokens_in | INTEGER | Input tokens |
| tokens_out | INTEGER | Output tokens |
| latency_ms | INTEGER | Response time |
| created_at | TIMESTAMP | |

### feedback
| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| message_id | UUID | FK -> messages |
| user_id | UUID | FK -> users |
| rating | SMALLINT | 1=dislike, 2=like |
| comment | TEXT | Optional text |
| created_at | TIMESTAMP | |

### agent_sessions
| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| conversation_id | UUID | FK -> conversations |
| agent_type | VARCHAR(50) | coder/researcher/etc |
| agent_name | VARCHAR(100) | |
| status | VARCHAR(20) | running/completed/failed |
| parent_agent_id | UUID | FK -> self (sub-agents) |
| config | JSONB | Agent configuration |
| result | JSONB | Final output |
| created_at | TIMESTAMP | |
| completed_at | TIMESTAMP | |

### workflows
| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| user_id | UUID | FK -> users |
| name | VARCHAR(100) | |
| description | TEXT | |
| steps | JSONB | Ordered step definitions |
| created_at | TIMESTAMP | |

### workflow_runs
| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| workflow_id | UUID | FK -> workflows |
| status | VARCHAR(20) | running/completed/failed |
| step_results | JSONB | Per-step outputs |
| started_at | TIMESTAMP | |
| completed_at | TIMESTAMP | |

### knowledge_entries
| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| user_id | UUID | FK -> users |
| title | VARCHAR(255) | |
| content | TEXT | Raw text |
| source_type | VARCHAR(50) | qa/doc/code/manual |
| embedding_id | VARCHAR(100) | ChromaDB reference |
| created_at | TIMESTAMP | |

### execution_logs
| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| user_id | UUID | FK -> users |
| language | VARCHAR(30) | python/js/lua/etc |
| code | TEXT | Submitted code |
| output | TEXT | Execution output |
| exit_code | INTEGER | |
| duration_ms | INTEGER | |
| created_at | TIMESTAMP | |

## API Endpoints

### Auth
- `POST /api/auth/register` — Create account
- `POST /api/auth/login` — Get JWT token
- `POST /api/auth/api-keys` — Generate API key
- `GET /api/auth/api-keys` — List user's keys
- `DELETE /api/auth/api-keys/{id}` — Revoke key

### Chat
- `POST /api/chat` — Send message, get AI response
- `GET /api/chat/conversations` — List conversations
- `GET /api/chat/conversations/{id}` — Get conversation history
- `POST /api/chat/feedback` — Like/dislike a message

### Agents
- `POST /api/agents/spawn` — Spawn sub-agent
- `GET /api/agents/{id}` — Get agent status
- `POST /api/agents/{id}/message` — Send message to agent
- `DELETE /api/agents/{id}` — Stop agent

### Teams
- `POST /api/teams` — Create agent team
- `GET /api/teams/{id}` — Get team status
- `POST /api/teams/{id}/agents` — Add agent to team
- `DELETE /api/teams/{id}` — Dissolve team

### Workflows
- `POST /api/workflows` — Create workflow
- `GET /api/workflows` — List workflows
- `POST /api/workflows/{id}/run` — Execute workflow
- `GET /api/workflows/{id}/runs/{run_id}` — Get run status

### Execute
- `POST /api/execute` — Run code in sandbox
- `GET /api/execute/languages` — List supported languages

### Knowledge
- `POST /api/knowledge/ingest` — Upload training data
- `POST /api/knowledge/query` — Search knowledge base
- `GET /api/knowledge/entries` — List entries

### Roblox
- `POST /api/roblox/chat` — Roblox-specific chat (Lua/Luau context)
- `POST /api/roblox/scan` — Analyze Lua script
- `POST /api/roblox/decompile` — Decompile script
- `GET /api/roblox/status` — Connection health check

## Agent Orchestration Design

### Agent Types
1. **CodeAgent** — Writes, reviews, debugs code
2. **ResearchAgent** — Searches knowledge base, web
3. **ExecutorAgent** — Runs code, validates output
4. **RobloxAgent** — Lua/Luau specialized

### Sub-Agent Spawning
```python
# Parent agent can spawn children
child = orchestrator.spawn(
    agent_type="code",
    task="Write a REST API endpoint",
    context=parent_context,
    parent_id=parent_agent.id
)
```

### Team Coordination
```python
team = team_manager.create_team(
    name="Feature Build",
    agents=[
        {"type": "code", "role": "backend"},
        {"type": "code", "role": "frontend"},
        {"type": "research", "role": "docs"},
    ]
)
team.execute(task="Build user authentication")
```

### Workflow Engine
Steps execute sequentially or in parallel:
```json
{
  "steps": [
    {"id": "1", "type": "ai", "prompt": "Design the API"},
    {"id": "2", "type": "code", "language": "python", "depends_on": ["1"]},
    {"id": "3", "type": "execute", "depends_on": ["2"]},
    {"id": "4", "type": "ai", "prompt": "Review output", "depends_on": ["3"]}
  ]
}
```

## Frontend Component Hierarchy

```
App (layout.tsx)
├── BinaryRain (fullscreen canvas background)
├── Sidebar
│   ├── Logo (Pub++ arcade font)
│   ├── NavItems (Chat, Agents, Workflows, Knowledge, Roblox)
│   └── UserMenu
├── MainContent
│   ├── ChatInterface
│   │   ├── MessageList
│   │   │   └── ChatMessage[]
│   │   │       └── CodeBlock (syntax + copy)
│   │   └── InputBar
│   ├── AgentPanel
│   │   ├── SpawnAgent
│   │   ├── AgentList
│   │   └── TeamBuilder
│   ├── WorkflowBuilder
│   │   ├── StepEditor
│   │   └── RunHistory
│   ├── KnowledgeUpload
│   │   ├── FileDropzone
│   │   └── EntryList
│   └── ApiKeyPanel (Roblox keys)
└── StatusBar (connection, model info)
```

## Roblox Integration Protocol

1. User generates API key on web panel (platform=roblox)
2. User puts API key + URL in Roblox client script
3. Client sends HTTP POST to `/api/roblox/chat` with:
   ```json
   {"api_key": "pub_xxx", "message": "scan workspace", "context": {"place_id": 123, "game_name": "..."}}
   ```
4. Backend authenticates key, routes to RobloxAgent
5. Response includes: text reply, optional code modifications, scan results
6. Client can self-modify its GUI based on AI responses

## Tech Stack
- **Frontend**: Next.js 14, TypeScript, Tailwind CSS, Framer Motion
- **Backend**: Python 3.11+, FastAPI, SQLAlchemy 2.0, Alembic, Pydantic v2
- **Database**: PostgreSQL 16, Redis 7
- **AI**: Anthropic Claude API / OpenAI API / Ollama (configurable)
- **Knowledge**: ChromaDB for vector embeddings
- **Execution**: subprocess sandboxing with resource limits
- **Deployment**: Railway, Docker
