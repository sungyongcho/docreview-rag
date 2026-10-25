"""Read the stored table records of retrieved table chunks.

Each table chunk's ``TableFragment`` and figure readings are rebuilt from the
canonical table rows, from the live index or from the snapshot it was retrieved from.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import ColumnElement, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.figures import TableCellReading
from app.db.models import (
    Base,
    Chunk,
    ChunkTableCell,
    ChunkTableHeader,
    ParsedTable,
    SnapshotChunkTableCell,
    SnapshotChunkTableHeader,
    SnapshotParsedTable,
    SnapshotTableCaption,
    SnapshotTableCellSource,
    SnapshotTableSourceCell,
    TableCaption,
    TableCell,
    TableCellSource,
    TableSourceCell,
)

type _GridCell = TableSourceCell | SnapshotTableSourceCell


@dataclass(frozen=True, slots=True)
class StoredTable:
    """One table chunk as stored: its fragment as JSON and the readings it carries.

    ``readings`` lists, for every fragment cell in order, the readings of its
    figure-bearing source cells, exactly as ``read_table_cells`` yields them.
    """

    fragment: dict[str, object]
    readings: tuple[TableCellReading, ...]


def _source_json(cell: _GridCell) -> dict[str, object]:
    """Render one stored grid cell as the ``SourceCell`` JSON a fragment holds."""
    return {
        "row": cell.grid_row,
        "column": cell.grid_column,
        "rowspan": cell.rowspan,
        "colspan": cell.colspan,
        "text": cell.text,
        "start_char": cell.start_char,
        "end_char": cell.end_char,
    }


def _reading(cell: _GridCell) -> TableCellReading | None:
    """Rebuild the stored reading of one grid cell, or None when it holds no figures."""
    if cell.reading_values is None or cell.reading_years is None:
        return None
    return TableCellReading(
        cell.grid_row,
        cell.grid_column,
        frozenset(Decimal(value) for value in cell.reading_values),
        frozenset(cell.reading_years),
        cell.reading_scale,
        cell.reading_item,
        cell.reading_percent,
        cell.reading_currency,
        bool(cell.reading_marked),
        cell.reading_row_label,
    )


async def load_chunk_tables(
    session: AsyncSession, chunk_ids: Iterable[int], snapshot_id: int | None = None
) -> dict[int, StoredTable]:
    """Return the stored table of each table chunk, from the index it was retrieved from.

    Text chunks, and table chunks stored without their table, are left out.
    """
    ids = sorted(set(chunk_ids))
    if not ids:
        return {}
    if snapshot_id is None:
        members_model, tables_model, captions_model = ChunkTableCell, ParsedTable, TableCaption
        cells_model, links_model, headers_model = TableSourceCell, TableCellSource, ChunkTableHeader
        frozen: dict[type[Base], list[ColumnElement[bool]]] = {}
    else:
        members_model, tables_model = SnapshotChunkTableCell, SnapshotParsedTable
        captions_model, cells_model = SnapshotTableCaption, SnapshotTableSourceCell
        links_model, headers_model = SnapshotTableCellSource, SnapshotChunkTableHeader
        frozen = {
            model: [model.snapshot_id == snapshot_id]
            for model in (
                SnapshotChunkTableCell,
                SnapshotChunkTableHeader,
                SnapshotParsedTable,
                SnapshotTableCaption,
                SnapshotTableSourceCell,
                SnapshotTableCellSource,
            )
        }

    def scope(model: type[Base]) -> list[ColumnElement[bool]]:
        """Read only the rows a snapshot froze, or the live index."""
        return frozen.get(model, [])

    members = (
        await session.scalars(
            select(members_model)
            .where(*scope(members_model), members_model.chunk_id.in_(ids))
            .order_by(members_model.chunk_id, members_model.ordinal)
        )
    ).all()
    if not members:
        return {}
    table_ids = sorted({member.table_id for member in members})
    tables = {
        table.table_id: table
        for table in await session.scalars(
            select(tables_model).where(*scope(tables_model), tables_model.table_id.in_(table_ids))
        )
    }
    captions: dict[str, list[dict[str, object]]] = {table_id: [] for table_id in table_ids}
    for caption in await session.scalars(
        select(captions_model)
        .where(*scope(captions_model), captions_model.table_id.in_(table_ids))
        .order_by(captions_model.table_id, captions_model.ordinal)
    ):
        captions[caption.table_id].append(
            {
                "start_char": caption.start_char,
                "end_char": caption.end_char,
                "text": caption.text,
                "cells": caption.cells,
            }
        )
    grid: dict[tuple[str, int, int], _GridCell] = {}
    for cell in await session.scalars(
        select(cells_model).where(*scope(cells_model), cells_model.table_id.in_(table_ids))
    ):
        grid[(cell.table_id, cell.grid_row, cell.grid_column)] = cell
    headers: dict[int, list[dict[str, object]]] = {}
    for header in await session.scalars(
        select(headers_model)
        .where(*scope(headers_model), headers_model.chunk_id.in_(ids))
        .order_by(headers_model.chunk_id, headers_model.ordinal)
    ):
        headers.setdefault(header.chunk_id, []).append(
            _source_json(grid[(header.table_id, header.grid_row, header.grid_column)])
        )
    sources: dict[tuple[str, int, int], list[_GridCell]] = {}
    for link in await session.scalars(
        select(links_model)
        .where(*scope(links_model), links_model.table_id.in_(table_ids))
        .order_by(
            links_model.table_id,
            links_model.source_row,
            links_model.column_index,
            links_model.ordinal,
        )
    ):
        sources.setdefault((link.table_id, link.source_row, link.column_index), []).append(
            grid[(link.table_id, link.grid_row, link.grid_column)]
        )

    cells: dict[int, list[dict[str, object]]] = {}
    readings: dict[int, list[TableCellReading]] = {}
    owners: dict[int, str] = {}
    for member in members:
        if owners.setdefault(member.chunk_id, member.table_id) != member.table_id:
            raise ValueError(f"chunk {member.chunk_id} links cells of two tables")
        member_sources = sources.get((member.table_id, member.source_row, member.column_index), [])
        cells.setdefault(member.chunk_id, []).append(
            {
                "row": member.source_row,
                "column": member.column_index,
                "text_start": member.text_start,
                "text_end": member.text_end,
                "sources": [_source_json(source) for source in member_sources],
            }
        )
        readings.setdefault(member.chunk_id, []).extend(
            reading for source in member_sources if (reading := _reading(source)) is not None
        )
    return {
        chunk_id: StoredTable(
            {
                "header_rows": list(tables[table_id].header_rows),
                "cells": cells[chunk_id],
                "header_cells": headers.get(chunk_id, []),
                "caption_sources": captions[table_id],
            },
            tuple(readings[chunk_id]),
        )
        for chunk_id, table_id in owners.items()
    }


async def load_table_readings(
    session: AsyncSession, chunk_ids: Iterable[int], snapshot_id: int | None = None
) -> dict[int, tuple[TableCellReading, ...]]:
    """Return the stored figure readings of each table chunk, for the figure check."""
    stored = await load_chunk_tables(session, chunk_ids, snapshot_id)
    return {chunk_id: table.readings for chunk_id, table in stored.items()}


async def load_table_fragments(
    session: AsyncSession, chunk_ids: Iterable[int], snapshot_id: int | None = None
) -> dict[int, dict[str, object]]:
    """Return each table chunk's ``TableFragment`` as JSON, rebuilt from its stored table."""
    stored = await load_chunk_tables(session, chunk_ids, snapshot_id)
    return {chunk_id: table.fragment for chunk_id, table in stored.items()}


async def load_cell_catalog(session: AsyncSession, chunk_id: int) -> dict[str, object]:
    """Return the selectable cells one stored chunk carries, with what makes them known.

    ``status`` is ``not_table`` for running text and ``unavailable`` for a table chunk
    stored without its table; neither means the documents lack an answer. Blank and
    non-numeric cells are left out; every other cell is listed with its own status, so a
    cell whose unit, currency, period or item is unknown is visible but not certified.
    """
    chunk = await session.get(Chunk, chunk_id)
    if chunk is None or chunk.kind != "table":
        return {"status": "not_table"}
    members = (
        await session.scalars(
            select(ChunkTableCell)
            .where(ChunkTableCell.chunk_id == chunk_id)
            .order_by(ChunkTableCell.ordinal)
        )
    ).all()
    if not members:
        return {"status": "unavailable"}
    table_id = members[0].table_id
    table = await session.get(ParsedTable, table_id)
    assert table is not None
    normalized = {
        (cell.source_row, cell.column_index): cell
        for cell in await session.scalars(select(TableCell).where(TableCell.table_id == table_id))
    }
    grid = {
        (cell.grid_row, cell.grid_column): cell
        for cell in await session.scalars(
            select(TableSourceCell).where(TableSourceCell.table_id == table_id)
        )
    }
    cells: list[dict[str, object]] = []
    for member in members:
        cell = normalized[(member.source_row, member.column_index)]
        if cell.status in ("blank", "not_numeric"):
            continue
        source = None
        if cell.value_row is not None and cell.value_column is not None:
            source = grid.get((cell.value_row, cell.value_column))
        reading = None if source is None else _reading(source)
        cells.append(
            {
                "ref": f"{chunk_id}:r{member.source_row}c{member.column_index}",
                "row_label": None if reading is None else reading.row_label,
                "column_header": cell.column_header,
                "raw_text": cell.text,
                "item": None if reading is None else reading.item,
                "fiscal_years": [] if reading is None else sorted(reading.years),
                "scale": None if reading is None or reading.scale is None else f"{reading.scale:f}",
                "currency": None if reading is None else reading.currency,
                "percent": None if reading is None else reading.percent,
                "status": cell.status,
                "complete": member.text_start == 0 and member.text_end == len(cell.text),
            }
        )
    return {
        "status": "available",
        "stable_key": chunk.stable_key,
        "resolver_identity": table.resolver_identity,
        "unit": {
            "status": table.unit_status,
            "scale": None if table.unit_scale is None else f"{table.unit_scale:f}",
            "currency": sorted(table.unit_currency),
        },
        "cells": cells,
    }
