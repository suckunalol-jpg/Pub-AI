"""
Pub-AI HuggingFace Spaces — vLLM OpenAI-compatible API on ZeroGPU.

Serves suckunalol/pub-ai-merged via:
  1. OpenAI-compatible /v1/chat/completions (POST)
  2. Gradio chat UI (for browser users)
"""

import spaces
import gradio as gr
import json
import time
import uuid
from typing import Optional

# ---------------------------------------------------------------------------
# Global model handle — loaded once on first GPU call, then cached.
# ZeroGPU gives you an H200 slice; the model stays in VRAM for the
# duration of the lease (typically 60-120 s).  Subsequent calls within
# the lease reuse the same engine.
# ---------------------------------------------------------------------------
_ENGINE = None
MODEL_ID = "suckunalol/pub-ai-merged"


def _get_engine():
    """Lazy-init the vLLM engine (runs inside a @spaces.GPU context)."""
    global _ENGINE
    if _ENGINE is None:
        from vllm import LLM
        _ENGINE = LLM(
            model=MODEL_ID,
            trust_remote_code=True,
            max_model_len=4096,       # keep conservative for free tier
            dtype="auto",
            # gpu_memory_utilization adjusted for shared H200
            gpu_memory_utilization=0.90,
        )
    return _ENGINE


# ---------------------------------------------------------------------------
# Core inference — decorated with @spaces.GPU so ZeroGPU allocates hardware
# ---------------------------------------------------------------------------
@spaces.GPU(duration=120)
def generate(messages: list[dict], max_tokens: int = 1024,
             temperature: float = 0.7, top_p: float = 0.95,
             stop: Optional[list[str]] = None):
    """Run chat completion and return the assistant reply string."""
    from vllm import SamplingParams

    engine = _get_engine()

    # Build a simple chat prompt.  If the tokenizer has a chat template
    # vLLM will use it automatically via engine.chat(); otherwise we
    # fall back to a manual format.
    try:
        outputs = engine.chat(
            messages=[messages],
            sampling_params=SamplingParams(
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                stop=stop or [],
            ),
            use_tqdm=False,
        )
        text = outputs[0].outputs[0].text
    except Exception:
        # Fallback: format manually and use engine.generate()
        prompt = _format_messages(messages)
        outputs = engine.generate(
            [prompt],
            sampling_params=SamplingParams(
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                stop=stop or [],
            ),
            use_tqdm=False,
        )
        text = outputs[0].outputs[0].text

    return text


def _format_messages(messages: list[dict]) -> str:
    """Simple fallback chat formatter if the tokenizer lacks a template."""
    parts = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        if role == "system":
            parts.append(f"<|system|>\n{content}")
        elif role == "user":
            parts.append(f"<|user|>\n{content}")
        elif role == "assistant":
            parts.append(f"<|assistant|>\n{content}")
    parts.append("<|assistant|>\n")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# OpenAI-compatible /v1/chat/completions endpoint
# ---------------------------------------------------------------------------
def openai_chat_completions(body: dict) -> dict:
    """
    Accepts an OpenAI ChatCompletion request body, returns a response
    in the same schema.
    """
    messages = body.get("messages", [])
    max_tokens = body.get("max_tokens", 1024)
    temperature = body.get("temperature", 0.7)
    top_p = body.get("top_p", 0.95)
    stop = body.get("stop", None)
    model = body.get("model", MODEL_ID)

    text = generate(
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
        top_p=top_p,
        stop=stop,
    )

    completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    created = int(time.time())

    return {
        "id": completion_id,
        "object": "chat.completion",
        "created": created,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": -1,     # TODO: wire up real token counts
            "completion_tokens": -1,
            "total_tokens": -1,
        },
    }


# ---------------------------------------------------------------------------
# Gradio chat UI — for people who visit the Space in a browser
# ---------------------------------------------------------------------------
def gradio_chat(message: str, history: list[list[str]]):
    """Gradio ChatInterface callback."""
    messages = []
    messages.append({
        "role": "system",
        "content": "You are Pub-AI, a helpful coding assistant.",
    })
    for user_msg, bot_msg in history:
        messages.append({"role": "user", "content": user_msg})
        if bot_msg:
            messages.append({"role": "assistant", "content": bot_msg})
    messages.append({"role": "user", "content": message})

    return generate(messages=messages)


# ---------------------------------------------------------------------------
# Build the Gradio app with the API endpoint mounted
# ---------------------------------------------------------------------------
with gr.Blocks(title="Pub-AI") as demo:
    gr.Markdown("# Pub-AI Chat\nPowered by `suckunalol/pub-ai-merged` on ZeroGPU (vLLM)")
    gr.Markdown(
        "**API usage:** POST to `/v1/chat/completions` with an OpenAI-compatible body.\n\n"
        "```bash\n"
        "curl -X POST https://<your-space>.hf.space/v1/chat/completions \\\n"
        '  -H "Content-Type: application/json" \\\n'
        "  -d '{\"messages\":[{\"role\":\"user\",\"content\":\"Hello\"}]}'\n"
        "```"
    )

    chatbot = gr.ChatInterface(
        fn=gradio_chat,
        title=None,
        examples=["Write a Python hello world", "Explain async/await"],
    )

# Mount the OpenAI-compatible API on Gradio's underlying FastAPI app
app = demo.app  # type: ignore[attr-defined]


@app.post("/v1/chat/completions")
async def chat_completions_endpoint(request: gr.Request):
    """OpenAI-compatible chat completions."""
    body = await request.request.json()  # inner Starlette request
    result = openai_chat_completions(body)
    from starlette.responses import JSONResponse
    return JSONResponse(content=result)


@app.get("/v1/models")
async def list_models():
    """OpenAI-compatible model listing."""
    from starlette.responses import JSONResponse
    return JSONResponse(content={
        "object": "list",
        "data": [
            {
                "id": MODEL_ID,
                "object": "model",
                "created": 1700000000,
                "owned_by": "suckunalol",
            }
        ],
    })


if __name__ == "__main__":
    demo.launch()
