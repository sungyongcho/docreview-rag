"""Cross-lingual diagnostics: twin alignment, lexical coverage, tables, and the gate."""

import asyncio
from types import SimpleNamespace
from typing import cast

import pytest

from app.evals.bilingual import BilingualSuite
import app.evals.crosslingual_diagnostics as crosslingual_diagnostics
from app.evals.crosslingual_diagnostics import (
    arm_comparison_markdown,
    gated_assessments,
    language_category_markdown,
    lexical_candidate_coverage,
    parity_pairs,
    twin_query_alignment,
)
from app.evals.parity import ParityAssessment
from app.evals.retrieval_eval import PersistedEvaluation
from app.retrieval.embeddings import DeterministicEmbeddingProvider
from tests.evals.crosslingual_support import (
    QUESTIONS,
    arm,
    evaluate_arm,
    golden,
    hit,
    scripted,
    suite,
)


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
    return crosslingual_diagnostics.gate_verdict(gated, persisted, enabled=True)


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

    assert crosslingual_diagnostics.gateable_matrix(shapes)
    assert crosslingual_diagnostics.gateable_matrix(dart_shapes)
    assert crosslingual_diagnostics._parity_identity(
        shapes[0]
    ) != crosslingual_diagnostics._parity_identity(dart_shapes[0])


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

    tolerated = crosslingual_diagnostics.gate_verdict(gated, first_run, enabled=True)
    required = crosslingual_diagnostics.gate_verdict(
        gated, first_run, enabled=True, require_baseline=True
    )

    assert tolerated["regression_first_runs"] == [first_run[0][0].name]
    assert tolerated["passed"] is True
    assert required["passed"] is False
