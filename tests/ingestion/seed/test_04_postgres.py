"""PostgreSQL persistence behavior across seed reruns and source changes."""

import asyncio
from dataclasses import replace
from datetime import date

import pytest
from sqlalchemy import insert, select, text

from app.config import EMBEDDING_DIMENSIONS
from app.db.models import Chunk, ChunkEmbedding, Document
from app.ingestion.persistence import persist_seed_batch
from app.ingestion.pipeline import SeedBatch
from tests.ingestion.seed.support import sample_batch
from tests.live_postgres import isolated_session_factory


@pytest.mark.live_postgres
def test_postgresql_rerun_preserves_identity_and_replaces_changed_evidence():
    """Keep stable evidence and vectors, update metadata, and discard stale evidence."""

    async def exercise() -> None:
        """Commit each seed operation separately and inspect its stored outcome."""
        async with isolated_session_factory() as factory:
            batch = sample_batch()
            vector = [1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 1)
            async with factory() as session:
                first = await persist_seed_batch(session, batch)
                assert (first.documents, first.chunks) == (1, 2)
                original = (
                    await session.execute(
                        select(Chunk.id, Chunk.index_text_sha256).where(Chunk.ordinal == 0)
                    )
                ).one()
                await session.execute(
                    insert(ChunkEmbedding).values(
                        chunk_id=original.id,
                        input_sha256=original.index_text_sha256,
                        provider="deterministic",
                        model="test-model",
                        dimensions=EMBEDDING_DIMENSIONS,
                        tokenizer="test-tokenizer",
                        embedding=vector,
                    )
                )
                await session.commit()

            async with factory() as session:
                assert await persist_seed_batch(session, batch) == first
                stored = await session.scalar(
                    select(ChunkEmbedding.embedding).where(ChunkEmbedding.chunk_id == original.id)
                )
                assert stored is not None
                assert list(stored) == vector
                assert await session.scalar(text("SELECT count(*) FROM documents")) == 1
                assert await session.scalar(text("SELECT count(*) FROM chunks")) == 2
                assert await session.scalar(text("SELECT count(*) FROM source_artifacts")) == 1
                assert await session.scalar(text("SELECT count(*) FROM parsed_structures")) == 1
                assert (
                    await session.scalar(text("SELECT count(*) FROM chunks WHERE kind = 'table'"))
                    == 1
                )
                assert (
                    await session.scalar(
                        text(
                            "SELECT p.item_index->0->>'status' FROM document_parses d "
                            "JOIN parsed_structures p ON p.structure_id = d.structure_id"
                        )
                    )
                    == "empty_disclosure"
                )

            reordered = replace(
                batch,
                chunks=(replace(batch.chunks[1], ordinal=0), replace(batch.chunks[0], ordinal=1)),
            )
            async with factory() as session:
                await persist_seed_batch(session, reordered)
                assert (
                    await session.scalar(select(Chunk.id).where(Chunk.ordinal == 1)) == original.id
                )
                stored = await session.scalar(
                    select(ChunkEmbedding.embedding).where(ChunkEmbedding.chunk_id == original.id)
                )
                assert stored is not None
                assert list(stored) == vector

            filing = batch.filings[0]
            document = filing.source.document
            assert document.sec is not None
            updated_source = replace(
                filing.source,
                document=document.model_copy(
                    update={
                        "aliases": ("NVIDIA Corporation",),
                        "report_period": date(2024, 1, 29),
                        "sec": document.sec.model_copy(update={"primary_document": "amended.html"}),
                    }
                ),
            )
            updated_filing = replace(filing, source=updated_source)
            changed_chunk = replace(
                batch.chunks[0],
                body="Changed source-derived narrative.",
                context_header="Updated NVIDIA context",
                start_char=12,
                end_char=48,
            )
            changed_batch = SeedBatch(
                (updated_filing.source.document,),
                (changed_chunk, batch.chunks[1]),
                (updated_filing,),
            )
            async with factory() as session:
                await persist_seed_batch(session, changed_batch)
                saved_document = await session.scalar(select(Document))
                assert saved_document is not None
                assert saved_document.aliases == ["NVIDIA Corporation"]
                assert saved_document.report_period == "2024-01-29"
                assert saved_document.sec is not None
                assert saved_document.sec["primary_document"] == "amended.html"
                saved_chunk = await session.scalar(select(Chunk).where(Chunk.ordinal == 0))
                assert saved_chunk is not None
                assert saved_chunk.id != original.id
                assert saved_chunk.body == "Changed source-derived narrative."
                assert saved_chunk.context_header == "Updated NVIDIA context"
                assert saved_chunk.index_text == (
                    "Updated NVIDIA context\n\nChanged source-derived narrative."
                )
                assert (saved_chunk.start_char, saved_chunk.end_char) == (12, 48)
                assert await session.scalar(text("SELECT count(*) FROM chunk_embeddings")) == 0
                assert await session.get(Chunk, original.id) is None

            async with factory() as session:
                await persist_seed_batch(session, replace(changed_batch, chunks=(changed_chunk,)))
                assert await session.scalar(text("SELECT count(*) FROM chunks")) == 1
                assert await session.scalar(select(Chunk.kind)) == "text"

    asyncio.run(exercise())
