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
from tests.support import load_settings


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


@pytest.mark.parametrize(
    ("argv", "code"),
    [
        pytest.param(["retrieve", "--query", "   "], "empty_query", id="blank-query"),
        pytest.param(["retrieve", "--query", "risk", "-k", "0"], "invalid_k", id="non-positive-k"),
        pytest.param(
            ["retrieve", "--query", "risk", "--embed-missing"],
            "embed_missing_requires_provider",
            id="backfill-without-a-named-provider",
        ),
    ],
)
def test_invalid_retrieve_arguments_are_typed_invalid_input_exits(capsys, argv, code):
    """Reject a blank query, a non-positive k and a backfill whose provider was not named
    as typed invalid-input exits, before any database access."""
    exit_code = cli.main(argv)

    payload = error_payload(capsys)
    assert exit_code == cli.ExitCode.INVALID_INPUT
    assert payload["error"]["code"] == code


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
    base = load_settings(Settings, env_file=None)

    with pytest.raises(ValidationError, match="MODE-selected OpenAI key slot is required"):
        cli._provider_settings(base, "openai")


def test_ingest_requires_explicit_selection():
    """Reject unscoped ingestion before contacting the application."""
    with pytest.raises(cli.CliError):
        cli.arguments(["ingest", "--manifest", "manifest.json"])


def test_ingest_submits_the_shared_job_contract(monkeypatch):
    """Return the exact application job state rather than run a second ingestion path."""
    from dataclasses import asdict

    from fastapi.encoders import jsonable_encoder
    import httpx

    from app.corpus_admin.types import AdminCommand, AdminJob

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


@pytest.mark.parametrize(
    ("argv", "failure", "error"),
    [
        pytest.param(
            ["retrieve", "--query", "risk", "--provider", "openai"],
            OpenAIError("credential and endpoint details must not be printed"),
            {
                "code": "provider_unavailable",
                "message": "embedding provider is unavailable (OpenAIError)",
            },
            id="embedding-provider",
        ),
        pytest.param(
            ["retrieve", "--query", "risk"],
            OperationalError("SELECT 1", {}, RuntimeError("secret database URL")),
            {
                "code": "database_unavailable",
                "message": "database is unavailable (OperationalError)",
            },
            id="database",
        ),
    ],
)
def test_unavailable_dependencies_have_stable_nonsecret_exits(
    monkeypatch, capsys, argv, failure, error
):
    """Name an unavailable provider or database by failure type without printing its detail."""

    async def unavailable(args):
        """Raise the dependency failure this exit code is supposed to describe."""
        raise failure

    monkeypatch.setattr(cli, "_run_data_command", unavailable)

    exit_code = cli.main(argv)

    payload = error_payload(capsys)
    assert exit_code == cli.ExitCode.UNAVAILABLE
    assert payload["error"] == error


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
    assert "{retrieve,ingest}" in result.stdout
