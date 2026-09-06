"""M5.1 strict HTTP schema and domain-mapping contracts."""

import json

from pydantic import ValidationError
import pytest

from app.api.review_profile import ReviewSessionProfile
from app.api.schemas import (
    BudgetLimitFailure,
    EvidenceHit,
    IngestRequest,
    RetrieveRequest,
    ReviewRequest,
    RunResponse,
)
from app.observability.types import build_run_report
from app.workflow.types import NodeError, ProviderFailure, WorkflowReport


def test_retrieve_request_is_strict_and_rejects_blank_or_unknown_input():
    """Reject blank queries, mistyped profile controls, and unknown top-level fields."""
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
    with pytest.raises(ValidationError):
        RetrieveRequest.model_validate({"query": "Revenue?", "unsupported": True})


def test_evidence_projection_exposes_complete_source_identity(hit):
    """Carry chunk, offsets, digest and citation through the evidence projection."""
    evidence = EvidenceHit.from_chunk_hit(hit)

    assert evidence.chunk_id == 7
    assert evidence.start_char == 100
    assert evidence.end_char == 180
    assert evidence.source_sha256 == "d" * 64
    assert evidence.citation == "ACME FY2024 - Item 7"
    assert evidence.section_title == "Management's Discussion and Analysis"


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


def test_ingest_and_review_requests_reject_empty_bodies():
    """Refuse an empty body rather than defaulting the required fields."""
    with pytest.raises(ValidationError):
        IngestRequest.model_validate_json("{}")
    with pytest.raises(ValidationError):
        ReviewRequest.model_validate_json("{}")


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


def test_successful_run_maps_to_strict_workflow_report(successful_run):
    """Map a supported run to a report response carrying no failure."""
    response = RunResponse.from_run_report(successful_run)

    assert response.status == "ok"
    assert response.failure is None
    assert isinstance(response.report, WorkflowReport)
    assert response.report.label == "SUPPORTED"
    assert response.report.citations[0].chunk_id == 7


def test_budget_run_maps_to_discriminated_failure(budget_run):
    """Map a budget-stopped run to the discriminated failure and no report."""
    response = RunResponse.from_run_report(budget_run)

    assert response.report is None
    assert isinstance(response.failure, BudgetLimitFailure)
    assert response.failure.blocked_node == "retrieve"


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


def test_run_response_redacts_public_prompt_and_failure_text():
    """Keep a secret out of both the public prompt and the failure text."""
    secret = "sk-supersecret123"
    failure = NodeError(
        node="grade",
        error_type="RuntimeError",
        message=f"api_key={secret}",
    )
    report = build_run_report(
        run_id="run-secret",
        status="error",
        total_time_seconds=0.1,
        system_prompt=f"Bearer {secret}",
        node_path=("retrieve", "grade"),
        steps=(),
        report={"reason": failure.model_dump(mode="json")},
    )

    response = RunResponse.from_run_report(report)

    assert secret not in response.system_prompt
    assert secret not in repr(response.failure)


@pytest.mark.parametrize("request_type", [RetrieveRequest, ReviewRequest])
@pytest.mark.parametrize(
    "field,value",
    [
        ("k", 3),
        ("filters", {"doc_ids": ["ACME-FY2024"]}),
        ("budget", {"max_iterations": 4}),
        ("max_context_chars", 10000),
    ],
)
def test_removed_top_level_controls_are_rejected(request_type, field, value):
    """Accept configurable controls only through the explicit session profile."""
    with pytest.raises(ValidationError) as error:
        request_type.model_validate({"query": "Revenue?", field: value})
    assert any(
        item["loc"] == (field,) and item["type"] == "extra_forbidden"
        for item in error.value.errors()
    )


@pytest.mark.parametrize("request_type", [RetrieveRequest, ReviewRequest])
def test_session_profile_preserves_every_explicit_filter(request_type):
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
    request = request_type.model_validate({"query": "Revenue?", "session_profile": profile})
    assert request.session_profile.explicit_filters().model_dump(mode="json") == {
        **filters,
        "items": [None, "7"],
    }
