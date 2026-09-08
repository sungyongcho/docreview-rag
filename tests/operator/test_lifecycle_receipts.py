"""The notification projection reads disposable receipts and never invokes lifecycle actions."""

import subprocess

import pytest

from app.operator.lifecycle_receipts import lifecycle_receipts
from scripts.stack.fresh import receipt_path, write_receipt


def test_lifecycle_receipt_is_read_only_and_uses_the_existing_path(tmp_path):
    """A real disposable Git directory exercises the shared receipt contract."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    assert lifecycle_receipts(tmp_path) == ()
    write_receipt(tmp_path, "start-fresh", status="succeeded", completed=["files"], restarted=False)
    path = receipt_path(tmp_path, "start-fresh")
    before = path.read_bytes()
    result = lifecycle_receipts(tmp_path)
    assert result[0].status == "succeeded" and result[0].restarted is False
    assert result[0].completed == ("files",)
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    "payload", ["broken", '{"command":"other"}', '{"command":"start-fresh","status":"invented"}']
)
def test_invalid_receipts_do_not_become_successful_notifications(tmp_path, payload):
    """Malformed or unknown outcomes fail without changing the saved file."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    path = receipt_path(tmp_path, "start-fresh")
    path.parent.mkdir(parents=True)
    path.write_text(payload)
    with pytest.raises(ValueError):
        lifecycle_receipts(tmp_path)
    assert path.read_text() == payload


def test_receipt_endpoint_requires_operator_auth_and_returns_only_recorded_fields(tmp_path):
    """The new read endpoint uses the existing origin/token boundary and never exposes a path."""
    from fastapi.testclient import TestClient

    from app.operator.service import create_operator_app

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    write_receipt(tmp_path, "start-fresh", status="failed", completed=["files"], error="ValueError")
    app = create_operator_app(
        token="fixture-token", allowed_origin="http://127.0.0.1:8000", root=tmp_path
    )
    with TestClient(app) as client:
        assert client.get("/lifecycle/receipts").status_code in {401, 403}
        response = client.get(
            "/lifecycle/receipts",
            headers={"origin": "http://127.0.0.1:8000", "authorization": "Bearer fixture-token"},
        )
    assert response.status_code == 200
    assert response.json()[0]["error"] == "ValueError"
    assert str(tmp_path) not in response.text
