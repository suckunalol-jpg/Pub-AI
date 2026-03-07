"""Pub AI provider -- serves inference from your custom model only.

Routes: HuggingFace Inference API > Ollama (local)
No external AI. This is YOUR model.
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


class PubAIProvider:
    """Serves inference from the custom Pub AI model.

    Routing:
        1. HuggingFace Inference API (deployed model)
        2. Ollama (local dev)
    """

    def __init__(self):
        self._client = httpx.AsyncClient(timeout=120.0)

    async def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        tools: Optional[List[Dict]] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> AIResponse:
        """Send messages to the Pub AI model."""

        # Try HuggingFace Inference API
        if settings.HF_INFERENCE_URL:
            try:
                return await self._huggingface(messages, temperature, max_tokens)
            except Exception as e:
                logger.warning("HuggingFace Inference unavailable: %s", e)

        # Try Ollama (local)
        if settings.OLLAMA_HOST:
            try:
                return await self._ollama(messages, temperature, max_tokens)
            except Exception as e:
                logger.warning("Ollama unavailable: %s", e)

        raise RuntimeError("Pub AI model is not available. Check HF_INFERENCE_URL or OLLAMA_HOST.")

    async def stream(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]:
        """Stream response tokens from the Pub AI model."""

        # Try HuggingFace streaming
        if settings.HF_INFERENCE_URL:
            try:
                async for chunk in self._huggingface_stream(messages, temperature, max_tokens):
                    yield chunk
                return
            except Exception as e:
                logger.warning("HF stream unavailable: %s", e)

        # Try Ollama streaming
        if settings.OLLAMA_HOST:
            try:
                async for chunk in self._ollama_stream(messages, temperature, max_tokens):
                    yield chunk
                return
            except Exception as e:
                logger.warning("Ollama stream unavailable: %s", e)

        raise RuntimeError("Pub AI model is not available.")

    # ---------- HuggingFace Inference API ----------

    async def _huggingface(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> AIResponse:
        url = settings.HF_INFERENCE_URL.rstrip("/")
        if "/v1/" not in url:
            url = f"{url}/v1/chat/completions"

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings.HF_API_TOKEN}",
        }

        start = time.perf_counter()
        resp = await self._client.post(
            url,
            headers=headers,
            json={
                "model": "pub-ai",
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
            model="pub-ai",
            tokens_in=usage.get("prompt_tokens", 0),
            tokens_out=usage.get("completion_tokens", 0),
            latency_ms=latency,
            provider="huggingface",
        )

    async def _huggingface_stream(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> AsyncIterator[str]:
        import json as json_mod

        url = settings.HF_INFERENCE_URL.rstrip("/")
        if "/v1/" not in url:
            url = f"{url}/v1/chat/completions"

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings.HF_API_TOKEN}",
        }

        async with self._client.stream(
            "POST",
            url,
            headers=headers,
            json={
                "model": "pub-ai",
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

    # ---------- Ollama (local dev) ----------

    async def _ollama(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> AIResponse:
        start = time.perf_counter()
        resp = await self._client.post(
            f"{settings.OLLAMA_HOST}/api/chat",
            json={
                "model": "pub-ai",
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
            model="pub-ai",
            tokens_in=data.get("prompt_eval_count", 0),
            tokens_out=data.get("eval_count", 0),
            latency_ms=latency,
            provider="ollama",
        )

    async def _ollama_stream(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> AsyncIterator[str]:
        import json as json_mod

        async with self._client.stream(
            "POST",
            f"{settings.OLLAMA_HOST}/api/chat",
            json={
                "model": "pub-ai",
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

    async def close(self):
        await self._client.aclose()


ai_provider = PubAIProvider()
