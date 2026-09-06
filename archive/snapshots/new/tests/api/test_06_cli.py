from __future__ import annotations

import json
import subprocess
import sys

from openai import OpenAIError
from sqlalchemy.exc import OperationalError

from app import cli


def error_payload(capsys) -> dict[str, object]:
    captured = capsys.readouterr()
    assert captured.out == ""
    return json.loads(captured.err)


def test_retrieve_defaults_to_the_offline_provider_and_prints_stable_json(
    monkeypatch,
    capsys,
):
    observed = {}

    async def run(args):
        observed.update(vars(args))
        return {
            "status": "ok",
            "command": "retrieve",
            "query": args.query,
            "provider": args.provider,
            "hits": [],
        }

    monkeypatch.setattr(cli, "_run_data_command", run)

    exit_code = cli.main(["retrieve", "--query", "NVDA revenue"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == cli.ExitCode.OK
    assert payload == {
        "command": "retrieve",
        "hits": [],
        "provider": "deterministic",
        "query": "NVDA revenue",
        "status": "ok",
    }
    assert observed["k"] == 5
    assert observed["provider"] == "deterministic"


def test_empty_query_is_a_typed_invalid_input_exit(capsys):
    exit_code = cli.main(["retrieve", "--query", "   "])

    payload = error_payload(capsys)
    assert exit_code == cli.ExitCode.INVALID_INPUT
    assert payload["error"]["code"] == "empty_query"


def test_zero_k_is_a_typed_invalid_input_exit(capsys):
    exit_code = cli.main(["retrieve", "--query", "risk", "-k", "0"])

    payload = error_payload(capsys)
    assert exit_code == cli.ExitCode.INVALID_INPUT
    assert payload["error"]["code"] == "invalid_k"


def test_missing_manifest_fails_before_database_access(tmp_path, capsys):
    missing = tmp_path / "missing.json"

    exit_code = cli.main(["ingest", "--manifest", str(missing)])

    payload = error_payload(capsys)
    assert exit_code == cli.ExitCode.INVALID_FILE
    assert payload["error"] == {
        "code": "manifest_not_found",
        "message": f"manifest file does not exist: {missing}",
    }


def test_broken_manifest_json_fails_before_database_access(tmp_path, capsys):
    manifest = tmp_path / "manifest.json"
    manifest.write_text('[{"ticker": "NVDA"}', encoding="utf-8")

    exit_code = cli.main(["ingest", "--manifest", str(manifest)])

    payload = error_payload(capsys)
    assert exit_code == cli.ExitCode.INVALID_FILE
    assert payload["error"]["code"] == "invalid_manifest_json"
    assert "line 1 column" in payload["error"]["message"]


def test_provider_unavailability_has_a_stable_nonsecret_exit(monkeypatch, capsys):
    async def unavailable(args):
        raise OpenAIError("credential and endpoint details must not be printed")

    monkeypatch.setattr(cli, "_run_data_command", unavailable)

    exit_code = cli.main(["retrieve", "--query", "risk", "--provider", "openai"])

    payload = error_payload(capsys)
    assert exit_code == cli.ExitCode.UNAVAILABLE
    assert payload["error"] == {
        "code": "provider_unavailable",
        "message": "embedding provider is unavailable (OpenAIError)",
    }


def test_database_unavailability_has_a_stable_nonsecret_exit(monkeypatch, capsys):
    async def unavailable(args):
        raise OperationalError("SELECT 1", {}, RuntimeError("secret database URL"))

    monkeypatch.setattr(cli, "_run_data_command", unavailable)

    exit_code = cli.main(["retrieve", "--query", "risk"])

    payload = error_payload(capsys)
    assert exit_code == cli.ExitCode.UNAVAILABLE
    assert payload["error"] == {
        "code": "database_unavailable",
        "message": "database is unavailable (OperationalError)",
    }


def test_serve_passes_every_runtime_option_to_uvicorn(monkeypatch, capsys):
    observed = {}

    def serve(args):
        observed.update(vars(args))

    monkeypatch.setattr(cli, "_serve", serve)

    exit_code = cli.main(
        [
            "serve",
            "--host",
            "0.0.0.0",
            "--port",
            "9000",
            "--workers",
            "2",
            "--log-level",
            "warning",
        ]
    )

    assert exit_code == cli.ExitCode.OK
    assert capsys.readouterr() == ("", "")
    assert observed == {
        "command": "serve",
        "host": "0.0.0.0",
        "port": 9000,
        "workers": 2,
        "log_level": "warning",
    }


def test_python_module_entrypoint_exposes_all_commands():
    result = subprocess.run(
        [sys.executable, "-m", "app.cli", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert "{retrieve,ingest,serve}" in result.stdout
