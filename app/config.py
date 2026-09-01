"""Environment-driven settings shared across ingestion, retrieval, and evaluation."""

from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

EmbeddingProviderName = Literal["openai", "deterministic", "sbert"]
LexicalRanker = Literal["ts_rank_cd", "bm25"]
BM25Idf = Literal["lucene", "robertson"]

DEFAULT_BM25_K1 = 1.2
DEFAULT_BM25_B = 0.75
DEFAULT_BM25_IDF: BM25Idf = "lucene"


class Settings(BaseSettings):
    """Runtime settings for corpus persistence and vector storage."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://filing:filing@localhost:5432/filing"
    corpus_dir: Path = Path("data/corpus")
    embedding_provider: EmbeddingProviderName = "deterministic"
    embedding_model: str = "text-embedding-3-small"
    sbert_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embed_dim: Literal[384] = 384
    embedding_batch_size: int = Field(default=128, gt=0, le=2048)
    openai_api_key: SecretStr | None = None
    # Read only by the corpus acquisition command. The DART client takes the key as an
    # argument so no library code reaches the process environment for a credential.
    dart_api_key: SecretStr | None = None
    # Read only by the corpus acquisition command. SEC requires a declared contact in
    # User-Agent and throttles clients that omit one, so the corpus cannot be fetched
    # without naming an operator.
    sec_user_agent: str | None = None
    lexical_ranker: LexicalRanker = "ts_rank_cd"
    # Commands pass this flag explicitly so measured runs record whether Korean queries
    # skipped the English lexical component. The retrieval service never reads Settings.
    query_language_routing: bool = False
    bm25_k1: float = Field(default=DEFAULT_BM25_K1, gt=0, allow_inf_nan=False)
    bm25_b: float = Field(default=DEFAULT_BM25_B, ge=0, le=1, allow_inf_nan=False)
    bm25_idf: BM25Idf = DEFAULT_BM25_IDF
    # The review workflow stays fail-closed (typed 503) until a model is named. Pricing
    # is required with the model because the provider budget cannot estimate cost
    # without it, and a guessed price would silently misreport spend.
    review_model: str | None = None
    review_max_input_tokens: int = Field(default=60_000, gt=0)
    review_max_output_tokens: int = Field(default=4_000, gt=0)
    review_max_cost_usd: Decimal = Field(default=Decimal("0.50"), ge=0)
    review_input_price_per_million_usd: Decimal | None = Field(default=None, ge=0)
    review_output_price_per_million_usd: Decimal | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def require_openai_api_key(self) -> Self:
        """Require an explicit nonblank API key for the OpenAI provider."""
        if self.embedding_provider == "openai" and (
            self.openai_api_key is None or not self.openai_api_key.get_secret_value().strip()
        ):
            raise ValueError("OPENAI_API_KEY is required when EMBEDDING_PROVIDER=openai")
        return self

    @model_validator(mode="after")
    def require_review_configuration(self) -> Self:
        """Require the key and both prices whenever a review model is configured."""
        if self.review_model is None:
            return self
        if not self.review_model.strip():
            raise ValueError("REVIEW_MODEL must not be blank when set")
        if self.openai_api_key is None or not self.openai_api_key.get_secret_value().strip():
            raise ValueError("OPENAI_API_KEY is required when REVIEW_MODEL is set")
        if (
            self.review_input_price_per_million_usd is None
            or self.review_output_price_per_million_usd is None
        ):
            raise ValueError(
                "REVIEW_INPUT_PRICE_PER_MILLION_USD and REVIEW_OUTPUT_PRICE_PER_MILLION_USD "
                "are required when REVIEW_MODEL is set"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide validated settings instance."""
    return Settings()
