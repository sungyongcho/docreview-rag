"""Document metadata, index coverage, and paginated catalog resources."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import StrictBool, StrictInt

from app.contracts.validation import NonNegativeInt, PositiveInt, StrictSchema

type DocumentSort = Literal[
    "doc_id",
    "issuer",
    "fiscal_year",
    "filing_date",
    "chunk_count",
    "embedding_coverage",
]


type DocumentEmbeddingStatus = Literal["complete", "partial", "missing"]


class AdminDocumentResource(StrictSchema):
    """One filing row with current chunk and embedding coverage."""

    doc_id: str
    registry: str
    language: str
    issuer: str
    issuer_name: str | None = None
    issuer_id: str
    fiscal_year: StrictInt
    form: str
    filing_date: str
    report_period: str
    filing_id: str
    source_url: str
    parse_status: str
    source_length: PositiveInt
    source_sha256: str
    chunk_count: NonNegativeInt
    embedded_chunks: NonNegativeInt
    text_chunks: NonNegativeInt
    table_chunks: NonNegativeInt
    embedding_status: DocumentEmbeddingStatus
    snapshot_count: NonNegativeInt


class DocumentInventoryResponse(StrictSchema):
    """One filtered deterministic document page."""

    documents: tuple[AdminDocumentResource, ...]
    total: NonNegativeInt
    next_cursor: str | None


class DocumentFacetValue(StrictSchema):
    """One filter value and its document count."""

    value: str
    count: PositiveInt
    label: str | None = None


class DocumentFacetsResponse(StrictSchema):
    """Available document facets computed from live rows."""

    registries: tuple[DocumentFacetValue, ...]
    issuers: tuple[DocumentFacetValue, ...]
    years: tuple[DocumentFacetValue, ...]
    languages: tuple[DocumentFacetValue, ...]
    forms: tuple[DocumentFacetValue, ...]
    sections: tuple[DocumentFacetValue, ...] = ()
    parse_statuses: tuple[DocumentFacetValue, ...]
    embedding_statuses: tuple[DocumentFacetValue, ...]
    snapshots: tuple[DocumentFacetValue, ...]


class DocumentMetadataResource(StrictSchema):
    """Immutable filing metadata for one selected document."""

    doc_id: str
    registry: str
    language: str
    issuer: str
    issuer_name: str | None = None
    issuer_id: str
    fiscal_year: StrictInt
    form: str
    parse_status: str
    filing_date: str
    report_period: str
    filing_id: str
    source_url: str
    source_length: PositiveInt
    source_sha256: str
    chunk_count: NonNegativeInt


class DocumentChunkPreviewResource(StrictSchema):
    """One bounded source-cited chunk preview."""

    chunk_id: PositiveInt
    ordinal: NonNegativeInt
    citation: str
    span: str
    source_sha256: str
    body: str


class DocumentItemCountResource(StrictSchema):
    """Chunk count for one filing section identity."""

    item: str
    count: PositiveInt


class DocumentEmbeddingIdentityResource(StrictSchema):
    """Embedding identity and coverage for one selected filing."""

    provider: str
    model: str
    dimensions: PositiveInt
    tokenizer: str
    count: PositiveInt


class DocumentSnapshotMembershipResource(StrictSchema):
    """One immutable snapshot revision containing the selected filing."""

    snapshot_id: PositiveInt
    label: str
    status: Literal["ready", "archived"]
    public: StrictBool
    created_at: datetime


class DocumentDetailResponse(StrictSchema):
    """Structured filing identity, index coverage, and source previews."""

    document: DocumentMetadataResource
    chunks: tuple[DocumentChunkPreviewResource, ...]
    text_chunks: NonNegativeInt
    table_chunks: NonNegativeInt
    embedded_chunks: NonNegativeInt
    item_counts: tuple[DocumentItemCountResource, ...]
    embedding_identities: tuple[DocumentEmbeddingIdentityResource, ...]
    snapshot_memberships: tuple[DocumentSnapshotMembershipResource, ...]
