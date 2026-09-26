"""Corpus administrator commands, jobs, limits and read projections."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from app.ingestion.source_catalog import ACQUISITION_COMPANIES, AcquisitionCompany, approved_company
from app.ingestion.source_selection import SourceInventory

type AdminJobKind = Literal[
    "acquire_edgar",
    "acquire_dart",
    "ingest_manifest",
    "ingest_selected",
    "delete_sources",
    "backfill_embeddings",
    "rebuild_bm25",
]
type AdminJobStatus = Literal[
    "queued", "running", "succeeded", "failed", "interrupted", "cancelled"
]
type SchemaStatus = Literal["compatible", "empty", "drifted", "unavailable"]

MAX_QUEUED_JOBS = 8
MAX_JOB_HISTORY = 20
CHUNK_PREVIEW_LIMIT = 5
CHUNK_PREVIEW_CHARS = 1_000


@dataclass(frozen=True, slots=True)
class ProcessingSelectionSummary:
    """Expose the exact acquired artifacts selected for processing."""

    selection_id: str
    document_ids: tuple[str, ...]
    artifact_ids: tuple[str, ...]
    sources_present: int


@dataclass(frozen=True, slots=True)
class ManifestIssuer:
    """A selectable company projected from source-independent filing references."""

    registry: Literal["sec", "dart"]
    issuer: str
    name: str


@dataclass(frozen=True, slots=True)
class ManifestSummary:
    """Expose one validated common corpus catalog and its selections."""

    name: str
    documents: int | None
    valid: bool
    corpus_id: str | None = None
    registries: tuple[str, ...] = ()
    sources_present: int | None = None
    selections: tuple[ProcessingSelectionSummary, ...] = ()
    issuers: tuple[ManifestIssuer, ...] = ()


@dataclass(frozen=True, slots=True)
class OperationOutcome:
    """Return structured provenance alongside the operation completion."""

    summary: str
    manifest: str | None = None
    selection_id: str | None = None


@dataclass(frozen=True, slots=True)
class CorpusStatus:
    """One non-secret operational summary for the administrator header."""

    database_connected: bool
    schema_status: SchemaStatus
    schema_message: str
    documents: int
    chunks: int
    embedded_chunks: int
    pending_embeddings: int
    bm25_ready: bool
    writable: bool
    provider: str
    bm25_rebuild_recorded: bool = False


@dataclass(frozen=True, slots=True)
class AdminDocument:
    """One ingested filing row rendered in the administrator table."""

    doc_id: str
    registry: str
    language: str
    issuer: str
    issuer_id: str
    fiscal_year: int
    form: str
    parse_status: str
    filing_date: str
    report_period: str
    filing_id: str
    source_url: str
    source_length: int
    source_sha256: str
    chunk_count: int


@dataclass(frozen=True, slots=True)
class ChunkPreview:
    """Bounded source-cited chunk text shown for a selected document."""

    chunk_id: int
    ordinal: int
    citation: str
    span: str
    source_sha256: str
    body: str


@dataclass(frozen=True, slots=True)
class SnapshotMembership:
    """One immutable snapshot revision containing a selected document."""

    snapshot_id: int
    label: str
    status: str
    public: bool
    created_at: datetime


@dataclass(frozen=True, slots=True)
class DocumentDetail:
    """One selected document and its bounded chunk previews."""

    document: AdminDocument
    chunks: tuple[ChunkPreview, ...]
    text_chunks: int = 0
    table_chunks: int = 0
    embedded_chunks: int = 0
    item_counts: tuple[dict[str, object], ...] = ()
    embedding_identities: tuple[dict[str, object], ...] = ()
    snapshot_memberships: tuple[SnapshotMembership, ...] = ()


@dataclass(frozen=True, slots=True)
class CorpusSnapshot:
    """Atomic administrator projection used by one UI refresh."""

    mode: Literal["live", "canned"]
    status: CorpusStatus
    manifests: tuple[ManifestSummary, ...]
    documents: tuple[AdminDocument, ...]
    sources: tuple[SourceInventory, ...] = ()
    acquisition_draft: dict[str, object] | None = None
    acquisition_companies: tuple[AcquisitionCompany, ...] = ACQUISITION_COMPANIES


@dataclass(frozen=True, slots=True)
class AdminCommand:
    """Validated safe operation submitted through the local administrator UI."""

    kind: AdminJobKind
    identifiers: tuple[str, ...] = ()
    years: tuple[int, ...] = ()
    manifest: str | None = None
    selection_id: str | None = None
    expected_documents: int | None = None
    document_ids: tuple[str, ...] | None = None
    deletion_token: str | None = None
    confirm_delete: bool | None = None

    def __post_init__(self) -> None:
        """Reject unsupported or structurally unsafe command arguments."""
        if self.kind in {"acquire_edgar", "acquire_dart"}:
            registry = "sec" if self.kind == "acquire_edgar" else "dart"
            if any(not approved_company(registry, value) for value in self.identifiers):
                raise ValueError("Choose a company from the supported acquisition catalog.")
            if not self.identifiers or not self.years:
                raise ValueError("acquisition requires identifiers and fiscal years")
            if any(year < 1900 or year > 2100 for year in self.years):
                raise ValueError("fiscal years must be between 1900 and 2100")
        if self.kind == "ingest_selected" and (
            not self.document_ids or len(set(self.document_ids)) != len(self.document_ids)
        ):
            raise ValueError("ingest_selected requires nonempty unique document_ids")
        if self.kind == "ingest_manifest" and (
            not (self.manifest or "").strip() or not (self.selection_id or "").strip()
        ):
            raise ValueError("ingestion requires a manifest and selection_id")
        if self.kind == "delete_sources":
            if not self.deletion_token or self.confirm_delete is not True:
                raise ValueError(
                    "Source deletion requires a fresh preview and explicit confirmation."
                )
            if (
                self.identifiers
                or self.years
                or self.manifest
                or self.selection_id
                or self.document_ids
            ):
                raise ValueError("Source deletion targets come only from the confirmed preview.")
        elif self.deletion_token is not None or self.confirm_delete is not None:
            raise ValueError("Deletion confirmation cannot be used for another operation.")
        if self.document_ids is not None and self.kind not in {
            "ingest_selected",
            "ingest_manifest",
        }:
            raise ValueError("Exact document IDs apply only to source ingestion.")
        if self.expected_documents is not None and self.expected_documents <= 0:
            raise ValueError("expected_documents must be positive")


@dataclass(frozen=True, slots=True)
class AdminJob:
    """One immutable snapshot of a queued or completed administrator operation."""

    job_id: str
    command: AdminCommand
    status: AdminJobStatus
    stage: str
    current: int
    total: int | None
    message: str
    detail_current: int | None = None
    detail_total: int | None = None
    created_at: datetime = datetime.min.replace(tzinfo=UTC)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_code: str | None = None
    result_refs: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class JobBoard:
    """Current worker state and bounded newest-first operation history."""

    active: AdminJob | None
    queued: tuple[AdminJob, ...]
    history: tuple[AdminJob, ...]
