"""Read the stored table records of retrieved table chunks.

Each table chunk's ``TableFragment`` and figure readings are rebuilt from the
canonical table rows, from the live index or from the snapshot it was retrieved from.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any

from sqlalchemy import ColumnElement, Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

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
from app.figures.answers import EvidenceText
from app.figures.tables import TableCellReading, complete_cell
from app.ingestion.persistence import slices
from app.ingestion.table_records import builder_identity, resolver_identity

type _GridCell = TableSourceCell | SnapshotTableSourceCell
type _Member = ChunkTableCell | SnapshotChunkTableCell
type _Table = ParsedTable | SnapshotParsedTable
type _Caption = TableCaption | SnapshotTableCaption
type _Header = ChunkTableHeader | SnapshotChunkTableHeader
type _Link = TableCellSource | SnapshotTableCellSource


@dataclass(frozen=True, slots=True)
class StoredTable:
    """One table chunk as stored: its fragment as JSON and the readings it carries.

    ``readings`` lists, for every fragment cell in order, the readings of its
    figure-bearing source cells, exactly as ``read_table_cells`` yields them.
    """

    fragment: dict[str, object]
    readings: tuple[TableCellReading, ...]


def stored_table_counts() -> Select[int, int]:
    """Count the live stored tables, and those not built and read by the running code."""
    return select(
        func.count(),
        func.count().filter(
            (ParsedTable.resolver_identity != resolver_identity())
            | (ParsedTable.builder_identity != builder_identity())
        ),
    ).select_from(ParsedTable)


def current_table(table: _Table) -> bool:
    """Whether a stored table was built and read by the running builder and interpreter."""
    return (table.builder_identity, table.resolver_identity) == (
        builder_identity(),
        resolver_identity(),
    )


def cell_ref(chunk_id: int, row: int, column: int) -> str:
    """Name one cell of a stored table chunk as a selection names it ("7:r3c1")."""
    return f"{chunk_id}:r{row}c{column}"


def cell_ref_chunk(ref: str) -> int:
    """Return the chunk id a cell ref names."""
    return int(ref.split(":", 1)[0])


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
    measure = cell.reading_measure
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
        "fact" if cell.reading_basis == "fact" else "text",
        tuple(cell.reading_overrides or ()),
        cell.reading_scope,
        measure if measure in ("amount", "per_share", "other") else None,
    )


def assemble_tables(
    members: Sequence[_Member],
    tables: Mapping[str, _Table],
    table_captions: Iterable[_Caption],
    grid_cells: Iterable[_GridCell],
    chunk_headers: Iterable[_Header],
    cell_links: Iterable[_Link],
) -> dict[int, StoredTable]:
    """Assemble each chunk's stored table from its rows, keeping the order they come in.

    Parameters
    ----------
    members : Sequence[_Member]
        The chunks' cell memberships, ordered by chunk and ordinal; never empty.
    tables : Mapping[str, _Table]
        Every table a member names, by table id.
    table_captions : Iterable[_Caption]
        The tables' captions, ordered by table and ordinal.
    grid_cells : Iterable[_GridCell]
        Every source grid cell of the tables.
    chunk_headers : Iterable[_Header]
        The chunks' header cells, ordered by chunk and ordinal.
    cell_links : Iterable[_Link]
        The links from each normalized cell to its source grid cells, ordered by table,
        cell and ordinal.

    Returns
    -------
    dict[int, StoredTable]
        Each chunk's fragment as JSON and its readings, in member order.

    Raises
    ------
    ValueError
        If one chunk links cells of two tables.
    """
    table_ids = sorted({member.table_id for member in members})
    captions: dict[str, list[dict[str, object]]] = {table_id: [] for table_id in table_ids}
    for caption in table_captions:
        captions[caption.table_id].append(
            {
                "start_char": caption.start_char,
                "end_char": caption.end_char,
                "text": caption.text,
                "cells": caption.cells,
            }
        )
    grid: dict[tuple[str, int, int], _GridCell] = {}
    for cell in grid_cells:
        grid[(cell.table_id, cell.grid_row, cell.grid_column)] = cell
    headers: dict[int, list[dict[str, object]]] = {}
    for header in chunk_headers:
        headers.setdefault(header.chunk_id, []).append(
            _source_json(grid[(header.table_id, header.grid_row, header.grid_column)])
        )
    sources: dict[tuple[str, int, int], list[_GridCell]] = {}
    for link in cell_links:
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
        text = " ".join(source.text for source in member_sources if source.text)
        complete = complete_cell(text, member.text_start, member.text_end)
        member_readings = [r for source in member_sources if (r := _reading(source)) is not None]
        for reading in member_readings:
            holds = (() if complete else ("incomplete",)) + (
                ("multiple",) if len(member_readings) > 1 else ()
            )
            readings.setdefault(member.chunk_id, []).append(
                replace(reading, overrides=(*reading.overrides, *holds)) if holds else reading
            )
        readings.setdefault(member.chunk_id, [])
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


async def load_chunk_tables(
    session: AsyncSession,
    chunk_ids: Iterable[int],
    snapshot_id: int | None = None,
    *,
    current_only: bool = False,
) -> dict[int, StoredTable]:
    """Return the stored table of each table chunk, from the index it was retrieved from.

    Text chunks, and table chunks stored without their table, are left out; so is a
    live table built or read by code other than the running code when ``current_only``
    is set (see ``current_table``). A snapshot is frozen by design and kept whole.
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

    async def read[M: Base](
        model: type[M],
        column: InstrumentedAttribute[Any],
        keys: Sequence[object],
        *order: InstrumentedAttribute[Any],
    ) -> list[M]:
        """Read one model's rows whose ``column`` is among ``keys``, a bounded slice at a time.

        Every row of one chunk or table falls in one slice, so its rows keep ``order``.
        """
        rows: list[M] = []
        for part in slices(keys):
            rows.extend(
                await session.scalars(
                    select(model).where(*scope(model), column.in_(part)).order_by(*order)
                )
            )
        return rows

    members = await read(
        members_model, members_model.chunk_id, ids, members_model.chunk_id, members_model.ordinal
    )
    if not members:
        return {}
    table_ids = sorted({member.table_id for member in members})
    tables = {
        table.table_id: table
        for table in await read(tables_model, tables_model.table_id, table_ids)
    }
    table_captions = await read(
        captions_model,
        captions_model.table_id,
        table_ids,
        captions_model.table_id,
        captions_model.ordinal,
    )
    grid_cells = await read(cells_model, cells_model.table_id, table_ids)
    chunk_headers = await read(
        headers_model, headers_model.chunk_id, ids, headers_model.chunk_id, headers_model.ordinal
    )
    cell_links = await read(
        links_model,
        links_model.table_id,
        table_ids,
        links_model.table_id,
        links_model.source_row,
        links_model.column_index,
        links_model.ordinal,
    )
    stored = assemble_tables(members, tables, table_captions, grid_cells, chunk_headers, cell_links)
    if snapshot_id is not None or not current_only:
        return stored
    stale = {member.chunk_id for member in members if not current_table(tables[member.table_id])}
    return {chunk_id: table for chunk_id, table in stored.items() if chunk_id not in stale}


async def load_table_readings(
    session: AsyncSession, chunk_ids: Iterable[int], snapshot_id: int | None = None
) -> dict[int, tuple[TableCellReading, ...]]:
    """Return the usable stored figure readings of each table chunk, for the figure check.

    A table chunk is left out when its readings are not usable: stored without its
    table, or a live table from code other than the running code. A snapshot's
    readings are returned as frozen. See ``figure_evidence`` for what a left-out
    table chunk gives the check.
    """
    stored = await load_chunk_tables(session, chunk_ids, snapshot_id, current_only=True)
    return {chunk_id: table.readings for chunk_id, table in stored.items()}


def figure_evidence(
    chunk_id: int,
    kind: str,
    body: str,
    context_header: str,
    readings: Mapping[int, Sequence[TableCellReading]],
) -> EvidenceText:
    """Give the figure check what one cited chunk can confirm, the same on every path.

    Running text gives its body. A table chunk gives its body and its usable stored
    readings from ``load_table_readings``; one without them gives no body and no cells,
    because its body read as running text would confirm more loosely than its table.
    """
    if kind != "table":
        return EvidenceText(chunk_id, body, context_header)
    cells = readings.get(chunk_id)
    if cells is None:
        return EvidenceText(chunk_id, "", context_header, ())
    return EvidenceText(chunk_id, body, context_header, cells)


async def load_table_fragments(
    session: AsyncSession, chunk_ids: Iterable[int], snapshot_id: int | None = None
) -> dict[int, dict[str, object]]:
    """Return each table chunk's ``TableFragment`` as JSON, rebuilt from its stored table."""
    stored = await load_chunk_tables(session, chunk_ids, snapshot_id)
    return {chunk_id: table.fragment for chunk_id, table in stored.items()}


def catalog_cells(
    chunk_id: int,
    chunk: Chunk,
    table: ParsedTable,
    members: Sequence[ChunkTableCell],
    normalized: Mapping[tuple[int, int], TableCell],
    grid: Mapping[tuple[int, int], TableSourceCell],
) -> dict[str, object]:
    """List the selectable cells of one stored table chunk, with what makes them known.

    Parameters
    ----------
    chunk_id : int
        The chunk the cells' refs name.
    chunk : Chunk
        The stored table chunk.
    table : ParsedTable
        The table every member belongs to.
    members : Sequence[ChunkTableCell]
        The chunk's cell memberships in ordinal order; never empty.
    normalized : Mapping[tuple[int, int], TableCell]
        The table's normalized cells by source row and column index.
    grid : Mapping[tuple[int, int], TableSourceCell]
        The table's source grid cells by grid row and column.

    Returns
    -------
    dict[str, object]
        The ``available`` catalog: the table's unit and every cell except blank and
        non-numeric ones, in member order.
    """
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
                "ref": cell_ref(chunk_id, member.source_row, member.column_index),
                "row_label": None if reading is None else reading.row_label,
                "column_header": cell.column_header,
                "raw_text": cell.text,
                "item": None if reading is None else reading.item,
                "fiscal_years": [] if reading is None else sorted(reading.years),
                "scale": None if reading is None or reading.scale is None else f"{reading.scale:f}",
                "currency": None if reading is None else reading.currency,
                "percent": None if reading is None else reading.percent,
                "status": cell.status,
                "complete": complete_cell(cell.text, member.text_start, member.text_end),
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


async def load_cell_catalog(session: AsyncSession, chunk_id: int) -> dict[str, object]:
    """Return the selectable cells one stored chunk carries, with what makes them known.

    ``status`` is ``not_table`` for running text, ``missing_records`` for a table
    chunk stored without rows, and ``stale_reading`` with both identities when its
    table was built or read by other code (see ``current_table``);
    neither means the documents lack an answer. Blank and
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
        return {"status": "missing_records"}
    table_id = members[0].table_id
    table = await session.get(ParsedTable, table_id)
    assert table is not None
    if not current_table(table):
        return {
            "status": "stale_reading",
            "stored_identity": {
                "builder_identity": table.builder_identity,
                "resolver_identity": table.resolver_identity,
            },
            "running_identity": {
                "builder_identity": builder_identity(),
                "resolver_identity": resolver_identity(),
            },
        }
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
    return catalog_cells(chunk_id, chunk, table, members, normalized, grid)
