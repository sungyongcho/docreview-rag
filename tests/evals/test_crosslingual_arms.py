"""Cross-lingual arm model: names, provenance, shape checks, and one-arm measurement."""

import asyncio
import json
from types import SimpleNamespace
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
import app.evals.arms as arms
import app.evals.crosslingual_arms as crosslingual_arms
from app.evals.crosslingual_arms import (
    CROSSLINGUAL_SUITE,
    CROSSLINGUAL_TARGET_TOKENS,
    ProviderChoice,
    TranslationLog,
    category_breakdown,
    embedding_identity,
    make_crosslingual_retriever,
)
from app.evals.identity import artifact_filename
from app.evals.types import EvaluationRetrieval
from app.llm.provider import LLMProvider
from app.llm.schemas import ProviderBudget
from app.retrieval.embeddings import DeterministicEmbeddingProvider
from app.retrieval.sbert import MULTILINGUAL_SBERT_MODEL
from app.retrieval.types import RetrievalFilters
from tests.evals.crosslingual_support import BM25_FIELDS, arm, evaluate_arm, hit, scripted
from tests.evals.support import EVALUATION_RECORDED_AT


def test_arm_names_encode_provider_strategy_ranker_handling_and_language():
    """Encode every measured axis in a filename-safe arm name."""
    assert arm().name == "xling-deterministic-hybrid-ts-rank-cd-en"
    assert arm(language="ko").name == "xling-deterministic-hybrid-ts-rank-cd-ko"
    assert (
        arm(embedding_provider="sbert-multi", handling="routed", language="ko").name
        == "xling-sbert-multi-hybrid-ts-rank-cd-routed-ko"
    )
    assert arm(strategy="vector", lexical_ranker=None).name == "xling-deterministic-vector-en"
    assert arm(lexical_ranker="bm25", **BM25_FIELDS).name == "xling-deterministic-hybrid-bm25-en"
    assert arm(language="ko").sort_key > arm().sort_key


def test_a_bm25_arm_carries_the_parameters_its_queries_actually_run_under():
    """Record BM25 provenance on a BM25 arm and refuse an arm that names it bare."""
    measured = arm(lexical_ranker="bm25", **BM25_FIELDS)

    assert measured.to_config()["retrieval"]["bm25"] == {"k1": 1.2, "b": 0.75, "idf": "lucene"}
    # A ts_rank_cd arm runs no BM25 query, so its config must not claim parameters.
    assert "bm25" not in arm().to_config()["retrieval"]

    with pytest.raises(ValueError, match="require explicit k1"):
        arm(lexical_ranker="bm25")
    with pytest.raises(ValueError, match="only for bm25 arms"):
        arm(**BM25_FIELDS)


def test_arm_config_carries_everything_a_baseline_must_separate_on():
    """Record every axis needed to keep regression baselines comparable."""
    config = arm(embedding_provider="sbert-multi", embedding_model=MULTILINGUAL_SBERT_MODEL)
    payload = config.to_config()

    assert payload["embedding"] == {
        "provider": "sbert-multi",
        "model": MULTILINGUAL_SBERT_MODEL,
        "dimensions": 384,
    }
    assert payload["query"] == {"language": "en", "handling": "direct", "translator": None}
    # The English-trained cross-encoder stays off in every arm, and the artifact says so.
    assert payload["retrieval"]["reranker"] is None
    assert payload["chunking"]["target_tokens"] == CROSSLINGUAL_TARGET_TOKENS
    assert payload["measurement"]["populated_corpus_embeddings_modified"] is False
    assert payload["measurement"]["paid_api_calls"] is False
    assert json.loads(json.dumps(payload)) == payload

    translated = arm(
        handling="translated",
        translator_model="gpt-4.1-mini",
    ).to_config()
    assert translated["query"]["translator"] == {"provider": "openai", "model": "gpt-4.1-mini"}
    assert translated["measurement"]["paid_api_calls"] is True


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"strategy": "vector"}, "must not name a lexical ranker"),
        ({"lexical_ranker": None}, "requires an explicit lexical ranker"),
        ({"strategy": "vector", "lexical_ranker": None, "handling": "routed"}, "hybrid"),
        ({"handling": "translated"}, "translator model"),
        ({"translator_model": "gpt-4.1-mini"}, "translator model"),
        ({"embedding_provider": "cohere"}, "unsupported embedding provider"),
        ({"strategy": "graph"}, "unsupported retrieval strategy"),
        ({"language": "fr"}, "unsupported query language"),
        ({"handling": "guessed"}, "unsupported query handling"),
        ({"candidate_k": 2}, "inconsistent"),
        ({"embedding_model": "  "}, "nonblank"),
    ],
)
def test_arm_rejects_shapes_whose_numbers_could_not_be_attributed(changes, message):
    """Reject arm configurations whose measurements would be mislabeled."""
    with pytest.raises(ValueError, match=message):
        arm(**changes)


def test_embedding_identity_maps_sbert_multi_without_a_new_provider_literal():
    """Map the multilingual model through the existing SBERT provider."""
    settings = cast(
        Settings,
        SimpleNamespace(
            embedding_model="text-embedding-3-large",
            sbert_model="sentence-transformers/all-MiniLM-L6-v2",
        ),
    )

    assert embedding_identity("deterministic", settings)[0] == "deterministic"
    assert embedding_identity("openai", settings) == ("openai", "text-embedding-3-large")
    assert embedding_identity("sbert", settings) == (
        "sbert",
        "sentence-transformers/all-MiniLM-L6-v2",
    )
    assert embedding_identity("sbert-multi", settings) == ("sbert", MULTILINGUAL_SBERT_MODEL)
    with pytest.raises(ValueError, match="unsupported"):
        embedding_identity(cast(ProviderChoice, "cohere"), settings)


def test_run_arm_slices_by_category_and_writes_a_schema_v1_artifact(monkeypatch, tmp_path):
    """Slice one arm by category and write its versioned raw artifact."""
    scripted(monkeypatch, {"en": [hit(1, start=100)], "ko": []})

    english = evaluate_arm(arm(), tmp_path)
    korean = evaluate_arm(arm(language="ko"), tmp_path)

    assert english.evaluation.suite == CROSSLINGUAL_SUITE
    assert english.evaluation.score.recall_at_k == pytest.approx(1.0)
    assert korean.evaluation.score.recall_at_k == pytest.approx(0.0)
    assert {group.group for group in english.categories} == {"simple_lookup", "multi_hop"}
    assert english.categories == category_breakdown(english.evaluation)

    assert english.artifact_path is not None
    assert english.artifact_path.name == artifact_filename(EVALUATION_RECORDED_AT, arm().name)
    payload = json.loads(english.artifact_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["config"]["query"]["language"] == "en"
    assert payload["config"]["retrieval"]["reranker"] is None


def test_handling_selects_the_query_path_through_one_shared_retriever(monkeypatch):
    """Route only for routed handling, and forward BM25 provenance either way."""
    calls = []

    async def fake_retrieve(session, query, **kwargs):
        """Record routing and BM25 options while returning one hit."""
        calls.append((kwargs["route_by_language"], kwargs["lexical_ranker"], kwargs["bm25_k1"]))
        return SimpleNamespace(hits=(hit(1, start=100),))

    monkeypatch.setattr(arms, "retrieve", fake_retrieve)
    for handling in ("routed", "direct"):
        retriever = make_crosslingual_retriever(
            cast(AsyncSession, SimpleNamespace()),
            arm(handling=handling, language="ko", lexical_ranker="bm25", **BM25_FIELDS),
            provider=DeterministicEmbeddingProvider(),
        )
        hits = asyncio.run(retriever("AMD의 매출은?", 5))
        assert [candidate.chunk_id for candidate in hits.hits] == [1]

    # A direct arm never routes, whatever the environment says: it is the "before"
    # measurement the routed arm is compared against.
    assert calls == [(True, "bm25", 1.2), (False, "bm25", 1.2)]


def test_translated_handling_rewrites_the_query_and_records_what_it_sent(monkeypatch):
    """Translate before retrieval and record the exact query that was sent."""
    seen = []
    scripted(monkeypatch, {"en": [hit(1, start=100)], "ko": []})

    def factory(session, **kwargs):
        """Build a retriever that records the translated query."""

        async def retriever(query: str, k: int):
            """Record the query and return one relevant hit."""
            seen.append(query)
            return EvaluationRetrieval(hits=(hit(1, start=100),))

        return retriever

    monkeypatch.setattr(crosslingual_arms, "make_retriever", factory)

    async def fake_translate(query, *, llm_provider, provider_budget, target_language="en"):
        """Return a fixed validated English translation."""
        return SimpleNamespace(translated_query="AMD revenue?", source_language="ko")

    monkeypatch.setattr(crosslingual_arms, "translate_query", fake_translate)
    log = TranslationLog()
    retriever = make_crosslingual_retriever(
        cast(AsyncSession, SimpleNamespace()),
        arm(handling="translated", language="ko", translator_model="gpt-4.1-mini"),
        provider=None,
        llm_provider=cast(LLMProvider, object()),
        provider_budget=cast(ProviderBudget, object()),
        translation_log=log,
    )

    asyncio.run(retriever("AMD의 매출은?", 5))

    assert seen == ["AMD revenue?"]
    # The arm label is what lets one command's log be split back into the slices whose
    # numbers it explains; several translated arms share one log.
    assert log.payload() == [
        {
            "arm": "xling-deterministic-hybrid-ts-rank-cd-translated-ko",
            "original": "AMD의 매출은?",
            "translated": "AMD revenue?",
            "source_language": "ko",
        }
    ]
    with pytest.raises(ValueError, match="LLM provider"):
        make_crosslingual_retriever(
            cast(AsyncSession, SimpleNamespace()),
            arm(handling="translated", language="ko", translator_model="gpt-4.1-mini"),
            provider=None,
        )


def test_dart_corpus_arm_names_and_config_carry_the_corpus_identity():
    """A DART arm cannot share a name or a baseline with its EDGAR twin."""
    edgar = arm(strategy="hybrid", lexical_ranker="ts_rank_cd", language="ko")
    dart = arm(
        strategy="hybrid",
        lexical_ranker="ts_rank_cd",
        language="ko",
        corpus_registry="dart",
    )

    assert edgar.name == "xling-deterministic-hybrid-ts-rank-cd-ko"
    assert dart.name == "xling-dart-deterministic-hybrid-ts-rank-cd-ko"
    assert edgar.to_config()["corpus"] == {"registry": "sec", "language": "en"}
    assert dart.to_config()["corpus"] == {"registry": "dart", "language": "ko"}


def test_every_arm_pins_its_corpus_language_filter(monkeypatch):
    """The bound retriever always carries the arm's corpus language filter."""
    seen = {}

    def factory(_session, **kwargs):
        """Capture the bound corpus filter and return an empty retriever."""
        seen.update(kwargs)

        async def run(_query, _k):
            """Return no hits for the filter-binding assertion."""
            return EvaluationRetrieval(hits=())

        return run

    monkeypatch.setattr(crosslingual_arms, "make_retriever", factory)
    session = cast(AsyncSession, object())
    crosslingual_arms.make_crosslingual_retriever(session, arm(), provider=None)
    assert seen["filters"] == RetrievalFilters(languages=("en",))

    crosslingual_arms.make_crosslingual_retriever(
        session, arm(corpus_registry="dart"), provider=None
    )
    assert seen["filters"] == RetrievalFilters(languages=("ko",))
