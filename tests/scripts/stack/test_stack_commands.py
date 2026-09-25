"""Guard shell reset orchestration without deleting data or rebuilding services."""

import argparse

import pytest

from scripts.stack import commands as commands, fresh


class FakeClient:
    """Record shared web endpoints and provide a deterministic reset result."""

    def __init__(self, status="succeeded"):
        """Select the final reset outcome."""
        self.calls = []
        self.origin = "http://127.0.0.1:8000"
        self.status = status

    def request(self, path, body=None):
        """Return one shared reset result without external effects."""
        self.calls.append((path, body))
        return {
            "id": "reset-1",
            "status": self.status,
            "completed": ["database_removed", "runtime_files_removed"],
            "removed_files": 0,
        }


@pytest.fixture
def reset(monkeypatch):
    """Replace only the operator connection, leaving status parsing real."""
    client = FakeClient()
    monkeypatch.setattr(commands, "operator_client", lambda root: client)
    return client


def test_wrong_confirmation_never_starts_reset(fresh_io, tmp_path, monkeypatch):
    """The new host cleaner cancels without submitting a Docker operation."""
    monkeypatch.setattr("builtins.input", lambda prompt: "yes")
    assert fresh.start_fresh(tmp_path) == 0
    fresh_io.assert_not_called()


def test_expired_preview_does_not_start_reset(fresh_io, tmp_path, monkeypatch):
    """A host preview expires before any resource removal is accepted."""
    times = iter([0, 301])
    monkeypatch.setattr(fresh.time, "monotonic", lambda: next(times))
    with pytest.raises(ValueError, match="expired"):
        fresh.start_fresh(tmp_path)
    fresh_io.assert_not_called()


@pytest.mark.parametrize("failure", [RuntimeError, PermissionError])
def test_incomplete_reset_never_builds(fresh_io, tmp_path, monkeypatch, failure):
    """Partial cleanup errors never proceed into the bootstrap subprocess."""
    from unittest.mock import Mock

    monkeypatch.setattr(fresh, "remove_files", Mock(side_effect=failure("fixture failure")))
    bootstrap = Mock()
    monkeypatch.setattr(fresh.subprocess, "run", bootstrap)
    with pytest.raises(failure):
        fresh.start_fresh(tmp_path)
    bootstrap.assert_not_called()


def test_corpus_submits_the_web_job_contract(tmp_path, monkeypatch):
    """Keep terminal acquisition jobs visible in the same browser queue."""
    calls = []
    monkeypatch.setattr(commands.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: "y")
    monkeypatch.setattr(
        commands.LocalClient,
        "request",
        lambda self, path, body=None: (
            calls.append((self.base, path, body)) or {"job_id": "test-job"}
        ),
    )
    args = argparse.Namespace(
        kind="acquire_dart",
        identifier=["005930"],
        year=[2024],
        manifest=None,
        selection=None,
        expected_documents=None,
    )
    assert commands.corpus(args, tmp_path) == 0
    assert calls == [
        (
            "http://127.0.0.1:8000/docreview-rag/api/admin",
            "/corpus/jobs/",
            {"kind": "acquire_dart", "identifiers": ["005930"], "years": [2024]},
        )
    ]


def test_changed_reset_identity_stops_rebuild(fresh_io, tmp_path, monkeypatch):
    """Changed resource IDs invalidate a confirmed preview before deletion."""
    values = iter(
        [
            {"docker": ["docker"], "containers": [], "volumes": [], "images": []},
            {"docker": ["docker"], "containers": ["new-container"], "volumes": [], "images": []},
        ]
    )
    monkeypatch.setattr(fresh, "docker_inventory", lambda *a, **k: next(values))
    with pytest.raises(ValueError, match="Preview changed"):
        fresh.start_fresh(tmp_path)
    fresh_io.assert_not_called()


def test_client_preserves_web_auth_and_does_not_retry_errors(monkeypatch):
    """Keep tokens in headers and avoid replaying an uncertain mutation."""
    from urllib.error import HTTPError

    client = commands.LocalClient(
        "http://127.0.0.1:18001", "http://127.0.0.1:8000", "private-token"
    )
    requests = []

    def reject(request, timeout):
        """Record one attempted request without revealing sensitive server details."""
        requests.append(request)
        raise HTTPError(request.full_url, 409, "private-token", {}, None)

    monkeypatch.setattr(client.opener, "open", reject)
    with pytest.raises(commands.RuntimeCommandError, match="HTTP 409") as error:
        client.request("/wipe", {"token": "preview-token", "confirmation": "WIPE test"})
    assert len(requests) == 1
    assert requests[0].get_header("Authorization") == "Bearer private-token"
    assert requests[0].get_header("Origin") == "http://127.0.0.1:8000"
    assert "private-token" not in str(error.value)


def test_status_reads_the_unified_job_board(monkeypatch, tmp_path, capsys):
    """CLI status reads historical jobs through the same record projection as the UI."""
    from types import SimpleNamespace

    paths = []

    def request(path):
        """Record a read without replaying any stored command."""
        paths.append(path)
        return {"jobs": []}

    monkeypatch.setattr(
        commands,
        "load_local_environment",
        lambda *a, **k: {"DOCREVIEW_LOCAL_HOST": "127.0.0.1", "APP_PORT": "8000"},
    )
    monkeypatch.setattr(commands, "LocalClient", lambda *a, **k: SimpleNamespace(request=request))
    assert commands.corpus(argparse.Namespace(kind="status"), tmp_path) == 0
    assert paths == ["/jobs/"]
    assert '"jobs"' in capsys.readouterr().out


@pytest.mark.parametrize(
    "payload",
    [
        b'{"diagnosis":{"code":"active_jobs","details":{"secret":"private-secret"},"remediation":["private-secret"]}}',
        b'{"diagnosis":{"code":"private-secret"},"detail":"private-secret"}',
        b"not-json private-secret",
    ],
)
def test_rejection_uses_only_the_generic_message(monkeypatch, payload):
    """Do not echo response text, diagnosis codes, or remediation strings from HTTP errors."""
    from io import BytesIO
    from urllib.error import HTTPError

    client = commands.LocalClient("http://127.0.0.1", "http://127.0.0.1")
    calls = []

    def reject(request, timeout):
        """Return one rejection containing deliberately sensitive arbitrary fields."""
        calls.append(request)
        raise HTTPError(request.full_url, 409, "private-secret", {}, BytesIO(payload))

    monkeypatch.setattr(client.opener, "open", reject)
    with pytest.raises(commands.RuntimeCommandError) as error:
        client.request("/corpus/jobs/", {})
    assert "private-secret" not in str(error.value)
    assert str(error.value) == (
        "Request rejected (HTTP 409). Cause unavailable; check Reset diagnosis. "
        "Execution may be uncertain. Run rag-dev reset data --local --status "
        "before any resubmission. No automatic retry was attempted."
    )
    assert len(calls) == 1


def test_completion_does_not_claim_browser_deletion(fresh_io, tmp_path, capsys):
    """Host completion schedules a browser reset instead of claiming deletion."""
    assert fresh.start_fresh(tmp_path) == 0
    output = capsys.readouterr().out
    assert "browser data will reset to defaults" in output
    assert "Other applications are unchanged" in output
    assert "deleted" not in output.lower()


def test_plain_warning_and_noninteractive_guard(fresh_io, tmp_path, monkeypatch, capsys):
    """A noninteractive command cannot authorize a host cleanup."""
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setattr(fresh.sys.stdin, "isatty", lambda: False)
    with pytest.raises(ValueError, match="interactively"):
        fresh.start_fresh(tmp_path)
    assert "\033[" not in capsys.readouterr().out
    fresh_io.assert_not_called()


def test_status_is_read_only_without_configuration(reset, tmp_path, capsys):
    """A removed .env does not prevent status inspection or cause a reset submission."""
    client = reset
    assert commands.reset_status(tmp_path) == 0
    assert client.calls == [("/wipe", None)]
    assert "Reset status: succeeded" in capsys.readouterr().out


def test_operator_connection_uses_recorded_origin_without_env(tmp_path, monkeypatch):
    """Use verified launch origin after custom-port .env configuration has been deleted."""
    from scripts.stack.operator import LocalOperator

    operator = LocalOperator(tmp_path)
    state = {"port": 39123, "origin": "http://127.0.0.1:39124", "token": "private-token"}
    monkeypatch.setattr(operator, "_read", lambda: state)
    monkeypatch.setattr(operator, "_owned", lambda value: True)
    monkeypatch.setattr(operator, "_reachable", lambda value: True)
    assert operator.client_connection() == (
        "http://127.0.0.1:39123",
        state["origin"],
        state["token"],
    )
    assert not (tmp_path / ".env").exists()


@pytest.fixture
def fresh_io(monkeypatch):
    """Keep orchestration checks isolated; real filesystem guards run in test_fresh."""
    from unittest.mock import Mock

    monkeypatch.setattr(fresh.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: "Y")
    monkeypatch.setattr(fresh, "inventory", lambda *a, **k: {"files": {}, "directories": []})
    monkeypatch.setattr(
        fresh,
        "docker_inventory",
        lambda *a, **k: {"docker": ["docker"], "containers": [], "volumes": [], "images": []},
    )
    monkeypatch.setattr(fresh, "write_receipt", lambda *a, **k: None)
    monkeypatch.setattr(fresh, "LocalOperator", lambda root: Mock())
    execution = Mock()
    monkeypatch.setattr(fresh, "run_step", execution)
    return execution
