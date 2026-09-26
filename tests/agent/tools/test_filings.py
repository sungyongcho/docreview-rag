"""Built-in filing tools: payload shapes, evidence extraction, and filters."""

import asyncio
import sys
from types import SimpleNamespace

from pydantic import ValidationError
import pytest

from app.agent.tools.filings import build_default_registry
from app.agent.tools.registry import ToolError
from app.retrieval.embedding.provider import DeterministicEmbeddingProvider
from tests.agent.support import FakeSessionFactory
from tests.retrieval.support import hit


class CountingEmbeddings(DeterministicEmbeddingProvider):
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
        provider = kwargs.get("provider")
        if provider is not None:
            await provider.embed_query(query)
        return SimpleNamespace(hits=responses[len(calls) - 1])

    module = sys.modules[build_default_registry.__module__]
    monkeypatch.setattr(module, "retrieve", fake_retrieve)
    return calls


def evidence_ids(tool, output):
    """Run the tool's evidence extractor, which every built-in tool must declare."""
    assert tool.evidence_ids is not None
    return tuple(item.chunk_id for item in tool.evidence_ids(output))


def test_search_filings_maps_filters_and_extracts_evidence(monkeypatch):
    """Map the tool arguments onto retrieval filters and close the per-call session."""
    calls = patch_retrieve(monkeypatch, [(hit(7, 0.5), hit(9, 0.5))])
    factory = FakeSessionFactory()
    registry = build_default_registry(factory)
    tool = registry.get("search_filings")

    params = tool.parameters.model_validate({"query": "revenue", "issuers": ["NVDA"]})
    output = asyncio.run(tool.run(params))

    (call,) = calls
    assert call[0] == "revenue"
    assert call[1]["k"] == 5
    assert call[1]["filters"].issuers == ("NVDA",)
    assert call[1]["filters"].fiscal_years == ()
    assert output["hits"][0]["chunk_id"] == 7
    assert "snippet" in output["hits"][0]
    assert evidence_ids(tool, output) == (7, 9)
    (session,) = factory.sessions
    assert session.closed
    assert not session.in_transaction()


def test_search_filings_uses_the_configured_default_k(monkeypatch):
    """Fall back to the registry's search_k when the caller omits k."""
    calls = patch_retrieve(monkeypatch, [(hit(7, 0.5),)])
    registry = build_default_registry(FakeSessionFactory(), search_k=7)

    tool = registry.get("search_filings")
    asyncio.run(tool.run(tool.parameters.model_validate({"query": "revenue"})))

    (call,) = calls
    assert call[1]["k"] == 7
    with pytest.raises(ValueError, match="search_k"):
        build_default_registry(FakeSessionFactory(), search_k=0)


def test_fetch_chunk_returns_the_stored_row_and_rejects_missing_ids():
    """Return the whole stored chunk, and name a missing id as an error."""
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
    factory = FakeSessionFactory(chunk)
    registry = build_default_registry(factory)
    tool = registry.get("fetch_chunk")

    output = asyncio.run(tool.run(tool.parameters.model_validate({"chunk_id": 7})))

    (session,) = factory.sessions
    assert session.requested_ids == [7]
    assert output["doc_id"] == "NVDA-FY2024"
    # The tool promises the chunk in full: a 9,000-character body is returned whole.
    assert output["body"] == chunk.body
    assert evidence_ids(tool, output) == (7,)
    assert session.closed

    missing_factory = FakeSessionFactory()
    missing = build_default_registry(missing_factory).get("fetch_chunk")
    with pytest.raises(ToolError, match="chunk 99 does not exist"):
        asyncio.run(missing.run(missing.parameters.model_validate({"chunk_id": 99})))
    (missing_session,) = missing_factory.sessions
    assert missing_session.closed
    assert not missing_session.in_transaction()


def test_compare_years_groups_hits_per_sorted_year(monkeypatch):
    """Query each year separately through one shared query-embedding cache, group the
    results in year order, and require a real span."""
    calls = patch_retrieve(monkeypatch, [(hit(1, 0.5),), (hit(2, 0.5),)])
    factory = FakeSessionFactory()
    embeddings = CountingEmbeddings()
    registry = build_default_registry(factory, embedding_provider=embeddings)
    tool = registry.get("compare_years")

    params = tool.parameters.model_validate(
        {"query": "revenue", "issuer": "NVDA", "fiscal_years": [2024, 2023]}
    )
    output = asyncio.run(tool.run(params))

    assert [call[1]["filters"].fiscal_years for call in calls] == [(2023,), (2024,)]
    assert [year["fiscal_year"] for year in output["years"]] == [2023, 2024]
    assert evidence_ids(tool, output) == (1, 2)
    assert embeddings.query_calls == 1
    (session,) = factory.sessions
    assert session.closed
    assert not session.in_transaction()

    with pytest.raises(ValidationError, match="two to four"):
        tool.parameters.model_validate(
            {"query": "revenue", "issuer": "NVDA", "fiscal_years": [2024]}
        )


@pytest.mark.parametrize(
    ("name", "arguments", "field"),
    [
        ("search_filings", {"query": "revenue", "issuers": [""]}, "issuers"),
        ("search_filings", {"query": "revenue", "fiscal_years": [0]}, "fiscal_years"),
        ("search_filings", {"query": "revenue", "forms": ["x" * 17]}, "forms"),
        ("search_filings", {"query": "   "}, "query"),
        (
            "compare_years",
            {"query": "revenue", "issuer": "NVDA", "fiscal_years": [0, 2024]},
            "fiscal_years",
        ),
        (
            "compare_years",
            {"query": "   ", "issuer": "NVDA", "fiscal_years": [2023, 2024]},
            "query",
        ),
    ],
)
def test_filter_violations_are_reported_as_invalid_arguments(name, arguments, field):
    """A schema-shaped call the retrieval contract rejects names the field instead of hiding it."""
    from app.agent.tools.registry import execute_tool

    registry = build_default_registry(FakeSessionFactory())

    outcome = asyncio.run(execute_tool(registry, name, arguments))

    assert outcome.error is not None
    assert outcome.error.startswith(f"invalid arguments for {name}:"), outcome.error
    assert field in outcome.error
