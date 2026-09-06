"""M5.1 synchronous ingest and review route tests."""

from app.api.errors import bad_request
from app.ingestion.seed import SeedResult


def test_ingest_route_completes_synchronously(client_factory, services):
    """Return the seed counts in the response rather than a job handle."""
    services.seed_result = SeedResult(documents=2, chunks=24)

    response = client_factory(services).post(
        "/ingest",
        json={
            "manifest_path": "data/corpus/manifest.json",
            "selection_id": "sec-evaluation",
            "expected_documents": 2,
            "chunk_batch_size": 100,
        },
    )

    assert response.status_code == 200
    assert response.json() == {"documents": 2, "chunks": 24}
    assert services.last_ingest_request.selection_id == "sec-evaluation"
    assert services.last_ingest_request.manifest_path == "data/corpus/manifest.json"


def test_missing_manifest_is_a_typed_client_error(client_factory, services):
    """Report a missing manifest as a 400 naming the failure."""
    services.ingest_error = bad_request("manifest_not_found", "Manifest file was not found.")

    response = client_factory(services).post(
        "/ingest",
        json={"manifest_path": "missing.json", "selection_id": "sec-evaluation"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "manifest_not_found"


def test_review_route_returns_supported_evidence_synchronously(
    client_factory,
    services,
    successful_run,
):
    """Return the supported report with its citation identity intact."""
    services.review_result = successful_run

    response = client_factory(services).post(
        "/review",
        json={"query": "How much did revenue increase?"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == "run-supported"
    assert body["report"]["label"] == "SUPPORTED"
    assert body["report"]["citations"][0]["chunk_id"] == 7
    assert body["report"]["citations"][0]["start_char"] == 100
    assert body["report"]["citations"][0]["end_char"] == 180
    assert body["report"]["citations"][0]["source_sha256"] == "d" * 64
    assert body["report"]["citations"][0]["citation"] == "ACME FY2024 - Item 7"


def test_review_budget_exhaustion_is_a_structured_429(
    client_factory,
    services,
    budget_run,
):
    """Report budget exhaustion as a 429 carrying the limit that stopped it."""
    services.review_result = budget_run

    response = client_factory(services).post(
        "/review",
        json={
            "query": "Revenue?",
            "session_profile": {
                "prompt_policy": {"workflow_budget": {"max_iterations": 0}},
            },
        },
    )

    assert response.status_code == 429
    assert (
        services.last_review_request.session_profile.prompt_policy.workflow_budget.max_iterations
        == 0
    )
    assert response.json()["failure"] == {
        "code": "budget_exceeded",
        "resource": "iterations",
        "limit": 0,
        "observed": 0,
        "blocked_node": "retrieve",
    }


def test_review_schema_rejection_is_a_structured_502(
    client_factory,
    services,
    schema_rejected_run,
):
    """Report a rejected provider schema as a 502 naming the status."""
    services.review_result = schema_rejected_run

    response = client_factory(services).post("/review", json={"query": "Revenue?"})

    assert response.status_code == 502
    assert response.json()["failure"]["code"] == "provider_failure"
    assert response.json()["failure"]["status"] == "schema_rejected"
