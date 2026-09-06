"""L2/L4: structure-aware text grouping and contextual headers."""

import pytest

from app.ingestion.parser import Block, ParsedFiling, Section
from tests.support import need


def _filing(blocks: list[Block]) -> ParsedFiling:
    filing = ParsedFiling(
        doc_id="NVDA-FY2024",
        ticker="NVDA",
        cik="1045810",
        form="10-K",
        filing_date="2024-02-21",
        report_period="2024-01-28",
        fiscal_year=2024,
        accession="x",
        source_url="https://example.test",
        source_length=1_000,
        source_sha256="a" * 64,
    )
    filing.sections = [
        Section("II", "7", "Management's Discussion", "Item 7. Management's Discussion", blocks)
    ]
    return filing


def test_chunk_filing_rejects_missing_source_identity(C):
    need(C, "chunk_filing")
    filing = _filing([Block("paragraph", "body", source_pos=10, end_pos=20)])

    filing.source_length = 0
    with pytest.raises(ValueError, match="source length"):
        C.chunk_filing(filing)

    filing.source_length = 1_000
    filing.source_sha256 = ""
    with pytest.raises(ValueError, match="source SHA-256"):
        C.chunk_filing(filing)


def test_text_chunks_respect_block_boundaries(C):
    need(C, "chunk_filing", "ChunkConfig")
    blocks = [
        Block("paragraph", "a" * 60, source_pos=10, end_pos=80),
        Block("paragraph", "b" * 60, source_pos=80, end_pos=150),
    ]
    chunks = C.chunk_filing(_filing(blocks), C.ChunkConfig(target_text_chars=100))
    assert [chunk.body for chunk in chunks] == ["a" * 60, "b" * 60]
    assert [(chunk.start_char, chunk.end_char) for chunk in chunks] == [(10, 80), (80, 150)]


def test_single_long_paragraph_is_not_destroyed(C):
    need(C, "chunk_filing", "ChunkConfig")
    block = Block("paragraph", "x" * 200, source_pos=10, end_pos=220)
    chunks = C.chunk_filing(_filing([block]), C.ChunkConfig(target_text_chars=50))
    assert len(chunks) == 1
    assert chunks[0].body == "x" * 200


def test_text_chunks_do_not_bridge_disjoint_source_ranges(C):
    need(C, "chunk_filing", "ChunkConfig")
    blocks = [
        Block("paragraph", "First range.", source_pos=10, end_pos=30, source_group=0),
        Block("paragraph", "Second range.", source_pos=100, end_pos=120, source_group=1),
    ]
    chunks = C.chunk_filing(_filing(blocks), C.ChunkConfig(target_text_chars=1_000))
    assert [chunk.body for chunk in chunks] == ["First range.", "Second range."]
    assert [(chunk.start_char, chunk.end_char) for chunk in chunks] == [(10, 30), (100, 120)]


def test_xref_context_resets_to_the_current_source_group(C):
    need(C, "chunk_filing", "ChunkConfig")
    filing = _filing(
        [
            Block(
                "heading",
                "First subsection",
                level=2,
                source_pos=10,
                end_pos=20,
                source_group=0,
                source_heading="First range",
            ),
            Block(
                "paragraph",
                "First body.",
                source_pos=20,
                end_pos=40,
                source_group=0,
                source_heading="First range",
            ),
            Block(
                "paragraph",
                "Second body.",
                source_pos=100,
                end_pos=120,
                source_group=1,
                source_heading="Second range",
            ),
        ]
    )
    filing.sections[0].reported_title = "First range; Second range"
    chunks = C.chunk_filing(filing)

    assert "First subsection" in chunks[0].context_header
    assert "Second range" not in chunks[0].context_header
    assert "Second range" in chunks[1].context_header
    assert "First subsection" not in chunks[1].context_header
    assert "First range; Second range" not in chunks[1].context_header


def test_intel_non_gaap_range_does_not_inherit_a_sibling_title(chunks_by_doc):
    chunks = [
        chunk
        for chunk in chunks_by_doc["INTC-FY2023"]
        if chunk.item == "7" and "Non-GAAP Financial Measures" in chunk.context_header
    ]

    assert chunks
    assert all("Total cash and investments 1" not in chunk.context_header for chunk in chunks)


def test_narrative_heading_becomes_repeated_context(C):
    need(C, "chunk_filing", "ChunkConfig")
    blocks = [
        Block("heading", "Liquidity", level=2, source_pos=10, end_pos=20),
        Block("paragraph", "Cash increased.", source_pos=20, end_pos=40),
        Block("paragraph", "Debt decreased.", source_pos=40, end_pos=60),
    ]
    chunks = C.chunk_filing(_filing(blocks), C.ChunkConfig(target_text_chars=15))
    assert len(chunks) == 2
    assert all("Liquidity" in chunk.context_header for chunk in chunks)
    assert all("Liquidity" not in chunk.body for chunk in chunks)


def test_ordinals_are_dense_and_source_ordered(chunks_by_doc):
    for doc_id, chunks in chunks_by_doc.items():
        assert [chunk.ordinal for chunk in chunks] == list(range(len(chunks)))
        assert [chunk.start_char for chunk in chunks] == sorted(
            chunk.start_char for chunk in chunks
        ), f"{doc_id}: chunk order differs from source order"


def test_chunk_spans_do_not_overlap(chunks_by_doc):
    for doc_id, chunks in chunks_by_doc.items():
        for left, right in zip(chunks, chunks[1:], strict=False):
            assert left.end_char <= right.start_char, (
                f"{doc_id}: chunks {left.ordinal} and {right.ordinal} overlap"
            )


def test_chunks_do_not_cross_items(chunks_by_doc):
    for chunks in chunks_by_doc.values():
        for chunk in chunks:
            assert chunk.item is None or f"Item {chunk.item}" in chunk.citation
