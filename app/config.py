"""Environment-driven settings shared across ingestion, retrieval, and evaluation."""

from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import (
    AliasChoices,
    Field,
    PrivateAttr,
    SecretStr,
    ValidationInfo,
    field_validator,
    model_validator,
)
from pydantic_settings import SettingsConfigDict

from app.openai_models import resolve_openai_model
from app.settings_sources import (
    DEFAULT_LOCAL_BASE_URL,
    DEFAULT_LOCAL_TIMEOUT_S,
    DotenvFirstSettings,
    Environment,
    KeySlot,
    resolve_openai_key,
)

EmbeddingProviderName = Literal["openai", "deterministic", "sbert"]
LexicalRanker = Literal["ts_rank_cd", "bm25"]
BM25Idf = Literal["lucene", "robertson"]

DEFAULT_BM25_K1 = 1.2
DEFAULT_BM25_B = 0.75
DEFAULT_BM25_IDF: BM25Idf = "lucene"


class Settings(DotenvFirstSettings):
    """Runtime settings for corpus persistence and vector storage."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://filing:filing@localhost:5432/filing"
    corpus_dir: Path = Path("data/corpus")
    embedding_provider: EmbeddingProviderName = "deterministic"
    embedding_model: str = "text-embedding-3-large"
    sbert_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embed_dim: Literal[384] = 384
    embedding_batch_size: int = Field(default=128, gt=0, le=2048)
    # MODE selects an isolated development or production credential slot.
    environment: Environment = Field(
        default="dev", validation_alias=AliasChoices("MODE", "DOCREVIEW_ENVIRONMENT")
    )
    openai_api_key_dev: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("OPENAI_API_KEY_LOCAL", "OPENAI_API_KEY_DEV"),
    )
    openai_api_key_prod: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("OPENAI_API_KEY_PROD")
    )
    _openai_key_slot: KeySlot | None = PrivateAttr(default=None)
    _resolved_openai_key: SecretStr | None = PrivateAttr(default=None)
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
    local_llm_base_url: str | None = Field(
        default=DEFAULT_LOCAL_BASE_URL,
        validation_alias=AliasChoices("LOCAL_LLM_BASE_URL", "DOCREVIEW_LOCAL_LLM_BASE_URL"),
    )
    local_llm_source: Literal["environment", "dotenv", "default"] = Field(
        default="default", validation_alias="local_llm_source", exclude=True
    )
    local_llm_protocol: Literal["auto", "openai_responses", "ollama"] = Field(
        default="auto",
        validation_alias=AliasChoices("LOCAL_LLM_PROTOCOL", "DOCREVIEW_LOCAL_LLM_PROTOCOL"),
    )
    local_llm_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("LOCAL_LLM_API_KEY", "DOCREVIEW_LOCAL_LLM_API_KEY"),
    )
    local_llm_max_input_tokens: int = Field(
        default=12_000,
        gt=0,
        validation_alias=AliasChoices(
            "LOCAL_LLM_MAX_INPUT_TOKENS", "DOCREVIEW_LOCAL_LLM_MAX_INPUT_TOKENS"
        ),
    )
    local_llm_max_output_tokens: int = Field(
        default=600,
        gt=0,
        validation_alias=AliasChoices(
            "LOCAL_LLM_MAX_OUTPUT_TOKENS", "DOCREVIEW_LOCAL_LLM_MAX_OUTPUT_TOKENS"
        ),
    )
    local_llm_timeout_s: float = Field(
        default=DEFAULT_LOCAL_TIMEOUT_S,
        gt=0,
        le=600,
        validation_alias=AliasChoices("LOCAL_LLM_TIMEOUT_S", "DOCREVIEW_LOCAL_LLM_TIMEOUT_S"),
    )

    @field_validator("embed_dim", mode="before")
    @classmethod
    def parse_embedding_dimension(cls, value: object) -> object:
        """Accept the fixed dimension from string-valued environment settings."""
        return 384 if isinstance(value, str) and value.strip() == "384" else value

    @field_validator("local_llm_base_url", mode="before")
    @classmethod
    def blank_local_values_are_unset(cls, value: object) -> object:
        """Treat blank Compose substitutions as absent local configuration."""
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator(
        "local_llm_max_input_tokens",
        "local_llm_max_output_tokens",
        "local_llm_timeout_s",
        mode="before",
    )
    @classmethod
    def blank_local_numbers_use_defaults(cls, value: object, info: ValidationInfo) -> object:
        """Fall back to the field default when Compose substitutes an unset numeric key.

        Notes
        -----
        Compose writes an empty string for `${VAR:-}` when the caller has no value, and
        an empty string is not a number. Without this the app would refuse to start for
        anyone whose dotenv omits the optional local budgets.
        """
        if isinstance(value, str) and not value.strip():
            return cls.model_fields[str(info.field_name)].default
        return value

    @model_validator(mode="after")
    def resolve_openai_key_slot(self) -> Self:
        """Resolve only the credential slot selected by MODE."""
        key, slot = resolve_openai_key(
            dev=self.openai_api_key_dev,
            prod=self.openai_api_key_prod,
            environment=self.environment,
        )
        # Keep the derived credential private; it is not another settings input.
        self._resolved_openai_key = key
        self._openai_key_slot = slot
        return self

    @property
    def openai_api_key(self) -> SecretStr | None:
        """Expose the resolved key to clients without accepting a common credential input."""
        return self._resolved_openai_key

    @property
    def openai_key_slot(self) -> KeySlot | None:
        """Report which slot supplied the OpenAI key without exposing its value."""
        return self._openai_key_slot

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
        if self.embedding_provider == "openai" and (
            self.openai_api_key is None or not self.openai_api_key.get_secret_value().strip()
        ):
            raise ValueError(
                "The MODE-selected OpenAI key slot is required when EMBEDDING_PROVIDER=openai"
            )
        return self

    @model_validator(mode="after")
    def require_review_configuration(self) -> Self:
        """Require the key and both prices whenever a review model is configured."""
        if self.review_model is None:
            if (
                self.review_input_price_per_million_usd is not None
                or self.review_output_price_per_million_usd is not None
            ):
                raise ValueError("manual review pricing was removed; model policy owns prices")
            return self
        if not self.review_model.strip():
            raise ValueError("REVIEW_MODEL must not be blank when set")
        if self.openai_api_key is None or not self.openai_api_key.get_secret_value().strip():
            raise ValueError(
                "The MODE-selected OpenAI key slot is required when REVIEW_MODEL is set"
            )
        resolve_openai_model("review", self.review_model)
        if (
            self.review_input_price_per_million_usd is not None
            or self.review_output_price_per_million_usd is not None
        ):
            raise ValueError("manual review pricing was removed; model policy owns prices")
        return self


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide validated settings instance."""
    return Settings()
