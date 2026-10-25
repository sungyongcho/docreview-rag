"""Build the canonical records of each table once, when its chunks are made.

A table is stored once: its original grid cells, its normalized cells with their
interpretation, the captions linked to it, and which part of which normalized cell
every chunk carries. Readers rebuild a chunk's ``TableFragment`` from these records,
and the interpretation is the one ``check_figures`` reads, computed here instead of
at every check.
"""

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from functools import lru_cache
import hashlib
import json
from pathlib import Path

from app.contracts.figures import (
    CellInterpretation,
    TableCellReading,
    TableUnit,
    interpret_table_cell,
    read_table_cells,
    read_table_unit,
)
from app.ingestion.chunking import CaptionSource, CellFragment, Chunk, TableFragment
from app.ingestion.parsing.tables import SourceCell, StructuredTable

_APP = Path(__file__).resolve().parents[1]


@lru_cache(maxsize=1)
def builder_identity() -> str:
    """Fingerprint the code that turns a parsed table into normalized cells and pieces."""
    names = ("ingestion/parsing/tables.py", "ingestion/chunking.py", "ingestion/table_records.py")
    return hashlib.sha256(b"".join((_APP / name).read_bytes() for name in names)).hexdigest()


@lru_cache(maxsize=1)
def resolver_identity() -> str:
    """Fingerprint the code that reads units, currencies, years and items from a table."""
    return hashlib.sha256((_APP / "contracts" / "figures.py").read_bytes()).hexdigest()


@dataclass(frozen=True, slots=True)
class SourceCellRecord:
    """One original grid cell, its header position and its reading when it holds figures.

    ``header_ordinal`` is the cell's position among the table's header cells, None for a
    body cell.
    """

    cell: SourceCell
    header_ordinal: int | None
    reading: TableCellReading | None


@dataclass(frozen=True, slots=True)
class NormalizedCellRecord:
    """One normalized body cell: its text, column header, sources and interpretation.

    ``row`` is the source row and ``column`` the normalized column, the coordinates a
    ``CellFragment`` names.
    """

    row: int
    column: int
    text: str
    column_header: str
    sources: tuple[SourceCell, ...]
    interpretation: CellInterpretation


@dataclass(frozen=True, slots=True)
class MembershipRecord:
    """Which interval of one normalized cell a chunk carries, in fragment order."""

    chunk_stable_key: str
    ordinal: int
    row: int
    column: int
    text_start: int
    text_end: int


@dataclass(frozen=True, slots=True)
class TableRecord:
    """Every stored fact of one table and the chunks that carry its cells."""

    table_id: str
    doc_id: str
    structure_id: str
    start_char: int
    end_char: int
    header_rows: tuple[int, ...]
    unit: TableUnit
    captions: tuple[CaptionSource, ...]
    source_cells: tuple[SourceCellRecord, ...]
    cells: tuple[NormalizedCellRecord, ...]
    memberships: tuple[MembershipRecord, ...]


def _table_id(structure_id: str, start_char: int, end_char: int) -> str:
    """Identify a table by its parse and its source span."""
    payload = json.dumps([structure_id, start_char, end_char], separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def _column_header(table: StructuredTable, column: int) -> str:
    """Join the header texts above one normalized column, as the rendered table shows."""
    return " ".join(
        row.cells[column].text
        for row in table.headers
        if column < len(row.cells) and row.cells[column].text
    )


def _whole_fragment(
    table: StructuredTable,
    header_cells: tuple[SourceCell, ...],
    captions: tuple[CaptionSource, ...],
) -> TableFragment:
    """Describe every body cell of a table as one fragment, for reading the whole table."""
    return TableFragment(
        tuple(row.source_row for row in table.headers),
        tuple(
            CellFragment(row.source_row, cell.column, 0, len(cell.text), cell.sources)
            for row in table.rows
            for cell in row.cells
        ),
        header_cells,
        captions,
    )


def _table_record(
    doc_id: str, structure_id: str, start_char: int, end_char: int, pieces: Sequence[Chunk]
) -> TableRecord:
    """Build one table's records from its chunk pieces, which must agree on the table."""
    first = pieces[0]
    table, fragment = first.table, first.table_fragment
    assert table is not None and fragment is not None
    for piece in pieces[1:]:
        other = piece.table_fragment
        if piece.table != table or other is None:
            raise ValueError(f"{doc_id} table pieces at {start_char} disagree on their table")
        if (other.header_rows, other.header_cells, other.caption_sources) != (
            fragment.header_rows,
            fragment.header_cells,
            fragment.caption_sources,
        ):
            raise ValueError(f"{doc_id} table pieces at {start_char} disagree on headers")
    whole = asdict(_whole_fragment(table, fragment.header_cells, fragment.caption_sources))
    readings: dict[tuple[int, int], TableCellReading] = {}
    for reading in read_table_cells(whole):
        key = (reading.row, reading.column)
        if readings.setdefault(key, reading) != reading:
            raise ValueError(f"{doc_id} source cell {key} reads two ways")
    header_positions = {
        (cell.row, cell.column): ordinal for ordinal, cell in enumerate(fragment.header_cells)
    }
    sources: dict[tuple[int, int], SourceCell] = {
        (cell.row, cell.column): cell for cell in fragment.header_cells
    }
    cells: list[NormalizedCellRecord] = []
    for row in table.rows:
        for cell in row.cells:
            for source in cell.sources:
                sources.setdefault((source.row, source.column), source)
            cells.append(
                NormalizedCellRecord(
                    row.source_row,
                    cell.column,
                    cell.text,
                    _column_header(table, cell.column),
                    cell.sources,
                    interpret_table_cell(
                        cell.text,
                        [
                            readings[key]
                            for source in cell.sources
                            if (key := (source.row, source.column)) in readings
                        ],
                    ),
                )
            )
    known = {(cell.row, cell.column): cell for cell in cells}
    memberships: list[MembershipRecord] = []
    for piece in pieces:
        assert piece.table_fragment is not None
        for ordinal, member in enumerate(piece.table_fragment.cells):
            normalized = known.get((member.row, member.column))
            if normalized is None or normalized.sources != member.sources:
                raise ValueError(f"{doc_id} chunk cell {(member.row, member.column)} is unknown")
            memberships.append(
                MembershipRecord(
                    piece.stable_key,
                    ordinal,
                    member.row,
                    member.column,
                    member.text_start,
                    member.text_end,
                )
            )
    return TableRecord(
        _table_id(structure_id, start_char, end_char),
        doc_id,
        structure_id,
        start_char,
        end_char,
        fragment.header_rows,
        read_table_unit(whole),
        fragment.caption_sources,
        tuple(
            SourceCellRecord(cell, header_positions.get(key), readings.get(key))
            for key, cell in sorted(sources.items())
        ),
        tuple(cells),
        tuple(memberships),
    )


def table_records(
    chunks: Sequence[Chunk], structure_ids: dict[str, str]
) -> tuple[TableRecord, ...]:
    """Group table chunks by document and source table and build each table's records.

    ``structure_ids`` maps each document to the parse its chunks come from. Table
    chunks without their whole table (chunked before tables were kept) are rejected,
    since their cells could not be stored.
    """
    groups: dict[tuple[str, int, int], list[Chunk]] = {}
    for chunk in chunks:
        if chunk.table_fragment is None:
            continue
        if chunk.table is None:
            raise ValueError(f"{chunk.doc_id} chunk {chunk.ordinal} has no table to store")
        groups.setdefault((chunk.doc_id, chunk.start_char, chunk.end_char), []).append(chunk)
    return tuple(
        _table_record(doc_id, structure_ids[doc_id], start, end, pieces)
        for (doc_id, start, end), pieces in sorted(groups.items())
    )
