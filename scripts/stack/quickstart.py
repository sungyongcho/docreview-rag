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
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener

from dotenv import dotenv_values, set_key
from sqlalchemy.exc import SQLAlchemyError

from app.db.bootstrap import SchemaDriftError
from scripts.diagnostics.ollama import diagnose
from scripts.schema.recreate import run as recreate_schema
from scripts.schema.status import prepare_schema
from scripts.stack.__main__ import compose_command, compose_environment, run
from scripts.stack.environment import load_local_environment
from scripts.stack.prompts import SetupCancelledError, confirm, step

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


def validate_configuration(root: Path) -> dict[str, str]:
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
    requirements = {
        "SEC_USER_AGENT": "your real name and reachable email",
        "DART_API_KEY": "your DART key",
        "OPENAI_API_KEY_LOCAL": "your development OpenAI key",
        "EMBEDDING_PROVIDER": "openai",
        "EMBEDDING_MODEL": "text-embedding-3-large",
    }
    missing = [
        key
        for key in ("SEC_USER_AGENT", "DART_API_KEY", "OPENAI_API_KEY_LOCAL")
        if placeholder(configured.get(key, ""))
    ]
    if not re.search(r"\S+@\S+\.\S+", configured.get("SEC_USER_AGENT", "")):
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
    return load_local_environment(path, mode="dev")


def configure(root: Path) -> dict[str, str]:
    """Let an interactive user repair configuration and resume at the same step."""
    while True:
        try:
            return validate_configuration(root)
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


def wait_ready(origin: str, *, timeout: float = 180) -> None:
    """Require actual API, database, schema, and DEV permission evidence after startup."""
    opener = build_opener(ProxyHandler({}))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with opener.open(
                origin + "/docreview-rag-agent/api/admin/corpus/", timeout=5
            ) as response:
                snapshot = json.load(response)
            state = snapshot["status"]
            if (
                state["database_connected"]
                and state["schema_status"] == "compatible"
                and state["writable"]
            ):
                if state["provider"] != "openai":
                    raise ValueError(
                        "The running API is not using OpenAI embeddings. "
                        "Check effective configuration."
                    )
                return
        except URLError, TimeoutError, ConnectionError:
            pass
        time.sleep(2)
    raise RuntimeError(
        "DEV readiness was not confirmed. Use rag-dev logs -f app and rag-ollama-check; "
        "existing data was retained."
    )


def report_services(root: Path, environment: dict[str, str]) -> None:
    """Report only this project's service state, without exposing container configuration."""
    output = subprocess.check_output(
        compose_command(root, "dev", ["ps", "--all", "--format", "json"]),
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


def ensure_database(root: Path, bindings: dict[str, str]) -> None:
    """Start only the selected local database and wait for its declared health check."""
    environment = compose_environment("dev", bindings)
    report_services(root, environment)
    subprocess.run(
        compose_command(root, "dev", ["up", "-d", "--wait", "--wait-timeout", "120", "db"]),
        cwd=root,
        env=environment,
        check=True,
    )


def start_ready(root: Path, bindings: dict[str, str], *, timeout: float = 180) -> None:
    """Verify startup and offer one diagnosed, volume-preserving restart on failure."""
    origin = f"http://{bindings['DOCREVIEW_LOCAL_HOST']}:{bindings['APP_PORT']}"
    for attempt in range(2):
        try:
            result = run("dev", ["up", "--build", "-d"], root=root)
            if result:
                raise RuntimeError(f"DEV startup command exited with status {result}.")
            report_services(root, compose_environment("dev", bindings))
            wait_ready(origin, timeout=timeout)
            return
        except (ValueError, RuntimeError, OSError, subprocess.CalledProcessError) as error:
            print(f"Startup/readiness blocked: {error}", flush=True)
            print("Read-only diagnostics follow; no model will be loaded or invoked.")
            diagnose(root, origin, details=True)
            print("Recovery in this checkout: rag-dev down && rag-dev up --build -d")
            if attempt or not confirm(
                "Restart this checkout (stop, preserve data volumes, then rebuild/start)?"
            ):
                raise RuntimeError(
                    "Readiness is unconfirmed. Review the diagnosis and recovery commands above."
                ) from None
            if run("dev", ["down"], root=root):
                raise RuntimeError(
                    "Stopping this checkout failed; no restart was submitted."
                ) from None


def handoff(bindings: dict[str, str]) -> None:
    """Print the verified application and exact bilingual tutorial continuation."""
    origin = f"http://{bindings['DOCREVIEW_LOCAL_HOST']}:{bindings['APP_PORT']}"
    print(f"Service ready: {origin}/docreview-rag-agent/")
    print(f"Quick Start - DEV ONLY: {origin}/docreview-rag-agent/docs/en/quickstart-dev/#qs-web-1")
    print(
        "Korean Quick Start - DEV ONLY: "
        f"{origin}/docreview-rag-agent/docs/ko/quickstart-dev/#qs-web-1"
    )
    print(
        "Continue in the web: Quick Start - DEV ONLY, Web path, step 1: verify the environment; "
        "then acquire sources, parse and chunk, prepare embeddings, and explicitly compute BM25."
    )
    print("No filings were downloaded and no embedding or answer requests were made.")


def quickstart(
    root: Path,
    *,
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
    bindings = configure(root)
    step(3, 5, "Local database", "Show this checkout's services; start its DB and wait for health.")
    try:
        ensure_database(root, bindings)
    except subprocess.CalledProcessError:
        print("Database startup failed. Inspect rag-dev ps -a and rag-dev logs --tail 50 db.")
        print("Recovery: rag-dev down && rag-dev up --build -d")
        if not confirm(
            "Stop this checkout without deleting volumes and retry database startup once?"
        ):
            raise RuntimeError(
                "Database readiness remains blocked; no schema reset was submitted."
            ) from None
        if run("dev", ["down"], root=root):
            raise RuntimeError("Stopping this checkout failed; no retry was submitted.") from None
        ensure_database(root, bindings)
    step(
        4,
        5,
        "Reset preview" if reset else "Schema",
        "Preview ORM data and selected source scope; deletion requires the exact typed phrase."
        if reset
        else "Inspect compatibility; create schema only in an empty database.",
    )
    if reset:
        outcome = recreate_schema(
            root, keep_sources=keep_sources, sample=sample, restart_planned=True
        )
        if outcome != "succeeded":
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
                    "Preserve this DB: rag-schema recover --return-stage index\n"
                    "A separately confirmed destructive choice is rag-schema recreate."
                )
                if attempt or not confirm(
                    "After fixing DB_PORT or compatibility, retry this step?"
                ):
                    raise RuntimeError(
                        "Schema is still blocked; no automatic reset was submitted."
                    ) from None
                bindings = configure(root)
                ensure_database(root, bindings)
        print(
            "Empty database schema created." if created else "Existing schema and data preserved."
        )
    step(
        5,
        5,
        "Start and verify",
        "Build/start DEV, verify readiness, then continue in the web tutorial.",
    )
    start_ready(root, bindings, timeout=timeout)
    handoff(bindings)
    return 0


def main() -> int:
    """Report setup failures without dumping configuration or provider credentials."""
    try:
        return quickstart(ROOT)
    except SetupCancelledError as error:
        print(str(error))
        return 0
    except (ValueError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
    except OSError, subprocess.CalledProcessError, SQLAlchemyError:
        print(
            "A local setup command failed. Check Docker/database access and rerun rag-quickstart. "
            "No database was reset.",
            file=sys.stderr,
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
