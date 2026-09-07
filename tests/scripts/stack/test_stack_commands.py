"""Guard shell reset orchestration without deleting data or rebuilding services."""

import argparse
import time

import pytest

from scripts.stack import commands as commands


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
        return {
            "id": "reset-1",
            "status": self.status,
            "completed": ["database_removed", "runtime_files_removed"],
            "removed_files": 0,
        }


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


@pytest.mark.parametrize(
    "payload",
    [
        b'{"diagnosis":{"code":"active_jobs","details":{"secret":"private-secret"},"remediation":["private-secret"]}}',
        b'{"diagnosis":{"code":"private-secret"},"detail":"private-secret"}',
        b"not-json private-secret",
    ],
)
def test_rejection_uses_only_allowlisted_diagnostics(monkeypatch, payload):
    """Do not echo response text, unknown codes, or remediation strings from HTTP errors."""
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
        client.request("/wipe/preview", {})
    assert "private-secret" not in str(error.value)
    assert "no reset was submitted" in str(error.value)
    assert (
        "Active jobs" in str(error.value)
        if b"active_jobs" in payload
        else "Cause unavailable" in str(error.value)
    )
    assert len(calls) == 1


@pytest.mark.parametrize("answers", [[""], ["no"], ["yes", ""], ["yes", "no"]])
def test_extreme_confirmation_cancellation_never_submits(reset, tmp_path, monkeypatch, answers):
    """Either default-No gate cancels before any wipe request or build."""
    client, builds = reset
    replies = iter(answers)
    monkeypatch.setattr("builtins.input", lambda prompt: next(replies))
    assert commands.fresh_start(tmp_path, extreme=True) == 0
    assert client.calls == [("/wipe/preview", {"extreme": True})]
    assert not builds


def test_extreme_completion_requires_browser_evidence(reset, tmp_path, monkeypatch):
    """Never claim browser deletion merely because the server returned succeeded."""
    client, builds = reset
    client.origin = "http://127.0.0.1:8000"
    replies = iter(["yes", "WIPE test"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(replies))
    with pytest.raises(commands.RuntimeCommandError, match="unverified"):
        commands.fresh_start(tmp_path, extreme=True)
    assert not builds


def test_extreme_success_reports_scope_without_restart(reset, tmp_path, monkeypatch, capsys):
    """Browser acknowledgement and completed deletion are required before reporting success."""
    client, builds = reset
    client.origin = "http://127.0.0.1:8000"
    original = client.request

    def request(path, body=None):
        """Supply verified completion of the exact operation."""
        result = original(path, body)
        if path == "/wipe" and body is None:
            result.update(browser_cleared=True, browser_origin=client.origin)
            result["completed"].append("extreme_complete")
        return result

    monkeypatch.setattr(client, "request", request)
    replies = iter(["yes", "WIPE test"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(replies))
    assert commands.fresh_start(tmp_path, extreme=True) == 0
    assert not builds
    assert client.calls[1][1]["backup_confirmed"] is True
    assert "Browser DocReview data deleted and acknowledged" in capsys.readouterr().out


@pytest.mark.parametrize("gate", [1, 2])
def test_extreme_eof_before_both_gates_never_submits(reset, tmp_path, monkeypatch, gate):
    """EOF at either gate leaves deletion unsubmitted."""
    client, builds = reset
    count = 0

    def answer(prompt):
        """End interactive input at the selected confirmation boundary."""
        nonlocal count
        count += 1
        if count == gate:
            raise EOFError
        return "yes"

    monkeypatch.setattr("builtins.input", answer)
    with pytest.raises(EOFError):
        commands.fresh_start(tmp_path, extreme=True)
    assert client.calls == [("/wipe/preview", {"extreme": True})]
    assert not builds


def test_extreme_plain_warning_and_noninteractive_guard(reset, tmp_path, monkeypatch, capsys):
    """Plain output retains the irreversible warning and cannot authorize deletion."""
    client, builds = reset
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setattr(commands.sys.stdin, "isatty", lambda: False)
    with pytest.raises(commands.RuntimeCommandError, match="interactively"):
        commands.fresh_start(tmp_path, extreme=True)
    output = capsys.readouterr().out
    assert "EXTREME RESET: NO BACKUP. IRREVERSIBLE DELETION." in output
    assert "\033[" not in output
    assert not client.calls and not builds


def test_status_is_read_only_without_configuration(reset, tmp_path, capsys):
    """A removed .env does not prevent status inspection or cause a reset submission."""
    client, builds = reset
    assert commands.reset_status(tmp_path) == 0
    assert client.calls == [("/wipe", None)]
    assert not builds
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
