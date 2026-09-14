"""Guard shell reset orchestration without deleting data or rebuilding services."""

import argparse
import time

import pytest

from scripts.stack import commands as commands, fresh


class FakeClient:
    """Record shared web endpoints and provide a deterministic reset lifecycle."""

    def __init__(self, status="succeeded", expired=False):
        """Select the final reset outcome and preview validity."""
        self.calls = []
        self.origin = "http://127.0.0.1:8000"
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
    monkeypatch.setattr(
        "builtins.input", lambda prompt: "yes" if prompt.startswith("Have you") else "WIPE test"
    )
    monkeypatch.setattr(commands, "receipt_path", lambda root, command: root / "receipt.json")
    monkeypatch.setattr(commands, "quickstart", lambda root, **options: builds.append(options) or 0)
    return client, builds


def test_normal_clean_start_uses_host_scope_without_web_preview(reset, tmp_path):
    """The default command bypasses the broader web preview that produced HTTP 409."""
    client, starts = reset
    assert commands.reset(tmp_path, sample=True) == 0
    assert client.calls == []
    assert starts == [{"reset": True, "keep_sources": False, "sample": True, "timeout": 1800}]


def test_wrong_confirmation_never_starts_reset(fresh_io, tmp_path, monkeypatch):
    """The new host cleaner cancels without submitting a Docker operation."""
    monkeypatch.setattr("builtins.input", lambda prompt: "yes")
    assert fresh.start_fresh(tmp_path, extreme=True) == 0
    fresh_io.assert_not_called()


def test_noninteractive_reset_does_not_request_preview(reset, tmp_path, monkeypatch):
    """Piped input cannot bypass reset target review."""
    client, builds = reset
    monkeypatch.setattr(commands.sys.stdin, "isatty", lambda: False)
    with pytest.raises(commands.RuntimeCommandError, match="interactively"):
        commands.reset(tmp_path)
    assert not client.calls and not builds


def test_expired_preview_does_not_start_reset(fresh_io, tmp_path, monkeypatch):
    """A host preview expires before any resource removal is accepted."""
    times = iter([0, 301])
    monkeypatch.setattr(fresh.time, "monotonic", lambda: next(times))
    with pytest.raises(ValueError, match="expired"):
        fresh.start_fresh(tmp_path, extreme=True)
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


def test_host_setup_failure_is_not_reported_as_success(reset, tmp_path, monkeypatch):
    """A failed guided setup keeps its failure code and never falls back to web deletion."""
    client, _ = reset
    monkeypatch.setattr(commands, "quickstart", lambda root, **options: 7)
    assert commands.reset(tmp_path) == 7
    assert not client.calls


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


@pytest.mark.parametrize("answers", [[""], ["no"], ["Y", ""], ["Y", "no"]])
def test_extreme_confirmation_cancellation_never_submits(fresh_io, tmp_path, monkeypatch, answers):
    """Either host extreme gate cancels before any mutation."""
    replies = iter(answers)
    monkeypatch.setattr("builtins.input", lambda prompt: next(replies))
    assert fresh.start_fresh(tmp_path, extreme=True) == 0
    fresh_io.assert_not_called()


def test_extreme_completion_does_not_claim_browser_deletion(fresh_io, tmp_path, capsys):
    """Host extreme completion schedules a browser reset instead of claiming deletion."""
    assert fresh.start_fresh(tmp_path, extreme=True) == 0
    output = capsys.readouterr().out
    assert "browser data will reset to defaults" in output
    assert "Other applications are unchanged" in output
    assert "deleted" not in output.lower()


def test_extreme_success_reports_scope_without_restart(fresh_io, tmp_path, monkeypatch, capsys):
    """Verified host cleanup ends with a quick-start instruction and no automatic restart."""
    from unittest.mock import Mock

    bootstrap = Mock()
    monkeypatch.setattr(fresh.subprocess, "run", bootstrap)
    assert fresh.start_fresh(tmp_path, extreme=True) == 0
    bootstrap.assert_not_called()
    assert "Run rag-dev start" in capsys.readouterr().out


@pytest.mark.parametrize("gate", [1, 2])
def test_extreme_eof_before_both_gates_never_submits(fresh_io, tmp_path, monkeypatch, gate):
    """EOF at either host confirmation leaves deletion unsubmitted."""
    count = 0

    def answer(prompt):
        """End interactive input at the selected confirmation boundary."""
        nonlocal count
        count += 1
        if count == gate:
            raise EOFError
        return "Y"

    monkeypatch.setattr("builtins.input", answer)
    assert fresh.start_fresh(tmp_path, extreme=True) == 0
    fresh_io.assert_not_called()


def test_extreme_plain_warning_and_noninteractive_guard(fresh_io, tmp_path, monkeypatch, capsys):
    """A noninteractive extreme command cannot authorize a host cleanup."""
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setattr(fresh.sys.stdin, "isatty", lambda: False)
    with pytest.raises(ValueError, match="interactively"):
        fresh.start_fresh(tmp_path, extreme=True)
    assert "\033[" not in capsys.readouterr().out
    fresh_io.assert_not_called()


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


def test_host_database_failure_is_reported_without_sql_disclosure(reset, monkeypatch, capsys):
    """The new host reset path returns failure without exposing raw database statement details."""
    from unittest.mock import Mock

    from sqlalchemy.exc import ProgrammingError

    error = ProgrammingError(
        "SELECT private-sql-marker", {"key": "private-parameter"}, Exception("private-db-detail")
    )
    monkeypatch.setattr(commands, "quickstart", Mock(side_effect=error))
    monkeypatch.setattr("sys.argv", ["commands", "reset"])
    assert commands.main() == 1
    output = capsys.readouterr()
    for private in ("private-sql-marker", "private-parameter", "private-db-detail"):
        assert private not in output.out + output.err
    assert output.err


@pytest.mark.parametrize("interruption", [EOFError, KeyboardInterrupt])
def test_host_interruption_points_to_schema_state_without_claiming_operator_evidence(
    reset, monkeypatch, capsys, interruption
):
    """A stopped host clean start returns interruption and preserves the source journal path."""
    from unittest.mock import Mock

    monkeypatch.setattr(commands, "quickstart", Mock(side_effect=interruption))
    monkeypatch.setattr("sys.argv", ["commands", "reset"])
    assert commands.main() == 130
    output = capsys.readouterr().err
    assert "data/.schema-recreate-journal" in output
    assert "rag-dev schema check" in output
    assert "rag-reset --status" not in output
    assert "No automatic retry or restart" in output


@pytest.fixture
def fresh_io(monkeypatch):
    """Keep orchestration checks isolated; real filesystem guards run in test_fresh."""
    from unittest.mock import Mock

    monkeypatch.setattr(fresh.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: "Y")
    monkeypatch.setattr(
        fresh, "inventory", lambda *a, **k: {"files": {}, "directories": [], "revert": []}
    )
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


def test_host_receipt_failure_is_not_overridden_by_older_web_success(reset, tmp_path, monkeypatch):
    """The reset command's own receipt determines its status when older web evidence differs."""
    (tmp_path / "receipt.json").write_text("{}")
    monkeypatch.setattr(commands, "fresh_status", lambda root, command: 1)
    assert commands.reset_status(tmp_path) == 1
