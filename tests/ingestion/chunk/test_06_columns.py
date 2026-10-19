"""Wide-table partitions retain column identity and the matching source headers."""

from pathlib import Path

import pytest

from app.ingestion.chunking import _table_pieces, chunk_filing
from app.ingestion.parsing.dart import parse_dart_filing
from app.ingestion.parsing.models import Block
from app.ingestion.parsing.tables import structured_table
from app.ingestion.sources.models import FilingSource, Manifest
from app.ingestion.tokens import InputBudget
from tests.ingestion.chunk.support import build_filing


@pytest.mark.parametrize("html", ["", "<table><tr><td>(단위 : 백만원)</td></tr></table>"])
def test_empty_or_caption_only_tables_have_no_row_fragments(html):
    """An empty body cannot produce column windows or retrieval row fragments."""
    assert _table_pieces(structured_table(html), "context", InputBudget()) == []


def test_wide_headers_split_with_their_values_and_original_columns():
    """Keep complete source membership when even headers exceed the hard bound."""
    names = [f"Subsidiary {i} with a sufficiently descriptive company name" for i in range(12)]
    html = (
        '<table><tr><td colspan="13">(단위 : 백만원)</td></tr>'
        "<tr><td>Metric</td>"
        + "".join(f"<td>{name}</td>" for name in names)
        + "</tr><tr><td>Revenue</td>"
        + "".join(f"<td>{100 + i}</td>" for i in range(12))
        + "</tr><tr><td>Income</td>"
        + "".join(f"<td>{200 + i}</td>" for i in range(12))
        + "</tr></table>"
    )
    filing = build_filing([Block("table", "", html=html, source_pos=0, end_pos=len(html))])
    filing.source_length = len(html)
    budget = InputBudget(target_tokens=200, max_tokens=500, max_chars=400)

    chunks = chunk_filing(filing, budget)

    assert len(chunks) > 1
    covered = set()
    for chunk in chunks:
        assert budget.accepts(chunk.content)
        assert "(단위 : 백만원)" in chunk.body
        assert (chunk.start_char, chunk.end_char) == (0, len(html))
        fragment = chunk.table_fragment
        assert fragment is not None
        assert fragment.header_rows == (1,)
        for cell in fragment.cells:
            if cell.column == 0 or cell.text_start == cell.text_end:
                continue
            value = str((100 if cell.row == 2 else 200) + cell.column - 1)
            assert chunk.body.count(names[cell.column - 1]) == 1
            assert value in chunk.body
            assert (cell.text_start, cell.text_end) == (0, len(value))
            assert len(cell.sources) == 1
            source = cell.sources[0]
            assert (source.row, source.column, source.text) == (cell.row, cell.column, value)
            covered.add((cell.row, cell.column))
        header_columns = {cell.column for cell in fragment.header_cells}
        assert header_columns == {cell.column for cell in fragment.cells}
        assert len(header_columns) < 13
    assert covered == {(row, col) for row in (2, 3) for col in range(1, 13)}


def test_selected_columns_keep_long_cell_intervals_in_original_coordinates():
    """Combine column projection and sentence cuts without renumbering evidence."""
    narrative = "Revenue remains supported by source evidence. " * 25
    html = (
        "<table><tr><td>Metric</td>"
        + "".join(f"<td>Company {i} with a descriptive operating name</td>" for i in range(8))
        + "</tr><tr><td>Revenue</td>"
        + "".join(f"<td>{narrative if i == 6 else 100 + i}</td>" for i in range(8))
        + "</tr></table>"
    )
    filing = build_filing([Block("table", "", html=html, source_pos=0, end_pos=len(html))])
    filing.source_length = len(html)
    budget = InputBudget(target_tokens=90, max_tokens=250, max_chars=400)
    chunks = chunk_filing(filing, budget)

    intervals = set()
    for chunk in chunks:
        assert budget.accepts(chunk.content)
        assert chunk.table_fragment is not None
        for cell in chunk.table_fragment.cells:
            if cell.column == 7 and cell.text_end > cell.text_start:
                assert cell.row == 1
                assert cell.sources[0].column == 7
                assert "Company 6 with a descriptive operating name" in chunk.body
                assert narrative.strip()[cell.text_start : cell.text_end].strip() in chunk.body
                intervals.add((cell.text_start, cell.text_end))
    end = 0
    assert len(intervals) > 1
    for start, stop in sorted(intervals):
        assert start == end
        end = stop
    assert end == len(narrative.strip())


def test_samsung_2023_subsidiary_table_chunks_with_bounded_matching_headers():
    """Recover the real 240-column table without losing source cell coordinates."""
    root = Path(__file__).resolve().parents[3] / "data/corpus"
    catalog_path = root / "manifest.json"
    if not catalog_path.exists():
        pytest.skip("The actual Samsung source is required for this regression")
    manifest = Manifest.read(catalog_path)
    document = next((d for d in manifest.documents if d.document_id == "dart-20240312000736"), None)
    if document is None:
        pytest.skip("Samsung FY2023 is not registered in this corpus")
    artifact = next(
        a
        for a in manifest.artifacts
        if a.document_id == document.document_id and a.role == "primary"
    )
    filing, _ = parse_dart_filing(FilingSource(document, artifact, root, manifest.corpus))
    block = next(
        block
        for section in filing.sections
        for block in section.blocks
        if block.kind == "table" and block.source_pos == 413409
    )
    table = structured_table(block.html)
    assert len(table.rows[0].cells) == 240

    chunks = chunk_filing(filing)

    budget = InputBudget()
    assert all(budget.accepts(chunk.content) for chunk in chunks)
    parts = [chunk for chunk in chunks if chunk.start_char == block.source_pos]
    assert len(parts) > 1
    cells = {(row.source_row, cell.column): cell for row in table.rows for cell in row.cells}
    covered = set()
    for chunk in parts:
        fragment = chunk.table_fragment
        assert fragment is not None
        assert fragment.header_rows == tuple(row.source_row for row in table.headers)
        for member in fragment.cells:
            expected = cells[member.row, member.column]
            assert member.sources == expected.sources
            assert expected.text[member.text_start : member.text_end] in chunk.body
            if expected.text:
                covered.add((member.row, member.column))
        selected = {member.column for member in fragment.cells}
        expected_headers = {
            source
            for row in table.headers
            for cell in row.cells
            if cell.column in selected
            for source in cell.sources
            if source.text
        }
        assert set(fragment.header_cells) == expected_headers
    assert covered == {identity for identity, cell in cells.items() if cell.text}
