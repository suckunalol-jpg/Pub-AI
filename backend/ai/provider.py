"""Pub AI provider -- multi-model inference router.

Supports registered models from the DB (RegisteredModel table).
Falls back to bootstrap defaults from env vars (HF_INFERENCE_URL / OLLAMA_HOST)
when no models are registered yet.

Provider types:
    - "huggingface"        : HuggingFace Inference API (OpenAI-compat /v1/chat/completions)
    - "ollama"             : Ollama local server (/api/chat)
    - "openai-compatible"  : Any OpenAI-compatible chat completions API
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx

from config import settings

logger = logging.getLogger(__name__)


@dataclass
class AIResponse:
    content: str
    model: str
    tokens_in: int
    tokens_out: int
    latency_ms: int
    provider: str = "pub-ai"


@dataclass
class _ResolvedModel:
    """Internal container for a fully-resolved model's connection details."""
    name: str
    provider_type: str  # huggingface / ollama / openai-compatible
    endpoint_url: str
    api_token: Optional[str]
    model_identifier: str
    config: dict


class PubAIProvider:
    """Routes inference to whichever registered model is requested (or the active default).

    Maintains an in-memory cache of models loaded from the DB.
    Call invalidate_cache() after any DB write that changes RegisteredModel rows.
    """

    def __init__(self):
        self._client = httpx.AsyncClient(timeout=120.0)
        # Cache: name -> _ResolvedModel.  None means "not yet loaded".
        self._cache: Optional[Dict[str, _ResolvedModel]] = None
        self._active_name: Optional[str] = None

    # ------------------------------------------------------------------
    # Cache management
    # ------------------------------------------------------------------

    def invalidate_cache(self) -> None:
        """Call after any RegisteredModel DB mutation."""
        self._cache = None
        self._active_name = None

    async def _ensure_cache(self) -> None:
        """Lazy-load the model registry from the DB if cache is empty."""
        if self._cache is not None:
            return

        self._cache = {}
        self._active_name = None

        try:
            from db.database import async_session
            from db.models import RegisteredModel
            from sqlalchemy import select

            async with async_session() as session:
                result = await session.execute(select(RegisteredModel))
                rows = result.scalars().all()

            for row in rows:
                resolved = _ResolvedModel(
                    name=row.name,
                    provider_type=row.provider_type,
                    endpoint_url=row.endpoint_url,
                    api_token=row.api_token,
                    model_identifier=row.model_identifier,
                    config=row.config or {},
                )
                self._cache[row.name] = resolved
                if row.is_active:
                    self._active_name = row.name

            logger.info(
                "Model registry loaded: %d model(s), active=%s",
                len(self._cache),
                self._active_name or "(none)",
            )
        except Exception as e:
            # During early startup the DB may not be ready yet; fall through to bootstrap.
            logger.debug("Could not load model registry from DB: %s", e)

    async def _resolve(self, model_name: Optional[str] = None) -> _ResolvedModel:
        """Resolve a model name to its connection details.

        Priority:
            1. Explicit model_name parameter (look up in registry)
            2. Active model in registry (is_active=True)
            3. Bootstrap defaults from env vars (HF_INFERENCE_URL / OLLAMA_HOST)
        """
        await self._ensure_cache()

        # 1. Explicit name requested
        if model_name and self._cache and model_name in self._cache:
            return self._cache[model_name]

        # 2. Active default from registry
        if self._active_name and self._cache and self._active_name in self._cache:
            return self._cache[self._active_name]

        # 3. Bootstrap: build a temporary _ResolvedModel from env vars
        if settings.HF_INFERENCE_URL:
            return _ResolvedModel(
                name="pub-ai",
                provider_type="huggingface",
                endpoint_url=settings.HF_INFERENCE_URL,
                api_token=settings.HF_API_TOKEN or None,
                model_identifier="pub-ai",
                config={},
            )

        if settings.OLLAMA_HOST:
            return _ResolvedModel(
                name="pub-ai",
                provider_type="ollama",
                endpoint_url=settings.OLLAMA_HOST,
                api_token=None,
                model_identifier="pub-ai",
                config={},
            )

        raise RuntimeError(
            "No model available. Register a model via /api/models or set HF_INFERENCE_URL / OLLAMA_HOST."
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        tools: Optional[List[Dict]] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> AIResponse:
        """Send a chat completion request to the resolved model."""
        resolved = await self._resolve(model)

        # Allow per-model config overrides for temperature / max_tokens
        temperature = resolved.config.get("default_temperature", temperature)
        max_tokens = resolved.config.get("default_max_tokens", max_tokens)

        if resolved.provider_type == "ollama":
            return await self._ollama_chat(resolved, messages, temperature, max_tokens)
        else:
            # huggingface and openai-compatible share the same OpenAI API shape
            return await self._openai_chat(resolved, messages, temperature, max_tokens)

    async def stream(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]:
        """Stream response tokens from the resolved model."""
        resolved = await self._resolve(model)

        temperature = resolved.config.get("default_temperature", temperature)
        max_tokens = resolved.config.get("default_max_tokens", max_tokens)

        if resolved.provider_type == "ollama":
            async for chunk in self._ollama_stream(resolved, messages, temperature, max_tokens):
                yield chunk
        else:
            async for chunk in self._openai_stream(resolved, messages, temperature, max_tokens):
                yield chunk

    # ------------------------------------------------------------------
    # OpenAI-compatible (covers HuggingFace + openai-compatible)
    # ------------------------------------------------------------------

    async def _openai_chat(
        self,
        model: _ResolvedModel,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> AIResponse:
        url = model.endpoint_url.rstrip("/")
        if "/v1/" not in url:
            url = f"{url}/v1/chat/completions"

        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if model.api_token:
            headers["Authorization"] = f"Bearer {model.api_token}"

        start = time.perf_counter()
        resp = await self._client.post(
            url,
            headers=headers,
            json={
                "model": model.model_identifier,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": False,
            },
            timeout=120.0,
        )
        latency = int((time.perf_counter() - start) * 1000)
        resp.raise_for_status()
        data = resp.json()

        choice = data["choices"][0]
        usage = data.get("usage", {})

        return AIResponse(
            content=choice["message"]["content"] or "",
            model=model.name,
            tokens_in=usage.get("prompt_tokens", 0),
            tokens_out=usage.get("completion_tokens", 0),
            latency_ms=latency,
            provider=model.provider_type,
        )

    async def _openai_stream(
        self,
        model: _ResolvedModel,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> AsyncIterator[str]:
        import json as json_mod

        url = model.endpoint_url.rstrip("/")
        if "/v1/" not in url:
            url = f"{url}/v1/chat/completions"

        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if model.api_token:
            headers["Authorization"] = f"Bearer {model.api_token}"

        async with self._client.stream(
            "POST",
            url,
            headers=headers,
            json={
                "model": model.model_identifier,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": True,
            },
            timeout=120.0,
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line.startswith("data: ") and line != "data: [DONE]":
                    chunk = json_mod.loads(line[6:])
                    delta = chunk["choices"][0].get("delta", {})
                    if "content" in delta:
                        yield delta["content"]

    # ------------------------------------------------------------------
    # Ollama
    # ------------------------------------------------------------------

    async def _ollama_chat(
        self,
        model: _ResolvedModel,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> AIResponse:
        start = time.perf_counter()
        resp = await self._client.post(
            f"{model.endpoint_url.rstrip('/')}/api/chat",
            json={
                "model": model.model_identifier,
                "messages": messages,
                "stream": False,
                "options": {
                    "temperature": temperature,
                    "num_predict": max_tokens,
                },
            },
            timeout=120.0,
        )
        latency = int((time.perf_counter() - start) * 1000)
        resp.raise_for_status()
        data = resp.json()

        return AIResponse(
            content=data.get("message", {}).get("content", ""),
            model=model.name,
            tokens_in=data.get("prompt_eval_count", 0),
            tokens_out=data.get("eval_count", 0),
            latency_ms=latency,
            provider="ollama",
        )

    async def _ollama_stream(
        self,
        model: _ResolvedModel,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> AsyncIterator[str]:
        import json as json_mod

        async with self._client.stream(
            "POST",
            f"{model.endpoint_url.rstrip('/')}/api/chat",
            json={
                "model": model.model_identifier,
                "messages": messages,
                "stream": True,
                "options": {
                    "temperature": temperature,
                    "num_predict": max_tokens,
                },
            },
            timeout=120.0,
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line:
                    chunk = json_mod.loads(line)
                    content = chunk.get("message", {}).get("content", "")
                    if content:
                        yield content

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self):
        await self._client.aclose()


ai_provider = PubAIProvider()
