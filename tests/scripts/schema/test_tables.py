"""Moving stored table fragments onto table records before dropping the JSON."""

import asyncio
from dataclasses import asdict
from decimal import Decimal
import json

import pytest
from sqlalchemy import select, text

from app.db.models import Chunk, SnapshotChunkTableCell, SnapshotTableSourceCell
from app.ingestion.persistence import persist_seed_batch
from app.retrieval.tables import load_table_readings
from scripts.schema.tables import comparable, migrate_tables, snapshot_rows
from tests.ingestion.seed.support import table_batch, tagged_table_batch
from tests.live_postgres import isolated_session


def stored_fragment() -> dict:
    """Return the table chunk fragment of the sample table batch as stored JSON."""
    (chunk,) = [chunk for chunk in table_batch().chunks if chunk.table_fragment is not None]
    assert chunk.table_fragment is not None
    return json.loads(json.dumps(asdict(chunk.table_fragment)))


def spanless_fragment() -> dict:
    """Return the stored fragment in its shape from before cell spans were recorded."""
    fragment = stored_fragment()
    for cell in [
        *(source for member in fragment["cells"] for source in member["sources"]),
        *fragment["header_cells"],
    ]:
        del cell["start_char"], cell["end_char"]
    return fragment


def test_a_snapshot_fragment_becomes_one_frozen_table_with_the_same_readings():
    """Freeze one snapshot chunk's cells, links and readings from its stored fragment."""
    fragment = stored_fragment()
    rows = snapshot_rows(3, "NVDA-FY2024", 11, 0, 100, fragment)
    readings = {
        (row["grid_row"], row["grid_column"]): (
            row["reading_item"],
            row["reading_years"],
            row["reading_values"],
            row["reading_currency"],
        )
        for row in rows[SnapshotTableSourceCell]
        if row["reading_values"] is not None
    }
    assert readings == {
        (1, 1): ("revenue", [2024], [Decimal("25785")], "USD"),
        (1, 2): ("revenue", [2023], [Decimal("22680")], "USD"),
        (2, 1): ("net income", [2024], [Decimal("1641")], "USD"),
    }
    assert [row["ordinal"] for row in rows[SnapshotChunkTableCell]] == list(range(6))


def test_a_fragment_stored_before_cell_spans_freezes_with_no_spans():
    """Freeze a fragment whose cells lack span keys, as cells with no span."""
    rows = snapshot_rows(3, "NVDA-FY2024", 11, 0, 100, spanless_fragment())
    cells = rows[SnapshotTableSourceCell]
    assert len(cells) == 9
    assert {(row["start_char"], row["end_char"]) for row in cells} == {(None, None)}


def test_absent_and_null_spans_compare_equal_and_known_spans_do_not():
    """Treat a missing span as a null one, but keep real spans and text differences."""
    assert comparable(spanless_fragment()) == comparable(stored_fragment())
    (tagged,) = [chunk for chunk in tagged_table_batch().chunks if chunk.table_fragment]
    assert tagged.table_fragment is not None
    spanned_json = json.loads(json.dumps(asdict(tagged.table_fragment)))
    assert comparable(spanned_json) == spanned_json
    spanned = stored_fragment()
    spanned["header_cells"][0] |= {"start_char": 5, "end_char": 9}
    assert comparable(spanned) != comparable(spanless_fragment())
    changed = spanless_fragment()
    changed["cells"][1]["sources"][0]["text"] = "$ 25,786"
    assert comparable(changed) != comparable(stored_fragment())


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


@pytest.mark.live_postgres
def test_snapshots_stored_before_and_after_cell_spans_both_rebuild_exactly():
    """Freeze and drop snapshot fragments of both shapes once each one is rebuilt."""

    async def exercise() -> None:
        """Snapshot the stored table chunk twice, once without its cells' span keys."""
        async with isolated_session() as session:
            await persist_seed_batch(session, table_batch())
            for table in ("chunks", "snapshot_chunks"):
                await session.execute(text(f"ALTER TABLE {table} ADD COLUMN table_fragment JSONB"))
            await session.execute(
                text(
                    "UPDATE chunks SET table_fragment = CAST(:value AS jsonb) WHERE kind = 'table'"
                ),
                {"value": json.dumps(stored_fragment())},
            )
            for snapshot_id, fragment in ((1, spanless_fragment()), (2, stored_fragment())):
                result = await session.scalar(
                    text(
                        "INSERT INTO eval_results (suite, config, metrics, raw_artifact_path) "
                        "VALUES ('snapshot-test', '{}', '{}', 'artifact.json') RETURNING id"
                    )
                )
                await session.execute(
                    text(
                        "INSERT INTO evaluation_snapshots "
                        "(id, label, status, public, corpus_fingerprint, profile, eval_result_id) "
                        "VALUES (:id, :label, 'ready', false, :fingerprint, '{}', :result)"
                    ),
                    {
                        "id": snapshot_id,
                        "label": f"snapshot-{snapshot_id}",
                        "fingerprint": "f" * 64,
                        "result": result,
                    },
                )
                await session.execute(
                    text(
                        "INSERT INTO snapshot_chunks (snapshot_id, chunk_id, stable_key, "
                        "index_text_sha256, doc_id, registry, language, issuer, fiscal_year, "
                        "form, item, kind, ordinal, body, context_header, index_text, "
                        "start_char, end_char, source_sha256, citation, table_fragment) "
                        "SELECT :snapshot, c.id, c.stable_key, c.index_text_sha256, c.doc_id, "
                        "d.registry, c.language, d.issuer, d.fiscal_year, d.form, c.item, "
                        "c.kind, c.ordinal, c.body, c.context_header, c.index_text, "
                        "c.start_char, c.end_char, c.source_sha256, c.citation, "
                        "CAST(:fragment AS jsonb) FROM chunks c "
                        "JOIN documents d ON d.doc_id = c.doc_id WHERE c.kind = 'table'"
                    ),
                    {"snapshot": snapshot_id, "fragment": json.dumps(fragment)},
                )
            report = await migrate_tables(session, drop=True)
            assert report["snapshots"] == {
                "1": {"chunks": 1, "frozen_now": True, "mismatches": []},
                "2": {"chunks": 1, "frozen_now": True, "mismatches": []},
            }
            assert (report["status"], report["live_mismatches"]) == ("migrated", [])
            chunk_id = await session.scalar(select(Chunk.id).where(Chunk.kind == "table"))
            assert chunk_id is not None
            frozen = await load_table_readings(session, [chunk_id], snapshot_id=1)
            assert {reading.item for reading in frozen[chunk_id]} == {"revenue", "net income"}

    asyncio.run(exercise())
