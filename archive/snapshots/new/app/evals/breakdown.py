"""Taxonomy-grouped retrieval metrics over one scored golden suite."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import get_args

from app.evals.scoring import CaseScore, score_suite
from app.evals.types import GoldenCase, GoldenCategory, GoldenFacet


@dataclass(frozen=True, slots=True)
class GroupScore:
    """Macro-averaged retrieval metrics for one taxonomy group of positive cases."""

    group: str
    k: int
    case_count: int
    recall_at_k: float
    hit_rate_at_k: float
    mrr: float


def _positive_case_index(cases: Sequence[GoldenCase]) -> dict[str, GoldenCase]:
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
    """Pair every score with its positive case and reject partial or stray scoring.

    A breakdown over a subset would silently misrepresent a group, so every positive
    case must carry exactly one score, an absent case must carry none, and every
    score must point at a known case.
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


def _grouped(
    pairs: Sequence[tuple[GoldenCase, CaseScore]],
    groups: Sequence[str],
    key: Callable[[GoldenCase], str],
) -> tuple[GroupScore, ...]:
    results: list[GroupScore] = []
    for group in groups:
        members = [score for case, score in pairs if key(case) == group]
        if not members:
            continue
        suite = score_suite(members)
        results.append(
            GroupScore(
                group=group,
                k=suite.k,
                case_count=suite.case_count,
                recall_at_k=suite.recall_at_k,
                hit_rate_at_k=suite.hit_rate_at_k,
                mrr=suite.mrr,
            )
        )
    return tuple(results)


def breakdown_by_category(
    cases: Sequence[GoldenCase],
    scores: Sequence[CaseScore],
) -> tuple[GroupScore, ...]:
    """Group suite metrics by golden category in declaration order."""
    pairs = _validated_pairs(cases, scores)
    return _grouped(pairs, get_args(GoldenCategory), lambda case: case.category)


def breakdown_by_facet(
    cases: Sequence[GoldenCase],
    scores: Sequence[CaseScore],
) -> tuple[GroupScore, ...]:
    """Group suite metrics by golden facet in declaration order."""
    pairs = _validated_pairs(cases, scores)
    return _grouped(pairs, get_args(GoldenFacet), lambda case: case.facet)


def breakdown_markdown(dimension: str, groups: Sequence[GroupScore]) -> str:
    """Render one taxonomy breakdown as a compact comparison table."""
    if not dimension.strip():
        raise ValueError("dimension must not be blank")
    if not groups:
        raise ValueError("groups must not be empty")
    lines = [
        f"| {dimension} | Cases | Recall@k | Hit rate@k | MRR |",
        "|---|---:|---:|---:|---:|",
    ]
    for group in groups:
        lines.append(
            f"| {group.group} | {group.case_count} | {group.recall_at_k:.6f} | "
            f"{group.hit_rate_at_k:.6f} | {group.mrr:.6f} |"
        )
    return "\n".join(lines)
