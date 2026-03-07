"""Pub AI provider -- routes inference to the custom model first,
falls back to external APIs only when the custom model is unavailable.

Priority order: vLLM (custom model on Railway) > Ollama (local) > external API (Claude/OpenAI)
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
    provider: str = "unknown"


class PubAIProvider:
    """Unified AI provider that prefers the custom Pub AI model.

    Inference routing:
        1. vLLM server (custom model deployed on Railway or self-hosted)
        2. Ollama (custom model running locally)
        3. External API fallback (Claude or OpenAI)
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
        """Send messages and get a response. Tries custom model first."""

        # Try vLLM (custom model)
        if settings.VLLM_HOST:
            try:
                return await self._vllm(messages, temperature, max_tokens)
            except Exception as e:
                logger.debug("vLLM unavailable: %s", e)

        # Try Ollama (custom model local)
        if settings.OLLAMA_HOST:
            try:
                return await self._ollama_custom(messages, temperature, max_tokens)
            except Exception as e:
                logger.debug("Ollama unavailable: %s", e)

        # Fallback to external API
        provider = settings.AI_PROVIDER.lower()
        model = model or settings.AI_MODEL

        if provider == "claude":
            return await self._claude(messages, model, tools, temperature, max_tokens)
        elif provider == "openai":
            return await self._openai(messages, model, tools, temperature, max_tokens)
        elif provider == "ollama":
            return await self._ollama(messages, model, temperature, max_tokens)
        else:
            raise ValueError(f"No AI provider available")

    async def stream(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]:
        """Stream response tokens from the custom model via vLLM or Ollama."""

        # Try vLLM streaming
        if settings.VLLM_HOST:
            try:
                async for chunk in self._vllm_stream(messages, temperature, max_tokens):
                    yield chunk
                return
            except Exception as e:
                logger.debug("vLLM stream unavailable: %s", e)

        # Try Ollama streaming
        if settings.OLLAMA_HOST:
            try:
                async for chunk in self._ollama_stream(messages, temperature, max_tokens):
                    yield chunk
                return
            except Exception as e:
                logger.debug("Ollama stream unavailable: %s", e)

        # No streaming fallback -- do a full request and yield the result
        response = await self.chat(messages, temperature=temperature, max_tokens=max_tokens)
        yield response.content

    # ---------- vLLM (custom model on Railway / self-hosted) ----------

    async def _vllm(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> AIResponse:
        headers = {"Content-Type": "application/json"}
        if settings.VLLM_API_KEY:
            headers["Authorization"] = f"Bearer {settings.VLLM_API_KEY}"

        start = time.perf_counter()
        resp = await self._client.post(
            f"{settings.VLLM_HOST}/v1/chat/completions",
            headers=headers,
            json={
                "model": settings.VLLM_MODEL_NAME,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
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
            model=data.get("model", "pub-ai"),
            tokens_in=usage.get("prompt_tokens", 0),
            tokens_out=usage.get("completion_tokens", 0),
            latency_ms=latency,
            provider="vllm",
        )

    async def _vllm_stream(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> AsyncIterator[str]:
        import json as json_mod

        headers = {"Content-Type": "application/json"}
        if settings.VLLM_API_KEY:
            headers["Authorization"] = f"Bearer {settings.VLLM_API_KEY}"

        async with self._client.stream(
            "POST",
            f"{settings.VLLM_HOST}/v1/chat/completions",
            headers=headers,
            json={
                "model": settings.VLLM_MODEL_NAME,
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

    # ---------- Ollama (custom model local) ----------

    async def _ollama_custom(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> AIResponse:
        start = time.perf_counter()
        resp = await self._client.post(
            f"{settings.OLLAMA_HOST}/api/chat",
            json={
                "model": settings.OLLAMA_MODEL_NAME,
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
            model=settings.OLLAMA_MODEL_NAME,
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
                "model": settings.OLLAMA_MODEL_NAME,
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

    # ---------- Fallback: Claude ----------

    async def _claude(
        self,
        messages: List[Dict[str, str]],
        model: str,
        tools: Optional[List[Dict]],
        temperature: float,
        max_tokens: int,
    ) -> AIResponse:
        system_content = ""
        chat_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_content = msg["content"]
            else:
                chat_messages.append({"role": msg["role"], "content": msg["content"]})

        body: Dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": chat_messages,
        }
        if system_content:
            body["system"] = system_content
        if tools:
            body["tools"] = tools

        start = time.perf_counter()
        resp = await self._client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": settings.AI_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=body,
        )
        latency = int((time.perf_counter() - start) * 1000)
        resp.raise_for_status()
        data = resp.json()

        content = ""
        for block in data.get("content", []):
            if block.get("type") == "text":
                content += block["text"]

        return AIResponse(
            content=content,
            model=model,
            tokens_in=data.get("usage", {}).get("input_tokens", 0),
            tokens_out=data.get("usage", {}).get("output_tokens", 0),
            latency_ms=latency,
            provider="claude",
        )

    # ---------- Fallback: OpenAI ----------

    async def _openai(
        self,
        messages: List[Dict[str, str]],
        model: str,
        tools: Optional[List[Dict]],
        temperature: float,
        max_tokens: int,
    ) -> AIResponse:
        body: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            body["tools"] = tools

        start = time.perf_counter()
        resp = await self._client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.AI_API_KEY}",
                "Content-Type": "application/json",
            },
            json=body,
        )
        latency = int((time.perf_counter() - start) * 1000)
        resp.raise_for_status()
        data = resp.json()

        choice = data["choices"][0]
        usage = data.get("usage", {})

        return AIResponse(
            content=choice["message"]["content"] or "",
            model=model,
            tokens_in=usage.get("prompt_tokens", 0),
            tokens_out=usage.get("completion_tokens", 0),
            latency_ms=latency,
            provider="openai",
        )

    # ---------- Fallback: Ollama (generic, non-custom model) ----------

    async def _ollama(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> AIResponse:
        start = time.perf_counter()
        resp = await self._client.post(
            f"{settings.OLLAMA_HOST}/api/chat",
            json={
                "model": model,
                "messages": messages,
                "stream": False,
                "options": {
                    "temperature": temperature,
                    "num_predict": max_tokens,
                },
            },
        )
        latency = int((time.perf_counter() - start) * 1000)
        resp.raise_for_status()
        data = resp.json()

        return AIResponse(
            content=data.get("message", {}).get("content", ""),
            model=model,
            tokens_in=data.get("prompt_eval_count", 0),
            tokens_out=data.get("eval_count", 0),
            latency_ms=latency,
            provider="ollama",
        )

    async def close(self):
        await self._client.aclose()


# Singleton -- replaces the old AIProvider
ai_provider = PubAIProvider()
