import json
import os
from pathlib import Path
from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./pub_ai.db"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # Pub AI Model — vLLM on GCP TPU (OpenAI-compatible)
    VLLM_API_URL: str = ""

    # Pub AI Model — HuggingFace Inference API
    HF_INFERENCE_URL: str = ""
    HF_API_TOKEN: str = ""

    # Pub AI Model — Ollama (local dev)
    OLLAMA_HOST: str = ""

    # Model identifier (e.g. llama-3.3-70b-versatile for Groq)
    MODEL_IDENTIFIER: str = ""

    # AI Provider override (auto-detected if not set)
    AI_PROVIDER: str = ""

    # Auth
    SECRET_KEY: str = "CHANGE-ME-IN-PRODUCTION"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 24 hours
    API_KEY_PREFIX: str = "pub_"

    # CORS
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:5173"

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    # Local HuggingFace model (transformers backend)
    LOCAL_HF_MODEL: str = ""              # Path to local HF model (empty = disabled)
    LOCAL_MODEL_DEVICE: str = "auto"      # "auto", "cuda", "cpu"
    LOCAL_MODEL_QUANTIZATION: str = ""    # "", "4bit", "8bit"

    # MCP Servers — JSON array of server configs, or path to config file
    # Format: [{"name": "server", "command": "npx", "args": [...], "env": {}}]
    MCP_SERVERS: str = ""  # JSON string from env, or empty to use ~/.pub-ai/mcp_servers.json

    # Execution sandbox
    EXEC_TIMEOUT_SECONDS: int = 10
    EXEC_MAX_OUTPUT_BYTES: int = 65536

    # Workspace containers (per-agent Kali Linux Docker containers)
    WORKSPACE_IMAGE: str = "pubai-workspace:latest"
    WORKSPACE_CPU_LIMIT: float = 2.0
    WORKSPACE_MEMORY_LIMIT: str = "4g"
    WORKSPACE_PID_LIMIT: int = 512
    WORKSPACE_NETWORK_MODE: str = "bridge"
    WORKSPACE_IDLE_TIMEOUT_MINUTES: int = 30
    WORKSPACE_EXEC_TIMEOUT: int = 120
    WORKSPACE_MAX_OUTPUT_BYTES: int = 131072
    WORKSPACE_ENABLED: bool = True
    WORKSPACE_PRIVILEGED: bool = True
    WORKSPACE_VNC_ENABLED: bool = True
    WORKSPACE_VNC_BASE_PORT: int = 6080
    WORKSPACE_AUTO_INSTALL: bool = True

    model_config = {"env_file": ["../.env", ".env"], "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()


def get_mcp_server_configs() -> list[dict]:
    """Load MCP server configurations from env var or ~/.pub-ai/mcp_servers.json."""
    # 1. Try the env var / settings field (JSON string)
    if settings.MCP_SERVERS:
        try:
            configs = json.loads(settings.MCP_SERVERS)
            if isinstance(configs, list):
                return configs
        except json.JSONDecodeError:
            pass

    # 2. Try the config file
    config_path = Path.home() / ".pub-ai" / "mcp_servers.json"
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                configs = json.load(f)
            if isinstance(configs, list):
                return configs
        except (json.JSONDecodeError, OSError):
            pass

    return []
