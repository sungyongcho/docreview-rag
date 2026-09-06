"""L2: half-open span matching and retrieval metric correctness."""

import importlib
import os

import pytest

from app.evals.types import GoldenSpan
from app.retrieval.types import ChunkHit
from tests.support import need

SCORING_MODULE_NAME = os.getenv("EVAL_SCORING_MODULE", "app.evals.scoring")
S = importlib.import_module(SCORING_MODULE_NAME)
SOURCE_SHA256 = "a" * 64


def golden(**changes) -> GoldenSpan:
    values = {
        "doc_id": "NVDA-FY2024",
        "source_sha256": SOURCE_SHA256,
        "start_char": 100,
        "end_char": 200,
    }
    values.update(changes)
    return GoldenSpan(**values)


def hit(**changes) -> ChunkHit:
    values = {
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


def test_exact_half_open_span_has_unit_iou():
    need(S, "span_iou", "IOU_THRESHOLD")
    assert S.IOU_THRESHOLD == 0.05
    assert S.span_iou(golden(), hit()) == 1.0


def test_partial_overlap_uses_union_and_includes_the_threshold():
    need(S, "span_iou", "score_case")
    boundary_hit = hit(start_char=190, end_char=300)
    below_threshold = hit(chunk_id=2, start_char=195, end_char=300)

    assert S.span_iou(golden(), boundary_hit) == pytest.approx(0.05)
    assert S.span_iou(golden(), below_threshold) < S.IOU_THRESHOLD
    assert S.score_case("q1", [golden()], [boundary_hit], 1).hit_at_k == 1.0
    assert S.score_case("q1", [golden()], [below_threshold], 1).hit_at_k == 0.0


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
    need(S, "span_iou", "score_case")
    assert S.span_iou(golden(), candidate) == 0.0
    assert S.score_case("q1", [golden()], [candidate], 1).recall_at_k == 0.0


def test_duplicate_hits_do_not_double_count_one_gold_span():
    need(S, "score_case")
    duplicate_hits = [hit(chunk_id=1), hit(chunk_id=2)]

    result = S.score_case("q1", [golden()], duplicate_hits, 2)

    assert result.gold_span_count == 1
    assert result.matched_gold_count == 1
    assert result.recall_at_k == 1.0
    assert result.hit_at_k == 1.0
    assert result.first_relevant_rank == 1
    assert result.reciprocal_rank == 1.0


def test_multiple_gold_spans_are_counted_once_each():
    need(S, "score_case")
    golds = [golden(), golden(start_char=400, end_char=500)]
    hits = [
        hit(chunk_id=1),
        hit(chunk_id=2),
        hit(chunk_id=3, start_char=400, end_char=500),
    ]

    top_two = S.score_case("q1", golds, hits, 2)
    top_three = S.score_case("q1", golds, hits, 3)

    assert top_two.matched_gold_count == 1
    assert top_two.recall_at_k == 0.5
    assert top_three.matched_gold_count == 2
    assert top_three.recall_at_k == 1.0


def test_one_broad_chunk_can_cover_multiple_distinct_gold_spans():
    need(S, "score_case")
    golds = [golden(), golden(start_char=400, end_char=500)]
    broad = hit(start_char=100, end_char=500)

    result = S.score_case("q1", golds, [broad], 1)

    assert result.matched_gold_count == 2
    assert result.recall_at_k == 1.0


def test_no_hit_has_zero_metrics_and_no_rank():
    need(S, "score_case")
    result = S.score_case(
        "q1",
        [golden()],
        [hit(start_char=300, end_char=400)],
        1,
    )

    assert result.matched_gold_count == 0
    assert result.recall_at_k == 0.0
    assert result.hit_at_k == 0.0
    assert result.first_relevant_rank is None
    assert result.reciprocal_rank == 0.0


def test_empty_retrieval_list_is_a_no_hit():
    need(S, "score_case")
    result = S.score_case("q1", [golden()], [], 3)

    assert result.recall_at_k == 0.0
    assert result.hit_at_k == 0.0
    assert result.first_relevant_rank is None
    assert result.reciprocal_rank == 0.0


def test_first_relevant_rank_is_limited_to_top_k():
    need(S, "score_case")
    hits = [
        hit(chunk_id=1, start_char=300, end_char=400),
        hit(chunk_id=2),
    ]

    top_one = S.score_case("q1", [golden()], hits, 1)
    top_two = S.score_case("q1", [golden()], hits, 2)

    assert top_one.first_relevant_rank is None
    assert top_one.reciprocal_rank == 0.0
    assert top_two.first_relevant_rank == 2
    assert top_two.reciprocal_rank == 0.5


def test_rechunked_and_reidentified_hits_preserve_scores():
    need(S, "score_case")
    config_a = [hit(chunk_id=11, start_char=90, end_char=210)]
    config_b = [
        hit(chunk_id=903, start_char=80, end_char=160),
        hit(chunk_id=17, start_char=160, end_char=240),
    ]

    score_a = S.score_case("q1", [golden()], config_a, 2)
    score_b = S.score_case("q1", [golden()], config_b, 2)

    assert score_a.recall_at_k == score_b.recall_at_k == 1.0
    assert score_a.hit_at_k == score_b.hit_at_k == 1.0
    assert score_a.reciprocal_rank == score_b.reciprocal_rank == 1.0


def test_suite_metrics_are_macro_averages_with_deterministic_case_order():
    need(
        S,
        "score_case",
        "score_suite",
        "recall_at_k",
        "hit_rate_at_k",
        "mrr",
        "mean_reciprocal_rank",
    )
    full = S.score_case("b", [golden()], [hit()], 2)
    partial = S.score_case(
        "a",
        [golden(), golden(start_char=400, end_char=500)],
        [
            hit(start_char=300, end_char=350),
            hit(chunk_id=2, start_char=400, end_char=500),
        ],
        2,
    )
    missed = S.score_case(
        "c",
        [golden()],
        [hit(start_char=300, end_char=400)],
        2,
    )
    results = [full, partial, missed]

    suite = S.score_suite(results)

    assert S.recall_at_k(results) == pytest.approx(0.5)
    assert S.hit_rate_at_k(results) == pytest.approx(2 / 3)
    assert S.mrr(results) == pytest.approx(0.5)
    assert S.mean_reciprocal_rank(results) == pytest.approx(0.5)
    assert suite.recall_at_k == pytest.approx(0.5)
    assert suite.hit_rate_at_k == pytest.approx(2 / 3)
    assert suite.mrr == pytest.approx(0.5)
    assert suite.k == 2
    assert suite.case_count == 3
    assert [case.case_id for case in suite.cases] == ["a", "b", "c"]


@pytest.mark.parametrize("k", [0, -1, True, 1.0, "1"])
def test_k_must_be_a_positive_integer(k):
    need(S, "score_case")
    with pytest.raises(ValueError, match="positive integer"):
        S.score_case("q1", [golden()], [hit()], k)


def test_case_validation_rejects_blank_ids_empty_or_duplicate_gold():
    need(S, "score_case")
    with pytest.raises(ValueError, match="case_id"):
        S.score_case(" ", [golden()], [hit()], 1)
    with pytest.raises(ValueError, match="exclude absent"):
        S.score_case("q1", [], [hit()], 1)
    with pytest.raises(ValueError, match="must be unique"):
        S.score_case("q1", [golden(), golden()], [hit()], 1)


@pytest.mark.parametrize(
    "metric",
    [
        "score_suite",
        "recall_at_k",
        "hit_rate_at_k",
        "mrr",
        "mean_reciprocal_rank",
    ],
)
def test_empty_suite_is_rejected(metric):
    need(S, metric)
    with pytest.raises(ValueError, match="must not be empty"):
        getattr(S, metric)([])


def test_suite_rejects_duplicate_case_ids_or_mixed_k():
    need(S, "score_case", "score_suite")
    first = S.score_case("q1", [golden()], [hit()], 1)
    duplicate = S.score_case("q1", [golden()], [hit()], 1)
    other_k = S.score_case("q2", [golden()], [hit()], 2)

    with pytest.raises(ValueError, match="case_ids must be unique"):
        S.score_suite([first, duplicate])
    with pytest.raises(ValueError, match="same k"):
        S.score_suite([first, other_k])
