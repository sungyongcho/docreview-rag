"""M5.1 strict HTTP schema and domain-mapping contracts."""

import json

from pydantic import ValidationError
import pytest

from app.observability import build_run_report
from app.workflow import NodeError, ProviderFailure
from tests.support import need


def test_retrieve_request_is_strict_and_rejects_blank_or_unknown_input(A):
    need(A, "RetrieveRequest")
    with pytest.raises(ValidationError):
        A.RetrieveRequest(query=" ")
    with pytest.raises(ValidationError):
        A.RetrieveRequest(query="Revenue?", k="5")
    with pytest.raises(ValidationError):
        A.RetrieveRequest(query="Revenue?", unsupported=True)


def test_evidence_projection_exposes_complete_source_identity(A, hit):
    need(A, "EvidenceHit")
    evidence = A.EvidenceHit.from_chunk_hit(hit)

    assert evidence.chunk_id == 7
    assert evidence.start_char == 100
    assert evidence.end_char == 180
    assert evidence.source_sha256 == "d" * 64
    assert evidence.citation == "ACME FY2024 - Item 7"


def test_ingest_and_review_requests_reject_empty_bodies(A):
    need(A, "IngestRequest", "ReviewRequest")
    with pytest.raises(ValidationError):
        A.IngestRequest.model_validate_json("{}")
    with pytest.raises(ValidationError):
        A.ReviewRequest.model_validate_json("{}")


def test_successful_run_maps_to_strict_workflow_report(A, successful_run):
    need(A, "RunResponse")
    response = A.RunResponse.from_run_report(successful_run)

    assert response.status == "ok"
    assert response.failure is None
    assert response.report.label == "SUPPORTED"
    assert response.report.citations[0].chunk_id == 7


def test_budget_run_maps_to_discriminated_failure(A, budget_run):
    need(A, "BudgetLimitFailure", "RunResponse")
    response = A.RunResponse.from_run_report(budget_run)

    assert response.report is None
    assert isinstance(response.failure, A.BudgetLimitFailure)
    assert response.failure.blocked_node == "retrieve"


def test_run_response_rejects_mismatched_success_and_failure_shapes(A, successful_run):
    need(A, "RunResponse")
    valid = A.RunResponse.from_run_report(successful_run)
    payload = valid.model_dump(mode="json")
    payload["status"] = "error"

    with pytest.raises(ValidationError):
        A.RunResponse.model_validate_json(json.dumps(payload))


@pytest.mark.parametrize(
    ("status", "failure"),
    [
        (
            "budget_exceeded",
            NodeError(node="grade", error_type="RuntimeError", message="failed"),
        ),
        (
            "schema_rejected",
            ProviderFailure(node="grade", status="provider_error", details=("failed",)),
        ),
        (
            "error",
            ProviderFailure(node="grade", status="budget_exceeded", details=("failed",)),
        ),
    ],
)
def test_run_response_requires_status_to_match_failure_type(A, budget_run, status, failure):
    need(A, "RunResponse")
    payload = A.RunResponse.from_run_report(budget_run).model_dump(mode="json")
    payload.update(status=status, failure=failure.model_dump(mode="json"))

    with pytest.raises(ValidationError, match="status must match"):
        A.RunResponse.model_validate_json(json.dumps(payload))


def test_run_response_redacts_public_prompt_and_failure_text(A):
    need(A, "RunResponse")
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
        report={"failure": failure.model_dump(mode="json")},
    )

    response = A.RunResponse.from_run_report(report)

    assert secret not in response.system_prompt
    assert secret not in repr(response.failure)
