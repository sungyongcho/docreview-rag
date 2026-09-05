"""Read-only public document resources restricted to published source identities."""

from typing import Annotated, Literal

from fastapi import APIRouter, Query

from app.api.admin_schemas import (
    DocumentDetailResponse,
    DocumentEmbeddingStatus,
    DocumentFacetsResponse,
    DocumentInventoryResponse,
)
from app.api.deps import Services
from app.api.errors import not_found, translate_runtime_errors
from app.api.schemas import ErrorResponse

router = APIRouter(prefix="/public", tags=["documents"])


@router.get("/documents", response_model=DocumentInventoryResponse)
async def document_inventory(
    services: Services,
    query: str = "",
    registry: str = "",
    issuer: str = "",
    fiscal_year: int | None = None,
    language: str = "",
    form: str = "",
    parse_status: str = "",
    embedding_status: DocumentEmbeddingStatus | None = None,
    snapshot_id: Annotated[int | None, Query(gt=0)] = None,
    sort: Literal[
        "doc_id",
        "issuer",
        "fiscal_year",
        "filing_date",
        "chunk_count",
        "embedding_coverage",
    ] = "doc_id",
    descending: bool = False,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> DocumentInventoryResponse:
    """Return one filtered and sortable live document page."""
    async with translate_runtime_errors():
        return await services.published_documents.documents(
            query=query,
            registry=registry,
            issuer=issuer,
            fiscal_year=fiscal_year,
            language=language,
            form=form,
            parse_status=parse_status,
            embedding_status=embedding_status,
            snapshot_id=snapshot_id,
            sort=sort,
            descending=descending,
            cursor=cursor,
            limit=limit,
        )


@router.get("/documents/facets", response_model=DocumentFacetsResponse)
async def document_facets(services: Services, registry: str = "") -> DocumentFacetsResponse:
    """Return live registry, issuer, year, language, form, and status facets."""
    async with translate_runtime_errors():
        return await services.published_documents.document_facets(registry=registry)


@router.get(
    "/documents/{doc_id:path}",
    response_model=DocumentDetailResponse,
    responses={404: {"model": ErrorResponse}},
)
async def document_detail(doc_id: str, services: Services) -> DocumentDetailResponse:
    """Return bounded metadata and chunk previews for one document."""
    async with translate_runtime_errors():
        detail = await services.published_documents.document_detail(doc_id)
    if detail is None:
        raise not_found("document", doc_id)
    return DocumentDetailResponse.model_validate(detail)
