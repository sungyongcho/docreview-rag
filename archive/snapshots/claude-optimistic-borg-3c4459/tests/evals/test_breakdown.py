"""Taxonomy grouping of a complete scored golden suite."""

import pytest

from app.evals.breakdown import breakdown_by_category, breakdown_by_facet, breakdown_markdown
from app.evals.scoring import CaseScore
from app.evals.types import GoldenCase


def _case_score(case_id: str, recall: float, rank: int | None, k: int = 5) -> CaseScore:
    """Build one case score with the requested recall and rank."""
    return CaseScore(
        case_id=case_id,
        k=k,
        gold_span_count=1,
        matched_gold_count=int(recall),
        recall_at_k=recall,
        hit_at_k=float(bool(rank)),
        reciprocal_rank=1.0 / rank if rank else 0.0,
        first_relevant_rank=rank,
    )


def _golden(case_id: str, category: str, facet: str, question: str) -> GoldenCase:
    """Build one golden case in the requested taxonomy group."""
    absent = category == "absent"
    return GoldenCase.model_validate(
        {
            "id": case_id,
            "question": question,
            "category": category,
            "facet": facet,
            "tags": [],
            "answers": []
            if absent
            else [
                {
                    "doc_id": "TEST-FY2024",
                    "source_sha256": "a" * 64,
                    "start_char": int(case_id[4:]) * 10,
                    "end_char": int(case_id[4:]) * 10 + 5,
                }
            ],
            "expected_label": "NOT_IN_DOCS" if absent else "SUPPORTED",
            "reference_answer": "NOT_IN_DOCS" if absent else "A value.",
            "note": "Breakdown fixture.",
            "curation_status": "agent-curated",
            "approval_status": "pending-author-approval",
            "human_verified": False,
        }
    )


def test_breakdown_groups_in_declaration_order_with_macro_averages():
    """Group a complete scored suite in taxonomy declaration order."""
    cases = [
        _golden("m3c-01", "multi_hop", "comparison", "How did margin change?"),
        _golden("m3c-02", "simple_lookup", "factual", "What was disclosed?"),
        _golden("m3c-03", "simple_lookup", "risk", "Which risk is named?"),
        _golden("m3c-04", "absent", "policy", "What dividend was declared?"),
    ]
    scores = [
        _case_score("m3c-01", 0.0, None),
        _case_score("m3c-02", 1.0, 1),
        _case_score("m3c-03", 1.0, 2),
    ]

    by_category = breakdown_by_category(cases, scores)
    assert [(group.group, group.suite.case_count) for group in by_category] == [
        ("simple_lookup", 2),
        ("multi_hop", 1),
    ]
    assert by_category[0].suite.recall_at_k == 1.0
    assert by_category[0].suite.mrr == 0.75
    assert by_category[1].suite.hit_rate_at_k == 0.0

    by_facet = breakdown_by_facet(cases, scores)
    assert [group.group for group in by_facet] == ["factual", "comparison", "risk"]
    assert all(group.suite.k == 5 for group in by_facet)


def test_breakdown_rejects_partial_stray_or_mixed_scoring():
    """Reject partial, stray, absent-case, mixed-k, and duplicate-id scoring."""
    cases = [
        _golden("m3c-01", "simple_lookup", "factual", "What was disclosed?"),
        _golden("m3c-02", "exact_number", "numeric", "How much revenue?"),
        _golden("m3c-03", "absent", "policy", "What dividend was declared?"),
    ]
    complete = [_case_score("m3c-01", 1.0, 1), _case_score("m3c-02", 0.0, None)]

    with pytest.raises(ValueError, match="missing a score"):
        breakdown_by_category(cases, complete[:1])
    with pytest.raises(ValueError, match="unknown golden case"):
        breakdown_by_category(cases, [*complete, _case_score("m3c-09", 1.0, 1)])
    with pytest.raises(ValueError, match="absent case cannot carry"):
        breakdown_by_category(cases, [*complete, _case_score("m3c-03", 1.0, 1)])
    with pytest.raises(ValueError, match="duplicate case score"):
        breakdown_by_category(cases, [*complete, _case_score("m3c-01", 1.0, 1)])
    with pytest.raises(ValueError, match="same k"):
        breakdown_by_category(cases, [complete[0], _case_score("m3c-02", 0.0, None, k=10)])
    with pytest.raises(ValueError, match="scores must not be empty"):
        breakdown_by_category(cases, [])

    duplicate_id = _golden("m3c-01", "multi_hop", "comparison", "How did it change?")
    with pytest.raises(ValueError, match="duplicate golden case id"):
        breakdown_by_category([cases[0], duplicate_id], complete[:1])


def test_breakdown_markdown_renders_the_exact_table():
    """Render one deterministic Markdown table and reject empty input."""
    cases = [
        _golden("m3c-01", "simple_lookup", "factual", "What was disclosed?"),
        _golden("m3c-02", "simple_lookup", "risk", "Which risk is named?"),
    ]
    scores = [_case_score("m3c-01", 1.0, 1), _case_score("m3c-02", 0.0, None)]
    groups = breakdown_by_category(cases, scores)

    assert breakdown_markdown("Category", groups) == (
        "| Category | Cases | Recall@k | Hit rate@k | MRR |\n"
        "|---|---:|---:|---:|---:|\n"
        "| simple_lookup | 2 | 0.500000 | 0.500000 | 0.500000 |"
    )
    with pytest.raises(ValueError, match="must not be empty"):
        breakdown_markdown("Category", [])
    with pytest.raises(ValueError, match="dimension must not be blank"):
        breakdown_markdown("   ", groups)

    assert breakdown_by_category(cases, list(reversed(scores))) == groups
