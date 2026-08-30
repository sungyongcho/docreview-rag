"""Retrieval service composition and command-output tests."""

import asyncio
import math
from typing import cast

from pydantic import ValidationError
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
import app.retrieval as public
from app.retrieval import __main__ as cli, service
from app.retrieval.embeddings import DeterministicEmbeddingProvider, EmbeddingBackfillResult
from app.retrieval.rerank import RerankProvider
from app.retrieval.types import RetrievalFilters
from tests.retrieval.support import hit


def test_public_query_normalization_preserves_compatibility():
    """Expand R&D variants without changing unrelated ampersands."""

    assert service.normalize_query("NVDA 2024 R&D") == "NVDA 2024 research development"
    assert service.normalize_query("R & D spending") == "research development spending"
    assert service.normalize_query("sales & marketing") == "sales & marketing"
    assert service.normalize_query("research and development") == "research and development"


def test_service_uses_default_candidate_pool_one_session_and_rank_only_components(monkeypatch):
    """Share one session and preserve rank-only component provenance."""
    events = []
    session = cast(AsyncSession, object())
    filters = RetrievalFilters(doc_ids=("NVDA-FY2024",))

    class Provider(DeterministicEmbeddingProvider):
        async def embed_query(self, query):
            events.append(("embed", query))
            return [0.0] * self.dimensions

    async def vector(received_session, query_vector, *, k, filters):
        events.append(("vector", received_session, len(query_vector), k, filters))
        return [hit(1, 0.99), hit(2, 0.01)]

    async def lexical(received_session, query, k, filters, *, text_search_config):
        events.append(("lexical", received_session, query, k, filters))
        return [hit(2, 9_000.0), hit(3, 8_000.0)]

    monkeypatch.setattr(service, "vector_search", vector)
    monkeypatch.setattr(service, "lexical_search", lexical)

    result = asyncio.run(
        service.retrieve(
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
    assert result.score_stage == "rrf"
    assert result.component_rankings.model_dump() == {
        "vector": (1, 2),
        "lexical": (2, 3),
    }
    assert set(service.ComponentRankings.model_fields) == {"vector", "lexical"}
    assert all(
        type(chunk_id) is int
        for ranking in result.component_rankings.model_dump().values()
        for chunk_id in ranking
    )

    events.clear()
    asyncio.run(
        service.retrieve(
            session,
            "NVDA 2024 R&D",
            provider=Provider(),
            k=6,
            filters=filters,
        )
    )
    assert events[1][3] == 24
    assert events[2][3] == 24


@pytest.mark.parametrize("chunk_id", ["3", 4.0, True])
def test_component_rankings_reject_non_strict_chunk_ids(chunk_id):
    """Reject coercible values so component provenance keeps strict identities."""
    with pytest.raises(ValidationError):
        service.ComponentRankings.model_validate({"vector": (chunk_id,), "lexical": ()})


def test_service_reranks_with_original_query_and_labels_the_score_stage(monkeypatch):
    """Normalize retrieval only, then label scores produced by the reranker."""
    session = cast(AsyncSession, object())
    rerank_calls = []

    async def vector(_session, _query_vector, *, k, filters):
        assert k == 2
        return [hit(1, 0.9), hit(2, 0.8)]

    async def lexical(_session, query, k, filters, *, text_search_config):
        assert query == "NVDA research development spending"
        assert k == 2
        return []

    class Reranker(RerankProvider):
        async def score(self, query, documents):
            rerank_calls.append((query, len(documents)))
            return [0.1, 0.9]

    monkeypatch.setattr(service, "vector_search", vector)
    monkeypatch.setattr(service, "lexical_search", lexical)

    result = asyncio.run(
        service.retrieve(
            session,
            "NVDA R&D spending",
            provider=DeterministicEmbeddingProvider(),
            k=1,
            candidate_k=2,
            reranker=Reranker(),
        )
    )

    assert rerank_calls == [("NVDA R&D spending", 2)]
    assert [candidate.chunk_id for candidate in result.hits] == [2]
    assert result.score_stage == "reranker"


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"query": " "}, "blank"),
        ({"k": 0}, "positive"),
        ({"k": -3}, "positive"),
        ({"k": 3, "candidate_k": 2}, "at least k"),
        ({"rrf_k": 0}, "positive"),
        ({"bm25_k1": math.inf}, "finite positive"),
        ({"bm25_k1": math.nan}, "finite positive"),
        ({"bm25_b": math.inf}, "finite number"),
        ({"bm25_b": math.nan}, "finite number"),
    ],
)
def test_service_rejects_invalid_requests_before_provider_or_hybrid_search(
    monkeypatch, changes, message
):
    """Validate service-owned inputs before building a provider or searching."""

    def build_provider():
        raise AssertionError("invalid input must not build the provider")

    async def search(*_args, **_kwargs):
        raise AssertionError("invalid input must not reach hybrid search")

    monkeypatch.setattr(service, "get_embedding_provider", build_provider)
    monkeypatch.setattr(service, "hybrid_search", search)
    arguments = {"query": "query", "k": 2} | changes

    with pytest.raises(ValueError, match=message):
        asyncio.run(service.retrieve(cast(AsyncSession, object()), **arguments))


def test_service_rejects_a_shallow_candidate_pool_with_a_reranker(monkeypatch):
    """Keep candidate depth at least the requested final result count."""

    class Provider(DeterministicEmbeddingProvider):
        async def embed_query(self, _query):
            raise AssertionError("invalid limits must not call the provider")

    class Reranker(RerankProvider):
        async def score(self, _query, _documents):
            raise AssertionError("invalid limits must not call the reranker")

    async def search(*_args, **_kwargs):
        raise AssertionError("invalid limits must not access the database")

    monkeypatch.setattr(service, "vector_search", search)
    monkeypatch.setattr(service, "lexical_search", search)

    with pytest.raises(ValueError, match="candidate_k must be at least k"):
        asyncio.run(
            service.retrieve(
                cast(AsyncSession, object()),
                "query",
                provider=Provider(),
                k=3,
                candidate_k=2,
                reranker=Reranker(),
            )
        )


def test_service_builds_and_validates_default_provider_before_hybrid_search(monkeypatch):
    """Build and dimension-check the default provider before composing retrieval."""
    calls = []

    def build_provider():
        calls.append("provider")
        return DeterministicEmbeddingProvider(dimensions=32)

    async def search(*_args, **_kwargs):
        raise AssertionError("an invalid provider must not reach hybrid search")

    monkeypatch.setattr(service, "get_embedding_provider", build_provider)
    monkeypatch.setattr(service, "hybrid_search", search)

    with pytest.raises(ValueError, match="database dimension 384"):
        asyncio.run(service.retrieve(cast(AsyncSession, object()), "query"))

    assert calls == ["provider"]


def test_application_settings_freeze_the_database_dimension_at_384():
    """Keep application embedding dimensions fixed to the database schema."""
    assert Settings().embed_dim == 384

    with pytest.raises(ValidationError):
        Settings.model_validate({"embed_dim": 256})


def test_package_exports_the_complete_production_surface():
    """Expose the complete baseline retrieval façade."""
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
    assert public.retrieve is service.retrieve


def test_cli_acceptance_arguments_and_payload_keep_component_scores_private():
    """Keep native component scores out of command output."""
    args = cli.arguments(
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
    result = service.RetrievalResult(
        hits=(hit(1, 1 / 61),),
        score_stage="rrf",
        component_rankings=service.ComponentRankings(vector=(1, 2), lexical=(1,)),
    )
    payload = cli._payload(
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
    assert payload["score_stage"] == "rrf"
    component_rankings = payload["component_rankings"]
    assert isinstance(component_rankings, dict)
    assert component_rankings == {"vector": [1, 2], "lexical": [1]}
    assert set(component_rankings) == {"vector", "lexical"}


@pytest.mark.parametrize(
    ("flag", "value", "message"),
    [
        ("--bm25-k1", "0", "--bm25-k1 must be a finite positive number"),
        ("--bm25-k1", "-1", "--bm25-k1 must be a finite positive number"),
        ("--bm25-k1", "nan", "--bm25-k1 must be a finite positive number"),
        ("--bm25-k1", "inf", "--bm25-k1 must be a finite positive number"),
        ("--bm25-b", "-0.1", "--bm25-b must be a finite number between 0 and 1"),
        ("--bm25-b", "1.1", "--bm25-b must be a finite number between 0 and 1"),
        ("--bm25-b", "nan", "--bm25-b must be a finite number between 0 and 1"),
        ("--bm25-b", "inf", "--bm25-b must be a finite number between 0 and 1"),
    ],
)
def test_cli_rejects_invalid_bm25_overrides_during_argument_parsing(capsys, flag, value, message):
    """Reject invalid BM25 overrides before command execution can touch the database."""
    with pytest.raises(SystemExit) as exc_info:
        cli.arguments(["--query", "market risk", flag, value, "--rebuild-bm25-stats"])

    assert exc_info.value.code == 2
    assert message in capsys.readouterr().err


def test_routing_skips_the_lexical_component_only_for_korean_queries(monkeypatch):
    """Skip the English lexical component for a Korean query and keep it for English."""
    events = []

    class Provider(DeterministicEmbeddingProvider):
        async def embed_query(self, query):
            events.append(("embed", query))
            return [0.0] * self.dimensions

    async def vector(received_session, query_vector, *, k, filters):
        events.append(("vector", k))
        return [hit(1, 0.99)]

    async def lexical(received_session, query, k, filters, *, text_search_config):
        events.append(("lexical", query))
        return [hit(2, 9_000.0)]

    monkeypatch.setattr(service, "vector_search", vector)
    monkeypatch.setattr(service, "lexical_search", lexical)

    korean = asyncio.run(
        service.retrieve(
            cast(AsyncSession, object()),
            "AMD의 매출총이익률은 어떻게 변화했습니까?",
            provider=Provider(),
            k=2,
            filters=RetrievalFilters(),
            route_by_language=True,
        )
    )

    assert [event[0] for event in events] == ["embed", "vector"]
    assert korean.component_rankings.lexical == ()
    assert korean.component_rankings.vector == (1,)
    assert [candidate.chunk_id for candidate in korean.hits] == [1]

    events.clear()
    english = asyncio.run(
        service.retrieve(
            cast(AsyncSession, object()),
            "How did AMD's gross margin change?",
            provider=Provider(),
            k=2,
            route_by_language=True,
        )
    )

    assert [event[0] for event in events] == ["embed", "vector", "lexical"]
    assert english.component_rankings.lexical == (2,)


def test_routing_stays_off_for_a_caller_that_does_not_ask_for_it(monkeypatch):
    """Keep the lexical component for a Korean query the caller did not route."""
    events = []

    class Provider(DeterministicEmbeddingProvider):
        async def embed_query(self, query):
            return [0.0] * self.dimensions

    async def vector(received_session, query_vector, *, k, filters):
        return [hit(1, 0.99)]

    async def lexical(received_session, query, k, filters, *, text_search_config):
        events.append(query)
        return [hit(2, 9_000.0)]

    monkeypatch.setattr(service, "vector_search", vector)
    monkeypatch.setattr(service, "lexical_search", lexical)

    session = cast(AsyncSession, object())
    result = asyncio.run(service.retrieve(session, "AMD의 매출은?", provider=Provider(), k=2))

    # The service holds no opinion of its own: it never reads Settings, so an arm
    # measured here cannot inherit a query path its recorded config does not name.
    assert events == ["AMD의 매출은?"]
    assert result.component_rankings.lexical == (2,)
    assert "get_settings" not in vars(service)


@pytest.mark.parametrize(
    ("configured", "flags", "expected"),
    [
        (False, [], False),
        (True, [], True),
        (False, ["--route-by-language"], True),
        (True, ["--no-route-by-language"], False),
    ],
)
def test_cli_resolves_language_routing_from_settings_and_honours_an_override(
    monkeypatch, configured, flags, expected
):
    """Read routing from settings at the command boundary, overridable in both ways."""
    from app.db import session as db_session

    seen: dict[str, object] = {}

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
        return service.RetrievalResult(
            hits=(hit(1, 1 / 61),),
            score_stage="rrf",
            component_rankings=service.ComponentRankings(vector=(1,), lexical=()),
        )

    settings = Settings(query_language_routing=configured)
    monkeypatch.setattr(db_session, "Session", Session)
    monkeypatch.setattr(db_session, "engine", Engine())
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(cli, "get_embedding_provider", lambda _settings: object())
    monkeypatch.setattr(cli, "retrieve", retrieve)

    payload = asyncio.run(cli._run(cli.arguments(["--query", "AMD의 매출은?", *flags])))

    # The value the command executed and the value it reports must be the same one,
    # or the evidence would name a query path the run did not take.
    assert seen["route_by_language"] is expected
    assert payload["route_by_language"] is expected


def test_korean_corpus_filter_tokenizes_the_lexical_query(monkeypatch):
    """A ko corpus filter sends n-gram tokens under the simple configuration."""
    calls = []
    session = cast(AsyncSession, object())

    async def vector(received_session, query_vector, *, k, filters):
        return [hit(1, 0.9)]

    async def lexical(received_session, query, k, filters, *, text_search_config):
        calls.append((query, text_search_config))
        return [hit(2, 5.0)]

    monkeypatch.setattr(service, "vector_search", vector)
    monkeypatch.setattr(service, "lexical_search", lexical)

    asyncio.run(
        service.retrieve(
            session,
            "삼성전자 매출",
            provider=DeterministicEmbeddingProvider(),
            k=2,
            filters=RetrievalFilters(languages=("ko",)),
        )
    )

    assert calls == [("삼성 성전 전자 매출", "simple")]


def test_english_corpus_keeps_the_raw_query_and_english_config(monkeypatch):
    """Without a ko filter the lexical component behaves exactly as committed."""
    calls = []
    session = cast(AsyncSession, object())

    async def vector(received_session, query_vector, *, k, filters):
        return [hit(1, 0.9)]

    async def lexical(received_session, query, k, filters, *, text_search_config):
        calls.append((query, text_search_config))
        return [hit(2, 5.0)]

    monkeypatch.setattr(service, "vector_search", vector)
    monkeypatch.setattr(service, "lexical_search", lexical)

    asyncio.run(
        service.retrieve(
            session,
            "NVDA data center revenue",
            provider=DeterministicEmbeddingProvider(),
            k=2,
        )
    )

    assert calls == [("NVDA data center revenue", "english")]


def test_mixed_language_filter_is_refused_for_lexical_retrieval():
    """One statement cannot parse a query under two tokenizations at once."""
    session = cast(AsyncSession, object())

    with pytest.raises(ValueError, match="cannot span corpus languages"):
        asyncio.run(
            service.retrieve(
                session,
                "query",
                provider=DeterministicEmbeddingProvider(),
                k=2,
                filters=RetrievalFilters(languages=("en", "ko")),
            )
        )


def test_routing_skips_lexical_when_query_and_corpus_languages_differ(monkeypatch):
    """Routing on a Korean corpus skips the lexical lane for an English query."""
    lexical_calls = []
    session = cast(AsyncSession, object())

    async def vector(received_session, query_vector, *, k, filters):
        return [hit(1, 0.9)]

    async def lexical(received_session, query, k, filters, *, text_search_config):
        lexical_calls.append(query)
        return [hit(2, 5.0)]

    monkeypatch.setattr(service, "vector_search", vector)
    monkeypatch.setattr(service, "lexical_search", lexical)

    result = asyncio.run(
        service.retrieve(
            session,
            "semiconductor revenue outlook",
            provider=DeterministicEmbeddingProvider(),
            k=2,
            filters=RetrievalFilters(languages=("ko",)),
            route_by_language=True,
        )
    )

    assert lexical_calls == []
    assert result.component_rankings.lexical == ()
