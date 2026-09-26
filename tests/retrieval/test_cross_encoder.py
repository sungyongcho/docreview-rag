"""Local cross-encoder provider and reranker wiring tests."""

import asyncio
from collections.abc import Sequence
import sys
import threading
import time
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.retrieval import cross_encoder
from app.retrieval.embeddings import DeterministicEmbeddingProvider
from app.retrieval.rerank import RerankProvider
import app.retrieval.service as service
from app.retrieval.types import RetrievalFilters
from tests.retrieval.support import fake_sentence_transformers, hit


def stub_components(monkeypatch, events: list[tuple[str, int]]) -> None:
    """Install four-candidate vector and lexical components."""

    async def vector(received_session, query_vector, *, k, filters, identity=None):
        """Exercise vector behavior."""
        events.append(("vector", k))
        return [hit(1, 0.9), hit(2, 0.8), hit(3, 0.7), hit(4, 0.6)]

    async def lexical(received_session, query, k, filters, *, text_search_config):
        """Exercise lexical behavior."""
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
            filters=RetrievalFilters(languages=("en",)),
            **kwargs,
        )
    )


@pytest.mark.parametrize(
    ("model", "batch_size"),
    [("", 32), ("model", 0)],
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
    first = cross_encoder.CrossEncoderReranker.shared(model="cross-encoder/fake")
    second = cross_encoder.CrossEncoderReranker.shared(model="cross-encoder/fake")
    smaller_batches = cross_encoder.CrossEncoderReranker.shared(
        model="cross-encoder/fake", batch_size=8
    )

    assert first is second
    assert smaller_batches is not first
    assert smaller_batches.batch_size == 8
    assert asyncio.run(first.score("first", ["document"])) == [1.0]
    assert asyncio.run(second.score("second", ["document"])) == [1.0]
    assert constructions == ["cross-encoder/fake"]
    # Direct construction stays private to its caller and never touches the shared cache.
    assert cross_encoder.CrossEncoderReranker(model="cross-encoder/fake") is not first


def test_component_rankings_record_proposals_not_rerank_survivors(monkeypatch):
    """Preserve component proposals independently of rerank survivors."""

    class Reranker(RerankProvider):
        """Test double for Reranker behavior."""

        async def score(self, query: str, documents: Sequence[str]) -> Sequence[float]:
            """Exercise score behavior."""
            return [0.0] * len(documents)

    result = retrieve(monkeypatch, [], k=1, candidate_k=4, reranker=Reranker())

    assert len(result.hits) == 1
    assert result.component_rankings.vector == (1, 2, 3, 4)
    assert result.component_rankings.lexical == (4, 3, 2, 1)
