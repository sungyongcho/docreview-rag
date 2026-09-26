"""Command-line axis normalization and canonical budget-arm selection."""

import pytest

from app.evals.run import arguments, budget_arm_selection


def test_cli_defaults_to_the_isolated_deterministic_ten_arm_matrix():
    """Default the command line to the deterministic isolated experiment matrix."""
    args = arguments([])

    assert args.selection_id == "sec-evaluation"
    assert args.provider == "deterministic"
    assert args.target_tokens == [1024, 2048]
    assert args.strategies == ["lexical", "vector", "hybrid"]
    assert args.lexical_rankers == ["ts_rank_cd", "bm25"]
    assert args.budget_queries == 200
    assert not args.persist_results


@pytest.mark.parametrize(
    ("argv", "axis", "expected"),
    [
        (["--strategies", "vector", "lexical", "vector"], "strategies", ["lexical", "vector"]),
        (["--target-tokens", "2048", "1024", "2048"], "target_tokens", [1024, 2048]),
        (["--lexical-rankers", "bm25", "bm25"], "lexical_rankers", ["bm25"]),
    ],
    ids=["strategies", "target_tokens", "lexical_rankers"],
)
def test_every_matrix_axis_is_deduplicated_and_canonically_ordered(argv, axis, expected):
    """Deduplicate and canonically order each axis before any corpus is read."""
    assert getattr(arguments(argv), axis) == expected


def test_a_candidate_depth_below_k_is_rejected_by_the_parser():
    """Reject conflicting retrieval limits at parse time, not mid-run."""
    with pytest.raises(SystemExit):
        arguments(["-k", "10", "--candidate-k", "5"])


@pytest.mark.parametrize(
    ("strategies", "rankers", "expected"),
    [
        (["hybrid", "vector", "lexical"], ["ts_rank_cd", "bm25"], ("hybrid", "ts_rank_cd")),
        (["lexical", "vector"], ["bm25", "ts_rank_cd"], ("vector", None)),
        (["lexical"], ["bm25", "ts_rank_cd"], ("lexical", "ts_rank_cd")),
        (["lexical"], ["bm25"], ("lexical", "bm25")),
    ],
    ids=[
        "hybrid_is_deepest_whatever_the_typed_order",
        "vector_lane_names_no_ranker",
        "lexical_lane_takes_the_canonical_ranker",
        "lexical_lane_takes_the_only_ranker",
    ],
)
def test_the_budget_arm_is_the_deepest_lane_with_a_ranker_only_for_lexical_queries(
    strategies, rankers, expected
):
    """Pick the deepest requested lane and name its canonical ranker only when it runs one."""
    assert budget_arm_selection(strategies, rankers) == expected


def test_budget_arm_selection_rejects_an_empty_or_rankerless_axis():
    """Refuse to name a budget arm the requested matrix does not contain."""
    with pytest.raises(ValueError, match="at least one strategy"):
        budget_arm_selection([], ["bm25"])
    with pytest.raises(ValueError, match="requires a lexical ranker"):
        budget_arm_selection(["hybrid"], [])
