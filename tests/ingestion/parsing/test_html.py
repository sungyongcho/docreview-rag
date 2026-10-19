"""Source-anchored block extraction from a raw filing."""

import hashlib
from types import ModuleType

import pytest

from tests.ingestion.chunk.support import source_text, tokens


def test_leaf_blocks_returns_expected_block_counts(parser_module: ModuleType) -> None:
    """leaf_blocks returns leaf text blocks and keeps a table as one block."""
    html = """
    <html><body>
      <div><p>First paragraph</p></div>
      <div>Second paragraph</div>
      <table><tr><td>Revenue</td><td>100</td></tr></table>
    </body></html>
    """

    soup = parser_module.normalize(html)
    blocks = parser_module.leaf_blocks(soup)

    assert len(blocks) == 3
    assert sum(block.name == "table" for block in blocks) == 1
    assert len(soup.find_all("table")) == 1


def test_normalize_drops_ix_header_instead_of_unwrapping(parser_module: ModuleType) -> None:
    """normalize removes the non-rendered ix:header and all of its contents."""
    html = """
    <html><body>
      <ix:header><xbrli:context>machine-only context</xbrli:context></ix:header>
      <p>Visible filing text</p>
    </body></html>
    """

    soup = parser_module.normalize(html)

    assert soup.find("ix:header") is None
    assert "machine-only context" not in soup.get_text(" ", strip=True)
    assert "Visible filing text" in soup.get_text(" ", strip=True)


def test_normalize_preserves_ixbrl_numbers(parser_module: ModuleType) -> None:
    """normalize unwraps ix:* facts without deleting their financial values."""
    html = """
    <html><body>
      <div>Revenue <ix:nonFraction>26,974</ix:nonFraction> million</div>
    </body></html>
    """

    soup = parser_module.normalize(html)

    assert soup.find("ix:nonfraction") is None
    assert "26,974" in soup.get_text()


def test_leaf_blocks_groups_a_legacy_table_as_one_block(parser_module: ModuleType) -> None:
    """leaf_blocks does not split a numeric table into nested div blocks."""
    html = """
    <html><body>
      <table><tr>
        <td><div>Revenue</div></td><td><div>2024</div></td>
        <td><div>100</div></td><td><div>2023</div></td>
        <td><div>90</div></td><td><div>80</div></td>
      </tr></table>
    </body></html>
    """

    soup = parser_module.normalize(html)
    blocks = parser_module.leaf_blocks(soup)

    assert len(blocks) == 1
    assert blocks[0].name == "table"
    assert "Revenue" in blocks[0].get_text(" ", strip=True)


@pytest.mark.parametrize("spacers", [0, 20])
@pytest.mark.parametrize("cell_tag", ["td", "te"])
def test_financial_table_detection_ignores_empty_layout_cells(parser_module, spacers, cell_tag):
    """Keep SEC/DART financial grids when publishers insert empty spacer cells."""
    gap = "<td>&nbsp;</td>" * spacers
    html = (
        "<table><tr><td></td><td>2024</td><td>2023</td></tr>"
        f"<tr><td><div>Net revenue</div></td>{gap}<td>25,785</td><td>22,680</td></tr>"
        "</table>"
    )
    html = html.replace("<td>", f"<{cell_tag}>").replace("</td>", f"</{cell_tag}>")
    soup = parser_module.normalize(html)
    assert parser_module._is_data_table(soup.table)
    assert parser_module.leaf_blocks(soup) == [soup.table]


def test_layout_table_keeps_bare_cells_alongside_nested_paragraphs(parser_module):
    """Reject prose-heavy layout as data without dropping its unwrapped cells."""
    prose = "Business description with operating context. " * 10
    raw = (
        f"<table><tr><td><div>{prose}</div></td><td><span>2024</span></td>"
        "<td>2023</td><td>2022</td></tr>"
        "<tr><td>Revenue</td><td>$25,785</td><td>$22,680</td><td>$23,601</td></tr></table>"
    )
    soup = parser_module.normalize(raw)
    assert not parser_module._is_data_table(soup.table)
    blocks = parser_module.leaf_blocks(soup)
    assert [block.get_text(" ", strip=True) for block in blocks] == [
        prose.strip(),
        "2024",
        "2023",
        "2022",
        "Revenue",
        "$25,785",
        "$22,680",
        "$23,601",
    ]
    spans = parser_module.block_source_spans(blocks, parser_module.line_offsets(raw), len(raw))
    for block, (start, end) in zip(blocks, spans, strict=True):
        assert tokens(source_text(raw, start, end)) == tokens(block.get_text(" ", strip=True))


def test_nested_financial_table_keeps_surrounding_units_and_notes(parser_module):
    """Keep a layout wrapper's context and the inner grid's row/column identity."""
    html = (
        "<table><tr><td>Amounts in millions</td>" + "<td></td>" * 40 + "<td><table>"
        "<tr><td>Year</td><td>2024</td><td>2023</td></tr>"
        "<tr><td>Revenue</td><td>100</td><td>90</td></tr>"
        "<tr><td>Income</td><td>10</td><td>9</td></tr>"
        "</table></td><td>Unaudited</td></tr></table>"
    )
    soup = parser_module.normalize(html)
    outer, inner = soup.find_all("table")
    assert not parser_module._is_data_table(outer)
    assert parser_module._is_data_table(inner)
    blocks = parser_module.leaf_blocks(soup)
    assert [block.name for block in blocks] == ["td", "table", "td"]
    assert blocks[1] is inner
    assert blocks[0].get_text() == "Amounts in millions"
    assert blocks[2].get_text() == "Unaudited"


def test_mixed_layout_text_keeps_exact_positions_around_a_nested_grid(parser_module):
    """Retain inline units and notes without flattening or duplicating the grid."""
    raw = (
        "<table><tr><td>Amounts &amp; units in <b>millions</b>\n<table>"
        "<tr><td>Year</td><td>2024</td><td>2023</td></tr>"
        "<tr><td>Revenue</td><td>100</td><td>90</td></tr>"
        "<tr><td>Income</td><td>10</td><td>9</td></tr>"
        "</table><i>Un</i>audited<!-- not evidence --></td></tr></table>"
    )
    soup = parser_module.normalize(raw)
    blocks = parser_module.leaf_blocks(soup)
    assert [block.name for block in blocks] == ["span", "table", "span"]
    assert blocks[0].get_text(strip=True) == "Amounts & units in millions"
    assert blocks[2].get_text(strip=True) == "Unaudited"
    spans = parser_module.block_source_spans(blocks, parser_module.line_offsets(raw), len(raw))
    for block, (start, end) in zip(blocks, spans, strict=True):
        cited = parser_module.normalize(raw[start:end]).get_text()
        assert " ".join(cited.split()) == " ".join(block.get_text().split())


def test_decoded_source_preserves_crlf_for_source_offsets(
    parser_module: ModuleType,
    tmp_path,
) -> None:
    """Keep CRLF, Unicode offsets, and the source digest bound to exact bytes."""
    path = tmp_path / "crlf.html"
    source_bytes = "<html>\r\n<p>First</p>\r\n<p>café</p>\r\n</html>".encode()
    path.write_bytes(source_bytes)

    raw = path.read_bytes().decode("utf-8")
    soup = parser_module.normalize(raw)
    offsets = parser_module.line_offsets(raw)
    second = soup.find_all("p")[1]
    start = raw.index("café")
    end = start + len("café")

    assert "\r\n" in raw
    assert parser_module.source_pos(second, offsets) == raw.index("<p>café</p>")
    assert raw[start:end] == "café"
    assert parser_module.source_digest(raw) == hashlib.sha256(source_bytes).hexdigest()
    assert len(source_bytes) > len(raw)


def test_line_offsets_count_only_the_separator_htmlparser_counts(
    parser_module: ModuleType,
) -> None:
    """Treat a form feed as ordinary text, because HTMLParser does not end a line on it."""
    raw = "<p>a</p>\x0c<p>b</p>\n<p>c</p>"

    offsets = parser_module.line_offsets(raw)
    soup = parser_module.normalize(raw)
    third = soup.find_all("p")[2]
    start = parser_module.source_pos(third, offsets)

    assert offsets[:2] == [0, raw.index("\n") + 1]
    assert raw[start:] == "<p>c</p>"


def test_leaf_blocks_accept_a_registry_specific_block_vocabulary(
    parser_module: ModuleType,
) -> None:
    """Collect the block tags a caller names without changing the default vocabulary."""
    html = "<body><title>I. Heading</title><p>Body</p></body>"

    soup = parser_module.normalize(html)
    default_blocks = parser_module.leaf_blocks(soup)
    with_title = parser_module.leaf_blocks(soup, ("title", "p"))

    assert [block.name for block in default_blocks] == ["p"]
    assert [block.name for block in with_title] == ["title", "p"]


def test_all_body_blocks_have_valid_spans(corpus) -> None:
    """Require ordered, non-overlapping source spans for every parsed body block."""
    for document, (filing, raw) in corpus.items():
        for section in filing.sections:
            previous_end = -1
            for block in section.blocks:
                assert block.source_pos is not None, f"{document}: missing block start"
                assert block.end_pos is not None, f"{document}: missing block end"
                assert 0 <= block.source_pos < block.end_pos <= len(raw)
                assert block.source_pos >= previous_end, (
                    f"{document}: block overlaps the previous source span"
                )
                previous_end = block.end_pos


def test_filing_coordinates_are_bound_to_the_source_snapshot(
    corpus,
    parser_module: ModuleType,
) -> None:
    """Bind filing length and SHA-256 coordinates to the canonical source."""
    for filing, raw in corpus.values():
        assert filing.source_length == len(raw)
        assert filing.source_sha256 == parser_module.source_digest(raw)


def test_text_block_round_trip(corpus) -> None:
    """Keep each paragraph and heading grounded in its parser source slice."""
    for document, (filing, raw) in corpus.items():
        for section in filing.sections:
            for block in section.blocks:
                if block.kind == "table" or not block.text:
                    continue
                actual = tokens(source_text(raw, block.source_pos, block.end_pos))
                expected = tokens(block.text)
                assert expected == actual[: len(expected)], (
                    f"{document}: block text does not begin at its cited source span"
                )


def test_table_block_span_contains_a_table(corpus) -> None:
    """Require every parser table block span to contain its source table."""
    for document, (filing, raw) in corpus.items():
        for section in filing.sections:
            for block in section.blocks:
                if block.kind == "table":
                    cited = raw[block.source_pos : block.end_pos].lower()
                    assert "<table" in cited, f"{document}: table citation misses its table"
