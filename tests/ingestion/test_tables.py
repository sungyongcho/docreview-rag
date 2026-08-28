from bs4 import BeautifulSoup, Tag

from app.ingestion.tables import (
    MAX_SPAN,
    drop_empty,
    merge_unit_columns,
    split_header,
    table_to_markdown,
    to_grid,
    to_markdown,
)


def _table(html: str) -> Tag:
    table = BeautifulSoup(html, "html.parser").find("table")
    assert isinstance(table, Tag)
    return table


# Grid expansion


def test_grid_is_rectangular() -> None:
    """Pad ragged source rows to the widest expanded row."""
    table = _table("<table><tr><td>A</td><td>B</td></tr><tr><td>C</td></tr></table>")
    assert to_grid(table) == [["A", "B"], ["C", ""]]


def test_rows_inside_a_row_group_are_found() -> None:
    """Read rows through an explicit thead, tbody, or tfoot wrapper."""
    table = _table("<table><tbody><tr><td>Revenue</td><td>100</td></tr></tbody></table>")
    assert to_grid(table) == [["Revenue", "100"]]


def test_rowspan_carries_down_without_duplicating_text() -> None:
    """Keep rowspan text at its anchor and leave covered cells empty."""
    table = _table(
        """<table>
        <tr><td rowspan="2">A</td><td>b1</td></tr>
        <tr><td>b2</td></tr>
        </table>"""
    )
    assert to_grid(table) == [["A", "b1"], ["", "b2"]]


def test_colspan_keeps_text_in_first_cell_only() -> None:
    """Reserve colspan width without replicating the cell text."""
    table = _table('<table><tr><td colspan="3">wide</td><td>x</td></tr></table>')
    assert to_grid(table) == [["wide", "", "", "x"]]


def test_right_aligned_colspan_lands_in_its_last_column() -> None:
    """Place a right-aligned spanned value where the filing renders it."""
    table = _table(
        """<table>
        <tr><td colspan="2" style="text-align:right">16,621</td></tr>
        <tr><td>$</td><td style="text-align:right">60,922</td></tr>
        </table>"""
    )
    assert to_grid(table) == [["", "16,621"], ["$", "60,922"]]


def test_centered_colspan_labels_every_column_it_covers() -> None:
    """Copy a centered spanning label onto each column that holds content."""
    table = _table(
        """<table>
        <tr><td colspan="2" style="text-align:center">Year Ended</td></tr>
        <tr><td>100</td><td>90</td></tr>
        </table>"""
    )
    assert to_grid(table) == [["Year Ended", "Year Ended"], ["100", "90"]]


def test_invalid_spans_default_to_one() -> None:
    """Treat missing, invalid, and non-positive spans as one cell."""
    table = _table('<table><tr><td colspan="invalid">A</td><td rowspan="0">B</td></tr></table>')
    assert to_grid(table) == [["A", "B"]]


def test_oversized_spans_are_clamped() -> None:
    """Bound a malformed span so one cell cannot allocate an unbounded grid."""
    table = _table('<table><tr><td colspan="200000">A</td></tr></table>')
    assert len(to_grid(table)[0]) == MAX_SPAN


def test_cell_text_keeps_words_the_filing_split_across_nodes() -> None:
    """Join inline fragments verbatim and separate only block-level children."""
    table = _table(
        """<table><tr>
        <td><span>P</span><span>art I</span></td>
        <td>(<span>257</span>)</td>
        <td><div>Amortized</div><div>Cost</div></td>
        </tr></table>"""
    )
    assert to_grid(table) == [["Part I", "(257)", "Amortized Cost"]]


# Layout collapse


def test_empty_rows_and_columns_are_removed() -> None:
    """Remove axes that contain no non-empty values."""
    grid = [["", "", ""], ["", "Revenue", "100"], ["", "", ""]]
    assert drop_empty(grid) == [["Revenue", "100"]]


def test_collapse_tolerates_ragged_rows() -> None:
    """Read a missing cell as empty instead of raising or dropping content."""
    assert drop_empty([["a"], ["b", "c"]]) == [["a", ""], ["b", "c"]]
    assert merge_unit_columns([["a", "b", "c"], ["d"]]) == [["a", "b", "c"], ["d", "", ""]]


def test_unit_columns_are_folded_in_reading_order() -> None:
    """Place currency before values and percentages after values."""
    assert merge_unit_columns([["$", "1,234"]]) == [["$ 1,234"]]
    assert merge_unit_columns([["72.7", "%"]]) == [["72.7 %"]]


def test_mixed_symbols_keep_their_own_reading_order() -> None:
    """Fold each marker by its own symbol, not by one direction per column."""
    assert merge_unit_columns([["$", "100"], ["%", "5"]]) == [["$ 100"], ["5 %"]]


def test_a_marker_without_a_value_is_not_duplicated() -> None:
    """Leave a lone symbol alone when the column it folds into is empty."""
    assert merge_unit_columns([["$", ""]]) == [["$"]]


def test_a_header_label_does_not_disable_the_unit_merge() -> None:
    """Decide unit columns from body rows so a header label above them is ignored."""
    grid = [["Period", "Average Price Paid per Share", ""], ["Q4", "$", "464.39"]]
    assert merge_unit_columns(grid) == [
        ["Period", "Average Price Paid per Share"],
        ["Q4", "$ 464.39"],
    ]


# Header inference


def test_header_rows_start_with_an_empty_label_column() -> None:
    """Split consecutive leading header-shaped rows from the body."""
    grid = [["", "2024", "2023"], ["Revenue", "1", "2"]]
    assert split_header(grid) == ([grid[0]], [grid[1]])


def test_a_labelled_column_title_row_is_still_a_header() -> None:
    """Accept one leading labelled row as a header while it carries no number."""
    grid = [["Years Ended", "2024", "2023"], ["Revenue", "1", "2"]]
    assert split_header(grid) == ([grid[0]], [grid[1]])


def test_no_header_shape_returns_everything_as_body() -> None:
    """Return the full grid as body when no inferred header exists."""
    grid = [["Revenue", "1"], ["Cost", "2"]]
    assert split_header(grid) == ([], grid)


def test_returned_header_rows_do_not_alias_the_input() -> None:
    """Return copies so mutating a result cannot corrupt the caller's grid."""
    grid = [["", "2024"], ["Revenue", "1"]]
    header, _body = split_header(grid)
    header[0][1] = "mutated"
    assert grid == [["", "2024"], ["Revenue", "1"]]


# Serialization and entry point


def test_multirow_header_is_merged_per_column() -> None:
    """Preserve multirow date context in each markdown header cell."""
    markdown = table_to_markdown(
        """<table>
        <tr><td></td><td colspan="4" style="text-align:center">Year Ended</td></tr>
        <tr><td></td>
            <td colspan="2" style="text-align:center">2024</td>
            <td colspan="2" style="text-align:center">2023</td></tr>
        <tr><td>Revenue</td>
            <td>$</td><td style="text-align:right">100</td>
            <td>$</td><td style="text-align:right">90</td></tr>
        <tr><td>Cost</td>
            <td colspan="2" style="text-align:right">(40)</td>
            <td colspan="2" style="text-align:right">(30)</td></tr>
        </table>"""
    )
    assert markdown == "\n".join(
        [
            "|  | Year Ended 2024 | Year Ended 2023 |",
            "| --- | --- | --- |",
            "| Revenue | $ 100 | $ 90 |",
            "| Cost | (40) | (30) |",
        ]
    )


def test_a_data_row_is_never_promoted_into_the_header() -> None:
    """Leave the header blank instead of labelling columns with a data row."""
    grid = [["Total revenue", "63,574", "79,699"], ["Total income", "2,334", "19,456"]]
    assert to_markdown(grid).splitlines()[0] == "|  |  |  |"


def test_rows_wider_than_the_header_keep_every_cell() -> None:
    """Size the table by its widest row so no value is truncated."""
    assert to_markdown([["", "2024"], ["Revenue", "100", "90"]]) == "\n".join(
        ["|  | 2024 |  |", "| --- | --- | --- |", "| Revenue | 100 | 90 |"]
    )


def test_parenthesized_negatives_survive_verbatim() -> None:
    """Keep filing-style parenthesized negatives unchanged."""
    html = """<table>
    <tr><td>Metric</td><td>Value</td></tr>
    <tr><td>Expense</td><td>(0.4)</td></tr>
    </table>"""
    markdown = table_to_markdown(html)
    assert "(0.4)" in markdown
    assert "-0.4" not in markdown


def test_markdown_rows_have_the_same_width() -> None:
    """Serialize every markdown row with the same pipe count."""
    html = """<table>
    <tr><td></td><td>2024</td><td>2023</td></tr>
    <tr><td>Revenue</td><td>100</td><td>90</td></tr>
    </table>"""
    widths = {line.count("|") for line in table_to_markdown(html).splitlines()}
    assert len(widths) == 1


def test_degenerate_input_never_raises() -> None:
    """Return empty output for missing or content-free tables."""
    assert table_to_markdown(None) == ""
    assert table_to_markdown("") == ""
    assert table_to_markdown("<p>not a table</p>") == ""
    assert table_to_markdown("<table></table>") == ""
    assert table_to_markdown("<table><tr><td></td></tr></table>") == ""


def test_a_parsed_node_renders_like_its_source_fragment() -> None:
    """Accept a parsed table and produce what the same fragment produces."""
    html = "<table><tr><td>Interest expense</td><td>(<span>257</span>)</td></tr></table>"
    assert table_to_markdown(_table(html)) == table_to_markdown(html)
    assert "(257)" in table_to_markdown(_table(html))


def test_cell_pipes_are_escaped() -> None:
    """Escape cell pipes instead of creating extra markdown columns."""
    markdown = table_to_markdown("<table><tr><td>a|b</td><td>c</td></tr></table>")
    assert r"a\|b" in markdown


def test_an_escaped_pipe_keeps_its_backslash() -> None:
    """Keep a literal backslash distinguishable from the escape it looks like."""
    escaped = table_to_markdown(r"<table><tr><td>a\|b</td><td>c</td></tr></table>")
    plain = table_to_markdown("<table><tr><td>a|b</td><td>c</td></tr></table>")
    assert escaped != plain
