"""Embedding provider and missing-vector backfill tests."""

import asyncio
from collections.abc import Sequence
import math
import subprocess
import sys
from types import SimpleNamespace
from typing import cast

from pydantic import SecretStr, ValidationError
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.retrieval import embeddings
from tests.retrieval.support import RecordingSession, normalized_sql


class FakeEmbeddingData:
    """Represent one indexed SDK-like embedding item."""

    def __init__(self, index: int, embedding: list[float]) -> None:
        self.index = index
        self.embedding = embedding


class FakeEmbeddingResponse:
    """Represent the SDK response surface consumed by the provider."""

    def __init__(self, data: list[FakeEmbeddingData]) -> None:
        self.data = data
        self.usage = SimpleNamespace(prompt_tokens=6, total_tokens=6)


class FakeEmbeddingsResource:
    """Return configured embedding data while recording request payloads."""

    def __init__(
        self,
        data: list[FakeEmbeddingData],
        requests: list[dict[str, object]] | None = None,
    ) -> None:
        self.data = data
        self.requests = [] if requests is None else requests

    async def create(
        self,
        *,
        input: Sequence[str],
        model: str,
        dimensions: int,
        encoding_format: str,
    ) -> FakeEmbeddingResponse:
        """Record one request and return the configured SDK-like response."""
        self.requests.append(
            {
                "input": list(input),
                "model": model,
                "dimensions": dimensions,
                "encoding_format": encoding_format,
            }
        )
        return FakeEmbeddingResponse(self.data)


class FakeEmbeddingClient:
    """Provide the structural client surface consumed by the provider."""

    def __init__(
        self,
        data: list[FakeEmbeddingData],
        requests: list[dict[str, object]] | None = None,
    ) -> None:
        self.embeddings = FakeEmbeddingsResource(data, requests)


def dot(left, right) -> float:
    """Return a small dependency-free dot product."""
    return sum(a * b for a, b in zip(left, right, strict=True))


def test_deterministic_provider_is_384_dimensional_normalized_and_repeatable():
    """Produce repeatable, finite, unit-length vectors with database dimensions."""
    provider = embeddings.DeterministicEmbeddingProvider()
    texts = ["Research expense increased", "Unrelated market risk"]

    first = asyncio.run(provider.embed_documents(texts))
    second = asyncio.run(provider.embed_documents(texts))

    assert provider.dimensions == 384
    assert first == second
    assert all(len(vector) == 384 for vector in first)
    assert all(math.isclose(dot(vector, vector), 1.0) for vector in first)
    assert all(math.isfinite(component) for vector in first for component in vector)


def test_deterministic_provider_normalizes_tokens_and_preserves_lexical_overlap():
    """Normalize equivalent tokens while retaining lexical similarity."""
    provider = embeddings.DeterministicEmbeddingProvider()
    base, normalized, overlap, unrelated = asyncio.run(
        provider.embed_documents(
            [
                "Alpha BETA",
                "ＡＬＰＨＡ beta",
                "alpha gamma",
                "delta epsilon",
            ]
        )
    )

    assert base == normalized
    assert dot(base, overlap) > dot(base, unrelated)


def test_embedding_provider_validates_inputs_and_output_shape():
    """Reject empty inputs and invalid provider vector shapes or values."""
    provider = embeddings.DeterministicEmbeddingProvider()

    assert asyncio.run(provider.embed_documents([])) == []
    with pytest.raises(ValueError, match="nonempty"):
        asyncio.run(provider.embed_query(""))
    with pytest.raises(ValueError, match="dimension"):
        embeddings.validate_embeddings([[0.0]], expected_count=1, dimensions=2)
    with pytest.raises(ValueError, match="non-finite"):
        embeddings.validate_embeddings([[math.nan]], expected_count=1, dimensions=1)
    with pytest.raises(ValueError, match="nonnumeric"):
        embeddings.validate_embeddings([[True]], expected_count=1, dimensions=1)
    with pytest.raises(ValueError, match="nonzero norm"):
        embeddings.validate_embeddings([[0.0, 0.0]], expected_count=1, dimensions=2)


def test_openai_provider_requests_384_floats_and_restores_response_order():
    """Request explicit dimensions and restore caller order from response indices."""
    requests: list[dict[str, object]] = []
    client = FakeEmbeddingClient(
        data=[
            FakeEmbeddingData(index=1, embedding=[2.0] * 384),
            FakeEmbeddingData(index=0, embedding=[1.0] * 384),
        ],
        requests=requests,
    )
    provider = embeddings.OpenAIEmbeddingProvider(client=client)
    vectors = asyncio.run(provider.embed_documents(["first", "second"]))

    assert requests == [
        {
            "input": ["first", "second"],
            "model": "text-embedding-3-small",
            "dimensions": 384,
            "encoding_format": "float",
        }
    ]
    assert vectors[0][0] == 1.0
    assert vectors[1][0] == 2.0
    assert provider.usage.requests == 1
    assert provider.usage.input_tokens == 6


@pytest.mark.parametrize(
    "data",
    [
        [FakeEmbeddingData(index=0, embedding=[0.0] * 384)],
        [
            FakeEmbeddingData(index=0, embedding=[0.0] * 384),
            FakeEmbeddingData(index=0, embedding=[0.0] * 384),
        ],
        [
            FakeEmbeddingData(index=0, embedding=[0.0] * 383),
            FakeEmbeddingData(index=1, embedding=[0.0] * 384),
        ],
    ],
)
def test_openai_provider_rejects_incomplete_duplicate_or_wrong_dimension_data(
    data: list[FakeEmbeddingData],
):
    """Reject incomplete, duplicate-indexed, and malformed provider responses."""
    provider = embeddings.OpenAIEmbeddingProvider(client=FakeEmbeddingClient(data))
    with pytest.raises(ValueError):
        asyncio.run(provider.embed_documents(["first", "second"]))


def test_openai_sdk_import_is_lazy_for_direct_and_factory_paths():
    """Import the module and use injected clients without loading the OpenAI SDK."""
    script = """
import builtins
import sys
from types import ModuleType, SimpleNamespace

real_import = builtins.__import__

def blocked_import(name, *args, **kwargs):
    if name == "openai" or name.startswith("openai."):
        raise AssertionError("OpenAI SDK imported before a client was needed")
    return real_import(name, *args, **kwargs)

builtins.__import__ = blocked_import

from app.config import Settings
from app.retrieval.embeddings import (
    OpenAIEmbeddingProvider,
    get_embedding_provider,
)

class Resource:
    async def create(self, **kwargs):
        return SimpleNamespace(data=[])

class Client:
    embeddings = Resource()

client = Client()
OpenAIEmbeddingProvider(client=client)
get_embedding_provider(
    Settings(
        _env_file=None,
        embedding_provider="openai",
        openai_api_key="injected-key",
    ),
    client=client,
)

builtins.__import__ = real_import
created = []

class SDKClient:
    embeddings = Resource()

    def __init__(self, *, api_key):
        created.append(api_key)

fake_openai = ModuleType("openai")
fake_openai.AsyncOpenAI = SDKClient
sys.modules["openai"] = fake_openai

OpenAIEmbeddingProvider(api_key="direct-key")
get_embedding_provider(
    Settings(
        _env_file=None,
        embedding_provider="openai",
        openai_api_key="factory-key",
    )
)
assert created == ["direct-key", "factory-key"]
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize("api_key", [None, SecretStr(""), SecretStr("   ")])
def test_settings_require_nonblank_api_key_for_openai_provider(
    api_key: SecretStr | None,
):
    """Reject an OpenAI provider configured without an explicit usable API key."""
    with pytest.raises(ValidationError, match="OPENAI_API_KEY"):
        Settings(
            embedding_provider="openai",
            openai_api_key=api_key,
        )


def test_provider_factory_uses_validated_settings_without_network_access():
    """Build the configured deterministic provider without network access."""
    settings = Settings(
        embedding_provider="deterministic",
        embed_dim=384,
        embedding_batch_size=2,
    )

    provider = embeddings.get_embedding_provider(settings)

    assert isinstance(provider, embeddings.DeterministicEmbeddingProvider)
    assert provider.dimensions == 384


def test_missing_batch_selects_only_null_vectors_in_stable_chunk_order():
    """Select missing vectors in stable chunk order within a bounded transaction."""

    class Result:
        """Return one missing embedding row from a recorded query."""

        def all(self):
            """Expose all selected rows."""
            return [SimpleNamespace(id=7, index_text="indexed evidence")]

    session = RecordingSession(Result())
    pending = asyncio.run(
        embeddings._missing_batch(
            cast(AsyncSession, session),
            8,
            after_chunk_id=6,
        )
    )
    sql, params = normalized_sql(session.statements[0])

    assert pending == [embeddings.PendingEmbedding(chunk_id=7, index_text="indexed evidence")]
    assert "chunks.embedding IS NULL" in sql
    assert "chunks.id >" in sql
    assert "ORDER BY chunks.id" in sql
    assert 6 in params.values()
    assert 8 in params.values()


def test_store_batch_guards_null_state_and_the_embedded_text_version():
    """Store a batch in one guarded VALUES update and count returned rows."""

    class ScalarResult:
        """Expose identifiers returned by the guarded update."""

        def all(self):
            """Return the stored chunk identifiers."""
            return [7]

    class Result:
        """Expose the scalar projection of one update result."""

        def scalars(self):
            """Return the scalar result wrapper."""
            return ScalarResult()

    session = RecordingSession(Result())
    pending = [
        embeddings.PendingEmbedding(chunk_id=7, index_text="indexed evidence"),
        embeddings.PendingEmbedding(chunk_id=8, index_text="new evidence"),
    ]
    stored = asyncio.run(
        embeddings._store_batch(
            cast(AsyncSession, session),
            pending,
            [[0.0] * 384, [1.0] * 384],
        )
    )
    sql, params = normalized_sql(session.statements[0])

    assert stored == 1
    assert len(session.statements) == 1
    assert "FROM (VALUES" in sql
    assert "CAST(pending_embeddings.embedding AS VECTOR(384))" in sql
    assert "chunks.id =" in sql
    assert "chunks.embedding IS NULL" in sql
    assert "chunks.index_text =" in sql
    assert "RETURNING chunks.id" in sql
    assert "indexed evidence" in params.values()
    assert "new evidence" in params.values()


def test_backfill_batches_missing_chunks_and_reports_stale_updates(monkeypatch):
    """Skip a stale id once per run while continuing to later missing ids."""
    available = [
        embeddings.PendingEmbedding(chunk_id=1, index_text="stale"),
        embeddings.PendingEmbedding(chunk_id=2, index_text="second"),
        embeddings.PendingEmbedding(chunk_id=3, index_text="third"),
    ]
    selected_sizes = []
    selected_cursors = []
    stored_ids = []
    progress = []

    async def missing(_session, batch_size, *, after_chunk_id):
        """Return the next stable batch after the supplied cursor."""
        selected_sizes.append(batch_size)
        selected_cursors.append(after_chunk_id)
        return [
            item for item in available if after_chunk_id is None or item.chunk_id > after_chunk_id
        ][:batch_size]

    async def store(_session, pending, _vectors):
        """Record pending IDs while treating the first as stale."""
        stored_ids.append([item.chunk_id for item in pending])
        return sum(item.chunk_id != 1 for item in pending)

    monkeypatch.setattr(embeddings, "_missing_batch", missing)
    monkeypatch.setattr(embeddings, "_store_batch", store)
    monkeypatch.setattr(
        embeddings,
        "get_settings",
        lambda: SimpleNamespace(embedding_batch_size=2),
    )
    provider = embeddings.DeterministicEmbeddingProvider()
    session = cast(AsyncSession, RecordingSession(None))

    result = asyncio.run(
        embeddings.embed_missing_chunks(session, provider, on_batch=progress.append)
    )

    assert result == embeddings.EmbeddingBackfillResult(
        selected=3,
        embedded=2,
        skipped_stale=1,
        batches=2,
    )
    assert selected_sizes == [2, 2, 2]
    assert selected_cursors == [None, 2, 3]
    assert stored_ids == [[1, 2], [3]]
    assert progress == [
        embeddings.EmbeddingBackfillResult(2, 1, 1, 1),
        embeddings.EmbeddingBackfillResult(3, 2, 1, 2),
    ]


def test_backfill_rejects_invalid_batch_size_and_active_transactions():
    """Reject nonpositive batches and sessions with active transactions."""
    provider = embeddings.DeterministicEmbeddingProvider()

    with pytest.raises(ValueError, match="positive"):
        asyncio.run(
            embeddings.embed_missing_chunks(
                cast(AsyncSession, RecordingSession(None)),
                provider,
                batch_size=0,
            )
        )
    with pytest.raises(RuntimeError, match="active transaction"):
        asyncio.run(
            embeddings.embed_missing_chunks(
                cast(AsyncSession, RecordingSession(None, transaction_active=True)),
                provider,
                batch_size=1,
            )
        )
