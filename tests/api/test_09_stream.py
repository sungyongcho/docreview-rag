"""M5.4 SSE review streaming: event order, terminal report, and typed errors."""

import asyncio
import json
from types import SimpleNamespace
from typing import cast

import pytest
from starlette.requests import ClientDisconnect

from app.api.deps import ApiServices
from app.api.routes import stream as stream_module
from app.api.schemas import ReviewRequest
from app.observability import build_run_report
from app.workflow import NodeError
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
    assert events[0][1] == {
        "error": {
            "code": "internal_error",
            "message": "The request could not be completed.",
            "details": [],
        }
    }


def test_stream_rejects_malformed_requests_before_streaming(A, client_factory, services):
    need(A, "create_api_app")
    response = client_factory(services).post("/review/stream", json={"query": " "})

    assert response.status_code == 422
    assert "text/event-stream" not in response.headers.get("content-type", "")


def test_stream_preserves_typed_service_errors_and_redacts_terminal_reports(
    A,
    client_factory,
    services,
):
    need(A, "ApiProblemError")
    services.review_error = A.ApiProblemError(
        status_code=503,
        code="provider_unavailable",
        message="Provider is unavailable.",
    )
    with client_factory(services).stream(
        "POST", "/review/stream", json={"query": "Revenue?"}
    ) as response:
        error_events = sse_events(response)

    assert error_events[0] == (
        "error",
        {
            "error": {
                "code": "provider_unavailable",
                "message": "Provider is unavailable.",
                "details": [],
            }
        },
    )

    secret = "sk-supersecret123"
    failure = NodeError(
        node="grade",
        error_type="RuntimeError",
        message=f"api_key={secret}",
    )
    services.review_error = None
    services.review_result = build_run_report(
        run_id="run-secret-stream",
        status="error",
        total_time_seconds=0.1,
        system_prompt=f"Bearer {secret}",
        node_path=("retrieve", "grade"),
        steps=(),
        report={"failure": failure.model_dump(mode="json")},
    )
    with client_factory(services).stream(
        "POST", "/review/stream", json={"query": "Revenue?"}
    ) as response:
        report_events = sse_events(response)

    assert secret not in repr(report_events)


def test_stream_send_failure_cancels_the_review_task():
    class BlockingServices:
        def __init__(self):
            self.started = asyncio.Event()
            self.cancelled = asyncio.Event()
            self.release = asyncio.Event()

        async def review_stream(self, request, on_node):
            await on_node("retrieve", state())
            self.started.set()
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                self.cancelled.set()
                raise

    async def exercise() -> None:
        services = BlockingServices()
        response = await stream_module.review_stream(
            ReviewRequest(query="Revenue?"),
            cast(ApiServices, services),
        )
        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.4"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/review/stream",
            "raw_path": b"/review/stream",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 1),
            "server": ("127.0.0.1", 80),
        }

        async def receive():
            return {"type": "http.disconnect"}

        async def send(message):
            if message["type"] == "http.response.body" and message.get("body"):
                raise OSError("client disconnected")

        with pytest.raises(ClientDisconnect):
            await response(scope, receive, send)
        assert services.started.is_set()
        assert services.cancelled.is_set()

    asyncio.run(exercise())
