"""Run one validated corpus command against source files and PostgreSQL.

Each command kind has its own method. Acquisition only writes source files, so it
runs even when the corpus schema is unusable; every other kind writes corpus rows
and first checks that the schema is compatible or still empty.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.corpus_admin.context import CorpusAdminContext
from app.corpus_admin.inspection import CorpusInspector
from app.corpus_admin.types import AdminCommand, OperationOutcome
from app.db.bootstrap import bootstrap_schema
from app.db.models import Chunk, ChunkEmbedding
from app.ingestion.dart_api import acquire_dart
from app.ingestion.edgar_api import DEFAULT_MANIFEST, acquire_edgar
from app.ingestion.manifest import Manifest
from app.ingestion.progress import OperationProgress, OperationProgressCallback
from app.ingestion.seed import load_seed_batch, persist_seed_batch
from app.ingestion.source_deletion import SourceDeletion
from app.observability.usage import UsageSink
from app.retrieval.bm25 import backfill_term_stats
from app.retrieval.embeddings import (
    EmbeddingBackfillResult,
    EmbeddingProvider,
    embed_missing_chunks,
    matching_embedding,
)

OperationRunner = Callable[
    [AdminCommand, OperationProgressCallback],
    Awaitable[OperationOutcome],
]


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


class CorpusOperations:
    """Execute validated corpus commands through reusable in-process boundaries.

    Parameters
    ----------
    context : CorpusAdminContext
        Settings, corpus root, database handles and embedding provider to write with.
    inspector : CorpusInspector
        Schema state and root catalogs that decide whether a write may start.
    source_deletion : SourceDeletion
        Deletion approvals that previews reserved for this service.
    operation_runner : OperationRunner | None
        Replacement for every operation except source deletion, or ``None`` to run
        the real acquisition, ingestion, embedding and BM25 steps.
    """

    def __init__(
        self,
        context: CorpusAdminContext,
        inspector: CorpusInspector,
        source_deletion: SourceDeletion,
        operation_runner: OperationRunner | None,
    ) -> None:
        self._context = context
        self._inspector = inspector
        self._source_deletion = source_deletion
        self._operation_runner = operation_runner

    async def run(
        self,
        command: AdminCommand,
        publish: OperationProgressCallback,
        on_usage: UsageSink | None = None,
    ) -> OperationOutcome:
        """Execute one safe operation through reusable in-process boundaries."""
        if command.kind == "delete_sources":
            return await self._delete_sources(command, publish)
        if self._operation_runner is not None:
            return await self._operation_runner(command, publish)
        if command.kind == "acquire_edgar":
            return await self._acquire_edgar(command, publish)
        if command.kind == "acquire_dart":
            return await self._acquire_dart(command, publish)
        # Every remaining kind writes corpus rows, so a drifted schema stops it here.
        await self._assert_writable_schema()
        if command.kind == "ingest_manifest":
            return await self._ingest_manifest(command, publish)
        if command.kind == "backfill_embeddings":
            return await self._backfill_embeddings(command, publish, on_usage)
        return await self._rebuild_bm25(publish)

    async def _assert_writable_schema(self) -> None:
        """Block every operation when live schema is unavailable or drifted."""
        status, message, _tables = await self._inspector.schema_state()
        if status not in {"compatible", "empty"}:
            raise RuntimeError(f"corpus writes are blocked: {message}")

    def _resolve_manifest(self, name: str) -> Path:
        """Resolve one enumerated manifest name inside the configured corpus root."""
        corpus_root = self._context.corpus_root
        candidate = (corpus_root / name).resolve()
        if candidate.parent != corpus_root:
            raise ValueError("manifest must be selected from the corpus root")
        if name.startswith("selected-") and name.endswith("-manifest.json") and candidate.is_file():
            catalog = Manifest.read(candidate)
            if (
                len(catalog.selections) == 1
                and name == f"{catalog.selections[0].selection_id}-manifest.json"
            ):
                return candidate
        allowed = {item.name for item in self._inspector.manifest_summaries() if item.valid}
        if name not in allowed:
            raise ValueError("manifest is not a valid selectable corpus manifest")
        return candidate

    async def _delete_sources(
        self, command: AdminCommand, publish: OperationProgressCallback
    ) -> OperationOutcome:
        """Delete the originals one fresh preview approved, off the event loop."""
        assert command.deletion_token is not None
        publish(OperationProgress("delete_sources", 0, 1, "Checking confirmed originals"))
        summary = await asyncio.to_thread(self._source_deletion.execute, command.deletion_token)
        publish(OperationProgress("delete_sources", 1, 1, summary))
        return OperationOutcome(summary)

    async def _acquire_edgar(
        self, command: AdminCommand, publish: OperationProgressCallback
    ) -> OperationOutcome:
        """Fetch SEC filings into the common catalog and report the new selection."""
        publish(OperationProgress("prepare", 0, 1, "Preparing EDGAR acquisition"))
        result = await acquire_edgar(
            self._context.corpus_root / DEFAULT_MANIFEST.name,
            tickers=command.identifiers,
            years=command.years,
            user_agent=self._context.settings.sec_user_agent or "",
            on_progress=publish,
        )
        return OperationOutcome(
            f"Fetched {len(result.fetched)} filing(s)", result.manifest, result.selection_id
        )

    async def _acquire_dart(
        self, command: AdminCommand, publish: OperationProgressCallback
    ) -> OperationOutcome:
        """Archive DART filings with the server's API key and report the new selection."""
        secret = self._context.settings.dart_api_key
        if secret is None:
            raise ValueError("DART_API_KEY is not configured")
        result = await acquire_dart(
            stock_codes=command.identifiers,
            fiscal_years=command.years,
            corpus_dir=self._context.corpus_root,
            api_key=secret.get_secret_value(),
            on_progress=publish,
        )
        return OperationOutcome(
            f"Archived {len(result.archived)} filing(s)", result.manifest, result.selection_id
        )

    async def _ingest_manifest(
        self, command: AdminCommand, publish: OperationProgressCallback
    ) -> OperationOutcome:
        """Parse one exact selection in a worker thread, then persist its chunks."""
        assert command.manifest is not None
        manifest = self._resolve_manifest(command.manifest)
        assert command.selection_id is not None
        # Reject an unknown selection before any parser work starts.
        Manifest.read(manifest).selected_sources(command.selection_id, self._context.corpus_root)
        loop = asyncio.get_running_loop()

        def publish_from_parser(progress: OperationProgress) -> None:
            """Move parser-thread progress safely onto the queue's event loop."""
            loop.call_soon_threadsafe(publish, progress)

        batch = await asyncio.to_thread(
            load_seed_batch,
            manifest,
            selection_id=command.selection_id,
            embedding_provider=self._context.embedding_provider,
            expected_documents=command.expected_documents,
            on_progress=publish_from_parser,
        )
        # Let the parser's queued progress land before the next stage is published.
        await asyncio.sleep(0)
        publish(OperationProgress("schema", 0, 1, "Checking schema compatibility"))
        await bootstrap_schema(self._context.database_engine)
        publish(OperationProgress("schema", 1, 1, "Schema compatible"))
        async with self._context.session_factory() as session:
            result = await persist_seed_batch(
                session,
                batch,
                on_progress=publish,
            )
        return OperationOutcome(
            f"Ingested {result.documents} document(s) and {result.chunks} chunk(s)",
            command.manifest,
            command.selection_id,
        )

    async def _backfill_embeddings(
        self,
        command: AdminCommand,
        publish: OperationProgressCallback,
        on_usage: UsageSink | None,
    ) -> OperationOutcome:
        """Embed missing chunks, then check the committed rows match what was reported."""
        document_ids = self._backfill_scope(command)
        await bootstrap_schema(self._context.database_engine)
        async with self._context.session_factory() as session:
            ready_before, pending = await _embedding_state(
                session, self._context.embedding_provider, document_ids
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

        async with self._context.session_factory() as session:
            result = await embed_missing_chunks(
                session,
                self._context.embedding_provider,
                on_batch=on_batch,
                document_ids=document_ids,
                on_usage=on_usage,
            )
        async with self._context.session_factory() as session:
            ready_after, pending_after = await _embedding_state(
                session, self._context.embedding_provider, document_ids
            )
        # A backfill that reports rows the database does not hold must fail, not succeed.
        if ready_after < ready_before + result.embedded:
            raise RuntimeError("embedding postcondition failed: reported rows were not committed")
        if pending_after > max(0, pending - result.embedded):
            raise RuntimeError("embedding postcondition failed: pending rows did not decrease")
        return OperationOutcome(
            f"Embedded {result.embedded} chunk(s); skipped {result.skipped_stale} stale; "
            f"verified {ready_after} ready"
        )

    def _backfill_scope(self, command: AdminCommand) -> tuple[str, ...] | None:
        """Return the selected document IDs, or ``None`` to backfill the whole corpus."""
        if command.manifest is None and command.selection_id is None:
            return None
        if not command.manifest or not command.selection_id:
            raise ValueError("selected backfill requires manifest and selection_id")
        manifest_path = self._resolve_manifest(command.manifest)
        sources = Manifest.read(manifest_path).selected_sources(
            command.selection_id, self._context.corpus_root
        )
        return tuple(source.document.document_id for source in sources)

    async def _rebuild_bm25(self, publish: OperationProgressCallback) -> OperationOutcome:
        """Recompute BM25 term statistics for every chunk in the corpus."""
        await bootstrap_schema(self._context.database_engine)
        publish(OperationProgress("bm25", 0, 1, "Rebuilding BM25 statistics"))
        async with self._context.session_factory() as session:
            result = await backfill_term_stats(session)
        publish(OperationProgress("bm25", 1, 1, "BM25 statistics rebuilt"))
        return OperationOutcome(f"Rebuilt BM25 statistics for {result.chunks} chunk(s)")
