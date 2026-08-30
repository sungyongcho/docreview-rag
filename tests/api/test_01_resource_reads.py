"""M5.1 retrieve and document resource route tests."""

from app.api.schemas import DocumentResource


def test_retrieve_route_returns_complete_evidence_identity(
    client_factory,
    services,
    hit,
):
    """Return every field a citation needs, and forward the requested k."""
    services.hits = (hit,)

    response = client_factory(services).post(
        "/retrieve",
        json={"query": "How much did revenue increase?", "k": 3},
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
    assert services.last_retrieve_request.k == 3


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
