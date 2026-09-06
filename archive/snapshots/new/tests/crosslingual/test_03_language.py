"""M8.3: Hangul-scan query-language detection and the routed lexical skip."""

import asyncio
import importlib
import inspect
import os

import pytest

from app.retrieval.embeddings import DeterministicEmbeddingProvider
from app.retrieval.types import ChunkHit, RetrievalFilters
from tests.retrieval.test_01_contract import hit_values
from tests.support import need

SERVICE_MODULE_NAME = os.getenv("RETRIEVAL_SERVICE_MODULE", "app.retrieval.service")
S = importlib.import_module(SERVICE_MODULE_NAME)


def hit(chunk_id: int, score: float) -> ChunkHit:
    """Build one valid candidate with a unique source span."""
    start = chunk_id * 100
    return ChunkHit(
        **hit_values(chunk_id=chunk_id, score=score, start_char=start, end_char=start + 50)
    )


@pytest.mark.parametrize(
    "query, language",
    [
        ("AMD의 매출총이익률은 어떻게 변화했습니까?", "ko"),
        ("2019 회계연도", "ko"),
        ("AMD의 매출", "ko"),
        ("ㄱ", "ko"),
        ("가", "ko"),
        ("ㅣ hello", "ko"),
        ("How did AMD's gross margin change?", "en"),
        ("TSMC 7nm 2021 10-K", "en"),
        ("R&D $1,234.5", "en"),
    ],
)
def test_detect_query_language_classifies_on_hangul_presence(LANG, query, language):
    need(LANG, "detect_query_language")
    assert LANG.detect_query_language(query) == language


def test_detect_query_language_scans_the_declared_unicode_boundaries(LANG):
    need(LANG, "contains_hangul", "detect_query_language")

    for start, end in LANG.HANGUL_RANGES:
        assert LANG.contains_hangul(chr(start))
        assert LANG.contains_hangul(chr(end))
        assert LANG.detect_query_language(f"AMD {chr(start)}") == "ko"

    # The characters immediately outside each range must stay English, or the
    # detector would route CJK punctuation and Latin text onto the Korean path.
    assert not LANG.contains_hangul(chr(0xAC00 - 1))
    assert not LANG.contains_hangul(chr(0xD7A3 + 1))
    assert not LANG.contains_hangul("AMD gross margin 2019")


@pytest.mark.parametrize("query", ["", "   ", "\n\t"])
def test_detect_query_language_rejects_blank_input(LANG, query):
    need(LANG, "detect_query_language")
    with pytest.raises(ValueError, match="blank"):
        LANG.detect_query_language(query)


def test_routing_skips_the_lexical_component_only_for_korean_queries(monkeypatch):
    need(S, "retrieve")
    if "route_by_language" not in inspect.signature(S.retrieve).parameters:
        pytest.skip("not implemented yet: retrieve(route_by_language=...)")
    events = []

    class Provider(DeterministicEmbeddingProvider):
        async def embed_query(self, query):
            events.append(("embed", query))
            return [0.0] * self.dimensions

    async def vector(received_session, query_vector, *, k, filters):
        events.append(("vector", k))
        return [hit(1, 0.99)]

    async def lexical(received_session, query, k, filters):
        events.append(("lexical", query))
        return [hit(2, 9_000.0)]

    monkeypatch.setattr(S, "vector_search", vector)
    monkeypatch.setattr(S, "lexical_search", lexical)

    korean = asyncio.run(
        S.retrieve(
            object(),
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
        S.retrieve(
            object(),
            "How did AMD's gross margin change?",
            provider=Provider(),
            k=2,
            route_by_language=True,
        )
    )

    assert [event[0] for event in events] == ["embed", "vector", "lexical"]
    assert english.component_rankings.lexical == (2,)


def test_routing_is_off_unless_the_caller_or_settings_turn_it_on(monkeypatch):
    need(S, "retrieve")
    if "route_by_language" not in inspect.signature(S.retrieve).parameters:
        pytest.skip("not implemented yet: retrieve(route_by_language=...)")
    events = []

    class Provider(DeterministicEmbeddingProvider):
        async def embed_query(self, query):
            return [0.0] * self.dimensions

    async def vector(received_session, query_vector, *, k, filters):
        return [hit(1, 0.99)]

    async def lexical(received_session, query, k, filters):
        events.append(query)
        return [hit(2, 9_000.0)]

    monkeypatch.setattr(S, "vector_search", vector)
    monkeypatch.setattr(S, "lexical_search", lexical)

    result = asyncio.run(S.retrieve(object(), "AMD의 매출은?", provider=Provider(), k=2))

    assert events == ["AMD의 매출은?"]
    assert result.component_rankings.lexical == (2,)
