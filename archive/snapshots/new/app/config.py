from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

LexicalRanker = Literal["ts_rank_cd", "bm25"]
BM25Idf = Literal["lucene", "robertson"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://filing:filing@localhost:5432/filing"
    corpus_dir: Path = Path("data/corpus")
    embedding_provider: Literal["openai", "deterministic", "sbert"] = "openai"
    embedding_model: str = "text-embedding-3-small"
    # Local sentence-transformer used when embedding_provider is "sbert". The
    # default produces exactly 384 dimensions, matching embed_dim and the
    # database column, so no migration is needed to switch.
    sbert_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embed_dim: Literal[384] = 384
    embedding_batch_size: int = Field(default=128, gt=0, le=2048)
    openai_api_key: SecretStr | None = None
    lexical_ranker: LexicalRanker = "ts_rank_cd"
    # The lexical index is built with the "english" text-search configuration, so a
    # Korean query produces no lexical candidates and hybrid fusion silently degrades
    # to the vector arm. Enabling this makes retrieve() skip the lexical component for
    # a Korean query instead, which is observable in ComponentRankings. Off by default:
    # M8 measures the collapse before changing the shipped query path.
    query_language_routing: bool = False
    bm25_k1: float = Field(default=1.2, gt=0)
    bm25_b: float = Field(default=0.75, ge=0, le=1)
    bm25_idf: BM25Idf = "lucene"


@lru_cache
def get_settings() -> Settings:
    return Settings()
