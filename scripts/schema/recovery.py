"""Create and start an isolated local recovery checkout without altering its source."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import time
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener
from uuid import uuid4

from dotenv import dotenv_values, set_key, unset_key

from scripts.stack.__main__ import compose_command, compose_environment
from scripts.stack.environment import load_local_environment


def create_recovery(source: Path, parent: Path) -> Path:
    """Clone committed code into a unique project and privately copy only local settings."""
    source = source.resolve()
    parent = parent.expanduser().resolve()
    if parent == source or source in parent.parents:
        raise ValueError("Recovery must be outside the source checkout.")
    if not parent.is_dir():
        raise ValueError("Choose an existing parent directory for the new recovery checkout.")
    config = source / ".env"
    if config.is_symlink():
        raise ValueError("Refusing to copy a symbolic-link .env; choose a regular local config.")
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
    target = parent / ("docreview-recovery-" + uuid4().hex[:12])
    target.mkdir(mode=0o700)
    print(f"Recovery directory reserved: {target}", flush=True)
    subprocess.run(
        ["git", "clone", "--quiet", "--no-hardlinks", "--no-checkout", str(source), str(target)],
        check=True,
    )
    subprocess.run(["git", "checkout", "--quiet", "--detach", revision], cwd=target, check=True)
    # Recovery is an independent runtime snapshot, not a route for pushing into the source.
    subprocess.run(["git", "remote", "remove", "origin"], cwd=target, check=True)
    subprocess.run(["git", "config", "core.hooksPath", ".githooks"], cwd=target, check=True)
    destination = target / ".env"
    if destination.exists():
        raise ValueError("The committed snapshot unexpectedly contains .env; recovery stopped.")
    with destination.open("x", encoding="utf-8") as stream:
        os.chmod(destination, 0o600)
        if config.exists():
            stream.write(config.read_text())
    sockets = []
    try:
        for key in ("DB_PORT", "APP_PORT", "DOCREVIEW_OPERATOR_PORT"):
            listener = socket.socket()
            sockets.append(listener)
            listener.bind(("127.0.0.1", 0))
            set_key(str(destination), key, str(listener.getsockname()[1]))
    finally:
        for listener in sockets:
            listener.close()
    for key in ("DATABASE_URL", "COMPOSE_PROJECT_NAME", "COMPOSE_FILE", "COMPOSE_PROFILES"):
        if key in dotenv_values(destination):
            unset_key(str(destination), key)
    set_key(str(destination), "DOCREVIEW_LOCAL_HOST", "127.0.0.1")
    print(f"Recovery checkout: {target}\nCommitted source: {revision}", flush=True)
    print(
        "Original database, configuration, corpus and services are unchanged. "
        "Uncommitted source edits and downloaded corpus files were not copied.",
        flush=True,
    )
    return target


def recovery_environment(target: Path) -> dict[str, str]:
    """Make both host CLI and Compose use the new target's file rather than shell overrides."""
    values = dotenv_values(target / ".env")
    environment = compose_environment("dev", load_local_environment(target / ".env"))
    for key in values.keys() | {
        "DATABASE_URL",
        "COMPOSE_PROJECT_NAME",
        "UV_PROJECT_ENVIRONMENT",
        "VIRTUAL_ENV",
    }:
        environment.pop(key, None)
    environment.update(load_local_environment(target / ".env"))
    environment["UV_PROJECT_ENVIRONMENT"] = str(target / ".venv")
    environment["UV_CACHE_DIR"] = str(target / ".cache/uv")
    return environment


def wait_recovery(origin: str, *, timeout: float = 180) -> None:
    """Confirm the routed web API sees a compatible writable DB, without requiring corpus data."""
    opener = build_opener(ProxyHandler({}))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with opener.open(
                origin + "/docreview-rag/api/admin/corpus/", timeout=5
            ) as response:
                status = json.load(response)["status"]
            if (
                status["database_connected"]
                and status["schema_status"] == "compatible"
                and status["writable"]
            ):
                return
        except KeyError, TypeError, json.JSONDecodeError:
            raise RuntimeError(
                "Recovery readiness response was invalid; no success was confirmed."
            ) from None
        except URLError, TimeoutError, ConnectionError:
            pass
        time.sleep(2)
    raise RuntimeError(
        "Recovery server readiness is unconfirmed. Inspect this recovery checkout's "
        "service logs; the original database was not repaired or reset."
    )


def start_recovery(target: Path, *, return_stage: str = "index") -> None:
    """Start only the new project, initialize its empty database and verify the web target."""
    environment = recovery_environment(target)
    if not shutil.which("uv") or not shutil.which("docker"):
        raise ValueError("Install uv and Docker before starting the recovery checkout.")
    subprocess.run(["uv", "sync", "--locked"], cwd=target, env=environment, check=True)
    subprocess.run(
        compose_command(target, "dev", ["up", "-d", "--wait", "--wait-timeout", "120", "db"]),
        cwd=target,
        env=environment,
        check=True,
    )
    python = str(target / ".venv/bin/python")
    subprocess.run(
        [python, "-m", "scripts.schema", "prepare"], cwd=target, env=environment, check=True
    )
    subprocess.run(
        [python, "-m", "scripts.stack", "dev", "up", "--build", "-d"],
        cwd=target,
        env=environment,
        check=True,
    )
    bindings = load_local_environment(target / ".env")
    origin = f"http://127.0.0.1:{bindings['APP_PORT']}"
    wait_recovery(origin)
    subprocess.run(
        [python, "-m", "scripts.schema", "check"], cwd=target, env=environment, check=True
    )
    print(f"Recovery ready: {origin}/docreview-rag/?recovery_stage={return_stage}")
    print(
        f"Next: cd {target}\nThen source ./rag-alias.sh to use this recovery checkout's commands."
    )
    print(
        "The original schema is still unchanged. This empty recovery database needs "
        "fresh data preparation; no provider requests were made."
    )
