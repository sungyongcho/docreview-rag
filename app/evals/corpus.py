"""Build and index one isolated evaluation corpus without touching the populated one."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
import time

from pgvector.sqlalchemy import Vector
from sqlalchemy import CheckConstraint, MetaData, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession

from app.config import Settings, get_settings
from app.db.models import Base
from app.evals.measurement import Clock, IndexingBudgetMeasurement, assess_indexing_budget
from app.ingestion.chunk import Chunk, chunk_filing
from app.ingestion.parser import ParsedFiling
from app.ingestion.progress import OperationProgress, OperationProgressCallback
from app.ingestion.seed import (
    DEFAULT_MANIFEST_NAME,
    SeedBatch,
    build_seed_batch,
    build_seed_batch_from_filings,
    embedding_chunk_config,
    load_manifest,
    parse_seed_filings,
    persist_seed_batch,
)
from app.retrieval.bm25 import backfill_term_stats
from app.retrieval.embeddings import (
    EmbeddingBackfillResult,
    EmbeddingProvider,
    embed_missing_chunks,
)


def load_chunking_filings(
    *,
    settings: Settings | None = None,
    selection_id: str,
    manifest_name: str = DEFAULT_MANIFEST_NAME,
    expected_documents: int | None = None,
    on_progress: OperationProgressCallback | None = None,
) -> tuple[ParsedFiling, ...]:
    """Parse the fixed evaluation corpus once for reuse by every chunking arm.

    Parameters
    ----------
    settings : Settings | None, optional
        Explicit corpus settings, or the process settings when omitted.
    selection_id : str
        Exact common-manifest processing selection to evaluate.
    manifest_name : str, optional
        Manifest file under the configured corpus directory. One manifest describes one
        corpus, so a second registry is selected here rather than merged into the first.
    expected_documents : int | None, optional
        Document count the named manifest must hold, or ``None`` to accept any count.

    Returns
    -------
    tuple[ParsedFiling, ...]
        Deterministically ordered parsed filings shared by the current evaluation run.

    Raises
    ------
    OSError
        If the configured manifest or a filing source cannot be read.
    json.JSONDecodeError
        If the manifest does not contain valid JSON.
    ValueError
        If the manifest is invalid, does not hold the expected document count, or a filing
        cannot satisfy parser contracts.

    Notes
    -----
    Returned parser models are mutable. The evaluation runner shares them read-only
    across chunk targets and builds a fresh immutable ``SeedBatch`` for each target.
    """
    configured = settings or get_settings()
    entries = load_manifest(configured.corpus_dir / manifest_name, selection_id=selection_id)
    return parse_seed_filings(
        entries,
        expected_documents=expected_documents,
        on_progress=on_progress,
    )


def build_chunking_batch(
    target_tokens: int,
    *,
    provider: EmbeddingProvider,
    parsed_filings: Sequence[ParsedFiling] | None = None,
    settings: Settings | None = None,
    selection_id: str,
    manifest_name: str = DEFAULT_MANIFEST_NAME,
    expected_documents: int | None = None,
    on_progress: OperationProgressCallback | None = None,
) -> SeedBatch:
    """Build one source-stable corpus arm from new or already parsed filings.

    Parameters
    ----------
    target_tokens : int
        Soft token-count target for the structure-aware chunker.
    provider : EmbeddingProvider
        Exact model budget and token counter used to plan the experiment chunks.
    parsed_filings : Sequence[ParsedFiling] | None, optional
        Parsed corpus snapshot to reuse. When omitted, this call loads and parses
        the configured manifest itself.
    settings : Settings | None, optional
        Explicit corpus settings used only by the independent path.
    selection_id : str
        Exact common-manifest processing selection to evaluate.
    manifest_name : str, optional
        Manifest file the independent path reads under the configured corpus directory.
    expected_documents : int | None, optional
        Document count that manifest must hold, or ``None`` to accept any count.

    Returns
    -------
    SeedBatch
        Validated records with canonical source spans unchanged.

    Raises
    ------
    OSError
        If independent construction cannot read the manifest or a filing source.
    json.JSONDecodeError
        If the independently loaded manifest does not contain valid JSON.
    ValueError
        If the target, manifest, parser output, chunks, or persistence records violate
        their source and ordering contracts.

    Notes
    -----
    Supplying ``parsed_filings`` bypasses settings and manifest parsing. The shared
    parser models are treated as read-only, and a new batch is returned for each call.
    """
    chunk_config = embedding_chunk_config(provider, target_tokens=target_tokens)

    def chunker(filing: ParsedFiling) -> list[Chunk]:
        """Chunk one parsed filing with the selected target."""
        return chunk_filing(filing, chunk_config)

    if parsed_filings is not None:
        return build_seed_batch_from_filings(
            parsed_filings,
            chunker=chunker,
            on_progress=on_progress,
        )

    configured = settings or get_settings()
    entries = load_manifest(configured.corpus_dir / manifest_name, selection_id=selection_id)
    return build_seed_batch(
        entries,
        expected_documents=expected_documents,
        chunker=chunker,
        on_progress=on_progress,
    )


def _temporary_metadata(dimensions: int) -> MetaData:
    """Clone the actual normalized schema with experiment-specific vector width."""
    if type(dimensions) is not int or dimensions <= 0:
        raise ValueError("embedding dimensions must be a positive integer")
    metadata = MetaData()
    for table in Base.metadata.sorted_tables:
        copied = table.to_metadata(metadata)
        copied._prefixes = (*copied._prefixes, "TEMPORARY")
        copied.dialect_options["postgresql"]["on_commit"] = "PRESERVE ROWS"
        for constraint in copied.constraints:
            if (
                isinstance(constraint, CheckConstraint)
                and constraint.name == "ck_chunk_embeddings_dimensions"
            ):
                constraint.sqltext = text(f"dimensions = {dimensions}")
        for column in copied.columns:
            if isinstance(column.type, Vector):
                column.type = Vector(dimensions)
    return metadata


async def _create_temporary_corpus_tables(connection: AsyncConnection, dimensions: int) -> None:
    """Create the isolated PostgreSQL schema for one corpus arm.

    Parameters
    ----------
    connection : AsyncConnection
        Dedicated connection whose session-local temporary tables hold the corpus.
    dimensions : int
        Positive embedding width used by the temporary pgvector column.

    Raises
    ------
    ValueError
        If ``dimensions`` is not a positive integer.
    RuntimeError
        If the connected database does not expose the pgvector extension.

    Notes
    -----
    Tables preserve rows across commits but remain scoped to ``connection``. The helper
    commits the temporary DDL before callers bind a session and seed data.
    """
    if isinstance(dimensions, bool) or not isinstance(dimensions, int) or dimensions <= 0:
        raise ValueError("embedding dimensions must be a positive integer")
    extension = await connection.scalar(
        text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
    )
    if extension is None:
        raise RuntimeError("the configured PostgreSQL database does not have pgvector")
    metadata = _temporary_metadata(dimensions)
    await connection.run_sync(lambda sync: metadata.create_all(sync, checkfirst=False))
    await connection.commit()


@asynccontextmanager
async def temporary_corpus_session(
    engine: AsyncEngine,
    batch: SeedBatch,
    provider: EmbeddingProvider,
    *,
    target_tokens: int,
    embedding_provider: str,
    shared_preparation_seconds: float = 0.0,
    clock: Clock = time.perf_counter_ns,
    started_at_ns: int | None = None,
    on_progress: OperationProgressCallback | None = None,
) -> AsyncIterator[tuple[AsyncSession, IndexingBudgetMeasurement]]:
    """Index one isolated corpus arm within a connection-scoped session.

    Parameters
    ----------
    engine : AsyncEngine
        Engine used to acquire the dedicated temporary-corpus connection.
    batch : SeedBatch
        Complete source-stable records for one chunking target.
    provider : EmbeddingProvider
        Provider used to populate every missing temporary embedding.
    target_tokens : int
        Chunk-size target attached to indexing evidence.
    embedding_provider : str
        Provider identity recorded with the measurement.
    shared_preparation_seconds : float, optional
        Parse-once duration charged to the arm's derived standalone total.
    clock : Clock, optional
        Monotonic nanosecond clock used for target-phase timing. It must be the same
        clock that produced ``started_at_ns``.
    started_at_ns : int | None, optional
        Earlier target-phase start, allowing caller-side batch construction to be included;
        otherwise timing begins when this context manager is entered.

    Yields
    ------
    tuple[AsyncSession, IndexingBudgetMeasurement]
        Session containing the indexed temporary corpus and its completed budget evidence.

    Raises
    ------
    RuntimeError
        If pgvector is unavailable or embedding backfill does not cover the full batch.
    ValueError
        If timing or indexing evidence violates the budget measurement contract.

    Notes
    -----
    Term statistics are rebuilt once per chunking arm before embeddings, and the indexed
    corpus is committed before the arm is yielded. That commit is what makes the corpus a
    stable baseline: a failed statement in one experiment aborts only its own transaction,
    and a caller's ``rollback`` returns to the full corpus instead of an empty one. Context
    exit always closes the session and its connection, which discards all temporary corpus
    state; the caller retains ownership of the engine.
    """
    started = clock() if started_at_ns is None else started_at_ns
    connection = await engine.connect()
    session: AsyncSession | None = None
    try:
        if on_progress is not None:
            on_progress(OperationProgress("temporary_schema", 0, 1, "Creating isolated tables"))
        await _create_temporary_corpus_tables(connection, provider.dimensions)
        if on_progress is not None:
            on_progress(OperationProgress("temporary_schema", 1, 1, "Isolated tables ready"))
        session = AsyncSession(bind=connection, expire_on_commit=False)
        await persist_seed_batch(session, batch, on_progress=on_progress)
        # One rebuild per corpus arm. Every BM25 experiment on this chunking shares
        # it, and the next chunk target gets its own corpus and its own statistics,
        # because df, avgdl, and dl are all properties of a particular chunking.
        if on_progress is not None:
            on_progress(OperationProgress("bm25", 0, 1, "Rebuilding term statistics"))
        await backfill_term_stats(session)
        if on_progress is not None:
            on_progress(OperationProgress("bm25", 1, 1, "Term statistics rebuilt"))

        def on_embedding_batch(result: EmbeddingBackfillResult) -> None:
            """Project cumulative embedding batches onto the operation callback."""
            if on_progress is not None:
                on_progress(
                    OperationProgress(
                        "embedding",
                        result.batches,
                        None,
                        f"{result.embedded} chunks stored",
                    )
                )

        backfill = await embed_missing_chunks(session, provider, on_batch=on_embedding_batch)
        if on_progress is not None:
            on_progress(
                OperationProgress(
                    "embedding",
                    backfill.batches,
                    backfill.batches,
                    f"{backfill.embedded} chunks stored",
                )
            )
        if backfill.embedded != len(batch.chunks) or backfill.skipped_stale:
            raise RuntimeError("temporary corpus embedding backfill was incomplete")
        await session.commit()
        target_phase_seconds = (clock() - started) / 1_000_000_000
        measurement = assess_indexing_budget(
            target_tokens=target_tokens,
            document_count=len(batch.documents),
            chunk_count=len(batch.chunks),
            embedding_provider=embedding_provider,
            target_phase_seconds=target_phase_seconds,
            shared_preparation_seconds=shared_preparation_seconds,
        )
        yield session, measurement
    finally:
        if session is not None:
            await session.close()
        await connection.invalidate()
        await connection.close()
