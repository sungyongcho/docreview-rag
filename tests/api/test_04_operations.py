"""M5.1 synchronous ingest and review route tests."""

from app.ingestion.seed import SeedResult
from tests.support import need


def test_ingest_route_completes_synchronously(client_factory, services):
    services.seed_result = SeedResult(documents=2, chunks=24)

    response = client_factory(services).post(
        "/ingest",
        json={
            "manifest_path": "data/corpus/manifest.json",
            "expected_documents": 2,
            "chunk_batch_size": 100,
        },
    )

    assert response.status_code == 200
    assert response.json() == {"documents": 2, "chunks": 24}
    assert services.last_ingest_request.manifest_path == "data/corpus/manifest.json"


def test_missing_manifest_is_a_typed_client_error(A, client_factory, services):
    need(A, "bad_request")
    services.ingest_error = A.bad_request("manifest_not_found", "Manifest file was not found.")

    response = client_factory(services).post(
        "/ingest",
        json={"manifest_path": "missing.json"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "manifest_not_found"


def test_review_route_returns_supported_evidence_synchronously(
    client_factory,
    services,
    successful_run,
):
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
    services.review_result = budget_run

    response = client_factory(services).post(
        "/review",
        json={"query": "Revenue?", "budget": {"max_iterations": 0}},
    )

    assert response.status_code == 429
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
    services.review_result = schema_rejected_run

    response = client_factory(services).post("/review", json={"query": "Revenue?"})

    assert response.status_code == 502
    assert response.json()["failure"]["code"] == "provider_failure"
    assert response.json()["failure"]["status"] == "schema_rejected"
