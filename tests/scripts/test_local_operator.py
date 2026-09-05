"""Private Operations ownership and safe detached lifecycle behavior."""

import json
import os
import signal
from unittest.mock import Mock

import pytest

from scripts.local_operator import LocalOperator, OperatorLifecycleError


@pytest.fixture
def operator(tmp_path, monkeypatch):
    """Keep per-checkout process state isolated from the running local stack."""
    monkeypatch.setattr("scripts.local_operator.tempfile.gettempdir", lambda: str(tmp_path))
    return LocalOperator(tmp_path / "checkout")


def test_reused_pid_is_never_signalled(operator, monkeypatch) -> None:
    """An unrelated process with an old PID does not become owned by its state file."""
    state = {
        "pid": 123,
        "start_time": "old",
        "token": "test",
        "origin": "http://localhost:8000",
        "port": "18001",
    }
    operator.state_path.write_text(json.dumps(state))
    monkeypatch.setattr(
        operator,
        "_identity",
        lambda pid: ("new", str(operator.root), ["python", "-m", "app.operator"]),
    )
    kill = Mock()
    monkeypatch.setattr(os, "kill", kill)
    operator.stop()
    kill.assert_not_called()
    assert not operator.state_path.exists()


def test_a_different_checkout_process_is_not_owned(operator, monkeypatch) -> None:
    """Matching module and PID start time do not authorize another repository's service."""
    monkeypatch.setattr(
        operator, "_identity", lambda pid: ("same", "/other", ["python", "-m", "app.operator"])
    )
    assert not operator._owned({"pid": 123, "start_time": "same"})


def test_owned_service_is_stopped_gracefully(operator, monkeypatch) -> None:
    """Only the saved service PID receives a graceful signal, without group-wide kills."""
    state = {
        "pid": 123,
        "start_time": "same",
        "token": "test",
        "origin": "http://localhost:8000",
        "port": "18001",
    }
    operator.state_path.write_text(json.dumps(state))
    monkeypatch.setattr(operator, "_owned", Mock(side_effect=[True, False]))
    kill = Mock()
    monkeypatch.setattr(os, "kill", kill)
    operator.stop()
    kill.assert_called_once_with(123, signal.SIGTERM)
    assert not operator.state_path.exists()


def test_start_is_detached_and_state_credentials_are_private(operator, monkeypatch) -> None:
    """A noninteractive child and owner-only state let `up -d` leave safely."""
    process = Mock(pid=123)
    process.poll.return_value = None
    launch = Mock(return_value=process)
    monkeypatch.setattr("scripts.local_operator.subprocess.Popen", launch)
    monkeypatch.setattr(
        operator,
        "_identity",
        lambda pid: ("same", str(operator.root), ["python", "-m", "app.operator"]),
    )
    monkeypatch.setattr(operator, "_reachable", lambda state: True)
    environment = operator.start(
        {
            "DOCREVIEW_LOCAL_HOST": "127.0.0.1",
            "APP_PORT": "8000",
            "DOCREVIEW_OPERATOR_PORT": "18001",
        }
    )
    assert launch.call_args.kwargs["start_new_session"] is True
    assert launch.call_args.kwargs["stdin"] == -3
    assert operator.state_path.stat().st_mode & 0o777 == 0o600
    assert operator.directory.stat().st_mode & 0o777 == 0o700
    assert (
        json.loads(operator.state_path.read_text())["token"]
        == environment["NEXT_PUBLIC_OPERATOR_TOKEN"]
    )


def test_corrupt_state_does_not_kill_or_start_a_process(operator, monkeypatch) -> None:
    """Invalid ownership data fails closed and leaves any existing process untouched."""
    operator.state_path.write_text("bad json")
    kill = Mock()
    monkeypatch.setattr(os, "kill", kill)
    with pytest.raises(OperatorLifecycleError, match="Cannot read"):
        operator.stop()
    kill.assert_not_called()
