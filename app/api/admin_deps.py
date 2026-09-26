"""Injected local-administrator service dependency."""

from typing import Annotated

from fastapi import Depends

from app.api.dependencies import AdminDependencies
from app.api.errors import unavailable


def get_admin_services() -> AdminDependencies:
    """Require explicit local administrator composition."""
    raise unavailable(
        "admin_unavailable",
        "Administrator services are not configured on this surface.",
    )


AdminServices = Annotated[AdminDependencies, Depends(get_admin_services)]
