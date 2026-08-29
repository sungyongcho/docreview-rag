"""Retrieval value-object and deterministic ordering tests."""

import math

from pydantic import ValidationError
import pytest

from app.db.models import Chunk, Document
from app.retrieval import types as retrieval_types
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


def test_chunk_hit_fields_match_the_current_sqlalchemy_models():
    """Keep the hit contract aligned with persisted chunk columns."""
    assert set(retrieval_types.ChunkHit.model_fields) == {
        "chunk_id",
        "doc_id",
        "item",
        "kind",
        "citation",
        "start_char",
        "end_char",
        "source_sha256",
        "body",
        "context_header",
        "index_text",
        "score",
    }

    chunk_columns = set(Chunk.__table__.columns.keys())
    assert set(retrieval_types.ChunkHit.model_fields) - {"chunk_id", "score"} <= chunk_columns
    assert "id" in chunk_columns
    assert "doc_id" in Document.__table__.columns


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


def test_chunk_hit_uses_the_canonical_index_text_composer(monkeypatch):
    """Delegate the persistence-boundary invariant to the ingestion helper."""
    calls: list[tuple[str, str]] = []

    def compose(context_header: str, body: str) -> str:
        calls.append((context_header, body))
        return "canonical index text"

    monkeypatch.setattr(retrieval_types, "compose_index_text", compose)
    values = hit_values(index_text="canonical index text")

    retrieval_types.ChunkHit(**values)

    assert calls == [(values["context_header"], values["body"])]


@pytest.mark.parametrize(
    "changes",
    [
        {"chunk_id": 0},
        {"chunk_id": "10"},
        {"doc_id": ""},
        {"item": "123456789"},
        {"kind": "image"},
        {"citation": ""},
        {"start_char": -1},
        {"end_char": 100},
        {"source_sha256": "A" * 64},
        {"body": ""},
        {"index_text": "stale indexed text"},
        {"score": math.nan},
        {"score": math.inf},
        {"score": "0.75"},
    ],
)
def test_chunk_hit_rejects_invalid_database_or_runtime_values(changes):
    """Reject invalid database identities, spans, content, and scores."""
    with pytest.raises(ValidationError):
        retrieval_types.ChunkHit(**hit_values(**changes))


def test_chunk_hit_forbids_unknown_fields():
    """Reject fields outside the strict retrieval hit contract."""
    with pytest.raises(ValidationError):
        retrieval_types.ChunkHit(**hit_values(distance=0.25))


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
        }
    )

    assert filters.doc_ids == ("AMD-FY2023", "NVDA-FY2024")
    assert filters.issuers == ("AMD", "NVDA")
    assert filters.fiscal_years == (2023, 2024)
    assert filters.forms == ("10-K",)
    assert filters.items == (None, "7")
    assert filters.kinds == ("text", "table")
    assert filters == retrieval_types.RetrievalFilters.model_validate(
        {
            "doc_ids": ["AMD-FY2023", "NVDA-FY2024"],
            "issuers": ["AMD", "NVDA"],
            "fiscal_years": [2023, 2024],
            "forms": ["10-K"],
            "items": [None, "7"],
            "kinds": ["text", "table"],
        }
    )

    with pytest.raises(ValidationError):
        filters.items = ("8",)


@pytest.mark.parametrize(
    "changes",
    [
        {"doc_ids": [""]},
        {"issuers": [""]},
        {"fiscal_years": [0]},
        {"forms": [""]},
        {"items": [""]},
        {"kinds": ["image"]},
        {"unknown": ["value"]},
    ],
)
def test_filters_reject_invalid_dimensions(changes):
    """Reject invalid document, issuer, year, form, item, and kind filters."""
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
