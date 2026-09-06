"""M1.2 — table HTML to markdown. `app/ingestion/tables.py` L2-L7.

This suite protects layout collapse, not mere serialization. Direct SEC-table
serialization produces a mostly empty, wide grid that is worse for retrieval than
the source text, so the collapse ratio is pinned as a corpus golden value.

To grade an independent implementation:
    uv run pytest tests/ingestion/test_09_tables.py
"""

from types import ModuleType

from bs4 import BeautifulSoup, Tag
import pytest

from tests.ingestion.golden import NVDA_FY2024_INCOME_MD, TABLES
from tests.support import need

type BlocksByDoc = dict[str, tuple[BeautifulSoup, list[Tag], str]]


def _tables(blocks: list[Tag]) -> list[Tag]:
    return [b for b in blocks if b.name == "table"]


# L2. Grid expansion


def test_grid_is_rectangular(T: ModuleType, blocks_by_doc: BlocksByDoc) -> None:
    """The expanded grid is always rectangular.

    Eighty of 1,200 source tables are ragged. Padding them here prevents L3
    column deletion from raising IndexError.
    """
    need(T, "to_grid")
    for doc, (_soup, blocks, _raw) in blocks_by_doc.items():
        for t in _tables(blocks):
            grid = T.to_grid(t)
            assert len({len(r) for r in grid}) <= 1, f"{doc}: row widths differ"


def test_rowspan_carries_down_without_duplicating_text(T: ModuleType) -> None:
    """A rowspan occupies its full shape but keeps text only at top-left.

    Replication would count numbers twice because value cells use spans.
    """
    need(T, "to_grid")
    html = """<table>
      <tr><td rowspan="2">A</td><td>b1</td></tr>
      <tr><td>b2</td></tr>
    </table>"""
    grid = T.to_grid(BeautifulSoup(html, "html.parser").find("table"))
    assert grid == [["A", "b1"], ["", "b2"]]


def test_colspan_keeps_text_in_first_cell_only(T: ModuleType) -> None:
    """A colspan reserves its full width without replicating cell text."""
    need(T, "to_grid")
    html = '<table><tr><td colspan="3">wide</td><td>x</td></tr></table>'
    grid = T.to_grid(BeautifulSoup(html, "html.parser").find("table"))
    assert grid == [["wide", "", "", "x"]]


# L3/L4. Layout collapse


@pytest.mark.parametrize("doc", sorted(TABLES))
def test_collapse_matches_golden(doc: str, T: ModuleType, blocks_by_doc: BlocksByDoc) -> None:
    """Table, empty-output, expanded-cell, and collapsed-cell counts match golden.

    A higher count means less layout was removed; a lower count means content
    was removed. The assertion catches regressions in both directions.
    """
    need(T, "to_grid", "drop_empty", "merge_unit_columns", "table_to_markdown")
    _soup, blocks, _raw = blocks_by_doc[doc]
    n_empty = before = after = 0
    for t in _tables(blocks):
        grid = T.to_grid(t)
        before += sum(len(r) for r in grid)
        after += sum(len(r) for r in T.merge_unit_columns(T.drop_empty(grid)))
        if not T.table_to_markdown(str(t)):
            n_empty += 1
    assert (len(_tables(blocks)), n_empty, before, after) == TABLES[doc]


def test_collapse_never_widens_a_table(T: ModuleType, blocks_by_doc: BlocksByDoc) -> None:
    """Collapse is monotonic and never adds columns."""
    need(T, "to_grid", "drop_empty", "merge_unit_columns")
    for doc, (_soup, blocks, _raw) in blocks_by_doc.items():
        for t in _tables(blocks):
            grid = T.to_grid(t)
            if not grid:
                continue
            out = T.merge_unit_columns(T.drop_empty(grid))
            if out:
                assert len(out[0]) <= len(grid[0]), f"{doc}: collapse added columns"


def test_unit_columns_are_folded_in_reading_order(T: ModuleType) -> None:
    """`$` precedes a value and `%` follows it, preserving reading order."""
    need(T, "merge_unit_columns")
    assert T.merge_unit_columns([["$", "1,234"]]) == [["$ 1,234"]]
    assert T.merge_unit_columns([["72.7", "%"]]) == [["72.7 %"]]


# L5. Header inference


def test_header_is_inferred_from_shape_not_from_th(
    T: ModuleType, blocks_by_doc: BlocksByDoc
) -> None:
    """The corpus has no `<th>` elements, so headers are inferred from shape.

    This assertion prevents an implementation from silently depending on a tag
    that never appears in the measured corpus.
    """
    for _doc, (soup, _blocks, _raw) in blocks_by_doc.items():
        assert soup.find("th") is None


def test_header_rows_are_the_leading_rows_with_an_empty_label_column(T: ModuleType) -> None:
    """Leading rows with an empty label column form the inferred header."""
    need(T, "split_header")
    grid = [["", "2024", "2023"], ["Revenue", "1", "2"]]
    assert T.split_header(grid) == ([["", "2024", "2023"]], [["Revenue", "1", "2"]])


def test_no_header_shape_returns_everything_as_body(T: ModuleType) -> None:
    """When no header shape exists, return the full grid for caller policy."""
    need(T, "split_header")
    grid = [["Revenue", "1"], ["Cost", "2"]]
    assert T.split_header(grid) == ([], grid)


# L6/L7. Serialization and entry point


def test_income_statement_renders_as_expected(T: ModuleType, blocks_by_doc: BlocksByDoc) -> None:
    """The NVDA-FY2024 income table collapses from 12 physical to 3 logical columns.

    This is the representative full-output golden, including the multi-row
    header merge of "Year Ended" and "Jan 28, 2024".
    """
    need(T, "table_to_markdown")
    _soup, blocks, _raw = blocks_by_doc["NVDA-FY2024"]
    for t in _tables(blocks):
        text = t.get_text(" ", strip=True)
        if "Revenue" in text and "Gross profit" in text:
            md = T.table_to_markdown(str(t))
            assert md == NVDA_FY2024_INCOME_MD
            return
    pytest.fail("NVDA-FY2024 income statement table was not found")


def test_parenthesized_negatives_survive_verbatim(
    T: ModuleType, blocks_by_doc: BlocksByDoc
) -> None:
    """Keep `(0.4)` verbatim instead of changing it to `-0.4`.

    Citations must match the filing, and ingestion-time normalization is
    irreversible. Query-time normalization remains possible.
    """
    need(T, "table_to_markdown")
    _soup, blocks, _raw = blocks_by_doc["NVDA-FY2024"]
    for t in _tables(blocks):
        text = t.get_text(" ", strip=True)
        if "Revenue" in text and "Gross profit" in text:
            md = T.table_to_markdown(str(t))
            assert "(0.4)" in md and "-0.4" not in md
            return
    pytest.fail("NVDA-FY2024 income statement table was not found")


def test_markdown_rows_all_have_the_same_width(T: ModuleType, blocks_by_doc: BlocksByDoc) -> None:
    """Every row has the same pipe count so the markdown table is renderable."""
    need(T, "table_to_markdown")
    for doc, (_soup, blocks, _raw) in blocks_by_doc.items():
        for t in _tables(blocks):
            md = T.table_to_markdown(str(t))
            if not md:
                continue
            widths = {line.count("|") for line in md.splitlines()}
            assert len(widths) == 1, f"{doc}: markdown row widths differ: {widths}"


def test_degenerate_input_never_raises(T: ModuleType) -> None:
    """Empty input, missing tables, and empty rows never raise."""
    need(T, "table_to_markdown")
    assert T.table_to_markdown(None) == ""
    assert T.table_to_markdown("") == ""
    assert T.table_to_markdown("<p>not a table</p>") == ""
    assert T.table_to_markdown("<table></table>") == ""
    assert T.table_to_markdown("<table><tr><td></td></tr></table>") == ""


def test_cell_pipes_are_escaped(T: ModuleType) -> None:
    """A pipe inside a cell is escaped instead of creating a new column."""
    need(T, "table_to_markdown")
    md = T.table_to_markdown("<table><tr><td>a|b</td><td>c</td></tr></table>")
    assert r"a\|b" in md
