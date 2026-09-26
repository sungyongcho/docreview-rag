"""M5.1 strict HTTP schema and domain-mapping contracts."""

import json

from pydantic import ValidationError
import pytest

from app.api.review.profiles import ReviewSessionProfile
from app.api.review.schemas import EvidenceHit, RetrieveRequest, ReviewRequest, RunResponse
from app.workflow.types import NodeError, ProviderFailure


def test_retrieve_request_is_strict_and_rejects_blank_or_unknown_input():
    """Reject blank queries and mistyped profile controls."""
    with pytest.raises(ValidationError):
        RetrieveRequest(query=" ")
    with pytest.raises(ValidationError):
        RetrieveRequest.model_validate(
            {
                "query": "Revenue?",
                "session_profile": {
                    "retrieval_preset": "custom",
                    "custom_retrieval": {"k": "5"},
                },
            }
        )


def test_evidence_projection_titles_dart_sections_by_registry(hit):
    """Resolve a DART numeral through the named registry without touching the citation."""
    dart_hit = hit.model_copy(update={"item": "II", "citation": "005930 FY2024 · II. 사업의 내용"})

    evidence = EvidenceHit.from_chunk_hit(dart_hit, registry="dart")

    assert evidence.section_title == "사업의 내용"
    assert evidence.citation == "005930 FY2024 · II. 사업의 내용"


def test_evidence_projection_leaves_unknown_sections_untitled(hit):
    """Unnumbered sections and foreign codes carry no title instead of a guess."""
    unnumbered = EvidenceHit.from_chunk_hit(hit.model_copy(update={"item": None}))
    foreign = EvidenceHit.from_chunk_hit(hit.model_copy(update={"item": "II"}), registry="sec")

    assert unnumbered.section_title is None
    assert foreign.section_title is None


def test_prompt_policy_appends_instructions_without_replacing_guard():
    """Keep the evidence guard first while allowing bounded developer instructions."""
    profile = ReviewSessionProfile.model_validate(
        {"prompt_policy": {"additional_instructions": "Prefer concise answers."}}
    )

    assert profile.prompt_policy.system_prompt.startswith("Use only the supplied filing evidence")
    assert profile.prompt_policy.system_prompt.endswith("Prefer concise answers.")


def test_review_request_accepts_json_arrays_for_strict_tuple_fields():
    """Normalize transport arrays without weakening strict nested values."""
    request = ReviewRequest.model_validate_json(
        json.dumps(
            {
                "query": "Revenue?",
                "session_profile": {
                    "issuers": ["NVDA"],
                    "languages": ["en"],
                    "fiscal_years": [2024],
                    "forms": ["10-K"],
                    "sections": ["7", None],
                },
                "conversation_history": [{"role": "user", "text": "Earlier question"}],
            }
        )
    )

    assert request.session_profile.issuers == ("NVDA",)
    assert request.session_profile.sections == ("7", None)
    assert request.conversation_history[0].role == "user"


def test_run_response_rejects_mismatched_success_and_failure_shapes(successful_run):
    """Reject a response whose status contradicts the report it carries."""
    valid = RunResponse.from_run_report(successful_run)
    payload = valid.model_dump(mode="json")
    payload["status"] = "error"

    with pytest.raises(ValidationError):
        RunResponse.model_validate_json(json.dumps(payload))


@pytest.mark.parametrize(
    ("status", "failure"),
    [
        (
            "budget_exceeded",
            NodeError(node="grade", error_type="RuntimeError", message="failed"),
        ),
        (
            "schema_rejected",
            ProviderFailure(node="grade", status="provider_error", attempts=2, details=("failed",)),
        ),
        (
            "error",
            ProviderFailure(
                node="grade", status="budget_exceeded", attempts=1, details=("failed",)
            ),
        ),
    ],
)
def test_run_response_requires_status_to_match_failure_type(budget_run, status, failure):
    """Reject every status paired with a failure type that does not belong to it."""
    payload = RunResponse.from_run_report(budget_run).model_dump(mode="json")
    payload.update(status=status, failure=failure.model_dump(mode="json"))

    with pytest.raises(ValidationError, match="status must match"):
        RunResponse.model_validate_json(json.dumps(payload))


@pytest.mark.parametrize("request_type", [RetrieveRequest, ReviewRequest])
def test_top_level_controls_are_rejected(request_type):
    """Accept configurable controls only through the explicit session profile."""
    with pytest.raises(ValidationError) as error:
        request_type.model_validate({"query": "Revenue?", "k": 3})
    assert any(
        item["loc"] == ("k",) and item["type"] == "extra_forbidden" for item in error.value.errors()
    )


def test_session_profile_preserves_every_explicit_filter():
    """Project document, registry, kind, and existing scope controls without losing any."""
    filters = {
        "doc_ids": ["ACME-FY2024"],
        "registries": ["sec"],
        "kinds": ["table"],
        "issuers": ["ACME"],
        "languages": ["en"],
        "fiscal_years": [2024],
        "forms": ["10-K"],
        "snapshot_id": 1,
    }
    profile = {**filters, "sections": ["7", None]}
    profile = ReviewSessionProfile.model_validate(profile)
    assert profile.explicit_filters().model_dump(mode="json") == {
        **filters,
        "items": [None, "7"],
    }
