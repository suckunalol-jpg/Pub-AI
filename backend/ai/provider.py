from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx

from config import settings


@dataclass
class AIResponse:
    content: str
    model: str
    tokens_in: int
    tokens_out: int
    latency_ms: int


class AIProvider:
    """Unified AI provider supporting Claude, OpenAI, and Ollama."""

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
        provider = settings.AI_PROVIDER.lower()
        model = model or settings.AI_MODEL

        if provider == "claude":
            return await self._claude(messages, model, tools, temperature, max_tokens)
        elif provider == "openai":
            return await self._openai(messages, model, tools, temperature, max_tokens)
        elif provider == "ollama":
            return await self._ollama(messages, model, temperature, max_tokens)
        else:
            raise ValueError(f"Unknown AI provider: {provider}")

    async def _claude(
        self,
        messages: List[Dict[str, str]],
        model: str,
        tools: Optional[List[Dict]],
        temperature: float,
        max_tokens: int,
    ) -> AIResponse:
        # Separate system message from the rest
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
        )

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
        )

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
        )

    async def close(self):
        await self._client.aclose()


ai_provider = AIProvider()
