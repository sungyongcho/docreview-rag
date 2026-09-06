"""Injected local-administrator service dependency."""

from typing import Annotated

from fastapi import Depends

from app.api.admin_runtime import RuntimeAdminApiServices
from app.api.errors import unavailable


def get_admin_services() -> RuntimeAdminApiServices:
    """Require explicit local administrator composition."""
    raise unavailable(
        "admin_unavailable",
        "Administrator services are not configured on this surface.",
    )


AdminServices = Annotated[RuntimeAdminApiServices, Depends(get_admin_services)]
