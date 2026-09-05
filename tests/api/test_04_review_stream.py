"""M5.4 SSE review streaming: event order, terminal report, and typed errors."""

import asyncio
import json
from types import SimpleNamespace
from typing import cast

import pytest
from starlette.requests import ClientDisconnect

from app.api.deps import ApiServices
from app.api.errors import ApiProblemError
from app.api.routes import stream as stream_module
from app.api.schemas import ReviewRequest
from app.observability.types import build_run_report
from app.workflow.types import NodeError


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
    """Build one workflow state with the counts the node event reports."""
    return SimpleNamespace(
        evidence=tuple(range(evidence)),
        relevant_chunk_ids=tuple(range(relevant)),
        steps=tuple(range(steps)),
    )


def test_stream_emits_node_events_then_the_terminal_run(client_factory, services, successful_run):
    """Emit one node event per node in order, then the report and the done marker."""
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


def test_stream_reports_a_failed_run_as_its_terminal_event(client_factory, services, budget_run):
    """End a budget-stopped run with a report event, not an error event."""
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


def test_stream_converts_an_unexpected_failure_into_a_typed_error_event(client_factory, services):
    """Convert an unexpected failure into a typed error event that leaks nothing."""
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


def test_stream_rejects_malformed_requests_before_streaming(client_factory, services):
    """Reject an invalid request before the response becomes a stream."""
    response = client_factory(services).post("/review/stream", json={"query": " "})

    assert response.status_code == 422
    assert "text/event-stream" not in response.headers.get("content-type", "")


def test_stream_preserves_typed_service_errors_and_redacts_terminal_reports(
    client_factory,
    services,
):
    """Keep a typed service error typed, and keep a secret out of the report."""
    services.review_error = ApiProblemError(
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
        report={"reason": failure.model_dump(mode="json")},
    )
    with client_factory(services).stream(
        "POST", "/review/stream", json={"query": "Revenue?"}
    ) as response:
        report_events = sse_events(response)

    assert secret not in repr(report_events)


def test_stream_send_failure_cancels_the_review_task():
    """Cancel the workflow when the body send fails on a disconnected client."""

    class BlockingServices:
        """Service boundary that blocks after the first node until cancelled."""

        def __init__(self):
            self.started = asyncio.Event()
            self.cancelled = asyncio.Event()
            self.release = asyncio.Event()

        async def review(self, request, on_node=None):
            """Report one node, then block so the send failure can cancel this task."""
            assert on_node is not None
            await on_node("retrieve", state())
            self.started.set()
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                self.cancelled.set()
                raise

    async def exercise() -> None:
        """Drive the response through an ASGI send that fails on the first body."""
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
            """Report the client as already disconnected."""
            return {"type": "http.disconnect"}

        async def send(message):
            """Fail the first non-empty body send, as a dropped connection would."""
            if message["type"] == "http.response.body" and message.get("body"):
                raise OSError("client disconnected")

        with pytest.raises(ClientDisconnect):
            await response(scope, receive, send)
        assert services.started.is_set()
        assert services.cancelled.is_set()

    asyncio.run(exercise())


def test_stream_emits_actual_stage_transitions_without_changing_node_contract(
    client_factory, services, successful_run
):
    """Expose in-flight stages and completed durations alongside legacy node payloads."""
    from app.observability.stages import stage, stage_metadata

    async def review(request, on_node=None):
        """Exercise the stream's actual recorder using the shared observation boundary."""
        async with stage("grade"):
            await on_node("grade", state(steps=1))
        return successful_run.model_copy(update={"request_context": stage_metadata()})

    services.review = review
    with client_factory(services).stream(
        "POST",
        "/review/stream",
        json={"query": "Revenue?"},
        headers={"X-DocReview-Telemetry": "stages"},
    ) as response:
        events = sse_events(response)
    assert [kind for kind, _ in events] == ["stage", "node", "stage", "report", "done"]
    assert events[0][1]["phase"] == "start" and events[0][1]["elapsed_ms"] is None
    assert events[2][1]["status"] == "completed" and events[2][1]["elapsed_ms"] >= 0
    execution = events[3][1]["execution"]
    assert execution["stages"][0]["node"] == "grade"
    assert execution["total_elapsed_ms"] >= events[2][1]["total_elapsed_ms"]


def test_stream_omits_new_events_without_explicit_telemetry_header(
    client_factory, services, successful_run
):
    """Old clients retain their event vocabulary while reports keep measured data."""
    from app.observability.stages import stage, stage_metadata

    async def review(request, on_node=None):
        """Run an observed stage without opting the HTTP client into new event types."""
        async with stage("grade"):
            await on_node("grade", state(steps=1))
        return successful_run.model_copy(update={"request_context": stage_metadata()})

    services.review = review
    with client_factory(services).stream(
        "POST", "/review/stream", json={"query": "Revenue?"}
    ) as response:
        events = sse_events(response)
    assert [kind for kind, _ in events] == ["node", "report", "done"]
    assert events[1][1]["execution"]["stages"][0]["node"] == "grade"
