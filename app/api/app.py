"""FastAPI application factory with explicit service injection."""

from dataclasses import dataclass
from typing import Any, Final

from fastapi import APIRouter, FastAPI
from fastapi.openapi.utils import get_openapi

from app.api.admin_deps import get_admin_services
from app.api.admin_runtime import RuntimeAdminApiServices
from app.api.deps import ApiServices, get_api_services
from app.api.errors import install_error_handlers
from app.api.routes import api_router
from app.api.routes.admin import router as admin_router
from app.api.routes.public_portfolio import router as public_portfolio_router
from app.api.routes.public_snapshot_details import router as public_snapshot_details_router
from app.api.runtime_gate import RuntimeResetGate, install_reset_gate
from app.api.schemas import ErrorResponse

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


def create_api_app(
    services: ApiServices | None = None,
    admin_services: RuntimeAdminApiServices | None = None,
    *,
    surface: ApiSurface = DEV_SURFACE,
) -> FastAPI:
    """Create the M5 application without starting external services.

    Parameters
    ----------
    services : ApiServices | None
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
    install_error_handlers(app)
    app.include_router(api_router, responses=COMMON_ERROR_RESPONSES)
    app.include_router(public_snapshot_details_router, responses=COMMON_ERROR_RESPONSES)
    app.include_router(public_portfolio_router, responses=COMMON_ERROR_RESPONSES)
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
