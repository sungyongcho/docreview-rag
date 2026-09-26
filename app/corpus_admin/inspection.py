"""Read live corpus state for the administrator without writing files or rows.

Readiness polls, the administrator header and the document table all ask the same
question: is the schema usable, and how much of the corpus is indexed? One status
probe answers it, and the snapshot builds on that probe so status and document
counts share the same reading.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
import os
from pathlib import Path
import time

from sqlalchemy import func, inspect, select

from app.corpus_admin.context import CorpusAdminContext
from app.corpus_admin.types import (
    AdminDocument,
    CorpusSnapshot,
    CorpusStatus,
    ManifestIssuer,
    ManifestSummary,
    ProcessingSelectionSummary,
    SchemaStatus,
)
from app.db.bootstrap import SchemaDriftError, ensure_schema_compatibility
from app.db.models import (
    Base,
    BM25CorpusStat,
    Chunk,
    ChunkEmbedding,
    Document,
    OperatorJob,
)
from app.db.queries import join_current_parse
from app.ingestion.manifest import Manifest
from app.ingestion.source_selection import acquisition_draft, source_inventory
from app.retrieval.embeddings import matching_embedding


@dataclass(frozen=True, slots=True)
class _StatusProbe:
    """One schema and count reading with the monotonic time it was taken."""

    schema_status: SchemaStatus
    schema_message: str
    tables: frozenset[str]
    documents: int
    chunks: int
    embedded_chunks: int
    bm25_ready: bool
    observed_at: float
    bm25_rebuild_recorded: bool = False


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


def _is_root_catalog(name: str) -> bool:
    """Accept common catalog names and skip the per-selection copies stored beside them."""
    if name.startswith("selected-"):
        return False
    return name == "manifest.json" or name.endswith("-manifest.json")


def _company_name(issuer: str, aliases: tuple[str, ...]) -> str:
    """Prefer the first alias that differs from the issuer code, such as a company name."""
    for alias in aliases:
        if alias != issuer:
            return alias
    return issuer


def _manifest_issuers(manifest: Manifest) -> tuple[ManifestIssuer, ...]:
    """List each registry company once, in a stable order, before any source is fetched."""
    issuers: dict[tuple[str, str], ManifestIssuer] = {}
    for document in manifest.documents:
        name = _company_name(document.issuer, document.aliases)
        issuers[(document.registry, document.issuer)] = ManifestIssuer(
            document.registry, document.issuer, name
        )
    return tuple(issuers[key] for key in sorted(issuers))


class CorpusInspector:
    """Probe corpus status and project live snapshots.

    Parameters
    ----------
    context : CorpusAdminContext
        Corpus root, database handles and embedding provider to read through.
    """

    def __init__(self, context: CorpusAdminContext) -> None:
        self._context = context
        self._status_lock = asyncio.Lock()
        self._status_cache: _StatusProbe | None = None

    async def schema_state(self) -> tuple[SchemaStatus, str, set[str]]:
        """Inspect compatibility and table presence without creating schema objects."""
        try:
            async with self._context.database_engine.connect() as connection:
                await ensure_schema_compatibility(connection)
                tables = await connection.run_sync(
                    lambda sync: set(inspect(sync).get_table_names())
                )
        except SchemaDriftError as error:
            return "drifted", str(error), set()
        except Exception as error:  # noqa: BLE001 - translated into non-secret status
            return "unavailable", self._context.redact(type(error).__name__), set()
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

    def manifest_summaries(self) -> tuple[ManifestSummary, ...]:
        """Validate root catalogs and expose exact processing selections."""
        summaries = []
        for path in sorted(self._context.corpus_root.glob("*.json")):
            if _is_root_catalog(path.name):
                summaries.append(self._manifest_summary(path))
        return tuple(summaries)

    def _manifest_summary(self, path: Path) -> ManifestSummary:
        """Summarize one root catalog, or mark it invalid when it cannot be read safely."""
        corpus_root = self._context.corpus_root
        try:
            if path.resolve().parent != corpus_root:
                raise ValueError("manifest resolves outside the corpus root")
            manifest = Manifest.read(path)
        except OSError, ValueError:
            return ManifestSummary(path.name, None, False)
        present = self._artifacts_on_disk(manifest)
        issuers = _manifest_issuers(manifest)
        selections = self._selection_summaries(manifest, present)
        registries = tuple(sorted({document.registry for document in manifest.documents}))
        # A primary source and its archive copy are one filing, so count documents.
        documents_on_disk = {
            artifact.document_id
            for artifact in manifest.artifacts
            if artifact.role == "primary" and present[artifact.artifact_id]
        }
        return ManifestSummary(
            path.name,
            len(manifest.documents),
            True,
            manifest.corpus.corpus_id,
            registries,
            len(documents_on_disk),
            selections,
            issuers,
        )

    def _artifacts_on_disk(self, manifest: Manifest) -> dict[str, bool]:
        """Map each artifact to whether its file exists inside the corpus root."""
        corpus_root = self._context.corpus_root
        present: dict[str, bool] = {}
        for artifact in manifest.artifacts:
            source = (corpus_root / artifact.path).resolve()
            present[artifact.artifact_id] = source.is_relative_to(corpus_root) and source.is_file()
        return present

    def _selection_summaries(
        self, manifest: Manifest, present: dict[str, bool]
    ) -> tuple[ProcessingSelectionSummary, ...]:
        """Expose the exact documents and artifacts each processing selection names."""
        selections = []
        for selection in manifest.selections:
            sources = manifest.selected_sources(selection.selection_id, self._context.corpus_root)
            selections.append(
                ProcessingSelectionSummary(
                    selection.selection_id,
                    tuple(source.document.document_id for source in sources),
                    tuple(source.artifact.artifact_id for source in sources),
                    sum(present[source.artifact.artifact_id] for source in sources),
                )
            )
        return tuple(selections)

    async def _counts(self, tables: set[str]) -> tuple[int, int, int, bool]:
        """Return corpus and index counts only when their tables exist."""
        if not {"documents", "chunks"}.issubset(tables):
            return 0, 0, 0, False
        async with self._context.session_factory() as session:
            documents = int(await session.scalar(select(func.count()).select_from(Document)) or 0)
            chunks = int(await session.scalar(select(func.count()).select_from(Chunk)) or 0)
            embedded = int(
                await session.scalar(
                    select(func.count())
                    .select_from(Chunk)
                    .where(
                        select(ChunkEmbedding.chunk_id)
                        .where(matching_embedding(self._context.embedding_provider.identity))
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
        async with self._context.session_factory() as session:
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

    async def _bm25_rebuild_recorded(self, tables: set[str]) -> bool:
        """Remember an explicit completed rebuild even after chunk changes invalidate its rows."""
        if "operator_jobs" not in tables:
            return False
        async with self._context.session_factory() as session:
            return bool(
                await session.scalar(
                    select(
                        select(OperatorJob.job_id)
                        .where(
                            OperatorJob.domain == "corpus",
                            OperatorJob.kind == "rebuild_bm25",
                            OperatorJob.status == "succeeded",
                        )
                        .exists()
                    )
                )
            )

    async def _probe_status(self, max_age_s: float) -> _StatusProbe:
        """Inspect schema state and counts, reusing a reading younger than ``max_age_s``.

        Concurrent callers share one measurement, and every outcome is memoized, so a
        readiness poll that lands while the database is busy never adds catalog sweeps.
        """
        async with self._status_lock:
            cached = self._status_cache
            if cached is not None and time.monotonic() - cached.observed_at < max_age_s:
                return cached
            schema_status, schema_message, tables = await self.schema_state()
            documents = chunks = embedded = 0
            bm25_ready = False
            rebuild_recorded = False
            if schema_status == "compatible":
                try:
                    documents, chunks, embedded, bm25_ready = await self._counts(tables)
                    rebuild_recorded = bm25_ready or await self._bm25_rebuild_recorded(tables)
                except Exception as error:  # noqa: BLE001 - rendered as safe unavailable state
                    schema_status = "unavailable"
                    schema_message = self._context.redact(type(error).__name__)
            probe = _StatusProbe(
                schema_status=schema_status,
                schema_message=schema_message,
                tables=frozenset(tables),
                documents=documents,
                chunks=chunks,
                embedded_chunks=embedded,
                bm25_ready=bm25_ready,
                observed_at=time.monotonic(),
                bm25_rebuild_recorded=rebuild_recorded,
            )
            self._status_cache = probe
            return probe

    def _status_from(self, probe: _StatusProbe) -> CorpusStatus:
        """Render one probe as the non-secret status the header and ``/ready`` share."""
        return CorpusStatus(
            database_connected=probe.schema_status != "unavailable",
            schema_status=probe.schema_status,
            schema_message=probe.schema_message,
            documents=probe.documents,
            chunks=probe.chunks,
            embedded_chunks=probe.embedded_chunks,
            pending_embeddings=max(probe.chunks - probe.embedded_chunks, 0),
            bm25_ready=probe.bm25_ready,
            bm25_rebuild_recorded=probe.bm25_rebuild_recorded,
            writable=os.access(self._context.corpus_root, os.W_OK | os.X_OK),
            provider=self._context.settings.embedding_provider,
        )

    async def status(self, *, max_age_s: float = 0.0) -> CorpusStatus:
        """Return the operational status alone, without document rows or file scans.

        ``max_age_s`` lets ``/ready`` reuse a recent reading; ``0.0`` always measures.
        """
        return self._status_from(await self._probe_status(max_age_s))

    def invalidate_status(self) -> None:
        """Drop the memoized reading so the next status call measures again."""
        self._status_cache = None

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
        probe = await self._probe_status(0.0)
        rows: tuple[AdminDocument, ...] = ()
        if probe.schema_status == "compatible":
            try:
                rows = await self._documents(set(probe.tables))
            except Exception as error:  # noqa: BLE001 - rendered as safe unavailable state
                # Report this snapshot as unavailable; the memoized probe stays as measured.
                probe = replace(
                    probe,
                    schema_status="unavailable",
                    schema_message=self._context.redact(type(error).__name__),
                )
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
        sources = source_inventory(self._context.corpus_root)
        return CorpusSnapshot(
            mode="live",
            status=self._status_from(probe),
            manifests=self.manifest_summaries(),
            sources=sources,
            acquisition_draft=acquisition_draft(self._context.corpus_root),
            documents=filtered,
        )
