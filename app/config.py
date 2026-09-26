"""Environment-driven settings shared across ingestion, retrieval, and evaluation."""

from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Final, Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import SettingsConfigDict

from app.openai_models import resolve_openai_model
from app.settings_sources import ProviderSettings

EmbeddingProviderName = Literal["openai", "deterministic", "sbert"]
LexicalRanker = Literal["ts_rank_cd", "bm25"]
BM25Idf = Literal["lucene", "robertson"]

DEFAULT_BM25_K1 = 1.2
DEFAULT_BM25_B = 0.75
DEFAULT_BM25_IDF: BM25Idf = "lucene"
EMBEDDING_DIMENSIONS: Final = 384


class Settings(ProviderSettings):
    """Runtime settings for corpus persistence and vector storage."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://filing:filing@localhost:5432/filing"
    corpus_dir: Path = Path("data/corpus")
    embedding_provider: EmbeddingProviderName = "deterministic"
    embedding_model: str = "text-embedding-3-large"
    sbert_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embed_dim: Literal[384] = EMBEDDING_DIMENSIONS
    embedding_batch_size: int = Field(default=128, gt=0, le=2048)
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
    # The review workflow stays fail-closed (typed 503) until a model is named. The
    # model policy supplies the price, so the provider budget never estimates cost from a
    # guessed or manually configured value.
    review_model: str | None = None
    review_max_input_tokens: int = Field(default=60_000, gt=0)
    review_max_output_tokens: int = Field(default=4_000, gt=0)
    review_max_cost_usd: Decimal = Field(default=Decimal("0.50"), ge=0)

    @field_validator("embed_dim", mode="before")
    @classmethod
    def parse_embedding_dimension(cls, value: object) -> object:
        """Accept the fixed dimension from string-valued environment settings."""
        return (
            EMBEDDING_DIMENSIONS
            if isinstance(value, str) and value.strip() == str(EMBEDDING_DIMENSIONS)
            else value
        )

    @property
    def local_llm_enabled(self) -> bool:
        """Report whether the optional local engine may be assembled at all.

        Notes
        -----
        `MODE=prod` disables it whatever the endpoint keys say. A deployment must not be
        able to answer from an unvetted local model just because a stray variable
        survived in the environment, and this property is the only gate the provider
        map and the readiness probe both consult.
        """
        return self.environment != "prod" and self.local_llm_base_url is not None

    @model_validator(mode="after")
    def require_openai_api_key(self) -> Self:
        """Require an explicit nonblank API key for the OpenAI provider."""
        resolve_openai_model("embedding", self.embedding_model)
        if self.embedding_provider == "openai" and self.openai_api_key is None:
            raise ValueError(
                "The MODE-selected OpenAI key slot is required when EMBEDDING_PROVIDER=openai"
            )
        return self

    @model_validator(mode="after")
    def require_review_configuration(self) -> Self:
        """Require the key and a policy-approved model whenever a review model is configured."""
        if self.review_model is None:
            return self
        if not self.review_model.strip():
            raise ValueError("REVIEW_MODEL must not be blank when set")
        if self.openai_api_key is None:
            raise ValueError(
                "The MODE-selected OpenAI key slot is required when REVIEW_MODEL is set"
            )
        resolve_openai_model("review", self.review_model)
        return self


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide validated settings instance."""
    return Settings()
