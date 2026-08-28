from types import ModuleType

import pytest


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
    """Keep production source bytes intact when calculating character offsets."""
    path = tmp_path / "crlf.html"
    path.write_bytes(b"<html>\r\n<p>First</p>\r\n<p>Second</p>\r\n</html>")

    raw = parser_module.read_source(path)
    soup = parser_module.normalize(raw)
    offsets = parser_module.line_offsets(raw)
    second = soup.find_all("p")[1]

    assert "\r\n" in raw
    assert parser_module.source_pos(second, offsets) == raw.index("<p>Second</p>")
