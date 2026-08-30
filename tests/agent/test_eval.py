"""Category slices over a scored evaluation."""

from types import SimpleNamespace

import pytest

from app.agent.eval import category_metrics
from app.evals.scoring import CaseScore


def test_category_metrics_slices_scored_cases_only():
    """Report per-category metrics over scored cases, omitting unscored ones."""

    def case(category, recall, rank):
        """Build one evaluated case, scored or left unscored."""
        score = None
        if recall is not None:
            score = CaseScore(
                case_id=f"m3c-{category[:2]}-{rank}",
                k=5,
                gold_span_count=2,
                matched_gold_count=int(recall * 2),
                recall_at_k=recall,
                hit_at_k=float(recall > 0),
                reciprocal_rank=1.0 / rank,
                first_relevant_rank=rank,
            )
        return SimpleNamespace(golden=SimpleNamespace(category=category), score=score)

    evaluation = SimpleNamespace(
        cases=(
            case("multi_hop", 0.5, 2),
            case("multi_hop", 1.0, 1),
            case("simple_lookup", 1.0, 1),
            case("absent", None, 1),
        )
    )

    metrics = category_metrics(evaluation)

    assert set(metrics) == {"multi_hop", "simple_lookup"}
    assert metrics["multi_hop"]["scored_case_count"] == 2.0
    assert metrics["multi_hop"]["recall_at_k"] == pytest.approx(0.75)
    assert metrics["multi_hop"]["mrr"] == pytest.approx(0.75)
    assert metrics["simple_lookup"]["recall_at_k"] == pytest.approx(1.0)
