"""Local cross-encoder provider and reranker wiring tests."""

import asyncio
from collections.abc import Sequence
import sys
import threading
import time
from types import SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import app.retrieval as public
from app.retrieval import cross_encoder
from app.retrieval.embeddings import DeterministicEmbeddingProvider
from app.retrieval.rerank import RerankProvider
import app.retrieval.service as service
from app.retrieval.types import RetrievalFilters
from tests.retrieval.support import fake_sentence_transformers, hit


def stub_components(monkeypatch, events: list[tuple[str, int]]) -> None:
    """Install four-candidate vector and lexical components."""

    async def vector(received_session, query_vector, *, k, filters):
        events.append(("vector", k))
        return [hit(1, 0.9), hit(2, 0.8), hit(3, 0.7), hit(4, 0.6)]

    async def lexical(received_session, query, k, filters):
        events.append(("lexical", k))
        return [hit(4, 9.0), hit(3, 8.0), hit(2, 7.0), hit(1, 6.0)]

    monkeypatch.setattr(service, "vector_search", vector)
    monkeypatch.setattr(service, "lexical_search", lexical)


def retrieve(monkeypatch, events: list[tuple[str, int]], **kwargs):
    """Run one retrieval request against stubbed components."""
    stub_components(monkeypatch, events)
    return asyncio.run(
        service.retrieve(
            cast(AsyncSession, object()),
            "market risk",
            provider=DeterministicEmbeddingProvider(),
            filters=RetrievalFilters(),
            **kwargs,
        )
    )


def test_public_surface_exports_cross_encoder():
    """Export the cross-encoder reranker from the public façade."""
    assert public.CrossEncoderReranker is cross_encoder.CrossEncoderReranker
    assert "CrossEncoderReranker" in public.__all__


def test_constructing_reranker_loads_no_model():
    """Construct the reranker without loading model weights."""
    reranker = cross_encoder.CrossEncoderReranker()
    assert reranker._encoder.value is None


@pytest.mark.parametrize(
    ("model", "batch_size"),
    [("", 32), ("model", 0), ("model", -1)],
)
def test_reranker_rejects_invalid_construction(model, batch_size):
    """Reject invalid reranker model and batch settings."""
    with pytest.raises(ValueError):
        cross_encoder.CrossEncoderReranker(model=model, batch_size=batch_size)


def test_missing_extra_raises_an_actionable_runtime_error(monkeypatch):
    """Raise an actionable error when the optional model package is absent."""
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)

    with pytest.raises(RuntimeError, match=r"uv sync --extra cpu"):
        cross_encoder.CrossEncoderReranker()._load()


def test_load_constructs_the_model_once(monkeypatch):
    """Load and cache one cross-encoder model instance."""
    calls: list[str] = []

    class Encoder:
        def __init__(self, model):
            calls.append(model)

    fake_sentence_transformers(monkeypatch, CrossEncoder=Encoder)
    reranker = cross_encoder.CrossEncoderReranker(model="cross-encoder/fake")

    first = reranker._load()
    second = reranker._load()

    assert first is second
    assert calls == ["cross-encoder/fake"]


def test_empty_candidate_list_does_not_load_a_model():
    """Return no scores without loading a model for empty candidates."""
    reranker = cross_encoder.CrossEncoderReranker()

    assert asyncio.run(reranker.score("query", [])) == []
    assert reranker._encoder.value is None


def test_score_preserves_pair_order_and_runs_model_off_loop(monkeypatch):
    """Preserve pair order while constructing and running the model off-loop."""
    main_thread = threading.get_ident()
    calls: dict[str, Any] = {}

    class Encoder:
        def __init__(self, model):
            calls["model"] = model
            calls["constructor_thread"] = threading.get_ident()

        def predict(self, pairs, *, batch_size):
            calls["pairs"] = list(pairs)
            calls["batch_size"] = batch_size
            calls["predict_thread"] = threading.get_ident()
            return [2, -0.25]

    fake_sentence_transformers(monkeypatch, CrossEncoder=Encoder)
    reranker = cross_encoder.CrossEncoderReranker(model="cross-encoder/fake", batch_size=5)

    scores = asyncio.run(reranker.score("query", ["first", "second"]))

    assert scores == [2.0, -0.25]
    assert calls["model"] == "cross-encoder/fake"
    assert calls["pairs"] == [("query", "first"), ("query", "second")]
    assert calls["batch_size"] == 5
    assert calls["constructor_thread"] != main_thread
    assert calls["predict_thread"] != main_thread


def test_simultaneous_cold_scores_construct_one_model(monkeypatch):
    """Serialize a simultaneous cold load and share the constructed model."""
    constructors: list[str] = []

    class Encoder:
        def __init__(self, model):
            constructors.append(model)
            time.sleep(0.05)

        def predict(self, pairs, *, batch_size):
            return [1.0] * len(pairs)

    fake_sentence_transformers(monkeypatch, CrossEncoder=Encoder)
    reranker = cross_encoder.CrossEncoderReranker(model="cross-encoder/fake")

    async def score_concurrently():
        return await asyncio.gather(
            reranker.score("first", ["document"]),
            reranker.score("second", ["document"]),
        )

    scores = asyncio.run(score_concurrently())

    assert scores == [[1.0], [1.0]]
    assert constructors == ["cross-encoder/fake"]


def test_no_reranker_keeps_baseline_retrieval_behavior(monkeypatch):
    """Keep baseline retrieval unchanged when no reranker is supplied."""
    baseline_events: list[tuple[str, int]] = []
    repeat_events: list[tuple[str, int]] = []

    baseline = retrieve(monkeypatch, baseline_events, k=2, candidate_k=4)
    repeat = retrieve(monkeypatch, repeat_events, k=2, candidate_k=4, reranker=None)

    assert baseline.hits == repeat.hits
    assert baseline_events == repeat_events == [("vector", 4), ("lexical", 4)]
    assert len(baseline.hits) == 2


def test_reranker_rescores_the_full_candidate_pool_then_truncates(monkeypatch):
    """Rescore the complete candidate pool before final truncation."""
    seen: dict[str, Any] = {}

    class Reranker(RerankProvider):
        async def score(self, query: str, documents: Sequence[str]) -> Sequence[float]:
            seen["query"] = query
            seen["documents"] = list(documents)
            return [float(index) for index in range(len(documents))]

    result = retrieve(monkeypatch, [], k=2, candidate_k=4, reranker=Reranker())

    assert seen["query"] == "market risk"
    assert len(seen["documents"]) == 4
    assert len(result.hits) == 2
    assert result.hits[0].score > result.hits[1].score


def test_component_rankings_record_proposals_not_rerank_survivors(monkeypatch):
    """Preserve component proposals independently of rerank survivors."""

    class Reranker(RerankProvider):
        async def score(self, query: str, documents: Sequence[str]) -> Sequence[float]:
            return [0.0] * len(documents)

    result = retrieve(monkeypatch, [], k=1, candidate_k=4, reranker=Reranker())

    assert len(result.hits) == 1
    assert result.component_rankings.vector == (1, 2, 3, 4)
    assert result.component_rankings.lexical == (4, 3, 2, 1)


def test_cli_accepts_rerank_flag():
    """Expose optional cross-encoder reranking through the CLI."""
    from app.retrieval.__main__ import arguments

    args = arguments(["--query", "market risk", "--rerank"])

    assert args.rerank is True


def test_run_passes_cross_encoder_when_rerank_is_enabled(monkeypatch):
    """Pass a cross-encoder to the service only when requested."""
    from app.db import session as db_session
    from app.retrieval import __main__ as cli

    reranker = object()
    seen: dict[str, Any] = {}

    class Session:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, exc_type, exc, traceback):
            return None

    class Engine:
        async def dispose(self):
            return None

    async def retrieve(session, query, **kwargs):
        seen.update(kwargs)
        return object()

    settings = SimpleNamespace(
        embedding_provider="deterministic",
        lexical_ranker="ts_rank_cd",
        query_language_routing=False,
        bm25_k1=1.2,
        bm25_b=0.75,
        bm25_idf="lucene",
    )
    monkeypatch.setattr(db_session, "Session", Session)
    monkeypatch.setattr(db_session, "engine", Engine())
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(cli, "get_embedding_provider", lambda _settings: object())
    monkeypatch.setattr(cli, "CrossEncoderReranker", lambda: reranker)
    monkeypatch.setattr(cli, "retrieve", retrieve)
    monkeypatch.setattr(cli, "_payload", lambda **values: values)

    args = cli.arguments(["--query", "market risk", "--rerank"])
    payload = asyncio.run(cli._run(args))

    assert seen["reranker"] is reranker
    assert payload["result"] is not None
