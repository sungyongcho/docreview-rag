"""Local reset authentication and full HTTP/stream request admission boundaries."""

import asyncio
import json
import stat
import tempfile
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest
from starlette.requests import ClientDisconnect

from app.api.admin_runtime import RuntimeAdminApiServices
from app.api.app import create_api_app
from app.api.deps import ApiServices
from app.api.routes.stream import review_stream
from app.api.runtime_gate import RuntimeResetGate, RuntimeResetMiddleware
from app.api.schemas import ReviewRequest


def test_control_requires_dev_opt_in_loopback_and_private_token(tmp_path, monkeypatch):
    """Expose no control on ordinary apps and reject unauthenticated loopback requests."""
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    for enabled, admin in ((False, object()), (True, None)):
        app = create_api_app(admin_services=admin, enable_reset=enabled)
        with TestClient(app) as client:
            assert client.get("/_internal/reset/activity").status_code == 404
        assert not list(tmp_path.glob("docreview-runtime-gate-*.json"))

    app = create_api_app(admin_services=cast(RuntimeAdminApiServices, object()), enable_reset=True)
    with TestClient(app, client=("127.0.0.1", 1000)) as client:
        files = list(tmp_path.glob("docreview-runtime-gate-*.json"))
        assert len(files) == 1
        assert stat.S_IMODE(files[0].stat().st_mode) == 0o600
        record = json.loads(files[0].read_text())
        assert client.get("/_internal/reset/activity").status_code == 403
        assert (
            client.get(
                "/_internal/reset/activity", headers=[(b"x-docreview-reset", b"\xff")]
            ).status_code
            == 403
        )
        headers = {"X-DocReview-Reset": record["token"]}
        response = client.get("/_internal/reset/activity", headers=headers)
        assert response.status_code == 200
        assert response.json()["active_requests"] == 0
        assert record["token"] not in response.text
        external = TestClient(app, client=("203.0.113.1", 1000))
        assert external.get("/_internal/reset/activity", headers=headers).status_code == 403
        external.close()
    assert not list(tmp_path.glob("docreview-runtime-gate-*.json"))


def test_hold_blocks_admission_and_requires_exact_release(tmp_path, monkeypatch):
    """Keep read liveness accessible while mutations and DB reads wait for exact release."""
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    app = create_api_app(admin_services=cast(RuntimeAdminApiServices, object()), enable_reset=True)

    @app.get("/health")
    async def health():
        """Return liveness without touching runtime state."""
        return {"ok": True}

    @app.post("/probe")
    async def probe():
        """Expose a small route to prove gate admission before application execution."""
        return {"ran": True}

    with TestClient(app, client=("127.0.0.1", 1000)) as client:
        token_file = next(tmp_path.glob("docreview-runtime-gate-*.json"))
        headers = {"X-DocReview-Reset": json.loads(token_file.read_text())["token"]}
        lease = str(uuid4())
        held = client.post("/_internal/reset/hold", headers=headers, json={"lease": lease})
        assert held.status_code == 200
        assert (
            client.post("/_internal/reset/hold", headers=headers, json={"lease": lease}).status_code
            == 200
        )
        assert client.post("/probe").status_code == 409
        assert client.get("/documents").status_code == 409
        assert client.get("/health").status_code == 200
        assert (
            client.post(
                "/_internal/reset/release", headers=headers, json={"lease": str(uuid4())}
            ).status_code
            == 409
        )
        assert client.post("/probe").status_code == 409
        assert (
            client.post(
                "/_internal/reset/release", headers=headers, json={"lease": lease}
            ).status_code
            == 200
        )
        assert client.post("/probe").status_code == 200


@pytest.mark.parametrize("failure", ["send", "cancel", "disconnect"])
def test_stream_remains_active_until_cancelled_producer_cleanup_finishes(failure):
    """Reject reset through stream body failure and asynchronous workflow cleanup."""

    async def scenario():
        """Drive the real stream response while observing its gate from another task."""
        started = asyncio.Event()
        cleanup_started = asyncio.Event()
        cleanup_release = asyncio.Event()
        cleaned = asyncio.Event()
        send_waiting = asyncio.Event()
        gate = RuntimeResetGate()

        class Services:
            """Simulate a workflow with observable cancellation cleanup and no providers."""

            async def review(self, _request, on_node):
                """Produce one event and hold cleanup until the test explicitly permits it."""
                await on_node(
                    "retrieve", SimpleNamespace(evidence=(), relevant_chunk_ids=(), steps=())
                )
                started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cleanup_started.set()
                    await cleanup_release.wait()
                    cleaned.set()

        response = await review_stream(
            ReviewRequest(query="Revenue?"), cast(ApiServices, Services())
        )
        wrapped = RuntimeResetMiddleware(response, gate)
        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.0" if failure == "disconnect" else "2.4"},
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
            """Leave disconnect handling to the deliberately failed send or task cancellation."""
            if failure == "disconnect":
                await send_waiting.wait()
                return {"type": "http.disconnect"}
            await asyncio.Event().wait()

        async def send(message):
            """Interrupt delivery only after the workflow has produced its first body."""
            if message["type"] == "http.response.body" and message.get("body"):
                send_waiting.set()
                if failure == "send":
                    raise OSError("client disconnected")
                if failure == "cancel":
                    await asyncio.Event().wait()

        task = asyncio.create_task(wrapped(scope, receive, send))
        await asyncio.wait_for(started.wait(), 2)
        await asyncio.wait_for(send_waiting.wait(), 2)
        if failure == "cancel":
            task.cancel()
        await asyncio.wait_for(cleanup_started.wait(), 2)
        assert gate.activity()["active_requests"] == 1
        with pytest.raises(HTTPException) as error:
            gate.hold(str(uuid4()))
        assert error.value.status_code == 409
        cleanup_release.set()
        if failure == "disconnect":
            await task
        else:
            with pytest.raises(ClientDisconnect if failure == "send" else asyncio.CancelledError):
                await task
        assert cleaned.is_set()
        assert gate.activity()["active_requests"] == 0
        assert gate.hold(str(uuid4()))["instance"] == gate.instance

    asyncio.run(scenario())


def test_gate_counts_background_cleanup_after_response_body():
    """Keep a finished HTTP body active until the ASGI application itself exits."""

    async def scenario():
        """Observe request admission while a handler finishes deferred cleanup."""
        gate = RuntimeResetGate()
        body_sent = asyncio.Event()
        complete = asyncio.Event()

        async def application(_scope, _receive, _send):
            """Represent a completed body followed by a still-running background task."""
            body_sent.set()
            await complete.wait()

        async def transport(*_arguments):
            """Provide unused ASGI transport functions for this lifecycle-only check."""
            return None

        task = asyncio.create_task(
            RuntimeResetMiddleware(application, gate)(
                {"type": "http", "method": "POST", "path": "/probe"}, transport, transport
            )
        )
        await body_sent.wait()
        with pytest.raises(HTTPException):
            gate.hold(str(uuid4()))
        complete.set()
        await task
        assert gate.activity()["active_requests"] == 0

    asyncio.run(scenario())
