"""Chunk types, configuration, and source-coordinate contracts."""

import pytest

import app.ingestion.chunking as chunking
from app.ingestion.tokens import InputBudget


@pytest.mark.parametrize(
    ("field", "value"),
    (("target_tokens", 0), ("target_tokens", -1), ("max_tokens", 8193), ("max_chars", 0)),
)
def test_config_rejects_non_positive_limits(field, value):
    """Reject invalid token and character bounds."""
    with pytest.raises(ValueError):
        InputBudget(**{field: value})


def test_source_span_fails_closed():
    """Reject chunk blocks that lack complete source coordinates."""

    class Missing:
        source_pos = None
        end_pos = None

    with pytest.raises(ValueError, match="source spans"):
        chunking._source_span([Missing()])


def test_source_span_validates_each_block_and_group():
    """Reject invalid coordinates and mixed narrative source groups."""
    from app.ingestion.parsing.models import Block

    valid = Block("paragraph", "valid", source_pos=10, end_pos=20, source_group=0)
    reversed_block = Block("paragraph", "bad", source_pos=30, end_pos=25, source_group=0)
    with pytest.raises(ValueError, match="invalid block"):
        chunking._source_span([valid, reversed_block])

    other_group = Block("paragraph", "other", source_pos=20, end_pos=30, source_group=1)
    with pytest.raises(ValueError, match="source groups"):
        chunking._source_span([valid, other_group])


def test_source_span_rejects_overlap_and_document_overflow():
    """Reject overlapping blocks and spans beyond the source document."""
    from app.ingestion.parsing.models import Block

    first = Block("paragraph", "first", source_pos=10, end_pos=25)
    overlapping = Block("paragraph", "second", source_pos=20, end_pos=30)
    with pytest.raises(ValueError, match="overlap"):
        chunking._source_span([first, overlapping])
    with pytest.raises(ValueError, match="source length"):
        chunking._source_span([first], source_length=20)


def test_source_span_allows_gaps_within_one_source_group():
    """Return one enclosing citation span when the parser omits page furniture."""
    from app.ingestion.parsing.models import Block

    first = Block("paragraph", "first", source_pos=10, end_pos=20, source_group=0)
    second = Block("paragraph", "second", source_pos=40, end_pos=50, source_group=0)

    assert chunking._source_span([first, second]) == (10, 50)
