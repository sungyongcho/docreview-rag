"""Resource-oriented M5 route collection."""

from fastapi import APIRouter

from app.api.routes import documents, eval, ingest, retrieve, review, runs, stream

api_router = APIRouter()
for module in (retrieve, documents, ingest, review, runs, eval, stream):
    api_router.include_router(module.router)

__all__ = ["api_router"]
