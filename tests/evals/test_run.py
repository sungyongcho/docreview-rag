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


def test_cli_can_narrow_the_ranker_axis():
    """Narrow the ranker axis from the command line."""
    args = arguments(["--lexical-rankers", "bm25"])

    assert args.lexical_rankers == ["bm25"]


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["--strategies", "hybrid", "hybrid"], ["hybrid"]),
        (["--strategies", "hybrid", "lexical"], ["lexical", "hybrid"]),
        (["--strategies", "vector", "lexical", "vector"], ["lexical", "vector"]),
    ],
)
def test_repeated_or_reordered_axes_normalize_to_the_canonical_matrix(argv, expected):
    """Deduplicate and canonically order each axis before any corpus is read."""
    assert arguments(argv).strategies == expected


def test_duplicate_chunk_targets_and_rankers_normalize_the_same_way():
    """Apply the same normalization to every matrix axis, not only to the rankers."""
    args = arguments(
        ["--target-tokens", "2048", "1024", "2048", "--lexical-rankers", "bm25", "bm25"]
    )

    assert args.target_tokens == [1024, 2048]
    assert args.lexical_rankers == ["bm25"]


def test_a_candidate_depth_below_k_is_rejected_by_the_parser():
    """Reject conflicting retrieval limits at parse time, not mid-run."""
    with pytest.raises(SystemExit):
        arguments(["-k", "10", "--candidate-k", "5"])


@pytest.mark.parametrize(
    "strategies",
    [
        ["lexical", "vector", "hybrid"],
        ["hybrid", "vector", "lexical"],
        ["vector", "hybrid"],
    ],
)
def test_the_budget_arm_ignores_the_order_the_axes_were_typed(strategies):
    """Pick the deepest retrieval path, so the same matrix always reports the same budget."""
    assert budget_arm_selection(strategies, ["ts_rank_cd", "bm25"]) == ("hybrid", "ts_rank_cd")


@pytest.mark.parametrize(
    ("strategies", "rankers", "expected"),
    [
        (["lexical", "vector"], ["bm25", "ts_rank_cd"], ("vector", None)),
        (["vector"], ["ts_rank_cd"], ("vector", None)),
        (["lexical"], ["bm25", "ts_rank_cd"], ("lexical", "ts_rank_cd")),
        (["lexical"], ["bm25"], ("lexical", "bm25")),
    ],
)
def test_the_budget_arm_names_a_ranker_only_when_it_runs_a_lexical_query(
    strategies, rankers, expected
):
    """Leave the budget ranker unset for a vector lane and canonical otherwise."""
    assert budget_arm_selection(strategies, rankers) == expected


def test_budget_arm_selection_rejects_an_empty_or_rankerless_axis():
    """Refuse to name a budget arm the requested matrix does not contain."""
    with pytest.raises(ValueError, match="at least one strategy"):
        budget_arm_selection([], ["bm25"])
    with pytest.raises(ValueError, match="requires a lexical ranker"):
        budget_arm_selection(["hybrid"], [])


def test_cli_rejects_the_removed_character_target_flag():
    """Require the token-based option instead of silently accepting old units."""
    with pytest.raises(SystemExit):
        arguments(["--target-text-chars", "1200"])
