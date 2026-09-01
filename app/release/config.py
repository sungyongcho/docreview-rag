"""Release settings, which default to the offline mode and open nothing implicitly."""

from decimal import Decimal
from ipaddress import ip_address
from typing import Literal, Self

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import SettingsConfigDict

from app.llm.schemas import ProviderBudget, TokenPricing
from app.openai_models import resolve_openai_model
from app.settings_sources import DotenvFirstSettings

type AdminMode = Literal["off", "readonly", "live"]


def _loopback_host(host: str) -> bool:
    """Return whether one configured bind host is explicitly loopback-only."""
    if host.strip().lower() == "localhost":
        return True
    try:
        return ip_address(host.strip()).is_loopback
    except ValueError:
        return False


class ReleaseSettings(DotenvFirstSettings):
    """Release controls that default to a zero-provider-call canned demo."""

    model_config = SettingsConfigDict(
        env_prefix="DOCREVIEW_",
        env_file=".env",
        extra="ignore",
        frozen=True,
    )

    mode: Literal["canned", "runtime"] = "canned"
    host: str = "0.0.0.0"
    port: int = Field(default=7860, ge=1, le=65_535)
    rate_limit_per_minute: int = Field(default=5, ge=1, le=1_000)
    rate_limit_per_day: int = Field(default=25, ge=1, le=100_000)
    rate_limit_max_clients: int = Field(default=1_024, ge=1, le=100_000)
    trust_proxy_headers: bool = False
    allow_ingest: bool = False
    admin_mode: AdminMode = "readonly"
    admin_cors_origin: str | None = None

    openai_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("DOCREVIEW_OPENAI_API_KEY", "OPENAI_API_KEY"),
    )
    openai_model: str = "gpt-5.6-terra"
    openai_max_input_tokens: int = Field(default=12_000, ge=1, le=100_000)
    openai_max_output_tokens: int = Field(default=600, ge=1, le=4_000)
    openai_max_cost_usd: Decimal = Field(default=Decimal("0.04"), gt=0, le=1)
    public_daily_cost_usd: Decimal = Field(default=Decimal("1.00"), gt=0, le=100)
    openai_input_per_million_usd: Decimal | None = Field(default=None, ge=0)
    openai_output_per_million_usd: Decimal | None = Field(default=None, ge=0)
    local_llm_base_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("LOCAL_LLM_BASE_URL", "DOCREVIEW_LOCAL_LLM_BASE_URL"),
    )
    local_llm_model: str | None = Field(
        default=None,
        validation_alias=AliasChoices("LOCAL_LLM_MODEL", "DOCREVIEW_LOCAL_LLM_MODEL"),
    )
    local_llm_protocol: Literal["auto", "openai_responses", "ollama"] = Field(
        default="auto",
        validation_alias=AliasChoices("LOCAL_LLM_PROTOCOL", "DOCREVIEW_LOCAL_LLM_PROTOCOL"),
    )
    local_llm_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("LOCAL_LLM_API_KEY", "DOCREVIEW_LOCAL_LLM_API_KEY"),
    )

    @field_validator(
        "openai_api_key",
        "local_llm_base_url",
        "local_llm_model",
        "local_llm_api_key",
        mode="before",
    )
    @classmethod
    def blank_key_is_unset(cls, value: object) -> object:
        """Treat blank compose substitutions as an absent provider secret."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def validate_release_limits(self) -> Self:
        """Keep the rolling-day limit and public identity internally consistent."""
        if self.rate_limit_per_day < self.rate_limit_per_minute:
            raise ValueError("rate_limit_per_day must be at least rate_limit_per_minute")
        if not self.host.strip():
            raise ValueError("host must not be blank")
        if not self.openai_model.strip():
            raise ValueError("openai_model must not be blank")
        resolve_openai_model("review", self.openai_model)
        if (
            self.openai_input_per_million_usd is not None
            or self.openai_output_per_million_usd is not None
        ):
            raise ValueError("manual OpenAI pricing was removed; model policy owns prices")
        if self.admin_mode == "live" and self.mode != "runtime":
            raise ValueError("live corpus administration requires DOCREVIEW_MODE=runtime")
        if self.admin_mode == "live" and not _loopback_host(self.host):
            raise ValueError("live corpus administration requires an explicit loopback host")
        if self.admin_cors_origin is not None and not self.admin_cors_origin.startswith(
            ("http://127.0.0.1:", "http://localhost:")
        ):
            raise ValueError("administrator CORS origin must be loopback HTTP")
        if self.openai_max_cost_usd > self.public_daily_cost_usd:
            raise ValueError("request cost cap must not exceed the public daily cost cap")
        if (self.local_llm_base_url is None) != (self.local_llm_model is None):
            raise ValueError("LOCAL_LLM_BASE_URL and LOCAL_LLM_MODEL must be configured together")
        return self

    @property
    def openai_enabled(self) -> bool:
        """Report secret presence without exposing the secret value."""
        return self.mode == "runtime" and self.openai_api_key is not None

    @property
    def local_llm_enabled(self) -> bool:
        """Report whether a complete local model pair is configured in runtime mode."""
        return (
            self.mode == "runtime"
            and self.local_llm_base_url is not None
            and self.local_llm_model is not None
        )

    def provider_budget(self) -> ProviderBudget:
        """Build the explicit provider cap used by every optional live review."""
        selection = resolve_openai_model("review", self.openai_model)
        return ProviderBudget(
            max_input_tokens=self.openai_max_input_tokens,
            max_output_tokens=self.openai_max_output_tokens,
            max_cost_usd=self.openai_max_cost_usd,
            pricing=TokenPricing(
                input_per_million_usd=selection.pricing.input_per_million_usd,
                output_per_million_usd=selection.pricing.output_per_million_usd,
                cached_input_per_million_usd=(selection.pricing.cached_input_per_million_usd),
                cache_write_input_per_million_usd=(
                    selection.pricing.cache_write_input_per_million_usd
                ),
            ),
        )
