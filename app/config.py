from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings for corpus persistence and vector storage."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://filing:filing@localhost:5432/filing"
    corpus_dir: Path = Path("data/corpus")
    embedding_provider: Literal["openai", "deterministic"] = "deterministic"
    embedding_model: str = "text-embedding-3-small"
    embed_dim: Literal[384] = 384
    embedding_batch_size: int = Field(default=128, gt=0, le=2048)
    openai_api_key: SecretStr | None = None

    @model_validator(mode="after")
    def require_openai_api_key(self) -> Self:
        """Require an explicit nonblank API key for the OpenAI provider."""
        if self.embedding_provider == "openai" and (
            self.openai_api_key is None or not self.openai_api_key.get_secret_value().strip()
        ):
            raise ValueError("OPENAI_API_KEY is required when EMBEDDING_PROVIDER=openai")
        return self


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide validated settings instance."""
    return Settings()
