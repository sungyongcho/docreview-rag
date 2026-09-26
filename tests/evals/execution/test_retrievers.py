"""Experiment-arm validation and the retrieval lane each arm binds."""

import asyncio
from types import SimpleNamespace
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import DEFAULT_BM25_B, DEFAULT_BM25_IDF, LexicalRanker
from app.evals.execution import retrievers as arms
from app.evals.execution.retrievers import make_retriever
from app.retrieval.embedding.provider import DeterministicEmbeddingProvider
from app.retrieval.search import service
from app.retrieval.search.plan import RetrievalStrategy
from app.retrieval.types import RetrievalFilters


class _Provider(DeterministicEmbeddingProvider):
    """Embedding provider stub that records the queries it is asked to embed."""

    dimensions = 384

    def __init__(self, seen=None):
        self.seen = seen

    async def embed_documents(self, texts):
        """Embed each text as a zero vector; the arms only ever embed queries."""
        return [[0.0] * self.dimensions for _ in texts]

    async def embed_query(self, text):
        """Record the normalized query and return a zero vector."""
        if self.seen is not None:
            self.seen.append(text)
        return [0.0] * self.dimensions


def test_every_retrieval_strategy_receives_the_same_normalized_query(monkeypatch):
    """Normalize the query identically on every retrieval path."""
    queries = []

    async def lexical_search(_session, query, _k, _filters, *, text_search_config):
        queries.append(query)
        return []

    async def vector_search(_session, _vector, *, k, filters, identity):
        assert k == 1
        assert filters is None
        assert identity == provider.identity
        return []

    async def retrieve(_session, query, **_kwargs):
        queries.append(query)
        return SimpleNamespace(hits=())

    monkeypatch.setattr(arms, "lexical_search", lexical_search)
    monkeypatch.setattr(arms, "vector_search", vector_search)
    monkeypatch.setattr(arms, "retrieve", retrieve)
    provider = _Provider(queries)
    session = cast(AsyncSession, object())

    retrievers = (
        make_retriever(session, strategy="lexical", provider=None, lexical_ranker="ts_rank_cd"),
        make_retriever(session, strategy="vector", provider=provider),
        make_retriever(session, strategy="hybrid", provider=provider, lexical_ranker="ts_rank_cd"),
    )
    for retriever in retrievers:
        asyncio.run(retriever("NVDA 2024 R&D", 1))

    assert queries == ["NVDA 2024 research development"] * 3


def test_bm25_parameters_are_identical_in_lexical_and_hybrid_paths(monkeypatch):
    """Pass one BM25 parameter set unchanged to both lexical and hybrid retrieval."""
    calls = []

    async def bm25_search(_session, query, _k, _filters, *, k1, b, idf, text_search_config):
        calls.append(("lexical", query, k1, b, idf))
        return []

    async def retrieve(_session, query, **kwargs):
        calls.append(
            (
                "hybrid",
                query,
                kwargs["plan"].bm25_k1,
                kwargs["plan"].bm25_b,
                kwargs["plan"].bm25_idf,
            )
        )
        return SimpleNamespace(hits=())

    monkeypatch.setattr(arms, "bm25_search", bm25_search)
    monkeypatch.setattr(arms, "retrieve", retrieve)
    settings = {"bm25_k1": 1.5, "bm25_b": 0.4, "bm25_idf": "robertson"}
    session = cast(AsyncSession, object())
    lexical = make_retriever(
        session, strategy="lexical", provider=None, lexical_ranker="bm25", **settings
    )
    hybrid = make_retriever(
        session, strategy="hybrid", provider=_Provider(), lexical_ranker="bm25", **settings
    )

    asyncio.run(lexical("R & D spending", 1))
    asyncio.run(hybrid("R & D spending", 1))

    assert calls == [
        ("lexical", "research development spending", 1.5, 0.4, "robertson"),
        ("hybrid", "research development spending", 1.5, 0.4, "robertson"),
    ]


@pytest.mark.parametrize("strategy", ["vector", "hybrid"])
def test_vector_and_hybrid_arms_preserve_mixed_corpus_languages(monkeypatch, strategy):
    """Keep both corpus languages through vector search and hybrid lexical fan-out."""
    calls = []
    filters = RetrievalFilters(languages=("en", "ko"))

    async def vector_search(_session, _vector, *, k, filters, identity):
        """Record the corpus filter at the database boundary."""
        calls.append(("vector", filters.languages))
        return []

    async def lexical_search(_session, _query, _k, filters, *, text_search_config):
        """Record each language-specific lexical query."""
        calls.append(("lexical", filters.languages))
        return []

    monkeypatch.setattr(arms, "vector_search", vector_search)
    monkeypatch.setattr(service, "vector_search", vector_search)
    monkeypatch.setattr(service, "lexical_search", lexical_search)
    retriever = make_retriever(
        cast(AsyncSession, object()),
        strategy=strategy,
        provider=_Provider(),
        lexical_ranker="ts_rank_cd" if strategy == "hybrid" else None,
        filters=filters,
    )

    assert asyncio.run(retriever("revenue", 1)).hits == ()
    expected = [("vector", ("en", "ko"))]
    if strategy == "hybrid":
        expected.extend([("lexical", ("en",)), ("lexical", ("ko",))])
    assert calls == expected


def test_language_routing_is_bound_to_the_arm_and_only_to_a_fused_one(monkeypatch):
    """Forward the arm's routing selection, and refuse it on a single-lane arm."""
    seen = {}

    async def retrieve(_session, _query, **kwargs):
        seen.update(kwargs)
        return SimpleNamespace(hits=())

    monkeypatch.setattr(arms, "retrieve", retrieve)
    session = cast(AsyncSession, object())
    routed = make_retriever(
        session,
        strategy="hybrid",
        provider=_Provider(),
        lexical_ranker="ts_rank_cd",
        route_by_language=True,
    )

    asyncio.run(routed("AMD의 매출은?", 1))
    assert seen["plan"].route_by_language is True

    unrouted = make_retriever(
        session, strategy="hybrid", provider=_Provider(), lexical_ranker="ts_rank_cd"
    )
    asyncio.run(unrouted("AMD의 매출은?", 1))
    assert seen["plan"].route_by_language is False

    # Routing chooses between two components, so a single-lane arm carrying the flag
    # would be labelled with a query path it never takes.
    single_lane: tuple[tuple[RetrievalStrategy, LexicalRanker | None], ...] = (
        ("lexical", "ts_rank_cd"),
        ("vector", None),
    )
    for strategy, ranker in single_lane:
        with pytest.raises(ValueError, match="routing requires the hybrid strategy"):
            make_retriever(
                session,
                strategy=strategy,
                provider=_Provider(),
                lexical_ranker=ranker,
                route_by_language=True,
            )


def test_a_bm25_arm_is_rejected_before_it_can_be_bound():
    """Require explicit BM25 parameters before an evaluation arm can run."""
    with pytest.raises(ValueError):
        make_retriever(
            cast(AsyncSession, object()),
            strategy="lexical",
            provider=None,
            lexical_ranker="bm25",
            bm25_k1=None,
            bm25_b=DEFAULT_BM25_B,
            bm25_idf=DEFAULT_BM25_IDF,
        )


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"strategy": "okapi", "provider": None}, "unsupported retrieval strategy"),
        ({"strategy": "hybrid", "provider": None}, "requires an explicit lexical ranker"),
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
            "candidate_k",
        ),
        (
            {"strategy": "lexical", "provider": None, "lexical_ranker": "ts_rank_cd", "rrf_k": 0},
            "rrf_k",
        ),
    ],
)
def test_a_mislabeled_arm_is_rejected_at_bind_time(kwargs, message):
    """Reject every mislabeled arm before it can touch a provider or the database."""
    with pytest.raises(ValueError, match=message):
        make_retriever(cast(AsyncSession, object()), **kwargs)


def test_a_bound_arm_rejects_a_deeper_per_call_hit_count(monkeypatch):
    """Refuse a per-call ``k`` the bound candidate depth cannot cover."""

    async def lexical_search(_session, _query, _k, _filters, *, text_search_config):
        raise AssertionError("depth validation must run before retrieval")

    monkeypatch.setattr(arms, "lexical_search", lexical_search)
    retriever = make_retriever(
        cast(AsyncSession, object()),
        strategy="lexical",
        provider=None,
        lexical_ranker="ts_rank_cd",
        candidate_k=3,
    )

    with pytest.raises(ValueError, match="candidate_k must be at least k"):
        asyncio.run(retriever("research", 4))


@pytest.mark.parametrize(
    ("filters", "query", "sent"),
    [
        (RetrievalFilters(languages=("ko",)), "삼성전자 매출", ("삼성 성전 전자 매출", "simple")),
        (None, "NVDA revenue", ("NVDA revenue", "english")),
    ],
    ids=["korean_filter_sends_bigrams_under_simple", "no_filter_keeps_the_english_path"],
)
def test_lexical_lane_tokenizes_for_the_filtered_corpus_language(monkeypatch, filters, query, sent):
    """A ko filter sends bigram tokens under the Korean configuration; no filter stays English."""
    calls = []

    async def lexical_search(_session, query, _k, _filters, *, text_search_config):
        calls.append((query, text_search_config))
        return []

    monkeypatch.setattr(arms, "lexical_search", lexical_search)
    retriever = make_retriever(
        cast(AsyncSession, object()),
        strategy="lexical",
        provider=None,
        lexical_ranker="ts_rank_cd",
        filters=filters,
    )
    asyncio.run(retriever(query, 1))

    assert calls == [sent]
