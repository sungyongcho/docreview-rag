"""Authenticated loopback Operations API and process lifecycle tests."""

import asyncio
from pathlib import Path
import sys

from fastapi.testclient import TestClient
import pytest

from app.operator.commands import OperatorCommand
from app.operator.service import OperatorJobManager, create_operator_app

TOKEN = "local-test-token"
ORIGIN = "http://127.0.0.1:8000"
HEADERS = {"origin": ORIGIN, "authorization": f"Bearer {TOKEN}"}


def test_operator_api_requires_exact_origin_and_token(tmp_path):
    """Reject cross-site and unauthenticated localhost requests."""
    application = create_operator_app(token=TOKEN, allowed_origin=ORIGIN, root=tmp_path)
    with TestClient(application) as client:
        assert client.get("/commands").status_code == 403
        assert client.get("/commands", headers={"origin": ORIGIN}).status_code == 401
        assert client.get("/commands", headers=HEADERS).status_code == 200


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1"])
def test_operator_accepts_both_loopback_names_on_the_selected_port(tmp_path, host):
    """Serve either browser name without relaxing the token or configured port."""
    origin = f"http://{host}:18080"
    app = create_operator_app(token=TOKEN, allowed_origin="http://localhost:18080", root=tmp_path)
    with TestClient(app) as client:
        response = client.options(
            "/commands",
            headers={
                "origin": origin,
                "access-control-request-method": "GET",
                "access-control-request-headers": "authorization",
            },
        )
        assert response.headers["access-control-allow-origin"] == origin
        assert client.get("/commands", headers={"origin": origin}).status_code == 401
        assert (
            client.get(
                "/commands", headers={"origin": origin, "authorization": f"Bearer {TOKEN}"}
            ).status_code
            == 200
        )


@pytest.mark.parametrize(
    "origin",
    ["http://localhost:3000", "https://localhost:8000", "http://example.com:8000"],
)
def test_operator_rejects_other_ports_protocols_and_hosts(tmp_path, origin):
    """Keep the paired loopback origins limited to the exact development port."""
    app = create_operator_app(token=TOKEN, allowed_origin=ORIGIN, root=tmp_path)
    with TestClient(app) as client:
        response = client.get(
            "/commands", headers={"origin": origin, "authorization": f"Bearer {TOKEN}"}
        )
        assert response.status_code == 403
        assert "access-control-allow-origin" not in response.headers


def test_job_runs_exact_argv_redacts_output_and_rejects_concurrency(tmp_path):
    """Run one fixed argv command with bounded redacted evidence."""
    command = OperatorCommand(
        "probe",
        "Probe",
        "Test command.",
        (sys.executable, "-c", "import time; print('api_key=sk-secret123456'); time.sleep(.2)"),
        Path("."),
        5,
        "verify",
    )
    manager = OperatorJobManager(tmp_path, {"probe": command})
    application = create_operator_app(
        token=TOKEN,
        allowed_origin=ORIGIN,
        root=tmp_path,
        manager=manager,
    )
    with TestClient(application) as client:
        started = client.post("/jobs", headers=HEADERS, json={"command_id": "probe"})
        assert started.status_code == 202
        conflict = client.post("/jobs", headers=HEADERS, json={"command_id": "probe"})
        assert conflict.status_code == 409
        job_id = started.json()["job_id"]
        for _ in range(50):
            result = client.get(f"/jobs/{job_id}", headers=HEADERS).json()
            if result["status"] != "running":
                break
            asyncio.run(asyncio.sleep(0.02))
    assert result["status"] == "succeeded"
    assert "sk-secret" not in result["output"]
    assert "[REDACTED]" in result["output"]


def test_running_job_can_be_cancelled_as_a_process_group(tmp_path):
    """Cancel one long-running child and retain a terminal job state."""
    command = OperatorCommand(
        "wait",
        "Wait",
        "Test cancellation.",
        (sys.executable, "-c", "import time; print('started', flush=True); time.sleep(30)"),
        Path("."),
        60,
        "verify",
    )
    manager = OperatorJobManager(tmp_path, {"wait": command})
    application = create_operator_app(
        token=TOKEN,
        allowed_origin=ORIGIN,
        root=tmp_path,
        manager=manager,
    )
    with TestClient(application) as client:
        started = client.post("/jobs", headers=HEADERS, json={"command_id": "wait"}).json()
        job_id = started["job_id"]
        for _ in range(50):
            current = client.get(f"/jobs/{job_id}", headers=HEADERS).json()
            if "started" in current["output"]:
                break
            asyncio.run(asyncio.sleep(0.02))
        cancelled = client.post(f"/jobs/{job_id}/cancel", headers=HEADERS)
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
