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
from sqlalchemy import inspect
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.bootstrap import bootstrap_schema, ensure_schema_compatibility
from app.db.models import Base
from scripts.local_env import load_local_environment
from scripts.local_stack import compose_command, compose_environment, run

ROOT = Path(__file__).resolve().parents[1]


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
            "Complete these settings without sharing their values: " + ", ".join(missing)
        )
    return load_local_environment(path, mode="dev")


async def prepare_schema(url: str) -> bool:
    """Bootstrap an empty database, or only inspect an existing compatible schema."""
    engine = create_async_engine(url, echo=False)
    try:
        async with engine.connect() as connection:
            tables = set(await connection.run_sync(lambda sync: inspect(sync).get_table_names()))
            if tables:
                await ensure_schema_compatibility(connection)
                missing = set(Base.metadata.tables) - tables
                if missing:
                    raise ValueError(
                        "Existing schema is incomplete; inspect migrations before continuing: "
                        + ", ".join(sorted(missing))
                    )
                return False
        await bootstrap_schema(engine)
        return True
    finally:
        await engine.dispose()


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
        "DEV readiness was not confirmed. Use rag-dev logs -f app and rag-diagnose; "
        "existing data was retained."
    )


def quickstart(root: Path) -> int:
    """Prepare only this Compose project's database and then its development services."""
    version = subprocess.check_output(
        ["docker", "compose", "version", "--short"], text=True
    ).strip()
    match = re.match(r"v?(\d+)\.(\d+)\.(\d+)", version)
    if not match or tuple(map(int, match.groups())) < (2, 24, 4):
        raise ValueError("Docker Compose 2.24.4 or newer is required.")
    bindings = validate_configuration(root)
    environment = compose_environment("dev", bindings)
    subprocess.run(
        compose_command(root, "dev", ["up", "-d", "--wait", "db"]),
        cwd=root,
        env=environment,
        check=True,
    )
    # This URL is derived from this project's published DB port, never an external DATABASE_URL.
    url = f"postgresql+asyncpg://filing:filing@127.0.0.1:{bindings['DB_PORT']}/filing"
    created = asyncio.run(prepare_schema(url))
    print(
        "Empty database schema created."
        if created
        else "Existing compatible schema and data preserved."
    )
    result = run("dev", ["up", "--build", "-d"], root=root)
    if result:
        return result
    origin = f"http://{bindings['DOCREVIEW_LOCAL_HOST']}:{bindings['APP_PORT']}"
    wait_ready(origin)
    print(f"Service ready: {origin}/docreview-rag-agent/")
    print(f"Quick Start: {origin}/docreview-rag-agent/docs/en/quickstart/")
    print(f"한국어: {origin}/docreview-rag-agent/docs/ko/quickstart/")
    print(
        "Service preparation is complete. Data preparation is a separate next step: "
        "follow Quick Start."
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
