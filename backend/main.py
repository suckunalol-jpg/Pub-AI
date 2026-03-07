from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    import db.models  # noqa: F401
    from db.database import init_db
    await init_db()
    print(f"[Pub AI] Database initialized")
    if settings.HF_INFERENCE_URL:
        print(f"[Pub AI] Model: HuggingFace @ {settings.HF_INFERENCE_URL}")
    elif settings.OLLAMA_HOST:
        print(f"[Pub AI] Model: Ollama @ {settings.OLLAMA_HOST}")
    else:
        print("[Pub AI] WARNING: No model configured! Set HF_INFERENCE_URL or OLLAMA_HOST")

    yield

    from ai.provider import ai_provider
    await ai_provider.close()
    print("[Pub AI] Shutdown complete")


app = FastAPI(
    title="Pub AI",
    description="AI-powered coding assistant — custom model, no third-party AI",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
from api.auth import router as auth_router
from api.chat import router as chat_router
from api.agents import router as agents_router
from api.teams import router as teams_router
from api.workflows import router as workflows_router
from api.execute import router as execute_router
from api.roblox import router as roblox_router
from api.knowledge import router as knowledge_router
from api.training import router as training_router
from api.memory import router as memory_router

app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(agents_router)
app.include_router(teams_router)
app.include_router(workflows_router)
app.include_router(execute_router)
app.include_router(roblox_router)
app.include_router(knowledge_router)
app.include_router(training_router)
app.include_router(memory_router)


@app.get("/health")
async def health_check():
    provider = "huggingface" if settings.HF_INFERENCE_URL else "ollama" if settings.OLLAMA_HOST else "none"
    return {
        "status": "online",
        "model": "pub-ai",
        "provider": provider,
    }
