"""Built-in filing tools: payload shapes, evidence extraction, and filters."""

import asyncio
import sys
from types import SimpleNamespace
from typing import cast

from pydantic import ValidationError
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.builtin_tools import _QueryEmbeddingCache, build_default_registry
from app.agent.tools import ToolError
from app.retrieval.embeddings import DeterministicEmbeddingProvider, EmbeddingProvider
from app.retrieval.types import ChunkHit
from tests.retrieval.support import hit_values


def hit(chunk_id, *, score=0.5):
    """Build one retrieval hit with offsets derived from its chunk id."""
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
        """Record the requested chunk id and return the staged row."""
        del model
        self.requested_ids.append(chunk_id)
        self.transaction_open = True
        return self.chunk

    def in_transaction(self):
        """Report whether this fake session currently holds a transaction."""
        return self.transaction_open

    async def rollback(self):
        """Close the transaction and count the rollback."""
        self.transaction_open = False
        self.rollback_count += 1


def session_for(chunk=None):
    """Build one fake session cast to the AsyncSession contract the registry declares."""
    return cast(AsyncSession, FakeSession(chunk))


class CountingEmbeddings(EmbeddingProvider):
    """Deterministic provider that counts every real embedding request."""

    def __init__(self):
        self.dimensions = 4
        self.query_calls = 0
        self.document_calls = 0

    async def embed_documents(self, texts):
        """Return one constant vector per text, counting the batch."""
        self.document_calls += 1
        return [[0.0] * self.dimensions for _ in texts]

    async def embed_query(self, text):
        """Return one constant vector, counting the call."""
        del text
        self.query_calls += 1
        return [0.0] * self.dimensions


def patch_retrieve(monkeypatch, responses):
    """Replace retrieval with a recorder returning staged hits per call."""
    calls = []

    async def fake_retrieve(session, query, **kwargs):
        """Record the query and options, returning the next staged hits."""
        session.transaction_open = True
        calls.append((query, kwargs))
        return SimpleNamespace(hits=responses[len(calls) - 1])

    module = sys.modules[build_default_registry.__module__]
    monkeypatch.setattr(module, "retrieve", fake_retrieve)
    return calls


def evidence_ids(tool, output):
    """Run the tool's evidence extractor, which every built-in tool must declare."""
    assert tool.evidence_ids is not None
    return tuple(item.chunk_id for item in tool.evidence_ids(output))


def test_search_filings_maps_filters_and_extracts_evidence(monkeypatch):
    """Map the tool arguments onto retrieval filters and close the read transaction."""
    calls = patch_retrieve(monkeypatch, [(hit(7), hit(9))])
    session = session_for()
    registry = build_default_registry(session)
    tool = registry.get("search_filings")

    params = tool.parameters.model_validate(
        {"query": "revenue", "k": None, "issuers": ["NVDA"], "fiscal_years": [2024], "forms": None}
    )
    output = asyncio.run(tool.run(params))

    (call,) = calls
    assert call[0] == "revenue"
    assert call[1]["k"] == 5
    assert call[1]["filters"].issuers == ("NVDA",)
    assert call[1]["filters"].fiscal_years == (2024,)
    assert output["hits"][0]["chunk_id"] == 7
    assert "snippet" in output["hits"][0]
    assert evidence_ids(tool, output) == (7, 9)
    fake = cast(FakeSession, session)
    assert fake.rollback_count == 1
    assert not fake.in_transaction()


def test_fetch_chunk_returns_the_stored_row_and_rejects_missing_ids():
    """Return the stored chunk within the body cap, and name a missing id as an error."""
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
    session = session_for(chunk)
    registry = build_default_registry(session)
    tool = registry.get("fetch_chunk")

    output = asyncio.run(tool.run(tool.parameters.model_validate({"chunk_id": 7})))

    assert cast(FakeSession, session).requested_ids == [7]
    assert output["doc_id"] == "NVDA-FY2024"
    assert len(output["body"]) <= 4_000
    assert evidence_ids(tool, output) == (7,)
    assert cast(FakeSession, session).rollback_count == 1

    missing_session = session_for()
    missing = build_default_registry(missing_session).get("fetch_chunk")
    with pytest.raises(ToolError, match="chunk 99 does not exist"):
        asyncio.run(missing.run(missing.parameters.model_validate({"chunk_id": 99})))
    fake = cast(FakeSession, missing_session)
    assert fake.rollback_count == 1
    assert not fake.in_transaction()


def test_compare_years_groups_hits_per_sorted_year(monkeypatch):
    """Query each year separately, group the results in year order, and require a real span."""
    calls = patch_retrieve(monkeypatch, [(hit(1),), (hit(2),)])
    session = session_for()
    registry = build_default_registry(session, embedding_provider=DeterministicEmbeddingProvider())
    tool = registry.get("compare_years")

    params = tool.parameters.model_validate(
        {"query": "revenue", "issuer": "NVDA", "fiscal_years": [2024, 2023], "k": None}
    )
    output = asyncio.run(tool.run(params))

    assert [call[1]["filters"].fiscal_years for call in calls] == [(2023,), (2024,)]
    assert [year["fiscal_year"] for year in output["years"]] == [2023, 2024]
    assert evidence_ids(tool, output) == (1, 2)
    assert cast(FakeSession, session).rollback_count == 2

    with pytest.raises(ValidationError, match="two to four"):
        tool.parameters.model_validate(
            {"query": "revenue", "issuer": "NVDA", "fiscal_years": [2024], "k": None}
        )


def test_compare_years_shares_one_query_embedding_cache(monkeypatch):
    """Hand every per-year retrieval the same caching provider around the injected one."""
    calls = patch_retrieve(monkeypatch, [(hit(1),), (hit(2),), (hit(3),)])
    inner = CountingEmbeddings()
    registry = build_default_registry(session_for(), embedding_provider=inner)
    tool = registry.get("compare_years")

    params = tool.parameters.model_validate(
        {"query": "revenue", "issuer": "NVDA", "fiscal_years": [2022, 2023, 2024], "k": None}
    )
    asyncio.run(tool.run(params))

    providers = [call[1]["provider"] for call in calls]
    assert all(isinstance(provider, _QueryEmbeddingCache) for provider in providers)
    assert len({id(provider) for provider in providers}) == 1


def test_query_embedding_cache_embeds_each_distinct_text_once():
    """Reuse the vector for a repeated query and forward batch embedding unchanged."""
    inner = CountingEmbeddings()
    cache = _QueryEmbeddingCache(inner)

    first = asyncio.run(cache.embed_query("revenue"))
    second = asyncio.run(cache.embed_query("revenue"))
    asyncio.run(cache.embed_query("expenses"))
    asyncio.run(cache.embed_documents(["a", "b"]))

    assert first == second
    assert inner.query_calls == 2
    assert inner.document_calls == 1
    assert cache.dimensions == inner.dimensions
