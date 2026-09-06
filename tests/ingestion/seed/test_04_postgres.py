"""Optional PostgreSQL integration tests for idempotent seed reruns."""

import asyncio
from dataclasses import replace

import pytest
from sqlalchemy import insert, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool
from sqlalchemy.schema import CreateTable

from app.config import get_settings
from app.db.bootstrap import ensure_vector_extension
from app.db.models import DIM, Base, Chunk, ChunkEmbedding
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
            await ensure_vector_extension(connection)
            for table in Base.metadata.sorted_tables:
                ddl = str(CreateTable(table).compile(dialect=postgresql.dialect()))
                await connection.execute(text(ddl.replace("CREATE TABLE", "CREATE TEMP TABLE", 1)))
            await connection.commit()

            batch = sample_batch()
            async with AsyncSession(bind=connection, expire_on_commit=False) as session:
                first = await module.persist_seed_batch(session, batch)
                assert first.documents == 1
                assert first.chunks == 2
            original = (
                await connection.execute(
                    select(Chunk.id, Chunk.index_text_sha256).where(Chunk.ordinal == 0)
                )
            ).one()
            await connection.execute(
                insert(ChunkEmbedding).values(
                    chunk_id=original.id,
                    input_sha256=original.index_text_sha256,
                    provider="deterministic",
                    model="test-model",
                    dimensions=DIM,
                    tokenizer="test-tokenizer",
                    embedding=[1.0] + [0.0] * (DIM - 1),
                )
            )
            await connection.commit()

            async with AsyncSession(bind=connection, expire_on_commit=False) as session:
                second = await module.persist_seed_batch(session, batch)
                assert second == first
            preserved = await connection.scalar(
                select(ChunkEmbedding.embedding)
                .join(Chunk, Chunk.id == ChunkEmbedding.chunk_id)
                .where(Chunk.ordinal == 0)
            )
            assert list(preserved) == [1.0] + [0.0] * (DIM - 1)
            original_id = await connection.scalar(select(Chunk.id).where(Chunk.ordinal == 0))
            reordered = module.SeedBatch(
                batch.documents,
                (replace(batch.chunks[1], ordinal=0), replace(batch.chunks[0], ordinal=1)),
                batch.filings,
            )
            async with AsyncSession(bind=connection, expire_on_commit=False) as session:
                await module.persist_seed_batch(session, reordered)
            assert (
                await connection.scalar(select(Chunk.id).where(Chunk.ordinal == 1)) == original_id
            )
            reordered_vector = await connection.scalar(
                select(ChunkEmbedding.embedding)
                .join(Chunk, Chunk.id == ChunkEmbedding.chunk_id)
                .where(Chunk.ordinal == 1)
            )
            assert list(reordered_vector) == list(preserved)
            async with AsyncSession(bind=connection, expire_on_commit=False) as session:
                await module.persist_seed_batch(session, batch)
            assert await connection.scalar(text("SELECT count(*) FROM source_artifacts")) == 1
            assert await connection.scalar(text("SELECT count(*) FROM parsed_structures")) == 1
            persisted_status = await connection.scalar(
                text(
                    "SELECT p.item_index->0->>'status' FROM document_parses d "
                    "JOIN parsed_structures p ON p.structure_id = d.structure_id"
                )
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
            changed_batch = module.SeedBatch(
                batch.documents, (changed_chunk, batch.chunks[1]), batch.filings
            )
            async with AsyncSession(bind=connection, expire_on_commit=False) as session:
                await module.persist_seed_batch(session, changed_batch)
            invalidated = await connection.scalar(
                select(ChunkEmbedding.embedding)
                .join(Chunk, Chunk.id == ChunkEmbedding.chunk_id)
                .where(Chunk.ordinal == 0)
            )
            assert invalidated is None

            shorter_batch = module.SeedBatch(batch.documents, (changed_chunk,), batch.filings)
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
