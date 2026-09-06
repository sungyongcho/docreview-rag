"""Gold-span coverage matching and macro retrieval metric correctness."""

from typing import Any

import pytest

from app.evals.scoring import (
    COVERAGE_THRESHOLD,
    hit_rate_at_k,
    mrr,
    recall_at_k,
    score_case,
    score_suite,
    span_coverage,
)
from app.evals.types import GoldenSpan
from app.retrieval.types import ChunkHit

SOURCE_SHA256 = "a" * 64


def golden(**changes: Any) -> GoldenSpan:
    """Build a gold answer span with optional replacements."""
    values: dict[str, Any] = {
        "doc_id": "NVDA-FY2024",
        "source_sha256": SOURCE_SHA256,
        "start_char": 100,
        "end_char": 200,
    }
    values.update(changes)
    return GoldenSpan(**values)


def hit(**changes: Any) -> ChunkHit:
    """Build a retrieved hit that exactly covers the default gold span."""
    values: dict[str, Any] = {
        "chunk_id": 1,
        "doc_id": "NVDA-FY2024",
        "item": "7",
        "kind": "text",
        "citation": "NVDA FY2024 · Item 7",
        "start_char": 100,
        "end_char": 200,
        "source_sha256": SOURCE_SHA256,
        "body": "Evidence.",
        "context_header": "NVDA FY2024 · Item 7",
        "index_text": "NVDA FY2024 · Item 7\n\nEvidence.",
        "score": 1.0,
    }
    values.update(changes)
    return ChunkHit(**values)


def test_an_exactly_coincident_span_is_fully_covered():
    """Score an exactly coincident span and hit as complete coverage."""
    assert COVERAGE_THRESHOLD == 0.5
    assert span_coverage(golden(), hit()) == 1.0


def test_partial_coverage_includes_the_threshold_and_rejects_the_step_below():
    """Count a hit covering exactly half the gold span and reject the one below it."""
    boundary_hit = hit(start_char=150, end_char=300)
    below_threshold = hit(chunk_id=2, start_char=151, end_char=300)

    assert span_coverage(golden(), boundary_hit) == pytest.approx(0.5)
    assert span_coverage(golden(), below_threshold) < COVERAGE_THRESHOLD
    assert score_case("q1", [golden()], [boundary_hit], 1).hit_at_k == 1.0
    assert score_case("q1", [golden()], [below_threshold], 1).hit_at_k == 0.0


def test_a_chunk_far_wider_than_the_gold_span_is_still_relevant():
    """Score a containing hit on its own merits rather than on how wide the chunk is."""
    # A real filing chunk's source span reaches ~11,000 raw characters at p90, against
    # a median gold span of ~450. Dividing by the union made that correct hit a miss.
    wide = hit(start_char=0, end_char=12_000)

    assert span_coverage(golden(), wide) == 1.0
    assert score_case("q1", [golden()], [wide], 1).hit_at_k == 1.0


@pytest.mark.parametrize("cut", [101, 150, 199])
def test_one_chunk_boundary_inside_a_gold_span_never_makes_it_unscoreable(cut):
    """Keep a split gold span reachable, because one side always holds at least half."""
    fragments = [
        hit(chunk_id=1, start_char=0, end_char=cut),
        hit(chunk_id=2, start_char=cut, end_char=400),
    ]

    best = max(span_coverage(golden(), fragment) for fragment in fragments)

    assert best >= COVERAGE_THRESHOLD
    assert score_case("q1", [golden()], fragments, 2).hit_at_k == 1.0


@pytest.mark.parametrize(
    "candidate",
    [
        hit(start_char=200, end_char=300),
        hit(start_char=0, end_char=100),
        hit(doc_id="AMD-FY2024"),
        hit(source_sha256="b" * 64),
    ],
)
def test_disjoint_touching_or_wrong_snapshot_spans_never_match(candidate):
    """Reject touching, disjoint, other-document, and stale-snapshot hits."""
    assert span_coverage(golden(), candidate) == 0.0
    assert score_case("q1", [golden()], [candidate], 1).recall_at_k == 0.0


def test_duplicate_hits_do_not_double_count_one_gold_span():
    """Count one gold span once even when several hits cover it."""
    duplicate_hits = [hit(chunk_id=1), hit(chunk_id=2)]

    result = score_case("q1", [golden()], duplicate_hits, 2)

    assert result.gold_span_count == 1
    assert result.matched_gold_count == 1
    assert result.recall_at_k == 1.0
    assert result.hit_at_k == 1.0
    assert result.first_relevant_rank == 1
    assert result.reciprocal_rank == 1.0


def test_multiple_gold_spans_are_counted_once_each():
    """Grow recall only when the cutoff admits a hit for another gold span."""
    golds = [golden(), golden(start_char=400, end_char=500)]
    hits = [
        hit(chunk_id=1),
        hit(chunk_id=2),
        hit(chunk_id=3, start_char=400, end_char=500),
    ]

    top_two = score_case("q1", golds, hits, 2)
    top_three = score_case("q1", golds, hits, 3)

    assert top_two.matched_gold_count == 1
    assert top_two.recall_at_k == 0.5
    assert top_three.matched_gold_count == 2
    assert top_three.recall_at_k == 1.0


def test_one_broad_chunk_can_cover_multiple_distinct_gold_spans():
    """Credit one wide hit for every gold span it independently covers."""
    golds = [golden(), golden(start_char=400, end_char=500)]
    broad = hit(start_char=100, end_char=500)

    result = score_case("q1", golds, [broad], 1)

    assert result.matched_gold_count == 2
    assert result.recall_at_k == 1.0


def test_no_hit_has_zero_metrics_and_no_rank():
    """Report zero metrics and no rank when nothing relevant is retrieved."""
    result = score_case("q1", [golden()], [hit(start_char=300, end_char=400)], 1)

    assert result.matched_gold_count == 0
    assert result.recall_at_k == 0.0
    assert result.hit_at_k == 0.0
    assert result.first_relevant_rank is None
    assert result.reciprocal_rank == 0.0


def test_empty_retrieval_list_is_a_no_hit():
    """Treat an empty ranking as a scored miss rather than an error."""
    result = score_case("q1", [golden()], [], 3)

    assert result.recall_at_k == 0.0
    assert result.hit_at_k == 0.0
    assert result.first_relevant_rank is None
    assert result.reciprocal_rank == 0.0


def test_first_relevant_rank_is_limited_to_top_k():
    """Ignore a relevant hit that falls outside the cutoff."""
    hits = [hit(chunk_id=1, start_char=300, end_char=400), hit(chunk_id=2)]

    top_one = score_case("q1", [golden()], hits, 1)
    top_two = score_case("q1", [golden()], hits, 2)

    assert top_one.first_relevant_rank is None
    assert top_one.reciprocal_rank == 0.0
    assert top_two.first_relevant_rank == 2
    assert top_two.reciprocal_rank == 0.5


def test_rechunked_and_reidentified_hits_preserve_scores():
    """Score the same evidence identically when it is rechunked at any width."""
    tight = [hit(chunk_id=11, start_char=90, end_char=210)]
    split = [
        hit(chunk_id=903, start_char=80, end_char=160),
        hit(chunk_id=17, start_char=160, end_char=240),
    ]
    document_wide = [hit(chunk_id=5, start_char=0, end_char=60_000)]

    scores = [score_case("q1", [golden()], config, 2) for config in (tight, split, document_wide)]

    assert {score.recall_at_k for score in scores} == {1.0}
    assert {score.hit_at_k for score in scores} == {1.0}
    assert {score.reciprocal_rank for score in scores} == {1.0}


def test_suite_metrics_are_macro_averages_with_deterministic_case_order():
    """Macro-average each metric and order cases by id regardless of input order."""
    full = score_case("b", [golden()], [hit()], 2)
    partial = score_case(
        "a",
        [golden(), golden(start_char=400, end_char=500)],
        [
            hit(start_char=300, end_char=350),
            hit(chunk_id=2, start_char=400, end_char=500),
        ],
        2,
    )
    missed = score_case("c", [golden()], [hit(start_char=300, end_char=400)], 2)
    results = [full, partial, missed]

    suite = score_suite(results)

    assert recall_at_k(results) == pytest.approx(0.5)
    assert hit_rate_at_k(results) == pytest.approx(2 / 3)
    assert mrr(results) == pytest.approx(0.5)
    assert suite.recall_at_k == pytest.approx(0.5)
    assert suite.hit_rate_at_k == pytest.approx(2 / 3)
    assert suite.mrr == pytest.approx(0.5)
    assert suite.k == 2
    assert suite.case_count == 3
    assert [case.case_id for case in suite.cases] == ["a", "b", "c"]
    assert suite.parameters == {"k": 2, "coverage_threshold": COVERAGE_THRESHOLD}


@pytest.mark.parametrize("k", [0, -1, True, 1.0, "1"])
def test_k_must_be_a_positive_integer(k):
    """Reject a nonpositive, boolean, or non-integer cutoff."""
    with pytest.raises(ValueError, match="positive integer"):
        score_case("q1", [golden()], [hit()], k)


def test_case_validation_rejects_blank_ids_empty_or_duplicate_gold():
    """Reject a blank case id, an absent case, and duplicate gold spans."""
    with pytest.raises(ValueError, match="case_id"):
        score_case(" ", [golden()], [hit()], 1)
    with pytest.raises(ValueError, match="exclude absent"):
        score_case("q1", [], [hit()], 1)
    with pytest.raises(ValueError, match="must be unique"):
        score_case("q1", [golden(), golden()], [hit()], 1)


@pytest.mark.parametrize("aggregate", [score_suite, recall_at_k, hit_rate_at_k, mrr])
def test_empty_suite_is_rejected(aggregate):
    """Refuse to average an empty suite instead of returning zero."""
    with pytest.raises(ValueError, match="must not be empty"):
        aggregate([])


def test_suite_rejects_duplicate_case_ids_or_mixed_k():
    """Reject a suite with repeated case ids or more than one cutoff."""
    first = score_case("q1", [golden()], [hit()], 1)
    duplicate = score_case("q1", [golden()], [hit()], 1)
    other_k = score_case("q2", [golden()], [hit()], 2)

    with pytest.raises(ValueError, match="case_ids must be unique"):
        score_suite([first, duplicate])
    with pytest.raises(ValueError, match="same k"):
        score_suite([first, other_k])
