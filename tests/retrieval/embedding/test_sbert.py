"""Local sentence-transformer provider and wiring tests."""

import asyncio
from collections.abc import Sequence
import sys
import threading
from typing import Any
from unittest.mock import Mock

import pytest

from app.config import EMBEDDING_DIMENSIONS, Settings
from app.retrieval.embedding import sbert
from app.retrieval.embedding.provider import get_embedding_provider
from tests.retrieval.support import fake_sentence_transformers


def fake_tokenizer(inputs, **kwargs):
    """Expose untruncated mock token lengths including the two special tokens."""
    assert kwargs["truncation"] is False and kwargs["add_special_tokens"] is True
    return {"input_ids": [[0] * (len(text.split()) + 2) for text in inputs]}


@pytest.mark.parametrize(
    ("model", "dimensions", "batch_size"),
    [
        ("", 384, 32),
        ("model", 0, 32),
        ("model", 384, 0),
    ],
)
def test_provider_rejects_invalid_construction(model, dimensions, batch_size):
    """Reject invalid local model, dimension, and batch settings."""
    with pytest.raises(ValueError):
        sbert.SentenceTransformerEmbeddingProvider(
            model=model,
            dimensions=dimensions,
            batch_size=batch_size,
        )


def test_factory_builds_configured_sbert_provider_without_loading_model(monkeypatch):
    """Build the configured local provider without loading weights."""
    constructor = Mock(side_effect=AssertionError("Provider selection must not load model weights"))
    fake_sentence_transformers(monkeypatch, SentenceTransformer=constructor)
    settings = Settings(
        embedding_provider="sbert",
        sbert_model="sentence-transformers/test-model",
    )

    provider: Any = get_embedding_provider(settings)

    assert isinstance(provider, sbert.SentenceTransformerEmbeddingProvider)
    assert provider.model == "sentence-transformers/test-model"
    assert provider.dimensions == EMBEDDING_DIMENSIONS
    constructor.assert_not_called()


def test_missing_extra_raises_an_actionable_runtime_error(monkeypatch):
    """Raise an actionable error when the optional model package is absent."""
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)

    with pytest.raises(RuntimeError, match=r"uv sync --extra cpu"):
        asyncio.run(sbert.SentenceTransformerEmbeddingProvider().embed_documents(["first"]))


def test_wrong_dimension_is_rejected_without_caching_the_failed_model(monkeypatch):
    """Retry construction after a dimension mismatch, then reuse the valid encoder."""
    constructions = []
    dimensions = iter([768, 2])

    class Matrix:
        """Return one valid encoded vector."""

        def tolist(self):
            """Expose the matrix conversion used by the dependency."""
            return [[1.0, 0.0]]

    class Encoder:
        """Offer an invalid first model followed by a valid replacement."""

        max_seq_length = 128
        tokenizer = staticmethod(fake_tokenizer)

        def __init__(self, model):
            """Record construction and consume the next model dimension."""
            constructions.append(model)
            self.dimensions = next(dimensions)

        def get_sentence_embedding_dimension(self):
            """Report the dimension of this model instance."""
            return self.dimensions

        def encode(self, inputs, **kwargs):
            """Return vectors only after dimension validation has succeeded."""
            return Matrix()

    fake_sentence_transformers(monkeypatch, SentenceTransformer=Encoder)
    provider = sbert.SentenceTransformerEmbeddingProvider(model="test-model", dimensions=2)

    with pytest.raises(ValueError, match=r"produces 768 dimensions"):
        asyncio.run(provider.embed_documents(["first"]))

    assert asyncio.run(provider.embed_documents(["second"])) == [[1.0, 0.0]]
    assert asyncio.run(provider.embed_documents(["third"])) == [[1.0, 0.0]]
    assert constructions == ["test-model", "test-model"]


def test_embed_documents_reuses_the_model_and_runs_model_off_loop(monkeypatch):
    """Reuse one model and run construction and encoding off the event loop."""
    main_thread = threading.get_ident()
    calls: dict[str, Any] = {"constructed": 0}

    class Matrix:
        def tolist(self):
            return [[1.0, 0.0], [0.0, 1.0]]

    class Encoder:
        max_seq_length = 128
        tokenizer = staticmethod(fake_tokenizer)

        def __init__(self, model):
            calls["constructed"] = int(calls["constructed"]) + 1
            calls["model"] = model
            calls["constructor_thread"] = threading.get_ident()

        def get_sentence_embedding_dimension(self):
            return 2

        def encode(
            self,
            inputs: Sequence[str],
            *,
            batch_size: int,
            normalize_embeddings: bool,
            convert_to_numpy: bool,
        ):
            calls["inputs"] = list(inputs)
            calls["batch_size"] = batch_size
            calls["normalize"] = normalize_embeddings
            calls["numpy"] = convert_to_numpy
            calls["encode_thread"] = threading.get_ident()
            return Matrix()

    fake_sentence_transformers(monkeypatch, SentenceTransformer=Encoder)
    provider = sbert.SentenceTransformerEmbeddingProvider(
        model="sentence-transformers/fake",
        dimensions=2,
        batch_size=7,
    )

    vectors = asyncio.run(provider.embed_documents(["first", "second"]))
    repeated = asyncio.run(provider.embed_documents(["first", "second"]))

    assert vectors == repeated == [[1.0, 0.0], [0.0, 1.0]]
    assert calls == {
        "constructed": 1,
        "model": "sentence-transformers/fake",
        "inputs": ["first", "second"],
        "batch_size": 7,
        "normalize": True,
        "numpy": True,
        "constructor_thread": calls["constructor_thread"],
        "encode_thread": calls["encode_thread"],
    }
    assert calls["constructor_thread"] != main_thread
    assert calls["encode_thread"] != main_thread


def test_empty_batch_does_not_load_a_model(monkeypatch):
    """Return an empty batch without loading model weights."""
    constructor = Mock(side_effect=AssertionError("Empty batches must not load model weights"))
    fake_sentence_transformers(monkeypatch, SentenceTransformer=constructor)
    provider = sbert.SentenceTransformerEmbeddingProvider()

    assert asyncio.run(provider.embed_documents([])) == []
    constructor.assert_not_called()


def test_provider_output_still_passes_through_shared_validation(monkeypatch):
    """Validate local model output through the shared embedding boundary."""

    class Matrix:
        def tolist(self):
            return [[1.0, 0.0]]

    class Encoder:
        max_seq_length = 128
        tokenizer = staticmethod(fake_tokenizer)

        def __init__(self, model):
            self.model = model

        def get_sentence_embedding_dimension(self):
            return 2

        def encode(self, inputs, **kwargs):
            return Matrix()

    fake_sentence_transformers(monkeypatch, SentenceTransformer=Encoder)
    provider = sbert.SentenceTransformerEmbeddingProvider(dimensions=2)

    with pytest.raises(ValueError, match=r"returned 1 vectors for 2 inputs"):
        asyncio.run(provider.embed_documents(["first", "second"]))


def test_sbert_planning_and_encoding_share_special_token_limits(monkeypatch):
    """Plan with the actual model limit and reject excess tokens before encoding."""
    calls = []

    class Encoder:
        max_seq_length = 8
        tokenizer = staticmethod(fake_tokenizer)

        def __init__(self, model):
            """Record lazy model construction."""
            calls.append("load")

        def get_sentence_embedding_dimension(self):
            """Declare the synthetic encoder's actual dimension."""
            return 2

        def encode(self, inputs, **kwargs):
            """Record inference only after complete-input preflight."""
            calls.append("encode")
            return type("Matrix", (), {"tolist": lambda self: [[1.0, 0.0]]})()

    fake_sentence_transformers(monkeypatch, SentenceTransformer=Encoder)
    provider = sbert.SentenceTransformerEmbeddingProvider(dimensions=2)
    assert calls == []
    assert provider.max_input_tokens == 8
    assert provider.count_input_tokens("one two three four five six") == 8
    assert asyncio.run(provider.embed_documents(["one two three four five six"])) == [[1.0, 0.0]]
    with pytest.raises(ValueError, match="9 tokens including special tokens"):
        asyncio.run(provider.embed_documents(["one two three four five six seven"]))
    assert calls == ["load", "encode"]
