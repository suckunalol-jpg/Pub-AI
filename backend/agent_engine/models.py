"""
Model provider for Agent Engine — adapted from Agent Zero's models.py.
Uses LiteLLM for multi-provider support (Ollama, OpenAI, Anthropic, HuggingFace, etc.)
"""

import os
import logging
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, Awaitable, Optional, List
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# ── Model Configuration ───────────────────────────────────────

class ModelType:
    CHAT = "Chat"
    EMBEDDING = "Embedding"


@dataclass
class ModelConfig:
    """Configuration for a single model (chat, utility, embedding, etc.)."""
    type: str = ModelType.CHAT
    provider: str = "ollama"          # ollama, openai, anthropic, huggingface, etc.
    name: str = ""                     # model name (e.g. "deepseek-r1:14b")
    api_base: str = ""                 # base URL for the API
    ctx_length: int = 8192             # context window size
    vision: bool = False               # supports vision/images
    limit_requests: int = 0            # rate limit: requests per minute
    limit_input: int = 0               # rate limit: input tokens per minute
    limit_output: int = 0              # rate limit: output tokens per minute
    kwargs: dict = field(default_factory=dict)  # extra kwargs for the provider

    def build_kwargs(self) -> dict:
        """Build kwargs dict for LiteLLM."""
        kw = dict(self.kwargs)
        if self.api_base:
            kw["api_base"] = self.api_base
        return kw


# ── Chat Result ───────────────────────────────────────────────

@dataclass
class ChatResult:
    """Result from a chat model call."""
    response: str = ""
    reasoning: str = ""


# ── LiteLLM Chat Wrapper ─────────────────────────────────────

class ChatModel:
    """Wrapper around LiteLLM for streaming chat completions."""

    def __init__(self, config: ModelConfig):
        self.config = config
        self._model_string = self._build_model_string()

    def _build_model_string(self) -> str:
        """Build the LiteLLM model string (e.g., 'ollama/deepseek-r1:14b')."""
        provider = self.config.provider.lower()
        name = self.config.name

        # Map common provider names to LiteLLM format
        provider_map = {
            "ollama": f"ollama/{name}",
            "openai": name,  # OpenAI models don't need prefix
            "anthropic": f"anthropic/{name}",
            "huggingface": f"huggingface/{name}",
            "groq": f"groq/{name}",
            "together": f"together_ai/{name}",
            "openrouter": f"openrouter/{name}",
            "lm_studio": f"openai/{name}",  # LM Studio uses OpenAI-compatible API
        }

        return provider_map.get(provider, f"{provider}/{name}")

    async def chat(
        self,
        messages: list[dict],
        stream: bool = True,
        response_callback: Optional[Callable[[str, str], Awaitable[None]]] = None,
        reasoning_callback: Optional[Callable[[str, str], Awaitable[None]]] = None,
        **kwargs,
    ) -> ChatResult:
        """
        Send messages to the LLM and return the response.
        Supports streaming with callbacks for real-time output.
        """
        import litellm

        result = ChatResult()
        extra_kwargs = self.config.build_kwargs()
        extra_kwargs.update(kwargs)

        try:
            if stream and response_callback:
                # Streaming mode
                response = await litellm.acompletion(
                    model=self._model_string,
                    messages=messages,
                    stream=True,
                    **extra_kwargs,
                )

                async for chunk in response:
                    delta = chunk.choices[0].delta if chunk.choices else None
                    if delta:
                        # Handle reasoning/thinking tokens
                        reasoning_content = getattr(delta, "reasoning_content", None)
                        if reasoning_content:
                            result.reasoning += reasoning_content
                            if reasoning_callback:
                                await reasoning_callback(reasoning_content, result.reasoning)

                        # Handle response content
                        content = delta.content or ""
                        if content:
                            result.response += content
                            if response_callback:
                                await response_callback(content, result.response)
            else:
                # Non-streaming mode
                response = await litellm.acompletion(
                    model=self._model_string,
                    messages=messages,
                    stream=False,
                    **extra_kwargs,
                )
                result.response = response.choices[0].message.content or ""

        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            raise

        return result


# ── Local HuggingFace Chat Model ─────────────────────────────

class LocalHFChatModel:
    """Chat model backed by a local HuggingFace model (transformers or vLLM)."""

    def __init__(self, config: ModelConfig, backend):
        self.config = config
        self._backend = backend  # LocalTransformersBackend or LocalVLLMBackend

    async def chat(
        self,
        messages: list[dict],
        stream: bool = True,
        response_callback: Optional[Callable[[str, str], Awaitable[None]]] = None,
        reasoning_callback: Optional[Callable[[str, str], Awaitable[None]]] = None,
        **kwargs,
    ) -> ChatResult:
        """Generate a response using the local backend, matching ChatModel interface."""
        result = ChatResult()
        try:
            result.response = await self._backend.generate(
                messages,
                max_tokens=kwargs.get("max_tokens", 4096),
                stream_callback=response_callback if stream else None,
            )
        except Exception as e:
            logger.error(f"Local HF model call failed: {e}")
            raise
        return result


# ── Embedding Model ──────────────────────────────────────────

class EmbeddingModel:
    """Wrapper for embedding models."""

    def __init__(self, config: ModelConfig):
        self.config = config

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a list of texts."""
        import litellm

        model_string = f"{self.config.provider}/{self.config.name}"
        extra_kwargs = self.config.build_kwargs()

        try:
            response = await litellm.aembedding(
                model=model_string,
                input=texts,
                **extra_kwargs,
            )
            return [item["embedding"] for item in response.data]
        except Exception as e:
            logger.error(f"Embedding call failed: {e}")
            raise


# ── Factory Functions ─────────────────────────────────────────

def get_chat_model(config: ModelConfig):
    """Create a ChatModel (or LocalHFChatModel) from a ModelConfig."""
    if config.provider == "local_hf":
        from agent_engine.local_models import LocalTransformersBackend
        backend = LocalTransformersBackend(
            model_path=config.name,
            device=config.kwargs.get("device", "auto"),
            quantization=config.kwargs.get("quantization") or None,
        )
        return LocalHFChatModel(config, backend)
    if config.provider == "local_vllm":
        from agent_engine.local_models import LocalVLLMBackend
        backend = LocalVLLMBackend(
            base_url=config.api_base,
            model_name=config.name or None,
        )
        return LocalHFChatModel(config, backend)
    return ChatModel(config)


def get_embedding_model(config: ModelConfig) -> EmbeddingModel:
    """Create an EmbeddingModel from a ModelConfig."""
    return EmbeddingModel(config)


# ── Default Config from Environment ──────────────────────────

def default_chat_config() -> ModelConfig:
    """Build a default chat model config from environment variables."""
    provider = os.getenv("AI_PROVIDER", "ollama")
    model_name = os.getenv("MODEL_IDENTIFIER", "deepseek-r1:14b")
    api_base = os.getenv("OLLAMA_HOST", "http://localhost:11434")

    # Auto-detect provider from env (priority order)
    local_hf = os.getenv("LOCAL_HF_MODEL", "")
    if local_hf:
        return ModelConfig(
            type=ModelType.CHAT,
            provider="local_hf",
            name=local_hf,
            ctx_length=int(os.getenv("MODEL_CTX_LENGTH", "8192")),
            kwargs={
                "device": os.getenv("LOCAL_MODEL_DEVICE", "auto"),
                "quantization": os.getenv("LOCAL_MODEL_QUANTIZATION", ""),
            },
        )

    if os.getenv("VLLM_API_URL"):
        # vLLM on GCP TPU or any server — OpenAI-compatible API
        provider = "openai"
        api_base = os.getenv("VLLM_API_URL", "")
    elif os.getenv("HF_INFERENCE_URL"):
        provider = "huggingface"
        api_base = os.getenv("HF_INFERENCE_URL", "")
    elif os.getenv("OPENAI_API_KEY"):
        provider = "openai"
        api_base = os.getenv("OPENAI_API_BASE", "")

    return ModelConfig(
        type=ModelType.CHAT,
        provider=provider,
        name=model_name,
        api_base=api_base,
        ctx_length=int(os.getenv("MODEL_CTX_LENGTH", "8192")),
    )


def default_utility_config() -> ModelConfig:
    """Build a utility model config (used for summaries, parsing, etc.)."""
    # Use same model as chat by default, can be overridden
    config = default_chat_config()
    config.name = os.getenv("UTILITY_MODEL", config.name)
    return config


def default_embedding_config() -> ModelConfig:
    """Build an embedding model config."""
    return ModelConfig(
        type=ModelType.EMBEDDING,
        provider=os.getenv("EMBED_PROVIDER", "huggingface"),
        name=os.getenv("EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2"),
    )
