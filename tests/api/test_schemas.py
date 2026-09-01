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
from app.workflow.types import NodeError, ProviderFailure


def test_retrieve_request_is_strict_and_rejects_blank_or_unknown_input():
    """Reject a blank query, a mistyped k, and any field the contract does not name."""
    with pytest.raises(ValidationError):
        RetrieveRequest(query=" ")
    with pytest.raises(ValidationError):
        RetrieveRequest(query="Revenue?", k="5")  # pyright: ignore[reportArgumentType]
    with pytest.raises(ValidationError):
        RetrieveRequest(query="Revenue?", unsupported=True)  # pyright: ignore[reportCallIssue]


def test_evidence_projection_exposes_complete_source_identity(hit):
    """Carry chunk, offsets, digest and citation through the evidence projection."""
    evidence = EvidenceHit.from_chunk_hit(hit)

    assert evidence.chunk_id == 7
    assert evidence.start_char == 100
    assert evidence.end_char == 180
    assert evidence.source_sha256 == "d" * 64
    assert evidence.citation == "ACME FY2024 - Item 7"


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
    assert response.report is not None
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
