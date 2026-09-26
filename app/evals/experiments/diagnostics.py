"""Cross-lingual query-path diagnostics, comparison tables, and the parity gate."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import math
from typing import Any, Final

from app.evals.execution.evaluator import PersistedEvaluation, RetrievalEvaluation
from app.evals.execution.retrievers import Retriever
from app.evals.experiments.crosslingual import (
    HANDLING_ORDER,
    LANGUAGE_CHOICES,
    CrosslingualArm,
    LanguageRun,
)
from app.evals.golden.bilingual import BilingualSuite
from app.evals.golden.models import GoldenCase
from app.evals.results.identity import EVALUATED_GOLDEN_KEY, STRATEGY_ORDER
from app.evals.results.regression import HIGHER_IS_BETTER_METRICS, MetricName, RegressionTolerances
from app.evals.results.reporting import markdown_table
from app.query.language import QueryLanguage
from app.retrieval.embedding.provider import EmbeddingProvider

DEFAULT_MIN_RECALL_RATIO: Final[float] = 0.85

# One positive case out of 24 moves a macro metric by about 0.042. A tolerance below
# that would let a single flipped case fail the gate, so the standing per-language
# regression allowance sits deliberately above single-case granularity.
PARITY_REGRESSION_TOLERANCE: Final[float] = 0.05

# Parity is a ratio between two arms measured together; this is the other half of the
# gate, and each language slice is compared with its own stored baseline through
# ``persist_evaluation``. Raising the Korean slice while quietly dropping the English
# one would improve the ratio, so the English slice keeps its own standing check.
LANGUAGE_REGRESSION_TOLERANCES: Final[RegressionTolerances] = RegressionTolerances(
    recall_at_k=PARITY_REGRESSION_TOLERANCE,
    hit_rate_at_k=PARITY_REGRESSION_TOLERANCE,
    mrr=PARITY_REGRESSION_TOLERANCE,
)

GATED_METRIC: Final[MetricName] = "recall_at_k"


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


@dataclass(frozen=True, slots=True)
class ParityMetric:
    """One metric measured on both language slices of the same arm.

    ``delta`` and ``ratio`` are oriented by the corpus's native language: delta is
    native minus foreign and ratio is foreign over native, so the same floor means
    the same thing on an English corpus (native en) and a Korean one (native ko).
    """

    metric: MetricName
    en: float
    ko: float
    delta: float
    ratio: float | None


@dataclass(frozen=True, slots=True)
class ParityAssessment:
    """The complete cross-language verdict for one arm pair."""

    suite: str
    k: int
    case_count: int
    min_recall_ratio: float
    metrics: tuple[ParityMetric, ...]
    failures: tuple[str, ...]
    native_language: str = "en"

    @property
    def passed(self) -> bool:
        """Return whether the gated ratio cleared its floor."""
        return not self.failures


def _config_identity(config: Mapping[str, Any], expected_language: str) -> dict[str, Any]:
    """Compare arm settings while allowing the two language-specific case payloads."""
    query = config.get("query")
    if not isinstance(query, Mapping) or "language" not in query:
        raise ValueError("parity requires an evaluation config carrying query.language")
    if query["language"] != expected_language:
        raise ValueError(f"expected a {expected_language} evaluation, got {query['language']!r}")
    # Translated questions have different evaluated hashes by design; case alignment is
    # checked separately before comparing these retrieval settings.
    identity = {
        key: value for key, value in config.items() if key not in {"name", EVALUATED_GOLDEN_KEY}
    }
    identity["query"] = {key: value for key, value in query.items() if key != "language"}
    return identity


def _case_ids(evaluation: RetrievalEvaluation) -> tuple[frozenset[str], frozenset[str]]:
    """Return the evaluated case ids and the subset that carried a score."""
    all_ids = frozenset(case.golden.id for case in evaluation.cases)
    scored_ids = frozenset(case.golden.id for case in evaluation.cases if case.score is not None)
    return all_ids, scored_ids


def assess_parity(
    en_eval: RetrievalEvaluation,
    ko_eval: RetrievalEvaluation,
    *,
    min_recall_ratio: float = DEFAULT_MIN_RECALL_RATIO,
    native_language: str = "en",
) -> ParityAssessment:
    """Compare evaluations whose only configured difference is query language.

    ``native_language`` names the corpus's own language: its slice is the
    denominator, so the gate always asks how well the foreign-language questions
    keep up with the questions the corpus was written in. A zero native score
    leaves the ratio undefined and fails closed.
    """
    if native_language not in {"en", "ko"}:
        raise ValueError("native_language must be 'en' or 'ko'")
    if not isinstance(en_eval, RetrievalEvaluation) or not isinstance(ko_eval, RetrievalEvaluation):
        raise TypeError("parity requires two RetrievalEvaluation values")
    if not math.isfinite(min_recall_ratio) or not 0.0 < min_recall_ratio <= 1.0:
        raise ValueError("min_recall_ratio must be in (0, 1]")
    if en_eval.suite != ko_eval.suite:
        raise ValueError("parity requires both evaluations to share one suite")
    if en_eval.score.k != ko_eval.score.k:
        raise ValueError("parity requires both evaluations to use the same k")

    en_ids, en_scored = _case_ids(en_eval)
    ko_ids, ko_scored = _case_ids(ko_eval)
    if en_ids != ko_ids or en_scored != ko_scored:
        raise ValueError("parity requires both evaluations to cover the same golden cases")
    if _config_identity(en_eval.config, "en") != _config_identity(ko_eval.config, "ko"):
        raise ValueError("parity arms must differ only in query language")

    en_values = en_eval.metric_values()
    ko_values = ko_eval.metric_values()
    metrics: list[ParityMetric] = []
    failures: list[str] = []
    for name in HIGHER_IS_BETTER_METRICS:
        english = en_values[name]
        korean = ko_values[name]
        native, foreign = (english, korean) if native_language == "en" else (korean, english)
        ratio = None if native == 0.0 else foreign / native
        metrics.append(
            ParityMetric(
                metric=name,
                en=english,
                ko=korean,
                delta=native - foreign,
                ratio=ratio,
            )
        )
        if name != GATED_METRIC:
            continue
        if ratio is None:
            failures.append(
                f"{name}: the native {native_language} slice scored 0, so parity is undefined"
            )
        elif ratio < min_recall_ratio and not math.isclose(
            ratio,
            min_recall_ratio,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            failures.append(f"{name}: ratio {ratio:.6f} is below the floor {min_recall_ratio:.6f}")

    return ParityAssessment(
        suite=en_eval.suite,
        k=en_eval.score.k,
        case_count=en_eval.score.case_count,
        min_recall_ratio=min_recall_ratio,
        metrics=tuple(metrics),
        failures=tuple(failures),
        native_language=native_language,
    )


def parity_markdown(assessment: ParityAssessment) -> str:
    """Render one parity assessment as a compact verdict table."""
    verdict = "PASS" if assessment.passed else "FAIL"
    native = assessment.native_language.upper()
    foreign = "KO" if native == "EN" else "EN"
    table = markdown_table(
        ["Metric", "EN", "KO", f"Delta ({native}-{foreign})", f"Ratio ({foreign}/{native})"],
        ["left", "right", "right", "right", "right"],
        [
            [
                result.metric,
                f"{result.en:.6f}",
                f"{result.ko:.6f}",
                f"{result.delta:.6f}",
                "undefined" if result.ratio is None else f"{result.ratio:.6f}",
            ]
            for result in assessment.metrics
        ],
    )
    lines = [table, ""]
    lines.append(
        f"{verdict} — {assessment.suite}, k={assessment.k}, "
        f"{assessment.case_count} scored cases, "
        f"{GATED_METRIC} floor {assessment.min_recall_ratio:.2f}."
    )
    for failure in assessment.failures:
        lines.append(f"- {failure}")
    return "\n".join(lines)
