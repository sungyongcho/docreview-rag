"""Build and index one isolated evaluation corpus without touching the populated one."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
import time

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession

from app.config import Settings, get_settings
from app.db.models import CONTENT_TSV_SQL, LANGUAGE_FORMAT_CHECK_SQL, LEXICAL_TEXT_CHECK_SQL
from app.evals.measurement import Clock, IndexingBudgetMeasurement, assess_indexing_budget
from app.ingestion.chunk import Chunk, ChunkConfig, chunk_filing
from app.ingestion.parser import ParsedFiling
from app.ingestion.seed import (
    DEFAULT_MANIFEST_NAME,
    EXPECTED_DOCUMENTS,
    SeedBatch,
    build_seed_batch,
    build_seed_batch_from_filings,
    load_manifest,
    parse_seed_filings,
    persist_seed_batch,
)
from app.retrieval.bm25 import backfill_term_stats
from app.retrieval.embeddings import EmbeddingProvider, embed_missing_chunks


def load_chunking_filings(
    *,
    settings: Settings | None = None,
    manifest_name: str = DEFAULT_MANIFEST_NAME,
    expected_documents: int | None = EXPECTED_DOCUMENTS,
) -> tuple[ParsedFiling, ...]:
    """Parse the fixed evaluation corpus once for reuse by every chunking arm.

    Parameters
    ----------
    settings : Settings | None, optional
        Explicit corpus settings, or the process settings when omitted.
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
    entries = load_manifest(configured.corpus_dir / manifest_name)
    return parse_seed_filings(entries, expected_documents=expected_documents)


def build_chunking_batch(
    target_text_chars: int,
    *,
    parsed_filings: Sequence[ParsedFiling] | None = None,
    settings: Settings | None = None,
    manifest_name: str = DEFAULT_MANIFEST_NAME,
    expected_documents: int | None = EXPECTED_DOCUMENTS,
) -> SeedBatch:
    """Build one source-stable corpus arm from new or already parsed filings.

    Parameters
    ----------
    target_text_chars : int
        Soft text-length target for the structure-aware chunker.
    parsed_filings : Sequence[ParsedFiling] | None, optional
        Parsed corpus snapshot to reuse. When omitted, this call loads and parses
        the configured manifest itself.
    settings : Settings | None, optional
        Explicit corpus settings used only by the independent path.
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
    chunk_config = ChunkConfig(target_text_chars=target_text_chars)

    def chunker(filing: ParsedFiling) -> list[Chunk]:
        """Chunk one parsed filing with the selected target."""
        return chunk_filing(filing, chunk_config)

    if parsed_filings is not None:
        return build_seed_batch_from_filings(parsed_filings, chunker=chunker)

    configured = settings or get_settings()
    entries = load_manifest(configured.corpus_dir / manifest_name)
    return build_seed_batch(
        entries,
        expected_documents=expected_documents,
        chunker=chunker,
    )


# The temporary schema mirrors app/db/models.py, including every CHECK constraint, so a
# record rejected by the populated corpus is rejected here too. It is written out rather
# than derived from Base.metadata because the embedding width follows the experiment's
# provider, not the application's configured dimension.
_TEMPORARY_CORPUS_DDL: tuple[str, ...] = (
    """
    CREATE TEMP TABLE documents (
        doc_id varchar(32) PRIMARY KEY,
        registry varchar(16) NOT NULL,
        language varchar(8) NOT NULL,
        issuer varchar(32) NOT NULL,
        issuer_id varchar(64) NOT NULL,
        fiscal_year integer NOT NULL,
        form varchar(32) NOT NULL,
        filing_date varchar(10) NOT NULL,
        report_period varchar(10) NOT NULL,
        filing_id varchar(64) NOT NULL,
        source_url text NOT NULL,
        parse_status varchar(32) NOT NULL,
        item_index jsonb NOT NULL,
        source_length bigint NOT NULL,
        source_sha256 varchar(64) NOT NULL,
        CONSTRAINT ck_documents_parse_status
            CHECK (parse_status IN ('parsed', 'needs_profile_update')),
        CONSTRAINT ck_documents_source_length_positive CHECK (source_length > 0),
        CONSTRAINT ck_documents_language_format CHECK ({language_format_check_sql}),
        CONSTRAINT ck_documents_source_sha256_format
            CHECK (source_sha256 ~ '^[0-9a-f]{{64}}$')
    ) ON COMMIT PRESERVE ROWS
    """,
    """
    CREATE TEMP TABLE chunks (
        id bigserial PRIMARY KEY,
        doc_id varchar(32) NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
        language varchar(8) NOT NULL,
        item varchar(8),
        kind varchar(16) NOT NULL,
        ordinal integer NOT NULL,
        body text NOT NULL,
        context_header text NOT NULL,
        index_text text NOT NULL,
        start_char bigint NOT NULL,
        end_char bigint NOT NULL,
        source_sha256 varchar(64) NOT NULL,
        citation text NOT NULL,
        lexical_text text,
        embedding vector({dimensions}),
        content_tsv tsvector GENERATED ALWAYS AS ({content_tsv_sql}) STORED,
        created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT uq_doc_ordinal UNIQUE (doc_id, ordinal),
        CONSTRAINT ck_chunks_ordinal_nonnegative CHECK (ordinal >= 0),
        CONSTRAINT ck_chunks_kind CHECK (kind IN ('text', 'table')),
        CONSTRAINT ck_chunks_language_format CHECK ({language_format_check_sql}),
        CONSTRAINT ck_chunks_lexical_text_language CHECK ({lexical_text_check_sql}),
        CONSTRAINT ck_chunks_start_nonnegative CHECK (start_char >= 0),
        CONSTRAINT ck_chunks_span_order CHECK (end_char > start_char),
        CONSTRAINT ck_chunks_source_sha256_format
            CHECK (source_sha256 ~ '^[0-9a-f]{{64}}$')
    ) ON COMMIT PRESERVE ROWS
    """,
    "CREATE INDEX ON chunks USING gin (content_tsv)",
    "CREATE INDEX ON chunks (doc_id)",
    """
    CREATE TEMP TABLE chunk_terms (
        chunk_id bigint NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
        lexeme text NOT NULL,
        tf integer NOT NULL,
        PRIMARY KEY (chunk_id, lexeme),
        CONSTRAINT ck_chunk_terms_tf_positive CHECK (tf > 0)
    ) ON COMMIT PRESERVE ROWS
    """,
    """
    CREATE TEMP TABLE chunk_lengths (
        chunk_id bigint PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,
        dl integer NOT NULL,
        CONSTRAINT ck_chunk_lengths_positive CHECK (dl > 0)
    ) ON COMMIT PRESERVE ROWS
    """,
    """
    CREATE TEMP TABLE lexeme_stats (
        language varchar(8) NOT NULL,
        lexeme text NOT NULL,
        df integer NOT NULL,
        PRIMARY KEY (language, lexeme),
        CONSTRAINT ck_lexeme_stats_df_positive CHECK (df > 0)
    ) ON COMMIT PRESERVE ROWS
    """,
    """
    CREATE TEMP TABLE bm25_corpus_stats (
        language varchar(8) PRIMARY KEY,
        n bigint NOT NULL,
        avgdl double precision NOT NULL,
        CONSTRAINT ck_bm25_corpus_stats_language_format CHECK ({language_format_check_sql}),
        CONSTRAINT ck_bm25_corpus_stats_n_positive CHECK (n > 0),
        CONSTRAINT ck_bm25_corpus_stats_avgdl_positive CHECK (avgdl > 0)
    ) ON COMMIT PRESERVE ROWS
    """,
    "CREATE INDEX ON chunk_terms (lexeme)",
)


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
    for statement in _TEMPORARY_CORPUS_DDL:
        await connection.execute(
            text(
                statement.format(
                    dimensions=dimensions,
                    content_tsv_sql=CONTENT_TSV_SQL,
                    language_format_check_sql=LANGUAGE_FORMAT_CHECK_SQL,
                    lexical_text_check_sql=LEXICAL_TEXT_CHECK_SQL,
                )
            )
        )
    await connection.commit()


@asynccontextmanager
async def temporary_corpus_session(
    engine: AsyncEngine,
    batch: SeedBatch,
    provider: EmbeddingProvider,
    *,
    target_text_chars: int,
    embedding_provider: str,
    shared_preparation_seconds: float = 0.0,
    clock: Clock = time.perf_counter_ns,
    started_at_ns: int | None = None,
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
    target_text_chars : int
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
        await _create_temporary_corpus_tables(connection, provider.dimensions)
        session = AsyncSession(bind=connection, expire_on_commit=False)
        await persist_seed_batch(session, batch)
        # One rebuild per corpus arm. Every BM25 experiment on this chunking shares
        # it, and the next chunk target gets its own corpus and its own statistics,
        # because df, avgdl, and dl are all properties of a particular chunking.
        await backfill_term_stats(session)
        backfill = await embed_missing_chunks(session, provider)
        if backfill.embedded != len(batch.chunks) or backfill.skipped_stale:
            raise RuntimeError("temporary corpus embedding backfill was incomplete")
        await session.commit()
        target_phase_seconds = (clock() - started) / 1_000_000_000
        measurement = assess_indexing_budget(
            target_text_chars=target_text_chars,
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
        await connection.close()
