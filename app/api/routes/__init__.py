"""Resource-oriented M5 route collection."""

from fastapi import APIRouter

from app.api.routes import (
    documents,
    eval,
    public_documents,
    retrieve,
    review,
    runs,
    snapshots,
    stream,
)

api_router = APIRouter()
for module in (
    retrieve,
    documents,
    public_documents,
    review,
    runs,
    eval,
    snapshots,
    stream,
):
    api_router.include_router(module.router)

__all__ = ["api_router"]
