from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Dict, Optional

from pydantic_settings import BaseSettings


class GPUProvider(str, Enum):
    RUNPOD = "runpod"
    LAMBDA = "lambda"
    LOCAL = "local"


# Default model IDs used for merging and fine-tuning
BASE_MODELS: Dict[str, str] = {
    "deepseek": "deepseek-ai/DeepSeek-Coder-V2-Lite-Instruct",
    "qwen": "Qwen/Qwen2.5-Coder-7B-Instruct",
    "qwen3.5": "Jackrong/Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled",
    "pub-ai-v2": "suckunalol/pub-ai-v2",
}


class TrainingSettings(BaseSettings):
    # GPU provider
    GPU_PROVIDER: str = GPUProvider.LOCAL.value

    # RunPod
    RUNPOD_API_KEY: str = ""
    RUNPOD_ENDPOINT: str = ""

    # Output directories
    TRAINING_OUTPUT_DIR: str = str(Path.home() / "pub-ai-models")
    DATASETS_DIR: str = str(Path.home() / "pub-ai-datasets")

    # vLLM inference server (Railway or self-hosted)
    VLLM_HOST: str = "http://localhost:8000"
    VLLM_API_KEY: str = ""

    # Ollama
    OLLAMA_HOST: str = "http://localhost:11434"
    OLLAMA_MODEL_NAME: str = "pub-ai"

    # Weights & Biases (optional training metrics)
    WANDB_API_KEY: str = ""
    WANDB_PROJECT: str = "pub-ai"

    model_config = {
        "env_file": ["../.env", ".env"],
        "env_file_encoding": "utf-8",
        "extra": "ignore",
        "env_prefix": "TRAIN_",
    }


training_settings = TrainingSettings()
