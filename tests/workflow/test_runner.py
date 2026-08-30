"""Retrieval binding the workflow runner exposes to its caller."""

import asyncio

import pytest

from app.retrieval.types import RetrievalFilters
from app.workflow import runner
from tests.workflow.support import hit


@pytest.mark.parametrize("route_by_language", [True, False])
def test_the_session_retriever_forwards_every_ranking_knob_it_was_bound_with(
    monkeypatch, route_by_language
):
    """Retrieve under the configuration the caller named, routing included."""
    seen: dict[str, object] = {}

    async def retrieve(session, query, **kwargs):
        seen.update(kwargs)
        return object()

    monkeypatch.setattr(runner, "retrieve", retrieve)
    bound = runner.make_session_retriever(
        object(),
        candidate_k=20,
        route_by_language=route_by_language,
        lexical_ranker="bm25",
        bm25_k1=1.5,
    )

    asyncio.run(bound("AMD의 매출은?", 5, RetrievalFilters()))

    # A run is reproducible only if its recorded configuration is the one it executed,
    # so no knob may be dropped between the binder and the service.
    assert seen["route_by_language"] is route_by_language
    assert seen["lexical_ranker"] == "bm25"
    assert seen["bm25_k1"] == 1.5


def test_the_session_retriever_widens_the_candidate_pool_to_the_overfetched_k(monkeypatch):
    """Widen a candidate pool the workflow's over-fetched hit count would overflow."""
    seen: dict[str, object] = {}

    async def retrieve(session, query, **kwargs):
        seen.update(kwargs)
        return hit(1)

    monkeypatch.setattr(runner, "retrieve", retrieve)
    bound = runner.make_session_retriever(object(), candidate_k=5)

    asyncio.run(bound("query", 15, RetrievalFilters()))

    assert seen["candidate_k"] == 15
