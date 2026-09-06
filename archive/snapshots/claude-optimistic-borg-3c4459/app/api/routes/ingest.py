"""Synchronous ingestion resource route."""

from fastapi import APIRouter

from app.api.deps import Services
from app.api.schemas import ErrorResponse, IngestRequest, IngestResponse

router = APIRouter(tags=["ingest"])


@router.post(
    "/ingest",
    response_model=IngestResponse,
    responses={400: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
async def ingest_manifest(request: IngestRequest, services: Services) -> IngestResponse:
    """Parse and persist one explicit local manifest before responding."""
    result = await services.ingest(request)
    return IngestResponse(documents=result.documents, chunks=result.chunks)
