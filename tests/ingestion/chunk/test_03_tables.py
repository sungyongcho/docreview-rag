"""Table chunking and source-citation tests."""

from app.ingestion.parser import Block
from app.ingestion.tables import table_to_markdown
from tests.ingestion.chunk.support import build_filing, markdown_cells


def test_table_is_not_split_without_row_level_provenance(C):
    """Keep each rendered table whole when only table-level provenance exists."""
    html = """<table>
      <tr><td></td><td>2024</td><td>2023</td></tr>
      <tr><td>Revenue</td><td>100</td><td>90</td></tr>
      <tr><td>Cost</td><td>40</td><td>35</td></tr>
    </table>"""
    block = Block("table", "", html=html, source_pos=10, end_pos=200)
    chunks = C.chunk_filing(build_filing([block]))

    assert len(chunks) == 1
    assert chunks[0].kind == "table"
    assert "| Revenue | 100 | 90 |" in chunks[0].body
    assert "| Cost | 40 | 35 |" in chunks[0].body
    assert (chunks[0].start_char, chunks[0].end_char) == (10, 200)


def test_each_renderable_source_table_becomes_exactly_one_chunk(C, corpus, chunks_by_doc):
    """Map every renderable table in parsed sections to exactly one chunk."""
    for doc_id, (filing, _raw) in corpus.items():
        renderable = sum(
            section.status == "parsed"
            and block.kind == "table"
            and bool(table_to_markdown(block.html))
            for section in filing.sections
            for block in section.blocks
        )
        output = sum(chunk.kind == "table" for chunk in chunks_by_doc[doc_id])
        assert output == renderable, (
            f"{doc_id}: table chunks do not map one-to-one to source tables"
        )


def test_table_chunk_spans_are_unique_within_a_document(chunks_by_doc):
    """Give every table chunk a unique source span within its document."""
    for doc_id, chunks in chunks_by_doc.items():
        spans = [(chunk.start_char, chunk.end_char) for chunk in chunks if chunk.kind == "table"]
        assert len(spans) == len(set(spans)), f"{doc_id}: duplicate table citation span"


def test_table_row_width_is_stable(chunks_by_doc):
    """Keep markdown row widths stable when cell text contains escaped pipes."""
    for doc_id, chunks in chunks_by_doc.items():
        for chunk in chunks:
            if chunk.kind != "table":
                continue
            widths = {len(markdown_cells(line)) for line in chunk.body.splitlines()}
            assert len(widths) == 1, f"{doc_id} chunk {chunk.ordinal}: ragged markdown"


def test_escaped_cell_pipe_does_not_change_markdown_width(C):
    """Treat an escaped literal pipe as cell content rather than a separator."""
    html = """<table>
      <tr><td>Metric</td><td>2024</td><td>2023</td></tr>
      <tr><td>Revenue A|B</td><td>100</td><td>90</td></tr>
    </table>"""
    block = Block("table", "", html=html, source_pos=10, end_pos=200)

    chunk = C.chunk_filing(build_filing([block]))[0]
    widths = {len(markdown_cells(line)) for line in chunk.body.splitlines()}

    assert widths == {3}


def test_caption_only_table_annotates_the_next_table_chunk(C):
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
    chunks = C.chunk_filing(build_filing([caption, data]))

    assert len(chunks) == 1
    assert chunks[0].kind == "table"
    assert "(단위 : 백만원)" in chunks[0].context_header
    assert "| 매출액 | 300,870 |" in chunks[0].body
