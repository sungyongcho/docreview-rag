"""Corpus preparation status and validated acquisition or indexing requests."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter
from pydantic import BeforeValidator, Field, StrictBool, StrictInt

from app.api.admin_deps import AdminServices
from app.api.dependencies import AdminDependencies
from app.api.errors import translate_runtime_errors
from app.api.review.schemas import ErrorResponse
from app.contracts.validation import NonNegativeInt, StrictSchema, tuple_from_json_array
from app.corpus_admin.types import AdminCommand


class ProcessingSelectionResource(StrictSchema):
    """One exact document selection available for processing."""

    selection_id: str
    document_ids: tuple[str, ...]
    artifact_ids: tuple[str, ...]
    sources_present: NonNegativeInt


class ManifestIssuerResource(StrictSchema):
    """A company and source registry available before ingestion."""

    registry: Literal["sec", "dart"]
    issuer: str
    name: str


class ManifestResource(StrictSchema):
    """A common corpus catalog and its available processing selections."""

    name: str
    corpus_id: str | None
    documents: NonNegativeInt | None
    valid: StrictBool
    registries: tuple[Literal["sec", "dart"], ...]
    sources_present: NonNegativeInt | None
    selections: tuple[ProcessingSelectionResource, ...]
    issuers: tuple[ManifestIssuerResource, ...] = ()


class CorpusStatusResource(StrictSchema):
    """Current preparation state shared by CLI and web."""

    database_connected: StrictBool
    schema_status: Literal["compatible", "empty", "drifted", "unavailable"]
    schema_message: str
    documents: NonNegativeInt
    chunks: NonNegativeInt
    embedded_chunks: NonNegativeInt
    pending_embeddings: NonNegativeInt
    bm25_ready: StrictBool
    bm25_rebuild_recorded: StrictBool | None = None
    writable: StrictBool = Field(
        description=(
            "Source directory write permission, independent of database schema compatibility."
        )
    )
    provider: str


class CorpusDocumentResource(StrictSchema):
    """An ingested filing summarized in preparation state."""

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
    source_length: NonNegativeInt
    source_sha256: str
    chunk_count: NonNegativeInt


class SourceDeletionRequest(StrictSchema):
    """Preview the exact acquired filing identities selected in step one."""

    document_ids: Annotated[
        tuple[str, ...],
        BeforeValidator(tuple_from_json_array),
        Field(min_length=1, max_length=200),
    ]


class SourceDeletionDocument(StrictSchema):
    """Show the official filing identity before original-file deletion is confirmed."""

    document_id: str
    registry: Literal["sec", "dart"]
    issuer: str
    fiscal_year: int
    filing_id: str


class SourceDeletionFile(StrictSchema):
    """Distinguish current files to remove from inputs retained for other recorded scopes."""

    path: str
    byte_length: NonNegativeInt
    retained: StrictBool


class SourceDeletionPreviewResource(StrictSchema):
    """A short-lived confirmation bound to exact files and the current catalog."""

    token: str
    expires_at: float
    documents: tuple[SourceDeletionDocument, ...]
    files: tuple[SourceDeletionFile, ...]
    retained_inputs: NonNegativeInt
    retained_derived: Literal[True] = True


class SourceInventoryResource(StrictSchema):
    """Downloaded source identity independent of database rows."""

    manifest: str
    document_id: str
    registry: Literal["sec", "dart"]
    issuer: str
    name: str
    fiscal_year: int
    filing_id: str
    on_disk: StrictBool
    ready: StrictBool
    blocker: str | None = None
    can_redownload: StrictBool


class AcquisitionPairResource(StrictSchema):
    """Preserve an exact intended filing without a mixed-registry cross product."""

    registry: Literal["sec", "dart"]
    issuer: str
    year: StrictInt


class AcquisitionDraftResource(StrictSchema):
    """Server-provided initial company and fiscal-year selection."""

    pairs: Annotated[tuple[AcquisitionPairResource, ...], BeforeValidator(tuple_from_json_array)]
    revision: str

    identifiers: Annotated[tuple[str, ...], BeforeValidator(tuple_from_json_array)]
    years: Annotated[tuple[int, ...], BeforeValidator(tuple_from_json_array)]


class CorpusSnapshotResource(StrictSchema):
    """Atomic typed preparation state with explicit source selections."""

    mode: Literal["live", "canned"]
    status: CorpusStatusResource
    manifests: tuple[ManifestResource, ...]
    documents: tuple[CorpusDocumentResource, ...]
    sources: tuple[SourceInventoryResource, ...] = ()
    acquisition_draft: AcquisitionDraftResource | None = None
    acquisition_companies: tuple[ManifestIssuerResource, ...] = ()


class CorpusJobResource(StrictSchema):
    """The same corpus job snapshot returned to CLI and web clients."""

    job_id: str
    command: AdminCommand
    status: Literal["queued", "running", "succeeded", "failed", "interrupted", "cancelled"]
    stage: str
    current: NonNegativeInt
    total: NonNegativeInt | None
    message: str
    detail_current: NonNegativeInt | None
    detail_total: NonNegativeInt | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error_code: str | None
    result_refs: dict[str, object] | None


router = APIRouter(prefix="/admin", tags=["admin"])


async def _corpus_snapshot(dependencies: AdminDependencies) -> CorpusSnapshotResource:
    """Return one JSON-ready live corpus and index snapshot."""
    snapshot = asdict(await dependencies.corpus.snapshot())
    names = dependencies.runtime.company_names()
    for document in snapshot["documents"]:
        document["issuer_name"] = names.get((document["registry"], document["issuer"]))
    return CorpusSnapshotResource.model_validate(snapshot)


async def _source_deletion_preview(
    dependencies: AdminDependencies, request: SourceDeletionRequest
) -> SourceDeletionPreviewResource:
    """Return the read-only source plan used by the confirmation dialog."""
    preview = await dependencies.corpus.preview_source_deletion(request.document_ids)
    return SourceDeletionPreviewResource.model_validate(
        {**preview, "documents": tuple(preview["documents"]), "files": tuple(preview["files"])}
    )


async def _enqueue_corpus(dependencies: AdminDependencies, request: AdminCommand) -> dict[str, Any]:
    """Queue one validated safe corpus operation."""
    job = await dependencies.corpus.enqueue(request)
    return asdict(job)


@router.get(
    "/corpus", response_model=CorpusSnapshotResource, responses={503: {"model": ErrorResponse}}
)
async def corpus_snapshot(services: AdminServices) -> CorpusSnapshotResource:
    """Return live corpus, schema, index, manifest, and document state."""
    async with translate_runtime_errors():
        return await _corpus_snapshot(services)


@router.post("/corpus/sources/deletion-preview", response_model=SourceDeletionPreviewResource)
async def source_deletion_preview(
    request: SourceDeletionRequest, services: AdminServices
) -> SourceDeletionPreviewResource:
    """Inspect exact acquired originals without deleting or changing their selection."""
    async with translate_runtime_errors():
        return await _source_deletion_preview(services, request)


@router.post(
    "/corpus/jobs", response_model=CorpusJobResource, responses={400: {"model": ErrorResponse}}
)
async def enqueue_corpus(request: AdminCommand, services: AdminServices) -> dict[str, Any]:
    """Queue one safe corpus acquisition, ingest, or indexing operation."""
    async with translate_runtime_errors():
        return await _enqueue_corpus(services, request)
