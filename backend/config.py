from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/pub_ai"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # AI Provider: "claude", "openai", "ollama"
    AI_PROVIDER: str = "claude"
    AI_API_KEY: str = ""
    AI_MODEL: str = "claude-sonnet-4-20250514"

    # Ollama (only used when AI_PROVIDER=ollama)
    OLLAMA_HOST: str = "http://localhost:11434"

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
