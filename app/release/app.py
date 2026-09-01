"""Assembled public release API and static Next.js service surface."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Literal

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict
from starlette.middleware.cors import CORSMiddleware

from app.api.admin_runtime import RuntimeAdminApiServices
from app.api.app import create_api_app
from app.api.runtime import RuntimeApiServices
from app.llm.provider import LLMProvider, OpenAILLMProvider
from app.release.config import AdminMode, ReleaseSettings
from app.release.limiter import DailyCostLimiter, InProcessRateLimiter
from app.release.middleware import ReleaseGuardMiddleware, SecurityHeadersMiddleware
from app.release.secrets import install_secret_redaction

ProviderFactory = Callable[..., LLMProvider]
DEFAULT_STATIC_DIR = Path(__file__).resolve().parents[2] / "web" / "out"
PUBLIC_BASE_PATH = "/docreview-rag-agent"


class ReleaseHealth(BaseModel):
    """Non-secret liveness state for container and platform probes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["ok"] = "ok"
    mode: Literal["canned", "runtime"]


class ReleaseInfo(BaseModel):
    """Public release controls without credentials or provider internals."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: Literal["canned", "runtime"]
    admin_mode: AdminMode
    frontend: Literal["next-static"] = "next-static"
    openai_enabled: bool
    key_handling: Literal["server_environment_only"] = "server_environment_only"
    key_persisted: Literal[False] = False
    rate_limit_scope: Literal["single_process"] = "single_process"
    rate_limit_per_minute: int
    rate_limit_per_day: int
    max_input_tokens: int
    max_output_tokens: int
    max_cost_usd: str
    public_daily_cost_usd: str


def build_runtime_services(
    settings: ReleaseSettings,
    *,
    provider_factory: ProviderFactory = OpenAILLMProvider,
) -> RuntimeApiServices:
    """Compose runtime services without activating a provider from key presence alone."""
    if settings.mode != "runtime":
        raise ValueError("runtime services require DOCREVIEW_MODE=runtime")
    if settings.openai_api_key is None:
        return RuntimeApiServices()

    api_key = settings.openai_api_key.get_secret_value()
    provider = provider_factory(model_name=settings.openai_model, api_key=api_key)
    install_secret_redaction((api_key,))
    return RuntimeApiServices(
        llm_provider=provider,
        provider_budget=settings.provider_budget(),
        secret_values=(api_key,),
    )


def _release_info(settings: ReleaseSettings) -> ReleaseInfo:
    """Project settings onto limits the release surface publishes."""
    return ReleaseInfo(
        mode=settings.mode,
        admin_mode=settings.admin_mode,
        openai_enabled=settings.openai_enabled,
        rate_limit_per_minute=settings.rate_limit_per_minute,
        rate_limit_per_day=settings.rate_limit_per_day,
        max_input_tokens=settings.openai_max_input_tokens,
        max_output_tokens=settings.openai_max_output_tokens,
        max_cost_usd=format(settings.openai_max_cost_usd, "f"),
        public_daily_cost_usd=format(settings.public_daily_cost_usd, "f"),
    )


def create_release_app(
    settings: ReleaseSettings | None = None,
    *,
    services: RuntimeApiServices | None = None,
    static_dir: Path | None = None,
) -> FastAPI:
    """Create one guarded API with an optional static Next.js service shell."""
    active_settings = settings or ReleaseSettings()
    active_services = services
    if active_settings.mode == "runtime" and active_services is None:
        active_services = build_runtime_services(active_settings)

    admin_services = (
        RuntimeAdminApiServices(runtime=active_services)
        if active_settings.admin_mode == "live" and active_services is not None
        else None
    )
    application = create_api_app(active_services, admin_services)
    limiter = InProcessRateLimiter(
        per_minute=active_settings.rate_limit_per_minute,
        per_day=active_settings.rate_limit_per_day,
        max_clients=active_settings.rate_limit_max_clients,
    )
    cost_limiter = DailyCostLimiter(
        daily_limit_usd=active_settings.public_daily_cost_usd,
        reservation_usd=active_settings.openai_max_cost_usd,
    )
    enforce_public_limits = active_settings.admin_mode != "live"
    application.add_middleware(
        ReleaseGuardMiddleware,
        limiter=limiter,
        trust_proxy_headers=active_settings.trust_proxy_headers,
        allow_ingest=active_settings.allow_ingest,
        enforce_rate_limit=enforce_public_limits,
        cost_limiter=(
            cost_limiter if active_settings.mode == "runtime" and enforce_public_limits else None
        ),
    )
    application.add_middleware(SecurityHeadersMiddleware)
    if active_settings.admin_mode == "live" and active_settings.admin_cors_origin is not None:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=[active_settings.admin_cors_origin],
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["content-type"],
        )

    @application.get("/health", response_model=ReleaseHealth, tags=["release"])
    async def health() -> ReleaseHealth:
        """Report liveness and the mode the release is serving in."""
        return ReleaseHealth(mode=active_settings.mode)

    @application.get("/release", response_model=ReleaseInfo, tags=["release"])
    async def release_info() -> ReleaseInfo:
        """Publish active limits without naming any credential."""
        return _release_info(active_settings)

    frontend = (static_dir or DEFAULT_STATIC_DIR).resolve()
    if frontend.is_dir():
        application.mount(
            PUBLIC_BASE_PATH,
            StaticFiles(directory=frontend, html=True),
            name="docreview-web",
        )

        @application.get("/", include_in_schema=False)
        async def root() -> RedirectResponse:
            """Redirect direct backend visits onto the public service base path."""
            return RedirectResponse(f"{PUBLIC_BASE_PATH}/")

    else:

        @application.get("/", include_in_schema=False, response_class=HTMLResponse)
        async def missing_frontend() -> str:
            """Explain a development checkout whose static frontend is not built."""
            return "<h1>DocReview API</h1><p>Build web/ before serving the service UI.</p>"

    return application
