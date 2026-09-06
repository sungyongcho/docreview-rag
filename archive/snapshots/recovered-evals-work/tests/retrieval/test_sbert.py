"""Local sentence-transformer provider and wiring tests."""

import asyncio
from collections.abc import Sequence
import sys
import threading
import time
from typing import Any

import pytest

from app.config import Settings
from app.db.models import DIM
import app.retrieval as public
from app.retrieval import sbert
from app.retrieval.embeddings import get_embedding_provider
from tests.retrieval.support import fake_sentence_transformers


def test_public_surface_exports_sbert_provider():
    """Export the sentence-transformer provider from the public façade."""
    assert public.SentenceTransformerEmbeddingProvider is sbert.SentenceTransformerEmbeddingProvider
    assert "SentenceTransformerEmbeddingProvider" in public.__all__


def test_constructing_provider_loads_no_model():
    """Construct the local provider without loading model weights."""
    provider = sbert.SentenceTransformerEmbeddingProvider()
    assert provider._encoder.value is None


@pytest.mark.parametrize(
    ("model", "dimensions", "batch_size"),
    [
        ("", 384, 32),
        ("model", 0, 32),
        ("model", -1, 32),
        ("model", 384, 0),
        ("model", 384, -1),
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


def test_provider_defaults_match_the_database_column():
    """Match local embedding dimensions to the database column."""
    assert sbert.SentenceTransformerEmbeddingProvider().dimensions == DIM


def test_factory_builds_configured_sbert_provider_without_loading_model():
    """Build the configured local provider without loading weights."""
    settings = Settings(
        embedding_provider="sbert",
        sbert_model="sentence-transformers/test-model",
    )

    provider: Any = get_embedding_provider(settings)

    assert isinstance(provider, sbert.SentenceTransformerEmbeddingProvider)
    assert provider.model == "sentence-transformers/test-model"
    assert provider.dimensions == DIM
    assert provider._encoder.value is None


def test_cli_accepts_sbert_provider():
    """Accept the local embedding provider through the CLI."""
    from app.retrieval.__main__ import arguments

    args = arguments(["--query", "market risk", "--provider", "sbert"])

    assert args.provider == "sbert"


def test_missing_extra_raises_an_actionable_runtime_error(monkeypatch):
    """Raise an actionable error when the optional model package is absent."""
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)

    with pytest.raises(RuntimeError, match=r"uv sync --extra cpu"):
        sbert.SentenceTransformerEmbeddingProvider()._load()


def test_load_rejects_a_model_with_the_wrong_dimension(monkeypatch):
    """Reject local models whose output width differs from the database."""

    class Encoder:
        def __init__(self, model):
            self.model = model

        def get_sentence_embedding_dimension(self):
            return 768

    fake_sentence_transformers(monkeypatch, SentenceTransformer=Encoder)
    provider = sbert.SentenceTransformerEmbeddingProvider(dimensions=384)

    with pytest.raises(ValueError, match=r"produces 768 dimensions"):
        provider._load()

    assert provider._encoder.value is None


def test_embed_documents_reuses_the_model_and_runs_model_off_loop(monkeypatch):
    """Reuse one model and run construction and encoding off the event loop."""
    main_thread = threading.get_ident()
    calls: dict[str, Any] = {"constructed": 0}

    class Matrix:
        def tolist(self):
            return [[1.0, 0.0], [0.0, 1.0]]

    class Encoder:
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
    assert provider._load() is provider._encoder.value

    assert vectors == [[1.0, 0.0], [0.0, 1.0]]
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


def test_simultaneous_cold_embeddings_construct_one_model(monkeypatch):
    """Serialize a simultaneous cold load and share the constructed model."""
    constructors: list[str] = []

    class Matrix:
        def __init__(self, size: int) -> None:
            self.size = size

        def tolist(self):
            return [[1.0, 0.0] for _ in range(self.size)]

    class Encoder:
        def __init__(self, model):
            constructors.append(model)
            time.sleep(0.05)

        def get_sentence_embedding_dimension(self):
            return 2

        def encode(self, inputs, **kwargs):
            return Matrix(len(inputs))

    fake_sentence_transformers(monkeypatch, SentenceTransformer=Encoder)
    provider = sbert.SentenceTransformerEmbeddingProvider(
        model="sentence-transformers/fake",
        dimensions=2,
    )

    async def embed_concurrently():
        return await asyncio.gather(
            provider.embed_documents(["first"]),
            provider.embed_documents(["second"]),
        )

    vectors = asyncio.run(embed_concurrently())

    assert vectors == [[[1.0, 0.0]], [[1.0, 0.0]]]
    assert constructors == ["sentence-transformers/fake"]


def test_empty_batch_does_not_load_a_model():
    """Return an empty batch without loading model weights."""
    provider = sbert.SentenceTransformerEmbeddingProvider()

    assert asyncio.run(provider.embed_documents([])) == []
    assert provider._encoder.value is None


def test_provider_output_still_passes_through_shared_validation(monkeypatch):
    """Validate local model output through the shared embedding boundary."""

    class Matrix:
        def tolist(self):
            return [[1.0, 0.0]]

    class Encoder:
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
