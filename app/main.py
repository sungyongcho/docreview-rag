"""FastAPI runtime entrypoint without import-time database or provider calls."""

from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict

from app.api.app import create_api_app
from app.api.deps import ApiServices
from app.api.runtime import RuntimeApiServices


class HealthResponse(BaseModel):
    """Stable process-liveness response used by container health checks."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["ok"] = "ok"


def create_app(services: ApiServices | None = None) -> FastAPI:
    """Build one API instance with an injectable database-backed service boundary."""
    active_services = RuntimeApiServices() if services is None else services
    application = create_api_app(active_services)

    @application.get(
        "/health",
        response_model=HealthResponse,
        tags=["runtime"],
        operation_id="runtime_health",
    )
    async def health() -> HealthResponse:
        """Report process liveness without touching a database or a provider."""
        return HealthResponse()

    return application


app = create_app()
