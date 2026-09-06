"""L1: chunk types, configuration, and source-coordinate contract."""

from dataclasses import FrozenInstanceError

import pytest

from tests.support import need


def test_config_defaults_are_positive(C):
    need(C, "ChunkConfig")
    config = C.ChunkConfig()
    assert config.target_text_chars > 0


@pytest.mark.parametrize(
    ("field", "value"),
    (("target_text_chars", 0), ("target_text_chars", -1)),
)
def test_config_rejects_non_positive_limits(C, field, value):
    need(C, "ChunkConfig")
    with pytest.raises(ValueError):
        C.ChunkConfig(**{field: value})


def test_chunk_is_immutable_and_content_includes_context(C):
    need(C, "Chunk")
    chunk = C.Chunk(
        doc_id="NVDA-FY2024",
        item="7",
        kind="text",
        ordinal=0,
        body="Revenue increased.",
        context_header="NVDA FY2024 · Item 7",
        citation="NVDA FY2024 · Item 7",
        start_char=10,
        end_char=30,
        source_sha256="abc123",
    )
    assert chunk.content == "NVDA FY2024 · Item 7\n\nRevenue increased."
    with pytest.raises(FrozenInstanceError):
        chunk.ordinal = 1


def test_source_span_fails_closed(C):
    need(C, "_source_span")

    class Missing:
        source_pos = None
        end_pos = None

    with pytest.raises(ValueError, match="source spans"):
        C._source_span([Missing()])


def test_source_span_validates_each_block_and_group(C):
    need(C, "_source_span")
    from app.ingestion.parser import Block

    valid = Block("paragraph", "valid", source_pos=10, end_pos=20, source_group=0)
    reversed_block = Block("paragraph", "bad", source_pos=30, end_pos=25, source_group=0)
    with pytest.raises(ValueError, match="invalid block"):
        C._source_span([valid, reversed_block])

    other_group = Block("paragraph", "other", source_pos=20, end_pos=30, source_group=1)
    with pytest.raises(ValueError, match="source groups"):
        C._source_span([valid, other_group])


def test_source_span_rejects_overlap_and_document_overflow(C):
    need(C, "_source_span")
    from app.ingestion.parser import Block

    first = Block("paragraph", "first", source_pos=10, end_pos=25)
    overlapping = Block("paragraph", "second", source_pos=20, end_pos=30)
    with pytest.raises(ValueError, match="overlap"):
        C._source_span([first, overlapping])
    with pytest.raises(ValueError, match="source length"):
        C._source_span([first], source_length=20)
