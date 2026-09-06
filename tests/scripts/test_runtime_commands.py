"""Guard shell reset orchestration without deleting data or rebuilding services."""

import argparse
import time

import pytest

from scripts import runtime_commands as commands


class FakeClient:
    """Record shared web endpoints and provide a deterministic reset lifecycle."""

    def __init__(self, status="succeeded", expired=False):
        """Select the final reset outcome and preview validity."""
        self.calls = []
        self.status = status
        self.expired = expired

    def request(self, path, body=None):
        """Return one shared preview or reset result without external effects."""
        self.calls.append((path, body))
        if path == "/wipe/preview":
            return {
                "token": "private-preview-token",
                "confirmation": "WIPE test",
                "expires": time.time() + (-1 if self.expired else 300),
                "target": {"volume": "test_pg_data", "files": []},
            }
        if path == "/wipe" and body is not None:
            return {"id": "reset-1", "status": "running", "stage": "database_volume"}
        return {"id": "reset-1", "status": self.status}


@pytest.fixture
def reset(monkeypatch):
    """Replace only I/O boundaries, leaving orchestration and confirmation checks real."""
    client = FakeClient()
    builds = []
    monkeypatch.setattr(commands.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(commands, "operator_client", lambda root: client)
    monkeypatch.setattr("builtins.input", lambda prompt: "WIPE test")
    monkeypatch.setattr(commands.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(commands, "run", lambda mode, args, *, root: builds.append(args) or 0)
    return client, builds


def test_reset_shares_web_confirmation_and_waits_before_rebuild(reset, tmp_path, capsys):
    """Use the web preview token and terminal status before any build or restart."""
    client, builds = reset
    assert commands.fresh_start(tmp_path) == 0
    assert client.calls == [
        ("/wipe/preview", {}),
        ("/wipe", {"token": "private-preview-token", "confirmation": "WIPE test"}),
        ("/wipe", None),
    ]
    assert builds == [
        ["build", "--no-cache", "app"],
        ["up", "-d", "--no-build", "--force-recreate"],
    ]
    output = capsys.readouterr().out
    assert "private-preview-token" not in output
    assert "View reset status" in output


@pytest.mark.parametrize("answer", ["", "yes", "WIPE another-checkout"])
def test_wrong_confirmation_never_starts_reset(reset, tmp_path, monkeypatch, answer):
    """Only the exact web confirmation authorizes destructive execution."""
    client, builds = reset
    monkeypatch.setattr("builtins.input", lambda prompt: answer)
    assert commands.fresh_start(tmp_path) == 0
    assert client.calls == [("/wipe/preview", {})]
    assert builds == []


def test_noninteractive_reset_does_not_request_preview(reset, tmp_path, monkeypatch):
    """Piped input cannot bypass target review."""
    client, builds = reset
    monkeypatch.setattr(commands.sys.stdin, "isatty", lambda: False)
    with pytest.raises(commands.RuntimeCommandError, match="interactively"):
        commands.fresh_start(tmp_path)
    assert not client.calls and not builds


def test_expired_preview_does_not_start_reset(reset, tmp_path):
    """An expired token requires another preview and confirmation."""
    client, builds = reset
    client.expired = True
    with pytest.raises(commands.RuntimeCommandError, match="expired"):
        commands.fresh_start(tmp_path)
    assert len(client.calls) == 1 and not builds


@pytest.mark.parametrize("status", ["failed", "interrupted", "running"])
def test_incomplete_reset_never_builds(reset, tmp_path, status):
    """Failures and wait expiry leave recovery to the existing web controls."""
    client, builds = reset
    client.status = status
    with pytest.raises(commands.RuntimeCommandError):
        commands.fresh_start(tmp_path, timeout=-1 if status == "running" else 10)
    assert not builds


def test_failed_build_does_not_restart(reset, tmp_path, monkeypatch):
    """Do not report success or start services from a failed fresh image build."""
    calls = []
    monkeypatch.setattr(commands, "run", lambda mode, args, *, root: calls.append(args) or 7)
    assert commands.fresh_start(tmp_path) == 7
    assert calls == [["build", "--no-cache", "app"]]


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
            "http://127.0.0.1:8000/docreview-rag-agent/api/admin",
            "/corpus/jobs/",
            {"kind": "acquire_dart", "identifiers": ["005930"], "years": [2024]},
        )
    ]


def test_changed_reset_identity_stops_rebuild(reset, tmp_path, monkeypatch):
    """Do not mistake another terminal's reset for this command's completed operation."""
    client, builds = reset
    original = client.request

    def changed(path, body=None):
        """Replace only the polled operation identity."""
        result = original(path, body)
        if path == "/wipe" and body is None:
            result["id"] = "another-reset"
        return result

    monkeypatch.setattr(client, "request", changed)
    with pytest.raises(commands.RuntimeCommandError, match="identity changed"):
        commands.fresh_start(tmp_path)
    assert not builds


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
