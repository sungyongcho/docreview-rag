"""Moving stored table fragments onto table records before dropping the JSON."""

import asyncio
from dataclasses import asdict
import json

import pytest
from sqlalchemy import select, text

from app.contracts.figures import read_table_cells
from app.db.models import Chunk, SnapshotChunkTableCell, SnapshotTableSourceCell
from app.ingestion.persistence import persist_seed_batch
from scripts.schema.tables import migrate_tables, snapshot_rows
from tests.ingestion.seed.support import table_batch
from tests.live_postgres import isolated_session


def stored_fragment() -> dict:
    """Return the table chunk fragment of the sample table batch as stored JSON."""
    (chunk,) = [chunk for chunk in table_batch().chunks if chunk.table_fragment is not None]
    assert chunk.table_fragment is not None
    return asdict(chunk.table_fragment)


def test_a_snapshot_fragment_becomes_one_frozen_table_with_the_same_readings():
    """Freeze one snapshot chunk's cells, links and readings from its stored fragment."""
    fragment = stored_fragment()
    rows = snapshot_rows(3, "NVDA-FY2024", 11, 0, 100, fragment)
    readings = {
        (row["grid_row"], row["grid_column"]): row["reading_item"]
        for row in rows[SnapshotTableSourceCell]
        if row["reading_values"] is not None
    }
    assert readings == {(cell.row, cell.column): cell.item for cell in read_table_cells(fragment)}
    assert [row["ordinal"] for row in rows[SnapshotChunkTableCell]] == list(
        range(len(fragment["cells"]))
    )


@pytest.mark.live_postgres
def test_fragments_are_dropped_only_after_every_one_is_rebuilt_exactly():
    """Report a fragment that differs, then drop the column once all are rebuilt."""

    async def exercise() -> None:
        """Restore the legacy column, store a table, and migrate twice."""
        async with isolated_session() as session:
            await persist_seed_batch(session, table_batch())
            for table in ("chunks", "snapshot_chunks"):
                await session.execute(text(f"ALTER TABLE {table} ADD COLUMN table_fragment JSONB"))
            chunk_id = await session.scalar(select(Chunk.id).where(Chunk.kind == "table"))
            fragment = stored_fragment()
            changed = {**fragment, "header_rows": [99]}
            await session.execute(
                text("UPDATE chunks SET table_fragment = CAST(:value AS jsonb) WHERE id = :id"),
                {"value": json.dumps(changed), "id": chunk_id},
            )
            report = await migrate_tables(session, drop=True)
            assert report["status"] == "mismatched" and report["live_mismatches"] == [chunk_id]
            await session.execute(
                text("UPDATE chunks SET table_fragment = CAST(:value AS jsonb) WHERE id = :id"),
                {"value": json.dumps(fragment), "id": chunk_id},
            )
            report = await migrate_tables(session, drop=True)
            assert report["status"] == "migrated" and report["dropped"] is True
            assert await migrate_tables(session, drop=True) == {
                "status": "migrated",
                "dropped": True,
            }

    asyncio.run(exercise())
