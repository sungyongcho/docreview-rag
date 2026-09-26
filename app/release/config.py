"""Release settings, which default to the offline mode and open nothing implicitly."""

from decimal import Decimal
from ipaddress import ip_address
from pathlib import Path
from typing import Literal, Self

from pydantic import (
    Field,
    model_validator,
)
from pydantic_settings import SettingsConfigDict

from app.llm.schemas import ProviderBudget
from app.openai_models import resolve_openai_model
from app.settings_sources import ProviderSettings

type AdminMode = Literal["off", "readonly", "live"]


def _loopback_host(host: str) -> bool:
    """Return whether one configured bind host is explicitly loopback-only."""
    if host.strip().lower() == "localhost":
        return True
    try:
        return ip_address(host.strip()).is_loopback
    except ValueError:
        return False


class ReleaseSettings(ProviderSettings):
    """Release controls that default to a zero-provider-call canned demo."""

    model_config = SettingsConfigDict(
        env_prefix="DOCREVIEW_",
        env_file=".env",
        extra="ignore",
        frozen=True,
    )

    service_mode: Literal["canned", "runtime"] = Field(
        default="canned", validation_alias="DOCREVIEW_MODE"
    )
    host: str = "0.0.0.0"
    rate_limit_per_minute: int = Field(default=10, ge=1, le=1_000)
    rate_limit_per_day: int = Field(default=50, ge=1, le=100_000)
    # Trust exactly one proxy hop: the client identity is the last X-Forwarded-For entry,
    # the address that proxy appended. Earlier entries are client-supplied and ignored.
    trust_proxy_headers: bool = False
    admin_mode: AdminMode = "readonly"
    admin_cors_origin: str | None = None

    openai_model: str = "gpt-5.6-luna"
    openai_max_input_tokens: int = Field(default=12_000, ge=1, le=100_000)
    openai_max_output_tokens: int = Field(default=600, ge=1, le=4_000)
    openai_max_cost_usd: Decimal = Field(default=Decimal("0.005"), gt=0, le=1)
    public_allowance_path: Path = Path("data/runtime/public-ai-limits.sqlite3")
    public_daily_cost_usd: Decimal = Field(default=Decimal("0.10"), gt=0, le=100)

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
        if self.environment == "prod" and self.openai_model != "gpt-5.6-luna":
            raise ValueError("production text calls require gpt-5.6-luna")
        if self.admin_mode == "live" and self.service_mode != "runtime":
            raise ValueError("live corpus administration requires DOCREVIEW_MODE=runtime")
        if self.admin_mode == "live" and not _loopback_host(self.host):
            raise ValueError("live corpus administration requires an explicit loopback host")
        if self.admin_cors_origin is not None and not self.admin_cors_origin.startswith(
            ("http://127.0.0.1:", "http://localhost:")
        ):
            raise ValueError("administrator CORS origin must be loopback HTTP")
        if self.openai_max_cost_usd > self.public_daily_cost_usd:
            raise ValueError("request cost cap must not exceed the public daily cost cap")
        return self

    @property
    def openai_enabled(self) -> bool:
        """Report secret presence without exposing the secret value."""
        return self.service_mode == "runtime" and self.openai_api_key is not None

    @property
    def admin_enabled(self) -> bool:
        """Permit administrator services only in the explicitly live DEV runtime."""
        return self.environment == "dev" and self.admin_mode == "live"

    @property
    def local_llm_enabled(self) -> bool:
        """Report whether the configured local server may be queried in this runtime.

        Notes
        -----
        `MODE=prod` disables it whatever the endpoint keys say, so a published build
        cannot answer from an unvetted local model even if a stray variable reaches it.
        """
        return (
            self.service_mode == "runtime"
            and self.environment != "prod"
            and self.local_llm_base_url is not None
        )

    def provider_budget(self) -> ProviderBudget:
        """Build the explicit provider cap used by every optional live review."""
        selection = resolve_openai_model("review", self.openai_model)
        return ProviderBudget(
            max_input_tokens=self.openai_max_input_tokens,
            max_output_tokens=self.openai_max_output_tokens,
            max_cost_usd=self.openai_max_cost_usd,
            pricing=selection.pricing,
        )
