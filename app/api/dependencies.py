"""FastAPI dependency declarations for application-owned services."""

from typing import Annotated

from fastapi import Depends

from app.api.composition import AdminServices
from app.api.documents.portfolio import PublicPortfolioReader
from app.api.errors import unavailable
from app.api.review.runtime import RuntimeApiServices
from app.evals.snapshots.evidence import PublicSnapshotDetails


def get_api_services() -> RuntimeApiServices:
    """Require the runtime installed by the application factory."""
    raise unavailable("service_unavailable", "API services are not configured.")


def get_admin_services() -> AdminServices:
    """Require administrator services explicitly enabled on this application."""
    raise unavailable(
        "admin_unavailable",
        "Administrator services are not configured on this surface.",
    )


def get_portfolio_reader() -> PublicPortfolioReader:
    """Require an explicitly composed source of measured preparation counts."""
    raise unavailable(
        "portfolio_preparation_unavailable",
        "Portfolio preparation counts require a runtime service.",
    )


def get_snapshot_details() -> PublicSnapshotDetails | None:
    """Let the route validate pagination before reporting an unavailable reader."""
    return None


RuntimeDependency = Annotated[RuntimeApiServices, Depends(get_api_services)]
AdminDependency = Annotated[AdminServices, Depends(get_admin_services)]
PortfolioReaderDependency = Annotated[PublicPortfolioReader, Depends(get_portfolio_reader)]
SnapshotDetailsDependency = Annotated[PublicSnapshotDetails | None, Depends(get_snapshot_details)]
