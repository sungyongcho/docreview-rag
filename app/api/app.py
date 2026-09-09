"""FastAPI application factory with explicit service injection."""

from typing import Any

from fastapi import FastAPI

from app.api.admin_deps import get_admin_services
from app.api.admin_runtime import RuntimeAdminApiServices
from app.api.deps import ApiServices, get_api_services
from app.api.errors import install_error_handlers
from app.api.routes import api_router
from app.api.routes.admin import router as admin_router
from app.api.routes.public_snapshot_details import router as public_snapshot_details_router
from app.api.runtime_gate import RuntimeResetGate, install_reset_gate
from app.api.schemas import ErrorResponse

COMMON_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    422: {"model": ErrorResponse, "description": "Request validation failed."},
    500: {"model": ErrorResponse, "description": "Internal server error."},
}


def create_api_app(
    services: ApiServices | None = None,
    admin_services: RuntimeAdminApiServices | None = None,
    *,
    enable_reset: bool = False,
) -> FastAPI:
    """Create the M5 application without starting external services.

    Parameters
    ----------
    services : ApiServices | None
        Optional injected implementation used for every resource route.

    Returns
    -------
    FastAPI
        Application with typed errors, routes, and optional dependency override.

    Notes
    -----
    Construction performs no database or provider request. Missing services remain a
    typed 503 dependency failure.
    """
    gate = RuntimeResetGate() if enable_reset and admin_services is not None else None
    app = FastAPI(
        title="Document Review RAG API",
        version="0.1.0",
        lifespan=gate.lifespan if gate is not None else None,
    )
    if gate is not None:
        install_reset_gate(app, gate)
    install_error_handlers(app)
    app.include_router(api_router, responses=COMMON_ERROR_RESPONSES)
    app.include_router(public_snapshot_details_router, responses=COMMON_ERROR_RESPONSES)
    if services is not None:
        app.dependency_overrides[get_api_services] = lambda: services
    if admin_services is not None:
        app.include_router(admin_router, responses=COMMON_ERROR_RESPONSES)
        app.dependency_overrides[get_admin_services] = lambda: admin_services
    return app
