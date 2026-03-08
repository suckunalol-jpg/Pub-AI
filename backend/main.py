from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings


async def _seed_default_model():
    """If no models are registered yet, create one from env vars so the system works out of the box."""
    from db.database import async_session
    from db.models import RegisteredModel
    from sqlalchemy import select, func

    async with async_session() as session:
        count_result = await session.execute(select(func.count()).select_from(RegisteredModel))
        count = count_result.scalar()
        if count and count > 0:
            return  # models already exist

        if settings.HF_INFERENCE_URL:
            model = RegisteredModel(
                name="pub-ai",
                provider_type="huggingface",
                endpoint_url=settings.HF_INFERENCE_URL,
                api_token=settings.HF_API_TOKEN or None,
                model_identifier="pub-ai",
                is_active=True,
                config={},
            )
            session.add(model)
            await session.commit()
            print("[Pub AI] Seeded default model: HuggingFace @ %s" % settings.HF_INFERENCE_URL)
        elif settings.OLLAMA_HOST:
            model = RegisteredModel(
                name="pub-ai",
                provider_type="ollama",
                endpoint_url=settings.OLLAMA_HOST,
                api_token=None,
                model_identifier="pub-ai",
                is_active=True,
                config={},
            )
            session.add(model)
            await session.commit()
            print("[Pub AI] Seeded default model: Ollama @ %s" % settings.OLLAMA_HOST)
        else:
            print("[Pub AI] WARNING: No model configured! Set HF_INFERENCE_URL or OLLAMA_HOST, or register via /api/models")


@asynccontextmanager
async def lifespan(app: FastAPI):
    import db.models  # noqa: F401
    from db.database import init_db
    await init_db()
    print("[Pub AI] Database initialized")

    # Seed a default model from env vars if the DB has none
    await _seed_default_model()

    # Seed team preset templates
    from api.team_templates import seed_team_presets
    await seed_team_presets()

    # Log which model is active
    from ai.provider import ai_provider
    try:
        resolved = await ai_provider._resolve()
        print(f"[Pub AI] Active model: {resolved.name} ({resolved.provider_type} @ {resolved.endpoint_url})")
    except RuntimeError:
        print("[Pub AI] WARNING: No model available")

    # Start auto-retraining background scheduler
    from training.auto_retrain import auto_retrainer
    auto_retrainer.start()

    yield

    # Stop auto-retrainer before shutdown
    auto_retrainer.stop()
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
from api.models import router as models_router
from api.mcp import router as mcp_router
from api.team_templates import router as team_templates_router

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
app.include_router(models_router)
app.include_router(mcp_router)
app.include_router(team_templates_router)


@app.get("/health")
async def health_check():
    from ai.provider import ai_provider
    try:
        resolved = await ai_provider._resolve()
        return {
            "status": "online",
            "model": resolved.name,
            "provider": resolved.provider_type,
        }
    except RuntimeError:
        return {
            "status": "online",
            "model": "none",
            "provider": "none",
        }
