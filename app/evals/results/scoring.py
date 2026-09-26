"""Deterministic span-level scoring for retrieval evaluation suites."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Final, get_args

from app.evals.golden.models import GoldenCase, GoldenCategory, GoldenSpan
from app.retrieval.types import ChunkHit

COVERAGE_THRESHOLD: Final[float] = 0.5


@dataclass(frozen=True, slots=True)
class CaseScore:
    """Retrieval metrics and matching provenance for one positive golden case."""

    case_id: str
    k: int
    gold_span_count: int
    matched_gold_count: int
    recall_at_k: float
    hit_at_k: float
    reciprocal_rank: float
    first_relevant_rank: int | None


@dataclass(frozen=True, slots=True)
class SuiteScore:
    """Macro-averaged retrieval metrics plus deterministic per-case results."""

    k: int
    case_count: int
    recall_at_k: float
    hit_rate_at_k: float
    mrr: float
    cases: tuple[CaseScore, ...]

    @property
    def parameters(self) -> dict[str, float]:
        """Return the scoring settings two runs must share to be comparable.

        Every metric above moves with the cutoff and with the relevance threshold,
        so a stored baseline is only meaningful against a run that used the same
        values. The evaluator records this mapping in both artifact and stored config.
        """
        return {"k": self.k, "coverage_threshold": COVERAGE_THRESHOLD}


def span_coverage(golden: GoldenSpan, hit: ChunkHit) -> float:
    """Return the fraction of one gold answer span that a retrieved chunk contains.

    The denominator is the gold span alone, never the chunk, so the score answers
    "is the curated answer inside this chunk?" and does not move when the chunker's
    target size changes. That independence is what makes recall comparable across
    chunking configurations. Touching boundaries have zero overlap, and a hit from
    another source snapshot is never relevant even when its document id and numeric
    offsets happen to match.

    Coverage rises with chunk width, so a wider chunk configuration buys relevance
    without retrieving better, and nothing here can detect that. A run's stored
    configuration must therefore record the chunk settings it used: two runs that
    chunked differently are two experiments, not a baseline and a regression.
    """
    if golden.doc_id != hit.doc_id or golden.source_sha256 != hit.source_sha256:
        return 0.0

    overlap = max(0, min(golden.end_char, hit.end_char) - max(golden.start_char, hit.start_char))
    return overlap / (golden.end_char - golden.start_char)


def score_case(
    case_id: str,
    golden_spans: Sequence[GoldenSpan],
    retrieved_hits: Sequence[ChunkHit],
    k: int,
) -> CaseScore:
    """Score the top-k hits for one positive golden case.

    Parameters
    ----------
    case_id : str
        Nonblank identifier copied into the resulting score.

    golden_spans : Sequence[GoldenSpan]
        Unique answer spans for one positive case.

    retrieved_hits : Sequence[ChunkHit]
        Ranked hits; only the first ``k`` are scored.

    k : int
        Positive cutoff shared by every metric.

    Returns
    -------
    CaseScore
        Per-case metrics with their matching provenance.

    Raises
    ------
    ValueError
        If ``k`` is not a positive integer, ``case_id`` is blank, or
        ``golden_spans`` is empty or contains duplicates.

    Notes
    -----
    A hit is relevant to a gold span when it contains at least
    ``COVERAGE_THRESHOLD`` of that span. Half is the largest threshold that survives
    a single chunk boundary falling inside a gold span, because two fragments cannot
    both be under half; a span cut by two or more boundaries can still drop below it.
    Recall counts unique gold spans covered: duplicate retrieved hits cannot count
    one gold span twice, while one broad hit may cover several distinct gold spans
    when it independently reaches the threshold for each.
    """
    if isinstance(k, bool) or not isinstance(k, int) or k <= 0:
        raise ValueError("k must be a positive integer.")

    if not isinstance(case_id, str) or not case_id.strip():
        raise ValueError("case_id must not be blank")
    if not golden_spans:
        raise ValueError("golden_spans must not be empty; exclude absent cases")

    identities = [span.identity for span in golden_spans]
    if len(identities) != len(set(identities)):
        raise ValueError("golden_spans must be unique")

    top_hits = retrieved_hits[:k]
    # One coverage pass feeds both recall and the first relevant rank, so the two
    # can never disagree about which pairs matched.
    relevant = [
        [span_coverage(golden, hit) >= COVERAGE_THRESHOLD for hit in top_hits]
        for golden in golden_spans
    ]

    matched_count = sum(any(row) for row in relevant)
    first_relevant_rank = next(
        (rank for rank in range(1, len(top_hits) + 1) if any(row[rank - 1] for row in relevant)),
        None,
    )
    reciprocal_rank = 1.0 / first_relevant_rank if first_relevant_rank is not None else 0.0
    return CaseScore(
        case_id=case_id,
        k=k,
        gold_span_count=len(golden_spans),
        matched_gold_count=matched_count,
        recall_at_k=matched_count / len(golden_spans),
        hit_at_k=float(bool(matched_count)),
        reciprocal_rank=reciprocal_rank,
        first_relevant_rank=first_relevant_rank,
    )


def _validated_scores(case_scores: Sequence[CaseScore]) -> tuple[CaseScore, ...]:
    """Return case scores sorted by id after uniqueness and single-k checks."""
    if not case_scores:
        raise ValueError("case_scores must not be empty")

    ordered = tuple(sorted(case_scores, key=lambda result: result.case_id))
    if len({result.case_id for result in ordered}) != len(ordered):
        raise ValueError("case_ids must be unique")
    if len({result.k for result in ordered}) != 1:
        raise ValueError("all case scores must use the same k")
    return ordered


def _macro(scores: tuple[CaseScore, ...], value: Callable[[CaseScore], float]) -> float:
    """Return the mean of one per-case metric over an already-validated suite."""
    return sum(value(result) for result in scores) / len(scores)


def score_suite(case_scores: Sequence[CaseScore]) -> SuiteScore:
    """Aggregate one nonempty, single-k suite in deterministic case-id order."""
    scores = _validated_scores(case_scores)
    return SuiteScore(
        k=scores[0].k,
        case_count=len(scores),
        recall_at_k=_macro(scores, lambda result: result.recall_at_k),
        hit_rate_at_k=_macro(scores, lambda result: result.hit_at_k),
        mrr=_macro(scores, lambda result: result.reciprocal_rank),
        cases=scores,
    )


@dataclass(frozen=True, slots=True)
class GroupScore:
    """One taxonomy group's label and the suite score of its positive cases.

    The metrics are held as the ``score_suite`` result rather than copied out of
    it, so a metric added to ``SuiteScore`` reaches every breakdown instead of
    being silently dropped by a field-by-field transcription.
    """

    group: str
    suite: SuiteScore


def _positive_case_index(cases: Sequence[GoldenCase]) -> dict[str, GoldenCase]:
    """Index golden cases while rejecting duplicate ids.

    Parameters
    ----------
    cases : Sequence[GoldenCase]
        Complete golden suite, including absent cases.

    Returns
    -------
    dict[str, GoldenCase]
        Case ids mapped to their unique cases.

    Raises
    ------
    ValueError
        If the suite repeats a case id.
    """
    index: dict[str, GoldenCase] = {}
    for case in cases:
        if case.id in index:
            raise ValueError(f"duplicate golden case id: {case.id}")
        index[case.id] = case
    return index


def _validated_pairs(
    cases: Sequence[GoldenCase],
    scores: Sequence[CaseScore],
) -> list[tuple[GoldenCase, CaseScore]]:
    """Pair every positive case with exactly one compatible score.

    Parameters
    ----------
    cases : Sequence[GoldenCase]
        Complete golden suite, including absent cases.
    scores : Sequence[CaseScore]
        Retrieval scores that must cover every positive case exactly once.

    Returns
    -------
    list[tuple[GoldenCase, CaseScore]]
        Score-order pairs used by taxonomy grouping.

    Raises
    ------
    ValueError
        If scores are empty, mix ``k`` values, repeat or miss a positive case,
        reference an unknown case, or score an absent case.

    Notes
    -----
    Rejecting partial coverage prevents a group average from silently excluding its
    hardest cases.
    """
    index = _positive_case_index(cases)
    if not scores:
        raise ValueError("scores must not be empty")
    if len({score.k for score in scores}) != 1:
        raise ValueError("all case scores must use the same k")

    pairs: list[tuple[GoldenCase, CaseScore]] = []
    scored_ids: set[str] = set()
    for score in scores:
        case = index.get(score.case_id)
        if case is None:
            raise ValueError(f"score references unknown golden case: {score.case_id}")
        if case.category == "absent":
            raise ValueError(f"absent case cannot carry a retrieval score: {score.case_id}")
        if score.case_id in scored_ids:
            raise ValueError(f"duplicate case score: {score.case_id}")
        scored_ids.add(score.case_id)
        pairs.append((case, score))

    unscored = [
        case.id for case in cases if case.category != "absent" and case.id not in scored_ids
    ]
    if unscored:
        raise ValueError(f"positive cases missing a score: {', '.join(sorted(unscored))}")
    return pairs


def group_scores_by_category(
    pairs: Sequence[tuple[GoldenCategory, CaseScore]],
) -> tuple[GroupScore, ...]:
    """Aggregate scored cases per golden category.

    Parameters
    ----------
    pairs : Sequence[tuple[GoldenCategory, CaseScore]]
        Each scored case's golden category and its retrieval score.

    Returns
    -------
    tuple[GroupScore, ...]
        Nonempty category aggregates in ``GoldenCategory`` declaration order.

    Notes
    -----
    ``score_suite`` remains the single implementation of macro averaging. The
    repeated scan is retained because the fixed taxonomy has at most five groups and
    a one-pass bucket benchmark saved only microseconds while increasing peak memory.
    """
    results: list[GroupScore] = []
    for group in get_args(GoldenCategory):
        members = [score for category, score in pairs if category == group]
        if members:
            results.append(GroupScore(group=group, suite=score_suite(members)))
    return tuple(results)


def breakdown_by_category(
    cases: Sequence[GoldenCase],
    scores: Sequence[CaseScore],
) -> tuple[GroupScore, ...]:
    """Group a complete scored suite by golden category.

    Parameters
    ----------
    cases : Sequence[GoldenCase]
        Complete golden suite.
    scores : Sequence[CaseScore]
        Complete positive-case retrieval scores.

    Returns
    -------
    tuple[GroupScore, ...]
        Nonempty category aggregates in ``GoldenCategory`` declaration order.

    Raises
    ------
    ValueError
        If case-score pairing is incomplete or inconsistent.
    """
    pairs = _validated_pairs(cases, scores)
    return group_scores_by_category([(case.category, score) for case, score in pairs])
