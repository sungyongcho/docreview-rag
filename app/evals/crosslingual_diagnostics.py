"""Cross-lingual query-path diagnostics, comparison tables, and the parity gate."""

from collections.abc import Sequence
from dataclasses import dataclass
import math
from typing import Any

from app.evals.arms import Retriever
from app.evals.bilingual import BilingualSuite
from app.evals.crosslingual_arms import (
    HANDLING_ORDER,
    LANGUAGE_CHOICES,
    CrosslingualArm,
    LanguageRun,
)
from app.evals.identity import STRATEGY_ORDER
from app.evals.parity import DEFAULT_MIN_RECALL_RATIO, ParityAssessment, assess_parity
from app.evals.reporting import markdown_table
from app.evals.retrieval_eval import PersistedEvaluation
from app.evals.types import GoldenCase
from app.retrieval.embeddings import EmbeddingProvider
from app.retrieval.language import QueryLanguage


@dataclass(frozen=True, slots=True)
class TwinCosine:
    """One twin pair's query-vector cosine under a single embedding provider."""

    case_id: str
    cosine: float


@dataclass(frozen=True, slots=True)
class TwinAlignment:
    """How closely one embedding space places Korean queries beside their twins."""

    provider: str
    pair_count: int
    mean_cosine: float
    min_cosine: float
    max_cosine: float
    pairs: tuple[TwinCosine, ...]


@dataclass(frozen=True, slots=True)
class LexicalCoverage:
    """How often the English lexical index returns nothing for one language."""

    language: QueryLanguage
    case_count: int
    zero_candidate_cases: int
    zero_candidate_rate: float
    mean_candidate_count: float
    zero_candidate_case_ids: tuple[str, ...]


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    """Return the cosine of two equal-length nonzero vectors."""
    if len(left) != len(right):
        raise ValueError("cosine requires vectors of equal length")
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0.0 or right_norm == 0.0:
        raise ValueError("cosine is undefined for a zero vector")
    return dot / (left_norm * right_norm)


async def twin_query_alignment(
    provider: EmbeddingProvider,
    suite: BilingualSuite,
    *,
    provider_name: str = "unknown",
) -> TwinAlignment:
    """Measure each Korean query's cosine alignment with its English twin.

    This diagnostic exercises the embedding space without a corpus or database.
    """
    pairs = suite.pairs()
    if not pairs:
        raise ValueError("twin alignment requires at least one pair")
    en_vectors = await provider.embed_documents([english.question for english, _ in pairs])
    ko_vectors = await provider.embed_documents([korean.question for _, korean in pairs])
    measured = tuple(
        TwinCosine(case_id=english.id, cosine=_cosine(en_vector, ko_vector))
        for (english, _), en_vector, ko_vector in zip(pairs, en_vectors, ko_vectors, strict=True)
    )
    cosines = [item.cosine for item in measured]
    return TwinAlignment(
        provider=provider_name,
        pair_count=len(measured),
        mean_cosine=sum(cosines) / len(cosines),
        min_cosine=min(cosines),
        max_cosine=max(cosines),
        pairs=measured,
    )


async def lexical_candidate_coverage(
    retriever: Retriever,
    cases: Sequence[GoldenCase],
    *,
    language: QueryLanguage,
    candidate_k: int = 20,
) -> LexicalCoverage:
    """Measure how often one language produces no lexical candidates.

    The injected retriever keeps the diagnostic usable both offline and in a measured
    corpus run.
    """
    if not cases:
        raise ValueError("lexical coverage requires at least one case")
    if candidate_k <= 0:
        raise ValueError("candidate_k must be positive")
    empty: list[str] = []
    total = 0
    for case in sorted(cases, key=lambda item: item.id):
        hits = (await retriever(case.question, candidate_k)).hits
        total += len(hits)
        if not hits:
            empty.append(case.id)
    return LexicalCoverage(
        language=language,
        case_count=len(cases),
        zero_candidate_cases=len(empty),
        zero_candidate_rate=len(empty) / len(cases),
        mean_candidate_count=total / len(cases),
        zero_candidate_case_ids=tuple(empty),
    )


def arm_comparison_markdown(runs: Sequence[LanguageRun]) -> str:
    """Render one row per measured arm in deterministic arm order."""
    if not runs:
        raise ValueError("comparison requires at least one run")
    return markdown_table(
        [
            "Arm",
            "Strategy",
            "Handling",
            "Language",
            "Cases",
            "Recall@k",
            "Hit rate@k",
            "MRR",
            "P95 ms",
        ],
        ["left", "left", "left", "left", "right", "right", "right", "right", "right"],
        [
            [
                run.arm.name,
                run.arm.strategy,
                run.arm.handling,
                run.arm.language,
                str(run.evaluation.score.case_count),
                f"{run.evaluation.score.recall_at_k:.6f}",
                f"{run.evaluation.score.hit_rate_at_k:.6f}",
                f"{run.evaluation.score.mrr:.6f}",
                f"{run.evaluation.latency.p95_ms:.3f}",
            ]
            for run in sorted(runs, key=lambda item: item.arm.sort_key)
        ],
    )


def language_category_markdown(runs: Sequence[LanguageRun]) -> str:
    """Join each language run's category slices into one comparison table."""
    if not runs:
        raise ValueError("category table requires at least one run")
    return markdown_table(
        ["Arm", "Language", "Category", "Cases", "Recall@k", "Hit rate@k", "MRR"],
        ["left", "left", "left", "right", "right", "right", "right"],
        [
            [
                run.arm.name,
                run.arm.language,
                group.group,
                str(group.suite.case_count),
                f"{group.suite.recall_at_k:.6f}",
                f"{group.suite.hit_rate_at_k:.6f}",
                f"{group.suite.mrr:.6f}",
            ]
            for run in sorted(runs, key=lambda item: item.arm.sort_key)
            for group in run.categories
        ],
    )


def _parity_identity(arm: CrosslingualArm) -> tuple[str, str, str, str | None]:
    """Return the key the two language slices of one measured arm must share.

    The corpus registry is part of the key: without it, the four cells of a
    question-language x corpus matrix would collapse onto two slots and half the
    measured runs would be silently overwritten before assessment.
    """
    return (arm.corpus_registry, arm.strategy, arm.handling, arm.lexical_ranker)


def gateable_matrix(arms: Sequence[CrosslingualArm]) -> bool:
    """Report whether the requested matrix can produce a pair the gate may judge.

    Decidable from the arms alone, so ``--gate`` on a matrix that could never be gated
    is refused before a corpus is parsed rather than after every arm has been measured
    and, with a paid provider, paid for.
    """
    languages: dict[tuple[str, str, str, str | None], set[str]] = {}
    for arm in arms:
        if arm.strategy == "hybrid" and arm.handling != "direct":
            languages.setdefault(_parity_identity(arm), set()).add(arm.language)
    return any(covered == set(LANGUAGE_CHOICES) for covered in languages.values())


def parity_pairs(
    runs: Sequence[LanguageRun],
    *,
    min_recall_ratio: float = DEFAULT_MIN_RECALL_RATIO,
) -> tuple[tuple[CrosslingualArm, ParityAssessment], ...]:
    """Assess parity for every arm that was measured in both languages."""
    by_identity: dict[tuple[str, str, str, str | None], dict[str, LanguageRun]] = {}
    for run in runs:
        by_identity.setdefault(_parity_identity(run.arm), {})[run.arm.language] = run
    assessments: list[tuple[CrosslingualArm, ParityAssessment]] = []
    ordered = sorted(
        by_identity,
        key=lambda key: (key[0], STRATEGY_ORDER[key[1]], HANDLING_ORDER[key[2]], key[3] or ""),
    )
    for identity in ordered:
        slices = by_identity[identity]
        if set(slices) != {"en", "ko"}:
            continue
        assessments.append(
            (
                slices["ko"].arm,
                assess_parity(
                    slices["en"].evaluation,
                    slices["ko"].evaluation,
                    min_recall_ratio=min_recall_ratio,
                    native_language=slices["ko"].arm.corpus_language,
                ),
            )
        )
    return tuple(assessments)


def gated_assessments(
    assessments: Sequence[tuple[CrosslingualArm, ParityAssessment]],
) -> tuple[tuple[CrosslingualArm, ParityAssessment], ...]:
    """Select language-aware hybrid arms whose parity can gate shipping."""
    return tuple(
        (arm, assessment)
        for arm, assessment in assessments
        if arm.strategy == "hybrid" and arm.handling != "direct"
    )


def gate_verdict(
    gated: Sequence[tuple[CrosslingualArm, ParityAssessment]],
    persisted: Sequence[tuple[CrosslingualArm, PersistedEvaluation]],
    *,
    enabled: bool,
    require_baseline: bool = False,
) -> dict[str, Any]:
    """Combine parity and per-language regression into one gate verdict.

    Parameters
    ----------
    gated : Sequence[tuple[CrosslingualArm, ParityAssessment]]
        Shipping arms whose ko/en ratio the gate may judge.
    persisted : Sequence[tuple[CrosslingualArm, PersistedEvaluation]]
        Runs compared against their own stored baseline, empty when the command did
        not persist results.
    enabled : bool
        Whether ``--gate`` was requested, recorded so a reported verdict says whether
        anything depended on it.

    Returns
    -------
    dict[str, Any]
        Component results, their arm names, and the combined decision. Regression is
        ``None`` when no persisted baseline comparison ran.
    """
    parity_passed = all(assessment.passed for _, assessment in gated)
    regression_passed = all(result.passed for _, result in persisted) if persisted else None
    # A missing baseline passes by default (there is nothing to regress against),
    # but it is reported by name so a silently reset history is visible in every
    # verdict, and --require-baseline turns it into a failure.
    first_runs = [arm.name for arm, result in persisted if result.comparison is None]
    baseline_ok = not (require_baseline and first_runs)
    return {
        "enabled": enabled,
        "parity_arms": [arm.name for arm, _ in gated],
        "regression_arms": [arm.name for arm, _ in persisted],
        "regression_first_runs": first_runs,
        "parity_passed": parity_passed,
        "regression_passed": regression_passed,
        "passed": parity_passed and regression_passed is not False and baseline_ok,
    }
