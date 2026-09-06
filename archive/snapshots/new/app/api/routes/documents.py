"""Document collection resource route."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import ApiServices, get_api_services
from app.api.schemas import DocumentListResponse

router = APIRouter(tags=["documents"])
Services = Annotated[ApiServices, Depends(get_api_services)]


@router.get("/documents", response_model=DocumentListResponse)
async def list_documents(services: Services) -> DocumentListResponse:
    """Return the deterministic collection of ingested filings."""
    documents = tuple(await services.list_documents())
    return DocumentListResponse(documents=documents)
