"""FastAPI application factory with explicit service injection."""

from fastapi import FastAPI

from app.api.deps import ApiServices, get_api_services
from app.api.errors import install_error_handlers
from app.api.routes import api_router


def create_api_app(services: ApiServices | None = None) -> FastAPI:
    """Create the synchronous M5 HTTP application without starting external services."""
    app = FastAPI(title="Document Review RAG API", version="0.1.0")
    install_error_handlers(app)
    app.include_router(api_router)
    if services is not None:
        app.dependency_overrides[get_api_services] = lambda: services
    return app
