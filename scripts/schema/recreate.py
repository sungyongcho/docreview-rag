"""Explicitly recreate only ORM-owned tables in a verified local development database."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import shlex
import stat
import subprocess
import sys
import time
from typing import Literal
from urllib.parse import urlparse

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from app.db.bootstrap import bootstrap_connection, ensure_complete_schema
from app.db.models import Base
from scripts.schema.sources import (
    SourceAccessError,
    SourceReset,
    check_source_journal,
    check_source_write_access,
    source_preview,
)
from scripts.stack.__main__ import compose_command, compose_environment
from scripts.stack.environment import load_local_environment
from scripts.stack.prompts import confirm


def local_target(root: Path) -> tuple[dict, dict[str, str]]:
    """Pin one local Docker daemon and verify the checkout, volume, and published DB port."""
    environment = compose_environment("dev", load_local_environment(root / ".env"))
    host = os.environ.get("DOCKER_HOST") if not os.environ.get("DOCKER_CONTEXT") else None
    if not host:
        context = json.loads(subprocess.check_output(["docker", "context", "inspect"], text=True))
        host = context[0]["Endpoints"]["docker"]["Host"]
    parsed = urlparse(host)
    if parsed.scheme != "unix" or parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError("Recreate requires a local Docker Unix socket.")
    if not stat.S_ISSOCK(Path(parsed.path).stat().st_mode):
        raise ValueError("Docker endpoint is not a local socket.")
    for key in ("DOCKER_CONTEXT", "DOCKER_HOST", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH"):
        environment.pop(key, None)
    docker = ["docker", "--host", host]
    command = (
        docker + compose_command(root, "dev", ["ps", "--all", "--format", "json", "db", "app"])[1:]
    )
    output = subprocess.check_output(command, cwd=root, env=environment, text=True).strip()
    rows = (
        json.loads(output)
        if output.startswith("[")
        else [json.loads(row) for row in output.splitlines()]
    )
    databases = [row for row in rows if row["Service"] == "db"]
    if len(databases) != 1:
        raise ValueError("Start this checkout's DB first: rag-dev up -d db")
    targets = []
    database = None
    for row in rows:
        details = json.loads(
            subprocess.check_output(docker + ["inspect", row["ID"]], env=environment, text=True)
        )[0]
        labels = details["Config"]["Labels"]
        if (
            labels.get("com.docker.compose.project") != root.name
            or Path(labels.get("com.docker.compose.project.working_dir", "")).resolve() != root
            or labels.get("com.docker.compose.service") != row["Service"]
        ):
            raise ValueError("Container identity differs from this checkout.")
        if row["Service"] == "app":
            values = dict(item.split("=", 1) for item in details["Config"]["Env"])
            if values.get("MODE") != "dev":
                raise ValueError("Recreate is limited to the local DEV stack.")
            targets.append(details["Id"])
        elif row["Service"] == "db":
            database = details
        else:
            raise ValueError("Unexpected Compose service in the target inventory.")
    if database is None:
        raise ValueError("Database container is unavailable.")
    db_environment = dict(item.split("=", 1) for item in database["Config"]["Env"])
    if (
        db_environment.get("POSTGRES_DB") != "filing"
        or db_environment.get("POSTGRES_USER") != "filing"
    ):
        raise ValueError("Database identity differs from the local filing target.")
    bindings = database["NetworkSettings"]["Ports"].get("5432/tcp") or []
    port = environment["DB_PORT"]
    if len(bindings) != 1 or bindings[0] != {"HostIp": "127.0.0.1", "HostPort": port}:
        raise ValueError("Database port is not this checkout's loopback target.")
    mounts = [row for row in database["Mounts"] if row["Destination"] == "/var/lib/postgresql/data"]
    if len(mounts) != 1 or mounts[0]["Type"] != "volume":
        raise ValueError("Recreate requires the local project's named database volume.")
    volume = json.loads(
        subprocess.check_output(
            docker + ["volume", "inspect", mounts[0]["Name"]], env=environment, text=True
        )
    )[0]
    if (
        (volume.get("Labels") or {}).get("com.docker.compose.project") != root.name
        or volume.get("Driver") != "local"
        or volume.get("Options")
    ):
        raise ValueError("Database volume is not a local project-owned target.")
    users = subprocess.check_output(
        docker + ["ps", "-aq", "--no-trunc", "--filter", f"volume={mounts[0]['Name']}"],
        env=environment,
        text=True,
    ).split()
    if set(users) != {database["Id"]}:
        raise ValueError("The database volume is shared with another container; recreate refused.")
    return {
        "database": database["Id"],
        "apps": sorted(targets),
        "volume": mounts[0]["Name"],
        "port": port,
        "docker": docker,
    }, environment


async def inventory(connection: AsyncConnection) -> dict[str, int]:
    """Count only known application tables without assuming their current columns."""
    tables = set(await connection.run_sync(lambda sync: inspect(sync).get_table_names()))
    result = {}
    for name in sorted(tables & set(Base.metadata.tables)):
        quoted = connection.dialect.identifier_preparer.quote(name)
        result[name] = (
            await connection.execute(text(f"SELECT count(*) FROM {quoted}"))
        ).scalar_one()
    return result


async def recreate(url: str, expected: dict[str, int] | None = None) -> dict[str, int]:
    """Preview, or transactionally drop/recreate ORM tables; never use cascading deletion."""
    engine = create_async_engine(url)
    try:
        async with engine.begin() as connection:
            if expected is None:
                return await inventory(connection)
            await connection.execute(text("SET LOCAL lock_timeout = '5s'"))
            await connection.execute(text("SELECT pg_advisory_xact_lock(7340291050)"))
            clients = (
                await connection.execute(
                    text(
                        "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() "
                        "AND backend_type='client backend' AND pid<>pg_backend_pid()"
                    )
                )
            ).scalar_one()
            if clients:
                raise ValueError(
                    "Close other DB clients and retry with a new preview; nothing deleted."
                )
            if await inventory(connection) != expected:
                raise ValueError("Table inventory changed; review a new preview. Nothing deleted.")
            await connection.run_sync(Base.metadata.drop_all)
            await bootstrap_connection(connection)
            await ensure_complete_schema(connection)
            remaining = await inventory(connection)
            if any(remaining.values()):
                raise ValueError("Recreated application tables are not empty; rolling back.")
            return remaining
    finally:
        await engine.dispose()


def preview_sources(root: Path, *, keep_sources: bool = False) -> dict | None:
    """Offer an exact permission repair and one read-only retry before any deletion preview."""
    for attempt in range(2):
        try:
            if keep_sources:
                check_source_journal(root)
                return None
            preview = source_preview(root)
            check_source_write_access(root, preview)
            return preview
        except PermissionError as error:
            if isinstance(error, SourceAccessError):
                paths = error.paths
            else:
                denied = Path(error.filename) if error.filename else root / "data"
                denied = (denied if denied.is_absolute() else root / denied).resolve()
                paths = (denied.parent, denied) if denied != root else (denied,)
            if any(not path.is_relative_to(root) for path in paths):
                raise ValueError(
                    "Denied path is outside this checkout; ask its owner to inspect it."
                ) from None
            command = [
                "sudo",
                "setfacl",
                "-R",
                "-m",
                f"u:{os.geteuid()}:rwX",
                "--",
                *(str(path) for path in paths),
            ]
            print("Source access blocked before confirmation; the API and data are unchanged.")
            for path in paths:
                print(f"  Blocked: {path}")
            print("Apply this scoped repair as the host user, then retry inspection:")
            print("  " + shlex.join(command))
            if attempt or not confirm("After applying the repair, retry source inspection once?"):
                raise ValueError(
                    "Source permissions remain blocked; no deletion was submitted."
                ) from None
    raise RuntimeError("Source inspection did not complete.")


def run(
    root: Path,
    *,
    keep_sources: bool = False,
    sample: bool = False,
    restart_planned: bool = False,
) -> Literal["cancelled", "succeeded", "incomplete"]:
    """Require exact interactive approval before stopping the API or changing any table."""
    if not sys.stdin.isatty():
        raise ValueError("Recreate requires an interactive terminal; no changes made.")
    if keep_sources and sample:
        raise ValueError("--sample cannot be combined with --keep-sources")
    root = root.resolve()
    sources = preview_sources(root, keep_sources=keep_sources)
    target, environment = local_target(root)
    url = f"postgresql+asyncpg://filing:filing@127.0.0.1:{target['port']}/filing"
    before = asyncio.run(recreate(url))
    print(
        "DANGER: for first-time setup or users who understand the consequences. "
        "All ORM-owned DB tables and their data will be deleted. No backup is created."
    )
    print(
        f"Checkout: {root}\nDatabase: 127.0.0.1:{target['port']}/filing\nVolume: {target['volume']}"
    )
    print(json.dumps(before, indent=2))
    if sources is not None:
        print("Downloaded source files to delete (path: SHA256):")
        print(json.dumps(sources, indent=2))
        print(
            "Acquisition draft: " + ("NVDA AMD / FY2023 FY2024; no download" if sample else "empty")
        )
    print(
        (
            "Preserved downloaded sources (--keep-sources). "
            if keep_sources
            else "Downloaded raw sources and manifest source entries will be removed. "
        )
        + "Preserved: code, .env, evaluation exports, unrelated tables, "
        "the database volume and host Ollama. Dependent unknown objects cause rollback."
    )
    print(
        "The API stops after confirmation. Guided setup rebuilds/starts it after success."
        if restart_planned
        else "The local API will stop after confirmation and is not restarted automatically."
    )
    expires = time.monotonic() + 300
    phrase = f"RECREATE {root.name}" if keep_sources else f"RECREATE {root.name} AND SOURCES"
    if input(f"Type {phrase} to confirm this entire irreversible preview (default No): ") != phrase:
        print("Cancelled; nothing changed.")
        return "cancelled"
    if time.monotonic() >= expires:
        raise ValueError("Preview expired; review a new preview. Nothing changed.")
    current, _ = local_target(root)
    if current != target:
        raise ValueError("Docker target changed; nothing deleted. Review a new preview.")
    reset = SourceReset(root, sources, sample=sample) if sources is not None else None
    database_started = False
    try:
        for app in target["apps"]:
            subprocess.run(
                target["docker"] + ["stop", app],
                env=environment,
                check=True,
                stdout=subprocess.DEVNULL,
            )
        if reset is not None:
            reset.stage()
        database_started = True
        asyncio.run(recreate(url, before))
    except (Exception, KeyboardInterrupt) as error:
        uncertain = database_started and not isinstance(error, ValueError)
        sources_unchanged = reset is None or not (reset.state["moved"] or reset.state["created"])
        try:
            if reset is not None and reset.journal.exists():
                reset.restore(database_outcome_uncertain=uncertain)
                sources_unchanged = True
        except (Exception, KeyboardInterrupt) as recovery_error:
            print(
                "INCOMPLETE: source rollback could not be confirmed. "
                "Preserve data/.schema-recreate-journal/journal.json; do not repeat the reset.",
                file=sys.stderr,
            )
            print(
                "Inspect the journal and run rag-schema check; "
                "then restore the API with: rag-dev up -d",
                file=sys.stderr,
            )
            raise RuntimeError(
                f"Source recovery failed ({type(recovery_error).__name__}); "
                "journal inspection is required."
            ) from recovery_error
        if not uncertain and sources_unchanged:
            print(
                "Reset failed; database and sources are unchanged by this reset "
                "(any staging was rolled back).",
                file=sys.stderr,
            )
        else:
            print(
                "Reset failed; "
                + (
                    "sources were restored. "
                    if sources_unchanged
                    else "source restoration is unconfirmed. "
                )
                + ("Database outcome is unconfirmed. " if uncertain else "Database is unchanged. ")
                + "Preserve data/.schema-recreate-journal/journal.json "
                "and run rag-schema check before another reset.",
                file=sys.stderr,
            )
        print(
            "The API may be stopped. Restore it without requesting a build: rag-dev up -d",
            file=sys.stderr,
        )
        if isinstance(error, PermissionError):
            path = f" at {error.filename}" if error.filename else ""
            raise ValueError(
                f"Source reset was blocked by filesystem permissions{path}. "
                "Recheck the source access repair before retrying."
            ) from error
        raise
    if reset is not None:
        try:
            reset.finish()
        except OSError, KeyboardInterrupt:
            print(
                "INCOMPLETE: DB committed, but source backup cleanup failed. "
                "Inspect data/.schema-recreate-journal/journal.json; do not repeat recreation.",
                file=sys.stderr,
            )
            print(
                "After inspecting the journal, restore the API without requesting a build: "
                "rag-dev up -d",
                file=sys.stderr,
            )
            return "incomplete"
    print(
        "Verified: ORM schema recreated and application tables empty. "
        + (
            "Downloaded sources preserved. "
            if keep_sources
            else "Downloaded sources and manifest source entries cleared. "
        )
        + "Code, .env, exports, unrelated tables and volume preserved. "
        + (
            "Guided setup will now rebuild/start DEV and verify readiness. "
            if restart_planned
            else "Run rag-up, then re-check Build and repeat data preparation. "
        )
        + "No paid work was started."
    )
    return "succeeded"
