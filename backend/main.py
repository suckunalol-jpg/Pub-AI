from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup — import all models first so SQLAlchemy metadata is populated
    import db.models  # noqa: F401
    from db.database import init_db
    await init_db()
    print(f"[Pub AI] Database initialized")
    print(f"[Pub AI] AI Provider: {settings.AI_PROVIDER} / {settings.AI_MODEL}")

    # TODO: Initialize Redis connection pool when needed
    # import redis.asyncio as aioredis
    # app.state.redis = aioredis.from_url(settings.REDIS_URL)

    yield

    # Shutdown
    from ai.provider import ai_provider
    await ai_provider.close()
    print("[Pub AI] Shutdown complete")


app = FastAPI(
    title="Pub AI",
    description="AI-powered coding assistant with agent orchestration",
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

app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(agents_router)
app.include_router(teams_router)
app.include_router(workflows_router)
app.include_router(execute_router)
app.include_router(roblox_router)
app.include_router(knowledge_router)


@app.get("/health")
async def health_check():
    return {
        "status": "online",
        "ai_provider": settings.AI_PROVIDER,
        "ai_model": settings.AI_MODEL,
    }
