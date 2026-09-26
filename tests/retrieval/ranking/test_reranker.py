"""Local cross-encoder provider and reranker wiring tests."""

import asyncio
import math
import sys
import threading
import time
from typing import Any
from unittest.mock import Mock

import pytest

from app.retrieval.ranking import reranker as cross_encoder, reranker as rerank
from tests.retrieval.support import fake_sentence_transformers, hit


@pytest.mark.parametrize(
    "settings",
    [
        pytest.param({"model": ""}, id="blank-model"),
        pytest.param({"batch_size": 0}, id="empty-batch"),
        pytest.param({"max_length": 0}, id="empty-input-window"),
    ],
)
def test_reranker_rejects_invalid_construction(settings):
    """Reject an empty model, batch or input window before loading the encoder."""
    with pytest.raises(ValueError):
        cross_encoder.CrossEncoderReranker(**settings)


def test_missing_extra_raises_an_actionable_runtime_error(monkeypatch):
    """Raise an actionable error when the optional model package is absent."""
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)

    with pytest.raises(RuntimeError, match=r"uv sync --extra cpu"):
        asyncio.run(cross_encoder.CrossEncoderReranker().score("query", ["document"]))


def test_empty_candidate_list_does_not_load_a_model(monkeypatch):
    """Return no scores without loading a model for empty candidates."""
    constructor = Mock(side_effect=AssertionError("Empty candidates must not load model weights"))
    fake_sentence_transformers(monkeypatch, CrossEncoder=constructor)
    reranker = cross_encoder.CrossEncoderReranker()

    assert asyncio.run(reranker.score("query", [])) == []
    constructor.assert_not_called()


def test_score_preserves_pair_order_and_runs_model_off_loop(monkeypatch):
    """Preserve pair order while constructing and running the model off-loop."""
    main_thread = threading.get_ident()
    calls: dict[str, Any] = {}

    class Encoder:
        """Test double for Encoder behavior."""

        def __init__(self, model, *, max_length):
            calls["model"] = model
            calls["max_length"] = max_length
            calls["constructor_thread"] = threading.get_ident()

        def predict(self, pairs, *, batch_size):
            """Exercise predict behavior."""
            calls["pairs"] = list(pairs)
            calls["batch_size"] = batch_size
            calls["predict_thread"] = threading.get_ident()
            return [2, -0.25]

    fake_sentence_transformers(monkeypatch, CrossEncoder=Encoder)
    reranker = cross_encoder.CrossEncoderReranker(model="cross-encoder/fake", batch_size=5)

    scores = asyncio.run(reranker.score("query", ["first", "second"]))

    assert scores == [2.0, -0.25]
    assert calls["model"] == "cross-encoder/fake"
    # The scoring window is explicit rather than the tokenizer's silent default.
    assert calls["max_length"] == 512
    assert calls["pairs"] == [("query", "first"), ("query", "second")]
    assert calls["batch_size"] == 5
    assert calls["constructor_thread"] != main_thread
    assert calls["predict_thread"] != main_thread


def test_simultaneous_cold_scores_construct_one_model(monkeypatch):
    """Serialize a simultaneous cold load and share the constructed model."""
    constructors: list[str] = []

    class Encoder:
        """Test double for Encoder behavior."""

        def __init__(self, model, *, max_length):
            del max_length
            constructors.append(model)
            time.sleep(0.05)

        def predict(self, pairs, *, batch_size):
            """Exercise predict behavior."""
            return [1.0] * len(pairs)

    fake_sentence_transformers(monkeypatch, CrossEncoder=Encoder)
    reranker = cross_encoder.CrossEncoderReranker(model="cross-encoder/fake")

    async def score_concurrently():
        """Exercise score concurrently behavior."""
        return await asyncio.gather(
            reranker.score("first", ["document"]),
            reranker.score("second", ["document"]),
        )

    scores = asyncio.run(score_concurrently())

    assert scores == [[1.0], [1.0]]
    assert constructors == ["cross-encoder/fake"]


def test_shared_reranker_is_one_instance_per_model_and_batch_size(monkeypatch):
    """Callers resolving the same (model, batch_size) share one lazily loaded model."""
    monkeypatch.setattr(cross_encoder, "_SHARED_RERANKERS", {}, raising=False)
    constructions: list[str] = []

    class Encoder:
        """Test double for Encoder behavior."""

        def __init__(self, model, *, max_length):
            del max_length
            constructions.append(model)

        def predict(self, pairs, *, batch_size):
            """Exercise predict behavior."""
            return [1.0] * len(pairs)

    fake_sentence_transformers(monkeypatch, CrossEncoder=Encoder)
    first = cross_encoder.shared_cross_encoder(model="cross-encoder/fake")
    second = cross_encoder.shared_cross_encoder(model="cross-encoder/fake")
    smaller_batches = cross_encoder.shared_cross_encoder(model="cross-encoder/fake", batch_size=8)

    assert first is second
    assert smaller_batches is not first
    assert smaller_batches.batch_size == 8
    assert asyncio.run(first.score("first", ["document"])) == [1.0]
    assert asyncio.run(second.score("second", ["document"])) == [1.0]
    assert constructions == ["cross-encoder/fake"]
    # Direct construction stays private to its caller and never touches the shared cache.
    assert cross_encoder.CrossEncoderReranker(model="cross-encoder/fake") is not first


def test_provider_receives_full_index_text_and_rescores_without_mutating_hits():
    """Rescore full indexed text without mutating candidate hits."""
    calls = []

    class Provider(rerank.RerankProvider):
        async def score(self, query, documents):
            calls.append((query, list(documents)))
            return [0.1, 0.9]

    hits = [hit(1, 99.0), hit(2, 1.0)]
    original_scores = [candidate.score for candidate in hits]
    reranked = asyncio.run(
        rerank.rerank_hits("research expense", hits, provider=Provider(), top_k=2)
    )

    assert calls == [("research expense", [candidate.index_text for candidate in hits])]
    assert [candidate.chunk_id for candidate in reranked] == [2, 1]
    assert [candidate.score for candidate in reranked] == [0.9, 0.1]
    assert [candidate.score for candidate in hits] == original_scores


@pytest.mark.parametrize(
    "scores, message",
    [
        ([1.0], "scores"),
        ([0.0, math.nan], "non-finite"),
        ([0.0, True], "nonnumeric"),
    ],
)
def test_provider_scores_must_match_count_and_be_finite_numeric(scores, message):
    """Reject provider scores with invalid count, type, or finiteness."""

    class Provider(rerank.RerankProvider):
        async def score(self, _query, _documents):
            return scores

    with pytest.raises(ValueError, match=message):
        asyncio.run(
            rerank.rerank_hits(
                "query",
                [hit(1, 0.5), hit(2, 0.4)],
                provider=Provider(),
            )
        )


def test_empty_candidates_and_zero_limit_do_not_call_provider():
    """Avoid provider calls for empty candidates or a zero result limit."""

    class Provider(rerank.RerankProvider):
        async def score(self, _query, _documents):
            raise AssertionError("provider should not be called")

    assert asyncio.run(rerank.rerank_hits("query", [], provider=Provider())) == []
    assert (
        asyncio.run(rerank.rerank_hits("query", [hit(1, 0.5)], provider=Provider(), top_k=0)) == []
    )


@pytest.mark.parametrize(("query", "top_k"), [("   ", 1), ("query", -1)])
def test_reranking_rejects_blank_queries_and_negative_limits(query, top_k):
    """Reject blank queries and negative result limits."""

    class Provider(rerank.RerankProvider):
        async def score(self, _query, _documents):
            raise AssertionError("provider should not be called")

    with pytest.raises(ValueError):
        asyncio.run(rerank.rerank_hits(query, [hit(1, 0.5)], provider=Provider(), top_k=top_k))
