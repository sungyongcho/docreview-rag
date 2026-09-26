"""HTML table detection, span expansion, and markdown rendering."""

from bs4 import BeautifulSoup, Tag

from app.ingestion.parsing.tables import (
    MAX_SPAN,
    is_unit_caption,
    merge_unit_columns,
    place_cells,
    split_header,
    structured_table,
)


def _table(html: str) -> Tag:
    table = BeautifulSoup(html, "html.parser").find("table")
    assert isinstance(table, Tag)
    return table


# Grid expansion


def test_grid_is_rectangular() -> None:
    """Pad ragged source rows to the widest expanded row."""
    table = _table("<table><tr><td>A</td><td>B</td></tr><tr><td>C</td></tr></table>")
    assert place_cells(table)[0] == [["A", "B"], ["C", ""]]


def test_rows_inside_a_row_group_are_found() -> None:
    """Read rows through an explicit thead, tbody, or tfoot wrapper."""
    table = _table("<table><tbody><tr><td>Revenue</td><td>100</td></tr></tbody></table>")
    assert place_cells(table)[0] == [["Revenue", "100"]]


def test_rowspan_carries_down_without_duplicating_text() -> None:
    """Keep rowspan text at its anchor and leave covered cells empty."""
    table = _table(
        """<table>
        <tr><td rowspan="2">A</td><td>b1</td></tr>
        <tr><td>b2</td></tr>
        </table>"""
    )
    assert place_cells(table)[0] == [["A", "b1"], ["", "b2"]]


def test_colspan_keeps_text_in_first_cell_only() -> None:
    """Reserve colspan width without replicating the cell text."""
    table = _table('<table><tr><td colspan="3">wide</td><td>x</td></tr></table>')
    assert place_cells(table)[0] == [["wide", "", "", "x"]]


def test_right_aligned_colspan_lands_in_its_last_column() -> None:
    """Place a right-aligned spanned value where the filing renders it."""
    table = _table(
        """<table>
        <tr><td colspan="2" style="text-align:right">16,621</td></tr>
        <tr><td>$</td><td style="text-align:right">60,922</td></tr>
        </table>"""
    )
    assert place_cells(table)[0] == [["", "16,621"], ["$", "60,922"]]


def test_centered_colspan_labels_every_column_it_covers() -> None:
    """Copy a centered spanning label onto each column that holds content."""
    table = _table(
        """<table>
        <tr><td colspan="2" style="text-align:center">Year Ended</td></tr>
        <tr><td>100</td><td>90</td></tr>
        </table>"""
    )
    assert place_cells(table)[0] == [["Year Ended", "Year Ended"], ["100", "90"]]


def test_invalid_spans_default_to_one() -> None:
    """Treat missing, invalid, and non-positive spans as one cell."""
    table = _table('<table><tr><td colspan="invalid">A</td><td rowspan="0">B</td></tr></table>')
    assert place_cells(table)[0] == [["A", "B"]]


def test_oversized_spans_are_clamped() -> None:
    """Bound a malformed span so one cell cannot allocate an unbounded grid."""
    table = _table('<table><tr><td colspan="200000">A</td></tr></table>')
    assert len(place_cells(table)[0][0]) == MAX_SPAN


def test_cell_text_keeps_words_the_filing_split_across_nodes() -> None:
    """Join inline fragments verbatim and separate only block-level children."""
    table = _table(
        """<table><tr>
        <td><span>P</span><span>art I</span></td>
        <td>(<span>257</span>)</td>
        <td><div>Amortized</div><div>Cost</div></td>
        </tr></table>"""
    )
    assert place_cells(table)[0] == [["Part I", "(257)", "Amortized Cost"]]


# Layout collapse


def test_collapse_tolerates_ragged_rows() -> None:
    """Read a missing cell as empty instead of raising or dropping content."""
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
    markdown = structured_table(
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
    ).render()
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
    html = (
        "<table><tr><td>Total revenue</td><td>63,574</td><td>79,699</td></tr>"
        "<tr><td>Total income</td><td>2,334</td><td>19,456</td></tr></table>"
    )
    assert structured_table(html).render().splitlines()[0] == "|  |  |  |"


def test_parenthesized_negatives_survive_verbatim() -> None:
    """Keep filing-style parenthesized negatives unchanged."""
    html = """<table>
    <tr><td>Metric</td><td>Value</td></tr>
    <tr><td>Expense</td><td>(0.4)</td></tr>
    </table>"""
    markdown = structured_table(html).render()
    assert "(0.4)" in markdown
    assert "-0.4" not in markdown


def test_degenerate_input_never_raises() -> None:
    """Return empty output for missing or content-free tables."""
    assert structured_table(None).render() == ""
    assert structured_table("").render() == ""
    assert structured_table("<p>not a table</p>").render() == ""
    assert structured_table("<table></table>").render() == ""
    assert structured_table("<table><tr><td></td></tr></table>").render() == ""


def test_a_parsed_node_renders_like_its_source_fragment() -> None:
    """Accept a parsed table and produce what the same fragment produces."""
    html = "<table><tr><td>Interest expense</td><td>(<span>257</span>)</td></tr></table>"
    assert structured_table(_table(html)).render() == structured_table(html).render()
    assert "(257)" in structured_table(_table(html)).render()


def test_cell_pipes_are_escaped() -> None:
    """Escape cell pipes instead of creating extra markdown columns."""
    markdown = structured_table("<table><tr><td>a|b</td><td>c</td></tr></table>").render()
    assert r"a\|b" in markdown


def test_an_escaped_pipe_keeps_its_backslash() -> None:
    """Keep a literal backslash distinguishable from the escape it looks like."""
    escaped = structured_table(r"<table><tr><td>a\|b</td><td>c</td></tr></table>").render()
    plain = structured_table("<table><tr><td>a|b</td><td>c</td></tr></table>").render()
    assert escaped != plain


# DART cell vocabulary and Korean unit conventions


def test_te_and_tu_cells_expand_like_td() -> None:
    """Collect DART's TE and TU cell elements as ordinary grid cells."""
    table = _table("<table><tr><te>매출액</te><tu>2024년</tu><td>300,870</td></tr></table>")
    assert place_cells(table)[0] == [["매출액", "2024년", "300,870"]]


def test_unit_caption_row_moves_ahead_of_the_table() -> None:
    """Lift an in-grid unit annotation out of header inference into a caption line."""
    markdown = structured_table(
        """<table>
          <tr><td colspan="3" align="right">(단위 : 백만원)</td></tr>
          <tr><td>구 분</td><td>제56기</td><td>제55기</td></tr>
          <tr><td>매출액</td><td>300,870,903</td><td>258,935,494</td></tr>
        </table>"""
    ).render()
    lines = markdown.splitlines()
    assert lines[0] == "(단위 : 백만원)"
    assert lines[1] == "| 구 분 | 제56기 | 제55기 |"
    assert "| 매출액 | 300,870,903 | 258,935,494 |" in lines


def test_caption_only_table_reports_captions_and_no_markdown() -> None:
    """A one-cell unit table renders no markdown but exposes its annotation."""
    html = "<table><tr><td>(단위 : 사)</td></tr></table>"

    assert structured_table(html).render() == ""
    assert structured_table(html).captions == ("(단위 : 사)",)


def test_is_unit_caption_accepts_only_a_whole_annotation() -> None:
    """is_unit_caption matches a lone unit annotation, tolerating outer whitespace."""
    assert is_unit_caption("(단위 : 백만원)")
    assert is_unit_caption("  (단위: 원)  \n")
    assert not is_unit_caption("당기 매출은 (단위 : 백만원) 기준으로 작성되었다")
    assert not is_unit_caption("매출액")
    assert not is_unit_caption("")


def test_won_sign_column_merges_onto_its_value() -> None:
    """A ₩-only column folds into the value on its right, like the dollar sign."""
    markdown = structured_table(
        """<table>
          <tr><td>구 분</td><td></td><td>금액</td></tr>
          <tr><td>매출액</td><td>₩</td><td>300,870</td></tr>
          <tr><td>영업이익</td><td>₩</td><td>32,725</td></tr>
        </table>"""
    ).render()
    assert "| 매출액 | ₩ 300,870 |" in markdown
    assert "| 영업이익 | ₩ 32,725 |" in markdown


def test_triangle_negative_reads_as_a_value_not_a_label() -> None:
    """A Korean triangle negative in a leading row does not become a header row."""
    header, body = split_header([["구 분", "제56기"], ["순손실", "△1,234"], ["매출", "5,678"]])
    assert header == [["구 분", "제56기"]]
    assert ["순손실", "△1,234"] in body


def test_date_and_unit_caption_tables_preserve_all_annotation_text():
    """Recognize explicit mixed annotations, including date and unit on separate rows."""
    html = (
        "<table><tr><td>(기준일 : 2024년 12월 31일 )</td></tr>"
        "<tr><td>(단위 : 백만원)</td></tr></table>"
    )
    table = structured_table(html)
    assert table.rows == table.headers == ()
    assert table.captions == ("(기준일 : 2024년 12월 31일 )", "(단위 : 백만원)")
    assert {(cell.row, cell.column, cell.text) for cell in table.caption_cells} == {
        (0, 0, "(기준일 : 2024년 12월 31일 )"),
        (1, 0, "(단위 : 백만원)"),
    }


def test_numeric_tables_are_not_reclassified_as_caption_blocks():
    """A unit or date label next to a value remains data rather than pending context."""
    html = (
        "<table><tr><td>(기준일 : 2024년 12월 31일 )</td><td>123</td></tr>"
        "<tr><td>(단위 : 백만원)</td><td>456</td></tr></table>"
    )
    table = structured_table(html)
    assert table.captions == table.caption_cells == ()
    assert "123" in table.render() and "456" in table.render()
    assert "(단위 : 백만원)" in table.render()
