from types import ModuleType

import pytest

XREF_TABLE_HTML = """
<table id="xref">
  <tr><td>Item 1.</td><td>Business</td><td>5-10</td></tr>
  <tr><td>Item 1A.</td><td>Risk Factors</td><td>11-18</td></tr>
  <tr><td>Item 7.</td><td>Management Discussion</td><td>19-44</td></tr>
  <tr><td>Item 8.</td><td>Financial Statements</td><td>45-90</td></tr>
  <tr><td>Item 16.</td><td>Form 10-K Summary</td><td>Not applicable</td></tr>
  <tr><td>Signatures</td><td>125</td></tr>
</table>
"""

TOC_TABLE_HTML = """
<table id="toc">
  <tr><th>Section</th><th>Page</th></tr>
  <tr><td>Business</td><td>5</td></tr>
  <tr><td>Risk Factors</td><td>11</td></tr>
  <tr><td>Management Discussion</td><td>19</td></tr>
  <tr><td>Financial Statements</td><td>45</td></tr>
  <tr><td>Controls</td><td>91</td></tr>
  <tr><td>Other Information</td><td>95</td></tr>
  <tr><td>Directors</td><td>100</td></tr>
  <tr><td>Compensation</td><td>105</td></tr>
  <tr><td>Ownership</td><td>110</td></tr>
  <tr><td>Exhibits</td><td>120</td></tr>
</table>
"""


def _soup(xref_module: ModuleType, html: str):
    return xref_module.BeautifulSoup(f"<html><body>{html}</body></html>", "html.parser")


def _table(xref_module: ModuleType, rows: str):
    return _soup(xref_module, f"<table>{rows}</table>").find("table")


def test_find_tables_detects_xref_and_toc_tables(xref_module: ModuleType) -> None:
    """Require both the SEC Item index and company TOC for xref segmentation.

    Missing either table makes the strategy fall back to undefined.
    """
    soup = _soup(xref_module, XREF_TABLE_HTML + TOC_TABLE_HTML)

    xref_table, toc_table = xref_module.find_tables(soup)

    assert xref_table is not None
    assert xref_table.get("id") == "xref"
    assert toc_table is not None
    assert toc_table.get("id") == "toc"


def test_parse_xref_reads_items_statuses_and_page_spans(xref_module: ModuleType) -> None:
    """Stop a closed Item from absorbing later indented rows.

    Otherwise the trailing Signatures row can attach page 125 to an Item declared
    Not applicable.
    """
    table = _soup(xref_module, XREF_TABLE_HTML).find("table")

    entries = xref_module.parse_xref(table)

    by_item = {entry.item: entry for entry in entries}
    assert by_item["1A"].spans == [(11, 18)]
    assert by_item["7"].status == "parsed"
    assert by_item["16"].status == "empty_disclosure"
    assert by_item["16"].spans == []


def test_parse_xref_reads_only_the_third_item_cell_as_a_value(
    xref_module: ModuleType,
) -> None:
    """Read only the third Item-row cell as a value.

    Reading the second cell as a page would turn the title "Form 10-K Summary" into
    the false page number 10.
    """
    table = _table(
        xref_module,
        """
        <tr><td>Item 7.</td><td>Form 10-K Summary</td></tr>
        <tr><td>Management Discussion</td><td>19-44</td></tr>
        """,
    )

    entry = xref_module.parse_xref(table)[0]

    assert entry.spans == [(19, 44)]
    assert (10, 10) not in entry.spans


def test_parse_xref_uses_page_spans_as_the_final_status(xref_module: ModuleType) -> None:
    """Use page spans as the final Item status decision.

    A child-row reference marker must not override real body pages and incorrectly
    remove the Item from assignment candidates.
    """
    table = _table(
        xref_module,
        """
        <tr><td>Item 7.</td><td>Management Discussion</td></tr>
        <tr><td>Off balance sheet arrangements</td><td>(a)</td></tr>
        <tr><td>Results of operations</td><td>19-44</td></tr>
        <tr><td>(a) Incorporated by reference from the proxy statement</td></tr>
        """,
    )

    entry = xref_module.parse_xref(table)[0]

    assert entry.spans == [(19, 44)]
    assert entry.status == "parsed"
    assert entry.reference_source == "Incorporated by reference from the proxy statement"


def test_parse_xref_closes_after_terminal_continuation_value(
    xref_module: ModuleType,
) -> None:
    """Stop a terminal continuation from absorbing a later Signatures row."""
    table = _table(
        xref_module,
        """
        <tr><td>Item 16.</td><td>Form 10-K Summary</td></tr>
        <tr><td>Summary</td><td>Not applicable</td></tr>
        <tr><td>Signatures</td><td>125</td></tr>
        """,
    )

    entry = xref_module.parse_xref(table)[0]

    assert entry.status == "empty_disclosure"
    assert entry.spans == []


def test_parse_xref_collects_multiple_page_continuations(xref_module: ModuleType) -> None:
    """Keep every page-bearing child row for an Item with several narrative ranges."""
    table = _table(
        xref_module,
        """
        <tr><td>Item 7.</td><td>Management Discussion</td></tr>
        <tr><td>Results of operations</td><td>Pages 5-6, 19-44</td></tr>
        <tr><td>Liquidity</td><td>Pages 42-47</td></tr>
        """,
    )

    entry = xref_module.parse_xref(table)[0]

    assert entry.spans == [(5, 6), (19, 44), (42, 47)]


def test_parse_xref_accepts_page_only_continuation(xref_module: ModuleType) -> None:
    """Read a page value that remains after empty continuation cells are stripped."""
    table = _table(
        xref_module,
        """
        <tr><td>Item 8.</td><td>Financial Statements</td></tr>
        <tr><td></td><td></td><td>70-108</td></tr>
        """,
    )

    entry = xref_module.parse_xref(table)[0]

    assert entry.status == "parsed"
    assert entry.spans == [(70, 108)]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("53–67", [(53, 67)]),
        ("53—67", [(53, 67)]),
        ("19-44 and 47-51", [(19, 44), (47, 51)]),
        ("19 44", [(19, 19), (44, 44)]),
        ("1 05", [(105, 105)]),
        ("1 05–1 08", [(105, 108)]),
        ("88 -86", [(86, 88)]),
    ],
)
def test_spans_handles_range_typography_and_broken_digits(
    xref_module: ModuleType,
    text: str,
    expected: list[tuple[int, int]],
) -> None:
    """Parse each range independently while preserving measured split digits."""
    assert xref_module._spans(text) == expected


def test_covering_returns_the_narrowest_matching_span(xref_module: ModuleType) -> None:
    """Return the narrowest span covering a page.

    Overlapping ranges are valid. Span width is the second tie-breaker after title
    overlap when one page belongs to several candidate Items.
    """
    entry = xref_module.XrefEntry(
        item="7",
        reported_title="Management Discussion",
        spans=[(5, 6), (19, 44), (40, 41)],
    )

    assert entry.covering(41) == (40, 41)
    assert entry.covering(20) == (19, 44)
    assert entry.covering(100) is None


def test_parse_toc_returns_ordered_title_page_pairs(xref_module: ModuleType) -> None:
    """Preserve TOC document order for the forward-only section cursor."""
    table = _soup(xref_module, TOC_TABLE_HTML).find("table")

    rows = xref_module.parse_toc(table)

    assert rows[:3] == [
        ("Business", 5),
        ("Risk Factors", 11),
        ("Management Discussion", 19),
    ]
    assert len(rows) == 10


def test_in_tables_returns_only_nested_block_indexes(xref_module: ModuleType) -> None:
    """Exclude metadata titles inside TOC and xref tables from narrative matching.

    Their block indexes must be skipped so the join selects the matching title in the
    filing body.
    """
    soup = _soup(
        xref_module,
        """
        <table id="toc"><tr><td><p>Risk Factors</p></td></tr></table>
        <p>Risk Factors</p>
        """,
    )
    table = soup.find("table")
    blocks = soup.find_all("p")

    assert xref_module.in_tables(blocks, [table, None]) == {0}


def test_in_tables_uses_identity_for_structurally_equal_tables(
    xref_module: ModuleType,
) -> None:
    """Do not skip a body block merely because its parent table has equal markup."""
    soup = _soup(
        xref_module,
        """
        <table><tr><td><p>Repeated title</p></td></tr></table>
        <table><tr><td><p>Repeated title</p></td></tr></table>
        """,
    )
    tables = soup.find_all("table")
    blocks = soup.find_all("p")

    assert tables[0] == tables[1]
    assert tables[0] is not tables[1]
    assert xref_module.in_tables(blocks, [tables[0]]) == {0}


def test_locate_sections_joins_toc_titles_to_body_blocks(xref_module: ModuleType) -> None:
    """Join TOC titles to body blocks in document order.

    Exact normalized titles are preferred, with word-set equality as a fallback for
    small article differences such as "the Consolidated" versus "Consolidated".
    """
    soup = _soup(
        xref_module,
        """
        <p>Cover</p>
        <p>Business</p>
        <p>Body text</p>
        <p>Notes to Consolidated Financial Statements</p>
        """,
    )
    blocks = soup.find_all("p")
    toc = [
        ("Business", 5),
        ("Notes to the Consolidated Financial Statements", 45),
    ]

    located = xref_module.locate_sections(blocks, toc, set())

    assert located == [
        ("Business", 5, 1),
        ("Notes to the Consolidated Financial Statements", 45, 3),
    ]


def test_item_for_page_prefers_title_overlap_then_narrower_span(
    xref_module: ModuleType,
) -> None:
    """Prefer title overlap, then span width, then the shorter Item number.

    Entries incorporated by reference are not body-assignment candidates.
    """
    entries = [
        xref_module.XrefEntry("7", "Management Discussion", [(19, 44)]),
        xref_module.XrefEntry("8", "Financial Statements", [(40, 41)]),
        xref_module.XrefEntry("10", "Directors", [(40, 50)], status="incorporated_by_reference"),
    ]

    assert xref_module.item_for_page(41, entries, "Financial Statements") == "8"
    assert xref_module.item_for_page(20, entries) == "7"
    assert xref_module.item_for_page(100, entries) is None


def test_assign_items_maps_located_blocks_to_items(xref_module: ModuleType) -> None:
    """Map located block indexes to Items for direct use by segmentation."""
    entries = [
        xref_module.XrefEntry("1", "Business", [(5, 10)]),
        xref_module.XrefEntry("1A", "Risk Factors", [(11, 18)]),
    ]
    located = [("Business", 5, 2), ("Risk Factors", 11, 8)]

    assert xref_module.assign_items(located, entries) == {2: "1", 8: "1A"}


def test_page_map_accepts_sequential_spaced_footers(xref_module: ModuleType) -> None:
    """Accept gradual, spaced page footers and reject isolated financial numbers."""
    values = ["1", "a", "b", "c", "d", "e", "2", "f", "100", "g", "h", "i", "3"]
    soup = _soup(xref_module, "".join(f"<p>{value}</p>" for value in values))

    assert xref_module.page_map(soup.find_all("p")) == [(0, 1), (6, 2), (12, 3)]


def test_page_map_seeds_from_a_confirmed_run_above_page_three(
    xref_module: ModuleType,
) -> None:
    """Seed a footer chain from three spaced candidates when early pages are absent."""
    values = ["4", *["body"] * 5, "5", *["body"] * 5, "6"]
    soup = _soup(xref_module, "".join(f"<p>{value}</p>" for value in values))

    assert xref_module.page_map(soup.find_all("p")) == [(0, 4), (6, 5), (12, 6)]


def test_page_map_recovers_after_a_large_footer_gap(xref_module: ModuleType) -> None:
    """Resynchronize on a confirmed run after four or more printed pages are missed."""
    values = [
        "1",
        *["body"] * 5,
        "2",
        *["body"] * 5,
        "7",
        *["body"] * 5,
        "8",
        *["body"] * 5,
        "9",
    ]
    soup = _soup(xref_module, "".join(f"<p>{value}</p>" for value in values))

    assert xref_module.page_map(soup.find_all("p")) == [
        (0, 1),
        (6, 2),
        (12, 7),
        (18, 8),
        (24, 9),
    ]


@pytest.mark.parametrize("assigned", [set(), {"3"}])
def test_find_missing_searches_only_unassigned_xref_titles(
    xref_module: ModuleType, assigned: set[str]
) -> None:
    """Find body headings omitted from the TOC without re-emitting assigned Items.

    The second sweep recovers Items such as Legal Proceedings whose heading exists in
    the body but not in the company TOC.
    """
    soup = _soup(xref_module, "<p>Business</p><p>Legal Proceedings</p><p>Other text</p>")
    entries = [
        xref_module.XrefEntry("1", "Business", [(5, 10)]),
        xref_module.XrefEntry("3", "Legal Proceedings", [(12, 12)]),
    ]

    found = xref_module.find_missing(soup.find_all("p"), entries, assigned | {"1"}, set())

    expected = [] if "3" in assigned else [("Legal Proceedings", 12, 1)]
    assert found == expected
