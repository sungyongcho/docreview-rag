"""L1 retrieval value-object and module-switch contract."""

import math
from typing import Any

from pydantic import ValidationError
import pytest

from app.db.models import Chunk, Document
from tests.retrieval.conftest import load_retrieval_module
from tests.support import need

SOURCE_SHA256 = "a" * 64


def hit_values(**changes) -> dict[str, Any]:
    """Return one valid hit payload with optional field replacements."""
    values: dict[str, Any] = {
        "chunk_id": 10,
        "doc_id": "NVDA-FY2024",
        "item": "7",
        "kind": "text",
        "citation": "NVDA FY2024 · Item 7",
        "start_char": 100,
        "end_char": 160,
        "source_sha256": SOURCE_SHA256,
        "body": "Research and development expenses increased.",
        "context_header": "NVDA FY2024 · Item 7",
        "index_text": ("NVDA FY2024 · Item 7\n\nResearch and development expenses increased."),
        "score": 0.75,
    }
    values.update(changes)
    return values


def test_chunk_hit_preserves_the_database_and_citation_surface(R):
    need(R, "ChunkHit")
    hit = R.ChunkHit(**hit_values())

    assert hit.chunk_id == 10
    assert hit.item == "7"
    assert hit.kind == "text"
    assert (hit.start_char, hit.end_char) == (100, 160)
    assert hit.source_sha256 == SOURCE_SHA256
    assert hit.index_text == f"{hit.context_header}\n\n{hit.body}"

    with pytest.raises(ValidationError):
        hit.score = 1.0


def test_chunk_hit_fields_match_the_current_sqlalchemy_models(R):
    need(R, "ChunkHit")
    assert set(R.ChunkHit.model_fields) == {
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
    assert set(R.ChunkHit.model_fields) - {"chunk_id", "score"} <= chunk_columns
    assert "id" in chunk_columns
    assert "doc_id" in Document.__table__.columns


def test_chunk_hit_accepts_body_as_index_text_when_context_is_empty(R):
    need(R, "ChunkHit")
    hit = R.ChunkHit(
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
def test_chunk_hit_rejects_invalid_database_or_runtime_values(R, changes):
    need(R, "ChunkHit")
    with pytest.raises(ValidationError):
        R.ChunkHit(**hit_values(**changes))


def test_chunk_hit_forbids_unknown_fields(R):
    need(R, "ChunkHit")
    with pytest.raises(ValidationError):
        R.ChunkHit(**hit_values(distance=0.25))


def test_filters_are_frozen_and_canonical(R):
    need(R, "RetrievalFilters")
    filters = R.RetrievalFilters(
        doc_ids=["NVDA-FY2024", "AMD-FY2023", "NVDA-FY2024"],
        tickers=["NVDA", "AMD"],
        fiscal_years=[2024, 2023, 2024],
        forms=["10-K", "10-K"],
        items=["7", None, "7"],
        kinds=["table", "text", "table"],
    )

    assert filters.doc_ids == ("AMD-FY2023", "NVDA-FY2024")
    assert filters.tickers == ("AMD", "NVDA")
    assert filters.fiscal_years == (2023, 2024)
    assert filters.forms == ("10-K",)
    assert filters.items == (None, "7")
    assert filters.kinds == ("text", "table")
    assert filters == R.RetrievalFilters(
        doc_ids=["AMD-FY2023", "NVDA-FY2024"],
        tickers=["AMD", "NVDA"],
        fiscal_years=[2023, 2024],
        forms=["10-K"],
        items=[None, "7"],
        kinds=["text", "table"],
    )

    with pytest.raises(ValidationError):
        filters.items = ("8",)


@pytest.mark.parametrize(
    "changes",
    [
        {"doc_ids": [""]},
        {"tickers": [""]},
        {"fiscal_years": [0]},
        {"forms": [""]},
        {"items": [""]},
        {"kinds": ["image"]},
        {"unknown": ["value"]},
    ],
)
def test_filters_reject_invalid_dimensions(R, changes):
    need(R, "RetrievalFilters")
    with pytest.raises(ValidationError):
        R.RetrievalFilters(**changes)


def test_sort_hits_uses_stable_tie_breakers_without_mutating_input(R):
    need(R, "ChunkHit", "sort_hits")
    hits = [
        R.ChunkHit(**hit_values(chunk_id=4, doc_id="B", score=0.5)),
        R.ChunkHit(**hit_values(chunk_id=3, doc_id="A", start_char=110, end_char=170, score=0.5)),
        R.ChunkHit(**hit_values(chunk_id=2, doc_id="A", score=0.5)),
        R.ChunkHit(**hit_values(chunk_id=1, doc_id="Z", score=0.9)),
    ]
    original_ids = [hit.chunk_id for hit in hits]

    ordered = R.sort_hits(hits)

    assert [hit.chunk_id for hit in ordered] == [1, 2, 3, 4]
    assert [hit.chunk_id for hit in hits] == original_ids


def test_package_exports_the_public_contract(R):
    need(R, "ChunkHit", "ChunkKind", "RetrievalFilters", "normalize_query", "sort_hits")
    assert R.ChunkHit.__module__ == "app.retrieval.types"
    assert R.normalize_query("NVDA R&D") == "NVDA research development"

    from app.retrieval.service import normalize_query

    assert R.normalize_query is normalize_query


def test_retrieval_module_override_loads_the_canonical_package(monkeypatch):
    monkeypatch.setenv("RETRIEVAL_MODULE", "app.retrieval")
    assert load_retrieval_module().__name__ == "app.retrieval"
