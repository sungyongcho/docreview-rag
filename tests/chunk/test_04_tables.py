"""L3: each rendered table remains one source-cited retrieval unit."""

from app.ingestion.parser import Block
from tests.chunk.test_03_text import _filing
from tests.support import need


def test_table_is_not_split_without_row_level_provenance(C):
    need(C, "chunk_filing")
    html = """<table>
      <tr><td></td><td>2024</td><td>2023</td></tr>
      <tr><td>Revenue</td><td>100</td><td>90</td></tr>
      <tr><td>Cost</td><td>40</td><td>35</td></tr>
    </table>"""
    block = Block("table", "", html=html, source_pos=10, end_pos=200)
    chunks = C.chunk_filing(_filing([block]))

    assert len(chunks) == 1
    assert chunks[0].kind == "table"
    assert "| Revenue | 100 | 90 |" in chunks[0].body
    assert "| Cost | 40 | 35 |" in chunks[0].body
    assert (chunks[0].start_char, chunks[0].end_char) == (10, 200)


def test_each_renderable_source_table_becomes_exactly_one_chunk(C, corpus, chunks_by_doc):
    need(C, "table_to_markdown")
    for doc_id, (filing, _raw) in corpus.items():
        renderable = sum(
            block.kind == "table" and bool(C.table_to_markdown(block.html))
            for section in filing.sections
            for block in section.blocks
        )
        output = sum(chunk.kind == "table" for chunk in chunks_by_doc[doc_id])
        assert output == renderable, (
            f"{doc_id}: table chunks do not map one-to-one to source tables"
        )


def test_table_chunk_spans_are_unique_within_a_document(chunks_by_doc):
    for doc_id, chunks in chunks_by_doc.items():
        spans = [(chunk.start_char, chunk.end_char) for chunk in chunks if chunk.kind == "table"]
        assert len(spans) == len(set(spans)), f"{doc_id}: duplicate table citation span"


def test_table_row_width_is_stable(chunks_by_doc):
    for doc_id, chunks in chunks_by_doc.items():
        for chunk in chunks:
            if chunk.kind != "table":
                continue
            widths = {line.count("|") for line in chunk.body.splitlines()}
            assert len(widths) == 1, f"{doc_id} chunk {chunk.ordinal}: ragged markdown"
