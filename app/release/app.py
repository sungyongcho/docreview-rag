"""Assembled public release API and static Next.js service surface."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware

from app.api.app import DEV_SURFACE, LIVE_ADMIN_SURFACE, PROD_SURFACE, create_api_app
from app.api.composition import create_admin_services, runtime_settings
from app.api.documents.catalog import DocumentCatalog
from app.api.documents.portfolio import PublicPortfolioReader
from app.api.review.runtime import RuntimeApiServices
from app.corpus_admin.service import RuntimeCorpusAdminService
from app.evals.snapshots.evidence import PublicSnapshotDetails
from app.release.ai_allowance import SharedAIAllowance
from app.release.config import ReleaseSettings
from app.release.middleware import ReleaseGuardMiddleware, SecurityHeadersMiddleware
from app.release.runtime import build_runtime_services
from app.release.status import install_status_routes

DEFAULT_STATIC_DIR = Path(__file__).resolve().parents[2] / "web" / "out"
PUBLIC_BASE_PATH = "/docreview-rag"


def create_release_app(
    settings: ReleaseSettings | None = None,
    *,
    services: RuntimeApiServices | None = None,
    static_dir: Path | None = None,
) -> FastAPI:
    """Create one guarded API with an optional static Next.js service shell."""
    active_settings = settings or ReleaseSettings()
    active_services = services
    if active_settings.service_mode == "runtime" and active_services is None:
        active_services = build_runtime_services(active_settings)

    admin_services = (
        create_admin_services(runtime=active_services)
        if active_settings.admin_enabled and active_services is not None
        else None
    )
    if active_settings.environment == "prod":
        surface = PROD_SURFACE
    elif active_settings.admin_enabled:
        surface = LIVE_ADMIN_SURFACE
    else:
        surface = DEV_SURFACE
    portfolio_reader = None
    snapshot_details = None
    if active_services is not None:
        corpus = (
            admin_services.corpus
            if admin_services is not None
            else RuntimeCorpusAdminService(
                settings=runtime_settings(active_services),
                session_factory=active_services.session_factory,
                embedding_provider=active_services.embedding_provider,
                corpus_access=active_services.corpus_access,
            )
        )
        catalog = (
            admin_services.documents
            if admin_services is not None
            else DocumentCatalog(
                active_services.session_factory,
                public_only=False,
                embedding_identity=active_services.embedding_provider.identity,
            )
        )
        portfolio_reader = PublicPortfolioReader(corpus, catalog)
        snapshot_details = PublicSnapshotDetails(
            active_services.session_factory, active_services.snapshots.artifacts
        )
    application = create_api_app(
        active_services,
        admin_services,
        surface=surface,
        portfolio_reader=portfolio_reader,
        snapshot_details=snapshot_details,
    )
    # One ledger meters every mode: per-client request windows plus the UTC-day cost cap,
    # charged by each actual provider call rather than by a flat per-request reservation.
    allowance = SharedAIAllowance(
        active_settings.public_allowance_path,
        active_settings.public_daily_cost_usd,
        active_settings.rate_limit_per_minute,
        active_settings.rate_limit_per_day,
    )
    enforce_public_limits = (
        active_settings.environment == "prod" or not active_settings.admin_enabled
    )
    application.add_middleware(
        ReleaseGuardMiddleware,
        allowance=allowance,
        trust_proxy_headers=active_settings.trust_proxy_headers,
        enforce_rate_limit=enforce_public_limits,
        public_read_only=not active_settings.admin_enabled,
        allow_local_engine=active_settings.environment != "prod",
        local_connection_origin=active_settings.admin_cors_origin,
    )
    application.add_middleware(SecurityHeadersMiddleware)
    if active_settings.admin_enabled and active_settings.admin_cors_origin is not None:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=[active_settings.admin_cors_origin],
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["content-type", "x-docreview-telemetry"],
        )

    install_status_routes(application, active_settings, active_services, admin_services, allowance)

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
