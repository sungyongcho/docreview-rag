"""Read-only diagnosis of the active connection and namespace-specific failures."""

import json
from unittest.mock import Mock

import httpx
import pytest

from scripts.diagnostics.ollama import container_probe, diagnose, failure_kind, main, probe_url


@pytest.fixture(autouse=True)
def clean_model_environment(monkeypatch):
    """Keep local developer keys and mode settings out of metadata transport tests."""
    for key in (
        "MODE",
        "DOCREVIEW_ENVIRONMENT",
        "LOCAL_LLM_BASE_URL",
        "DOCREVIEW_LOCAL_LLM_BASE_URL",
        "LOCAL_LLM_API_KEY",
        "DOCREVIEW_LOCAL_LLM_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)


def app_client(
    *, config=None, local=None, mode="dev", paths=None, diagnostics=None
) -> httpx.Client:
    """Serve canonical application routes and reject unexpected external traffic."""
    if local is None:
        local = {
            "enabled": True,
            "models": [{"name": "gemma-test", "selectable": True, "loaded": False}],
        }
    if config is None:
        config = {
            "base_url": "http://saved.example:11434",
            "source": "saved",
            "protocol": "ollama",
            "local": local,
        }
    responses = {
        "/docreview-rag/api/release/": {"environment": mode},
        "/docreview-rag/api/health/": {"status": "ok"},
        "/docreview-rag/api/admin/local-llm/connection/": config,
        "/docreview-rag/api/ready/": {"review_engines": {"local": local}},
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


def test_healthy_unloaded_answer_model_is_available_without_a_load(
    tmp_path, monkeypatch, capsys
) -> None:
    """Normal standby remains usable and diagnosis never loads a model."""
    probe = Mock(side_effect=AssertionError("existing app metadata is sufficient"))
    monkeypatch.setattr("scripts.diagnostics.ollama.container_probe", probe)
    with app_client() as client:
        assert diagnose(tmp_path, "http://localhost:8000/docreview-rag/", client=client) == 0
    output = capsys.readouterr().out
    assert "normal standby" in output
    assert "Connection source: saved" in output
    probe.assert_not_called()


def test_diagnosis_uses_active_web_selection_instead_of_stale_dotenv(tmp_path, monkeypatch) -> None:
    """A failing saved endpoint is probed without reading the older initial model URL."""
    (tmp_path / ".env").write_text("LOCAL_LLM_BASE_URL=http://old.example:11434\n")
    local = {"enabled": True, "models": [{"name": "answer", "selectable": True}]}
    config = {
        "base_url": "https://active.example:12443",
        "source": "saved",
        "protocol": "ollama",
        "local": {"enabled": False, "reason": "unreachable"},
    }
    probe = Mock(return_value={"status": "reachable", "local": local})
    monkeypatch.setattr("scripts.diagnostics.ollama.container_probe", probe)
    with app_client(config=config, local=local) as client:
        assert diagnose(tmp_path, "http://localhost:8000", client=client) == 0
    probe.assert_called_once_with(tmp_path, "https://active.example:12443", "ollama")


def test_prod_uses_actual_api_mode_and_sends_no_model_or_admin_requests(
    tmp_path, monkeypatch, capsys
) -> None:
    """A prod API wins over a stale dev shell and skips every model-related request."""
    monkeypatch.setenv("MODE", "dev")
    monkeypatch.setenv("LOCAL_LLM_BASE_URL", "http://private.example:11434")
    forbidden = Mock(side_effect=AssertionError("prod must not probe"))
    monkeypatch.setattr("scripts.diagnostics.ollama.container_probe", forbidden)
    monkeypatch.setattr("scripts.diagnostics.ollama.probe_url", forbidden)
    paths = []
    with app_client(mode="prod", paths=paths) as client:
        assert diagnose(tmp_path, "http://localhost:8000", client=client) == 0
    assert paths == ["/docreview-rag/api/release/", "/docreview-rag/api/health/"]
    assert "intentionally disabled in prod" in capsys.readouterr().out
    forbidden.assert_not_called()


@pytest.mark.parametrize("source", ["disabled", "invalid"])
def test_disabled_or_corrupt_configuration_does_not_fall_back(
    tmp_path, monkeypatch, capsys, source
) -> None:
    """Explicit disabled or invalid saved state never triggers a guessed default probe."""
    forbidden = Mock(side_effect=AssertionError("no fallback server"))
    monkeypatch.setattr("scripts.diagnostics.ollama.container_probe", forbidden)
    config = {"source": source, "base_url": None, "local": {"enabled": False, "reason": source}}
    with app_client(config=config) as client:
        assert diagnose(tmp_path, "http://localhost:8000", client=client) == 1
    assert "reset to the initial settings" in capsys.readouterr().out
    forbidden.assert_not_called()


@pytest.mark.parametrize(
    "models", [[], [{"name": "embedding", "selectable": False, "loaded": False}]]
)
def test_zero_or_embedding_only_models_are_connected_but_not_answerable(
    tmp_path, monkeypatch, capsys, models
) -> None:
    """Reachable model metadata is distinct from having an answer-capable model."""
    monkeypatch.setattr(
        "scripts.diagnostics.ollama.container_probe", Mock(side_effect=AssertionError)
    )
    local = {"enabled": False, "reason": "no_answer_models", "models": models}
    with app_client(local=local) as client:
        assert diagnose(tmp_path, "http://localhost:8000", client=client) == 1
    output = capsys.readouterr().out
    assert "[PASS] 3." in output
    assert "[FAIL] 4." in output
    assert "answer-capable: 0" in output


def test_missing_docker_is_incomplete_and_does_not_guess_another_server(
    tmp_path, monkeypatch, capsys
) -> None:
    """Backend reachability stays unconfirmed when the container tool is unavailable."""
    monkeypatch.setattr("scripts.diagnostics.ollama.shutil.which", lambda program: None)
    local = {"enabled": False, "reason": "unreachable", "models": []}
    with app_client(local=local) as client:
        assert diagnose(tmp_path, "http://localhost:8000", client=client) == 2
    output = capsys.readouterr().out
    assert "[SKIP] 3." in output
    assert "docker_missing" in output


def model_transport(requests, *, capabilities=None) -> httpx.MockTransport:
    """Expose only native metadata endpoints; any generation or loading call fails."""

    def respond(request):
        """Return one installed model with no currently loaded models."""
        requests.append(request)
        if request.url.path == "/api/tags" and request.method == "GET":
            return httpx.Response(200, json={"models": [{"name": "test-model", "digest": "abc"}]})
        if request.url.path == "/api/ps" and request.method == "GET":
            return httpx.Response(200, json={"models": []})
        if request.url.path == "/api/show" and request.method == "POST":
            assert json.loads(request.content) == {"model": "test-model"}
            return httpx.Response(200, json={"capabilities": capabilities or ["completion"]})
        raise AssertionError(f"unexpected model operation: {request.method} {request.url.path}")

    return httpx.MockTransport(respond)


def test_native_probe_reads_metadata_without_model_loading() -> None:
    """Native tags, show, and ps alone establish available unloaded models."""
    requests = []
    result = probe_url("http://models.example:11434", transport=model_transport(requests))
    assert result["status"] == "reachable"
    assert result["local"]["models"][0]["loaded"] is False
    assert result["local"]["enabled"] is True
    assert {request.url.path for request in requests} == {"/api/tags", "/api/show", "/api/ps"}


@pytest.mark.parametrize("same_endpoint", [True, False])
def test_environment_key_is_only_forwarded_to_its_original_endpoint(
    monkeypatch, same_endpoint
) -> None:
    """A saved replacement URL cannot inherit credentials from another endpoint."""
    monkeypatch.setenv("LOCAL_LLM_BASE_URL", "http://original.example:11434")
    monkeypatch.setenv("LOCAL_LLM_API_KEY", "private-test-token")
    requests = []
    url = "http://original.example:11434" if same_endpoint else "http://new.example:11434"
    assert probe_url(url, transport=model_transport(requests))["status"] == "reachable"
    expected = "Bearer private-test-token" if same_endpoint else None
    assert all(request.headers.get("authorization") == expected for request in requests)


def test_container_probe_stops_before_http_in_prod(monkeypatch) -> None:
    """Even a directly invoked internal probe cannot contact a model from prod."""
    monkeypatch.setenv("MODE", "prod")

    def forbidden(request):
        """Record an unwanted network request as an explicit test failure."""
        raise AssertionError("prod network request")

    assert probe_url("http://model.example", transport=httpx.MockTransport(forbidden)) == {
        "status": "disabled",
        "reason": "disabled_in_prod",
    }


@pytest.mark.parametrize(
    "message, reason",
    [
        ("connection refused; http://secret:password@private.example", "refused"),
        ("TLS certificate failed private-test-key", "tls"),
        ("Name or service not known private-test-key", "dns"),
    ],
)
def test_transport_errors_never_return_private_exception_text(message, reason) -> None:
    """Connection diagnosis returns a fixed category instead of server or credential text."""

    def respond(request):
        """Simulate transport failures containing sensitive diagnostic internals."""
        raise httpx.ConnectError(message, request=request)

    result = probe_url("http://models.example", transport=httpx.MockTransport(respond))
    assert result == {"status": "unreachable", "reason": reason}


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

    def forbidden(request):
        """Reject any network attempt made before validating the supplied URL."""
        raise AssertionError("unexpected request")

    assert probe_url(url, transport=httpx.MockTransport(forbidden)) == {
        "status": "unreachable",
        "reason": "invalid_url",
    }


def test_authentication_status_is_redacted() -> None:
    """An HTTP error is reported by category without exposing the request URL."""
    request = httpx.Request("GET", "http://private.example?token=secret")
    response = httpx.Response(401, request=request)
    assert (
        failure_kind(httpx.HTTPStatusError("secret error", request=request, response=response))
        == "authentication"
    )


def test_container_probe_executes_in_existing_stable_project(tmp_path, monkeypatch) -> None:
    """Diagnosis uses exec in the current app, never compose up or another project name."""
    monkeypatch.setattr(
        "scripts.diagnostics.ollama.shutil.which", lambda program: "/usr/bin/docker"
    )
    execute = Mock(return_value=Mock(returncode=0, stdout='{"status":"reachable","local":{}}'))
    monkeypatch.setattr("scripts.diagnostics.ollama.subprocess.run", execute)
    container_probe(tmp_path, "http://active.example:11434", "ollama")
    command = execute.call_args.args[0]
    assert command[command.index("-p") + 1] == tmp_path.name
    assert "exec" in command and "up" not in command
    assert execute.call_args.kwargs["timeout"] == 10
    assert "def probe_url" in execute.call_args.kwargs["input"]


def test_malformed_config_response_is_reported_without_traceback(tmp_path, capsys) -> None:
    """An unexpected app version yields a bounded readable failure."""
    with app_client(config=[]) as client:
        assert diagnose(tmp_path, "http://localhost:8000", client=client) == 1
    assert "unexpected response" in capsys.readouterr().out


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


def test_shared_diagnostics_avoids_duplicate_probes_and_reports_actual_models(
    tmp_path, monkeypatch, capsys
) -> None:
    """A current backend supplies all metadata without Docker or host-side re-probing."""
    forbidden = Mock(side_effect=AssertionError("shared metadata must suffice"))
    monkeypatch.setattr("scripts.diagnostics.ollama.container_probe", forbidden)
    monkeypatch.setattr("scripts.diagnostics.ollama.probe_url", forbidden)
    paths = []
    with app_client(diagnostics=diagnostic_report(), paths=paths) as client:
        assert diagnose(tmp_path, "http://localhost:8000", client=client) == 0
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
    forbidden.assert_not_called()


def test_shared_failure_has_actionable_setup_and_opt_in_namespace_details(
    tmp_path, monkeypatch, capsys
) -> None:
    """A refused backend connection explains manual remedies without running them."""
    forbidden = Mock(side_effect=AssertionError("diagnosis must not execute setup commands"))
    monkeypatch.setattr("scripts.diagnostics.ollama.subprocess.run", forbidden)
    with app_client(diagnostics=diagnostic_report(available=False, reason="refused")) as client:
        assert diagnose(tmp_path, "http://localhost:8000", client=client, details=True) == 1
    output = capsys.readouterr().out
    assert "connection refused" in output
    assert "systemctl status ollama --no-pager" in output
    assert "rag-ollama-check --setup" in output
    assert "Advanced:" in output
    assert "localhost is the app container" in output
    assert "ollama list" in output
    assert "no installed-model count was verified" in output
    assert "Installed: 0" not in output
    forbidden.assert_not_called()


@pytest.mark.parametrize("code", ["disconnected", "invalid"])
def test_shared_blocked_selection_explains_reconnect_without_probing(
    tmp_path, monkeypatch, capsys, code
) -> None:
    """A disconnected server has no transport or model measurement to print as a result."""
    forbidden = Mock(side_effect=AssertionError("blocked selection must not probe"))
    monkeypatch.setattr("scripts.diagnostics.ollama.container_probe", forbidden)
    report = diagnostic_report(available=False)
    report["checks"] = [
        {
            "id": "configuration",
            "status": "blocked",
            "code": code,
            "remediation": ["select_server"],
        }
    ]
    with app_client(diagnostics=report) as client:
        assert diagnose(tmp_path, "http://localhost:8000", client=client) == 1
    output = capsys.readouterr().out
    assert "Model inventory was not collected" in output
    assert "select Default server" in output
    assert "unexpected response" not in output
    assert "Installed: 0" not in output
    forbidden.assert_not_called()


@pytest.mark.parametrize("installed", [0, 1])
def test_shared_missing_answer_models_retains_measured_counts(tmp_path, capsys, installed) -> None:
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
        assert diagnose(tmp_path, "http://localhost:8000", client=client) == 1
    output = capsys.readouterr().out
    assert f"Installed: {installed}; answer-capable: 0" in output
    assert "inventory is unconfirmed" not in output
    assert "ollama list" in output
    assert "unexpected response" not in output


def test_shared_malformed_report_stops_without_legacy_probe(tmp_path, monkeypatch, capsys) -> None:
    """An invalid new response is a failure, not permission to guess another server."""
    forbidden = Mock(side_effect=AssertionError("no legacy fallback for malformed metadata"))
    monkeypatch.setattr("scripts.diagnostics.ollama.container_probe", forbidden)
    with app_client(diagnostics={"available": True, "checks": []}) as client:
        assert diagnose(tmp_path, "http://localhost:8000", client=client) == 1
    assert "unexpected response" in capsys.readouterr().out
    forbidden.assert_not_called()


def test_setup_help_is_offline_and_only_prints_manual_commands(monkeypatch, capsys) -> None:
    """Setup guidance requires neither a configured service nor live provider access."""
    forbidden = Mock(side_effect=AssertionError("setup help is offline"))
    monkeypatch.setattr("sys.argv", ["diagnose_ollama", "--setup"])
    monkeypatch.setattr("scripts.diagnostics.ollama.httpx.Client", forbidden)
    monkeypatch.setattr("scripts.diagnostics.ollama.subprocess.run", forbidden)
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
    assert run.call_args.args[1] == "http://127.0.0.1:8123"
    assert run.call_args.kwargs == {"details": False}
