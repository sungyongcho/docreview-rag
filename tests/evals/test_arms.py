"""Experiment-arm validation and the retrieval lane each arm binds."""

import asyncio
from types import SimpleNamespace

import pytest

from app.config import DEFAULT_BM25_B, DEFAULT_BM25_IDF, DEFAULT_BM25_K1
from app.evals import arms
from app.evals.arms import make_retriever, resolve_bm25_parameters


class _Provider:
    """Embedding provider stub that records the queries it is asked to embed."""

    dimensions = 384

    def __init__(self, seen=None):
        self.seen = seen

    async def embed_query(self, query):
        """Record the normalized query and return a zero vector."""
        if self.seen is not None:
            self.seen.append(query)
        return [0.0] * self.dimensions


def test_every_retrieval_strategy_receives_the_same_normalized_query(monkeypatch):
    """Normalize the query identically on every retrieval path."""
    queries = []

    async def lexical_search(_session, query, _k, _filters):
        queries.append(query)
        return []

    async def vector_search(_session, _vector, *, k, filters):
        assert k == 1
        assert filters is None
        return []

    async def retrieve(_session, query, **_kwargs):
        queries.append(query)
        return SimpleNamespace(hits=())

    monkeypatch.setattr(arms, "lexical_search", lexical_search)
    monkeypatch.setattr(arms, "vector_search", vector_search)
    monkeypatch.setattr(arms, "retrieve", retrieve)
    provider = _Provider(queries)

    retrievers = (
        make_retriever(object(), strategy="lexical", provider=None, lexical_ranker="ts_rank_cd"),
        make_retriever(object(), strategy="vector", provider=provider),
        make_retriever(object(), strategy="hybrid", provider=provider, lexical_ranker="ts_rank_cd"),
    )
    for retriever in retrievers:
        asyncio.run(retriever("NVDA 2024 R&D", 1))

    assert queries == ["NVDA 2024 research development"] * 3


def test_bm25_parameters_are_identical_in_lexical_and_hybrid_paths(monkeypatch):
    """Pass one BM25 parameter set unchanged to both lexical and hybrid retrieval."""
    calls = []

    async def bm25_search(_session, query, _k, _filters, *, k1, b, idf):
        calls.append(("lexical", query, k1, b, idf))
        return []

    async def retrieve(_session, query, **kwargs):
        calls.append(
            (
                "hybrid",
                query,
                kwargs["bm25_k1"],
                kwargs["bm25_b"],
                kwargs["bm25_idf"],
            )
        )
        return SimpleNamespace(hits=())

    monkeypatch.setattr(arms, "bm25_search", bm25_search)
    monkeypatch.setattr(arms, "retrieve", retrieve)
    settings = {"bm25_k1": 1.5, "bm25_b": 0.4, "bm25_idf": "robertson"}
    lexical = make_retriever(
        object(), strategy="lexical", provider=None, lexical_ranker="bm25", **settings
    )
    hybrid = make_retriever(
        object(), strategy="hybrid", provider=_Provider(), lexical_ranker="bm25", **settings
    )

    asyncio.run(lexical("R & D spending", 1))
    asyncio.run(hybrid("R & D spending", 1))

    assert calls == [
        ("lexical", "research development spending", 1.5, 0.4, "robertson"),
        ("hybrid", "research development spending", 1.5, 0.4, "robertson"),
    ]


def test_a_non_bm25_hybrid_arm_forwards_no_bm25_values(monkeypatch):
    """Leave the fusion ranker's own defaults in place for a ts_rank_cd arm."""
    seen = {}

    async def retrieve(_session, _query, **kwargs):
        seen.update(kwargs)
        return SimpleNamespace(hits=())

    monkeypatch.setattr(arms, "retrieve", retrieve)
    hybrid = make_retriever(
        object(), strategy="hybrid", provider=_Provider(), lexical_ranker="ts_rank_cd"
    )

    asyncio.run(hybrid("research", 1))

    assert seen["lexical_ranker"] == "ts_rank_cd"
    assert "bm25_k1" not in seen


def test_language_routing_is_bound_to_the_arm_and_only_to_a_fused_one(monkeypatch):
    """Forward the arm's routing selection, and refuse it on a single-lane arm."""
    seen = {}

    async def retrieve(_session, _query, **kwargs):
        seen.update(kwargs)
        return SimpleNamespace(hits=())

    monkeypatch.setattr(arms, "retrieve", retrieve)
    routed = make_retriever(
        object(),
        strategy="hybrid",
        provider=_Provider(),
        lexical_ranker="ts_rank_cd",
        route_by_language=True,
    )

    asyncio.run(routed("AMD의 매출은?", 1))
    assert seen["route_by_language"] is True

    unrouted = make_retriever(
        object(), strategy="hybrid", provider=_Provider(), lexical_ranker="ts_rank_cd"
    )
    asyncio.run(unrouted("AMD의 매출은?", 1))
    assert seen["route_by_language"] is False

    # Routing chooses between two components, so a single-lane arm carrying the flag
    # would be labelled with a query path it never takes.
    for strategy, ranker in (("lexical", "ts_rank_cd"), ("vector", None)):
        with pytest.raises(ValueError, match="routing requires the hybrid strategy"):
            make_retriever(
                object(),
                strategy=strategy,
                provider=_Provider(),
                lexical_ranker=ranker,
                route_by_language=True,
            )


def test_resolve_bm25_parameters_returns_values_only_for_a_bm25_arm():
    """Resolve a complete parameter set for BM25 and nothing for any other arm."""
    assert resolve_bm25_parameters("bm25", 1.5, 0.4, "robertson") == (1.5, 0.4, "robertson")
    assert resolve_bm25_parameters("ts_rank_cd", None, None, None) is None
    assert resolve_bm25_parameters(None, None, None, None) is None


@pytest.mark.parametrize(
    "values",
    [
        (None, DEFAULT_BM25_B, DEFAULT_BM25_IDF),
        (0, DEFAULT_BM25_B, DEFAULT_BM25_IDF),
        (float("inf"), DEFAULT_BM25_B, DEFAULT_BM25_IDF),
        (True, DEFAULT_BM25_B, DEFAULT_BM25_IDF),
        (DEFAULT_BM25_K1, -0.1, DEFAULT_BM25_IDF),
        (DEFAULT_BM25_K1, float("nan"), DEFAULT_BM25_IDF),
        (DEFAULT_BM25_K1, DEFAULT_BM25_B, "okapi"),
        (DEFAULT_BM25_K1, DEFAULT_BM25_B, None),
    ],
)
def test_a_bm25_arm_is_rejected_before_it_can_be_bound(values):
    """Reject an invalid BM25 set at bind time rather than on the first query."""
    k1, b, idf = values

    with pytest.raises(ValueError):
        resolve_bm25_parameters("bm25", k1, b, idf)
    with pytest.raises(ValueError):
        make_retriever(
            object(),
            strategy="lexical",
            provider=None,
            lexical_ranker="bm25",
            bm25_k1=k1,
            bm25_b=b,
            bm25_idf=idf,
        )


@pytest.mark.parametrize("lexical_ranker", [None, "ts_rank_cd"])
def test_bm25_values_are_rejected_on_an_arm_that_runs_no_bm25_query(lexical_ranker):
    """Refuse to label an arm with parameters its retrieval never uses."""
    with pytest.raises(ValueError, match="only for bm25 arms"):
        resolve_bm25_parameters(lexical_ranker, DEFAULT_BM25_K1, None, None)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"strategy": "okapi", "provider": None}, "unsupported retrieval strategy"),
        ({"strategy": "hybrid", "provider": None}, "requires an explicit lexical ranker"),
        ({"strategy": "lexical", "provider": None}, "requires an explicit lexical ranker"),
        (
            {"strategy": "lexical", "provider": None, "lexical_ranker": "okapi"},
            "requires an explicit lexical ranker",
        ),
        (
            {"strategy": "vector", "provider": None, "lexical_ranker": "bm25"},
            "must not name a lexical ranker",
        ),
        ({"strategy": "vector", "provider": None}, "requires an embedding provider"),
        (
            {"strategy": "hybrid", "provider": None, "lexical_ranker": "ts_rank_cd"},
            "requires an embedding provider",
        ),
        (
            {
                "strategy": "lexical",
                "provider": None,
                "lexical_ranker": "ts_rank_cd",
                "candidate_k": 0,
            },
            "candidate_k must be positive",
        ),
        (
            {"strategy": "lexical", "provider": None, "lexical_ranker": "ts_rank_cd", "rrf_k": 0},
            "rrf_k must be positive",
        ),
    ],
)
def test_a_mislabeled_arm_is_rejected_at_bind_time(kwargs, message):
    """Reject every mislabeled arm before it can touch a provider or the database."""
    with pytest.raises(ValueError, match=message):
        make_retriever(object(), **kwargs)


def test_a_bound_arm_rejects_a_deeper_per_call_hit_count(monkeypatch):
    """Refuse a per-call ``k`` the bound candidate depth cannot cover."""

    async def lexical_search(_session, _query, _k, _filters):
        raise AssertionError("depth validation must run before retrieval")

    monkeypatch.setattr(arms, "lexical_search", lexical_search)
    retriever = make_retriever(
        object(), strategy="lexical", provider=None, lexical_ranker="ts_rank_cd", candidate_k=3
    )

    with pytest.raises(ValueError, match="candidate_k must be at least k"):
        asyncio.run(retriever("research", 4))
