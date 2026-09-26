"""Release capabilities, readiness, and current public allowance."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from app.api.composition import AdminServices
from app.api.review.profiles import PromptPolicy
from app.api.review.runtime import RuntimeApiServices
from app.api.system.jobs import READINESS_STATUS_MAX_AGE_S, _readiness_status
from app.corpus_admin.service import RuntimeCorpusAdminService
from app.corpus_admin.types import CorpusStatus
from app.llm.local.connection import LocalConnectionManager
from app.llm.openai_limits import OpenAICallLimits, OpenAILimitsManager
from app.openai_models import POLICY_REVISION, openai_policy_snapshot
from app.release.ai_allowance import SharedAIAllowance
from app.release.config import AdminMode, ReleaseSettings
from app.release.middleware import client_key
from app.settings_sources import Environment

BROWSER_RESET_PATH = Path(__file__).resolve().parents[2] / "data/browser-reset.json"


def browser_reset_id() -> str | None:
    """Read a fresh-start receipt; ordinary application startup never creates one."""
    try:
        raw = json.loads(BROWSER_RESET_PATH.read_text())
    except FileNotFoundError:
        return None
    if (
        not isinstance(raw, dict)
        or set(raw) != {"reset_id"}
        or not isinstance(raw["reset_id"], str)
    ):
        raise ValueError("Invalid DocReview browser reset marker.")
    return str(UUID(raw["reset_id"]))


async def _local_engine_readiness(
    settings: ReleaseSettings,
    connection: LocalConnectionManager | None = None,
    *,
    public_request: bool = False,
) -> dict[str, object]:
    """Share connection discovery only with requests allowed to inspect local engines."""
    if settings.environment == "prod":
        return {"enabled": False, "reason": "disabled_in_prod"}
    if public_request:
        return {"enabled": False, "reason": "public_surface"}
    if connection is None:
        return {"enabled": False, "reason": "not_configured"}
    return await connection.public_state()


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
    rate_limit_scope: Literal["shared_storage"] = "shared_storage"
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
    """Configured and currently remaining public limits from the shared allowance ledger."""

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
    prompt_policy: PromptPolicy
    per_call: OpenAICallLimits
    scope: Literal["shared_storage"] = "shared_storage"


class CorpusReadiness(BaseModel):
    """Runtime readiness; only write access is withheld from public surfaces."""

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


def _release_info(settings: ReleaseSettings) -> ReleaseInfo:
    """Project settings onto limits the release surface publishes."""
    return ReleaseInfo(
        mode=settings.service_mode,
        environment=settings.environment,
        admin_mode=settings.admin_mode if settings.environment == "dev" else "readonly",
        openai_enabled=settings.openai_enabled,
        rate_limit_per_minute=settings.rate_limit_per_minute,
        rate_limit_per_day=settings.rate_limit_per_day,
        max_input_tokens=settings.openai_max_input_tokens,
        max_output_tokens=settings.openai_max_output_tokens,
        max_cost_usd=format(settings.openai_max_cost_usd, "f"),
        public_daily_cost_usd=format(settings.public_daily_cost_usd, "f"),
    )


def install_status_routes(
    application: FastAPI,
    active_settings: ReleaseSettings,
    active_services: RuntimeApiServices | None,
    admin_services: AdminServices | None,
    allowance: SharedAIAllowance,
) -> None:
    """Mount read-only status handlers over the application's existing services."""

    @application.get("/health", response_model=ReleaseHealth, tags=["release"])
    async def health() -> ReleaseHealth:
        """Report liveness and the mode the release is serving in."""
        return ReleaseHealth(mode=active_settings.service_mode)

    @application.get("/release", response_model=ReleaseInfo, tags=["release"])
    async def release_info() -> ReleaseInfo:
        """Publish active limits without naming any credential."""
        return _release_info(active_settings)

    @application.get("/capabilities", response_model=ReleaseCapabilities, tags=["release"])
    async def capabilities(request: Request) -> ReleaseCapabilities:
        """Publish authoritative UI capabilities without exposing credentials."""
        live = active_settings.admin_enabled and request.headers.get("x-docreview-public") != "true"
        return ReleaseCapabilities(
            environment=active_settings.environment,
            browser_reset_id=browser_reset_id() if active_settings.environment == "dev" else None,
            can_configure_local_llm=live and active_settings.environment != "prod",
            can_edit_prompt_policy=live,
            can_edit_run_limits=live,
            can_edit_golden=live,
            can_build_snapshot=live,
            can_run_evaluation=live,
            can_change_custom_retrieval=True,
            can_query_snapshot=live,
            can_use_operations=live and active_settings.environment != "prod",
        )

    @application.get("/limits", response_model=ReleaseLimits, tags=["release"])
    async def limits(request: Request) -> ReleaseLimits:
        """Inspect public allowance without consuming request or cost capacity."""
        key = client_key(
            request, trust_proxy_headers=active_settings.trust_proxy_headers, salt=allowance.salt
        )
        rate = await allowance.peek(key)
        remaining_cost, cost_reset = await allowance.status()
        manager = active_services.openai_limits if active_services is not None else None
        call_limits = (
            manager or OpenAILimitsManager(active_settings.provider_budget(), enabled=False)
        ).state()
        return ReleaseLimits(
            prompt_policy=PromptPolicy(),
            per_call=call_limits.model_copy(update={"editable": False}),
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

    async def default_readiness_probe() -> CorpusStatus:
        """Report corpus status without document rows, file scans or schema changes.

        The live administrator service memoizes its status reading and knows whether
        a job is running; a runtime without administration keeps one private service
        instead of constructing a new one per poll.
        """
        nonlocal fallback_corpus
        if admin_services is not None:
            return await _readiness_status(admin_services)
        if fallback_corpus is None:
            fallback_corpus = RuntimeCorpusAdminService()
        return await fallback_corpus.status(max_age_s=READINESS_STATUS_MAX_AGE_S)

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
        if active_settings.service_mode == "canned":
            return ReleaseReadiness(
                status="ready",
                mode="canned",
                environment=active_settings.environment,
                admin_mode=active_settings.admin_mode
                if active_settings.environment == "dev"
                else "readonly",
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

        try:
            status = await default_readiness_probe()
        except Exception as error:
            corpus_ready = False
            corpus = CorpusReadiness(
                availability="unavailable",
                schema_message=type(error).__name__,
            )
        else:
            updating = active_services is not None and active_services.corpus_access.updating
            corpus_ready = (
                not updating
                and status.database_connected
                and status.schema_status == "compatible"
                and status.documents > 0
                and status.chunks > 0
                and status.pending_embeddings == 0
                and status.bm25_ready
            )
            corpus = CorpusReadiness(
                availability="ready" if corpus_ready else "degraded",
                database_connected=status.database_connected,
                schema_status=status.schema_status,
                schema_message=status.schema_message,
                documents=status.documents,
                chunks=status.chunks,
                embedded_chunks=status.embedded_chunks,
                pending_embeddings=status.pending_embeddings,
                bm25_ready=status.bm25_ready,
                bm25_rebuild_recorded=status.bm25_rebuild_recorded,
                writable=status.writable,
                updating=updating,
            )

        public_surface = (
            not active_settings.admin_enabled or request.headers.get("x-docreview-public") == "true"
        )
        if public_surface:
            # Counts are public reading material; only write access stays private.
            corpus = corpus.model_copy(update={"writable": None})

        local_readiness = await _local_engine_readiness(
            active_settings,
            active_services.local_connection if active_services else None,
            public_request=request.headers.get("x-docreview-public") == "true",
        )
        openai_limits = active_services.openai_limits if active_services is not None else None
        call_limits = openai_limits.state() if openai_limits is not None else None
        if call_limits is not None and public_surface:
            call_limits = call_limits.model_copy(update={"editable": False})
        payload = ReleaseReadiness(
            status="ready" if corpus_ready else "degraded",
            mode="runtime",
            environment=active_settings.environment,
            admin_mode=active_settings.admin_mode
            if active_settings.environment == "dev"
            else "readonly",
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
