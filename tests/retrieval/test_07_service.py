"""L7: production service composition and command output."""

import asyncio
import importlib
import os

from pydantic import ValidationError
import pytest

import app.retrieval as public
from app.retrieval.embeddings import DeterministicEmbeddingProvider, EmbeddingBackfillResult
from app.retrieval.types import ChunkHit, RetrievalFilters
from tests.retrieval.conftest import make_settings
from tests.retrieval.test_01_contract import hit_values
from tests.support import need

SERVICE_MODULE_NAME = os.getenv("RETRIEVAL_SERVICE_MODULE", "app.retrieval.service")
S = importlib.import_module(SERVICE_MODULE_NAME)
CLI = importlib.import_module("app.retrieval.__main__")


def hit(chunk_id: int, score: float, **changes) -> ChunkHit:
    """Build one valid service candidate with a unique source span."""
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


def test_public_query_normalization_preserves_compatibility():
    need(S, "normalize_query")

    assert S.normalize_query("NVDA 2024 R&D") == "NVDA 2024 research development"
    assert S.normalize_query("R & D spending") == "research development spending"
    assert S.normalize_query("sales & marketing") == "sales & marketing"
    assert S.normalize_query("research and development") == "research and development"
    assert S._normalize_query is S.normalize_query


def test_service_uses_default_candidate_pool_one_session_and_rank_only_components(monkeypatch):
    need(S, "ComponentRankings", "RetrievalResult", "retrieve")
    events = []
    session = object()
    filters = RetrievalFilters(doc_ids=("NVDA-FY2024",))

    class Provider(DeterministicEmbeddingProvider):
        async def embed_query(self, query):
            events.append(("embed", query))
            return [0.0] * self.dimensions

    async def vector(received_session, query_vector, *, k, filters):
        events.append(("vector", received_session, len(query_vector), k, filters))
        return [hit(1, 0.99), hit(2, 0.01)]

    async def lexical(received_session, query, k, filters):
        events.append(("lexical", received_session, query, k, filters))
        return [hit(2, 9_000.0), hit(3, 8_000.0)]

    monkeypatch.setattr(S, "vector_search", vector)
    monkeypatch.setattr(S, "lexical_search", lexical)

    result = asyncio.run(
        S.retrieve(
            session,
            "NVDA 2024 R&D",
            provider=Provider(),
            k=2,
            filters=filters,
        )
    )

    assert events[0] == ("embed", "NVDA 2024 research development")
    assert [event[0] for event in events] == ["embed", "vector", "lexical"]
    assert events[1][1] is session
    assert events[2][1] is session
    assert events[1][3] == 20
    assert events[2][3] == 20
    assert events[2][2] == "NVDA 2024 research development"
    assert [candidate.chunk_id for candidate in result.hits] == [2, 1]
    assert result.component_rankings.model_dump() == {
        "vector": (1, 2),
        "lexical": (2, 3),
    }
    assert all(
        "score" not in component for component in result.component_rankings.model_dump().values()
    )

    events.clear()
    asyncio.run(
        S.retrieve(
            session,
            "NVDA 2024 R&D",
            provider=Provider(),
            k=6,
            filters=filters,
        )
    )
    assert events[1][3] == 24
    assert events[2][3] == 24


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"query": " "}, "blank"),
        ({"k": 0}, "positive"),
        ({"k": 3, "candidate_k": 2}, "at least k"),
        ({"rrf_k": 0}, "positive"),
    ],
)
def test_service_rejects_invalid_requests_before_provider_or_database(
    monkeypatch, changes, message
):
    need(S, "retrieve")

    class Provider(DeterministicEmbeddingProvider):
        async def embed_query(self, _query):
            raise AssertionError("invalid input must not call the provider")

    async def search(*_args, **_kwargs):
        raise AssertionError("invalid input must not access the database")

    monkeypatch.setattr(S, "vector_search", search)
    monkeypatch.setattr(S, "lexical_search", search)
    arguments = {"query": "query", "provider": Provider(), "k": 2} | changes

    with pytest.raises(ValueError, match=message):
        asyncio.run(S.retrieve(object(), **arguments))


def test_service_rejects_a_provider_that_cannot_match_the_database_dimension():
    need(S, "retrieve")
    provider = DeterministicEmbeddingProvider(dimensions=32)

    with pytest.raises(ValueError, match="database dimension 384"):
        asyncio.run(S.retrieve(object(), "query", provider=provider))


def test_application_settings_freeze_the_m2_database_dimension_at_384():
    assert make_settings().embed_dim == 384

    with pytest.raises(ValidationError):
        make_settings(embed_dim=256)


def test_package_exports_the_complete_production_surface():
    expected = {
        "ComponentRankings",
        "DeterministicEmbeddingProvider",
        "EmbeddingProvider",
        "OpenAIEmbeddingProvider",
        "RetrievalResult",
        "embed_missing_chunks",
        "hybrid_search",
        "lexical_search",
        "retrieve",
        "rrf_fuse",
        "vector_search",
    }

    assert expected <= set(public.__all__)
    assert public.retrieve is S.retrieve


def test_cli_acceptance_arguments_and_payload_keep_component_scores_private():
    args = CLI.arguments(
        [
            "--query",
            "NVDA 2024 R&D",
            "--k",
            "2",
            "--candidate-k",
            "4",
            "--provider",
            "deterministic",
            "--embed-missing",
        ]
    )
    result = S.RetrievalResult(
        hits=(hit(1, 1 / 61),),
        component_rankings=S.ComponentRankings(vector=(1, 2), lexical=(1,)),
    )
    payload = CLI._payload(
        query=args.query,
        provider=args.provider,
        backfill=EmbeddingBackfillResult(3, 3, 0, 1),
        result=result,
    )

    assert (args.k, args.candidate_k, args.embed_missing) == (2, 4, True)
    assert payload["provider"] == "deterministic"
    assert payload["backfill"] == {
        "selected": 3,
        "embedded": 3,
        "skipped_stale": 0,
        "batches": 1,
    }
    assert payload["component_rankings"] == {"vector": [1, 2], "lexical": [1]}
    assert set(payload["component_rankings"]) == {"vector", "lexical"}
