from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings


async def _run_migrations():
    """Run lightweight ALTER TABLE migrations for new columns on existing tables.
    
    SQLAlchemy's create_all() only creates new tables; it cannot add columns to
    existing ones. This function handles that for us.
    """
    from db.database import async_session
    from sqlalchemy import text

    migrations = [
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS preferences_json TEXT",
    ]

    async with async_session() as session:
        for sql in migrations:
            try:
                await session.execute(text(sql))
            except Exception as e:
                # Column might already exist or syntax may differ on SQLite — ignore
                print(f"[Pub AI] Migration note: {e}")
        await session.commit()
    print("[Pub AI] Migrations complete")

async def _ensure_owner_roles():
    """Ensure owner accounts (obinofue1, miz_lean) have role='owner' on startup."""
    from db.database import async_session
    from db.models import User
    from sqlalchemy import select

    owner_usernames = {"obinofue1", "miz_lean"}

    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.username.in_(owner_usernames))
        )
        users = result.scalars().all()
        updated = 0
        for user in users:
            if user.role != "owner":
                user.role = "owner"
                updated += 1
        if updated:
            await session.commit()
            print(f"[Pub AI] Updated {updated} owner account(s)")
        else:
            print("[Pub AI] Owner roles verified")


async def _seed_default_model():
    """Ensure the default 'pub-ai' model matches env vars. Creates or updates as needed."""
    from db.database import async_session
    from db.models import RegisteredModel
    from sqlalchemy import select

    if not settings.HF_INFERENCE_URL and not settings.OLLAMA_HOST:
        print("[Pub AI] WARNING: No model configured! Set HF_INFERENCE_URL or OLLAMA_HOST, or register via /api/models")
        return

    if settings.HF_INFERENCE_URL:
        provider_type = "huggingface"
        endpoint_url = settings.HF_INFERENCE_URL
        api_token = settings.HF_API_TOKEN or None
        model_id = settings.MODEL_IDENTIFIER or "pub-ai"
    elif settings.OLLAMA_HOST:
        provider_type = "ollama"
        endpoint_url = settings.OLLAMA_HOST
        api_token = None
        model_id = settings.MODEL_IDENTIFIER or "pub-ai"
    else:
        print("[Pub AI] WARNING: No model configured! Set HF_INFERENCE_URL or OLLAMA_HOST")
        return

    async with async_session() as session:
        result = await session.execute(
            select(RegisteredModel).where(RegisteredModel.name == "pub-ai")
        )
        model = result.scalar_one_or_none()

        if model:
            model.provider_type = provider_type
            model.endpoint_url = endpoint_url
            model.api_token = api_token
            model.model_identifier = model_id
            model.is_active = True
            print("[Pub AI] Updated default model: %s @ %s (model: %s)" % (provider_type, endpoint_url, model_id))
        else:
            model = RegisteredModel(
                name="pub-ai",
                provider_type=provider_type,
                endpoint_url=endpoint_url,
                api_token=api_token,
                model_identifier=model_id,
                is_active=True,
                config={},
            )
            session.add(model)
            print("[Pub AI] Seeded default model: %s @ %s (model: %s)" % (provider_type, endpoint_url, model_id))

        await session.commit()

    # Invalidate provider cache so it picks up the new model
    from ai.provider import ai_provider
    ai_provider.invalidate_cache()


@asynccontextmanager
async def lifespan(app: FastAPI):
    import db.models  # noqa: F401
    from db.database import init_db
    await init_db()
    print("[Pub AI] Database initialized")

    # Run lightweight migrations for new columns on existing tables
    await _run_migrations()

    # Ensure owner accounts have the correct role
    await _ensure_owner_roles()

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
from api.preferences import router as preferences_router

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
app.include_router(preferences_router)


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
