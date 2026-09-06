"""Optional PostgreSQL integration tests for idempotent seed reruns."""

import asyncio
from dataclasses import replace

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import get_settings
import app.ingestion.seed as seed
from tests.ingestion.seed.support import sample_batch
from tests.live_postgres import live_postgres_unavailable


async def _database_is_reachable(database_url: str) -> tuple[bool, str]:
    """Exercise database is reachable behavior."""
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with asyncio.timeout(3):
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        return True, ""
    except Exception as exc:
        return False, str(exc)
    finally:
        await engine.dispose()


async def _exercise_rerun(module) -> None:
    """Exercise exercise rerun behavior."""
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            await connection.execute(
                text(
                    """
                    CREATE TEMP TABLE documents (
                        doc_id text PRIMARY KEY,
                        registry text NOT NULL,
                        language text NOT NULL,
                        issuer text NOT NULL,
                        issuer_id text NOT NULL,
                        fiscal_year integer NOT NULL,
                        form text NOT NULL,
                        filing_date text NOT NULL,
                        report_period text NOT NULL,
                        filing_id text NOT NULL,
                        source_url text NOT NULL,
                        parse_status text NOT NULL,
                        item_index jsonb NOT NULL,
                        source_length bigint NOT NULL,
                        source_sha256 text NOT NULL
                    )
                    """
                )
            )
            await connection.execute(
                text(
                    """
                    CREATE TEMP TABLE chunks (
                        id bigserial PRIMARY KEY,
                        doc_id text NOT NULL REFERENCES documents(doc_id),
                        language text NOT NULL,
                        item text,
                        kind text NOT NULL,
                        ordinal integer NOT NULL,
                        body text NOT NULL,
                        context_header text NOT NULL,
                        index_text text NOT NULL,
                        start_char bigint NOT NULL,
                        end_char bigint NOT NULL,
                        source_sha256 text NOT NULL,
                        citation text NOT NULL,
                        lexical_text text,
                        embedding text,
                        embedding_provider text,
                        embedding_model text,
                        embedding_dimensions integer,
                        UNIQUE (doc_id, ordinal)
                    )
                    """
                )
            )
            await connection.commit()

            batch = sample_batch()
            async with AsyncSession(bind=connection, expire_on_commit=False) as session:
                first = await module.persist_seed_batch(session, batch)
                assert first.documents == 1
                assert first.chunks == 2
            await connection.execute(
                text("UPDATE chunks SET embedding = 'existing-vector' WHERE ordinal = 0")
            )
            await connection.commit()

            async with AsyncSession(bind=connection, expire_on_commit=False) as session:
                second = await module.persist_seed_batch(session, batch)
                assert second == first
            preserved = await connection.scalar(
                text("SELECT embedding FROM chunks WHERE ordinal = 0")
            )
            assert preserved == "existing-vector"
            persisted_status = await connection.scalar(
                text("SELECT item_index->0->>'status' FROM documents")
            )
            assert persisted_status == "empty_disclosure"

            document_count = await connection.scalar(text("SELECT count(*) FROM documents"))
            chunk_count = await connection.scalar(text("SELECT count(*) FROM chunks"))
            table_count = await connection.scalar(
                text("SELECT count(*) FROM chunks WHERE kind = 'table'")
            )
            assert document_count == 1
            assert chunk_count == 2
            assert table_count == 1

            changed_chunk = replace(
                batch.chunks[0],
                body="Changed source-derived narrative.",
                index_text="NVDA-FY2024 context\n\nChanged source-derived narrative.",
            )
            changed_batch = module.SeedBatch(batch.documents, (changed_chunk, batch.chunks[1]))
            async with AsyncSession(bind=connection, expire_on_commit=False) as session:
                await module.persist_seed_batch(session, changed_batch)
            invalidated = await connection.scalar(
                text("SELECT embedding FROM chunks WHERE ordinal = 0")
            )
            assert invalidated is None

            shorter_batch = module.SeedBatch(batch.documents, (changed_chunk,))
            async with AsyncSession(bind=connection, expire_on_commit=False) as session:
                await module.persist_seed_batch(session, shorter_batch)
            shortened_count = await connection.scalar(text("SELECT count(*) FROM chunks"))
            assert shortened_count == 1
    finally:
        await engine.dispose()


@pytest.mark.live_postgres
def test_postgresql_rerun_keeps_row_counts_stable():
    """Preserve rows and embeddings across idempotent PostgreSQL reruns."""
    reachable, detail = asyncio.run(_database_is_reachable(get_settings().database_url))
    if not reachable:
        live_postgres_unavailable(detail)
    asyncio.run(_exercise_rerun(seed))
