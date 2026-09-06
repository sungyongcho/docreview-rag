"""Complete-input structural budgets and exact source-membership acceptance checks."""

from dataclasses import asdict, replace
import os
from pathlib import Path
import shutil

from bs4 import BeautifulSoup
import pytest

from app.ingestion.chunk import ChunkConfig, chunk_filing
from app.ingestion.parser import Block
from app.ingestion.tables import render_table, structured_table
from app.ingestion.tokens import MAX_INPUT_CHARACTERS, count_tokens
from tests.ingestion.chunk.support import build_filing


def _chunks(html: str, **budget):
    """Chunk one synthetic table with honest enclosing source coordinates."""
    filing = build_filing([Block("table", "", html=html, source_pos=0, end_pos=len(html))])
    filing.source_length = len(html)
    return chunk_filing(filing, ChunkConfig(**budget))


def _raw_source_cells(html: str) -> dict[tuple[int, int, int, int], str]:
    """Read original nonempty cells and spans independently of the renderer grid."""
    table = BeautifulSoup(html, "html.parser").find("table")
    assert table is not None
    rows = [row for row in table.find_all("tr") if row.find_parent("table") is table]
    occupied: set[tuple[int, int]] = set()
    cells = {}
    for row_index, row in enumerate(rows):
        column = 0
        for cell in row.find_all(["td", "th", "te", "tu"], recursive=False):
            while (row_index, column) in occupied:
                column += 1
            rowspan, colspan = int(cell.get("rowspan", 1)), int(cell.get("colspan", 1))
            visible = "".join(cell.get_text().split())
            if visible:
                cells[row_index, column, rowspan, colspan] = visible
            occupied.update(
                (r, c)
                for r in range(row_index, row_index + rowspan)
                for c in range(column, column + colspan)
            )
            column += colspan
    return cells


def _source_key(cell):
    """Identify the original HTML cell rather than its normalized output column."""
    return cell.row, cell.column, cell.rowspan, cell.colspan


def _assert_raw_source_coverage(html: str, chunks):
    """Require every original cell value/span in the persisted fragment metadata."""
    raw = _raw_source_cells(html)
    retained = {}
    for chunk in chunks:
        sources = [
            *chunk.table_fragment.header_cells,
            *(source for cell in chunk.table_fragment.cells for source in cell.sources),
        ]
        for caption in chunk.table_fragment.caption_sources:
            if (caption.start_char, caption.end_char) == (chunk.start_char, chunk.end_char):
                sources.extend(caption.cells)
        for source in sources:
            if source.text:
                retained[_source_key(source)] = "".join(source.text.split())
    assert retained == raw


def _assert_cell_coverage(table, chunks):
    """Require every normalized cell character to survive at its declared membership."""
    for row in table.rows:
        for cell in row.cells:
            for chunk in chunks:
                for part in chunk.table_fragment.cells:
                    if part.row == row.source_row and part.column == cell.column:
                        text = cell.text[part.text_start : part.text_end]
                        escaped = " ".join(text.replace("\\", "\\\\").replace("|", "\\|").split())
                        assert escaped in chunk.body
            intervals = sorted(
                {
                    (part.text_start, part.text_end)
                    for chunk in chunks
                    for part in chunk.table_fragment.cells
                    if part.row == row.source_row
                    and part.column == cell.column
                    and part.text_end > part.text_start
                }
            )
            end = 0
            for start, stop in intervals:
                assert start <= end, (row.source_row, cell.column, start, end)
                assert 0 <= start < stop <= len(cell.text)
                end = max(end, stop)
            assert end == len(cell.text), (row.source_row, cell.column)


def test_merged_cells_keep_source_relationships_and_numeric_rendering():
    """Retain original spans while preserving currencies, negatives, and header rows."""
    html = """<table><tr><td></td><td colspan="2" align="center">Year</td></tr>
    <tr><td>Metric</td><td></td><td>2024</td></tr>
    <tr><td rowspan="2">Revenue</td><td>$</td><td>(1,234)</td></tr>
    <tr><td>$</td><td>567</td></tr></table>"""
    table = structured_table(html)
    assert table.render() == render_table(html)[1]
    assert "$ (1,234)" in table.render()
    assert len(table.headers) == 2
    assert any(
        source.rowspan == 2 for row in table.rows for cell in row.cells for source in cell.sources
    )
    assert any(
        source.colspan == 2
        for row in table.headers
        for cell in row.cells
        for source in cell.sources
    )
    chunks = _chunks(html)
    assert len(chunks) == 1
    _assert_cell_coverage(table, chunks)


def test_large_row_groups_repeat_headers_units_and_preserve_all_cells():
    """Split complete row groups with repeated units and no lost source membership."""
    rows = "".join(f"<tr><td>Metric {i}</td><td>{i},234</td></tr>" for i in range(50))
    html = (
        '<table><tr><td colspan="2">(단위 : 백만원)</td></tr><tr><td>Metric</td><td>2024</td></tr>'
        + rows
        + "</table>"
    )
    chunks = _chunks(html, target_tokens=120)
    assert len(chunks) > 1
    assert all(count_tokens(chunk.content) <= 120 for chunk in chunks)
    assert all("(단위 : 백만원)" in chunk.body and "2024" in chunk.body for chunk in chunks)
    assert {(chunk.start_char, chunk.end_char) for chunk in chunks} == {(0, len(html))}
    _assert_cell_coverage(structured_table(html), chunks)
    assert len({chunk.stable_key for chunk in chunks}) == len(chunks)
    assert replace(chunks[0], ordinal=999).stable_key == chunks[0].stable_key
    assert replace(chunks[0], body=chunks[0].body + "changed").stable_key != chunks[0].stable_key


def test_wide_rows_and_long_cells_split_at_cells_and_sentences():
    """Keep sentence intervals and original row identity when one row exceeds target."""
    text = "Revenue increased significantly. " * 90
    html = (
        "<table><tr><td>Metric</td><td>Narrative</td><td>Amount</td></tr><tr><td>Revenue</td><td>"
        + text
        + "</td><td>(9,876)</td></tr></table>"
    )
    chunks = _chunks(html, target_tokens=100, max_tokens=250, max_chars=2000)
    assert len(chunks) > 2
    assert all(count_tokens(chunk.content) <= 100 for chunk in chunks)
    assert any("(9,876)" in chunk.body for chunk in chunks)
    assert all(chunk.table_fragment.header_rows == (0,) for chunk in chunks)
    _assert_cell_coverage(structured_table(html), chunks)
    assert all(fragment.sources for chunk in chunks for fragment in chunk.table_fragment.cells)


def test_indivisible_cell_fails_with_row_and_column():
    """Reject a cell sentence above the hard limit before any embedding is possible."""
    html = (
        "<table><tr><td>Label</td><td>Description</td></tr><tr><td>1</td><td>"
        + "word " * 500
        + "</td></tr></table>"
    )
    with pytest.raises(ValueError, match=r"Table row 1, column 1.*indivisible"):
        _chunks(html, target_tokens=100, max_tokens=200)


def test_narrative_sentences_preserve_text_and_enclosing_spans():
    """Split sentence boundaries and retain the enclosing paragraph source span."""
    text = "A complete sentence with financial evidence. " * 30
    filing = build_filing([Block("paragraph", text, source_pos=10, end_pos=900)])
    chunks = chunk_filing(filing, ChunkConfig(target_tokens=60, max_tokens=100))
    assert len(chunks) > 1
    assert len({chunk.stable_key for chunk in chunks}) == len(chunks)
    assert "".join(chunk.body for chunk in chunks) == text
    assert all(count_tokens(chunk.content) <= 60 for chunk in chunks)
    assert {(chunk.start_char, chunk.end_char) for chunk in chunks} == {(10, 900)}


def test_indivisible_narrative_and_repeated_context_obey_hard_limits():
    """Reject full inputs exceeding character or token limits, including context."""
    filing = build_filing([Block("paragraph", "word " * 300, source_pos=10, end_pos=900)])
    with pytest.raises(ValueError, match="indivisible sentence"):
        chunk_filing(filing, ChunkConfig(target_tokens=100, max_tokens=200))
    filing.sections[0].blocks[0].text = "Short sentence."
    with pytest.raises(ValueError, match="indivisible sentence"):
        chunk_filing(filing, ChunkConfig(max_chars=15))


def test_exact_five_samsung_tables_and_nvda_fit_complete_input_budgets(tmp_path, monkeypatch):
    """Measure the two identified source filings without modifying source or profiles."""
    root_text = os.environ.get("DOCREVIEW_ACCEPTANCE_SOURCE_ROOT")
    if not root_text:
        pytest.skip(
            "Set DOCREVIEW_ACCEPTANCE_SOURCE_ROOT to the source checkout for real acceptance"
        )
    from app.ingestion import edgar
    from app.ingestion.dart import parse_dart_filing

    root = Path(root_text)
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    profile = root / "data/profiles/NVDA.json"
    if profile.is_file():
        shutil.copy2(profile, profiles / profile.name)
    monkeypatch.setattr(edgar, "PROFILES", profiles)
    from app.ingestion.manifest import Manifest

    catalog_path = Path(__file__).resolve().parents[2] / "data/corpus/manifest.json"
    catalog = Manifest.read(catalog_path)
    entries = [
        (source, edgar.parse_filing if source.document.registry == "sec" else parse_dart_filing)
        for source in catalog.selected_sources("tutorial", root / "data/corpus")
    ]
    expected = {
        (3667520, 4485072),
        (4707141, 4889170),
        (5067120, 5260040),
        (5440579, 5675111),
        (5286302, 5439337),
    }
    caption_spans = {
        3667520: (3666995, 3667520, "(단위 : 개월)"),
        4707141: (4706620, 4707141, "(단위 : %)"),
        5067120: (5066702, 5067120, "(단위 : 백만원)"),
        5286302: (5285780, 5286302, "(단위 : 사)"),
        5440579: (5439868, 5440579, "(단위 : 백만원, 천주, %)"),
    }
    for entry, parse in entries:
        filing, _ = parse(entry)
        assert filing.parse_status == "parsed"
        chunks = chunk_filing(filing)
        assert chunks and all(
            count_tokens(chunk.content) <= 8192 and len(chunk.content) <= MAX_INPUT_CHARACTERS
            for chunk in chunks
        )
        assert len({chunk.stable_key for chunk in chunks}) == len(chunks)
        oversized = set()
        for section in filing.sections:
            for block in section.blocks:
                if block.kind != "table":
                    continue
                table = structured_table(block.html)
                assert table.render() == render_table(block.html)[1]
                if count_tokens(table.render()) <= 8192:
                    continue
                span = (block.source_pos, block.end_pos)
                oversized.add(span)
                parts = [
                    chunk
                    for chunk in chunks
                    if chunk.kind == "table" and (chunk.start_char, chunk.end_char) == span
                ]
                assert len(parts) > 1
                assert all(count_tokens(chunk.content) <= 2048 for chunk in parts)
                _assert_cell_coverage(table, parts)
                _assert_raw_source_coverage(block.html, parts)
                caption_start, caption_end, unit = caption_spans[span[0]]
                caption_block = next(
                    block
                    for section in filing.sections
                    for block in section.blocks
                    if (block.source_pos, block.end_pos) == (caption_start, caption_end)
                )
                caption_raw = _raw_source_cells(caption_block.html)
                for part in parts:
                    assert unit in part.context_header
                    references = [
                        caption
                        for caption in part.table_fragment.caption_sources
                        if (caption.start_char, caption.end_char) == (caption_start, caption_end)
                    ]
                    assert len(references) == 1
                    caption = references[0]
                    assert {
                        _source_key(cell): "".join(cell.text.split()) for cell in caption.cells
                    } == caption_raw
                    assert unit in caption.text
                    if span[0] != 5067120:
                        assert "(기준일 : 2024년 12월 31일 )" in part.context_header
                        assert "(기준일 : 2024년 12월 31일 )" in caption.text
                    assert asdict(part.table_fragment)["header_cells"]
        assert oversized == (expected if filing.source.document.registry == "dart" else set())


def test_wide_numeric_row_splits_at_cells_without_dropping_values():
    """Keep each numeric cell and source column when a complete wide row is too large."""
    headers = "".join(f"<td>Column {i}</td>" for i in range(8))
    values = "".join(f"<td>{i},234,567,890,123,456,789</td>" for i in range(8))
    html = "<table><tr>" + headers + "</tr><tr>" + values + "</tr></table>"
    table = structured_table(html)
    chunks = _chunks(html, target_tokens=140, max_tokens=300)
    assert len(chunks) > 1
    assert all(count_tokens(chunk.content) <= 140 for chunk in chunks)
    _assert_cell_coverage(table, chunks)
    for cell in table.rows[0].cells:
        assert any(cell.text in chunk.body for chunk in chunks)


def test_unit_column_preserves_original_scale_header_and_cell_relationships():
    """Retain a meaningful scale label even when its currency column is merged."""
    html = (
        "<table><tr><td>Metric</td><td>USD millions</td><td>2024</td></tr>"
        "<tr><td>Revenue</td><td>$</td><td>123</td></tr></table>"
    )
    chunks = _chunks(html)
    assert "USD millions" in chunks[0].body
    assert "$ 123" in chunks[0].body
    _assert_raw_source_coverage(html, chunks)
    assert any(
        cell.text == "USD millions" and cell.column == 1
        for cell in chunks[0].table_fragment.header_cells
    )


def test_adjacent_date_unit_caption_records_its_own_span_without_changing_data_span():
    """Link mixed date/unit annotations to every fragment of only the associated table."""
    caption = (
        "<table><tr><td>(기준일 : 2024년 12월 31일 )</td>"
        "<td>(단위 : 백만원, 천주, %)</td></tr></table>"
    )
    data = (
        "<table><tr><td>Metric</td><td>2024</td></tr>"
        + "".join(f"<tr><td>Revenue {i}</td><td>{i}123</td></tr>" for i in range(20))
        + "</table>"
    )
    start = len(caption)
    following = start + len(data)
    blocks = [
        Block("table", "", html=caption, source_pos=0, end_pos=start),
        Block("table", "", html=data, source_pos=start, end_pos=following),
        Block("table", "", html=data, source_pos=following, end_pos=following + len(data)),
    ]
    filing = build_filing(blocks)
    filing.source_length = following + len(data)
    chunks = chunk_filing(filing, ChunkConfig(target_tokens=160))
    first = [chunk for chunk in chunks if chunk.start_char == start]
    second = [chunk for chunk in chunks if chunk.start_char == following]
    assert len(first) > 1 and second
    raw = _raw_source_cells(caption)
    for chunk in first:
        assert (chunk.start_char, chunk.end_char) == (start, following)
        assert "(단위 : 백만원, 천주, %)" in chunk.context_header
        assert "(기준일 : 2024년 12월 31일 )" in chunk.context_header
        (source,) = chunk.table_fragment.caption_sources
        assert (source.start_char, source.end_char) == (0, start)
        assert {_source_key(cell): "".join(cell.text.split()) for cell in source.cells} == raw
    assert all(not chunk.table_fragment.caption_sources for chunk in second)
    assert all("단위" not in chunk.context_header for chunk in second)


@pytest.mark.parametrize("boundary", ["heading", "group", "paragraph"])
def test_caption_provenance_does_not_cross_a_context_boundary(boundary):
    """Clear unit relationships at headings, new source groups, and unrelated narrative."""
    caption = "<table><tr><td>(단위 : 백만원)</td></tr></table>"
    data = "<table><tr><td>Revenue</td><td>123</td></tr></table>"
    blocks = [Block("table", "", html=caption, source_pos=0, end_pos=100)]
    if boundary != "group":
        blocks.append(Block(boundary, "Other context", source_pos=100, end_pos=150))
    blocks.append(
        Block(
            "table",
            "",
            html=data,
            source_pos=150,
            end_pos=300,
            source_group=1 if boundary == "group" else 0,
        )
    )
    chunks = chunk_filing(build_filing(blocks))
    table_chunk = next(chunk for chunk in chunks if chunk.kind == "table")
    assert "단위" not in table_chunk.context_header
    assert table_chunk.table_fragment.caption_sources == ()


def test_internal_caption_cells_and_multilevel_header_spans_survive_serialization():
    """Preserve original caption and merged header cells inside data-table provenance."""
    html = (
        '<table><tr><td colspan="3">(단위 : 백만원)</td></tr>'
        '<tr><td rowspan="2">Metric</td><td colspan="2" align="center">Year</td></tr>'
        "<tr><td>2024</td><td>2023</td></tr>"
        "<tr><td>Revenue</td><td>123</td><td>100</td></tr></table>"
    )
    chunks = _chunks(html)
    _assert_raw_source_coverage(html, chunks)
    metadata = asdict(chunks[0].table_fragment)
    assert any(cell["rowspan"] == 2 for cell in metadata["header_cells"])
    assert any(cell["colspan"] == 2 for cell in metadata["header_cells"])
    assert metadata["caption_sources"][0]["start_char"] == 0
    assert metadata["caption_sources"][0]["end_char"] == len(html)


def test_caption_references_cannot_escape_the_source_document():
    """Validate inherited caption coordinates separately from the data-table span."""
    html = "<table><tr><td>Revenue</td><td>123</td></tr></table>"
    blocks = [
        Block("paragraph", "(단위 : 백만원)", source_pos=0, end_pos=1500),
        Block("table", "", html=html, source_pos=200, end_pos=300),
    ]
    with pytest.raises(ValueError, match="caption source span"):
        chunk_filing(build_filing(blocks))
