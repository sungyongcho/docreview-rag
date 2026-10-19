"""Table chunking and source-citation tests."""

import app.ingestion.chunking as chunking
from app.ingestion.parsing.html import line_offsets, normalize, source_pos
from app.ingestion.parsing.models import Block
from app.ingestion.parsing.tables import structured_table
from tests.ingestion.chunk.support import build_filing, markdown_cells


def test_amd_2024_financial_tables_keep_revenue_headers_units_and_source(corpus, chunks_by_doc):
    """Recover every reported revenue table from the exact AMD filing, through chunking."""
    doc_id = "sec-0000002488-25-000012"
    filing, raw = corpus[doc_id]
    assert filing.source_sha256 == (
        "a56e68cfe5f9cbb84451c9bb7ffe95e287c84ea616570e392f052474e0400664"
    )
    tables = normalize(raw).find_all("table")
    offsets = line_offsets(raw)
    # These are independently inspected tables in the pinned source, not parser output IDs.
    for index in (8, 9, 12, 22, 24):
        start = source_pos(tables[index], offsets)
        matching = [c for c in chunks_by_doc[doc_id] if c.kind == "table" and c.start_char == start]
        assert matching, f"source table {index} was dropped"
        revenue = next(c for c in matching if "25,785" in c.body and "22,680" in c.body)
        assert "December 28, 2024" in revenue.body
        assert "December 30, 2023" in revenue.body
        assert "million" in revenue.body
        assert "$ 25,785" in revenue.body
        assert "$ 22,680" in revenue.body
        assert revenue.source_sha256 == filing.source_sha256
        assert revenue.doc_id == doc_id
        assert revenue.start_char < revenue.end_char <= len(raw)
        cited = raw[revenue.start_char : revenue.end_char]
        assert "25,785" in cited and "22,680" in cited
        assert revenue.table_fragment is not None
        if index == 12:
            assert "Consolidated Statements of Operations" in revenue.context_header
            assert "| Net revenue | $ 25,785 | $ 22,680 | $ 23,601 |" in revenue.body
            assert revenue.citation == "AMD FY2024 · Item 8"
            assert "AMD" in revenue.content
            assert "| Net revenue | $ 25,785 | $ 22,680 | $ 23,601 |" in revenue.content


def test_nvda_inventory_grid_reaches_indexing_with_years_units_and_source(corpus, chunks_by_doc):
    """Recover another issuer's sparse table as usable, source-bound retrieval input."""
    doc_id = "sec-0001045810-24-000029"
    filing, raw = corpus[doc_id]
    table = normalize(raw).find_all("table")[41]
    start = source_pos(table, line_offsets(raw))
    chunk = next(c for c in chunks_by_doc[doc_id] if c.kind == "table" and c.start_char == start)
    assert "Jan 28, 2024" in chunk.content
    assert "Jan 29, 2023" in chunk.content
    assert "(In millions)" in chunk.content
    assert "| Total inventories | $ 5,282 | $ 5,159 |" in chunk.content
    assert chunk.citation == "NVDA FY2024 · Item 15"
    assert chunk.source_sha256 == filing.source_sha256
    assert chunk.table_fragment is not None
    cited = raw[chunk.start_char : chunk.end_char]
    assert "5,282" in cited and "5,159" in cited


def test_each_renderable_source_table_has_complete_fragment_coverage(corpus, chunks_by_doc):
    """Map each source table to a distinct enclosing span with typed fragment membership."""
    for doc_id, (filing, _raw) in corpus.items():
        renderable = sum(
            section.status == "parsed"
            and block.kind == "table"
            and bool(structured_table(block.html).render())
            for section in filing.sections
            for block in section.blocks
        )
        output = len(
            {
                (chunk.start_char, chunk.end_char)
                for chunk in chunks_by_doc[doc_id]
                if chunk.kind == "table"
            }
        )
        assert output == renderable, (
            f"{doc_id}: table chunks do not map one-to-one to source tables"
        )


def test_table_row_width_is_stable(chunks_by_doc):
    """Keep markdown row widths stable when cell text contains escaped pipes."""
    for doc_id, chunks in chunks_by_doc.items():
        for chunk in chunks:
            if chunk.kind != "table":
                continue
            widths = {len(markdown_cells(line)) for line in chunk.body.splitlines()}
            assert len(widths) == 1, f"{doc_id} chunk {chunk.ordinal}: ragged markdown"


def test_escaped_cell_pipe_does_not_change_markdown_width():
    """Treat an escaped literal pipe as cell content rather than a separator."""
    html = """<table>
      <tr><td>Metric</td><td>2024</td><td>2023</td></tr>
      <tr><td>Revenue A|B</td><td>100</td><td>90</td></tr>
    </table>"""
    block = Block("table", "", html=html, source_pos=10, end_pos=200)

    chunk = chunking.chunk_filing(build_filing([block]))[0]
    widths = {len(markdown_cells(line)) for line in chunk.body.splitlines()}

    assert widths == {3}


def test_caption_only_table_annotates_the_next_table_chunk():
    """Carry a preceding unit-annotation table into the next table's context."""
    caption = Block(
        "table",
        "",
        html="<table><tr><td>(단위 : 백만원)</td></tr></table>",
        source_pos=10,
        end_pos=80,
    )
    data = Block(
        "table",
        "",
        html="<table><tr><td>매출액</td><td>300,870</td></tr>"
        "<tr><td>영업이익</td><td>32,725</td></tr></table>",
        source_pos=80,
        end_pos=300,
    )
    chunks = chunking.chunk_filing(build_filing([caption, data]))

    assert len(chunks) == 1
    assert chunks[0].kind == "table"
    assert "(단위 : 백만원)" in chunks[0].context_header
    assert "| 매출액 | 300,870 |" in chunks[0].body


def test_caption_paragraph_annotates_the_next_table_chunk():
    """A paragraph that is nothing but a unit caption becomes the table's context."""
    heading = Block("heading", "재무 현황", level=2, source_pos=10, end_pos=30)
    caption = Block("paragraph", "(단위 : 백만원)", source_pos=30, end_pos=60)
    data = Block(
        "table",
        "",
        html="<table><tr><td>매출액</td><td>300,870</td></tr>"
        "<tr><td>영업이익</td><td>32,725</td></tr></table>",
        source_pos=60,
        end_pos=300,
    )
    chunks = chunking.chunk_filing(build_filing([heading, caption, data]))

    assert len(chunks) == 1
    assert chunks[0].kind == "table"
    # The caption must not break the heading run: both reach the table's context.
    assert "재무 현황" in chunks[0].context_header
    assert "(단위 : 백만원)" in chunks[0].context_header
    assert "(단위 : 백만원)" not in chunks[0].body


def test_caption_paragraph_without_a_table_is_dropped():
    """A caption paragraph followed by narrative vanishes; the narrative still chunks."""
    caption = Block("paragraph", "(단위 : 백만원)", source_pos=10, end_pos=40)
    para = Block("paragraph", "Revenue grew this year.", source_pos=40, end_pos=120)
    chunks = chunking.chunk_filing(build_filing([caption, para]))

    assert len(chunks) == 1
    assert chunks[0].kind == "text"
    assert "Revenue grew this year." in chunks[0].body
    assert all("(단위 : 백만원)" not in chunk.content for chunk in chunks)
