"""M5.4 SSE review streaming: event order, terminal report, and typed errors."""

import json
from types import SimpleNamespace

from tests.support import need


def sse_events(response):
    """Parse the streamed body into ordered (event, payload) pairs."""
    events = []
    current = None
    for line in response.iter_lines():
        if line.startswith("event: "):
            current = line.removeprefix("event: ")
        elif line.startswith("data: "):
            assert current is not None, "data line arrived before its event line"
            events.append((current, json.loads(line.removeprefix("data: "))))
            current = None
    return events


def state(evidence=1, relevant=0, steps=0):
    return SimpleNamespace(
        evidence=tuple(range(evidence)),
        relevant_chunk_ids=tuple(range(relevant)),
        steps=tuple(range(steps)),
    )


def test_stream_emits_node_events_then_the_terminal_run(
    A, client_factory, services, successful_run
):
    need(A, "create_api_app")
    services.review_result = successful_run
    services.stream_states = (
        ("retrieve", state(steps=0)),
        ("grade", state(relevant=1, steps=1)),
        ("check", state(relevant=1, steps=2)),
        ("report", state(relevant=1, steps=2)),
    )

    with client_factory(services).stream(
        "POST", "/review/stream", json={"query": "How much did revenue increase?"}
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        events = sse_events(response)

    kinds = [kind for kind, _ in events]
    assert kinds == ["node", "node", "node", "node", "report", "done"]
    assert [payload["node"] for kind, payload in events if kind == "node"] == [
        "retrieve",
        "grade",
        "check",
        "report",
    ]
    assert events[1][1] == {
        "node": "grade",
        "evidence_count": 1,
        "relevant_count": 1,
        "step_count": 1,
    }
    report = events[4][1]
    assert report["status"] == "ok"
    assert report["run_id"] == successful_run.run_id
    assert services.last_review_request.query == "How much did revenue increase?"


def test_stream_reports_a_failed_run_as_its_terminal_event(A, client_factory, services, budget_run):
    need(A, "create_api_app")
    services.review_result = budget_run
    services.stream_states = (("retrieve", state()),)

    with client_factory(services).stream(
        "POST", "/review/stream", json={"query": "How much did revenue increase?"}
    ) as response:
        assert response.status_code == 200
        events = sse_events(response)

    kinds = [kind for kind, _ in events]
    assert kinds == ["node", "report", "done"]
    assert events[1][1]["status"] == "budget_exceeded"


def test_stream_converts_an_unexpected_failure_into_a_typed_error_event(
    A, client_factory, services
):
    need(A, "create_api_app")
    services.review_error = RuntimeError("provider exploded")

    with client_factory(services).stream(
        "POST", "/review/stream", json={"query": "How much did revenue increase?"}
    ) as response:
        assert response.status_code == 200
        events = sse_events(response)

    assert [kind for kind, _ in events] == ["error", "done"]
    assert events[0][1] == {"error_type": "RuntimeError"}


def test_stream_rejects_malformed_requests_before_streaming(A, client_factory, services):
    need(A, "create_api_app")
    response = client_factory(services).post("/review/stream", json={"query": " "})

    assert response.status_code == 422
    assert "text/event-stream" not in response.headers.get("content-type", "")
