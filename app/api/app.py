"""FastAPI application factory with explicit service injection."""

from dataclasses import dataclass
from typing import Any, Final

from fastapi import APIRouter, FastAPI
from fastapi.openapi.utils import get_openapi

from app.api.composition import AdminServices
from app.api.corpus import routes as corpus
from app.api.dependencies import (
    get_admin_services,
    get_api_services,
    get_portfolio_reader,
    get_snapshot_details,
)
from app.api.documents import admin as document_admin, routes as documents
from app.api.documents.portfolio import PublicPortfolioReader
from app.api.errors import install_error_handlers
from app.api.evaluations import results, routes as evaluations
from app.api.review import preset_routes, previews, routes as review, streaming
from app.api.review.runtime import RuntimeApiServices
from app.api.review.schemas import ErrorResponse
from app.api.runtime_gate import RuntimeResetGate, install_reset_gate
from app.api.snapshots import (
    admin as snapshot_admin,
    details as snapshot_details_routes,
    routes as snapshots,
)
from app.api.system import jobs, settings, usage
from app.evals.snapshots.evidence import PublicSnapshotDetails

COMMON_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    422: {"model": ErrorResponse, "description": "Request validation failed."},
    500: {"model": ErrorResponse, "description": "Internal server error."},
}


@dataclass(frozen=True, slots=True)
class ApiSurface:
    """The optional controls and documentation one application exposes.

    Attributes
    ----------
    reset_gate : bool
        Install the authenticated runtime reset gate when admin routes are mounted.
    docs_execution : bool
        Let Swagger UI send requests; otherwise every submit method is disabled.
    admin_schema : bool
        Document administrator operations even without mounting their live routes.
    """

    reset_gate: bool
    docs_execution: bool
    admin_schema: bool


# Callers pick one of these instead of combining the fields. A DEV application serves an
# interactive Swagger UI; with live admin routes it also installs the runtime reset gate.
# A PROD application documents every operation, admin included, and executes none of them
# from Swagger UI.
DEV_SURFACE: Final = ApiSurface(reset_gate=False, docs_execution=True, admin_schema=False)
LIVE_ADMIN_SURFACE: Final = ApiSurface(reset_gate=True, docs_execution=True, admin_schema=False)
PROD_SURFACE: Final = ApiSurface(reset_gate=False, docs_execution=False, admin_schema=True)

admin_router = APIRouter()
for feature in (
    corpus,
    document_admin,
    evaluations,
    snapshot_admin,
    jobs,
    usage,
    previews,
    settings,
    preset_routes,
):
    admin_router.include_router(feature.router)


def create_api_app(
    services: RuntimeApiServices | None = None,
    admin_services: AdminServices | None = None,
    *,
    surface: ApiSurface = DEV_SURFACE,
    portfolio_reader: PublicPortfolioReader | None = None,
    snapshot_details: PublicSnapshotDetails | None = None,
) -> FastAPI:
    """Create the HTTP application without starting external services.

    Parameters
    ----------
    services : RuntimeApiServices | None
        Optional injected implementation used for every resource route.
    surface : ApiSurface
        The reset gate and documentation behaviour this application exposes.

    Returns
    -------
    FastAPI
        Application with typed errors, routes, and optional dependency override.

    Notes
    -----
    Construction performs no database or provider request. Missing services remain a
    typed 503 dependency failure.
    """
    gate = RuntimeResetGate() if surface.reset_gate and admin_services is not None else None
    app = FastAPI(
        title="Document Review RAG API",
        version="0.1.0",
        lifespan=gate.lifespan if gate is not None else None,
        swagger_ui_parameters=(
            None
            if surface.docs_execution
            else {"supportedSubmitMethods": [], "tryItOutEnabled": False}
        ),
    )
    if gate is not None:
        install_reset_gate(app, gate)
    if portfolio_reader is not None:
        app.dependency_overrides[get_portfolio_reader] = lambda: portfolio_reader
    if snapshot_details is not None:
        app.dependency_overrides[get_snapshot_details] = lambda: snapshot_details
    install_error_handlers(app)
    for feature in (documents, review, results, snapshots, streaming, snapshot_details_routes):
        app.include_router(feature.router, responses=COMMON_ERROR_RESPONSES)
    if services is not None:
        app.dependency_overrides[get_api_services] = lambda: services
    if admin_services is not None:
        app.include_router(admin_router, responses=COMMON_ERROR_RESPONSES)
        app.dependency_overrides[get_admin_services] = lambda: admin_services
    elif surface.admin_schema:
        _include_documented_admin_routes(app)
    return app


def _include_documented_admin_routes(app: FastAPI) -> None:
    """Add administrator schemas without making their handlers reachable."""
    documented_router = APIRouter()
    documented_router.include_router(admin_router, responses=COMMON_ERROR_RESPONSES)
    original_openapi = app.openapi
    documented_schema: dict[str, Any] | None = None

    def documented_openapi() -> dict[str, Any]:
        """Extend the current schema while preserving FastAPI route-cache invalidation."""
        nonlocal documented_schema
        schema = original_openapi()
        if schema is not documented_schema:
            complete = get_openapi(
                title=app.title,
                version=app.version,
                openapi_version=app.openapi_version,
                routes=[*app.routes, *documented_router.routes],
                webhooks=app.webhooks.routes,
                separate_input_output_schemas=app.separate_input_output_schemas,
            )
            schema["paths"] = complete["paths"]
            schema["components"] = complete["components"]
            documented_schema = schema
        return schema

    app.openapi = documented_openapi
