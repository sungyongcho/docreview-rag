"""L2: async embedding providers and resumable missing-vector backfill."""

import asyncio
import importlib
import math
import os
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from tests.retrieval.conftest import make_settings
from tests.support import need

EMBEDDINGS_MODULE_NAME = os.getenv("RETRIEVAL_EMBEDDINGS_MODULE", "app.retrieval.embeddings")
E = importlib.import_module(EMBEDDINGS_MODULE_NAME)


def dot(left, right) -> float:
    """Return a small dependency-free dot product."""
    return sum(a * b for a, b in zip(left, right, strict=True))


def normalized_sql(statement) -> tuple[str, dict[str, object]]:
    """Compile PostgreSQL SQL with normalized whitespace."""
    compiled = statement.compile(dialect=postgresql.dialect())
    return " ".join(str(compiled).split()), compiled.params


def test_deterministic_provider_is_384_dimensional_normalized_and_repeatable():
    need(E, "DeterministicEmbeddingProvider")
    provider = E.DeterministicEmbeddingProvider()
    texts = ["Research expense increased", "Unrelated market risk"]

    first = asyncio.run(provider.embed_documents(texts))
    second = asyncio.run(provider.embed_documents(texts))

    assert provider.dimensions == 384
    assert first == second
    assert all(len(vector) == 384 for vector in first)
    assert all(math.isclose(dot(vector, vector), 1.0) for vector in first)
    assert all(math.isfinite(component) for vector in first for component in vector)


def test_deterministic_provider_normalizes_tokens_and_preserves_lexical_overlap():
    need(E, "DeterministicEmbeddingProvider")
    provider = E.DeterministicEmbeddingProvider()
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
    need(E, "DeterministicEmbeddingProvider", "validate_embeddings")
    provider = E.DeterministicEmbeddingProvider()

    assert asyncio.run(provider.embed_documents([])) == []
    with pytest.raises(ValueError, match="nonempty"):
        asyncio.run(provider.embed_query(""))
    with pytest.raises(ValueError, match="dimension"):
        E.validate_embeddings([[0.0]], expected_count=1, dimensions=2)
    with pytest.raises(ValueError, match="non-finite"):
        E.validate_embeddings([[math.nan]], expected_count=1, dimensions=1)
    with pytest.raises(ValueError, match="nonnumeric"):
        E.validate_embeddings([[True]], expected_count=1, dimensions=1)


def test_openai_provider_requests_384_floats_and_restores_response_order():
    need(E, "OpenAIEmbeddingProvider")
    requests = []

    class Embeddings:
        async def create(self, **kwargs):
            requests.append(kwargs)
            return SimpleNamespace(
                data=[
                    SimpleNamespace(index=1, embedding=[2.0] * 384),
                    SimpleNamespace(index=0, embedding=[1.0] * 384),
                ]
            )

    client = SimpleNamespace(embeddings=Embeddings())
    provider = E.OpenAIEmbeddingProvider(client=client)
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


@pytest.mark.parametrize(
    "data",
    [
        [SimpleNamespace(index=0, embedding=[0.0] * 384)],
        [
            SimpleNamespace(index=0, embedding=[0.0] * 384),
            SimpleNamespace(index=0, embedding=[0.0] * 384),
        ],
        [
            SimpleNamespace(index=0, embedding=[0.0] * 383),
            SimpleNamespace(index=1, embedding=[0.0] * 384),
        ],
    ],
)
def test_openai_provider_rejects_incomplete_duplicate_or_wrong_dimension_data(data):
    need(E, "OpenAIEmbeddingProvider")

    class Embeddings:
        async def create(self, **_kwargs):
            return SimpleNamespace(data=data)

    provider = E.OpenAIEmbeddingProvider(client=SimpleNamespace(embeddings=Embeddings()))
    with pytest.raises(ValueError):
        asyncio.run(provider.embed_documents(["first", "second"]))


def test_provider_factory_uses_validated_settings_without_network_access():
    need(E, "DeterministicEmbeddingProvider", "get_embedding_provider")
    settings = make_settings(
        embedding_provider="deterministic",
        embed_dim=384,
        embedding_batch_size=2,
    )

    provider = E.get_embedding_provider(settings)

    assert isinstance(provider, E.DeterministicEmbeddingProvider)
    assert provider.dimensions == 384


def test_missing_batch_selects_only_null_vectors_in_stable_chunk_order():
    need(E, "_missing_batch")

    class Transaction:
        async def __aenter__(self):
            return None

        async def __aexit__(self, *_args):
            return None

    class Result:
        def all(self):
            return [SimpleNamespace(id=7, index_text="indexed evidence")]

    class Session:
        def __init__(self):
            self.statements = []

        def begin(self):
            return Transaction()

        async def execute(self, statement):
            self.statements.append(statement)
            return Result()

    session = Session()
    pending = asyncio.run(E._missing_batch(session, 8))
    sql, params = normalized_sql(session.statements[0])

    assert pending == [E.PendingEmbedding(chunk_id=7, index_text="indexed evidence")]
    assert "chunks.embedding IS NULL" in sql
    assert "ORDER BY chunks.id" in sql
    assert 8 in params.values()


def test_store_batch_guards_null_state_and_the_embedded_text_version():
    need(E, "PendingEmbedding", "_store_batch")

    class Transaction:
        async def __aenter__(self):
            return None

        async def __aexit__(self, *_args):
            return None

    class Session:
        def __init__(self):
            self.statements = []

        def begin(self):
            return Transaction()

        async def execute(self, statement):
            self.statements.append(statement)
            return SimpleNamespace(rowcount=1)

    session = Session()
    pending = [E.PendingEmbedding(chunk_id=7, index_text="indexed evidence")]
    stored = asyncio.run(E._store_batch(session, pending, [[0.0] * 384]))
    sql, params = normalized_sql(session.statements[0])

    assert stored == 1
    assert "chunks.id =" in sql
    assert "chunks.embedding IS NULL" in sql
    assert "chunks.index_text =" in sql
    assert "indexed evidence" in params.values()


def test_backfill_batches_missing_chunks_and_reports_stale_updates(monkeypatch):
    need(E, "EmbeddingBackfillResult", "PendingEmbedding", "embed_missing_chunks")
    batches = [
        [
            E.PendingEmbedding(chunk_id=1, index_text="first"),
            E.PendingEmbedding(chunk_id=2, index_text="second"),
        ],
        [E.PendingEmbedding(chunk_id=3, index_text="third")],
        [],
    ]
    selected_sizes = []
    stored_ids = []

    async def missing(_session, batch_size):
        selected_sizes.append(batch_size)
        return batches.pop(0)

    async def store(_session, pending, _vectors):
        stored_ids.append([item.chunk_id for item in pending])
        return len(pending) if pending[0].chunk_id == 1 else 0

    monkeypatch.setattr(E, "_missing_batch", missing)
    monkeypatch.setattr(E, "_store_batch", store)
    monkeypatch.setattr(
        E,
        "get_settings",
        lambda: SimpleNamespace(embedding_batch_size=2),
    )
    provider = E.DeterministicEmbeddingProvider()
    session = SimpleNamespace(in_transaction=lambda: False)

    result = asyncio.run(E.embed_missing_chunks(session, provider))

    assert result == E.EmbeddingBackfillResult(
        selected=3,
        embedded=2,
        skipped_stale=1,
        batches=2,
    )
    assert selected_sizes == [2, 2, 2]
    assert stored_ids == [[1, 2], [3]]


def test_backfill_rejects_invalid_batch_size_and_active_transactions():
    need(E, "DeterministicEmbeddingProvider", "embed_missing_chunks")
    provider = E.DeterministicEmbeddingProvider()

    with pytest.raises(ValueError, match="positive"):
        asyncio.run(
            E.embed_missing_chunks(
                SimpleNamespace(in_transaction=lambda: False),
                provider,
                batch_size=0,
            )
        )
    with pytest.raises(RuntimeError, match="active transaction"):
        asyncio.run(
            E.embed_missing_chunks(
                SimpleNamespace(in_transaction=lambda: True),
                provider,
                batch_size=1,
            )
        )
