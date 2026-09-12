"""M5.1 run, trace, eval, and complete route-surface tests."""

from datetime import UTC, datetime

from app.api.schemas import EvalResultResource


def test_run_route_returns_resource_and_typed_404(
    client_factory,
    services,
    successful_run,
):
    """Return a stored run, and a typed 404 for one that does not exist."""
    services.runs[successful_run.run_id] = successful_run
    client = client_factory(services)

    found = client.get("/runs/run-supported")
    missing = client.get("/runs/run-missing")

    assert found.status_code == 200
    assert found.json()["report"]["citations"][0]["chunk_id"] == 7
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "run_not_found"


def test_trace_route_returns_raw_output_and_validates_parent(
    client_factory,
    services,
    trace,
):
    """Return raw provider output, and reject traces of an unknown run."""
    services.traces["run-supported"] = (trace,)
    client = client_factory(services)

    found = client.get("/runs/run-supported/traces")
    missing = client.get("/runs/run-missing/traces")

    assert found.status_code == 200
    assert found.json()["traces"][0]["llm_output"] == '{"grades":[]}'
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "run_not_found"


def test_eval_route_applies_bounded_limit(client_factory, services):
    """Honour a limit within range and reject one outside it."""
    services.eval_results = tuple(
        EvalResultResource(
            result_id=result_id,
            suite="retrieval-v1",
            config={"strategy": "hybrid"},
            metrics={"recall_at_k": 0.8},
            raw_artifact_path=f"data/eval_runs/{result_id}.json",
            created_at=datetime(2026, 8, 12, tzinfo=UTC),
        )
        for result_id in (3, 2, 1)
    )
    client = client_factory(services)

    response = client.get("/eval?limit=2")
    invalid = client.get("/eval?limit=0")

    assert response.status_code == 200
    assert [row["result_id"] for row in response.json()["results"]] == [3, 2]
    assert services.last_eval_limit == 2
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "request_validation_failed"


def test_openapi_exposes_resource_oriented_surface(client_factory, services):
    """Publish exactly the documented paths, error schemas, and the SSE media type."""
    document = client_factory(services).get("/openapi.json").json()
    paths = set(document["paths"])

    assert paths == {
        "/documents",
        "/public/documents",
        "/public/documents/facets",
        "/public/documents/{doc_id}",
        "/public/portfolio/preparation",
        "/public/snapshots/{snapshot_id}/dataset",
        "/public/snapshots/{snapshot_id}/evaluation",
        "/eval",
        "/ingest",
        "/retrieve",
        "/review",
        "/review/stream",
        "/runs/{run_id}",
        "/runs/{run_id}/traces",
        "/snapshots",
        "/snapshots/compare",
    }

    retrieve_responses = document["paths"]["/retrieve"]["post"]["responses"]
    assert retrieve_responses["422"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ErrorResponse"
    }
    review_responses = document["paths"]["/review"]["post"]["responses"]
    assert review_responses["429"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/RunResponse"
    }
    assert {
        item["$ref"]
        for item in review_responses["503"]["content"]["application/json"]["schema"]["anyOf"]
    } == {
        "#/components/schemas/ErrorResponse",
        "#/components/schemas/RunResponse",
    }
    assert document["paths"]["/runs/{run_id}"]["get"]["responses"]["404"]["content"][
        "application/json"
    ]["schema"] == {"$ref": "#/components/schemas/ErrorResponse"}
    assert (
        "text/event-stream"
        in document["paths"]["/review/stream"]["post"]["responses"]["200"]["content"]
    )
