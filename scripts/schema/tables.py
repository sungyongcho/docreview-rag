"""Move stored table fragments onto the canonical table records, then drop the JSON.

Chunks of the live index get their table records by being ingested again; this
module only checks that every stored fragment is rebuilt exactly from them.
Evaluation snapshots cannot be ingested again, so each snapshot table chunk gets its
own frozen table built from its stored fragment with the current resolver. Only when
every live and snapshot fragment is rebuilt exactly, and dropping was asked for, are
the ``table_fragment`` columns removed.
"""

from collections.abc import Mapping, Sequence
import hashlib
import json
from typing import Any

from sqlalchemy import insert, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.contracts.figures import interpret_table_cell, read_table_cells, read_table_unit
from app.db.bootstrap import bootstrap_schema
from app.db.models import (
    SnapshotChunkTableCell,
    SnapshotChunkTableHeader,
    SnapshotParsedTable,
    SnapshotTableCaption,
    SnapshotTableCell,
    SnapshotTableCellSource,
    SnapshotTableSourceCell,
)
from app.ingestion.persistence import reading_columns
from app.ingestion.table_records import resolver_identity
from app.retrieval.tables import load_table_fragments

# Marks frozen tables rebuilt from a stored fragment rather than by the table builder.
FRAGMENT_BUILDER = "fragment"
FRAGMENT_COLUMNS = (("chunks", "id"), ("snapshot_chunks", "chunk_id"))


def _fragment_table_id(doc_id: str, chunk_id: int) -> str:
    """Identify the frozen table rebuilt from one snapshot chunk's fragment."""
    payload = json.dumps([FRAGMENT_BUILDER, doc_id, chunk_id], separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def _cell_text(sources: Sequence[Mapping[str, Any]]) -> str:
    """Rejoin a normalized cell's text from its source cells, as unit merging writes it."""
    return " ".join(
        str(source["text"]).strip() for source in sources if str(source["text"]).strip()
    )


def snapshot_rows(
    snapshot_id: int, doc_id: str, chunk_id: int, start: int, end: int, fragment: dict[str, Any]
) -> dict[type, list[dict[str, Any]]]:
    """Build the frozen table rows of one snapshot chunk from its stored fragment."""
    table_id = _fragment_table_id(doc_id, chunk_id)
    readings = {(cell.row, cell.column): cell for cell in read_table_cells(fragment)}
    unit = read_table_unit(fragment)
    grid: dict[tuple[int, int], dict[str, Any]] = {}
    for cell in fragment["header_cells"]:
        grid[(cell["row"], cell["column"])] = cell
    for member in fragment["cells"]:
        for source in member["sources"]:
            grid.setdefault((source["row"], source["column"]), source)
    base = {"snapshot_id": snapshot_id, "table_id": table_id}
    source_rows = []
    for (row, column), cell in sorted(grid.items()):
        reading = readings.get((row, column))
        source_rows.append(
            {
                **base,
                "grid_row": row,
                "grid_column": column,
                "rowspan": cell["rowspan"],
                "colspan": cell["colspan"],
                "text": cell["text"],
                "start_char": cell["start_char"],
                "end_char": cell["end_char"],
                **reading_columns(reading),
            }
        )
    cell_rows, link_rows, member_rows = [], [], []
    for ordinal, member in enumerate(fragment["cells"]):
        coordinates = {"source_row": member["row"], "column_index": member["column"]}
        sources = member["sources"]
        interpretation = interpret_table_cell(
            _cell_text(sources),
            [readings[key] for s in sources if (key := (s["row"], s["column"])) in readings],
        )
        reading = interpretation.reading
        cell_rows.append(
            {
                **base,
                **coordinates,
                "text": _cell_text(sources),
                "column_header": "",
                "status": interpretation.status,
                "status_reason": interpretation.reason,
                "value": interpretation.value,
                "value_row": None if reading is None else reading.row,
                "value_column": None if reading is None else reading.column,
            }
        )
        link_rows.extend(
            {
                **base,
                **coordinates,
                "ordinal": position,
                "grid_row": s["row"],
                "grid_column": s["column"],
            }
            for position, s in enumerate(sources)
        )
        member_rows.append(
            {
                "snapshot_id": snapshot_id,
                "chunk_id": chunk_id,
                "ordinal": ordinal,
                "table_id": table_id,
                **coordinates,
                "text_start": member["text_start"],
                "text_end": member["text_end"],
            }
        )
    return {
        SnapshotParsedTable: [
            {
                **base,
                "doc_id": doc_id,
                "structure_id": None,
                "start_char": start,
                "end_char": end,
                "header_rows": list(fragment["header_rows"]),
                "builder_identity": FRAGMENT_BUILDER,
                "resolver_identity": resolver_identity(),
                "unit_status": unit.status,
                "unit_scale": unit.scale,
                "unit_percent": unit.percent,
                "unit_per_share_plain": unit.per_share_plain,
                "unit_currency": sorted(unit.currency),
            }
        ],
        SnapshotTableCaption: [
            {**base, "ordinal": ordinal, **caption}
            for ordinal, caption in enumerate(fragment["caption_sources"])
        ],
        SnapshotTableSourceCell: source_rows,
        SnapshotTableCell: cell_rows,
        SnapshotTableCellSource: link_rows,
        SnapshotChunkTableCell: member_rows,
        SnapshotChunkTableHeader: [
            {
                "snapshot_id": snapshot_id,
                "chunk_id": chunk_id,
                "ordinal": ordinal,
                "table_id": table_id,
                "grid_row": cell["row"],
                "grid_column": cell["column"],
            }
            for ordinal, cell in enumerate(fragment["header_cells"])
        ],
    }


async def _fragment_column_present(session: AsyncSession, table: str) -> bool:
    """Whether one table still has its ``table_fragment`` column."""
    return bool(
        await session.scalar(
            text(
                "SELECT count(*) FROM information_schema.columns WHERE table_schema = "
                "current_schema() AND table_name = :table AND column_name = 'table_fragment'"
            ),
            {"table": table},
        )
    )


async def _mismatches(
    session: AsyncSession, stored: Mapping[int, object], snapshot_id: int | None
) -> list[int]:
    """Return the chunks whose rebuilt fragment differs from the stored one."""
    rebuilt = await load_table_fragments(session, stored, snapshot_id)
    return sorted(
        chunk_id for chunk_id, fragment in stored.items() if rebuilt.get(chunk_id) != fragment
    )


async def migrate_tables(session: AsyncSession, *, drop: bool) -> dict[str, object]:
    """Freeze snapshot tables, compare every rebuilt fragment, and drop JSON on request.

    Nothing is dropped while a live table chunk lacks its records (ingest it again
    first) or any rebuilt fragment differs from the stored one.
    """
    if not await _fragment_column_present(session, "chunks"):
        return {"status": "migrated", "dropped": True}
    live = {
        row.id: row.table_fragment
        for row in await session.execute(
            text(
                "SELECT id, table_fragment FROM chunks "
                "WHERE jsonb_typeof(table_fragment) = 'object'"
            )
        )
    }
    live_mismatches = await _mismatches(session, live, None)
    snapshots: dict[str, object] = {}
    for snapshot_id in await session.scalars(
        text("SELECT DISTINCT snapshot_id FROM snapshot_chunks ORDER BY snapshot_id")
    ):
        rows = (
            await session.execute(
                text(
                    "SELECT chunk_id, doc_id, start_char, end_char, table_fragment "
                    "FROM snapshot_chunks WHERE snapshot_id = :snapshot "
                    "AND jsonb_typeof(table_fragment) = 'object' ORDER BY chunk_id"
                ),
                {"snapshot": snapshot_id},
            )
        ).all()
        frozen = await session.scalar(
            select(SnapshotParsedTable.table_id)
            .where(SnapshotParsedTable.snapshot_id == snapshot_id)
            .limit(1)
        )
        if frozen is None:
            batches: dict[type, list[dict[str, Any]]] = {}
            for row in rows:
                for model, values in snapshot_rows(
                    snapshot_id,
                    row.doc_id,
                    row.chunk_id,
                    row.start_char,
                    row.end_char,
                    row.table_fragment,
                ).items():
                    batches.setdefault(model, []).extend(values)
            for model, values in batches.items():
                for start in range(0, len(values), 1000):
                    await session.execute(insert(model).values(values[start : start + 1000]))
        stored = {row.chunk_id: row.table_fragment for row in rows}
        snapshots[str(snapshot_id)] = {
            "chunks": len(stored),
            "frozen_now": frozen is None,
            "mismatches": await _mismatches(session, stored, snapshot_id),
        }
    exact = not live_mismatches and not any(
        report["mismatches"] for report in snapshots.values() if isinstance(report, dict)
    )
    dropped = False
    if drop and exact:
        for table, _ in FRAGMENT_COLUMNS:
            await session.execute(text(f"ALTER TABLE {table} DROP COLUMN table_fragment"))
        dropped = True
    return {
        "status": "migrated" if dropped else "checked" if exact else "mismatched",
        "dropped": dropped,
        "live_table_chunks": len(live),
        "live_mismatches": live_mismatches,
        "snapshots": snapshots,
    }


async def run(url: str, *, drop: bool) -> dict[str, object]:
    """Create the table records' schema, then migrate inside one transaction."""
    engine = create_async_engine(url, echo=False)
    try:
        await bootstrap_schema(engine)
        async with async_sessionmaker(engine)() as session, session.begin():
            return await migrate_tables(session, drop=drop)
    finally:
        await engine.dispose()
