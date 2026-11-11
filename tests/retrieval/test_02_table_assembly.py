"""Stored table rows assembled into fragments, readings and cell catalogs, offline."""

from dataclasses import replace
from decimal import Decimal

import pytest

from app.db.models import (
    Chunk,
    ChunkTableCell,
    ChunkTableHeader,
    ParsedTable,
    TableCaption,
    TableCell,
    TableCellSource,
    TableSourceCell,
)
from app.figures.tables import TableCellReading
from app.ingestion.persistence import reading_columns
from app.retrieval.tables import assemble_tables, catalog_cells

TABLE = "t" * 64


def revenue(column: int, value: str, **changes: object) -> TableCellReading:
    """Build one FY2024 USD million revenue reading of row 1, changed where a test says."""
    base = TableCellReading(
        1,
        column,
        frozenset({Decimal(value)}),
        frozenset({2024}),
        Decimal(1_000_000),
        "revenue",
        False,
        "USD",
        row_label="Net revenue",
    )
    return replace(base, **changes)


def grid(row: int, column: int, text: str, reading: TableCellReading | None = None):
    """Build one stored source grid cell carrying ``reading`` in its columns."""
    return TableSourceCell(
        table_id=TABLE,
        grid_row=row,
        grid_column=column,
        rowspan=1,
        colspan=1,
        text=text,
        start_char=None,
        end_char=None,
        **reading_columns(reading),
    )


def member(ordinal: int, row: int, column: int, table: str = TABLE, chunk: int = 7, end: int = 6):
    """Build one chunk cell membership covering its whole cell text."""
    return ChunkTableCell(
        chunk_id=chunk,
        ordinal=ordinal,
        table_id=table,
        source_row=row,
        column_index=column,
        text_start=0,
        text_end=end,
    )


def link(row: int, column: int, ordinal: int, grid_row: int, grid_column: int):
    """Link one normalized cell to one source grid cell."""
    return TableCellSource(
        table_id=TABLE,
        source_row=row,
        column_index=column,
        ordinal=ordinal,
        grid_row=grid_row,
        grid_column=grid_column,
    )


def header(ordinal: int, column: int) -> ChunkTableHeader:
    """Build one header cell of chunk 7 on grid row 0."""
    return ChunkTableHeader(
        chunk_id=7, ordinal=ordinal, table_id=TABLE, grid_row=0, grid_column=column
    )


def test_a_fragment_keeps_member_header_and_caption_order():
    """Rebuild cells, headers and captions in the order their rows are read."""
    cells = [grid(0, 0, "(In millions)"), grid(0, 1, "2024"), grid(1, 0, "Net revenue")]
    cells.append(grid(1, 1, "25,785"))
    caption = TableCaption(
        table_id=TABLE, ordinal=0, start_char=0, end_char=13, text="(In millions)", cells=[]
    )
    stored = assemble_tables(
        [member(0, 1, 0), member(1, 1, 1)],
        {TABLE: ParsedTable(table_id=TABLE, header_rows=[0])},
        [caption],
        cells,
        [header(0, 0), header(1, 1)],
        [link(1, 0, 0, 1, 0), link(1, 1, 0, 1, 1)],
    )
    fragment = stored[7].fragment
    assert fragment["header_rows"] == [0]
    assert [(cell["row"], cell["column"]) for cell in fragment["cells"]] == [(1, 0), (1, 1)]
    assert [cell["sources"][0]["text"] for cell in fragment["cells"]] == [
        "Net revenue",
        "25,785",
    ]
    assert [cell["text"] for cell in fragment["header_cells"]] == ["(In millions)", "2024"]
    assert [source["text"] for source in fragment["caption_sources"]] == ["(In millions)"]


def test_readings_follow_member_order_then_link_order():
    """List each member's readings in link order, skipping sources without one."""
    first, second, third = revenue(1, "25785"), revenue(2, "22680"), revenue(3, "1")
    stored = assemble_tables(
        [member(0, 1, 3, end=1), member(1, 1, 1, end=25)],
        {TABLE: ParsedTable(table_id=TABLE, header_rows=[0])},
        [],
        [grid(1, 0, "Net revenue"), grid(1, 1, "25,785", first), grid(1, 2, "22,680", second)]
        + [grid(1, 3, "1", third)],
        [],
        [link(1, 1, 0, 1, 2), link(1, 1, 1, 1, 0), link(1, 1, 2, 1, 1), link(1, 3, 0, 1, 3)],
    )
    assert stored[7].readings == (
        third,
        replace(second, overrides=("multiple",)),
        replace(first, overrides=("multiple",)),
    )


def test_a_chunk_linking_cells_of_two_tables_is_refused():
    """Refuse a chunk whose members name two different tables."""
    with pytest.raises(ValueError, match="chunk 7 links cells of two tables"):
        assemble_tables([member(0, 1, 0), member(1, 1, 1, table="u" * 64)], {}, [], [], [], [])


def test_a_stored_reading_round_trips_through_its_columns():
    """Read back exactly the reading persistence wrote into a grid cell's columns."""
    reading = revenue(
        1,
        "25785.5",
        marked=True,
        basis="fact",
        overrides=("scale",),
        scope="entity",
        measure="amount",
    )
    stored = assemble_tables(
        [member(0, 1, 1, end=8)],
        {TABLE: ParsedTable(table_id=TABLE, header_rows=[0])},
        [],
        [grid(1, 1, "25,785.5", reading)],
        [],
        [link(1, 1, 0, 1, 1)],
    )
    assert stored[7].readings == (reading,)


def test_a_catalog_lists_numeric_cells_by_ref_with_their_reading():
    """Leave blank cells out and describe the rest from their value cell's reading."""
    chunk = Chunk(id=7, kind="table", stable_key="k" * 64)
    table = ParsedTable(
        table_id=TABLE,
        resolver_identity="r" * 64,
        unit_status="known",
        unit_scale=Decimal(1_000_000),
        unit_currency=["USD"],
    )
    normalized = {
        (1, 0): TableCell(text="", column_header="", status="blank"),
        (1, 1): TableCell(
            text="25,785", column_header="2024", status="known", value_row=1, value_column=1
        ),
    }
    catalog = catalog_cells(
        7,
        chunk,
        table,
        [member(0, 1, 0), member(1, 1, 1)],
        normalized,
        {(1, 1): grid(1, 1, "25,785", revenue(1, "25785"))},
    )
    assert catalog["unit"] == {"status": "known", "scale": "1000000", "currency": ["USD"]}
    (cell,) = catalog["cells"]
    assert (cell["ref"], cell["item"], cell["fiscal_years"], cell["complete"]) == (
        "7:r1c1",
        "revenue",
        [2024],
        True,
    )


@pytest.mark.parametrize("start,end,eligible", [(0, 6, True), (0, 2, False), (4, 6, False)])
def test_only_whole_memberships_can_certify_the_source_amount(start, end, eligible):
    """A complete cell verifies; value-only and label-only slices cannot supply it."""
    from app.evals.execution.retrievers import _fragment_cell_spans
    from app.figures.answers import EvidenceText, check_figures

    membership = member(0, 1, 1, end=end)
    membership.text_start = start
    source = grid(1, 1, "25,785", revenue(1, "25785"))
    source.start_char, source.end_char = 100, 120
    stored = assemble_tables(
        [membership],
        {TABLE: ParsedTable(table_id=TABLE, header_rows=[])},
        [],
        [source],
        [],
        [link(1, 1, 0, 1, 1)],
    )[7]
    assert stored.readings[0].evidence_eligible is eligible
    verdict = check_figures(
        "FY2024 revenue was USD 25,785 million.",
        [EvidenceText(7, "25,785"[start:end], "", stored.readings)],
        [2024],
    ).verdict
    assert verdict == ("verified" if eligible else "unverified")
    assert _fragment_cell_spans(stored.fragment) == (((100, 120),) if eligible else None)
