"""M5.1 retrieve, document, and snapshot resource route tests."""

from datetime import UTC, datetime

from app.api.schemas import (
    DocumentResource,
    EvalResultResource,
    SnapshotComparisonResponse,
    SnapshotMetricDelta,
    SnapshotResource,
)


def test_retrieve_route_returns_complete_evidence_identity(
    client_factory,
    services,
    hit,
):
    """Return every field a citation needs, and forward the requested k."""
    services.hits = (hit,)

    response = client_factory(services).post(
        "/retrieve",
        json={
            "query": "How much did revenue increase?",
            "session_profile": {
                "retrieval_preset": "custom",
                "custom_retrieval": {"k": 3},
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "How much did revenue increase?"
    assert body["results"][0] == {
        "chunk_id": 7,
        "doc_id": "ACME-FY2024",
        "item": "7",
        "kind": "text",
        "citation": "ACME FY2024 - Item 7",
        "start_char": 100,
        "end_char": 180,
        "source_sha256": "d" * 64,
        "body": "Revenue increased by ten percent.",
        "context_header": "ACME FY2024 - Item 7",
        "score": 1.0,
    }
    assert services.last_retrieve_request.session_profile.custom_retrieval.k == 3
    assert body["resolved_profile"]["k"] == 3


def test_documents_route_returns_typed_collection(client_factory, services):
    """Return the document collection with its chunk count and source digest."""
    services.documents = (
        DocumentResource(
            doc_id="ACME-FY2024",
            registry="sec",
            language="en",
            issuer="ACME",
            issuer_id="123",
            fiscal_year=2024,
            form="10-K",
            filing_date="2024-02-01",
            report_period="2023-12-31",
            filing_id="0000000123-24-000001",
            source_url="https://example.invalid/acme-2024",
            parse_status="parsed",
            source_length=1_000,
            source_sha256="d" * 64,
            chunk_count=12,
        ),
    )

    response = client_factory(services).get("/documents")

    assert response.status_code == 200
    assert response.json()["documents"][0]["chunk_count"] == 12
    assert response.json()["documents"][0]["source_sha256"] == "d" * 64


def test_snapshot_routes_read_stored_results_without_starting_work(client_factory, services):
    """List and compare immutable public snapshots through typed resources."""
    recorded = datetime(2026, 9, 1, tzinfo=UTC)
    result = EvalResultResource(
        result_id=9,
        suite="sec-en",
        config={"golden_sha256": "a" * 64},
        metrics={"mrr": 0.5},
        raw_artifact_path="artifact.json",
        created_at=recorded,
    )
    services.snapshots = (
        SnapshotResource(
            snapshot_id=1,
            label="Baseline",
            status="ready",
            public=True,
            corpus_fingerprint="b" * 64,
            profile={},
            golden_revision_id=None,
            eval_result=result,
            document_count=2,
            created_at=recorded,
        ),
    )
    services.snapshot_comparison = SnapshotComparisonResponse(
        baseline_id=1,
        candidate_id=2,
        directly_comparable=True,
        warning=None,
        metrics=(SnapshotMetricDelta(name="mrr", baseline=0.4, candidate=0.5, delta=0.1),),
    )
    client = client_factory(services)

    listed = client.get("/snapshots")
    compared = client.get("/snapshots/compare?baseline_id=1&candidate_id=2")

    assert listed.json()["snapshots"][0]["label"] == "Baseline"
    assert compared.json()["metrics"][0]["delta"] == 0.1
