"""Table chunks rebuilt from their stored table records."""

import asyncio
from dataclasses import asdict
import json

import pytest
from sqlalchemy import delete, select

from app.contracts.figures import read_table_cells
from app.db.models import Chunk, ChunkTableCell
from app.ingestion.persistence import persist_seed_batch
from app.retrieval.tables import load_cell_catalog, load_chunk_tables, load_table_readings
from tests.ingestion.seed.support import table_batch, tagged_table_batch
from tests.live_postgres import isolated_session


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
            assert stored[chunk_id].readings == tuple(read_table_cells(expected))
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
