"""Retrieval service composition tests."""

import asyncio
import math
from typing import cast

from pydantic import ValidationError
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.retrieval import service
from app.retrieval.embeddings import DeterministicEmbeddingProvider
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
    filters = RetrievalFilters(doc_ids=("NVDA-FY2024",), languages=("en",))

    class Provider(DeterministicEmbeddingProvider):
        """Test double for Provider behavior."""

        async def embed_query(self, query):
            """Exercise embed query behavior."""
            events.append(("embed", query))
            return [0.0] * self.dimensions

    async def vector(received_session, query_vector, *, k, filters, identity=None):
        """Exercise vector behavior."""
        events.append(("vector", received_session, len(query_vector), k, filters))
        return [hit(1, 0.99), hit(2, 0.01)]

    async def lexical(received_session, query, k, filters, *, text_search_config):
        """Exercise lexical behavior."""
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
        "vector_by_language": {},
        "lexical": (2, 3),
        "lexical_by_language": {"en": (2, 3)},
    }

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

    async def vector(_session, _query_vector, *, k, filters, identity=None):
        """Exercise vector behavior."""
        assert k == 2
        return [hit(1, 0.9), hit(2, 0.8)]

    async def lexical(_session, query, k, filters, *, text_search_config):
        """Exercise lexical behavior."""
        assert query == "NVDA research development spending"
        assert k == 2
        return []

    class Reranker(RerankProvider):
        """Test double for Reranker behavior."""

        async def score(self, query, documents):
            """Exercise score behavior."""
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
            filters=RetrievalFilters(languages=("en",)),
            reranker=Reranker(),
        )
    )

    assert rerank_calls == [("NVDA R&D spending", 2)]
    assert [candidate.chunk_id for candidate in result.hits] == [2]
    assert result.score_stage == "reranker"


@pytest.mark.parametrize(
    "changes, message",
    [
        pytest.param({"query": " "}, "blank", id="blank-query"),
        pytest.param({"k": 0}, "positive", id="non-positive-limit"),
        pytest.param({"k": 3, "candidate_k": 2}, "at least k", id="candidate-pool-below-limit"),
        pytest.param({"rrf_k": 0}, "positive", id="non-positive-rrf-k"),
        pytest.param({"bm25_k1": math.nan}, "finite positive", id="non-finite-bm25-k1"),
        pytest.param({"bm25_b": math.nan}, "finite number", id="non-finite-bm25-b"),
    ],
)
def test_service_rejects_invalid_requests_before_provider_or_search(monkeypatch, changes, message):
    """Validate service-owned inputs before building a provider or searching."""

    def build_provider():
        """Exercise build provider behavior."""
        raise AssertionError("invalid input must not build the provider")

    async def search(*_args, **_kwargs):
        """Reject any attempt to reach a real retrieval component."""
        raise AssertionError("invalid input must not reach a retrieval component")

    monkeypatch.setattr(service, "get_embedding_provider", build_provider)
    monkeypatch.setattr(service, "vector_search", search)
    monkeypatch.setattr(service, "lexical_search", search)
    arguments = {"query": "query", "k": 2} | changes

    with pytest.raises(ValueError, match=message):
        asyncio.run(service.retrieve(cast(AsyncSession, object()), **arguments))


def test_service_forwards_default_provider_width_and_identity(monkeypatch):
    """Forward the provider's actual vector width and identity to the search boundary."""
    provider = DeterministicEmbeddingProvider(dimensions=32)
    calls = []

    def build_provider():
        """Return a configured alternate-width provider without database access."""
        calls.append("provider")
        return provider

    async def search(_session, query_vector, *, identity, **_kwargs):
        """Verify forwarding with an injected unit-test search implementation."""
        calls.append("vector")
        assert len(query_vector) == 32
        assert identity == provider.identity
        assert identity.dimensions == 32
        return []

    monkeypatch.setattr(service, "get_embedding_provider", build_provider)
    monkeypatch.setattr(service, "vector_search", search)
    result = asyncio.run(service.retrieve(cast(AsyncSession, object()), "query", strategy="vector"))
    assert not result.hits
    assert calls == ["provider", "vector"]


def test_routing_skips_the_lexical_component_only_for_korean_queries(monkeypatch):
    """Skip the English lexical component for a Korean query and keep it for English."""
    events = []

    class Provider(DeterministicEmbeddingProvider):
        """Test double for Provider behavior."""

        async def embed_query(self, query):
            """Exercise embed query behavior."""
            events.append(("embed", query))
            return [0.0] * self.dimensions

    async def vector(received_session, query_vector, *, k, filters, identity=None):
        """Exercise vector behavior."""
        events.append(("vector", k))
        return [hit(1, 0.99)]

    async def lexical(received_session, query, k, filters, *, text_search_config):
        """Exercise lexical behavior."""
        events.append(("lexical", query))
        return [hit(2, 9_000.0)]

    monkeypatch.setattr(service, "vector_search", vector)
    monkeypatch.setattr(service, "lexical_search", lexical)

    korean = asyncio.run(
        service.retrieve(
            cast(AsyncSession, object()),
            "매출총이익률은 어떻게 변화했습니까?",
            provider=Provider(),
            k=2,
            filters=RetrievalFilters(languages=("en",)),
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
        """Test double for Provider behavior."""

        async def embed_query(self, query):
            """Exercise embed query behavior."""
            return [0.0] * self.dimensions

    async def vector(received_session, query_vector, *, k, filters, identity=None):
        """Exercise vector behavior."""
        return [hit(1, 0.99)]

    async def lexical(received_session, query, k, filters, *, text_search_config):
        """Exercise lexical behavior."""
        events.append(query)
        return [hit(2, 9_000.0)]

    monkeypatch.setattr(service, "vector_search", vector)
    monkeypatch.setattr(service, "lexical_search", lexical)

    session = cast(AsyncSession, object())
    result = asyncio.run(
        service.retrieve(
            session,
            "AMD의 매출은?",
            provider=Provider(),
            k=2,
            filters=RetrievalFilters(languages=("en",)),
        )
    )

    # The service holds no opinion of its own: it never reads Settings, so an arm
    # measured here cannot inherit a query path its recorded config does not name.
    assert events == ["AMD의 매출은?"]
    assert result.component_rankings.lexical == (2,)
    assert "get_settings" not in vars(service)


def test_korean_corpus_filter_tokenizes_the_lexical_query(monkeypatch):
    """A ko corpus filter sends n-gram tokens under the simple configuration."""
    calls = []
    session = cast(AsyncSession, object())

    async def vector(received_session, query_vector, *, k, filters, identity=None):
        """Exercise vector behavior."""
        return [hit(1, 0.9)]

    async def lexical(received_session, query, k, filters, *, text_search_config):
        """Exercise lexical behavior."""
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


def test_mixed_language_filter_fans_out_lexical_retrieval(monkeypatch):
    """Run one tokenizer-matched lexical statement per corpus language."""
    calls = []
    session = cast(AsyncSession, object())

    async def vector(received_session, query_vector, *, k, filters, identity=None):
        """Exercise vector behavior."""
        return [hit(1, 0.9)]

    async def lexical(received_session, query, k, filters, *, text_search_config):
        """Exercise lexical behavior."""
        calls.append((filters.languages, text_search_config))
        return [hit(2 if filters.languages == ("en",) else 3, 5.0)]

    monkeypatch.setattr(service, "vector_search", vector)
    monkeypatch.setattr(service, "lexical_search", lexical)

    result = asyncio.run(
        service.retrieve(
            session,
            "memory 매출",
            provider=DeterministicEmbeddingProvider(),
            k=3,
            filters=RetrievalFilters(languages=("en", "ko")),
        )
    )

    assert calls == [(("en",), "english"), (("ko",), "simple")]
    assert set(result.component_rankings.lexical_by_language) == {"en", "ko"}


def test_routing_skips_lexical_when_query_and_corpus_languages_differ(monkeypatch):
    """Routing on a Korean corpus skips the lexical lane for an English query."""
    lexical_calls = []
    session = cast(AsyncSession, object())

    async def vector(received_session, query_vector, *, k, filters, identity=None):
        """Exercise vector behavior."""
        return [hit(1, 0.9)]

    async def lexical(received_session, query, k, filters, *, text_search_config):
        """Exercise lexical behavior."""
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


def test_translated_variant_keeps_the_target_lexical_lane(monkeypatch):
    """Use a supplied English translation even when the raw query contains only Hangul."""
    lexical_calls = []

    async def vector(session, query_vector, *, k, filters, identity=None):
        """Return an independent vector candidate for the hybrid composition."""
        return [hit(1, 0.9)]

    async def lexical(session, query, k, filters, *, text_search_config):
        """Record the translated query and the corpus tokenizer that receive it."""
        lexical_calls.append((query, filters.languages, text_search_config))
        return [hit(2, 5.0)]

    monkeypatch.setattr(service, "vector_search", vector)
    monkeypatch.setattr(service, "lexical_search", lexical)
    result = asyncio.run(
        service.retrieve(
            cast(AsyncSession, object()),
            "매출 증가 요인",
            provider=DeterministicEmbeddingProvider(),
            filters=RetrievalFilters(languages=("en",)),
            query_variants={"en": "revenue growth drivers"},
            route_by_language=True,
        )
    )

    assert lexical_calls == [("revenue growth drivers", ("en",), "english")]
    assert result.component_rankings.lexical_by_language == {"en": (2,)}


def test_unrestricted_filter_with_a_routed_variant_reaches_every_corpus(monkeypatch):
    """An empty language filter fans both lanes out over every corpus language."""
    embedded = []
    vector_calls = []
    lexical_calls = []

    class Provider(DeterministicEmbeddingProvider):
        """Record the query text each vector lane embeds."""

        async def embed_query(self, query):
            """Exercise embed query behavior."""
            embedded.append(query)
            return [0.0] * self.dimensions

    async def vector(session, query_vector, *, k, filters, identity=None):
        """Record the language restriction of every vector lane."""
        vector_calls.append(filters.languages)
        return [hit(1 if filters.languages == ("en",) else 3, 0.9)]

    async def lexical(session, query, k, filters, *, text_search_config):
        """Record the language and configuration of every lexical lane."""
        lexical_calls.append((filters.languages, text_search_config))
        return [hit(2 if filters.languages == ("en",) else 4, 5.0)]

    monkeypatch.setattr(service, "vector_search", vector)
    monkeypatch.setattr(service, "lexical_search", lexical)
    result = asyncio.run(
        service.retrieve(
            cast(AsyncSession, object()),
            "compare all companies 매출 growth",
            provider=Provider(),
            k=4,
            filters=RetrievalFilters(),
            query_variants={"en": "compare all companies revenue growth"},
            route_by_language=True,
        )
    )

    # One vector lane per corpus language, each embedded with the query in its language.
    assert vector_calls == [("en",), ("ko",)]
    assert embedded == ["compare all companies revenue growth", "compare all companies 매출 growth"]
    assert lexical_calls == [(("en",), "english"), (("ko",), "simple")]
    assert result.component_rankings.vector_by_language == {"en": (1,), "ko": (3,)}
    assert result.component_rankings.lexical_by_language == {"en": (2,), "ko": (4,)}
    assert {candidate.chunk_id for candidate in result.hits} == {1, 2, 3, 4}


def test_unrestricted_filter_without_a_variant_keeps_one_vector_lane(monkeypatch):
    """Without a translation the vector lane stays unrestricted; lexical lanes still fan out."""
    vector_calls = []
    lexical_calls = []

    async def vector(session, query_vector, *, k, filters, identity=None):
        """Record the language restriction of every vector lane."""
        vector_calls.append(filters.languages)
        return [hit(1, 0.9)]

    async def lexical(session, query, k, filters, *, text_search_config):
        """Record the query each lexical lane parses."""
        lexical_calls.append((filters.languages, query))
        return [hit(2 if filters.languages == ("en",) else 3, 5.0)]

    monkeypatch.setattr(service, "vector_search", vector)
    monkeypatch.setattr(service, "lexical_search", lexical)
    result = asyncio.run(
        service.retrieve(
            cast(AsyncSession, object()),
            "삼성전자 memory",
            provider=DeterministicEmbeddingProvider(),
            k=3,
            filters=None,
        )
    )

    assert vector_calls == [()]
    assert lexical_calls == [(("en",), "삼성전자 memory"), (("ko",), "삼성 성전 전자 memory")]
    assert result.component_rankings.vector_by_language == {}
    assert result.component_rankings.lexical_by_language == {"en": (2,), "ko": (3,)}


def test_package_reexports_each_public_name_from_its_defining_module():
    """The retrieval package is the one sanctioned re-export façade (AGENTS.md): every name it
    publishes must be the very object its defining retrieval module exports."""
    import importlib

    import app.retrieval as public

    assert public.__all__
    for name in public.__all__:
        exported = getattr(public, name)
        assert exported.__module__.startswith("app.retrieval."), name
        defining = importlib.import_module(exported.__module__)
        assert getattr(defining, name) is exported, name
