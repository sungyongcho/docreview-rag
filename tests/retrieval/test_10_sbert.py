"""L10: local sentence-transformer embeddings and production wiring."""

import asyncio
from collections.abc import Sequence
import sys
import threading
from types import ModuleType
from typing import Any

import pytest

from app.db.models import DIM
from app.retrieval.embeddings import get_embedding_provider
from tests.retrieval.conftest import make_settings
from tests.support import need, optional_module

PUBLIC = optional_module("app.retrieval")
SBERT = optional_module("app.retrieval.sbert")
PROVIDER = "SentenceTransformerEmbeddingProvider"


def need_sbert_setting() -> None:
    """Skip until ``embedding_provider`` accepts the local backend."""
    try:
        make_settings(embedding_provider="sbert")
    except Exception:
        pytest.skip("not implemented yet: Settings(embedding_provider='sbert')")


def fake_sentence_transformers(monkeypatch, encoder_type: type[object]) -> None:
    """Expose one fake encoder through the optional third-party module name."""
    module = ModuleType("sentence_transformers")
    module.__dict__["SentenceTransformer"] = encoder_type
    monkeypatch.setitem(sys.modules, "sentence_transformers", module)


def test_public_surface_exports_sbert_provider():
    need(SBERT, PROVIDER)
    need(PUBLIC, PROVIDER)
    assert getattr(PUBLIC, PROVIDER) is SBERT.SentenceTransformerEmbeddingProvider
    assert PROVIDER in PUBLIC.__all__


def test_constructing_provider_loads_no_model():
    need(SBERT, PROVIDER)
    provider = SBERT.SentenceTransformerEmbeddingProvider()
    assert provider._encoder is None


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
    need(SBERT, PROVIDER)
    need(SBERT, PROVIDER)
    with pytest.raises(ValueError):
        SBERT.SentenceTransformerEmbeddingProvider(
            model=model,
            dimensions=dimensions,
            batch_size=batch_size,
        )


def test_provider_defaults_match_the_database_column():
    need(SBERT, PROVIDER)
    assert SBERT.SentenceTransformerEmbeddingProvider().dimensions == DIM


def test_factory_builds_configured_sbert_provider_without_loading_model():
    need(SBERT, PROVIDER)
    need_sbert_setting()
    settings = make_settings(
        embedding_provider="sbert",
        sbert_model="sentence-transformers/test-model",
    )

    provider: Any = get_embedding_provider(settings)

    assert isinstance(provider, SBERT.SentenceTransformerEmbeddingProvider)
    assert provider.model == "sentence-transformers/test-model"
    assert provider.dimensions == DIM
    assert provider._encoder is None


def test_cli_accepts_sbert_provider():
    need_sbert_setting()
    from app.retrieval.__main__ import arguments

    args = arguments(["--query", "market risk", "--provider", "sbert"])

    assert args.provider == "sbert"


def test_missing_extra_raises_an_actionable_runtime_error(monkeypatch):
    need(SBERT, PROVIDER)
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)

    with pytest.raises(RuntimeError, match=r"uv sync --extra cpu"):
        SBERT.SentenceTransformerEmbeddingProvider()._load()


def test_load_rejects_a_model_with_the_wrong_dimension(monkeypatch):
    need(SBERT, PROVIDER)

    class Encoder:
        def __init__(self, model):
            self.model = model

        def get_sentence_embedding_dimension(self):
            return 768

    fake_sentence_transformers(monkeypatch, Encoder)
    provider = SBERT.SentenceTransformerEmbeddingProvider(dimensions=384)

    with pytest.raises(ValueError, match=r"produces 768 dimensions"):
        provider._load()

    assert provider._encoder is None


def test_embed_documents_reuses_the_model_and_runs_encode_off_loop(monkeypatch):
    need(SBERT, PROVIDER)
    main_thread = threading.get_ident()
    calls: dict[str, Any] = {"constructed": 0}

    class Matrix:
        def tolist(self):
            return [[1.0, 0.0], [0.0, 1.0]]

    class Encoder:
        def __init__(self, model):
            calls["constructed"] = int(calls["constructed"]) + 1
            calls["model"] = model

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
            calls["thread"] = threading.get_ident()
            return Matrix()

    fake_sentence_transformers(monkeypatch, Encoder)
    provider = SBERT.SentenceTransformerEmbeddingProvider(
        model="sentence-transformers/fake",
        dimensions=2,
        batch_size=7,
    )

    vectors = asyncio.run(provider.embed_documents(["first", "second"]))
    assert provider._load() is provider._encoder

    assert vectors == [[1.0, 0.0], [0.0, 1.0]]
    assert calls == {
        "constructed": 1,
        "model": "sentence-transformers/fake",
        "inputs": ["first", "second"],
        "batch_size": 7,
        "normalize": True,
        "numpy": True,
        "thread": calls["thread"],
    }
    assert calls["thread"] != main_thread


def test_empty_batch_does_not_load_a_model():
    need(SBERT, PROVIDER)
    provider = SBERT.SentenceTransformerEmbeddingProvider()

    assert asyncio.run(provider.embed_documents([])) == []
    assert provider._encoder is None


def test_provider_output_still_passes_through_shared_validation(monkeypatch):
    need(SBERT, PROVIDER)

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

    fake_sentence_transformers(monkeypatch, Encoder)
    provider = SBERT.SentenceTransformerEmbeddingProvider(dimensions=2)

    with pytest.raises(ValueError, match=r"returned 1 vectors for 2 inputs"):
        asyncio.run(provider.embed_documents(["first", "second"]))
