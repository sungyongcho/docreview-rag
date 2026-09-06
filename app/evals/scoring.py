"""Deterministic span-level scoring for retrieval evaluation suites."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from app.evals.types import GoldenSpan
from app.retrieval.types import ChunkHit

IOU_THRESHOLD: Final[float] = 0.05


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


def _span_identity(span: GoldenSpan) -> tuple[str, str, int, int]:
    """Return the exact source identity tuple for one golden span."""
    return (span.doc_id, span.source_sha256, span.start_char, span.end_char)


def span_iou(golden: GoldenSpan, hit: ChunkHit) -> float:
    """Return half-open span IoU after exact document-snapshot matching.

    Touching boundaries have zero overlap. A stale hit from another source snapshot
    is never relevant even if its document id and numeric offsets happen to match.
    """
    if golden.doc_id != hit.doc_id or golden.source_sha256 != hit.source_sha256:
        return 0.0

    # IoU = overlapping length / (answer length + chunk length - overlapping length)
    overlap = max(0, min(golden.end_char, hit.end_char) - max(golden.start_char, hit.start_char))

    if overlap == 0:
        return 0.0

    union = (golden.end_char - golden.start_char) + (hit.end_char - hit.start_char) - overlap
    return overlap / union


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
    Recall counts unique gold spans covered. Duplicate retrieved hits cannot
    count one gold span twice, while one broad hit may cover multiple distinct
    gold spans when it independently reaches the IoU threshold for each.
    """

    def _is_relavelent(golden: GoldenSpan, hit: ChunkHit) -> bool:
        """Return whether one hit clears the IoU relevance threshold."""
        return span_iou(golden, hit) >= IOU_THRESHOLD

    if isinstance(k, bool) or not isinstance(k, int) or k <= 0:
        raise ValueError("k must be a positive integer.")

    if not isinstance(case_id, str) or not case_id.strip():
        raise ValueError("case_id must not be blank")
    if not golden_spans:
        raise ValueError("golden_spans must not be empty; exclude absent cases")

    identities = [_span_identity(span) for span in golden_spans]
    if len(identities) != len(set(identities)):
        raise ValueError("golden_spans must be unique")

    top_hits = retrieved_hits[:k]
    matched_gold = {
        index
        for index, golden in enumerate(golden_spans)
        if any(_is_relavelent(golden, hit) for hit in top_hits)
    }

    first_relevant_rank = next(
        (
            rank
            for rank, hit in enumerate(top_hits, start=1)
            if any(_is_relavelent(golden, hit) for golden in golden_spans)
        ),
        None,
    )

    matched_count = len(matched_gold)
    recall = matched_count / len(golden_spans)
    hit_at_k = float(bool(matched_count))
    reciprocal_rank = 1.0 / first_relevant_rank if first_relevant_rank is not None else 0.0
    return CaseScore(
        case_id=case_id,
        k=k,
        gold_span_count=len(golden_spans),
        matched_gold_count=matched_count,
        recall_at_k=recall,
        hit_at_k=hit_at_k,
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


def recall_at_k(case_scores: Sequence[CaseScore]) -> float:
    """Return macro recall across a nonempty suite of positive cases."""
    scores = _validated_scores(case_scores)
    return sum(result.recall_at_k for result in scores) / len(scores)


def hit_rate_at_k(case_scores: Sequence[CaseScore]) -> float:
    """Return the fraction of positive cases with at least one relevant top-k hit."""
    scores = _validated_scores(case_scores)
    return sum(result.hit_at_k for result in scores) / len(scores)


def mrr(case_scores: Sequence[CaseScore]) -> float:
    """Return mean reciprocal rank of the first relevant top-k hit per case."""
    scores = _validated_scores(case_scores)
    return sum(result.reciprocal_rank for result in scores) / len(scores)


def mean_reciprocal_rank(case_scores: Sequence[CaseScore]) -> float:
    """Return MRR using its unabbreviated public name."""
    return mrr(case_scores)


def score_suite(case_scores: Sequence[CaseScore]) -> SuiteScore:
    """Aggregate one nonempty, single-k suite in deterministic case-id order."""
    scores = _validated_scores(case_scores)
    return SuiteScore(
        k=scores[0].k,
        case_count=len(scores),
        recall_at_k=sum(result.recall_at_k for result in scores) / len(scores),
        hit_rate_at_k=sum(result.hit_at_k for result in scores) / len(scores),
        mrr=sum(result.reciprocal_rank for result in scores) / len(scores),
        cases=scores,
    )
