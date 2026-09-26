"""Retrieval value-object and deterministic ordering tests."""

import math

from pydantic import ValidationError
import pytest

from app.retrieval import lexical, types as retrieval_types
from tests.retrieval.support import SOURCE_SHA256, hit_values


def test_chunk_hit_preserves_the_database_and_citation_surface():
    """Preserve complete evidence and citation fields in immutable hits."""
    hit = retrieval_types.ChunkHit(**hit_values())

    assert hit.chunk_id == 10
    assert hit.item == "7"
    assert hit.kind == "text"
    assert (hit.start_char, hit.end_char) == (100, 160)
    assert hit.source_sha256 == SOURCE_SHA256
    assert hit.index_text == f"{hit.context_header}\n\n{hit.body}"

    with pytest.raises(ValidationError):
        hit.score = 1.0


def test_searched_rows_carry_exactly_the_chunk_hit_fields():
    """Select every field the hit contract validates and nothing it would reject."""
    statement = lexical.lexical_statement("research expense", 1)

    assert set(statement.selected_columns.keys()) == set(retrieval_types.ChunkHit.model_fields)


def test_chunk_hit_accepts_body_as_index_text_when_context_is_empty():
    """Allow body-only indexed text when no context header exists."""
    hit = retrieval_types.ChunkHit(
        **hit_values(
            body="Research evidence.",
            context_header="",
            index_text="Research evidence.",
        )
    )
    assert hit.index_text == "Research evidence."


@pytest.mark.parametrize(
    "changes",
    [
        pytest.param({"chunk_id": 0}, id="non-positive-chunk-id"),
        pytest.param({"chunk_id": "10"}, id="coercible-string-chunk-id"),
        pytest.param({"doc_id": ""}, id="blank-doc-id"),
        pytest.param({"item": "123456789"}, id="overlong-item"),
        pytest.param({"kind": "image"}, id="unknown-kind"),
        pytest.param({"citation": ""}, id="blank-citation"),
        pytest.param({"start_char": -1}, id="negative-start"),
        pytest.param({"end_char": 100}, id="end-not-after-start"),
        pytest.param({"source_sha256": "A" * 64}, id="uppercase-source-digest"),
        pytest.param({"body": ""}, id="blank-body"),
        pytest.param({"index_text": "stale indexed text"}, id="index-text-detached-from-body"),
        pytest.param({"score": math.nan}, id="nan-score"),
        pytest.param({"score": math.inf}, id="infinite-score"),
        pytest.param({"score": "0.75"}, id="string-score"),
        pytest.param({"distance": 0.25}, id="unknown-field"),
    ],
)
def test_chunk_hit_rejects_values_outside_its_contract(changes):
    """Reject invalid identities, spans, content, scores, and fields the contract lacks."""
    with pytest.raises(ValidationError):
        retrieval_types.ChunkHit(**hit_values(**changes))


def test_filters_are_frozen_and_canonical():
    """Freeze filters and canonicalize duplicate values deterministically."""
    filters = retrieval_types.RetrievalFilters.model_validate(
        {
            "doc_ids": ["NVDA-FY2024", "AMD-FY2023", "NVDA-FY2024"],
            "issuers": ["NVDA", "AMD"],
            "fiscal_years": [2024, 2023, 2024],
            "forms": ["10-K", "10-K"],
            "items": ["7", None, "7"],
            "kinds": ["table", "text", "table"],
            "languages": ["ko", "en", "ko"],
        }
    )

    assert filters.doc_ids == ("AMD-FY2023", "NVDA-FY2024")
    assert filters.issuers == ("AMD", "NVDA")
    assert filters.fiscal_years == (2023, 2024)
    assert filters.forms == ("10-K",)
    assert filters.items == (None, "7")
    assert filters.kinds == ("text", "table")
    assert filters.languages == ("en", "ko")
    assert filters == retrieval_types.RetrievalFilters.model_validate(
        {
            "doc_ids": ["AMD-FY2023", "NVDA-FY2024"],
            "issuers": ["AMD", "NVDA"],
            "fiscal_years": [2023, 2024],
            "forms": ["10-K"],
            "items": [None, "7"],
            "kinds": ["text", "table"],
            "languages": ["en", "ko"],
        }
    )

    with pytest.raises(ValidationError):
        filters.items = ("8",)


@pytest.mark.parametrize(
    "changes",
    [
        pytest.param({"doc_ids": [""]}, id="blank-doc-id"),
        pytest.param({"issuers": [""]}, id="blank-issuer"),
        pytest.param({"fiscal_years": [0]}, id="non-positive-year"),
        pytest.param({"forms": [""]}, id="blank-form"),
        pytest.param({"items": [""]}, id="blank-item"),
        pytest.param({"kinds": ["image"]}, id="unknown-kind"),
        pytest.param({"languages": ["KOR"]}, id="non-two-letter-language"),
        pytest.param({"unknown": ["value"]}, id="unknown-dimension"),
    ],
)
def test_filters_reject_invalid_dimensions(changes):
    """Reject invalid document, issuer, year, form, item, kind, and language filters."""
    with pytest.raises(ValidationError):
        retrieval_types.RetrievalFilters(**changes)


def test_sort_hits_uses_stable_tie_breakers_without_mutating_input():
    """Sort by relevance and source identity without mutating input hits."""
    hits = [
        retrieval_types.ChunkHit(**hit_values(chunk_id=4, doc_id="B", score=0.5)),
        retrieval_types.ChunkHit(
            **hit_values(chunk_id=3, doc_id="A", start_char=110, end_char=170, score=0.5)
        ),
        retrieval_types.ChunkHit(**hit_values(chunk_id=2, doc_id="A", score=0.5)),
        retrieval_types.ChunkHit(**hit_values(chunk_id=1, doc_id="Z", score=0.9)),
    ]
    original_ids = [hit.chunk_id for hit in hits]

    ordered = retrieval_types.sort_hits(hits)

    assert [hit.chunk_id for hit in ordered] == [1, 2, 3, 4]
    assert [hit.chunk_id for hit in hits] == original_ids


def test_sort_hits_uses_c_collation_compatible_codepoint_order_for_text_ties():
    """Match SQL's explicit C collation for punctuation and case-sensitive ties."""
    hits = [
        retrieval_types.ChunkHit(**hit_values(chunk_id=4, doc_id="a", score=0.5)),
        retrieval_types.ChunkHit(**hit_values(chunk_id=3, doc_id="NVDAB-FY2024", score=0.5)),
        retrieval_types.ChunkHit(**hit_values(chunk_id=2, doc_id="NVDA-FY2024", score=0.5)),
        retrieval_types.ChunkHit(**hit_values(chunk_id=1, doc_id="B", score=0.5)),
    ]

    ordered = retrieval_types.sort_hits(hits)

    assert [hit.chunk_id for hit in ordered] == [1, 2, 3, 4]
