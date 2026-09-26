"""Exercise review behavior at service and HTTP boundaries."""

import asyncio
from typing import cast

import pytest

from app.api.dependencies import create_admin_services
from app.api.review.previews import _retrieval_preview, _review_preview
from app.api.review.runtime import RuntimeApiServices
from app.db.session_factory import SessionFactory
from app.retrieval.embedding.provider import DeterministicEmbeddingProvider


@pytest.mark.parametrize("strategy", ["vector", "lexical", "hybrid"])
def test_preview_strategies_use_the_shared_search_contract(monkeypatch, hit, strategy):
    """Run each valid preview plan through retrieval and preserve its actual component ranks."""
    from contextlib import asynccontextmanager

    from app.api.review.previews import RetrievalPreviewRequest
    from app.retrieval.search import service as retrieval, service as search_consistency

    calls = []

    async def prepare(*args):
        """Skip the database readiness probe, retaining the real retrieval dispatcher."""
        del args

    async def vector_search(*args, **kwargs):
        """Return a recorded vector candidate without querying PostgreSQL."""
        calls.append("vector")
        return [hit]

    async def lexical_search(*args, **kwargs):
        """Return a recorded lexical candidate without querying PostgreSQL."""
        calls.append("lexical")
        return [hit]

    @asynccontextmanager
    async def no_database():
        """Provide the session seam consumed by the isolated search components."""
        yield None

    monkeypatch.setattr(search_consistency, "prepare_search", prepare)
    monkeypatch.setattr(retrieval, "vector_search", vector_search)
    monkeypatch.setattr(retrieval, "lexical_search", lexical_search)
    services = create_admin_services(
        runtime=RuntimeApiServices(
            embedding_provider=DeterministicEmbeddingProvider(),
            session_factory=cast(SessionFactory, no_database),
        )
    )
    request = RetrievalPreviewRequest.model_validate(
        {
            "query": "Revenue?",
            "profile": {
                "strategy": strategy,
                "lexical_ranker": None if strategy == "vector" else "ts_rank_cd",
            },
            "filters": {"languages": ["en"]},
        }
    )
    result = asyncio.run(_retrieval_preview(services, request))
    expected = [lane for lane in ("vector", "lexical") if strategy in {lane, "hybrid"}]
    assert calls == expected
    assert [item.chunk_id for item in result.results] == [hit.chunk_id]
    assert result.component_rankings["vector"] == ((hit.chunk_id,) if "vector" in expected else ())
    assert result.component_rankings["lexical_by_language"] == (
        {"en": (hit.chunk_id,)} if "lexical" in expected else {}
    )


def test_previews_run_and_present_the_effective_bm25_values(monkeypatch):
    """A preview keeps its stated BM25 value and takes the rest from the server settings."""
    from contextlib import asynccontextmanager

    from app.api.review.previews import RetrievalPreviewRequest, ReviewPreviewRequest
    from app.retrieval.search.service import ComponentRankings, RetrievalResult

    calls = []

    async def retrieve(session, query, **kwargs):
        """Capture the hybrid retrieval plan without a database."""
        del session, query
        calls.append(kwargs)
        return RetrievalResult(
            hits=(),
            candidates=(),
            score_stage="rrf",
            component_rankings=ComponentRankings(vector=(), lexical=()),
        )

    @asynccontextmanager
    async def no_database():
        """Open no session; the recording retrieval never uses one."""
        yield None

    services = create_admin_services(
        runtime=RuntimeApiServices(
            embedding_provider=DeterministicEmbeddingProvider(),
            session_factory=cast(SessionFactory, no_database),
            retrieval_service=retrieve,
            bm25_k1=1.6,
            bm25_b=0.5,
            bm25_idf="robertson",
        )
    )
    payload = {"query": "Revenue?", "profile": {"lexical_ranker": "bm25", "bm25_b": 0.3}}
    response = asyncio.run(
        _retrieval_preview(services, RetrievalPreviewRequest.model_validate(payload))
    )
    assert [
        (call["plan"].bm25_k1, call["plan"].bm25_b, call["plan"].bm25_idf) for call in calls
    ] == [(1.6, 0.3, "robertson")]
    assert (response.profile.bm25_k1, response.profile.bm25_b, response.profile.bm25_idf) == (
        1.6,
        0.3,
        "robertson",
    )
    reviewed = []

    async def review(review):
        """Capture the Custom plan the review preview hands to the workflow."""
        reviewed.append(review)
        raise LookupError("review boundary reached")

    monkeypatch.setattr(services.runtime, "review", review)
    with pytest.raises(LookupError, match="review boundary"):
        asyncio.run(_review_preview(services, ReviewPreviewRequest.model_validate(payload)))
    custom = reviewed[0].session_profile.custom_retrieval
    assert (custom.bm25_k1, custom.bm25_b, custom.bm25_idf) == (1.6, 0.3, "robertson")


def test_corpus_update_refuses_preview_before_translation_or_database(monkeypatch):
    """An exclusive corpus writer blocks routed previews before they spend model work."""
    from unittest.mock import AsyncMock, Mock

    from app.api.errors import ApiProblemError
    from app.api.review.previews import RetrievalPreviewRequest

    database = Mock(side_effect=AssertionError("blocked preview opened a database session"))
    runtime = RuntimeApiServices(
        embedding_provider=DeterministicEmbeddingProvider(), session_factory=database
    )
    engine = AsyncMock(
        side_effect=AssertionError("blocked preview resolved a translation provider")
    )
    monkeypatch.setattr(runtime._engines, "resolve_engine", engine)
    dependencies = create_admin_services(runtime=runtime)
    request = RetrievalPreviewRequest.model_validate(
        {
            "query": "매출은 얼마입니까?",
            "profile": {"route_by_language": True},
            "filters": {"languages": ["en"]},
        }
    )

    async def scenario():
        """Hold the real writer admission barrier while submitting the preview."""
        async with runtime.corpus_access.update():
            with pytest.raises(ApiProblemError) as refusal:
                await _retrieval_preview(dependencies, request)
        assert refusal.value.status_code == 503
        assert refusal.value.error.code == "corpus_updating"

    asyncio.run(scenario())
    engine.assert_not_awaited()
    database.assert_not_called()
