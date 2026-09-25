"""Group one complete scored golden suite by its declared taxonomy.

This module performs no retrieval or I/O. It validates a complete case-to-score
mapping before delegating every aggregate calculation to ``score_suite``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import get_args

from app.evals.scoring import CaseScore, SuiteScore, score_suite
from app.evals.types import GoldenCase, GoldenCategory


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

    Notes
    -----
    ``score_suite`` remains the single implementation of macro averaging. The
    repeated scan is retained because the fixed taxonomy has at most five groups and
    a one-pass bucket benchmark saved only microseconds while increasing peak memory.
    """
    pairs = _validated_pairs(cases, scores)
    results: list[GroupScore] = []
    for group in get_args(GoldenCategory):
        members = [score for case, score in pairs if case.category == group]
        if members:
            results.append(GroupScore(group=group, suite=score_suite(members)))
    return tuple(results)
