"""Cross-lingual arms, query-path diagnostics, rendering, and command tests."""

import asyncio
import json
from types import SimpleNamespace
from typing import Any, cast

from pydantic import SecretStr
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
import app.evals.arms as arms
from app.evals.bilingual import BilingualSuite
import app.evals.crosslingual as crosslingual
from app.evals.crosslingual import (
    CROSSLINGUAL_SUITE,
    CROSSLINGUAL_TARGET_TEXT_CHARS,
    CrosslingualArm,
    ProviderChoice,
    TranslationLog,
    arguments,
    arm_comparison_markdown,
    build_arms,
    category_breakdown,
    embedding_identity,
    gated_assessments,
    language_category_markdown,
    lexical_candidate_coverage,
    make_crosslingual_retriever,
    parity_pairs,
    run_arm,
    twin_query_alignment,
)
from app.evals.identity import artifact_filename
from app.evals.parity import ParityAssessment
from app.evals.retrieval_eval import PersistedEvaluation
from app.evals.types import GoldenCase, GoldenCategory, GoldenSpan
from app.llm.provider import LLMProvider, OpenAILLMProvider
from app.llm.schemas import ProviderBudget
from app.retrieval.embeddings import DeterministicEmbeddingProvider
from app.retrieval.sbert import MULTILINGUAL_SBERT_MODEL
from app.retrieval.types import ChunkHit, RetrievalFilters
from tests.evals.support import EVALUATION_RECORDED_AT, SOURCE_SHA256

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
    categories: tuple[GoldenCategory, ...] = ("simple_lookup", "simple_lookup", "multi_hop"),
):
    """Build one synthetic twin suite over three shared answer spans."""
    ids = sorted(QUESTIONS)
    return BilingualSuite(
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
    body = "Research and development expenses increased."
    context_header = "AMD FY2019 · Item 7"
    return ChunkHit(
        chunk_id=chunk_id,
        doc_id="AMD-FY2019",
        item="7",
        kind="text",
        citation=context_header,
        start_char=start,
        end_char=start + 100,
        source_sha256=SOURCE_SHA256,
        body=body,
        context_header=context_header,
        index_text=f"{context_header}\n\n{body}",
        score=score,
    )


BM25_FIELDS = {"bm25_k1": 1.2, "bm25_b": 0.75, "bm25_idf": "lucene"}


def arm(**changes):
    """Build one hybrid deterministic arm with optional field replacements."""
    values: dict[str, Any] = {
        "embedding_provider": "deterministic",
        "embedding_model": "token-hash-384",
        "strategy": "hybrid",
        "language": "en",
        "lexical_ranker": "ts_rank_cd",
    }
    values.update(changes)
    return CrosslingualArm(**values)


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
    assert payload["chunking"]["target_text_chars"] == CROSSLINGUAL_TARGET_TEXT_CHARS
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


def test_twin_alignment_measures_the_embedding_space_without_a_corpus():
    """Measure bilingual embedding alignment without corpus persistence."""
    provider = DeterministicEmbeddingProvider()

    alignment = asyncio.run(twin_query_alignment(provider, suite(), provider_name="deterministic"))

    assert alignment.provider == "deterministic"
    assert alignment.pair_count == 3
    assert {pair.case_id for pair in alignment.pairs} == set(QUESTIONS)
    assert -1.0 <= alignment.min_cosine <= alignment.mean_cosine <= alignment.max_cosine <= 1.0
    # A token-hashing space shares almost nothing across the twins, but 384 hashed
    # dimensions do collide, so the cosine is near zero rather than exactly zero.
    assert alignment.mean_cosine < 0.5

    identical = BilingualSuite(
        en=(golden("m3c-01", "en"),),
        ko=(golden("m3c-01", "en"),),
    )
    same = asyncio.run(twin_query_alignment(provider, identical))
    assert same.mean_cosine == pytest.approx(1.0)
    assert same.provider == "unknown"


def test_lexical_coverage_counts_the_collapse_instead_of_assuming_it():
    """Measure partial Korean lexical collapse from actual candidate counts."""
    cases = suite().ko

    async def latin_only(query: str, k: int):
        """Return one candidate only for the Latin-bearing Korean question."""
        # Korean questions still carry Latin tokens, and the English tsquery can match
        # them, so the collapse is partial. The number says how partial.
        return [hit(1, start=100)] if "AMD" in query else []

    coverage = asyncio.run(
        lexical_candidate_coverage(latin_only, cases, language="ko", candidate_k=20)
    )

    assert coverage.language == "ko"
    assert coverage.case_count == 3
    assert coverage.zero_candidate_cases == 2
    assert 0.0 < coverage.zero_candidate_rate < 1.0
    assert coverage.zero_candidate_case_ids == ("m3c-02", "m3c-03")
    assert coverage.mean_candidate_count == pytest.approx(1 / 3)

    with pytest.raises(ValueError, match="at least one case"):
        asyncio.run(lexical_candidate_coverage(latin_only, (), language="ko"))


def evaluate_arm(module_arm, tmp_path=None):
    """Evaluate one arm against a scripted retriever, bypassing the database."""
    return asyncio.run(
        run_arm(
            cast(AsyncSession, SimpleNamespace()),
            module_arm,
            suite(),
            provider=None,
            artifact_dir=tmp_path,
            recorded_at=EVALUATION_RECORDED_AT,
        )
    )


def scripted(monkeypatch, per_language):
    """Replace ``make_retriever`` with a scripted, database-free retriever."""

    def factory(session, **kwargs):
        """Build one scripted retriever for the requested language."""

        async def retriever(query: str, k: int):
            """Return the scripted hits for the query language."""
            language = (
                "ko" if any(question == query for _, question in QUESTIONS.values()) else "en"
            )
            return per_language[language]

        return retriever

    monkeypatch.setattr(crosslingual, "make_retriever", factory)


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


def test_rendered_tables_join_the_two_language_runs(monkeypatch):
    """Render language runs and category slices in deterministic order."""
    scripted(monkeypatch, {"en": [hit(1, start=100)], "ko": []})
    runs = [evaluate_arm(arm(language="ko")), evaluate_arm(arm())]

    comparison = arm_comparison_markdown(runs)
    categories = language_category_markdown(runs)

    lines = comparison.splitlines()
    assert lines[0].startswith("| Arm | Strategy | Handling | Language |")
    # English sorts before Korean regardless of the order the runs arrived in.
    assert "-en |" in lines[2]
    assert "-ko |" in lines[3]
    assert categories.splitlines()[0].startswith("| Arm | Language | Category |")
    assert categories.count("| en |") == 2
    assert categories.count("| ko |") == 2
    with pytest.raises(ValueError, match="at least one run"):
        arm_comparison_markdown([])
    with pytest.raises(ValueError, match="at least one run"):
        language_category_markdown([])


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
        assert [candidate.chunk_id for candidate in hits] == [1]

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
            return [hit(1, start=100)]

        return retriever

    monkeypatch.setattr(crosslingual, "make_retriever", factory)

    async def fake_translate(query, *, llm_provider, provider_budget, target_language="en"):
        """Return a fixed validated English translation."""
        return SimpleNamespace(translated_query="AMD revenue?", source_language="ko")

    monkeypatch.setattr(crosslingual, "translate_query", fake_translate)
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


def test_parity_pairs_only_gate_a_hybrid_arm_with_language_aware_handling(monkeypatch):
    """Gate parity only for paired hybrid arms with language-aware handling."""
    scripted(monkeypatch, {"en": [hit(1, start=100)], "ko": [hit(1, start=100)]})
    runs = [
        evaluate_arm(arm(language=language, handling=handling))
        for handling in ("direct", "routed")
        for language in ("en", "ko")
    ]
    runs.append(evaluate_arm(arm(strategy="vector", lexical_ranker=None)))

    assessments = parity_pairs(runs)
    gated = gated_assessments(assessments)

    assert [assessment_arm.name for assessment_arm, _ in assessments] == [
        "xling-deterministic-hybrid-ts-rank-cd-ko",
        "xling-deterministic-hybrid-ts-rank-cd-routed-ko",
    ]
    assert [assessment_arm.handling for assessment_arm, _ in gated] == ["routed"]
    assert all(assessment.passed for _, assessment in gated)


def test_command_line_defaults_and_flags_match_the_documented_shape():
    """Expose stable defaults and accept explicit cross-lingual matrix flags."""
    defaults = arguments([])

    assert defaults.provider == "deterministic"
    assert defaults.languages == ["en", "ko"]
    assert defaults.strategies == ["lexical", "vector", "hybrid"]
    assert defaults.handling == ["direct"]
    assert defaults.artifact_dir.as_posix() == "data/eval_runs"
    assert defaults.persist_results is False
    assert defaults.gate is False
    assert defaults.min_recall_ratio == pytest.approx(0.85)

    args = arguments(
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


def verdict(*, parity, regression):
    """Build one gate verdict from scripted parity and regression outcomes."""
    gated = [
        (
            arm(handling="routed", language="ko"),
            cast(ParityAssessment, SimpleNamespace(passed=outcome)),
        )
        for outcome in parity
    ]
    persisted = [
        (
            arm(language="ko"),
            cast(PersistedEvaluation, SimpleNamespace(passed=outcome, comparison=object())),
        )
        for outcome in regression
    ]
    return crosslingual.gate_verdict(gated, persisted, enabled=True)


def test_the_gate_blocks_on_a_failing_ratio_or_a_regressed_language_slice():
    """Require both halves, and report null for the half that never ran."""
    assert verdict(parity=[True], regression=[True])["passed"] is True
    assert verdict(parity=[False], regression=[True])["passed"] is False

    # Raising the Korean slice by dropping the English one improves the ratio, so a
    # per-language regression fails the gate even when parity looks healthy.
    regressed = verdict(parity=[True], regression=[True, False])
    assert regressed["passed"] is False
    assert regressed["regression_passed"] is False

    # A command that persisted nothing compared nothing, and must not report a pass
    # for a check it never performed.
    unpersisted = verdict(parity=[True], regression=[])
    assert unpersisted["regression_passed"] is None
    assert unpersisted["passed"] is True
    assert unpersisted["regression_arms"] == []
    assert unpersisted["parity_arms"] == ["xling-deterministic-hybrid-ts-rank-cd-routed-ko"]


def test_the_translation_boundary_resolves_its_deferred_sdk_import():
    """Build the paid provider and budget through the import _run_cli defers."""
    # _run_cli needs a corpus and a database and no test executes it, so the deferred
    # import inside it is invisible to both the linter and the suite. Building the
    # boundary here is what makes a moved or renamed SDK symbol fail a test rather
    # than every invocation of the command.
    provider, budget = crosslingual.translation_boundary(
        "gpt-5.6-luna", Settings(openai_api_key=SecretStr("sk-not-a-real-key"))
    )
    try:
        assert provider.model_name == "gpt-5.6-luna"
        assert budget.max_input_tokens == crosslingual.TRANSLATION_MAX_INPUT_TOKENS
        assert budget.max_output_tokens == crosslingual.TRANSLATION_MAX_OUTPUT_TOKENS
    finally:
        asyncio.run(cast(OpenAILLMProvider, provider).aclose())


def test_run_arm_records_the_suite_the_command_was_given(monkeypatch):
    """Stamp the requested suite on the artifact, not the module default."""
    scripted(monkeypatch, {"en": [hit(1, start=100)], "ko": []})

    # Suite identity is half of the baseline key, so a run isolated under its own name
    # must not write into the shipped suite's regression history.
    measured = asyncio.run(
        run_arm(
            cast(AsyncSession, SimpleNamespace()),
            arm(),
            suite(),
            provider=None,
            suite_name="my-isolated-suite",
            recorded_at=EVALUATION_RECORDED_AT,
        )
    )

    assert measured.evaluation.suite == "my-isolated-suite"
    assert arguments([]).suite == CROSSLINGUAL_SUITE


def test_the_gate_is_refused_before_a_corpus_when_the_matrix_cannot_be_gated():
    """Decide gate feasibility from the requested axes alone."""
    # --handling defaults to direct, so plain --gate can never be judged; refusing it
    # only after indexing would spend the whole matrix on a run destined to fail.
    assert crosslingual.gateable_matrix(build_arms(arguments([]), "token-hash-384")) is False
    assert (
        crosslingual.gateable_matrix(
            build_arms(arguments(["--handling", "routed", "--languages", "en"]), "token-hash-384")
        )
        is False
    )
    assert (
        crosslingual.gateable_matrix(
            build_arms(arguments(["--handling", "routed"]), "token-hash-384")
        )
        is True
    )


def test_the_command_rejects_a_candidate_pool_shallower_than_k_during_parsing():
    """Reject an inconsistent depth at parse time, not after the suites are loaded."""
    with pytest.raises(SystemExit) as exit_info:
        arguments(["-k", "10", "--candidate-k", "5"])

    assert exit_info.value.code == 2


def test_the_command_rejects_an_impossible_parity_floor_before_measuring_anything():
    """Reject an out-of-range floor during parsing, not after the matrix has run."""
    with pytest.raises(SystemExit) as exit_info:
        arguments(["--min-recall-ratio", "1.5"])

    assert exit_info.value.code == 2
    assert arguments(["--min-recall-ratio", "1"]).min_recall_ratio == pytest.approx(1.0)


def test_build_arms_gives_a_bm25_matrix_the_parameters_its_binder_demands():
    """Source BM25 values from settings for a BM25 matrix and omit them otherwise."""
    settings = Settings(bm25_k1=1.5, bm25_b=0.5, bm25_idf="robertson")
    args = arguments(["--strategies", "vector", "hybrid", "--lexical-ranker", "bm25"])

    built = build_arms(args, "token-hash-384", settings=settings)
    by_strategy = {arm.strategy: arm for arm in built}

    assert by_strategy["hybrid"].to_config()["retrieval"]["bm25"] == {
        "k1": 1.5,
        "b": 0.5,
        "idf": "robertson",
    }
    # A vector arm runs no lexical query, so it must carry no BM25 provenance at all.
    assert by_strategy["vector"].bm25_k1 is None
    assert "bm25" not in by_strategy["vector"].to_config()["retrieval"]

    default = build_arms(arguments(["--strategies", "hybrid"]), "token-hash-384", settings=settings)
    assert "bm25" not in default[0].to_config()["retrieval"]


def test_build_arms_crosses_handling_only_with_the_hybrid_strategy():
    """Cross routed handling only with hybrid arms and deduplicate axes."""
    args = arguments(
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

    arms = build_arms(args, "token-hash-384")

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
    assert all(built.target_text_chars == CROSSLINGUAL_TARGET_TEXT_CHARS for built in arms)
    assert all(built.to_config()["retrieval"]["reranker"] is None for built in arms)


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


def test_parity_groups_never_collapse_across_corpora():
    """The same shape measured on two corpora forms two parity groups, not one."""
    shapes = [
        arm(strategy="hybrid", lexical_ranker="ts_rank_cd", language=lang, handling="routed")
        for lang in ("en", "ko")
    ]
    dart_shapes = [
        arm(
            strategy="hybrid",
            lexical_ranker="ts_rank_cd",
            language=lang,
            handling="routed",
            corpus_registry="dart",
        )
        for lang in ("en", "ko")
    ]

    assert crosslingual.gateable_matrix(shapes)
    assert crosslingual.gateable_matrix(dart_shapes)
    assert crosslingual._parity_identity(shapes[0]) != crosslingual._parity_identity(dart_shapes[0])


def test_corpus_argument_resolves_suite_goldens_and_chunk_target():
    """--corpus dart binds the DART suite, goldens, manifest, and 600-char target."""
    args = crosslingual.arguments(["--corpus", "dart"])

    assert args.suite == crosslingual.DART_CROSSLINGUAL_SUITE
    assert args.golden.name == "dart_retrieval.json"
    assert args.ko_golden.name == "dart_retrieval_ko.json"
    built = crosslingual.build_arms(args, "token-hash-384", settings=Settings())
    assert {arm.corpus_registry for arm in built} == {"dart"}
    assert {arm.target_text_chars for arm in built} == {600}

    edgar_args = crosslingual.arguments([])
    assert edgar_args.suite == crosslingual.CROSSLINGUAL_SUITE
    assert edgar_args.golden.name == "retrieval.json"
    edgar_built = crosslingual.build_arms(edgar_args, "token-hash-384", settings=Settings())
    assert {arm.target_text_chars for arm in edgar_built} == {1200}


def test_every_arm_pins_its_corpus_language_filter(monkeypatch):
    """The bound retriever always carries the arm's corpus language filter."""
    seen = {}

    def factory(_session, **kwargs):
        """Capture the bound corpus filter and return an empty retriever."""
        seen.update(kwargs)

        async def run(_query, _k):
            """Return no hits for the filter-binding assertion."""
            return ()

        return run

    monkeypatch.setattr(crosslingual, "make_retriever", factory)
    session = cast(AsyncSession, object())
    crosslingual.make_crosslingual_retriever(session, arm(), provider=None)
    assert seen["filters"] == RetrievalFilters(languages=("en",))

    crosslingual.make_crosslingual_retriever(session, arm(corpus_registry="dart"), provider=None)
    assert seen["filters"] == RetrievalFilters(languages=("ko",))


def test_gate_reports_and_optionally_fails_missing_baselines():
    """Name first-run arms in the verdict; --require-baseline turns them into a failure."""
    gated = [
        (
            arm(handling="routed", language="ko"),
            cast(ParityAssessment, SimpleNamespace(passed=True)),
        )
    ]
    first_run = [
        (
            arm(language="ko"),
            cast(PersistedEvaluation, SimpleNamespace(passed=True, comparison=None)),
        )
    ]

    tolerated = crosslingual.gate_verdict(gated, first_run, enabled=True)
    required = crosslingual.gate_verdict(gated, first_run, enabled=True, require_baseline=True)

    assert tolerated["regression_first_runs"] == [first_run[0][0].name]
    assert tolerated["passed"] is True
    assert required["passed"] is False
