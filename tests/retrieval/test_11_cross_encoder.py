"""L11: local cross-encoder scoring and production reranker wiring."""

import asyncio
from collections.abc import Sequence
import inspect
import sys
import threading
from types import ModuleType, SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.retrieval.embeddings import DeterministicEmbeddingProvider
from app.retrieval.rerank import RerankProvider
import app.retrieval.service as service
from app.retrieval.types import ChunkHit, RetrievalFilters
from tests.retrieval.test_01_contract import hit_values
from tests.support import need, optional_module

PUBLIC = optional_module("app.retrieval")
CE = optional_module("app.retrieval.cross_encoder")
RERANKER = "CrossEncoderReranker"


def need_reranker_wiring() -> None:
    """Skip until ``retrieve`` accepts a reranker."""
    if "reranker" not in inspect.signature(service.retrieve).parameters:
        pytest.skip("not implemented yet: retrieve(reranker=...)")


def fake_sentence_transformers(monkeypatch, encoder_type: type[object]) -> None:
    """Expose one fake encoder through the optional third-party module name."""
    module = ModuleType("sentence_transformers")
    module.__dict__["CrossEncoder"] = encoder_type
    monkeypatch.setitem(sys.modules, "sentence_transformers", module)


def hit(chunk_id: int, score: float, **changes) -> ChunkHit:
    """Build one valid candidate with a unique source span."""
    start = changes.pop("start_char", chunk_id * 100)
    return ChunkHit(
        **hit_values(
            chunk_id=chunk_id,
            score=score,
            start_char=start,
            end_char=start + 50,
            **changes,
        )
    )


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
    need(CE, RERANKER)
    need(PUBLIC, RERANKER)
    assert getattr(PUBLIC, RERANKER) is CE.CrossEncoderReranker
    assert RERANKER in PUBLIC.__all__


def test_constructing_reranker_loads_no_model():
    need(CE, RERANKER)
    reranker = CE.CrossEncoderReranker()
    assert reranker._encoder is None


@pytest.mark.parametrize(
    ("model", "batch_size"),
    [("", 32), ("model", 0), ("model", -1)],
)
def test_reranker_rejects_invalid_construction(model, batch_size):
    need(CE, RERANKER)
    need(CE, RERANKER)
    with pytest.raises(ValueError):
        CE.CrossEncoderReranker(model=model, batch_size=batch_size)


def test_missing_extra_raises_an_actionable_runtime_error(monkeypatch):
    need(CE, RERANKER)
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)

    with pytest.raises(RuntimeError, match=r"uv sync --extra cpu"):
        CE.CrossEncoderReranker()._load()


def test_load_constructs_the_model_once(monkeypatch):
    need(CE, RERANKER)
    calls: list[str] = []

    class Encoder:
        def __init__(self, model):
            calls.append(model)

    fake_sentence_transformers(monkeypatch, Encoder)
    reranker = CE.CrossEncoderReranker(model="cross-encoder/fake")

    first = reranker._load()
    second = reranker._load()

    assert first is second
    assert calls == ["cross-encoder/fake"]


def test_empty_candidate_list_does_not_load_a_model():
    need(CE, RERANKER)
    reranker = CE.CrossEncoderReranker()

    assert asyncio.run(reranker.score("query", [])) == []
    assert reranker._encoder is None


def test_score_preserves_pair_order_and_runs_predict_off_loop(monkeypatch):
    need(CE, RERANKER)
    main_thread = threading.get_ident()
    calls: dict[str, Any] = {}

    class Encoder:
        def __init__(self, model):
            calls["model"] = model

        def predict(self, pairs, *, batch_size):
            calls["pairs"] = list(pairs)
            calls["batch_size"] = batch_size
            calls["thread"] = threading.get_ident()
            return [2, -0.25]

    fake_sentence_transformers(monkeypatch, Encoder)
    reranker = CE.CrossEncoderReranker(model="cross-encoder/fake", batch_size=5)

    scores = asyncio.run(reranker.score("query", ["first", "second"]))

    assert scores == [2.0, -0.25]
    assert calls["model"] == "cross-encoder/fake"
    assert calls["pairs"] == [("query", "first"), ("query", "second")]
    assert calls["batch_size"] == 5
    assert calls["thread"] != main_thread


def test_no_reranker_keeps_the_m27_behaviour(monkeypatch):
    need_reranker_wiring()
    baseline_events: list[tuple[str, int]] = []
    repeat_events: list[tuple[str, int]] = []

    baseline = retrieve(monkeypatch, baseline_events, k=2, candidate_k=4)
    repeat = retrieve(monkeypatch, repeat_events, k=2, candidate_k=4, reranker=None)

    assert baseline.hits == repeat.hits
    assert baseline_events == repeat_events == [("vector", 4), ("lexical", 4)]
    assert len(baseline.hits) == 2


def test_reranker_rescores_the_full_candidate_pool_then_truncates(monkeypatch):
    need_reranker_wiring()
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
    need_reranker_wiring()

    class Reranker(RerankProvider):
        async def score(self, query: str, documents: Sequence[str]) -> Sequence[float]:
            return [0.0] * len(documents)

    result = retrieve(monkeypatch, [], k=1, candidate_k=4, reranker=Reranker())

    assert len(result.hits) == 1
    assert result.component_rankings.vector == (1, 2, 3, 4)
    assert result.component_rankings.lexical == (4, 3, 2, 1)


def test_cli_accepts_rerank_flag():
    from app.retrieval.__main__ import arguments

    args = arguments(["--query", "market risk", "--rerank"])

    assert args.rerank is True


def test_run_passes_cross_encoder_when_rerank_is_enabled(monkeypatch):
    from app.retrieval import __main__ as cli

    reranker = object()
    seen: dict[str, Any] = {}

    class Session:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, exc_type, exc, traceback):
            return None

    async def retrieve(session, query, **kwargs):
        seen.update(kwargs)
        return object()

    settings = SimpleNamespace(
        embedding_provider="deterministic",
        lexical_ranker="ts_rank_cd",
        bm25_k1=1.2,
        bm25_b=0.75,
        bm25_idf="lucene",
    )
    monkeypatch.setattr(cli, "Session", Session)
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(cli, "get_embedding_provider", lambda _settings: object())
    monkeypatch.setattr(cli, "CrossEncoderReranker", lambda: reranker)
    monkeypatch.setattr(cli, "retrieve", retrieve)
    monkeypatch.setattr(cli, "_payload", lambda **values: values)

    args = cli.arguments(["--query", "market risk", "--rerank"])
    payload = asyncio.run(cli._run(args))

    assert seen["reranker"] is reranker
    assert payload["result"] is not None
