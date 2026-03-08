"""Models API -- register, list, update, delete, activate, and test AI model endpoints.

This powers the multi-model support feature. Each RegisteredModel record describes
a remote (or local) inference endpoint that Pub AI can route chat requests to.
"""

import uuid
from datetime import datetime
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import get_current_user_from_token
from db.database import get_db
from db.models import RegisteredModel, User

router = APIRouter(prefix="/api/models", tags=["models"])


# ---------- Schemas ----------

class ModelCreate(BaseModel):
    name: str
    provider_type: str  # "huggingface" | "ollama" | "openai-compatible"
    endpoint_url: str
    api_token: Optional[str] = None
    model_identifier: str
    is_active: bool = False
    config: dict = {}


class ModelUpdate(BaseModel):
    name: Optional[str] = None
    provider_type: Optional[str] = None
    endpoint_url: Optional[str] = None
    api_token: Optional[str] = None
    model_identifier: Optional[str] = None
    is_active: Optional[bool] = None
    config: Optional[dict] = None


class ModelOut(BaseModel):
    id: uuid.UUID
    name: str
    provider_type: str
    endpoint_url: str
    api_token: Optional[str] = None
    model_identifier: str
    is_active: bool
    config: dict
    created_at: datetime
    updated_at: datetime
    created_by: Optional[uuid.UUID] = None

    model_config = {"from_attributes": True}


class ModelTestResult(BaseModel):
    status: str  # "ok" | "error"
    latency_ms: Optional[int] = None
    detail: Optional[str] = None


# ---------- Helpers ----------

VALID_PROVIDER_TYPES = {"huggingface", "ollama", "openai-compatible"}


def _validate_provider_type(provider_type: str) -> None:
    if provider_type not in VALID_PROVIDER_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid provider_type '{provider_type}'. Must be one of: {', '.join(sorted(VALID_PROVIDER_TYPES))}",
        )


# ---------- Routes ----------

@router.post("", response_model=ModelOut, status_code=201)
async def register_model(
    req: ModelCreate,
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    """Register a new model endpoint."""
    _validate_provider_type(req.provider_type)

    # Check uniqueness
    existing = await db.execute(
        select(RegisteredModel).where(RegisteredModel.name == req.name)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Model with name '{req.name}' already exists")

    # If this model is being set as active, deactivate all others first
    if req.is_active:
        await db.execute(
            update(RegisteredModel).values(is_active=False)
        )

    model = RegisteredModel(
        name=req.name,
        provider_type=req.provider_type,
        endpoint_url=req.endpoint_url,
        api_token=req.api_token,
        model_identifier=req.model_identifier,
        is_active=req.is_active,
        config=req.config,
        created_by=user.id,
    )
    db.add(model)
    await db.flush()

    # Invalidate provider cache so it picks up the new model
    from ai.provider import ai_provider
    ai_provider.invalidate_cache()

    return model


@router.get("", response_model=list[ModelOut])
async def list_models(
    db: AsyncSession = Depends(get_db),
):
    """List all registered models."""
    result = await db.execute(
        select(RegisteredModel).order_by(RegisteredModel.created_at)
    )
    return result.scalars().all()


@router.put("/{model_id}", response_model=ModelOut)
async def update_model(
    model_id: uuid.UUID,
    req: ModelUpdate,
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    """Update a registered model."""
    result = await db.execute(
        select(RegisteredModel).where(RegisteredModel.id == model_id)
    )
    model = result.scalar_one_or_none()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")

    if req.provider_type is not None:
        _validate_provider_type(req.provider_type)

    # If activating this model, deactivate all others
    if req.is_active is True:
        await db.execute(
            update(RegisteredModel).values(is_active=False)
        )

    # Apply updates
    update_data = req.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(model, field, value)
    model.updated_at = datetime.utcnow()

    await db.flush()

    from ai.provider import ai_provider
    ai_provider.invalidate_cache()

    return model


@router.delete("/{model_id}")
async def delete_model(
    model_id: uuid.UUID,
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    """Delete a registered model."""
    result = await db.execute(
        select(RegisteredModel).where(RegisteredModel.id == model_id)
    )
    model = result.scalar_one_or_none()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")

    await db.delete(model)
    await db.flush()

    from ai.provider import ai_provider
    ai_provider.invalidate_cache()

    return {"detail": f"Model '{model.name}' deleted"}


@router.post("/{model_id}/activate", response_model=ModelOut)
async def activate_model(
    model_id: uuid.UUID,
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    """Set a model as the active default. Deactivates all others."""
    result = await db.execute(
        select(RegisteredModel).where(RegisteredModel.id == model_id)
    )
    model = result.scalar_one_or_none()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")

    # Deactivate all, then activate target
    await db.execute(
        update(RegisteredModel).values(is_active=False)
    )
    model.is_active = True
    model.updated_at = datetime.utcnow()
    await db.flush()

    from ai.provider import ai_provider
    ai_provider.invalidate_cache()

    return model


@router.post("/{model_id}/test", response_model=ModelTestResult)
async def test_model(
    model_id: uuid.UUID,
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    """Health-check a registered model by sending a minimal inference request."""
    result = await db.execute(
        select(RegisteredModel).where(RegisteredModel.id == model_id)
    )
    model = result.scalar_one_or_none()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")

    import time

    test_messages = [{"role": "user", "content": "ping"}]
    headers: dict = {"Content-Type": "application/json"}
    if model.api_token:
        headers["Authorization"] = f"Bearer {model.api_token}"

    start = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            if model.provider_type == "ollama":
                resp = await client.post(
                    f"{model.endpoint_url.rstrip('/')}/api/chat",
                    json={
                        "model": model.model_identifier,
                        "messages": test_messages,
                        "stream": False,
                        "options": {"num_predict": 1},
                    },
                )
            else:
                # huggingface and openai-compatible both use the OpenAI API shape
                url = model.endpoint_url.rstrip("/")
                if "/v1/" not in url:
                    url = f"{url}/v1/chat/completions"
                resp = await client.post(
                    url,
                    headers=headers,
                    json={
                        "model": model.model_identifier,
                        "messages": test_messages,
                        "max_tokens": 1,
                        "stream": False,
                    },
                )

            latency = int((time.perf_counter() - start) * 1000)
            resp.raise_for_status()
            return ModelTestResult(status="ok", latency_ms=latency)

    except httpx.HTTPStatusError as e:
        latency = int((time.perf_counter() - start) * 1000)
        return ModelTestResult(
            status="error",
            latency_ms=latency,
            detail=f"HTTP {e.response.status_code}: {e.response.text[:200]}",
        )
    except Exception as e:
        latency = int((time.perf_counter() - start) * 1000)
        return ModelTestResult(
            status="error",
            latency_ms=latency,
            detail=str(e)[:300],
        )
