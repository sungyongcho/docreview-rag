"""Fresh-start marker reads never create a reset or consume user browser state."""

import json
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from app.release import browser_reset
from app.release.app import create_release_app
from app.release.config import ReleaseSettings


def test_marker_is_absent_until_fresh_start_writes_it(tmp_path, monkeypatch):
    """Ordinary startup and metadata reads cannot introduce a reset."""
    marker = tmp_path / "browser-reset.json"
    monkeypatch.setattr(browser_reset, "BROWSER_RESET_PATH", marker)
    assert browser_reset.browser_reset_id() is None
    assert not marker.exists()
    reset_id = str(uuid4())
    marker.write_text(json.dumps({"reset_id": reset_id}))
    assert browser_reset.browser_reset_id() == reset_id
    assert browser_reset.browser_reset_id() == reset_id


def test_marker_is_rejected_when_invalid(tmp_path, monkeypatch):
    """Malformed metadata cannot accidentally authorize a browser reset."""
    marker = tmp_path / "browser-reset.json"
    monkeypatch.setattr(browser_reset, "BROWSER_RESET_PATH", marker)
    marker.write_text('{"reset_id":"not-a-reset"}')
    with pytest.raises(ValueError):
        browser_reset.browser_reset_id()


@pytest.mark.parametrize("environment", ["dev", "prod"])
def test_only_dev_capabilities_expose_the_checkout_reset(tmp_path, monkeypatch, environment):
    """A local cleanup receipt must not reset visitor data on a production deployment."""
    marker = tmp_path / "browser-reset.json"
    reset_id = str(uuid4())
    marker.write_text(json.dumps({"reset_id": reset_id}))
    monkeypatch.setattr(browser_reset, "BROWSER_RESET_PATH", marker)
    settings = ReleaseSettings(_env_file=None, mode="canned", DOCREVIEW_ENVIRONMENT=environment)
    with TestClient(create_release_app(settings)) as client:
        response = client.get("/capabilities")
        assert response.status_code == 200
        assert response.json()["browser_reset_id"] == (reset_id if environment == "dev" else None)
