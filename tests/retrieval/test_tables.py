"""Table chunks rebuilt from their stored table records."""

import asyncio
from dataclasses import asdict
import json

import pytest
from sqlalchemy import select

from app.contracts.figures import read_table_cells
from app.db.models import Chunk
from app.ingestion.persistence import persist_seed_batch
from app.retrieval.tables import load_chunk_tables, load_table_readings
from tests.ingestion.seed.support import table_batch
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
