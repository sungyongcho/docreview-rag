"""L1: strict golden-case and raw-span value objects."""

from pydantic import ValidationError
import pytest

from tests.support import need


def _answer(E, **overrides):
    values = {
        "doc_id": "TEST-FY2024",
        "source_sha256": "a" * 64,
        "start_char": 10,
        "end_char": 20,
    }
    values.update(overrides)
    return E.GoldenSpan(**values)


def _case(E, **overrides):
    values = {
        "id": "m3c-01",
        "question": "What fact is disclosed?",
        "category": "simple_lookup",
        "facet": "factual",
        "tags": [],
        "answers": [_answer(E)],
        "expected_label": "SUPPORTED",
        "reference_answer": "The disclosed fact.",
        "note": "A test case.",
        "curation_status": "agent-curated",
        "approval_status": "pending-author-approval",
        "human_verified": False,
    }
    values.update(overrides)
    return E.GoldenCase(**values)


def test_public_golden_contract_is_strict_and_immutable(E):
    need(E, "GoldenSpan", "GoldenCase")
    case = _case(E, tags=["demo-hero"])

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
def test_answer_span_rejects_invalid_hashes_offsets_and_coercion(E, field, value):
    need(E, "GoldenSpan")
    with pytest.raises(ValueError):
        _answer(E, **{field: value})


def test_contract_rejects_unknown_fields_and_duplicate_members(E):
    need(E, "GoldenSpan", "GoldenCase")
    with pytest.raises(ValueError):
        E.GoldenSpan(
            doc_id="TEST-FY2024",
            source_sha256="a" * 64,
            start_char=1,
            end_char=2,
            chunk_id=7,
        )
    with pytest.raises(ValueError, match="tags must be unique"):
        _case(E, tags=["demo-hero", "demo-hero"])
    answer = _answer(E)
    with pytest.raises(ValueError, match="answer spans must be unique"):
        _case(E, answers=[answer, answer])


@pytest.mark.parametrize(
    "overrides",
    [
        {"category": "absent", "answers": [], "expected_label": "SUPPORTED"},
        {"category": "absent", "answers": [], "reference_answer": "Unknown"},
        {
            "category": "absent",
            "answers": [_answer],
            "expected_label": "NOT_IN_DOCS",
            "reference_answer": "NOT_IN_DOCS",
        },
        {"answers": []},
        {"expected_label": "NOT_IN_DOCS"},
        {"reference_answer": "NOT_IN_DOCS"},
    ],
)
def test_positive_and_absent_contracts_cannot_be_mixed(E, overrides):
    need(E, "GoldenSpan", "GoldenCase")
    if overrides.get("answers") == [_answer]:
        overrides = {**overrides, "answers": [_answer(E)]}
    with pytest.raises(ValueError):
        _case(E, **overrides)


@pytest.mark.parametrize(
    "overrides",
    [
        {"curation_status": "human-curated"},
        {"approval_status": "approved"},
        {"human_verified": True},
        {"human_verified": 0},
    ],
)
def test_unapproved_agent_provenance_is_required(E, overrides):
    need(E, "GoldenSpan", "GoldenCase")
    with pytest.raises(ValueError):
        _case(E, **overrides)


def test_absent_case_has_no_source_span(E):
    need(E, "GoldenSpan", "GoldenCase")
    case = _case(
        E,
        category="absent",
        facet="risk",
        answers=[],
        expected_label="NOT_IN_DOCS",
        reference_answer="NOT_IN_DOCS",
    )

    assert case.answers == ()
