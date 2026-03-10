from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./pub_ai.db"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # Pub AI Model — HuggingFace Inference API
    HF_INFERENCE_URL: str = ""
    HF_API_TOKEN: str = ""

    # Pub AI Model — Ollama (local dev)
    OLLAMA_HOST: str = ""

    # Model identifier (e.g. llama-3.3-70b-versatile for Groq)
    MODEL_IDENTIFIER: str = ""

    # Auth
    SECRET_KEY: str = "CHANGE-ME-IN-PRODUCTION"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 24 hours
    API_KEY_PREFIX: str = "pub_"

    # CORS
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:5173"

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    # Execution sandbox
    EXEC_TIMEOUT_SECONDS: int = 10
    EXEC_MAX_OUTPUT_BYTES: int = 65536

    model_config = {"env_file": ["../.env", ".env"], "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
