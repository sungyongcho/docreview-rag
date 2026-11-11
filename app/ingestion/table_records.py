"""Build the canonical records of each table once, when its chunks are made.

A table is stored once: its original grid cells, its normalized cells with their
interpretation, the captions linked to it, and which part of which normalized cell
every chunk carries. Readers rebuild a chunk's ``TableFragment`` from these records,
and the interpretation is the one ``check_figures`` reads, computed here instead of
at every check.
"""

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from functools import lru_cache
import hashlib
import json
from pathlib import Path

from app.figures.tables import (
    CellFact,
    CellInterpretation,
    TableCellReading,
    TableStatement,
    TableUnit,
    interpret_table_cell,
    read_table_cells,
    read_table_unit,
)
from app.ingestion.chunking import CaptionSource, CellFragment, Chunk, TableFragment
from app.ingestion.parsing.facts import FilingFacts, SourceFact
from app.ingestion.parsing.tables import SourceCell, StructuredTable

_APP = Path(__file__).resolve().parents[1]


@lru_cache(maxsize=1)
def builder_identity() -> str:
    """Fingerprint the code that turns a parsed table into normalized cells and pieces."""
    names = ("ingestion/parsing/tables.py", "ingestion/chunking.py", "ingestion/table_records.py")
    return hashlib.sha256(b"".join((_APP / name).read_bytes() for name in names)).hexdigest()


# The code that decides a stored reading: the figure rules, and the fact reader whose
# contexts, period terms and statement declarations give tagged and untagged cells
# their years and scopes.
RESOLVER_FILES = (
    "figures/currency.py",
    "figures/items.py",
    "figures/vocabulary.py",
    "figures/text.py",
    "figures/tables.py",
    "ingestion/parsing/facts.py",
)


@lru_cache(maxsize=1)
def resolver_identity() -> str:
    """Fingerprint the code that reads units, currencies, years, scopes and items.

    Besides the figure rules this includes the fact reader (``RESOLVER_FILES``),
    since its contexts, period terms and statement declarations change readings.
    """
    return hashlib.sha256(
        b"".join((_APP / name).read_bytes() for name in RESOLVER_FILES)
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class SourceCellRecord:
    """One original grid cell, its reading when it holds figures, and its tagged facts."""

    cell: SourceCell
    reading: TableCellReading | None
    facts: tuple[SourceFact, ...] = ()


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
class HeaderRecord:
    """One header cell a chunk renders, in its fragment's header order.

    A wide table split by columns repeats only the headers of each piece's columns, so
    header cells belong to the chunk, not to the table.
    """

    chunk_stable_key: str
    ordinal: int
    row: int
    column: int


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
    statement: TableStatement | None
    statement_basis: str | None
    captions: tuple[CaptionSource, ...]
    source_cells: tuple[SourceCellRecord, ...]
    cells: tuple[NormalizedCellRecord, ...]
    memberships: tuple[MembershipRecord, ...]
    headers: tuple[HeaderRecord, ...]


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


def _header_cells(table: StructuredTable) -> tuple[SourceCell, ...]:
    """Return every named header cell of the whole table, as the chunker lists them."""
    return tuple(
        dict.fromkeys(
            source
            for row in table.headers
            for cell in row.cells
            for source in cell.sources
            if source.text
        )
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


def _cell_facts(cell: SourceCell, facts: FilingFacts) -> tuple[SourceFact, ...]:
    """Return the tagged facts inside one source cell's span; none without a span."""
    if cell.start_char is None or cell.end_char is None:
        return ()
    return facts.within(cell.start_char, cell.end_char)


def _joined(fact: SourceFact, facts: FilingFacts) -> CellFact:
    """Join one tagged fact with the context and unit its filing declares for it.

    A fact naming a context the filing does not declare keeps no fiscal year and an
    opaque scope, so it can neither date nor stand for the whole entity. An inline
    XBRL fact's sign is ``-`` or ``+`` (no sign attribute); a DART tag states none.
    """
    context = next((c for c in facts.contexts if c.context_id == fact.context_id), None)
    unit = next((u for u in facts.units if u.unit_id == fact.unit_id), None)
    return CellFact(
        fact.concept,
        None if context is None else context.fiscal_year,
        (("undeclared", fact.context_id),) if context is None else context.dimensions,
        None if unit is None else unit.numerator,
        None if unit is None else unit.denominator,
        fact.scale,
        fact.text,
        ("-" if fact.sign == "-" else "+") if facts.source == "ixbrl" else None,
    )


def _statement(start: int, facts: FilingFacts) -> tuple[TableStatement | None, str | None]:
    """Resolve what a filing declares about the statement of the table starting here.

    Only a filing whose form presents several entity scopes declares statements. The
    kind is the most specific one declared (a table group's class over its section);
    scopes that disagree are ``conflicting``. The basis quotes every declaration.
    """
    if not facts.scope_declared:
        return None, None
    found = sorted(
        facts.declarations_at(start),
        key=lambda declaration: declaration.end_char - declaration.start_char,
    )
    kind = next((d.kind for d in found if d.kind is not None and d.kind != "statement"), None)
    scopes = {d.scope for d in found if d.scope is not None}
    scope = next(iter(scopes)) if len(scopes) == 1 else "conflicting" if scopes else None
    return TableStatement(kind, scope), "; ".join(d.basis for d in found) or None


def _table_record(
    doc_id: str,
    structure_id: str,
    start_char: int,
    end_char: int,
    pieces: Sequence[Chunk],
    facts: FilingFacts,
) -> TableRecord:
    """Build one table's records from its chunk pieces, which must agree on the table."""
    first = pieces[0]
    table, fragment = first.table, first.table_fragment
    assert table is not None and fragment is not None
    for piece in pieces[1:]:
        other = piece.table_fragment
        if piece.table != table or other is None:
            raise ValueError(f"{doc_id} table pieces at {start_char} disagree on their table")
        if (other.header_rows, other.caption_sources) != (
            fragment.header_rows,
            fragment.caption_sources,
        ):
            raise ValueError(f"{doc_id} table pieces at {start_char} disagree on headers")
    header_cells = _header_cells(table)
    whole = asdict(_whole_fragment(table, header_cells, fragment.caption_sources))
    tagged = {
        (source.row, source.column): tuple(_joined(fact, facts) for fact in found)
        for row in table.rows
        for cell in row.cells
        for source in cell.sources
        if (found := _cell_facts(source, facts))
    }
    readings: dict[tuple[int, int], TableCellReading] = {}
    terms = {term.term: term.fiscal_year for term in facts.period_terms}
    statement, basis = _statement(start_char, facts)
    for reading in read_table_cells(whole, tagged, terms, statement):
        key = (reading.row, reading.column)
        if readings.setdefault(key, reading) != reading:
            raise ValueError(f"{doc_id} source cell {key} reads two ways")
    sources: dict[tuple[int, int], SourceCell] = {
        (cell.row, cell.column): cell for cell in header_cells
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
    headers: list[HeaderRecord] = []
    for piece in pieces:
        assert piece.table_fragment is not None
        # stable_key hashes the whole fragment, so compute it once per piece.
        key = piece.stable_key
        for ordinal, header in enumerate(piece.table_fragment.header_cells):
            if sources.get((header.row, header.column)) != header:
                raise ValueError(f"{doc_id} chunk header {(header.row, header.column)} is unknown")
            headers.append(HeaderRecord(key, ordinal, header.row, header.column))
        for ordinal, member in enumerate(piece.table_fragment.cells):
            normalized = known.get((member.row, member.column))
            if normalized is None or normalized.sources != member.sources:
                raise ValueError(f"{doc_id} chunk cell {(member.row, member.column)} is unknown")
            memberships.append(
                MembershipRecord(
                    key,
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
        statement,
        basis,
        fragment.caption_sources,
        tuple(
            SourceCellRecord(cell, readings.get(key), _cell_facts(cell, facts))
            for key, cell in sorted(sources.items())
        ),
        tuple(cells),
        tuple(memberships),
        tuple(headers),
    )


def table_records(
    chunks: Sequence[Chunk],
    structure_ids: dict[str, str],
    facts: Mapping[str, FilingFacts] | None = None,
) -> tuple[TableRecord, ...]:
    """Group table chunks by document and source table and build each table's records.

    ``structure_ids`` maps each document to the parse its chunks come from and
    ``facts`` to the tagged facts that parse found; a document without facts has
    none. Table chunks without their whole table (chunked before tables were kept)
    are rejected, since their cells could not be stored.
    """
    facts = facts or {}
    groups: dict[tuple[str, int, int], list[Chunk]] = {}
    for chunk in chunks:
        if chunk.table_fragment is None:
            continue
        if chunk.table is None:
            raise ValueError(f"{chunk.doc_id} chunk {chunk.ordinal} has no table to store")
        groups.setdefault((chunk.doc_id, chunk.start_char, chunk.end_char), []).append(chunk)
    return tuple(
        _table_record(
            doc_id, structure_ids[doc_id], start, end, pieces, facts.get(doc_id, FilingFacts())
        )
        for (doc_id, start, end), pieces in sorted(groups.items())
    )
