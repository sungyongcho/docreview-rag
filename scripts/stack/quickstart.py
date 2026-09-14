"""Prepare a local first-run stack without replacing data or invoking model providers."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, build_opener

from dotenv import dotenv_values, set_key
from sqlalchemy.exc import SQLAlchemyError

from app.db.bootstrap import SchemaDriftError
from scripts.diagnostics.ollama import diagnose
from scripts.schema.recreate import run as recreate_schema
from scripts.schema.status import prepare_schema
from scripts.stack.__main__ import compose_command, compose_environment, run
from scripts.stack.environment import load_local_environment
from scripts.stack.fresh import write_receipt
from scripts.stack.prompts import SetupCancelledError, confirm, step
from scripts.stack.terminal import activity, run_step

ROOT = Path(__file__).resolve().parents[2]


def placeholder(value: str) -> bool:
    """Recognize empty values and the shipped example credentials without printing them."""
    lowered = value.strip().lower()
    return (
        not lowered
        or "<" in value
        or "your-" in lowered
        or "example.com" in lowered
        or "example.org" in lowered
    )


class ConfigurationError(ValueError):
    """Expose failing key names and redacted source-aware repair instructions."""

    def __init__(self, keys: tuple[str, ...], message: str) -> None:
        """Retain names only so guided repair never stores credentials in an error."""
        super().__init__(message)
        self.keys = keys


def configuration_value(key: str, value: str | None) -> str:
    """Show public embedding selectors while redacting credential and contact values."""
    if value is None:
        return "<unset>"
    if key in {"EMBEDDING_PROVIDER", "EMBEDDING_MODEL"}:
        return json.dumps(value)
    return "<set; hidden>" if value else "<empty>"


def validate_configuration(root: Path, *, mode: str = "dev") -> dict[str, str]:
    """Validate effective configuration and identify both file and shell sources safely."""
    path = root / ".env"
    if not path.exists():
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as handle:
            handle.write((root / ".env.example").read_text())
            handle.write(
                "\n# Required by the real-data Quick Start.\n"
                "EMBEDDING_PROVIDER=openai\nEMBEDDING_MODEL=text-embedding-3-large\n"
            )
        print("Created private .env from the template; enter your own credentials locally.")
    file_values = {key: value for key, value in dotenv_values(path).items() if value is not None}
    configured = file_values | dict(os.environ)
    key_slot = "OPENAI_API_KEY_LOCAL" if mode == "dev" else "OPENAI_API_KEY_PROD"
    requirements = {
        "SEC_USER_AGENT": "your real name and reachable email",
        "DART_API_KEY": "your DART key",
        key_slot: f"your {mode} OpenAI key",
        "EMBEDDING_PROVIDER": "openai",
        "EMBEDDING_MODEL": "text-embedding-3-large",
    }
    missing = [
        key
        for key in (("SEC_USER_AGENT", "DART_API_KEY", key_slot) if mode == "dev" else (key_slot,))
        if placeholder(configured.get(key, ""))
    ]
    if mode == "dev" and not re.search(r"\S+@\S+\.\S+", configured.get("SEC_USER_AGENT", "")):
        if "SEC_USER_AGENT" not in missing:
            missing.append("SEC_USER_AGENT")
    missing.extend(
        key
        for key in ("EMBEDDING_PROVIDER", "EMBEDDING_MODEL")
        if configured.get(key) != requirements[key]
    )
    if missing:
        lines = {}
        for number, line in enumerate(path.read_text().splitlines(), 1):
            match = re.match(r"\s*(?:export\s+)?([A-Za-z_][A-Za-z_0-9]*)\s*=", line)
            if match:
                lines[match[1]] = number
        details = ["Configuration blocked. Effective values and their sources:"]
        for key in missing:
            location = f"{path}:{lines[key]}" if key in lines else f"{path} (missing key)"
            source = "shell export" if key in os.environ else location
            details.append(
                f"  {key}: .env={configuration_value(key, file_values.get(key))}; "
                f"shell={configuration_value(key, os.environ.get(key))}; effective source={source}"
            )
            details.append(f"    File fix: edit {location}; set {key}={requirements[key]}.")
            if key in os.environ:
                details.append(f"    Shell fix: unset {key} (the export currently overrides .env).")
        details.append("No services were started by this configuration check.")
        raise ConfigurationError(tuple(missing), "\n".join(details))
    return load_local_environment(path, mode=mode)


def configure(root: Path, *, mode: str = "dev") -> dict[str, str]:
    """Let an interactive user repair configuration and resume at the same step."""
    while True:
        try:
            return validate_configuration(root, mode=mode)
        except ConfigurationError as error:
            print(str(error), flush=True)
            if not sys.stdin.isatty():
                raise
            print(
                "[f] Ignore failing shell exports for this invocation and use .env.\n"
                "[e] Set the two public embedding values in .env and this invocation.\n"
                "[r] Recheck after editing the named file; [q] cancel.\n"
                "Credentials are never printed or edited by these choices."
            )
            try:
                choice = input("Configuration choice [f/e/r/q; default q]: ").strip().lower()
            except EOFError:
                choice = "q"
            if choice == "f":
                for key in error.keys:
                    os.environ.pop(key, None)
                print(
                    "Using .env for failing keys in this invocation; parent shell exports remain."
                )
            elif choice == "e":
                for key, value in (
                    ("EMBEDDING_PROVIDER", "openai"),
                    ("EMBEDDING_MODEL", "text-embedding-3-large"),
                ):
                    set_key(root / ".env", key, value)
                    os.environ[key] = value
                print("Saved embedding settings; no embedding or model request was made.")
            elif choice != "r":
                raise SetupCancelledError(
                    "Configuration cancelled; no later setup step was run."
                ) from None


def wait_ready(origin: str, *, timeout: float = 180, mode: str = "dev") -> None:
    """Require actual API, database, schema, and DEV permission evidence after startup."""
    opener = build_opener(ProxyHandler({}))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with opener.open(
                origin
                + (
                    "/docreview-rag/api/admin/corpus/"
                    if mode == "dev"
                    else "/docreview-rag/api/ready/"
                ),
                timeout=5,
            ) as response:
                snapshot = json.load(response)
            if mode == "prod":
                corpus = snapshot.get("corpus", {})
                if (
                    snapshot.get("environment") == "prod"
                    and corpus.get("database_connected")
                    and corpus.get("schema_status") == "compatible"
                ):
                    return
            state = snapshot["status"] if mode == "dev" else {}
            if (
                state.get("database_connected")
                and state.get("schema_status") == "compatible"
                and state.get("writable")
            ):
                if state["provider"] != "openai":
                    raise ValueError(
                        "The running API is not using OpenAI embeddings. "
                        "Check effective configuration."
                    )
                return
        except HTTPError as error:
            if mode == "prod" and error.code == 503:
                snapshot = json.load(error)
                corpus = snapshot.get("corpus", {})
                if (
                    snapshot.get("environment") == "prod"
                    and corpus.get("database_connected")
                    and corpus.get("schema_status") == "compatible"
                ):
                    return
        except URLError, TimeoutError, ConnectionError:
            pass
        time.sleep(2)
    raise RuntimeError(
        "DEV readiness was not confirmed. Use rag-dev logs -f app and rag-dev doctor; "
        "existing data was retained."
    )


def report_services(root: Path, environment: dict[str, str], *, mode: str = "dev") -> None:
    """Report only this project's service state, without exposing container configuration."""
    output = subprocess.check_output(
        compose_command(root, mode, ["ps", "--all", "--format", "json"]),
        cwd=root,
        env=environment,
        text=True,
    ).strip()
    rows = (
        json.loads(output)
        if output.startswith("[")
        else [json.loads(line) for line in output.splitlines() if line.strip()]
    )
    services = {row["Service"]: row for row in rows}
    for name in ("db", "app", "web"):
        row = services.get(name)
        if row is None:
            status = "stopped (not created)"
        else:
            state, health = row.get("State", "unknown"), row.get("Health", "")
            if state == "running":
                status = {
                    "healthy": "already running / healthy",
                    "starting": "starting (health check pending)",
                    "unhealthy": "unhealthy; inspect rag-dev logs --tail 50 " + name,
                }.get(health, "running (no health check; server readiness not yet confirmed)")
            elif state in {"exited", "dead", "created"}:
                status = "stopped (" + state + ")"
            else:
                status = state
        print(f"  {name}: {status}", flush=True)


def ensure_database(root: Path, bindings: dict[str, str], *, mode: str = "dev") -> None:
    """Start only the selected local database and wait for its declared health check."""
    environment = compose_environment(mode, bindings)
    report_services(root, environment, mode=mode)
    if mode == "prod":
        from scripts.stack.prod import ensure_storage

        ensure_storage(root)
    run_step(
        "Stop the API before selecting the mode's database volume",
        compose_command(root, mode, ["stop", "app"]),
        cwd=root,
        env=environment,
    )
    run_step(
        "Start database and wait for health",
        compose_command(root, mode, ["up", "-d", "--wait", "--wait-timeout", "120", "db"]),
        cwd=root,
        env=environment,
    )


def start_ready(
    root: Path, bindings: dict[str, str], *, timeout: float = 180, mode: str = "dev"
) -> None:
    """Verify startup and offer one diagnosed, volume-preserving restart on failure."""
    origin = f"http://{bindings['DOCREVIEW_LOCAL_HOST']}:{bindings['APP_PORT']}"
    for attempt in range(2):
        try:
            result = run(mode, ["up", "--build", "-d"], root=root, quiet=True)
            if result:
                raise RuntimeError(f"{mode.upper()} startup command exited with status {result}.")
            report_services(root, compose_environment(mode, bindings), mode=mode)
            with activity("Verify server readiness"):
                wait_ready(origin, timeout=timeout, mode=mode)
            return
        except (ValueError, RuntimeError, OSError, subprocess.CalledProcessError) as error:
            print(f"Startup/readiness blocked: {error}", flush=True)
            print("Read-only diagnostics follow; no model will be loaded or invoked.")
            diagnose(root, origin, details=True)
            print(
                "Recovery in this checkout: rag-dev compose down && rag-dev compose up --build -d"
            )
            if attempt or not confirm(
                "Restart this checkout (stop, preserve data volumes, then rebuild/start)?"
            ):
                raise RuntimeError(
                    "Readiness is unconfirmed. Review the diagnosis and recovery commands above."
                ) from None
            if run(mode, ["down"], root=root):
                raise RuntimeError(
                    "Stopping this checkout failed; no restart was submitted."
                ) from None


def handoff(bindings: dict[str, str], *, mode: str = "dev") -> None:
    """Print the verified application and exact bilingual tutorial continuation."""
    origin = f"http://{bindings['DOCREVIEW_LOCAL_HOST']}:{bindings['APP_PORT']}"
    print(f"Server running ({mode.upper()}): {origin}/docreview-rag/")
    if mode == "prod":
        print("Server startup verified; corpus search readiness is reported separately by /ready.")
        print(
            "Saved data preparation: rag-prod prepare --local; no embedding generation is required."
        )
        return
    print(f"Quick Start - DEV ONLY: {origin}/docreview-rag/docs/en/quickstart-dev/#qs-web-1")
    print(f"Korean Quick Start - DEV ONLY: {origin}/docreview-rag/docs/ko/quickstart-dev/#qs-web-1")
    print(
        "Continue in the web: Quick Start - DEV ONLY, Web path, step 1: verify the environment; "
        "then acquire sources, parse and chunk, prepare embeddings, and explicitly compute BM25."
    )
    print("No filings were downloaded and no embedding or answer requests were made.")


def _prepare(
    root: Path,
    *,
    mode: str = "dev",
    reset: bool = False,
    keep_sources: bool = False,
    sample: bool = False,
    timeout: float = 180,
) -> int:
    """Guide one local setup, optionally previewing and confirming a host-side clean start."""
    step(1, 5, "Prerequisites", "Check Docker Compose; this step does not change services or data.")
    version = subprocess.check_output(
        ["docker", "compose", "version", "--short"], text=True
    ).strip()
    match = re.match(r"v?(\d+)\.(\d+)\.(\d+)", version)
    if not match or tuple(map(int, match.groups())) < (2, 24, 4):
        raise ValueError(
            "Docker Compose 2.24.4 or newer is required; check docker compose version."
        )
    step(
        2,
        5,
        "Configuration",
        "Read .env and shell overrides; offer explicit repairs before startup.",
    )
    bindings = configure(root, mode=mode)
    step(3, 5, "Local database", "Show this checkout's services; start its DB and wait for health.")
    try:
        ensure_database(root, bindings, mode=mode)
    except subprocess.CalledProcessError:
        print("Database startup failed. Inspect rag-dev status -a and rag-dev logs --tail 50 db.")
        print("Recovery: rag-dev compose down && rag-dev compose up --build -d")
        if not confirm(
            "Stop this checkout without deleting volumes and retry database startup once?"
        ):
            raise RuntimeError(
                "Database readiness remains blocked; no schema reset was submitted."
            ) from None
        if run(mode, ["down"], root=root):
            raise RuntimeError("Stopping this checkout failed; no retry was submitted.") from None
        ensure_database(root, bindings, mode=mode)
    step(
        4,
        5,
        "Reset preview" if reset else "Schema",
        "Preview ORM data and selected source scope; deletion requires uppercase Y."
        if reset
        else "Inspect compatibility; create schema only in an empty database.",
    )
    if reset:
        outcome = recreate_schema(
            root, keep_sources=keep_sources, sample=sample, restart_planned=True
        )
        if outcome != "succeeded":
            write_receipt(root, "reset", status=outcome)
            return 0 if outcome == "cancelled" else 1
    else:
        for attempt in range(2):
            url = f"postgresql+asyncpg://filing:filing@127.0.0.1:{bindings['DB_PORT']}/filing"
            try:
                created = asyncio.run(prepare_schema(url))
                break
            except (SchemaDriftError, ValueError) as error:
                print(f"Schema preparation blocked: {error}. Existing data was preserved.")
                print(
                    "Inspect: .venv/bin/python -m scripts.schema check\n"
                    "Preserve this DB: rag-dev schema recover --return-stage index\n"
                    "A separately confirmed destructive choice is rag-dev schema recreate."
                )
                if attempt or not confirm(
                    "After fixing DB_PORT or compatibility, retry this step?"
                ):
                    raise RuntimeError(
                        "Schema is still blocked; no automatic reset was submitted."
                    ) from None
                bindings = configure(root, mode=mode)
                ensure_database(root, bindings, mode=mode)
        print(
            "Empty database schema created." if created else "Existing schema and data preserved."
        )
    step(
        5,
        5,
        "Start and verify",
        "Build/start DEV, verify readiness, then continue in the web tutorial.",
    )
    start_ready(root, bindings, timeout=timeout, mode=mode)
    handoff(bindings, mode=mode)
    write_receipt(
        root,
        "reset" if reset else "start-quick",
        status="succeeded",
        completed=["configuration", "database", "schema", "readiness"],
    )
    return 0


def quickstart(
    root: Path,
    *,
    mode: str = "dev",
    reset: bool = False,
    keep_sources: bool = False,
    sample: bool = False,
    timeout: float = 180,
) -> int:
    """Retain one command receipt across success, cancellation, failure and interruption."""
    name = "reset" if reset else "start-quick"
    write_receipt(root, name, status="running", completed=[])
    try:
        return _prepare(
            root, mode=mode, reset=reset, keep_sources=keep_sources, sample=sample, timeout=timeout
        )
    except (Exception, KeyboardInterrupt) as error:
        write_receipt(
            root,
            name,
            status="interrupted" if isinstance(error, KeyboardInterrupt) else "failed",
            error=type(error).__name__,
        )
        raise


def main() -> int:
    """Report setup failures without dumping configuration or provider credentials."""
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verbose", "-vv", action="store_true")
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()
    if args.verbose:
        os.environ["DOCREVIEW_VERBOSE"] = "1"
    if args.status:
        from scripts.stack.fresh import status

        return status(ROOT, "start-quick")
    try:
        return quickstart(ROOT)
    except SetupCancelledError as error:
        print(str(error))
        return 0
    except (ValueError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
    except OSError, subprocess.CalledProcessError, SQLAlchemyError:
        print(
            "A local setup command failed. Check Docker/database access and rerun rag-dev start. "
            "No database was reset.",
            file=sys.stderr,
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
