"""Strict golden-case and source-span value-object contracts."""

from typing import Any

from pydantic import ValidationError
import pytest

from app.evals.types import GoldenCase, GoldenSpan


def _answer(**overrides: Any) -> GoldenSpan:
    """Build a valid answer span with optional replacements."""
    values: dict[str, Any] = {
        "doc_id": "TEST-FY2024",
        "source_sha256": "a" * 64,
        "start_char": 10,
        "end_char": 20,
    }
    values.update(overrides)
    return GoldenSpan(**values)


def _case(**overrides: Any) -> GoldenCase:
    """Build a valid positive case with optional replacements."""
    values: dict[str, Any] = {
        "id": "m3c-01",
        "question": "What fact is disclosed?",
        "category": "simple_lookup",
        "facet": "factual",
        "tags": [],
        "answers": [_answer()],
        "expected_label": "SUPPORTED",
        "reference_answer": "The disclosed fact.",
        "note": "A test case.",
        "curation_status": "agent-curated",
        "approval_status": "pending-author-approval",
        "human_verified": False,
    }
    values.update(overrides)
    return GoldenCase(**values)


def test_public_golden_contract_is_strict_and_immutable():
    """Freeze a loaded case and normalize its sequences to tuples."""
    case = _case(tags=["demo-hero"])

    assert case.tags == ("demo-hero",)
    assert isinstance(case.answers, tuple)
    assert case.human_verified is False
    with pytest.raises(ValidationError):
        case.question = "Changed"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_sha256", "A" * 64),
        ("start_char", "10"),
        ("start_char", True),
        ("end_char", 0),
        ("end_char", 10),
    ],
)
def test_answer_span_rejects_invalid_hashes_offsets_and_coercion(field, value):
    """Reject uppercase digests, coerced offsets, and empty intervals."""
    with pytest.raises(ValueError):
        _answer(**{field: value})


def test_contract_rejects_unknown_fields_and_duplicate_members():
    """Reject extra fields and duplicate answer spans; collapse repeated tags in order."""
    with pytest.raises(ValueError):
        _answer(chunk_id=7)
    assert _case(tags=["demo-hero", "demo-hero", "dart"]).tags == ("demo-hero", "dart")
    answer = _answer()
    with pytest.raises(ValueError, match="answer spans must be unique"):
        _case(answers=[answer, answer])


@pytest.mark.parametrize(
    "overrides",
    [
        {"category": "absent", "answers": [], "expected_label": "SUPPORTED"},
        {"category": "absent", "answers": [], "reference_answer": "Unknown"},
        {
            "category": "absent",
            "answers": [_answer()],
            "expected_label": "NOT_IN_DOCS",
            "reference_answer": "NOT_IN_DOCS",
        },
        {"answers": []},
        {"expected_label": "NOT_IN_DOCS"},
        {"reference_answer": "NOT_IN_DOCS"},
    ],
)
def test_positive_and_absent_contracts_cannot_be_mixed(overrides):
    """Keep absent cases spanless and positive cases supported."""
    with pytest.raises(ValueError):
        _case(**overrides)


@pytest.mark.parametrize(
    "overrides",
    [
        {"curation_status": "human-curated"},
        {"approval_status": "approved"},
        {"human_verified": True},
        {"human_verified": 0},
    ],
)
def test_unapproved_agent_provenance_is_required(overrides):
    """Reject any provenance that claims a review the data has not had."""
    with pytest.raises(ValueError):
        _case(**overrides)


@pytest.mark.parametrize("case_id", ["m3c-01", "retrieval-ko-07", "s2"])
def test_case_id_accepts_any_suite_slug(case_id):
    """Accept any suite's slug id, because the prefix is suite policy, not a type rule."""
    assert _case(id=case_id).id == case_id


@pytest.mark.parametrize("case_id", ["", "M3C-01", "m3c_01", "m3c-01 ", "-m3c-01"])
def test_case_id_rejects_non_slug_values(case_id):
    """Reject ids that are not lowercase hyphenated slugs."""
    with pytest.raises(ValidationError):
        _case(id=case_id)


def test_absent_case_has_no_source_span():
    """Accept an absent case that cites no source span."""
    case = _case(
        category="absent",
        facet="risk",
        answers=[],
        expected_label="NOT_IN_DOCS",
        reference_answer="NOT_IN_DOCS",
    )

    assert case.answers == ()
