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

from dotenv import dotenv_values
from sqlalchemy.exc import SQLAlchemyError

from app.db.bootstrap import SchemaDriftError
from scripts.schema.status import prepare_schema
from scripts.stack.__main__ import compose_command, compose_environment, run
from scripts.stack.environment import load_local_environment

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


def validate_configuration(root: Path) -> dict[str, str]:
    """Create a private template once and report only missing setting names."""
    path = root / ".env"
    if not path.exists():
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as handle:
            handle.write((root / ".env.example").read_text())
            handle.write(
                "\n# Required by the real-data Quick Start.\n"
                "EMBEDDING_PROVIDER=openai\nEMBEDDING_MODEL=text-embedding-3-large\n"
            )
        print("Created .env. Fill in your own credentials locally, then rerun rag-quickstart.")
    # Compose interpolates shell values before values from its explicit env file.
    configured = {k: v for k, v in dotenv_values(path).items() if v is not None} | dict(os.environ)
    missing = [k for k in ["SEC_USER_AGENT", "DART_API_KEY"] if placeholder(configured.get(k, ""))]
    selected = "OPENAI_API_KEY_LOCAL"
    if placeholder(configured.get(selected, "")):
        missing.append(selected)
    if (
        not re.search(r"\S+@\S+\.\S+", configured.get("SEC_USER_AGENT", ""))
        and "SEC_USER_AGENT" not in missing
    ):
        missing.append("SEC_USER_AGENT (include your reachable email)")
    for key, expected in [
        ("EMBEDDING_PROVIDER", "openai"),
        ("EMBEDDING_MODEL", "text-embedding-3-large"),
    ]:
        if configured.get(key) != expected:
            missing.append(f"{key}={expected}")
    if missing:
        raise ValueError(
            "Configuration blocked. Edit "
            + str(path)
            + " locally: "
            + ", ".join(missing)
            + ". Shell environment overrides .env; correct or unset conflicting exports. "
            "Then rerun rag-quickstart (or bash scripts/stack/quickstart.sh). "
            "No services were started by this invocation; existing services were left unchanged."
        )
    return load_local_environment(path, mode="dev")


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


def quickstart(root: Path) -> int:
    """Prepare only this Compose project's database and then its development services."""
    print("[1/5] Checking Docker Compose prerequisites.", flush=True)
    version = subprocess.check_output(
        ["docker", "compose", "version", "--short"], text=True
    ).strip()
    match = re.match(r"v?(\d+)\.(\d+)\.(\d+)", version)
    if not match or tuple(map(int, match.groups())) < (2, 24, 4):
        raise ValueError("Docker Compose 2.24.4 or newer is required.")
    print("[2/5] Checking local configuration (credentials are never displayed).", flush=True)
    bindings = validate_configuration(root)
    environment = compose_environment("dev", bindings)
    print("[3/5] Current project services; ensuring the database is healthy.", flush=True)
    report_services(root, environment)
    subprocess.run(
        compose_command(root, "dev", ["up", "-d", "--wait", "--wait-timeout", "120", "db"]),
        cwd=root,
        env=environment,
        check=True,
    )
    # This URL is derived from this project's published DB port, never an external DATABASE_URL.
    url = f"postgresql+asyncpg://filing:filing@127.0.0.1:{bindings['DB_PORT']}/filing"
    print("[4/5] Checking schema; only an empty database will be initialized.", flush=True)
    try:
        created = asyncio.run(prepare_schema(url))
    except (SchemaDriftError, ValueError) as error:
        raise RuntimeError(
            "Schema preparation blocked: "
            + str(error)
            + ". Existing data was preserved. Run .venv/bin/python -m scripts.schema check "
            "from this checkout. Do not change DATABASE_URL: this command uses "
            "the local Compose DB_PORT. Use scripts.schema recover to preserve data, "
            "or explicitly review scripts.schema recreate to discard local DB contents. "
            "After resolving compatibility, rerun rag-quickstart."
        ) from None
    print(
        "Empty database schema created."
        if created
        else "Existing compatible schema and data preserved."
    )
    print("[5/5] Building/starting DEV services, then verifying server readiness.", flush=True)
    result = run("dev", ["up", "--build", "-d"], root=root)
    if result:
        print(
            "Service startup failed; readiness was not confirmed. Run rag-dev ps -a and "
            "rag-dev logs --tail 50, then rerun rag-quickstart. No database was reset."
        )
        return result
    origin = f"http://{bindings['DOCREVIEW_LOCAL_HOST']}:{bindings['APP_PORT']}"
    report_services(root, environment)
    wait_ready(origin)
    print(f"Service ready: {origin}/docreview-rag-agent/")
    print(f"Quick Start: {origin}/docreview-rag-agent/docs/en/quickstart/")
    print(f"한국어: {origin}/docreview-rag-agent/docs/ko/quickstart/")
    print(
        "Service preparation is complete. Data preparation is a separate next step: "
        "open Quick Start, choose CLI or Web, and start at step 1: verify the empty environment. "
        "Then acquire the NVIDIA FY2024 and Samsung FY2024 reports as documented."
    )
    print("No filings were downloaded and no embedding or answer requests were made.")
    return 0


def main() -> int:
    """Report setup failures without dumping configuration or provider credentials."""
    try:
        return quickstart(ROOT)
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
