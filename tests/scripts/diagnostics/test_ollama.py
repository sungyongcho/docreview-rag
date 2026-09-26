"""Read-only diagnosis of the active connection and namespace-specific failures."""

import json
import subprocess
from unittest.mock import Mock

import httpx
import pytest

from scripts.diagnostics.ollama import diagnose, failure_kind, main, valid_url


def app_client(*, mode="dev", paths=None, diagnostics=None) -> httpx.Client:
    """Serve canonical application routes and reject unexpected external traffic."""
    responses = {
        "/docreview-rag/api/release/": {"environment": mode},
        "/docreview-rag/api/health/": {"status": "ok"},
    }

    def respond(request):
        """Require trailing slashes used by the single Next entry point."""
        if paths is not None:
            paths.append(request.url.path)
        assert request.url.host == "localhost"
        if request.url.path == "/docreview-rag/api/admin/local-llm/diagnostics/":
            assert request.method == "POST"
            assert json.loads(request.content) == {}
            return httpx.Response(404 if diagnostics is None else 200, json=diagnostics)
        assert request.method == "GET"
        return httpx.Response(200, json=responses[request.url.path])

    return httpx.Client(transport=httpx.MockTransport(respond))


def test_prod_uses_actual_api_mode_and_sends_no_model_or_admin_requests(
    monkeypatch, capsys
) -> None:
    """A prod API wins over a stale dev shell and skips every model-related request."""
    monkeypatch.setenv("MODE", "dev")
    monkeypatch.setenv("LOCAL_LLM_BASE_URL", "http://private.example:11434")
    paths = []
    with app_client(mode="prod", paths=paths) as client:
        assert diagnose("http://localhost:8000", client=client) == 0
    assert paths == ["/docreview-rag/api/release/", "/docreview-rag/api/health/"]
    assert "intentionally disabled in prod" in capsys.readouterr().out


@pytest.mark.parametrize(
    "message, reason",
    [
        ("connection refused; http://secret:password@example.test", "refused"),
        ("TLS certificate failed private-test-key", "tls"),
        ("Name or service not known private-test-key", "dns"),
    ],
)
def test_transport_errors_never_return_private_exception_text(message, reason) -> None:
    """Connection diagnosis returns a fixed category instead of server or credential text."""
    request = httpx.Request("GET", "http://models.example")
    assert failure_kind(httpx.ConnectError(message, request=request)) == reason


@pytest.mark.parametrize(
    "url",
    [
        "http://user:password@private.example",
        "http://example?token=private",
        "file:///etc/passwd",
        "http://localhost:99999",
    ],
)
def test_invalid_or_secret_bearing_urls_never_reach_http(url) -> None:
    """Invalid addresses are rejected before any request or exception detail can escape."""
    with pytest.raises(ValueError):
        valid_url(url)


def test_authentication_status_is_redacted() -> None:
    """An HTTP error is reported by category without exposing the request URL."""
    request = httpx.Request("GET", "http://private.example?token=secret")
    response = httpx.Response(401, request=request)
    assert (
        failure_kind(httpx.HTTPStatusError("secret error", request=request, response=response))
        == "authentication"
    )


def diagnostic_report(*, available=True, reason="reachable"):
    """Provide the public metadata-only diagnostic response consumed by the CLI."""
    return {
        "server_name": "Default server",
        "available": available,
        "model_count": 1 if available else None,
        "answer_model_count": 1 if available else None,
        "models": [{"name": "installed-model", "selectable": True, "loaded": False}]
        if available
        else [],
        "checks": [
            {"id": "configuration", "status": "passed", "code": "configured", "remediation": []},
            {
                "id": "connection",
                "status": "passed" if available else "failed",
                "code": reason,
                "remediation": [] if available else ["check_ollama_service", "check_listener"],
            },
            {
                "id": "models",
                "status": "passed" if available else "unknown",
                "code": "answer_models_available" if available else "unconfirmed",
                "remediation": [] if available else ["check_ollama_models"],
            },
        ],
    }


def test_shared_diagnostics_avoids_duplicate_probes_and_reports_actual_models(capsys) -> None:
    """A current backend supplies all metadata without Docker or host-side re-probing."""
    paths = []
    with app_client(diagnostics=diagnostic_report(), paths=paths) as client:
        assert diagnose("http://localhost:8000", client=client) == 0
    assert paths == [
        "/docreview-rag/api/release/",
        "/docreview-rag/api/health/",
        "/docreview-rag/api/admin/local-llm/diagnostics/",
    ]
    output = capsys.readouterr().out
    assert 'Server: "Default server"' in output
    assert '"installed-model": answer-capable; not loaded (normal standby)' in output
    assert "Installed: 1; answer-capable: 1" in output
    assert "Advanced:" not in output


def test_shared_failure_has_actionable_setup_and_opt_in_namespace_details(
    monkeypatch, capsys
) -> None:
    """A refused backend connection explains manual remedies without running them."""
    forbidden = Mock(side_effect=AssertionError("diagnosis must not execute setup commands"))
    monkeypatch.setattr(subprocess, "run", forbidden)
    with app_client(diagnostics=diagnostic_report(available=False, reason="refused")) as client:
        assert diagnose("http://localhost:8000", client=client, details=True) == 1
    output = capsys.readouterr().out
    assert "connection refused" in output
    assert "systemctl status ollama --no-pager" in output
    assert "rag-dev doctor --setup" in output
    assert "Advanced:" in output
    assert "localhost is the app container" in output
    assert "ollama list" in output
    assert "no installed-model count was verified" in output
    assert "Installed: 0" not in output
    forbidden.assert_not_called()


def test_shared_blocked_selection_explains_reconnect_without_probing(capsys) -> None:
    """A disconnected server has no transport or model measurement to print as a result."""
    report = diagnostic_report(available=False)
    report["checks"] = [
        {
            "id": "configuration",
            "status": "blocked",
            "code": "disconnected",
            "remediation": ["select_server"],
        }
    ]
    with app_client(diagnostics=report) as client:
        assert diagnose("http://localhost:8000", client=client) == 1
    output = capsys.readouterr().out
    assert "Model inventory was not collected" in output
    assert "select Default server" in output
    assert "unexpected response" not in output
    assert "Installed: 0" not in output


@pytest.mark.parametrize("installed", [0, 1])
def test_shared_missing_answer_models_retains_measured_counts(capsys, installed) -> None:
    """An empty or embedding-only server was measured even though answers remain blocked."""
    report = diagnostic_report(available=False)
    report["model_count"] = installed
    report["answer_model_count"] = 0
    report["models"] = [{"name": "embedding", "selectable": False}] if installed else []
    report["checks"][1] = {
        "id": "connection",
        "status": "passed",
        "code": "reachable",
        "remediation": [],
    }
    report["checks"][2] = {
        "id": "models",
        "status": "blocked",
        "code": "no_answer_models",
        "remediation": ["check_ollama_models"],
    }
    with app_client(diagnostics=report) as client:
        assert diagnose("http://localhost:8000", client=client) == 1
    output = capsys.readouterr().out
    assert f"Installed: {installed}; answer-capable: 0" in output
    assert "inventory is unconfirmed" not in output
    assert "ollama list" in output
    assert "unexpected response" not in output


def test_shared_malformed_report_stops_without_legacy_probe(capsys) -> None:
    """An invalid new response is a failure, not permission to guess another server."""
    with app_client(diagnostics={"available": True, "checks": []}) as client:
        assert diagnose("http://localhost:8000", client=client) == 1
    assert "unexpected response" in capsys.readouterr().out


def test_setup_help_is_offline_and_only_prints_manual_commands(monkeypatch, capsys) -> None:
    """Setup guidance requires neither a configured service nor live provider access."""
    forbidden = Mock(side_effect=AssertionError("setup help is offline"))
    monkeypatch.setattr("sys.argv", ["diagnose_ollama", "--setup"])
    monkeypatch.setattr("scripts.diagnostics.ollama.httpx.Client", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr("scripts.diagnostics.ollama.dotenv_values", forbidden)
    assert main() == 0
    output = capsys.readouterr().out
    assert "Default server" in output
    assert "Add a server" in output
    assert "ollama --version" in output
    assert "ollama list" in output
    assert "ollama pull 'MODEL_NAME'" in output
    assert "Nothing was installed" in output
    forbidden.assert_not_called()


def test_default_command_derives_web_address_without_requiring_user_url(monkeypatch) -> None:
    """The ordinary alias finds DocReview from configured APP_PORT and default local host."""
    monkeypatch.setattr("sys.argv", ["diagnose_ollama"])
    monkeypatch.setenv("APP_PORT", "8123")
    monkeypatch.delenv("DOCREVIEW_LOCAL_HOST", raising=False)
    monkeypatch.setattr("scripts.diagnostics.ollama.dotenv_values", Mock(return_value={}))
    run = Mock(return_value=0)
    monkeypatch.setattr("scripts.diagnostics.ollama.diagnose", run)
    assert main() == 0
    assert run.call_args.args[0] == "http://127.0.0.1:8123"
    assert run.call_args.kwargs == {"details": False}
