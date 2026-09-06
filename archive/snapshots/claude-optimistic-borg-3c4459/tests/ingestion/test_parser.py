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


@pytest.mark.parametrize(
    "table_html",
    [
        "<table><tr><td>Revenue</td><td>100</td></tr></table>",
        """
        <table><tr>
          <td><div>Revenue</div></td><td><div>2024</div></td>
          <td><div>100</div></td><td><div>2023</div></td>
          <td><div>90</div></td><td><div>80</div></td>
        </tr></table>
        """,
    ],
)
def test_leaf_blocks_never_loses_a_table(parser_module: ModuleType, table_html: str) -> None:
    """leaf_blocks preserves both simple and legacy nested-div tables."""
    soup = parser_module.normalize(f"<html><body>{table_html}</body></html>")

    blocks = parser_module.leaf_blocks(soup)

    assert sum(block.name == "table" for block in blocks) == 1


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


def test_read_source_preserves_crlf_for_source_offsets(
    parser_module: ModuleType,
    tmp_path,
) -> None:
    """Keep CRLF, Unicode offsets, and the source digest bound to exact bytes."""
    path = tmp_path / "crlf.html"
    source_bytes = "<html>\r\n<p>First</p>\r\n<p>café</p>\r\n</html>".encode()
    path.write_bytes(source_bytes)

    raw = parser_module.read_source(path)
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
