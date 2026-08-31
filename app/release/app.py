"""Assembled public release application: guards, health, and the demo surface."""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict

from app.api.app import create_api_app
from app.api.runtime import RuntimeApiServices
from app.demo import CannedDemoService, RuntimeDemoService, build_demo
from app.llm.provider import LLMProvider, OpenAILLMProvider
from app.release.config import ReleaseSettings
from app.release.limiter import InProcessRateLimiter
from app.release.middleware import ReleaseGuardMiddleware, SecurityHeadersMiddleware
from app.release.secrets import install_secret_redaction

ProviderFactory = Callable[..., LLMProvider]


class ReleaseHealth(BaseModel):
    """Non-secret liveness state for container and platform probes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["ok"] = "ok"
    mode: Literal["canned", "runtime"]


class ReleaseInfo(BaseModel):
    """Public release controls without credentials or provider internals."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: Literal["canned", "runtime"]
    openai_enabled: bool
    key_handling: Literal["server_environment_only"] = "server_environment_only"
    key_persisted: Literal[False] = False
    rate_limit_scope: Literal["single_process"] = "single_process"
    rate_limit_per_minute: int
    rate_limit_per_day: int
    max_input_tokens: int
    max_output_tokens: int
    max_cost_usd: str


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
    provider = provider_factory(
        model_name=settings.openai_model,
        api_key=api_key,
    )
    install_secret_redaction((api_key,))
    return RuntimeApiServices(
        llm_provider=provider,
        provider_budget=settings.provider_budget(),
        secret_values=(api_key,),
    )


def _release_info(settings: ReleaseSettings) -> ReleaseInfo:
    """Project the settings onto the limits the release surface publishes."""
    return ReleaseInfo(
        mode=settings.mode,
        openai_enabled=settings.openai_enabled,
        rate_limit_per_minute=settings.rate_limit_per_minute,
        rate_limit_per_day=settings.rate_limit_per_day,
        max_input_tokens=settings.openai_max_input_tokens,
        max_output_tokens=settings.openai_max_output_tokens,
        max_cost_usd=format(settings.openai_max_cost_usd, "f"),
    )


def create_release_app(
    settings: ReleaseSettings | None = None,
    *,
    services: RuntimeApiServices | None = None,
) -> FastAPI:
    """Create one canned-default release app without external calls at import time."""
    import gradio as gr

    active_settings = settings or ReleaseSettings()
    active_services = services
    if active_settings.mode == "runtime" and active_services is None:
        active_services = build_runtime_services(active_settings)

    application = create_api_app(active_services)
    limiter = InProcessRateLimiter(
        per_minute=active_settings.rate_limit_per_minute,
        per_day=active_settings.rate_limit_per_day,
        max_clients=active_settings.rate_limit_max_clients,
    )
    application.add_middleware(
        ReleaseGuardMiddleware,
        limiter=limiter,
        trust_proxy_headers=active_settings.trust_proxy_headers,
        allow_ingest=active_settings.allow_ingest,
    )
    application.add_middleware(SecurityHeadersMiddleware)

    @application.get("/health", response_model=ReleaseHealth, tags=["release"])
    async def health() -> ReleaseHealth:
        """Report liveness and the mode the release is serving in."""
        return ReleaseHealth(mode=active_settings.mode)

    @application.get("/release", response_model=ReleaseInfo, tags=["release"])
    async def release_info() -> ReleaseInfo:
        """Publish the active limits without naming any credential."""
        return _release_info(active_settings)

    if active_settings.mode == "runtime":
        assert active_services is not None
        demo_service = RuntimeDemoService(active_services)
        notice = (
            "Deployment mode: local runtime review with an operator-supplied server secret."
            if active_settings.openai_enabled
            else "Deployment mode: local runtime retrieval; review is fail-closed."
        )
    else:
        demo_service = CannedDemoService()
        notice = "Deployment mode: canned fixture; provider requests and cost are zero."

    blocks = build_demo(demo_service, release_notice=notice)
    return gr.mount_gradio_app(
        application,
        blocks,
        path="/",
        allowed_paths=[],
        blocked_paths=[".env", ".git"],
        show_error=False,
        enable_monitoring=False,
        app_kwargs={"docs_url": "/docs", "redoc_url": None},
    )
