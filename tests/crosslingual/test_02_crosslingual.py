"""M8.2: cross-lingual arms, query-path diagnostics, rendering, and the command."""

import asyncio
from datetime import UTC, datetime
import json
from types import SimpleNamespace

import pytest

from app.evals.types import GoldenCase, GoldenCategory, GoldenSpan
from app.retrieval.embeddings import DeterministicEmbeddingProvider
from app.retrieval.sbert import MULTILINGUAL_SBERT_MODEL
from app.retrieval.types import ChunkHit
from tests.retrieval.test_01_contract import hit_values
from tests.support import need

SOURCE_SHA256 = "a" * 64
RECORDED_AT = datetime(2026, 1, 1, tzinfo=UTC)
QUESTIONS = {
    "m3c-01": ("How did AMD's gross margin change?", "AMD의 매출총이익률은 어떻게 변화했습니까?"),
    "m3c-02": (
        "What did Intel disclose about capacity?",
        "인텔은 생산 능력에 대해 무엇을 공시했습니까?",
    ),
    "m3c-03": ("Which risk did the filing name?", "공시는 어떤 위험을 언급했습니까?"),
}


def golden(
    case_id: str, language: str, *, category: GoldenCategory = "simple_lookup"
) -> GoldenCase:
    """Build one twin case in the requested language."""
    question = QUESTIONS[case_id][0 if language == "en" else 1]
    return GoldenCase(
        id=case_id,
        question=question,
        category=category,
        facet="factual",
        tags=(),
        answers=(
            GoldenSpan(
                doc_id="AMD-FY2019",
                source_sha256=SOURCE_SHA256,
                start_char=100,
                end_char=200,
            ),
        ),
        expected_label="SUPPORTED",
        reference_answer="Supported evidence.",
        note="Cross-lingual fixture.",
        curation_status="agent-curated",
        approval_status="pending-author-approval",
        human_verified=False,
    )


def suite(
    BI,
    categories: tuple[GoldenCategory, ...] = ("simple_lookup", "simple_lookup", "multi_hop"),
):
    """Build one synthetic twin suite over three shared answer spans."""
    ids = sorted(QUESTIONS)
    return BI.BilingualSuite(
        en=tuple(
            golden(case_id, "en", category=category)
            for case_id, category in zip(ids, categories, strict=True)
        ),
        ko=tuple(
            golden(case_id, "ko", category=category)
            for case_id, category in zip(ids, categories, strict=True)
        ),
    )


def hit(chunk_id: int, *, start: int, score: float = 0.5) -> ChunkHit:
    """Build one candidate whose span may or may not overlap the golden one."""
    return ChunkHit(
        **hit_values(
            chunk_id=chunk_id,
            doc_id="AMD-FY2019",
            score=score,
            start_char=start,
            end_char=start + 100,
        )
    )


def arm(XL, **changes):
    """Build one hybrid deterministic arm with optional field replacements."""
    values = {
        "embedding_provider": "deterministic",
        "embedding_model": "token-hash-384",
        "strategy": "hybrid",
        "language": "en",
        "lexical_ranker": "ts_rank_cd",
    }
    values.update(changes)
    return XL.CrosslingualArm(**values)


def test_arm_names_encode_provider_strategy_ranker_handling_and_language(XL):
    need(XL, "CrosslingualArm")
    assert arm(XL).name == "xling-deterministic-hybrid-ts-rank-cd-en"
    assert arm(XL, language="ko").name == "xling-deterministic-hybrid-ts-rank-cd-ko"
    assert (
        arm(XL, embedding_provider="sbert-multi", handling="routed", language="ko").name
        == "xling-sbert-multi-hybrid-ts-rank-cd-routed-ko"
    )
    assert arm(XL, strategy="vector", lexical_ranker=None).name == "xling-deterministic-vector-en"
    assert arm(XL, lexical_ranker="bm25").name == "xling-deterministic-hybrid-bm25-en"
    assert arm(XL, language="ko").sort_key > arm(XL).sort_key


def test_arm_config_carries_everything_a_baseline_must_separate_on(XL):
    need(XL, "CrosslingualArm", "CROSSLINGUAL_TARGET_TEXT_CHARS")
    config = arm(XL, embedding_provider="sbert-multi", embedding_model=MULTILINGUAL_SBERT_MODEL)
    payload = config.to_config()

    assert payload["embedding"] == {
        "provider": "sbert-multi",
        "model": MULTILINGUAL_SBERT_MODEL,
        "dimensions": 384,
    }
    assert payload["query"] == {"language": "en", "handling": "direct", "translator": None}
    # The English-trained cross-encoder stays off in every arm, and the artifact says so.
    assert payload["retrieval"]["reranker"] is None
    assert payload["chunking"]["target_text_chars"] == XL.CROSSLINGUAL_TARGET_TEXT_CHARS
    assert payload["measurement"]["populated_corpus_embeddings_modified"] is False
    assert payload["measurement"]["paid_api_calls"] is False
    assert json.loads(json.dumps(payload)) == payload

    translated = arm(
        XL,
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
        ({"language": "fr"}, "unsupported query language"),
        ({"handling": "guessed"}, "unsupported query handling"),
        ({"candidate_k": 2}, "inconsistent"),
        ({"embedding_model": "  "}, "nonblank"),
    ],
)
def test_arm_rejects_shapes_whose_numbers_could_not_be_attributed(XL, changes, message):
    need(XL, "CrosslingualArm")
    with pytest.raises(ValueError, match=message):
        arm(XL, **changes)


def test_paired_with_returns_the_same_arm_in_the_other_language(XL):
    need(XL, "CrosslingualArm")
    english = arm(XL, handling="routed")
    korean = english.paired_with("ko")

    assert korean.language == "ko"
    assert korean.to_config()["retrieval"] == english.to_config()["retrieval"]
    assert korean.to_config()["embedding"] == english.to_config()["embedding"]


def test_embedding_identity_maps_sbert_multi_without_a_new_provider_literal(XL):
    need(XL, "embedding_identity")
    settings = SimpleNamespace(
        embedding_model="text-embedding-3-small",
        sbert_model="sentence-transformers/all-MiniLM-L6-v2",
    )

    assert XL.embedding_identity("deterministic", settings)[0] == "deterministic"
    assert XL.embedding_identity("openai", settings) == ("openai", "text-embedding-3-small")
    assert XL.embedding_identity("sbert", settings) == (
        "sbert",
        "sentence-transformers/all-MiniLM-L6-v2",
    )
    assert XL.embedding_identity("sbert-multi", settings) == ("sbert", MULTILINGUAL_SBERT_MODEL)
    with pytest.raises(ValueError, match="unsupported"):
        XL.embedding_identity("cohere", settings)


def test_twin_alignment_measures_the_embedding_space_without_a_corpus(XL, BI):
    need(XL, "twin_query_alignment")
    need(BI, "BilingualSuite")
    provider = DeterministicEmbeddingProvider()

    alignment = asyncio.run(
        XL.twin_query_alignment(provider, suite(BI), provider_name="deterministic")
    )

    assert alignment.provider == "deterministic"
    assert alignment.pair_count == 3
    assert {pair.case_id for pair in alignment.pairs} == set(QUESTIONS)
    assert -1.0 <= alignment.min_cosine <= alignment.mean_cosine <= alignment.max_cosine <= 1.0
    # A token-hashing space shares almost nothing across the twins, but 384 hashed
    # dimensions do collide, so the cosine is near zero rather than exactly zero.
    assert alignment.mean_cosine < 0.5

    identical = BI.BilingualSuite(
        en=(golden("m3c-01", "en"),),
        ko=(golden("m3c-01", "en"),),
    )
    same = asyncio.run(XL.twin_query_alignment(provider, identical))
    assert same.mean_cosine == pytest.approx(1.0)
    assert same.provider == "unknown"


def test_lexical_coverage_counts_the_collapse_instead_of_assuming_it(XL, BI):
    need(XL, "lexical_candidate_coverage")
    need(BI, "BilingualSuite")
    cases = suite(BI).ko

    async def latin_only(query: str, k: int):
        # Korean questions still carry Latin tokens, and the English tsquery can match
        # them, so the collapse is partial. The number says how partial.
        return [hit(1, start=100)] if "AMD" in query else []

    coverage = asyncio.run(
        XL.lexical_candidate_coverage(latin_only, cases, language="ko", candidate_k=20)
    )

    assert coverage.language == "ko"
    assert coverage.case_count == 3
    assert coverage.zero_candidate_cases == 2
    assert 0.0 < coverage.zero_candidate_rate < 1.0
    assert coverage.zero_candidate_case_ids == ("m3c-02", "m3c-03")
    assert coverage.mean_candidate_count == pytest.approx(1 / 3)

    with pytest.raises(ValueError, match="at least one case"):
        asyncio.run(XL.lexical_candidate_coverage(latin_only, (), language="ko"))


def run(XL, BI, module_arm, hits, tmp_path=None):
    """Evaluate one arm against a scripted retriever, bypassing the database."""
    return asyncio.run(
        XL.run_arm(
            SimpleNamespace(),
            module_arm,
            suite(BI),
            provider=None,
            artifact_dir=tmp_path,
            recorded_at=RECORDED_AT,
        )
    )


def scripted(XL, monkeypatch, per_language):
    """Replace ``make_retriever`` with a scripted, database-free retriever."""

    def factory(session, **kwargs):
        async def retriever(query: str, k: int):
            language = (
                "ko" if any(question == query for _, question in QUESTIONS.values()) else "en"
            )
            return per_language[language]

        return retriever

    monkeypatch.setattr(XL, "make_retriever", factory)


def test_run_arm_slices_by_category_and_writes_a_schema_v1_artifact(XL, BI, monkeypatch, tmp_path):
    need(XL, "run_arm", "category_breakdown", "artifact_filename")
    need(BI, "BilingualSuite")
    scripted(XL, monkeypatch, {"en": [hit(1, start=100)], "ko": []})

    english = run(XL, BI, arm(XL), None, tmp_path)
    korean = run(XL, BI, arm(XL, language="ko"), None, tmp_path)

    assert english.evaluation.suite == XL.CROSSLINGUAL_SUITE
    assert english.evaluation.score.recall_at_k == pytest.approx(1.0)
    assert korean.evaluation.score.recall_at_k == pytest.approx(0.0)
    assert {group.group for group in english.categories} == {"simple_lookup", "multi_hop"}
    assert english.categories == XL.category_breakdown(english.evaluation)

    assert english.artifact_path is not None
    assert english.artifact_path.name == XL.artifact_filename(RECORDED_AT, arm(XL))
    payload = json.loads(english.artifact_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["config"]["query"]["language"] == "en"
    assert payload["config"]["retrieval"]["reranker"] is None


def test_rendered_tables_join_the_two_language_runs(XL, BI, monkeypatch):
    need(XL, "arm_comparison_markdown", "language_category_markdown")
    need(BI, "BilingualSuite")
    scripted(XL, monkeypatch, {"en": [hit(1, start=100)], "ko": []})
    runs = [run(XL, BI, arm(XL, language="ko"), None), run(XL, BI, arm(XL), None)]

    comparison = XL.arm_comparison_markdown(runs)
    categories = XL.language_category_markdown(runs)

    lines = comparison.splitlines()
    assert lines[0].startswith("| Arm | Strategy | Handling | Language |")
    # English sorts before Korean regardless of the order the runs arrived in.
    assert "-en |" in lines[2]
    assert "-ko |" in lines[3]
    assert categories.splitlines()[0].startswith("| Arm | Language | Category |")
    assert categories.count("| en |") == 2
    assert categories.count("| ko |") == 2
    with pytest.raises(ValueError, match="at least one run"):
        XL.arm_comparison_markdown([])
    with pytest.raises(ValueError, match="at least one run"):
        XL.language_category_markdown([])


def test_routed_handling_asks_the_service_to_skip_the_dead_component(XL, monkeypatch):
    need(XL, "make_crosslingual_retriever")
    calls = []

    async def fake_retrieve(session, query, **kwargs):
        calls.append((query, kwargs["route_by_language"], kwargs["lexical_ranker"]))
        return SimpleNamespace(hits=(hit(1, start=100),))

    monkeypatch.setattr(XL, "retrieve", fake_retrieve)
    retriever = XL.make_crosslingual_retriever(
        SimpleNamespace(),
        arm(XL, handling="routed", language="ko"),
        provider=None,
    )

    hits = asyncio.run(retriever("AMD의 매출은?", 5))

    assert [candidate.chunk_id for candidate in hits] == [1]
    assert calls == [("AMD의 매출은?", True, "ts_rank_cd")]


def test_translated_handling_rewrites_the_query_and_records_what_it_sent(XL, monkeypatch):
    need(XL, "make_crosslingual_retriever", "TranslationLog")
    seen = []
    scripted(XL, monkeypatch, {"en": [hit(1, start=100)], "ko": []})

    def factory(session, **kwargs):
        async def retriever(query: str, k: int):
            seen.append(query)
            return [hit(1, start=100)]

        return retriever

    monkeypatch.setattr(XL, "make_retriever", factory)

    async def fake_translate(query, *, llm_provider, provider_budget):
        return SimpleNamespace(translated_query="AMD revenue?", source_language="ko")

    monkeypatch.setattr(XL, "translate_query", fake_translate)
    log = XL.TranslationLog()
    retriever = XL.make_crosslingual_retriever(
        SimpleNamespace(),
        arm(XL, handling="translated", language="ko", translator_model="gpt-4.1-mini"),
        provider=None,
        llm_provider=object(),
        provider_budget=object(),
        translation_log=log,
    )

    asyncio.run(retriever("AMD의 매출은?", 5))

    assert seen == ["AMD revenue?"]
    assert log.payload() == [
        {
            "original": "AMD의 매출은?",
            "translated": "AMD revenue?",
            "source_language": "ko",
        }
    ]
    with pytest.raises(ValueError, match="LLM provider"):
        XL.make_crosslingual_retriever(
            SimpleNamespace(),
            arm(XL, handling="translated", language="ko", translator_model="gpt-4.1-mini"),
            provider=None,
        )


def test_parity_pairs_only_gate_a_hybrid_arm_with_language_aware_handling(XL, BI, monkeypatch):
    need(XL, "parity_pairs", "gated_assessments")
    need(BI, "BilingualSuite")
    scripted(XL, monkeypatch, {"en": [hit(1, start=100)], "ko": [hit(1, start=100)]})

    async def fake_retrieve(session, query, **kwargs):
        return SimpleNamespace(hits=(hit(1, start=100),))

    monkeypatch.setattr(XL, "retrieve", fake_retrieve)
    runs = [
        run(XL, BI, arm(XL, language=language, handling=handling), None)
        for handling in ("direct", "routed")
        for language in ("en", "ko")
    ]
    runs.append(run(XL, BI, arm(XL, strategy="vector", lexical_ranker=None), None))

    assessments = XL.parity_pairs(runs)
    gated = XL.gated_assessments(assessments)

    assert [assessment_arm.name for assessment_arm, _ in assessments] == [
        "xling-deterministic-hybrid-ts-rank-cd-ko",
        "xling-deterministic-hybrid-ts-rank-cd-routed-ko",
    ]
    assert [assessment_arm.handling for assessment_arm, _ in gated] == ["routed"]
    assert all(assessment.passed for _, assessment in gated)


def test_command_line_defaults_and_flags_match_the_documented_shape(XL):
    need(XL, "arguments", "build_arms")
    defaults = XL.arguments([])

    assert defaults.provider == "deterministic"
    assert defaults.languages == ["en", "ko"]
    assert defaults.strategies == ["lexical", "vector", "hybrid"]
    assert defaults.handling == ["direct"]
    assert defaults.artifact_dir.as_posix() == "data/eval_runs"
    assert defaults.persist_results is False
    assert defaults.gate is False
    assert defaults.min_recall_ratio == pytest.approx(0.85)

    args = XL.arguments(
        [
            "--provider",
            "sbert-multi",
            "--languages",
            "en",
            "ko",
            "--strategies",
            "hybrid",
            "--handling",
            "direct",
            "routed",
            "--artifact-dir",
            "/tmp/runs",
            "--persist-results",
            "--gate",
        ]
    )

    assert (args.provider, args.strategies, args.handling) == (
        "sbert-multi",
        ["hybrid"],
        ["direct", "routed"],
    )
    assert args.persist_results is True
    assert args.gate is True


def test_build_arms_crosses_handling_only_with_the_hybrid_strategy(XL):
    need(XL, "build_arms")
    args = XL.arguments(
        [
            "--strategies",
            "lexical",
            "vector",
            "hybrid",
            "--handling",
            "direct",
            "routed",
            "--languages",
            "ko",
            "en",
            "en",
        ]
    )

    arms = XL.build_arms(args, "token-hash-384")

    assert [built.name for built in arms] == [
        "xling-deterministic-lexical-ts-rank-cd-en",
        "xling-deterministic-lexical-ts-rank-cd-ko",
        "xling-deterministic-vector-en",
        "xling-deterministic-vector-ko",
        "xling-deterministic-hybrid-ts-rank-cd-en",
        "xling-deterministic-hybrid-ts-rank-cd-ko",
        "xling-deterministic-hybrid-ts-rank-cd-routed-en",
        "xling-deterministic-hybrid-ts-rank-cd-routed-ko",
    ]
    assert all(built.target_text_chars == XL.CROSSLINGUAL_TARGET_TEXT_CHARS for built in arms)
    assert all(built.to_config()["retrieval"]["reranker"] is None for built in arms)
