"""Assembled public release API and static Next.js service surface."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import asdict
from datetime import datetime
from hashlib import blake2s
from pathlib import Path
import secrets
from typing import Any, Literal

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict
from starlette.middleware.cors import CORSMiddleware

from app.api.admin_runtime import READINESS_STATUS_MAX_AGE_S, RuntimeAdminApiServices
from app.api.app import create_api_app
from app.api.runtime import RuntimeApiServices
from app.config import Settings
from app.corpus_admin import RuntimeCorpusAdminService
from app.llm.local_connection import LocalConnectionManager
from app.llm.local_inventory import LocalModelInventory
from app.llm.local_runtime import build_local_runtime
from app.llm.openai_limits import OpenAICallLimits, OpenAILimitsManager
from app.llm.provider import LLMProvider, OpenAILLMProvider
from app.openai_models import POLICY_REVISION, openai_policy_snapshot
from app.release.browser_reset import browser_reset_id
from app.release.config import AdminMode, ReleaseSettings
from app.release.limiter import DailyCostLimiter, InProcessRateLimiter
from app.release.middleware import ReleaseGuardMiddleware, SecurityHeadersMiddleware, client_host
from app.release.secrets import install_secret_redaction
from app.retrieval.embeddings import get_embedding_provider
from app.settings_sources import Environment

ProviderFactory = Callable[..., LLMProvider]
ReadinessProbe = Callable[[], Awaitable[dict[str, Any]]]
DEFAULT_STATIC_DIR = Path(__file__).resolve().parents[2] / "web" / "out"
PUBLIC_BASE_PATH = "/docreview-rag-agent"


async def _local_engine_readiness(
    settings: ReleaseSettings,
    inventory: LocalModelInventory | None = None,
    connection: LocalConnectionManager | None = None,
) -> dict[str, object]:
    """Share bounded discovery with runtime execution without exposing the endpoint."""
    if settings.environment == "prod":
        return {"enabled": False, "reason": "disabled_in_prod"}
    if connection is not None:
        return await connection.public_state()
    if not settings.local_llm_enabled:
        return {"enabled": False, "reason": "not_configured"}
    if inventory is None:
        assert settings.local_llm_base_url is not None
        inventory = LocalModelInventory(
            base_url=settings.local_llm_base_url,
            protocol=settings.local_llm_protocol,
            api_key=settings.local_llm_api_key.get_secret_value()
            if settings.local_llm_api_key
            else None,
        )
    return (await inventory.snapshot()).public_state()


class ReleaseHealth(BaseModel):
    """Non-secret liveness state for container and platform probes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["ok"] = "ok"
    mode: Literal["canned", "runtime"]


class ReleaseInfo(BaseModel):
    """Public release controls without credentials or provider internals."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: Literal["canned", "runtime"]
    environment: Environment
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


class ReleaseCapabilities(BaseModel):
    """Non-secret controls available to this frontend mode."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    environment: Environment
    can_configure_local_llm: bool
    can_edit_prompt_policy: bool
    can_edit_run_limits: bool
    can_edit_golden: bool
    can_build_snapshot: bool
    can_run_evaluation: bool
    can_change_custom_retrieval: bool
    can_query_snapshot: bool
    can_use_operations: bool
    can_compare_published_snapshots: bool = True
    browser_reset_id: str | None = None


class ReleaseLimits(BaseModel):
    """Configured and currently remaining public single-process limits."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    per_minute: int
    per_day: int
    remaining_minute: int
    remaining_day: int
    max_input_tokens: int
    max_output_tokens: int
    max_cost_usd: str
    daily_cost_usd: str
    remaining_daily_cost_usd: str
    retry_after_seconds: int
    minute_reset_seconds: int
    day_reset_seconds: int
    daily_cost_reset_at_utc: datetime
    scope: Literal["single_process"] = "single_process"


class CorpusReadiness(BaseModel):
    """Runtime readiness with nullable counts withheld from public surfaces."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    availability: Literal["ready", "degraded", "not_applicable", "unavailable"]
    database_connected: bool | None = None
    schema_status: str | None = None
    schema_message: str | None = None
    documents: int | None = None
    chunks: int | None = None
    embedded_chunks: int | None = None
    pending_embeddings: int | None = None
    bm25_ready: bool | None = None
    bm25_rebuild_recorded: bool | None = None
    writable: bool | None = None
    updating: bool = False


class ReleaseReadiness(BaseModel):
    """Typed readiness with read-only discovery of local model availability."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["ready", "degraded"]
    mode: Literal["canned", "runtime"]
    environment: Environment
    admin_mode: AdminMode
    policy_revision: str
    models: dict[str, object]
    review_enabled: bool
    active_review_model: str | None
    review_engines: dict[str, object]
    corpus: CorpusReadiness
    openai_call_limits: OpenAICallLimits | None = None


def build_runtime_services(
    settings: ReleaseSettings,
    *,
    provider_factory: ProviderFactory = OpenAILLMProvider,
) -> RuntimeApiServices:
    """Compose runtime services without activating a provider from key presence alone."""
    if settings.mode != "runtime":
        raise ValueError("runtime services require DOCREVIEW_MODE=runtime")
    providers = {}
    budgets = {}
    secrets: list[str] = []
    if settings.openai_api_key is not None:
        api_key = settings.openai_api_key.get_secret_value()
        provider = provider_factory(model_name=settings.openai_model, api_key=api_key)
        providers["openai"] = provider
        budgets["openai"] = settings.provider_budget()
        secrets.append(api_key)
    # The ceiling is known without a key, so Dev can inspect and lower it before enabling OpenAI.
    openai_limits = OpenAILimitsManager(
        settings.provider_budget(), enabled=settings.environment != "prod"
    )
    local_connection, local_budget = build_local_runtime(
        environment=settings.environment,
        base_url=settings.local_llm_base_url,
        protocol=settings.local_llm_protocol,
        source=settings.local_llm_source,
        api_key=settings.local_llm_api_key.get_secret_value()
        if settings.local_llm_api_key
        else None,
        max_input_tokens=settings.local_llm_max_input_tokens,
        max_output_tokens=settings.local_llm_max_output_tokens,
    )
    if local_budget is not None:
        budgets["local"] = local_budget
        if settings.local_llm_api_key is not None:
            secrets.append(settings.local_llm_api_key.get_secret_value())
    install_secret_redaction(tuple(secrets))
    corpus_settings = Settings.model_validate(
        {
            "MODE": settings.environment,
            "OPENAI_API_KEY_LOCAL": settings.openai_api_key_dev,
            "OPENAI_API_KEY_PROD": settings.openai_api_key_prod,
        }
    )
    return RuntimeApiServices(
        embedding_provider=get_embedding_provider(corpus_settings),
        llm_providers=providers,
        provider_budgets=budgets,
        local_connection=local_connection,
        openai_limits=openai_limits,
        allow_local_engine=settings.environment != "prod",
        local_timeout_s=settings.local_llm_timeout_s,
        secret_values=tuple(secrets),
        credential_slot=settings.openai_key_slot,
        intent_classifier_enabled=True,
        query_routing_enabled=True,
        allow_custom_prompt_policy=settings.admin_mode == "live",
        allow_snapshot_query=settings.admin_mode == "live",
    )


def _release_info(settings: ReleaseSettings) -> ReleaseInfo:
    """Project settings onto limits the release surface publishes."""
    return ReleaseInfo(
        mode=settings.mode,
        environment=settings.environment,
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
    readiness_probe: ReadinessProbe | None = None,
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
    application = create_api_app(
        active_services,
        admin_services,
        enable_reset=active_settings.environment == "dev" and active_settings.admin_mode == "live",
    )
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
    limiter_salt = secrets.token_bytes(32)
    application.add_middleware(
        ReleaseGuardMiddleware,
        limiter=limiter,
        trust_proxy_headers=active_settings.trust_proxy_headers,
        allow_ingest=active_settings.allow_ingest,
        enforce_rate_limit=enforce_public_limits,
        public_read_only=active_settings.admin_mode != "live",
        allow_local_engine=active_settings.environment != "prod",
        local_connection_origin=active_settings.admin_cors_origin,
        cost_limiter=cost_limiter if active_settings.mode == "runtime" else None,
        salt=limiter_salt,
    )
    application.add_middleware(SecurityHeadersMiddleware)
    if active_settings.admin_mode == "live" and active_settings.admin_cors_origin is not None:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=[active_settings.admin_cors_origin],
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["content-type", "x-docreview-telemetry"],
        )

    @application.get("/health", response_model=ReleaseHealth, tags=["release"])
    async def health() -> ReleaseHealth:
        """Report liveness and the mode the release is serving in."""
        return ReleaseHealth(mode=active_settings.mode)

    @application.get("/release", response_model=ReleaseInfo, tags=["release"])
    async def release_info() -> ReleaseInfo:
        """Publish active limits without naming any credential."""
        return _release_info(active_settings)

    @application.get("/capabilities", response_model=ReleaseCapabilities, tags=["release"])
    async def capabilities(request: Request) -> ReleaseCapabilities:
        """Publish authoritative UI capabilities without exposing credentials."""
        live = (
            active_settings.admin_mode == "live"
            and request.headers.get("x-docreview-public") != "true"
        )
        return ReleaseCapabilities(
            environment=active_settings.environment,
            browser_reset_id=browser_reset_id() if active_settings.environment == "dev" else None,
            can_configure_local_llm=live and active_settings.environment != "prod",
            can_edit_prompt_policy=live,
            can_edit_run_limits=live,
            can_edit_golden=live,
            can_build_snapshot=live,
            can_run_evaluation=live,
            can_change_custom_retrieval=live,
            can_query_snapshot=live,
            can_use_operations=live and active_settings.environment != "prod",
        )

    @application.get("/limits", response_model=ReleaseLimits, tags=["release"])
    async def limits(request: Request) -> ReleaseLimits:
        """Inspect public allowance without consuming request or cost capacity."""
        host = client_host(request, trust_proxy_headers=active_settings.trust_proxy_headers)
        key = blake2s(host.encode("utf-8"), key=limiter_salt, digest_size=16).hexdigest()
        rate = await limiter.peek(key)
        remaining_cost, cost_reset = await cost_limiter.status()
        return ReleaseLimits(
            per_minute=active_settings.rate_limit_per_minute,
            per_day=active_settings.rate_limit_per_day,
            remaining_minute=rate.remaining_minute,
            remaining_day=rate.remaining_day,
            max_input_tokens=active_settings.openai_max_input_tokens,
            max_output_tokens=active_settings.openai_max_output_tokens,
            max_cost_usd=format(active_settings.openai_max_cost_usd, "f"),
            daily_cost_usd=format(active_settings.public_daily_cost_usd, "f"),
            remaining_daily_cost_usd=format(remaining_cost, "f"),
            retry_after_seconds=rate.retry_after_seconds,
            minute_reset_seconds=rate.minute_reset_seconds,
            day_reset_seconds=rate.day_reset_seconds,
            daily_cost_reset_at_utc=cost_reset,
        )

    fallback_corpus: RuntimeCorpusAdminService | None = None

    async def default_readiness_probe() -> dict[str, Any]:
        """Report corpus status without document rows, file scans or schema changes.

        The live administrator service memoizes its status reading and knows whether
        a job is running; a runtime without administration keeps one private service
        instead of constructing a new one per poll.
        """
        nonlocal fallback_corpus
        if admin_services is not None:
            status = await admin_services.readiness_status()
        else:
            if fallback_corpus is None:
                fallback_corpus = RuntimeCorpusAdminService()
            status = await fallback_corpus.status(max_age_s=READINESS_STATUS_MAX_AGE_S)
        return {"status": asdict(status)}

    @application.get(
        "/ready",
        response_model=ReleaseReadiness,
        responses={503: {"model": ReleaseReadiness}},
        tags=["release"],
    )
    async def readiness(request: Request) -> ReleaseReadiness | JSONResponse:
        """Report configured runtime readiness without contacting OpenAI."""
        models = openai_policy_snapshot()["roles"]
        if not isinstance(models, dict):
            raise ValueError("model policy roles must be an object")
        if active_settings.mode == "canned":
            return ReleaseReadiness(
                status="ready",
                mode="canned",
                environment=active_settings.environment,
                admin_mode=active_settings.admin_mode,
                policy_revision=POLICY_REVISION,
                models=models,
                review_enabled=False,
                active_review_model=None,
                review_engines={
                    "openai": {"enabled": False, "reason": "canned_mode"},
                    "local": {"enabled": False, "reason": "canned_mode"},
                },
                corpus=CorpusReadiness(availability="not_applicable"),
            )

        probe = readiness_probe or default_readiness_probe
        try:
            snapshot = await probe()
            raw_status = snapshot.get("status", {})
            if not isinstance(raw_status, dict):
                raise ValueError("corpus readiness status must be an object")
            database_connected = raw_status.get("database_connected") is True
            schema_status = str(raw_status.get("schema_status", "unavailable"))
            documents = int(raw_status.get("documents", 0))
            chunks = int(raw_status.get("chunks", 0))
            pending_embeddings = int(raw_status.get("pending_embeddings", 0))
            updating = active_services is not None and active_services.corpus_access.updating
            corpus_ready = (
                not updating
                and database_connected
                and schema_status == "compatible"
                and documents > 0
                and chunks > 0
                and pending_embeddings == 0
                and raw_status.get("bm25_ready") is True
            )
            corpus = CorpusReadiness(
                availability="ready" if corpus_ready else "degraded",
                database_connected=database_connected,
                schema_status=schema_status,
                schema_message=str(raw_status.get("schema_message", "")),
                documents=documents,
                chunks=chunks,
                embedded_chunks=int(raw_status.get("embedded_chunks", 0)),
                pending_embeddings=pending_embeddings,
                bm25_ready=raw_status.get("bm25_ready") is True,
                bm25_rebuild_recorded=raw_status.get("bm25_rebuild_recorded") is True,
                writable=raw_status.get("writable") is True,
                updating=updating,
            )
        except Exception as error:
            corpus_ready = False
            corpus = CorpusReadiness(
                availability="unavailable",
                schema_message=type(error).__name__,
            )

        public_surface = (
            active_settings.admin_mode != "live"
            or request.headers.get("x-docreview-public") == "true"
        )
        if public_surface:
            corpus = corpus.model_copy(
                update={
                    "documents": None,
                    "chunks": None,
                    "embedded_chunks": None,
                    "pending_embeddings": None,
                    "writable": None,
                }
            )

        if active_settings.environment == "prod":
            local_readiness = {"enabled": False, "reason": "disabled_in_prod"}
        elif request.headers.get("x-docreview-public") == "true":
            local_readiness = {"enabled": False, "reason": "public_surface"}
        elif (
            active_services is not None
            and active_services.local_connection is None
            and active_services.local_inventory is None
        ):
            local_readiness = {"enabled": False, "reason": "not_configured"}
        else:
            local_readiness = await _local_engine_readiness(
                active_settings,
                active_services.local_inventory if active_services else None,
                active_services.local_connection if active_services else None,
            )
        openai_limits = active_services.openai_limits if active_services is not None else None
        call_limits = openai_limits.state() if openai_limits is not None else None
        if call_limits is not None and public_surface:
            call_limits = call_limits.model_copy(update={"editable": False})
        payload = ReleaseReadiness(
            status="ready" if corpus_ready else "degraded",
            mode="runtime",
            environment=active_settings.environment,
            admin_mode=active_settings.admin_mode,
            policy_revision=POLICY_REVISION,
            models=models,
            review_enabled=(
                active_settings.openai_enabled or local_readiness.get("enabled") is True
            ),
            active_review_model=(
                active_settings.openai_model if active_settings.openai_enabled else None
            ),
            review_engines={
                "openai": {
                    "enabled": active_settings.openai_enabled,
                    "model": (
                        active_settings.openai_model if active_settings.openai_enabled else None
                    ),
                    "protocol": "responses",
                    "key_slot": active_settings.openai_key_slot,
                },
                "local": {
                    **local_readiness,
                },
            },
            corpus=corpus,
            openai_call_limits=call_limits,
        )
        if corpus_ready:
            return payload
        return JSONResponse(status_code=503, content=payload.model_dump(mode="json"))

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
