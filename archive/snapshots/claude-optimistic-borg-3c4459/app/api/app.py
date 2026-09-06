"""FastAPI application factory with explicit service injection."""

from typing import Any

from fastapi import FastAPI

from app.api.admin_deps import get_admin_services
from app.api.admin_runtime import RuntimeAdminApiServices
from app.api.deps import ApiServices, get_api_services
from app.api.errors import install_error_handlers
from app.api.routes import api_router
from app.api.routes.admin import router as admin_router
from app.api.schemas import ErrorResponse

COMMON_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    422: {"model": ErrorResponse, "description": "Request validation failed."},
    500: {"model": ErrorResponse, "description": "Internal server error."},
}


def create_api_app(
    services: ApiServices | None = None,
    admin_services: RuntimeAdminApiServices | None = None,
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
    app = FastAPI(title="Document Review RAG API", version="0.1.0")
    install_error_handlers(app)
    app.include_router(api_router, responses=COMMON_ERROR_RESPONSES)
    if services is not None:
        app.dependency_overrides[get_api_services] = lambda: services
    if admin_services is not None:
        app.include_router(admin_router, responses=COMMON_ERROR_RESPONSES)
        app.dependency_overrides[get_admin_services] = lambda: admin_services
    return app
