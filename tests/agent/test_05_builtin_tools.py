"""M9.4 built-in filing tools: payload shapes, evidence extraction, and filters."""

import asyncio
import sys
from types import SimpleNamespace

from pydantic import ValidationError
import pytest

from app.retrieval import ChunkHit
from tests.retrieval.test_01_contract import hit_values
from tests.support import need


def hit(chunk_id, *, score=0.5):
    start = chunk_id * 100
    return ChunkHit(
        **hit_values(chunk_id=chunk_id, score=score, start_char=start, end_char=start + 50)
    )


class FakeSession:
    """Duck-typed async session capturing chunk lookups."""

    def __init__(self, chunk=None):
        self.chunk = chunk
        self.requested_ids = []
        self.transaction_open = False
        self.rollback_count = 0

    async def get(self, model, chunk_id):
        del model
        self.requested_ids.append(chunk_id)
        self.transaction_open = True
        return self.chunk

    def in_transaction(self):
        return self.transaction_open

    async def rollback(self):
        self.transaction_open = False
        self.rollback_count += 1


def patch_retrieve(AG, monkeypatch, responses):
    calls = []

    async def fake_retrieve(session, query, **kwargs):
        session.transaction_open = True
        calls.append((query, kwargs))
        return SimpleNamespace(hits=responses[len(calls) - 1])

    module = sys.modules[AG.build_default_registry.__module__]
    monkeypatch.setattr(module, "retrieve", fake_retrieve)
    return calls


def test_search_filings_maps_filters_and_extracts_evidence(AG, monkeypatch):
    need(AG, "build_default_registry")
    calls = patch_retrieve(AG, monkeypatch, [(hit(7), hit(9))])
    session = FakeSession()
    registry = AG.build_default_registry(session)
    tool = registry.get("search_filings")

    params = tool.parameters.model_validate(
        {"query": "revenue", "k": None, "tickers": ["NVDA"], "fiscal_years": [2024], "forms": None}
    )
    output = asyncio.run(tool.run(params))

    (call,) = calls
    assert call[0] == "revenue"
    assert call[1]["k"] == 5
    assert call[1]["filters"].tickers == ("NVDA",)
    assert call[1]["filters"].fiscal_years == (2024,)
    assert output["hits"][0]["chunk_id"] == 7
    assert "snippet" in output["hits"][0]
    assert tuple(item.chunk_id for item in tool.evidence_ids(output)) == (7, 9)
    assert session.rollback_count == 1
    assert not session.in_transaction()


def test_fetch_chunk_returns_the_stored_row_and_rejects_missing_ids(AG):
    need(AG, "build_default_registry")
    chunk = SimpleNamespace(
        id=7,
        doc_id="NVDA-FY2024",
        citation="NVDA FY2024 · Item 7",
        start_char=700,
        end_char=750,
        source_sha256="a" * 64,
        context_header="NVDA FY2024 · Item 7",
        body="Research and development expenses increased." * 200,
    )
    session = FakeSession(chunk)
    registry = AG.build_default_registry(session)
    tool = registry.get("fetch_chunk")

    output = asyncio.run(tool.run(tool.parameters.model_validate({"chunk_id": 7})))

    assert session.requested_ids == [7]
    assert output["doc_id"] == "NVDA-FY2024"
    assert len(output["body"]) <= 4_000
    assert tuple(item.chunk_id for item in tool.evidence_ids(output)) == (7,)
    assert session.rollback_count == 1

    missing_session = FakeSession()
    missing = AG.build_default_registry(missing_session).get("fetch_chunk")
    with pytest.raises(ValueError, match="does not exist"):
        asyncio.run(missing.run(missing.parameters.model_validate({"chunk_id": 99})))
    assert missing_session.rollback_count == 1
    assert not missing_session.in_transaction()


def test_compare_years_groups_hits_per_sorted_year(AG, monkeypatch):
    need(AG, "build_default_registry")
    calls = patch_retrieve(AG, monkeypatch, [(hit(1),), (hit(2),)])
    session = FakeSession()
    registry = AG.build_default_registry(session)
    tool = registry.get("compare_years")

    params = tool.parameters.model_validate(
        {"query": "revenue", "ticker": "NVDA", "fiscal_years": [2024, 2023], "k": None}
    )
    output = asyncio.run(tool.run(params))

    assert [call[1]["filters"].fiscal_years for call in calls] == [(2023,), (2024,)]
    assert [year["fiscal_year"] for year in output["years"]] == [2023, 2024]
    assert tuple(item.chunk_id for item in tool.evidence_ids(output)) == (1, 2)
    assert session.rollback_count == 2

    with pytest.raises(ValidationError, match="two to four"):
        tool.parameters.model_validate(
            {"query": "revenue", "ticker": "NVDA", "fiscal_years": [2024], "k": None}
        )
