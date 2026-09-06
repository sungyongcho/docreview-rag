"""Document collection resource route."""

from fastapi import APIRouter

from app.api.deps import Services
from app.api.schemas import DocumentListResponse, ErrorResponse

router = APIRouter(tags=["documents"])


@router.get(
    "/documents",
    response_model=DocumentListResponse,
    responses={503: {"model": ErrorResponse}},
)
async def list_documents(services: Services) -> DocumentListResponse:
    """Return the deterministic collection of ingested filings."""
    documents = tuple(await services.list_documents())
    return DocumentListResponse(documents=documents)
