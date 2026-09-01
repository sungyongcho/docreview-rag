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


def test_provider_override_revalidates_the_openai_key_guard():
    """Run the fail-closed key guard when the provider is overridden per invocation."""
    base = Settings.model_validate({**get_settings().model_dump(), "openai_api_key": None})

    with pytest.raises(ValidationError, match="OPENAI_API_KEY is required"):
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


def test_missing_manifest_fails_before_database_access(tmp_path, capsys):
    """Fail on an absent manifest before any database access."""
    missing = tmp_path / "missing.json"

    exit_code = cli.main(["ingest", "--manifest", str(missing)])

    payload = error_payload(capsys)
    assert exit_code == cli.ExitCode.INVALID_FILE
    assert payload["error"] == {
        "code": "manifest_not_found",
        "message": f"Manifest file was not found: {missing}",
    }


def test_broken_manifest_json_fails_before_database_access(tmp_path, capsys):
    """Fail on unparseable manifest JSON before any database access."""
    manifest = tmp_path / "manifest.json"
    manifest.write_text('[{"ticker": "NVDA"}', encoding="utf-8")

    exit_code = cli.main(["ingest", "--manifest", str(manifest)])

    payload = error_payload(capsys)
    assert exit_code == cli.ExitCode.INVALID_FILE
    assert payload["error"]["code"] == "invalid_manifest_json"
    assert "line 1 column" in payload["error"]["message"]


def test_recreate_schema_is_an_explicit_destructive_ingest_option():
    """Expose rebuilding separately from non-destructive missing-table creation."""
    args = cli.arguments(["ingest", "--manifest", "manifest.json", "--recreate-schema"])

    assert args.recreate_schema is True
    assert args.create_schema is False


def test_schema_creation_and_recreation_are_mutually_exclusive():
    """Reject an ambiguous ingest request before opening the database."""
    with pytest.raises(cli.CliError, match="not allowed with argument"):
        cli.arguments(
            [
                "ingest",
                "--manifest",
                "manifest.json",
                "--create-schema",
                "--recreate-schema",
            ]
        )


def test_create_schema_reports_drift_before_parsing_the_corpus(monkeypatch):
    """Fail a stale database preflight without spending time parsing every filing."""
    import app.db.bootstrap as bootstrap
    import app.ingestion.seed as seed

    parsed = False

    async def drift(_engine):
        """Raise the compatibility failure returned by the live bootstrap."""
        raise bootstrap.SchemaDriftError("stale schema")

    def load(*_args, **_kwargs):
        """Record an invalid late parse if schema preflight did not stop the command."""
        nonlocal parsed
        parsed = True
        raise AssertionError("corpus parsing must not start")

    monkeypatch.setattr(bootstrap, "bootstrap_schema", drift)
    monkeypatch.setattr(seed, "load_seed_batch", load)
    args = cli.arguments(["ingest", "--manifest", "manifest.json", "--create-schema"])

    with pytest.raises(cli.CliError, match="stale schema") as excinfo:
        asyncio.run(cli._ingest(args))

    assert excinfo.value.code == "schema_drift"
    assert parsed is False


def test_recreate_schema_drops_then_bootstraps_before_persisting(monkeypatch):
    """Keep the destructive rebuild ordered behind parsing and ahead of writes."""
    import app.db.bootstrap as bootstrap
    import app.db.session as db_session
    import app.ingestion.seed as seed

    events = []
    batch = object()
    session = object()

    class Connection:
        """Record the metadata operation executed inside the rebuild transaction."""

        async def run_sync(self, operation):
            """Record the metadata operation executed by the transaction."""
            events.append(operation.__name__)

    class Begin:
        """Yield the recording connection as an async engine transaction."""

        async def __aenter__(self):
            return Connection()

        async def __aexit__(self, _exc_type, _exc, _traceback):
            return None

    class Engine:
        """Open the one recording rebuild transaction."""

        def begin(self):
            """Return the recording rebuild transaction."""
            return Begin()

    class SessionContext:
        """Yield the recording persistence session."""

        async def __aenter__(self):
            return session

        async def __aexit__(self, _exc_type, _exc, _traceback):
            return None

    def load(*_args, **_kwargs):
        """Return a validated batch before any destructive operation."""
        events.append("parse")
        return batch

    async def create(_engine):
        """Record current-schema bootstrap after the drop."""
        events.append("bootstrap")

    async def persist(received_session, received_batch, **_kwargs):
        """Record persistence after the rebuilt schema exists."""
        assert received_session is session
        assert received_batch is batch
        events.append("persist")
        return seed.SeedResult(documents=1, chunks=2)

    engine = Engine()
    monkeypatch.setattr(bootstrap, "bootstrap_schema", create)
    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "Session", SessionContext)
    monkeypatch.setattr(seed, "load_seed_batch", load)
    monkeypatch.setattr(seed, "persist_seed_batch_with_stats", persist)
    args = cli.arguments(["ingest", "--manifest", "manifest.json", "--recreate-schema"])

    result = asyncio.run(cli._ingest(args))

    assert result["documents"] == 1
    assert events == ["parse", "drop_all", "bootstrap", "persist"]


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
