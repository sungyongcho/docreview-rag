"""M8.4: the ko/en parity ratio, its fail-closed zero branch, and the gate floor."""

from datetime import UTC, datetime
import importlib
import os

import pytest

from app.evals.scoring import CaseScore, SuiteScore
from app.evals.types import GoldenCase, GoldenSpan
from tests.support import need

RUNNER_MODULE_NAME = os.getenv("EVAL_RUNNER_MODULE", "app.evals.retrieval_eval")
R = importlib.import_module(RUNNER_MODULE_NAME)
SOURCE_SHA256 = "a" * 64
CASE_IDS = ("m3c-01", "m3c-02")
RECORDED_AT = datetime(2026, 1, 1, tzinfo=UTC)


def golden(case_id: str) -> GoldenCase:
    """Build one positive golden case for a synthetic evaluation."""
    return GoldenCase(
        id=case_id,
        question=f"Question {case_id}?",
        category="simple_lookup",
        facet="factual",
        tags=(),
        answers=(
            GoldenSpan(
                doc_id="AMD-FY2019",
                source_sha256=SOURCE_SHA256,
                start_char=100,
                end_char=200,
            ),
        ),
        expected_label="SUPPORTED",
        reference_answer="Supported evidence.",
        note="Parity fixture.",
        curation_status="agent-curated",
        approval_status="pending-author-approval",
        human_verified=False,
    )


def case_score(case_id: str, recall: float) -> CaseScore:
    """Build one per-case score consistent with a chosen recall."""
    return CaseScore(
        case_id=case_id,
        k=5,
        gold_span_count=1,
        matched_gold_count=int(recall),
        recall_at_k=recall,
        hit_at_k=recall,
        reciprocal_rank=recall,
        first_relevant_rank=1 if recall else None,
    )


def config(language: str, **changes) -> dict:
    """Build one canonical arm config differing only in query language."""
    payload = {
        "name": f"xling-deterministic-hybrid-ts-rank-cd-{language}",
        "chunking": {"target_text_chars": 1200},
        "retrieval": {"strategy": "hybrid", "lexical_ranker": "ts_rank_cd", "reranker": None},
        "embedding": {"provider": "deterministic", "model": "token-hash-384", "dimensions": 384},
        "query": {"language": language, "handling": "direct", "translator": None},
    }
    payload.update(changes)
    return payload


def evaluation(
    language: str,
    *,
    recall: float,
    hit_rate: float,
    mrr: float,
    case_ids: tuple[str, ...] = CASE_IDS,
    suite: str = "m8-crosslingual-v1",
    k: int = 5,
    **config_changes,
) -> object:
    """Build one artifact-shaped evaluation with chosen aggregate metrics."""
    cases = tuple(
        R.CaseEvaluation(
            golden=golden(case_id),
            latency_ms=1.0,
            hits=(),
            score=case_score(case_id, recall),
        )
        for case_id in case_ids
    )
    return R.RetrievalEvaluation(
        suite=suite,
        recorded_at=RECORDED_AT,
        config=config(language, **config_changes),
        provenance=R.GoldenProvenance(
            total_cases=len(case_ids),
            scored_positive_cases=len(case_ids),
            unscored_absent_cases=0,
            curation_status="agent-curated",
            approval_status="pending-author-approval",
            human_verified=False,
        ),
        score=SuiteScore(
            k=k,
            case_count=len(case_ids),
            recall_at_k=recall,
            hit_rate_at_k=hit_rate,
            mrr=mrr,
            cases=tuple(case_score(case_id, recall) for case_id in case_ids),
        ),
        latency=R.LatencySummary(
            query_count=len(case_ids),
            total_ms=2.0,
            mean_ms=1.0,
            p50_ms=1.0,
            p95_ms=1.0,
            max_ms=1.0,
        ),
        cases=cases,
    )


def test_assess_parity_reports_delta_and_ratio_for_every_gated_metric(PAR):
    need(PAR, "assess_parity")
    english = evaluation("en", recall=0.8, hit_rate=1.0, mrr=0.5)
    korean = evaluation("ko", recall=0.4, hit_rate=0.5, mrr=0.25)

    assessment = PAR.assess_parity(english, korean)

    assert {result.metric for result in assessment.metrics} == {
        "recall_at_k",
        "hit_rate_at_k",
        "mrr",
    }
    recall = assessment.metric("recall_at_k")
    assert recall.en == pytest.approx(0.8)
    assert recall.ko == pytest.approx(0.4)
    assert recall.delta == pytest.approx(0.4)
    assert recall.ratio == pytest.approx(0.5)
    assert assessment.recall_ratio == pytest.approx(0.5)
    assert assessment.metric("mrr").ratio == pytest.approx(0.5)
    assert not assessment.passed
    assert "below the floor" in assessment.failures[0]
    assert assessment.suite == "m8-crosslingual-v1"
    assert assessment.k == 5
    assert assessment.case_count == 2


def test_assess_parity_fails_closed_when_the_english_slice_scored_zero(PAR):
    need(PAR, "assess_parity")
    english = evaluation("en", recall=0.0, hit_rate=0.0, mrr=0.0)
    korean = evaluation("ko", recall=0.0, hit_rate=0.0, mrr=0.0)

    assessment = PAR.assess_parity(english, korean)

    # 0/0 would read as perfect agreement between two dead arms.
    assert assessment.recall_ratio is None
    assert not assessment.passed
    assert "undefined" in assessment.failures[0]


def test_the_parity_floor_is_inclusive_at_its_boundary(PAR):
    need(PAR, "assess_parity", "DEFAULT_MIN_RECALL_RATIO")
    floor = PAR.DEFAULT_MIN_RECALL_RATIO
    english = evaluation("en", recall=1.0, hit_rate=1.0, mrr=1.0)

    exact = PAR.assess_parity(english, evaluation("ko", recall=floor, hit_rate=1.0, mrr=1.0))
    below = PAR.assess_parity(english, evaluation("ko", recall=floor - 0.01, hit_rate=1.0, mrr=1.0))
    above = PAR.assess_parity(english, evaluation("ko", recall=1.0, hit_rate=1.0, mrr=1.0))

    assert exact.passed
    assert not below.passed
    assert above.passed
    assert above.recall_ratio == pytest.approx(1.0)


@pytest.mark.parametrize(
    "english, korean, message",
    [
        (
            evaluation("en", recall=1.0, hit_rate=1.0, mrr=1.0, suite="other"),
            evaluation("ko", recall=1.0, hit_rate=1.0, mrr=1.0),
            "one suite",
        ),
        (
            evaluation("en", recall=1.0, hit_rate=1.0, mrr=1.0, k=5),
            evaluation("ko", recall=1.0, hit_rate=1.0, mrr=1.0, k=10),
            "same k",
        ),
        (
            evaluation("en", recall=1.0, hit_rate=1.0, mrr=1.0),
            evaluation("ko", recall=1.0, hit_rate=1.0, mrr=1.0, case_ids=("m3c-01", "m3c-03")),
            "same golden cases",
        ),
        (
            evaluation("en", recall=1.0, hit_rate=1.0, mrr=1.0),
            evaluation(
                "ko",
                recall=1.0,
                hit_rate=1.0,
                mrr=1.0,
                embedding={"provider": "sbert", "model": "multi", "dimensions": 384},
            ),
            "differ only in query language",
        ),
        (
            evaluation("ko", recall=1.0, hit_rate=1.0, mrr=1.0),
            evaluation("ko", recall=1.0, hit_rate=1.0, mrr=1.0),
            "expected a en evaluation",
        ),
    ],
)
def test_assess_parity_rejects_pairs_that_are_not_comparable(PAR, english, korean, message):
    need(PAR, "assess_parity")
    with pytest.raises(ValueError, match=message):
        PAR.assess_parity(english, korean)


def test_assess_parity_validates_its_own_inputs_and_floor(PAR):
    need(PAR, "assess_parity")
    english = evaluation("en", recall=1.0, hit_rate=1.0, mrr=1.0)
    korean = evaluation("ko", recall=1.0, hit_rate=1.0, mrr=1.0)

    with pytest.raises(ValueError, match=r"\(0, 1\]"):
        PAR.assess_parity(english, korean, min_recall_ratio=0.0)
    with pytest.raises(ValueError, match=r"\(0, 1\]"):
        PAR.assess_parity(english, korean, min_recall_ratio=1.5)
    with pytest.raises(TypeError, match="RetrievalEvaluation"):
        PAR.assess_parity(object(), korean)


def test_language_regression_allows_more_than_one_flipped_case(PAR):
    need(PAR, "language_regression", "PARITY_REGRESSION_TOLERANCE")
    assert PAR.PARITY_REGRESSION_TOLERANCE > 1 / 24

    baseline = {"recall_at_k": 0.80, "hit_rate_at_k": 0.80, "mrr": 0.80}
    single_case = {"recall_at_k": 0.80 - 1 / 24, "hit_rate_at_k": 0.80, "mrr": 0.80}
    collapse = {"recall_at_k": 0.60, "hit_rate_at_k": 0.80, "mrr": 0.80}

    assert PAR.language_regression(baseline, single_case).passed
    assert not PAR.language_regression(baseline, collapse).passed
    assert PAR.language_regression(baseline, collapse).regressed_metrics == ("recall_at_k",)


def test_parity_markdown_renders_the_verdict_and_the_undefined_ratio(PAR):
    need(PAR, "assess_parity", "parity_markdown")
    failing = PAR.assess_parity(
        evaluation("en", recall=0.0, hit_rate=0.0, mrr=0.0),
        evaluation("ko", recall=0.0, hit_rate=0.0, mrr=0.0),
    )
    passing = PAR.assess_parity(
        evaluation("en", recall=1.0, hit_rate=1.0, mrr=1.0),
        evaluation("ko", recall=1.0, hit_rate=1.0, mrr=1.0),
    )

    failed_table = PAR.parity_markdown(failing)
    passed_table = PAR.parity_markdown(passing)

    assert failed_table.startswith("| Metric | EN | KO |")
    assert "undefined" in failed_table
    assert "FAIL" in failed_table
    assert "PASS" in passed_table
    assert "1.000000" in passed_table
