"""Command-line contracts: stable JSON, typed exits, and no leaked detail."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from typing import TypedDict, cast

from openai import OpenAIError
from pydantic import ValidationError
import pytest
from sqlalchemy.exc import OperationalError

from app import cli
from app.config import Settings, get_settings


class ErrorDetail(TypedDict):
    """Stable CLI error detail used by assertions."""

    code: str
    message: str


class FailurePayload(TypedDict):
    """Stable CLI failure envelope used by assertions."""

    status: str
    error: ErrorDetail


def error_payload(capsys) -> FailurePayload:
    """Read the failure envelope off stderr, asserting stdout stayed empty."""
    captured = capsys.readouterr()
    assert captured.out == ""
    return cast(FailurePayload, json.loads(captured.err))


def test_retrieve_defaults_to_the_configured_provider_and_prints_stable_json(
    monkeypatch,
    capsys,
):
    """Leave the provider to configuration and print one stable, sorted JSON object."""
    observed = {}

    async def run(args):
        """Record the parsed arguments and return one successful payload."""
        observed.update(vars(args))
        return {
            "status": "ok",
            "command": "retrieve",
            "query": args.query,
            "provider": args.provider or "deterministic",
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
    # No flag means no override: the configured EMBEDDING_PROVIDER stays in charge.
    assert observed["provider"] is None


def test_filters_construct_against_the_real_domain_model():
    """Build real RetrievalFilters from parsed flags, proving the field names match."""
    args = cli.arguments(
        [
            "retrieve",
            "--query",
            "revenue",
            "--issuer",
            "ACME",
            "--fiscal-year",
            "2024",
        ]
    )

    filters = cli._filters(args)

    assert filters.issuers == ("ACME",)
    assert filters.fiscal_years == (2024,)


def test_embed_missing_without_explicit_provider_is_a_typed_exit(capsys):
    """Refuse a backfill whose provider was not named, before any database access."""
    exit_code = cli.main(["retrieve", "--query", "risk", "--embed-missing"])

    payload = error_payload(capsys)
    assert exit_code == cli.ExitCode.INVALID_INPUT
    assert payload["error"]["code"] == "embed_missing_requires_provider"


def test_invalid_settings_are_a_typed_exit_without_values(monkeypatch, capsys):
    """Map a settings validation failure to a typed exit that echoes no input values."""

    async def failing(args):
        """Re-validate settings with a value the schema rejects."""
        Settings.model_validate({**get_settings().model_dump(), "embedding_batch_size": 0})
        raise AssertionError("validation should have failed")

    monkeypatch.setattr(cli, "_run_data_command", failing)

    exit_code = cli.main(["retrieve", "--query", "risk"])

    payload = error_payload(capsys)
    assert exit_code == cli.ExitCode.INVALID_INPUT
    assert payload["error"]["code"] == "invalid_configuration"
    assert "embedding_batch_size" in payload["error"]["message"]
    # Locations and messages only: the rejected input values themselves stay out.
    assert "input_value" not in payload["error"]["message"]


def test_provider_override_revalidates_the_openai_key_guard(monkeypatch, tmp_path):
    """Run the fail-closed key guard when the provider is overridden per invocation."""
    # Re-validation reads `.env` from the working directory again, so isolate the
    # checkout dotenv and every key slot rather than only the explicit key.
    monkeypatch.chdir(tmp_path)
    for name in (
        "OPENAI_API_KEY",
        "OPENAI_API_KEY_LOCAL",
        "OPENAI_API_KEY_DEV",
        "OPENAI_API_KEY_PROD",
    ):
        monkeypatch.delenv(name, raising=False)
    base = Settings(_env_file=None)

    with pytest.raises(ValidationError, match="MODE-selected OpenAI key slot is required"):
        cli._provider_settings(base, "openai")


def test_empty_query_is_a_typed_invalid_input_exit(capsys):
    """Reject a blank query as a typed invalid-input exit."""
    exit_code = cli.main(["retrieve", "--query", "   "])

    payload = error_payload(capsys)
    assert exit_code == cli.ExitCode.INVALID_INPUT
    assert payload["error"]["code"] == "empty_query"


def test_zero_k_is_a_typed_invalid_input_exit(capsys):
    """Reject a non-positive k as a typed invalid-input exit."""
    exit_code = cli.main(["retrieve", "--query", "risk", "-k", "0"])

    payload = error_payload(capsys)
    assert exit_code == cli.ExitCode.INVALID_INPUT
    assert payload["error"]["code"] == "invalid_k"


def test_ingest_requires_explicit_selection():
    """Reject unscoped ingestion before contacting the application."""
    with pytest.raises(cli.CliError):
        cli.arguments(["ingest", "--manifest", "manifest.json"])


@pytest.mark.parametrize("flag", ["--create-schema", "--recreate-schema"])
def test_ingest_cannot_reset_or_bootstrap_the_database(flag):
    """Keep first-run setup and destructive reset outside ingestion jobs."""
    with pytest.raises(cli.CliError):
        cli.arguments(["ingest", "--manifest", "manifest.json", "--selection", "tutorial", flag])


def test_ingest_submits_the_shared_job_contract(monkeypatch):
    """Return the exact application job state rather than run a second ingestion path."""
    from dataclasses import asdict

    from fastapi.encoders import jsonable_encoder
    import httpx

    from app.corpus_admin import AdminCommand, AdminJob

    job = AdminJob(
        "cli-job",
        AdminCommand("ingest_manifest", manifest="manifest.json", selection_id="tutorial"),
        "queued",
        "queued",
        0,
        None,
        "Queued",
    )
    calls = []

    def handle(request):
        """Capture a typed local application request without a network call."""
        calls.append(json.loads(request.content))
        assert request.headers["origin"] == "http://127.0.0.1:8000"
        return httpx.Response(200, json=jsonable_encoder(asdict(job)))

    client_type = httpx.AsyncClient
    monkeypatch.setattr(
        cli.httpx,
        "AsyncClient",
        lambda **kwargs: client_type(transport=httpx.MockTransport(handle), **kwargs),
    )
    args = cli.arguments(["ingest", "--manifest", "manifest.json", "--selection", "tutorial"])
    result = asyncio.run(cli._ingest(args))
    assert result["job_id"] == "cli-job"
    assert result["status"] == "queued"
    assert calls[0]["kind"] == "ingest_manifest"
    assert calls[0]["manifest"] == "manifest.json"
    assert calls[0]["selection_id"] == "tutorial"


def test_provider_unavailability_has_a_stable_nonsecret_exit(monkeypatch, capsys):
    """Name the provider failure by type without printing its detail."""

    async def unavailable(args):
        """Raise the failure this exit code is supposed to describe."""
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
    """Name the database failure by type without printing the URL."""

    async def unavailable(args):
        """Raise the failure this exit code is supposed to describe."""
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
    """Forward every bind option to the server, printing nothing."""
    observed = {}

    def serve(args):
        """Record the options the serve command forwarded."""
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
    """Expose all three commands when run as a module."""
    result = subprocess.run(
        [sys.executable, "-m", "app.cli", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert "{retrieve,ingest,serve}" in result.stdout


def test_help_does_not_load_runtime_settings():
    """Print help without loading settings that would reject this environment."""
    environment = dict(os.environ)
    environment["EMBEDDING_BATCH_SIZE"] = "0"
    result = subprocess.run(
        [sys.executable, "-m", "app.cli", "--help"],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert "{retrieve,ingest,serve}" in result.stdout
