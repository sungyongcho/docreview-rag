"""Local corpus administration and deterministic public-demo projections."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
import os
from pathlib import Path
from typing import Literal, Protocol, cast
from uuid import uuid4

from pydantic import StrictInt, StrictStr, TypeAdapter
from sqlalchemy import func, inspect, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.config import Settings, get_settings
from app.db.bootstrap import SchemaDriftError, bootstrap_schema, ensure_schema_compatibility
from app.db.models import (
    Base,
    BM25CorpusStat,
    Chunk,
    ChunkEmbedding,
    Document,
    EvaluationSnapshot,
    SnapshotDocument,
)
from app.db.queries import join_current_parse
from app.ingestion.dart_api import acquire_dart
from app.ingestion.edgar_api import DEFAULT_MANIFEST, acquire_edgar
from app.ingestion.manifest import Manifest
from app.ingestion.progress import OperationProgress
from app.ingestion.seed import load_seed_batch, persist_seed_batch_with_stats
from app.observability.persistence import redact_sensitive_text
from app.observability.usage import LEDGER_KIND, USAGE_KEY, UsageSink, merge_usage
from app.operator.jobs import (
    JobExecutionCoordinator,
    JobStore,
    JobTurnCancelledError,
    ProgressPersister,
    StoredJob,
)
from app.retrieval.bm25 import backfill_term_stats
from app.retrieval.embeddings import (
    EmbeddingBackfillResult,
    EmbeddingProvider,
    embed_missing_chunks,
    matching_embedding,
)

type AdminJobKind = Literal[
    "acquire_edgar",
    "acquire_dart",
    "ingest_manifest",
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


def _utc_now() -> datetime:
    """Return one timezone-aware job timestamp."""
    return datetime.now(UTC)


def _default_engine() -> AsyncEngine:
    """Resolve the process engine only when live administration needs it."""
    from app.db.session import engine

    return engine


def _default_session_factory() -> AsyncSession:
    """Create one process-configured session for an administrative operation."""
    from app.db.session import Session

    return Session()


class SessionFactory(Protocol):
    """Build one caller-owned asynchronous database session."""

    def __call__(self) -> AsyncSession:
        """Return one asynchronous session context manager."""
        ...


async def _embedding_state(
    session: AsyncSession, provider: EmbeddingProvider, document_ids: tuple[str, ...] | None = None
) -> tuple[int, int]:
    """Return committed compatible and pending chunk counts for one provider identity."""
    identity = provider.identity
    compatible = select(ChunkEmbedding.chunk_id).where(matching_embedding(identity)).exists()
    scope = (Chunk.doc_id.in_(document_ids),) if document_ids is not None else ()
    total = int(await session.scalar(select(func.count()).select_from(Chunk).where(*scope)) or 0)
    ready = int(
        await session.scalar(select(func.count()).select_from(Chunk).where(compatible, *scope)) or 0
    )
    return ready, total - ready


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


@dataclass(frozen=True, slots=True)
class AdminCommand:
    """Validated safe operation submitted through the local administrator UI."""

    kind: AdminJobKind
    identifiers: tuple[str, ...] = ()
    years: tuple[int, ...] = ()
    manifest: str | None = None
    selection_id: str | None = None
    expected_documents: int | None = None

    def __post_init__(self) -> None:
        """Reject unsupported or structurally unsafe command arguments."""
        if self.kind in {"acquire_edgar", "acquire_dart"}:
            if not self.identifiers or not self.years:
                raise ValueError("acquisition requires identifiers and fiscal years")
            if any(year < 1900 or year > 2100 for year in self.years):
                raise ValueError("fiscal years must be between 1900 and 2100")
        if self.kind == "ingest_manifest" and (
            not (self.manifest or "").strip() or not (self.selection_id or "").strip()
        ):
            raise ValueError("ingestion requires a manifest and selection_id")
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


class JobCancelledError(RuntimeError):
    """Signal cooperative cancellation at one safe progress boundary."""


def _command_payload(command: AdminCommand) -> dict[str, object]:
    """Serialize one validated command for persistent retry provenance."""
    return {
        "identifiers": list(command.identifiers),
        "years": list(command.years),
        "manifest": command.manifest,
        "selection_id": command.selection_id,
        "expected_documents": command.expected_documents,
    }


_JOB_KIND = TypeAdapter(AdminJobKind)
_COMMAND_IDENTIFIERS = TypeAdapter(tuple[StrictStr, ...])
_COMMAND_YEARS = TypeAdapter(tuple[StrictInt, ...])
_COMMAND_TEXT = TypeAdapter(StrictStr | None)
_COMMAND_COUNT = TypeAdapter(StrictInt | None)


def _command_from_stored(job: StoredJob) -> AdminCommand:
    """Validate persisted JSON before restoring command and retry provenance."""
    payload = job.request_json
    return AdminCommand(
        kind=_JOB_KIND.validate_python(job.kind, strict=True),
        identifiers=_COMMAND_IDENTIFIERS.validate_python(payload.get("identifiers", [])),
        years=_COMMAND_YEARS.validate_python(payload.get("years", [])),
        manifest=_COMMAND_TEXT.validate_python(payload.get("manifest")),
        selection_id=_COMMAND_TEXT.validate_python(payload.get("selection_id")),
        expected_documents=_COMMAND_COUNT.validate_python(payload.get("expected_documents")),
    )


def _job_from_stored(job: StoredJob) -> AdminJob:
    """Project a stored job onto the existing corpus job response contract."""
    return AdminJob(
        job_id=job.job_id,
        command=_command_from_stored(job),
        status=cast("AdminJobStatus", job.status),
        stage=job.stage,
        current=job.current,
        total=job.total,
        message=job.message,
        detail_current=job.detail_current,
        detail_total=job.detail_total,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        error_code=job.error_code,
        result_refs=job.result_refs,
    )


class CorpusAdminService(Protocol):
    """Shared live and canned boundary consumed by the Gradio administrator tab."""

    @property
    def read_only(self) -> bool:
        """Report whether operation controls must remain disabled."""
        ...

    async def snapshot(
        self,
        *,
        registry: str = "",
        issuer: str = "",
        fiscal_year: int | None = None,
        language: str = "",
        parse_status: str = "",
    ) -> CorpusSnapshot:
        """Return one filtered corpus snapshot."""
        ...

    async def document_detail(self, doc_id: str) -> DocumentDetail | None:
        """Return one selected document and bounded chunk previews."""
        ...

    async def enqueue(self, command: AdminCommand, *, retry_of: str | None = None) -> AdminJob:
        """Queue one safe administrator operation."""
        ...

    async def retry(self, job_id: str) -> AdminJob:
        """Queue the same command from one failed job."""
        ...

    async def jobs(self) -> JobBoard:
        """Return current queue and history state."""
        ...


def _matches(
    document: AdminDocument,
    *,
    registry: str,
    issuer: str,
    fiscal_year: int | None,
    language: str,
    parse_status: str,
) -> bool:
    """Apply normalized administrator filters to one projected document."""
    return (
        (not registry or document.registry == registry)
        and (not issuer or issuer.lower() in document.issuer.lower())
        and (fiscal_year is None or document.fiscal_year == fiscal_year)
        and (not language or document.language == language)
        and (not parse_status or document.parse_status == parse_status)
    )


class CannedCorpusAdminService:
    """Deterministic read-only corpus administration portfolio fixture."""

    _documents = (
        AdminDocument(
            doc_id="NVDA-FY2024",
            registry="sec",
            language="en",
            issuer="NVDA",
            issuer_id="0001045810",
            fiscal_year=2024,
            form="10-K",
            parse_status="parsed",
            filing_date="2024-02-21",
            report_period="2024-01-28",
            filing_id="0001045810-24-000029",
            source_url="https://www.sec.gov/Archives/edgar/data/1045810/",
            source_length=1_873_421,
            source_sha256="3" * 64,
            chunk_count=612,
        ),
        AdminDocument(
            doc_id="005930-FY2024",
            registry="dart",
            language="ko",
            issuer="005930",
            issuer_id="00126380",
            fiscal_year=2024,
            form="사업보고서",
            parse_status="parsed",
            filing_date="2025-03-11",
            report_period="2024-12-31",
            filing_id="20250311001042",
            source_url="https://dart.fss.or.kr/",
            source_length=5_780_874,
            source_sha256="5" * 64,
            chunk_count=668,
        ),
    )

    _details = {
        "NVDA-FY2024": (
            ChunkPreview(
                chunk_id=42,
                ordinal=41,
                citation="NVDA FY2024 · Item 7",
                span="chars 539406-540566",
                source_sha256="3" * 64,
                body="Data Center revenue increased as accelerated computing demand grew.",
            ),
        ),
        "005930-FY2024": (
            ChunkPreview(
                chunk_id=84,
                ordinal=83,
                citation="삼성전자 FY2024 · 반도체 사업",
                span="chars 12040-13220",
                source_sha256="5" * 64,
                body="메모리 시장과 설비투자에 관한 사업보고서 근거 예시입니다.",
            ),
        ),
    }

    def __init__(self) -> None:
        self._history = (
            AdminJob(
                job_id="demo-success",
                command=AdminCommand("rebuild_bm25"),
                status="succeeded",
                stage="complete",
                current=1,
                total=1,
                message="BM25 statistics rebuilt",
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
                started_at=datetime(2026, 1, 1, tzinfo=UTC),
                finished_at=datetime(2026, 1, 1, tzinfo=UTC),
            ),
            AdminJob(
                job_id="demo-failure",
                command=AdminCommand("backfill_embeddings"),
                status="failed",
                stage="failed",
                current=0,
                total=None,
                message="Provider unavailable in the read-only fixture",
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
                started_at=datetime(2026, 1, 1, tzinfo=UTC),
                finished_at=datetime(2026, 1, 1, tzinfo=UTC),
            ),
        )

    @property
    def read_only(self) -> bool:
        """Keep every canned operation control disabled."""
        return True

    def initial_snapshot(self) -> CorpusSnapshot:
        """Return the unfiltered fixture synchronously for DB-free UI construction."""
        return CorpusSnapshot(
            mode="canned",
            status=CorpusStatus(
                database_connected=False,
                schema_status="compatible",
                schema_message="Deterministic portfolio fixture; no database access.",
                documents=2,
                chunks=1_280,
                embedded_chunks=1_280,
                pending_embeddings=0,
                bm25_ready=True,
                writable=False,
                provider="deterministic",
            ),
            manifests=(
                ManifestSummary(
                    "manifest.json",
                    2,
                    True,
                    corpus_id="demo",
                    registries=("sec", "dart"),
                    sources_present=2,
                ),
            ),
            documents=self._documents,
        )

    async def snapshot(
        self,
        *,
        registry: str = "",
        issuer: str = "",
        fiscal_year: int | None = None,
        language: str = "",
        parse_status: str = "",
    ) -> CorpusSnapshot:
        """Return deterministic representative SEC and DART corpus state."""
        documents = tuple(
            document
            for document in self._documents
            if _matches(
                document,
                registry=registry,
                issuer=issuer,
                fiscal_year=fiscal_year,
                language=language,
                parse_status=parse_status,
            )
        )
        return replace(self.initial_snapshot(), documents=documents)

    async def document_detail(self, doc_id: str) -> DocumentDetail | None:
        """Return one deterministic representative chunk preview."""
        document = next((item for item in self._documents if item.doc_id == doc_id), None)
        if document is None:
            return None
        return DocumentDetail(document, self._details.get(doc_id, ()))

    async def enqueue(self, command: AdminCommand, *, retry_of: str | None = None) -> AdminJob:
        """Refuse mutation on the public portfolio fixture."""
        del command, retry_of
        raise PermissionError("Read-only portfolio demo; local administrator mode is required.")

    async def retry(self, job_id: str) -> AdminJob:
        """Refuse retries on the public portfolio fixture."""
        del job_id
        raise PermissionError("Read-only portfolio demo; local administrator mode is required.")

    async def jobs(self) -> JobBoard:
        """Return deterministic sample success and failure history."""
        return JobBoard(None, (), self._history)


OperationRunner = Callable[
    [AdminCommand, Callable[[OperationProgress], None]],
    Awaitable[OperationOutcome],
]


class RuntimeCorpusAdminService:
    """Local-only corpus administration over real files and PostgreSQL state."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        engine: AsyncEngine | None = None,
        session_factory: SessionFactory = _default_session_factory,
        embedding_provider: EmbeddingProvider | None = None,
        operation_runner: OperationRunner | None = None,
        job_store: JobStore | None = None,
        execution_lock: asyncio.Lock | None = None,
        execution_coordinator: JobExecutionCoordinator | None = None,
    ) -> None:
        configured = settings or get_settings()
        self._settings = configured
        self._engine = engine
        self._session_factory = session_factory
        self._embedding_provider = embedding_provider
        self._operation_runner = operation_runner
        self._job_store = job_store
        self._execution_lock = execution_lock or asyncio.Lock()
        self._execution_coordinator = execution_coordinator or JobExecutionCoordinator()
        self._corpus_root = configured.corpus_dir.resolve()
        self._queue: asyncio.Queue[AdminJob] = asyncio.Queue(maxsize=MAX_QUEUED_JOBS)
        self._jobs: dict[str, AdminJob] = {}
        self._history: deque[str] = deque(maxlen=MAX_JOB_HISTORY)
        self._worker: asyncio.Task[None] | None = None
        self._recovered_jobs = False
        self._cancel_events: dict[str, asyncio.Event] = {}
        self._persister = ProgressPersister(self._persist_current_job)

    @property
    def read_only(self) -> bool:
        """Enable controls only for this explicit live service."""
        return False

    @property
    def _database_engine(self) -> AsyncEngine:
        """Resolve an injected or process engine lazily."""
        return self._engine or _default_engine()

    @property
    def _provider(self) -> EmbeddingProvider:
        """Resolve the server-configured embedding provider without accepting UI secrets."""
        if self._embedding_provider is None:
            from app.retrieval.embeddings import get_embedding_provider

            self._embedding_provider = get_embedding_provider(self._settings)
        return self._embedding_provider

    def _redact(self, text: str) -> str:
        """Remove configured server credentials and recognizable secret syntax."""
        safe = text
        for secret in (self._settings.openai_api_key, self._settings.dart_api_key):
            if secret is not None:
                value = secret.get_secret_value()
                if value:
                    safe = safe.replace(value, "[REDACTED]")
        return redact_sensitive_text(safe)

    async def _schema_state(self) -> tuple[SchemaStatus, str, set[str]]:
        """Inspect compatibility and table presence without creating schema objects."""
        try:
            async with self._database_engine.connect() as connection:
                await ensure_schema_compatibility(connection)
                tables = await connection.run_sync(
                    lambda sync: set(inspect(sync).get_table_names())
                )
        except SchemaDriftError as error:
            return "drifted", str(error), set()
        except Exception as error:  # noqa: BLE001 - translated into non-secret status
            return "unavailable", self._redact(type(error).__name__), set()
        if not tables:
            return "empty", "No corpus tables exist yet.", tables
        missing = sorted(set(Base.metadata.tables) - tables)
        if missing:
            return (
                "drifted",
                "The schema is incomplete. Missing tables: "
                + ", ".join(missing)
                + ". Existing data is preserved; inspect the schema before indexing.",
                tables,
            )
        return "compatible", "Schema matches the current ORM models.", tables

    def _manifest_summaries(self) -> tuple[ManifestSummary, ...]:
        """Validate root catalogs and expose exact processing selections."""
        summaries = []
        for path in sorted(self._corpus_root.glob("*.json")):
            if path.name != "manifest.json" and not path.name.endswith("-manifest.json"):
                continue
            try:
                if path.resolve().parent != self._corpus_root:
                    raise ValueError("manifest resolves outside the corpus root")
                manifest = Manifest.read(path)
            except OSError, ValueError:
                summaries.append(ManifestSummary(path.name, None, False))
                continue
            present = {}
            for artifact in manifest.artifacts:
                source = (self._corpus_root / artifact.path).resolve()
                present[artifact.artifact_id] = (
                    source.is_relative_to(self._corpus_root) and source.is_file()
                )
            issuers = {
                (document.registry, document.issuer): ManifestIssuer(
                    document.registry,
                    document.issuer,
                    next(
                        (alias for alias in document.aliases if alias != document.issuer),
                        document.issuer,
                    ),
                )
                for document in manifest.documents
            }
            selections = []
            for selection in manifest.selections:
                sources = manifest.selected_sources(selection.selection_id, self._corpus_root)
                selections.append(
                    ProcessingSelectionSummary(
                        selection.selection_id,
                        tuple(source.document.document_id for source in sources),
                        tuple(source.artifact.artifact_id for source in sources),
                        sum(present[source.artifact.artifact_id] for source in sources),
                    )
                )
            summaries.append(
                ManifestSummary(
                    path.name,
                    len(manifest.documents),
                    True,
                    manifest.corpus.corpus_id,
                    tuple(sorted({document.registry for document in manifest.documents})),
                    len(
                        {
                            artifact.document_id
                            for artifact in manifest.artifacts
                            if artifact.role == "primary" and present[artifact.artifact_id]
                        }
                    ),
                    tuple(selections),
                    tuple(issuers[key] for key in sorted(issuers)),
                )
            )
        return tuple(summaries)

    async def _counts(self, tables: set[str]) -> tuple[int, int, int, bool]:
        """Return corpus and index counts only when their tables exist."""
        if not {"documents", "chunks"}.issubset(tables):
            return 0, 0, 0, False
        async with self._session_factory() as session:
            documents = int(await session.scalar(select(func.count()).select_from(Document)) or 0)
            chunks = int(await session.scalar(select(func.count()).select_from(Chunk)) or 0)
            embedded = int(
                await session.scalar(
                    select(func.count())
                    .select_from(Chunk)
                    .where(
                        select(ChunkEmbedding.chunk_id)
                        .where(matching_embedding(self._provider.identity))
                        .exists()
                    )
                )
                or 0
            )
            bm25_ready = False
            if "bm25_corpus_stats" in tables:
                bm25_ready = bool(
                    await session.scalar(select(func.count()).select_from(BM25CorpusStat))
                )
        return documents, chunks, embedded, bm25_ready

    async def _documents(self, tables: set[str]) -> tuple[AdminDocument, ...]:
        """Return deterministic document rows from a compatible populated schema."""
        if not {"documents", "chunks"}.issubset(tables):
            return ()
        statement = (
            select(Document, func.count(Chunk.id).label("chunk_count"))
            .outerjoin(Chunk, Chunk.doc_id == Document.doc_id)
            .group_by(Document.doc_id)
            .order_by(Document.registry, Document.issuer, Document.fiscal_year, Document.doc_id)
        )
        statement = join_current_parse(statement, load=True, grouped=True)
        async with self._session_factory() as session:
            rows = (await session.execute(statement)).all()
        return tuple(
            AdminDocument(
                doc_id=document.doc_id,
                registry=document.registry,
                language=document.language,
                issuer=document.issuer,
                issuer_id=document.issuer_id,
                fiscal_year=document.fiscal_year,
                form=document.form,
                parse_status=document.current_parse.structure.parse_status,
                filing_date=document.filing_date,
                report_period=document.report_period,
                filing_id=document.filing_id,
                source_url=document.source_url,
                source_length=document.current_parse.structure.source_length,
                source_sha256=document.current_parse.structure.source_sha256,
                chunk_count=int(chunk_count),
            )
            for document, chunk_count in rows
        )

    async def snapshot(
        self,
        *,
        registry: str = "",
        issuer: str = "",
        fiscal_year: int | None = None,
        language: str = "",
        parse_status: str = "",
    ) -> CorpusSnapshot:
        """Inspect live state while failing closed on schema drift or database errors."""
        schema_status, schema_message, tables = await self._schema_state()
        documents = chunks = embedded = 0
        bm25_ready = False
        rows: tuple[AdminDocument, ...] = ()
        if schema_status == "compatible":
            try:
                documents, chunks, embedded, bm25_ready = await self._counts(tables)
                rows = await self._documents(tables)
            except Exception as error:  # noqa: BLE001 - rendered as safe unavailable state
                schema_status = "unavailable"
                schema_message = self._redact(type(error).__name__)
        filtered = tuple(
            document
            for document in rows
            if _matches(
                document,
                registry=registry,
                issuer=issuer,
                fiscal_year=fiscal_year,
                language=language,
                parse_status=parse_status,
            )
        )
        return CorpusSnapshot(
            mode="live",
            status=CorpusStatus(
                database_connected=schema_status != "unavailable",
                schema_status=schema_status,
                schema_message=schema_message,
                documents=documents,
                chunks=chunks,
                embedded_chunks=embedded,
                pending_embeddings=max(chunks - embedded, 0),
                bm25_ready=bm25_ready,
                writable=os.access(self._corpus_root, os.W_OK | os.X_OK),
                provider=self._settings.embedding_provider,
            ),
            manifests=self._manifest_summaries(),
            documents=filtered,
        )

    async def document_detail(self, doc_id: str) -> DocumentDetail | None:
        """Load one live document and no more than five bounded chunk bodies."""
        snapshot = await self.snapshot()
        if not snapshot.status.database_connected or snapshot.status.schema_status != "compatible":
            return None
        document = next((item for item in snapshot.documents if item.doc_id == doc_id), None)
        if document is None:
            return None
        statement = (
            select(Chunk)
            .where(Chunk.doc_id == doc_id)
            .order_by(Chunk.ordinal)
            .limit(CHUNK_PREVIEW_LIMIT)
        )
        async with self._session_factory() as session:
            chunks = tuple(await session.scalars(statement))
            aggregate_rows = (
                await session.execute(
                    select(
                        Chunk.kind,
                        Chunk.item,
                        ChunkEmbedding.provider,
                        ChunkEmbedding.model,
                        ChunkEmbedding.dimensions,
                        ChunkEmbedding.tokenizer,
                        func.count(func.distinct(Chunk.id)),
                    )
                    .outerjoin(ChunkEmbedding, matching_embedding(self._provider.identity))
                    .where(Chunk.doc_id == doc_id)
                    .group_by(
                        Chunk.kind,
                        Chunk.item,
                        ChunkEmbedding.provider,
                        ChunkEmbedding.model,
                        ChunkEmbedding.dimensions,
                        ChunkEmbedding.tokenizer,
                    )
                )
            ).all()
            snapshot_rows = (
                await session.execute(
                    select(EvaluationSnapshot)
                    .join(
                        SnapshotDocument,
                        SnapshotDocument.snapshot_id == EvaluationSnapshot.id,
                    )
                    .where(
                        SnapshotDocument.doc_id == doc_id,
                        SnapshotDocument.source_sha256 == document.source_sha256,
                    )
                    .order_by(EvaluationSnapshot.created_at.desc(), EvaluationSnapshot.id.desc())
                )
            ).scalars()
            memberships = tuple(snapshot_rows)
        text_chunks = sum(int(row[6]) for row in aggregate_rows if row.kind == "text")
        table_chunks = sum(int(row[6]) for row in aggregate_rows if row.kind == "table")
        embedded_chunks = sum(int(row[6]) for row in aggregate_rows if row.provider is not None)
        item_totals: dict[str, int] = {}
        embedding_totals: dict[tuple[str, str, int, str], int] = {}
        for row in aggregate_rows:
            item = row.item or "unsectioned"
            item_totals[item] = item_totals.get(item, 0) + int(row[6])
            if row.provider is not None:
                identity = (
                    str(row.provider),
                    str(row.model),
                    int(row.dimensions),
                    str(row.tokenizer),
                )
                embedding_totals[identity] = embedding_totals.get(identity, 0) + int(row[6])
        return DocumentDetail(
            document,
            tuple(
                ChunkPreview(
                    chunk_id=chunk.id,
                    ordinal=chunk.ordinal,
                    citation=chunk.citation,
                    span=f"chars {chunk.start_char}-{chunk.end_char}",
                    source_sha256=chunk.source_sha256,
                    body=chunk.body[:CHUNK_PREVIEW_CHARS],
                )
                for chunk in chunks
            ),
            text_chunks=text_chunks,
            table_chunks=table_chunks,
            embedded_chunks=embedded_chunks,
            item_counts=tuple(
                {"item": item, "count": count} for item, count in sorted(item_totals.items())
            ),
            embedding_identities=tuple(
                {
                    "provider": identity[0],
                    "model": identity[1],
                    "dimensions": identity[2],
                    "tokenizer": identity[3],
                    "count": count,
                }
                for identity, count in sorted(embedding_totals.items())
            ),
            snapshot_memberships=tuple(
                SnapshotMembership(
                    snapshot_id=snapshot.id,
                    label=snapshot.label,
                    status=snapshot.status,
                    public=snapshot.public,
                    created_at=snapshot.created_at,
                )
                for snapshot in memberships
            ),
        )

    async def enqueue(self, command: AdminCommand, *, retry_of: str | None = None) -> AdminJob:
        """Queue one operation and start the persistent single worker lazily."""
        await self.recover_jobs()
        if self._queue.full():
            raise RuntimeError(f"administrator queue is full ({MAX_QUEUED_JOBS})")
        job = AdminJob(
            job_id=f"admin-{uuid4().hex}",
            command=command,
            status="queued",
            stage="queued",
            current=0,
            total=None,
            message="Queued",
            created_at=_utc_now(),
            result_refs={"retry_of": retry_of} if retry_of is not None else {},
        )
        self._jobs[job.job_id] = job
        self._cancel_events[job.job_id] = asyncio.Event()
        if self._job_store is not None:
            await self._job_store.create(
                job_id=job.job_id,
                domain="corpus",
                kind=command.kind,
                request_json=_command_payload(command),
                created_at=job.created_at,
                result_refs=job.result_refs,
            )
        await self._execution_coordinator.register(job.job_id, job.created_at)
        self._queue.put_nowait(job)
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._work(), name="corpus-admin-worker")
        return job

    def forget_history(self, job_ids: tuple[str, ...]) -> None:
        """Release terminal cache records only after their persistent deletion."""
        for job_id in job_ids:
            job = self._jobs.get(job_id)
            if job is not None and job.status not in {"queued", "running"}:
                self._jobs.pop(job_id, None)
        self._history = deque(
            (job_id for job_id in self._history if job_id not in job_ids),
            maxlen=self._history.maxlen,
        )

    async def retry(self, job_id: str) -> AdminJob:
        """Requeue the command from one failed or interrupted operation only."""
        await self.recover_jobs()
        if self._job_store is not None:
            record = await self._job_store.get(job_id)
            if record is not None and record.kind == LEDGER_KIND:
                raise ValueError("Usage ledger entries cannot be executed or retried.")
            if record is None or record.result_refs.get("__history_archived") is True:
                raise ValueError(
                    "Restore archived history before retrying; deleted jobs cannot be retried."
                )
        job = self._jobs.get(job_id)
        if job is None and self._job_store is not None:
            stored = await self._job_store.get(job_id)
            job = (
                _job_from_stored(stored)
                if stored is not None and stored.domain == "corpus"
                else None
            )
        if job is None or job.status not in {"failed", "interrupted"}:
            raise ValueError("only a known failed or interrupted job can be retried")
        return await self.enqueue(job.command, retry_of=job_id)

    async def cancel(self, job_id: str) -> AdminJob:
        """Cancel queued work or request cooperative running-job cancellation."""
        await self.recover_jobs()
        job = self._jobs.get(job_id)
        if job is None or job.status not in {"queued", "running"}:
            raise ValueError("only a known queued or running job can be cancelled")
        if job.status == "running" and job.command.kind != "backfill_embeddings":
            raise ValueError("this running operation has no safe cancellation boundary")
        self._cancel_events.setdefault(job_id, asyncio.Event()).set()
        await self._execution_coordinator.cancel(job_id)
        cancelled = replace(
            job,
            status="cancelled",
            stage="cancelled",
            message="Cancelled by operator.",
            finished_at=_utc_now(),
            error_code="cancelled",
        )
        self._jobs[job_id] = cancelled
        if self._job_store is not None:
            await self._job_store.cancel(job_id)
        return cancelled

    async def jobs(self) -> JobBoard:
        """Return one active job, FIFO queue, and newest-first bounded history."""
        await self.recover_jobs()
        if self._job_store is not None:
            rows = await self._job_store.list(domain="corpus", limit=MAX_JOB_HISTORY + 16)
            jobs = tuple(_job_from_stored(row) for row in rows if row.kind != LEDGER_KIND)
            active = next((item for item in jobs if item.status == "running"), None)
            queued = tuple(
                sorted(
                    (item for item in jobs if item.status == "queued"),
                    key=lambda item: item.created_at,
                )
            )
            history = tuple(
                item
                for item in jobs
                if item.status in {"succeeded", "failed", "interrupted", "cancelled"}
            )[:MAX_JOB_HISTORY]
            return JobBoard(active, queued, history)
        ordered = sorted(self._jobs.values(), key=lambda item: item.created_at)
        active = next((item for item in ordered if item.status == "running"), None)
        queued = tuple(item for item in ordered if item.status == "queued")
        history = tuple(self._jobs[job_id] for job_id in reversed(self._history))
        return JobBoard(active, queued, history)

    def _publish(self, job_id: str, progress: OperationProgress) -> None:
        """Replace one running job with its newest non-secret progress snapshot."""
        if self._cancel_events.get(job_id, asyncio.Event()).is_set():
            raise JobCancelledError("cancelled by operator")
        job = self._jobs[job_id]
        self._jobs[job_id] = replace(
            job,
            stage=progress.stage,
            current=progress.current,
            total=progress.total,
            message=self._redact(progress.message),
            detail_current=progress.detail_current,
            detail_total=progress.detail_total,
        )
        if self._job_store is not None:
            self._persister.schedule(job_id)

    async def recover_jobs(self) -> None:
        """Mark stale process-owned jobs interrupted once before accepting work."""
        if self._recovered_jobs:
            return
        if self._job_store is not None:
            await self._job_store.interrupt_incomplete("corpus")
        self._recovered_jobs = True

    async def _persist_current_job(self, job_id: str) -> None:
        """Persist the latest in-memory state, collapsing stale progress callbacks."""
        if self._job_store is None or job_id not in self._jobs:
            return
        job = self._jobs[job_id]
        await self._job_store.put(
            job_id,
            status=job.status,
            stage=job.stage,
            current=job.current,
            total=job.total,
            detail_current=job.detail_current,
            detail_total=job.detail_total,
            message=job.message,
            started_at=job.started_at,
            finished_at=job.finished_at,
            error_code=job.error_code,
            result_refs=job.result_refs or {},
        )

    async def _assert_writable_schema(self) -> None:
        """Block every operation when live schema is unavailable or drifted."""
        status, message, _tables = await self._schema_state()
        if status not in {"compatible", "empty"}:
            raise RuntimeError(f"corpus writes are blocked: {message}")

    def _resolve_manifest(self, name: str) -> Path:
        """Resolve one enumerated manifest name inside the configured corpus root."""
        candidate = (self._corpus_root / name).resolve()
        if candidate.parent != self._corpus_root:
            raise ValueError("manifest must be selected from the corpus root")
        allowed = {item.name for item in self._manifest_summaries() if item.valid}
        if name not in allowed:
            raise ValueError("manifest is not a valid selectable corpus manifest")
        return candidate

    async def _run_operation(
        self,
        command: AdminCommand,
        publish: Callable[[OperationProgress], None],
        on_usage: UsageSink | None = None,
    ) -> OperationOutcome:
        """Execute one safe operation through reusable in-process boundaries."""
        if self._operation_runner is not None:
            return await self._operation_runner(command, publish)
        if command.kind not in {"acquire_edgar", "acquire_dart"}:
            await self._assert_writable_schema()

        if command.kind == "acquire_edgar":
            publish(OperationProgress("prepare", 0, 1, "Preparing EDGAR acquisition"))
            result = await acquire_edgar(
                self._corpus_root / DEFAULT_MANIFEST.name,
                tickers=command.identifiers,
                years=command.years,
                user_agent=self._settings.sec_user_agent or "",
                on_progress=publish,
            )
            return OperationOutcome(
                f"Fetched {len(result.fetched)} filing(s)", result.manifest, result.selection_id
            )

        if command.kind == "acquire_dart":
            secret = self._settings.dart_api_key
            if secret is None:
                raise ValueError("DART_API_KEY is not configured")
            result = await acquire_dart(
                stock_codes=command.identifiers,
                fiscal_years=command.years,
                corpus_dir=self._corpus_root,
                api_key=secret.get_secret_value(),
                on_progress=publish,
            )
            return OperationOutcome(
                f"Archived {len(result.archived)} filing(s)", result.manifest, result.selection_id
            )

        if command.kind == "ingest_manifest":
            assert command.manifest is not None
            manifest = self._resolve_manifest(command.manifest)
            assert command.selection_id is not None
            Manifest.read(manifest).selected_sources(command.selection_id, self._corpus_root)
            loop = asyncio.get_running_loop()

            def publish_from_parser(progress: OperationProgress) -> None:
                """Move parser-thread progress safely onto the queue's event loop."""
                loop.call_soon_threadsafe(publish, progress)

            batch = await asyncio.to_thread(
                load_seed_batch,
                manifest,
                selection_id=command.selection_id,
                embedding_provider=self._provider,
                expected_documents=command.expected_documents,
                on_progress=publish_from_parser,
            )
            await asyncio.sleep(0)
            publish(OperationProgress("schema", 0, 1, "Checking schema compatibility"))
            await bootstrap_schema(self._database_engine)
            publish(OperationProgress("schema", 1, 1, "Schema compatible"))
            async with self._session_factory() as session:
                result = await persist_seed_batch_with_stats(
                    session,
                    batch,
                    on_progress=publish,
                )
            return OperationOutcome(
                f"Ingested {result.documents} document(s) and {result.chunks} chunk(s)",
                command.manifest,
                command.selection_id,
            )

        if command.kind == "backfill_embeddings":
            document_ids = None
            if command.manifest is not None or command.selection_id is not None:
                if not command.manifest or not command.selection_id:
                    raise ValueError("selected backfill requires manifest and selection_id")
                manifest_path = self._resolve_manifest(command.manifest)
                sources = Manifest.read(manifest_path).selected_sources(
                    command.selection_id, self._corpus_root
                )
                document_ids = tuple(source.document.document_id for source in sources)
            await bootstrap_schema(self._database_engine)
            async with self._session_factory() as session:
                ready_before, pending = await _embedding_state(
                    session, self._provider, document_ids
                )

            def on_batch(result: EmbeddingBackfillResult) -> None:
                """Publish cumulative batch counts from the resumable backfill."""
                publish(
                    OperationProgress(
                        "embedding",
                        result.embedded + result.skipped_stale,
                        pending,
                        f"Embedded {result.embedded}; skipped stale {result.skipped_stale}",
                    )
                )

            async with self._session_factory() as session:
                result = await embed_missing_chunks(
                    session,
                    self._provider,
                    on_batch=on_batch,
                    document_ids=document_ids,
                    on_usage=on_usage,
                )
            async with self._session_factory() as session:
                ready_after, pending_after = await _embedding_state(
                    session, self._provider, document_ids
                )
            if ready_after < ready_before + result.embedded:
                raise RuntimeError(
                    "embedding postcondition failed: reported rows were not committed"
                )
            if pending_after > max(0, pending - result.embedded):
                raise RuntimeError("embedding postcondition failed: pending rows did not decrease")
            return OperationOutcome(
                f"Embedded {result.embedded} chunk(s); skipped {result.skipped_stale} stale; "
                f"verified {ready_after} ready"
            )

        await bootstrap_schema(self._database_engine)
        publish(OperationProgress("bm25", 0, 1, "Rebuilding BM25 statistics"))
        async with self._session_factory() as session:
            result = await backfill_term_stats(session)
        publish(OperationProgress("bm25", 1, 1, "BM25 statistics rebuilt"))
        return OperationOutcome(f"Rebuilt BM25 statistics for {result.chunks} chunk(s)")

    async def _execute_job(self, queued: AdminJob) -> None:
        """Execute one corpus job while the shared operator lock is held."""
        running = replace(
            queued,
            status="running",
            stage="starting",
            message="Starting",
            started_at=_utc_now(),
        )
        self._jobs[queued.job_id] = running
        if self._job_store is not None:
            self._persister.schedule(queued.job_id)
        try:
            job_id = queued.job_id

            async def record_usage(record: dict[str, object]) -> None:
                """Persist cumulative batch usage without stale progress overwriting it."""
                await self._persister.flush(job_id)
                current = self._jobs[job_id]
                refs = dict(current.result_refs or {})
                previous = refs.get(USAGE_KEY, [])
                if not isinstance(previous, list) or any(
                    not isinstance(row, dict) for row in previous
                ):
                    raise ValueError("Persisted embedding usage ledger is invalid")
                refs[USAGE_KEY] = merge_usage([*previous, record])
                self._jobs[job_id] = replace(current, result_refs=refs)
                await self._persist_current_job(job_id)

            message = await self._run_operation(
                queued.command,
                lambda progress, job_id=job_id: self._publish(job_id, progress),
                on_usage=record_usage,
            )
        except JobCancelledError:
            finished = replace(
                self._jobs[queued.job_id],
                status="cancelled",
                stage="cancelled",
                message="Cancelled by operator.",
                error_code="cancelled",
                finished_at=_utc_now(),
            )
        except Exception as error:  # noqa: BLE001 - job boundary records typed safe failure
            finished = replace(
                self._jobs[queued.job_id],
                status="failed",
                stage="failed",
                message=self._redact(f"{type(error).__name__}: {error}"),
                error_code=(
                    "postcondition_failed"
                    if "postcondition failed" in str(error)
                    else type(error).__name__.lower()
                ),
                finished_at=_utc_now(),
            )
        else:
            result_refs = {}
            if message.manifest is not None:
                result_refs = {"manifest": message.manifest, "selection_id": message.selection_id}
            message = message.summary
            finished = replace(
                self._jobs[queued.job_id],
                status="succeeded",
                stage="complete",
                message=self._redact(message),
                finished_at=_utc_now(),
                result_refs={
                    **(self._jobs[queued.job_id].result_refs or {}),
                    **result_refs,
                    "summary": self._redact(message),
                },
            )
        self._jobs[queued.job_id] = finished
        await self._persister.write_final(queued.job_id)
        self._history.append(queued.job_id)
        self._cancel_events.pop(queued.job_id, None)

    async def _abandon_job(self, queued: AdminJob, error: Exception) -> None:
        """Record a worker-level failure so a broken job never stays running."""
        current = self._jobs.get(queued.job_id, queued)
        if current.status in {"queued", "running"}:
            self._jobs[queued.job_id] = replace(
                current,
                status="failed",
                stage="failed",
                message=self._redact(f"{type(error).__name__}: {error}"),
                error_code="worker_error",
                finished_at=_utc_now(),
            )
            await self._persister.write_final(queued.job_id)
        if queued.job_id not in self._history:
            self._history.append(queued.job_id)
        self._cancel_events.pop(queued.job_id, None)

    async def _work(self) -> None:
        """Run queued jobs serially through the shared corpus/evaluation lock."""
        while not self._queue.empty():
            queued = await self._queue.get()
            try:
                if self._jobs.get(queued.job_id, queued).status == "cancelled":
                    self._history.append(queued.job_id)
                    continue
                async with self._execution_coordinator.turn(queued.job_id):
                    async with self._execution_lock:
                        if self._jobs.get(queued.job_id, queued).status != "cancelled":
                            try:
                                await self._execute_job(queued)
                            except Exception as error:  # noqa: BLE001 - the worker outlives one job
                                await self._abandon_job(queued, error)
                        else:
                            self._history.append(queued.job_id)
            except JobTurnCancelledError:
                if queued.job_id not in self._history:
                    self._history.append(queued.job_id)
            finally:
                self._queue.task_done()
