"""Table chunks rebuilt from their stored table records."""

import asyncio
from dataclasses import asdict
from decimal import Decimal
import json

import pytest
from sqlalchemy import delete, select, update

from app.db.models import Chunk, ChunkTableCell, ParsedTable
from app.figures.answers import EvidenceText
from app.figures.tables import TableCellReading
from app.ingestion.persistence import persist_seed_batch
from app.ingestion.table_records import resolver_identity
from app.retrieval.tables import (
    figure_evidence,
    load_cell_catalog,
    load_chunk_tables,
    load_table_readings,
)
from tests.ingestion.seed.support import table_batch, tagged_table_batch
from tests.live_postgres import isolated_session

MILLION = Decimal(1_000_000)
NET_INCOME = "Net income (loss)"


@pytest.mark.live_postgres
def test_a_stored_table_rebuilds_its_chunk_fragment_and_readings_exactly():
    """Rebuild the fragment JSON the chunker made and the readings a check would read."""

    async def exercise() -> None:
        """Store one table chunk and read it back."""
        batch = table_batch()
        (record,) = [chunk for chunk in batch.chunks if chunk.table_fragment is not None]
        assert record.table_fragment is not None
        expected = json.loads(json.dumps(asdict(record.table_fragment)))
        async with isolated_session() as session:
            await persist_seed_batch(session, batch)
            chunk_id = await session.scalar(select(Chunk.id).where(Chunk.kind == "table"))
            text_id = await session.scalar(select(Chunk.id).where(Chunk.kind == "text"))
            assert chunk_id is not None
            stored = await load_chunk_tables(session, [chunk_id, *([text_id] if text_id else [])])
            assert set(stored) == {chunk_id}
            assert stored[chunk_id].fragment == expected
            assert [
                (
                    reading.row,
                    reading.column,
                    reading.values,
                    reading.years,
                    reading.scale,
                    reading.item,
                    reading.currency,
                    reading.row_label,
                    reading.basis,
                )
                for reading in stored[chunk_id].readings
            ] == [
                (1, 1, {Decimal(25785)}, {2024}, MILLION, "revenue", "USD", "Net revenue", "text"),
                (1, 2, {Decimal(22680)}, {2023}, MILLION, "revenue", "USD", "Net revenue", "text"),
                (2, 1, {Decimal(1641)}, {2024}, MILLION, "net income", "USD", NET_INCOME, "text"),
            ]
            assert await load_table_readings(session, []) == {}

    asyncio.run(exercise())


@pytest.mark.live_postgres
def test_the_cell_catalog_lists_stored_cells_and_says_why_a_chunk_has_none():
    """List figure cells with their facts; name running text and missing tables apart."""

    async def exercise() -> None:
        """Store the table batch, then read each kind of chunk's catalog."""
        async with isolated_session() as session:
            await persist_seed_batch(session, table_batch())
            chunk_id = await session.scalar(select(Chunk.id).where(Chunk.kind == "table"))
            assert chunk_id is not None
            catalog = await load_cell_catalog(session, chunk_id)
            assert catalog["status"] == "available"
            cells = {cell["raw_text"]: cell for cell in catalog["cells"]}
            assert set(cells) == {"$ 25,785", "$ 22,680", "(1,641)"}
            revenue = cells["$ 25,785"]
            assert revenue["ref"].startswith(f"{chunk_id}:r")
            assert (revenue["item"], revenue["fiscal_years"], revenue["currency"]) == (
                "revenue",
                [2024],
                "USD",
            )
            assert (revenue["status"], revenue["complete"], revenue["scale"]) == (
                "known",
                True,
                "1000000",
            )
            assert await load_cell_catalog(session, 999_999) == {"status": "not_table"}
            await session.execute(delete(ChunkTableCell))
            assert await load_cell_catalog(session, chunk_id) == {"status": "unavailable"}

    asyncio.run(exercise())


@pytest.mark.live_postgres
def test_stored_fact_readings_come_back_as_they_were_read():
    """Rebuild each tagged cell's basis, overrides, scope and measure from its stored row."""

    async def exercise() -> None:
        """Store the tagged table and compare its stored readings with the built ones."""
        async with isolated_session() as session:
            batch = tagged_table_batch()
            await persist_seed_batch(session, batch)
            chunk_id = await session.scalar(select(Chunk.id).where(Chunk.kind == "table"))
            assert chunk_id is not None
            readings = (await load_table_readings(session, [chunk_id]))[chunk_id]
            tagged = {(cell.row, cell.column): cell for cell in readings if cell.basis == "fact"}
            assert tagged[(2, 1)].overrides == ("scale",)
            assert tagged[(2, 1)].measure == "per_share"
            assert tagged[(3, 1)].scope == (
                "us-gaap:StatementBusinessSegmentsAxis=nvda:DataCenterMember"
            )
            catalog = await load_cell_catalog(session, chunk_id)
            cells = catalog["cells"]
            assert isinstance(cells, list)
            statuses = {cell["ref"]: cell["status"] for cell in cells}
            assert statuses[f"{chunk_id}:r3c1"] == "scope_qualified"

    asyncio.run(exercise())


@pytest.mark.live_postgres
def test_tables_load_for_more_chunk_ids_than_one_statement_can_bind():
    """Load a stored table among 40,000 requested ids, from the live index and a snapshot."""

    async def exercise() -> None:
        """Store one table chunk and request it with ids past asyncpg's 32,767 limit."""
        async with isolated_session() as session:
            await persist_seed_batch(session, table_batch())
            chunk_id = await session.scalar(select(Chunk.id).where(Chunk.kind == "table"))
            assert chunk_id is not None
            ids = [chunk_id, *range(10_000_000, 10_040_000)]
            assert set(await load_chunk_tables(session, ids)) == {chunk_id}
            assert await load_chunk_tables(session, ids, snapshot_id=1) == {}

    asyncio.run(exercise())


@pytest.mark.live_postgres
@pytest.mark.parametrize("identity", ["resolver_identity", "builder_identity"])
def test_a_table_from_other_code_has_no_catalog_and_no_usable_readings(identity):
    """Serve catalog and readings while both stored identities are the running ones."""

    async def exercise() -> None:
        """Store the table, then mark it as built or read by older code."""
        async with isolated_session() as session:
            await persist_seed_batch(session, table_batch())
            chunk_id = await session.scalar(select(Chunk.id).where(Chunk.kind == "table"))
            assert chunk_id is not None
            catalog = await load_cell_catalog(session, chunk_id)
            assert catalog["status"] == "available"
            assert catalog["resolver_identity"] == resolver_identity()
            current = (await load_table_readings(session, [chunk_id]))[chunk_id]
            assert {reading.item for reading in current} == {"revenue", "net income"}
            await session.execute(update(ParsedTable).values({identity: "0" * 64}))
            assert await load_cell_catalog(session, chunk_id) == {"status": "unavailable"}
            assert set(await load_chunk_tables(session, [chunk_id])) == {chunk_id}
            assert await load_chunk_tables(session, [chunk_id], current_only=True) == {}
            assert await load_table_readings(session, [chunk_id]) == {}

    asyncio.run(exercise())


def test_figure_evidence_gives_no_body_or_cells_for_a_table_without_usable_readings():
    """Give prose its body and a table its readings, and a table without readings nothing."""
    reading = TableCellReading(1, 1, frozenset({Decimal(5)}), frozenset({2024}), None, None, None)
    assert figure_evidence(1, "text", "Revenue grew 14%.", "h", {}) == EvidenceText(
        1, "Revenue grew 14%.", "h", None
    )
    assert figure_evidence(2, "table", "| a | 5 |", "h", {2: (reading,)}) == EvidenceText(
        2, "| a | 5 |", "h", (reading,)
    )
    assert figure_evidence(3, "table", "Revenue grew 14%.", "h", {2: (reading,)}) == (
        EvidenceText(3, "", "h", ())
    )
