"""Local HuggingFace model backends for Pub-AI."""
import asyncio
import json
import logging
from typing import Optional, Callable, Awaitable

logger = logging.getLogger(__name__)


class LocalTransformersBackend:
    """Run HF models locally via transformers library."""

    def __init__(self, model_path: str, device: str = "auto", quantization: str = None):
        self.model_path = model_path
        self.device = device
        self.quantization = quantization
        self._model = None
        self._tokenizer = None

    def _load(self):
        """Lazy-load model and tokenizer."""
        if self._model is not None:
            return
        from transformers import AutoModelForCausalLM, AutoTokenizer

        load_kwargs = {"device_map": self.device}
        if self.quantization == "4bit":
            from transformers import BitsAndBytesConfig
            load_kwargs["quantization_config"] = BitsAndBytesConfig(load_in_4bit=True)
        elif self.quantization == "8bit":
            from transformers import BitsAndBytesConfig
            load_kwargs["quantization_config"] = BitsAndBytesConfig(load_in_8bit=True)

        logger.info(f"Loading local model: {self.model_path} (device={self.device}, quant={self.quantization})")
        self._tokenizer = AutoTokenizer.from_pretrained(self.model_path)
        self._model = AutoModelForCausalLM.from_pretrained(self.model_path, **load_kwargs)
        logger.info("Local model loaded successfully.")

    async def generate(self, messages: list[dict], max_tokens: int = 4096,
                       stream_callback: Optional[Callable[[str, str], Awaitable[None]]] = None) -> str:
        """Generate response from messages."""
        self._load()
        loop = asyncio.get_event_loop()

        def _generate():
            # Apply chat template
            if hasattr(self._tokenizer, "apply_chat_template"):
                input_ids = self._tokenizer.apply_chat_template(
                    messages, return_tensors="pt"
                ).to(self._model.device)
            else:
                # Fallback: concatenate messages
                text = "\n".join(f"{m['role']}: {m['content']}" for m in messages)
                input_ids = self._tokenizer.encode(text, return_tensors="pt").to(self._model.device)

            outputs = self._model.generate(
                input_ids, max_new_tokens=max_tokens, do_sample=True, temperature=0.7
            )
            response = self._tokenizer.decode(
                outputs[0][input_ids.shape[1]:], skip_special_tokens=True
            )
            return response

        result = await loop.run_in_executor(None, _generate)
        if stream_callback:
            await stream_callback(result, result)
        return result


class LocalVLLMBackend:
    """Connect to a local vLLM server (OpenAI-compatible API)."""

    def __init__(self, base_url: str = "http://localhost:8000", model_name: str = None):
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name

    async def generate(self, messages: list[dict], max_tokens: int = 4096,
                       stream_callback: Optional[Callable[[str, str], Awaitable[None]]] = None) -> str:
        """Generate via vLLM's OpenAI-compatible API."""
        import httpx

        async with httpx.AsyncClient(timeout=120) as client:
            # If model_name not set, get first available model
            if not self.model_name:
                resp = await client.get(f"{self.base_url}/v1/models")
                models = resp.json().get("data", [])
                self.model_name = models[0]["id"] if models else "default"

            payload = {
                "model": self.model_name,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": 0.7,
                "stream": bool(stream_callback),
            }

            if stream_callback:
                full = ""
                async with client.stream(
                    "POST", f"{self.base_url}/v1/chat/completions", json=payload
                ) as resp:
                    async for line in resp.aiter_lines():
                        if line.startswith("data: ") and line != "data: [DONE]":
                            chunk = json.loads(line[6:])
                            delta = chunk["choices"][0].get("delta", {}).get("content", "")
                            if delta:
                                full += delta
                                await stream_callback(delta, full)
                return full
            else:
                resp = await client.post(
                    f"{self.base_url}/v1/chat/completions", json=payload
                )
                data = resp.json()
                return data["choices"][0]["message"]["content"]
