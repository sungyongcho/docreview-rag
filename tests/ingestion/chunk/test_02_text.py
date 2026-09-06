"""Structure-aware text grouping and contextual header tests."""

import pytest

from app.ingestion.parser import Block, Section
from tests.ingestion.chunk.support import build_filing


def test_chunk_filing_rejects_missing_source_identity(C):
    """Reject filings without canonical source length and digest identity."""
    filing = build_filing([Block("paragraph", "body", source_pos=10, end_pos=20)])

    filing.source_length = 0
    with pytest.raises(ValueError, match="source length"):
        C.chunk_filing(filing)

    filing.source_length = 1_000
    filing.source_sha256 = ""
    with pytest.raises(ValueError, match="source SHA-256"):
        C.chunk_filing(filing)


def test_text_chunks_respect_block_boundaries(C):
    """Split only between complete paragraph blocks near the soft target."""
    blocks = [
        Block("paragraph", "a" * 60, source_pos=10, end_pos=80),
        Block("paragraph", "b" * 60, source_pos=80, end_pos=150),
    ]
    chunks = C.chunk_filing(build_filing(blocks), C.ChunkConfig(target_tokens=35))
    assert [chunk.body for chunk in chunks] == ["a" * 60, "b" * 60]
    assert [(chunk.start_char, chunk.end_char) for chunk in chunks] == [(10, 80), (80, 150)]


def test_single_long_paragraph_is_not_destroyed(C):
    """Keep one long paragraph intact even when it exceeds the soft target."""
    block = Block("paragraph", "x" * 200, source_pos=10, end_pos=220)
    chunks = C.chunk_filing(build_filing([block]), C.ChunkConfig(target_tokens=20))
    assert len(chunks) == 1
    assert chunks[0].body == "x" * 200


def test_text_chunks_do_not_bridge_disjoint_source_ranges(C):
    """Do not combine blocks from separate narrative source groups."""
    blocks = [
        Block("paragraph", "First range.", source_pos=10, end_pos=30, source_group=0),
        Block("paragraph", "Second range.", source_pos=100, end_pos=120, source_group=1),
    ]
    chunks = C.chunk_filing(build_filing(blocks), C.ChunkConfig(target_tokens=1_000))
    assert [chunk.body for chunk in chunks] == ["First range.", "Second range."]
    assert [(chunk.start_char, chunk.end_char) for chunk in chunks] == [(10, 30), (100, 120)]


def test_xref_context_resets_to_the_current_source_group(C):
    """Reset xref context when chunking advances to another source group."""
    filing = build_filing(
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
    """Keep Intel's non-GAAP range free of a sibling range title."""
    chunks = [
        chunk
        for chunk in chunks_by_doc["INTC-FY2023"]
        if chunk.item == "7" and "Non-GAAP Financial Measures" in chunk.context_header
    ]

    assert chunks
    assert all("Total cash and investments 1" not in chunk.context_header for chunk in chunks)


def test_narrative_heading_becomes_repeated_context(C):
    """Repeat a narrative heading across chunks without copying it into body."""
    blocks = [
        Block("heading", "Liquidity", level=2, source_pos=10, end_pos=20),
        Block("paragraph", "Cash increased.", source_pos=20, end_pos=40),
        Block("paragraph", "Debt decreased.", source_pos=40, end_pos=60),
    ]
    chunks = C.chunk_filing(build_filing(blocks), C.ChunkConfig(target_tokens=20))
    assert len(chunks) == 2
    assert all("Liquidity" in chunk.context_header for chunk in chunks)
    assert all("Liquidity" not in chunk.body for chunk in chunks)


def test_consecutive_headings_remain_in_context(C):
    """Preserve every heading in a consecutive heading path."""
    blocks = [
        Block("heading", "Note 12 - Debt", level=2, source_pos=10, end_pos=30),
        Block("heading", "Commercial Paper", level=2, source_pos=30, end_pos=50),
        Block("paragraph", "We had commercial paper.", source_pos=50, end_pos=80),
    ]

    chunks = C.chunk_filing(build_filing(blocks))

    assert len(chunks) == 1
    assert "Note 12 - Debt · Commercial Paper" in chunks[0].context_header


@pytest.mark.parametrize("status", ["empty_disclosure", "incorporated_by_reference"])
def test_non_substantive_sections_do_not_become_chunks(C, status):
    """Exclude empty and reference-only sections from retrieval chunks."""
    filing = build_filing([Block("paragraph", "Real body.", source_pos=10, end_pos=30)])
    filing.sections.append(
        Section(
            "II",
            "8",
            "Financial Statements",
            "Financial Statements",
            [Block("paragraph", "Not substantive.", source_pos=30, end_pos=60)],
            status=status,
        )
    )

    chunks = C.chunk_filing(filing)

    assert [chunk.body for chunk in chunks] == ["Real body."]


def test_ordinals_are_dense_and_source_ordered(chunks_by_doc):
    """Assign dense ordinals after restoring document source order."""
    for doc_id, chunks in chunks_by_doc.items():
        assert [chunk.ordinal for chunk in chunks] == list(range(len(chunks)))
        assert [chunk.start_char for chunk in chunks] == sorted(
            chunk.start_char for chunk in chunks
        ), f"{doc_id}: chunk order differs from source order"


def test_chunk_spans_overlap_only_when_sharing_enclosing_source(chunks_by_doc):
    """Allow repeated enclosing spans only for distinct source fragments."""
    for doc_id, chunks in chunks_by_doc.items():
        for left, right in zip(chunks, chunks[1:], strict=False):
            assert left.end_char <= right.start_char or (
                (left.start_char, left.end_char) == (right.start_char, right.end_char)
                and left.stable_key != right.stable_key
            ), f"{doc_id}: chunks {left.ordinal} and {right.ordinal} overlap"


def test_chunks_do_not_cross_items(C):
    """Keep adjacent sections in separate chunks with their own Item identity."""
    filing = build_filing([Block("paragraph", "Item 7 body.", source_pos=10, end_pos=30)])
    filing.sections.append(
        Section(
            "II",
            "7A",
            "Market Risk",
            "Item 7A. Market Risk",
            [Block("paragraph", "Item 7A body.", source_pos=30, end_pos=50)],
        )
    )

    chunks = C.chunk_filing(filing)

    assert [(chunk.item, chunk.body) for chunk in chunks] == [
        ("7", "Item 7 body."),
        ("7A", "Item 7A body."),
    ]
