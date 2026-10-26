"""PostgreSQL persistence behavior across seed reruns and source changes."""

import asyncio
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import insert, select, text

from app.config import EMBEDDING_DIMENSIONS
from app.db.models import (
    Chunk,
    ChunkEmbedding,
    ChunkTableCell,
    Document,
    FilingFactContext,
    FilingPeriodTerm,
    TableCell,
    TableSourceCell,
    TableSourceFact,
)
from app.ingestion.parsing.facts import FilingFacts, PeriodTerm
from app.ingestion.persistence import persist_seed_batch
from app.ingestion.pipeline import SeedBatch
from tests.ingestion.seed.support import sample_batch, table_batch, tagged_table_batch
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


@pytest.mark.live_postgres
def test_postgresql_stores_each_table_once_and_links_its_chunks():
    """Store a table's cells and interpretation, link its chunk, and replace it on rerun."""

    async def exercise() -> None:
        """Persist the table batch twice and read the stored table back."""
        async with isolated_session_factory() as factory:
            batch = table_batch()
            async with factory() as session:
                await persist_seed_batch(session, batch)
                chunk_id = await session.scalar(select(Chunk.id).where(Chunk.kind == "table"))
                assert await session.scalar(text("SELECT count(*) FROM parsed_tables")) == 1
                known = await session.execute(
                    select(TableCell.text, TableCell.value).where(TableCell.status == "known")
                )
                cells = {text_: value for text_, value in known}
                assert cells == {
                    "$ 25,785": Decimal(25785),
                    "$ 22,680": Decimal(22680),
                    "(1,641)": Decimal(-1641),
                }
                assert await session.scalar(
                    select(TableCell.status).where(TableCell.text == "—")
                ) == ("blank")
                linked = (
                    (await session.execute(select(ChunkTableCell.chunk_id).distinct()))
                    .scalars()
                    .all()
                )
                assert linked == [chunk_id]
                currency = await session.scalar(
                    select(TableSourceCell.reading_currency).where(
                        TableSourceCell.reading_item == "revenue",
                        TableSourceCell.reading_years == [2024],
                    )
                )
                assert currency == "USD"

            async with factory() as session:
                await persist_seed_batch(session, batch)
                assert await session.scalar(select(Chunk.id).where(Chunk.kind == "table")) == (
                    chunk_id
                )
                assert await session.scalar(text("SELECT count(*) FROM parsed_tables")) == 1
                fragment = batch.chunks[0].table_fragment
                assert fragment is not None
                assert await session.scalar(text("SELECT count(*) FROM chunk_table_cells")) == (
                    len(fragment.cells)
                )

            async with factory() as session:
                await persist_seed_batch(session, sample_batch())
                assert await session.scalar(text("SELECT count(*) FROM parsed_tables")) == 0
                assert await session.scalar(text("SELECT count(*) FROM table_cells")) == 0

    asyncio.run(exercise())


@pytest.mark.live_postgres
def test_postgresql_stores_fact_contexts_units_and_each_cells_facts():
    """Store the parse's contexts and units and tie each tagged number to its source cell."""

    async def exercise() -> None:
        """Persist the tagged table batch and read its facts back."""
        async with isolated_session_factory() as factory:
            batch = tagged_table_batch()
            async with factory() as session:
                await persist_seed_batch(session, batch)
                contexts = {
                    context_id: (fiscal_year, dimensions)
                    for context_id, fiscal_year, dimensions in await session.execute(
                        select(
                            FilingFactContext.context_id,
                            FilingFactContext.fiscal_year,
                            FilingFactContext.dimensions,
                        )
                    )
                }
                assert contexts == {
                    "fy24": (2024, []),
                    "fy23": (2023, []),
                    "dc24": (2024, ["us-gaap:StatementBusinessSegmentsAxis=nvda:DataCenterMember"]),
                }
                assert await session.scalar(text("SELECT count(*) FROM filing_fact_units")) == 2
                facts = (
                    await session.execute(
                        select(
                            TableSourceFact.grid_row,
                            TableSourceFact.grid_column,
                            TableSourceFact.context_id,
                            TableSourceFact.unit_id,
                            TableSourceFact.scale,
                        ).order_by(TableSourceFact.grid_row, TableSourceFact.grid_column)
                    )
                ).all()
                assert [tuple(row) for row in facts] == [
                    (1, 1, "fy24", "usd", 6),
                    (1, 2, "fy23", "usd", 6),
                    (2, 1, "fy24", "usdPerShare", 0),
                    (2, 2, "fy23", "usdPerShare", 0),
                    (3, 1, "dc24", "usd", 6),
                ]

            async with factory() as session:
                await persist_seed_batch(session, batch)
                assert await session.scalar(text("SELECT count(*) FROM table_source_facts")) == 5
                assert await session.scalar(text("SELECT count(*) FROM filing_fact_contexts")) == 3

    asyncio.run(exercise())


@pytest.mark.live_postgres
def test_postgresql_stores_the_period_words_a_report_defines():
    """Store each defined period word with its year, dates and declaration span."""

    async def exercise() -> None:
        """Persist a table batch whose filing defines 당기 and read the term back."""
        term = PeriodTerm("당기", 2024, date(2024, 1, 1), date(2024, 12, 31), 3, 40)
        async with isolated_session_factory() as factory, factory() as session:
            await persist_seed_batch(
                session, table_batch(facts=FilingFacts("dart", period_terms=(term,)))
            )
            stored = (await session.execute(select(FilingPeriodTerm))).scalars().all()
            assert [
                (row.term, row.fiscal_year, row.period_start, row.period_end, row.start_char)
                for row in stored
            ] == [("당기", 2024, date(2024, 1, 1), date(2024, 12, 31), 3)]

    asyncio.run(exercise())
