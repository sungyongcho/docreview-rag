"""Eligibility rules that match an inspected Docker stack to this checkout's reset target.

The reset service gathers container, volume, Compose and request-gate metadata with Docker
commands and then applies these rules in a fixed order. None of them runs a command, and each
raises ``WipeError`` for the first broken rule so the preview names the exact reason a reset is
unavailable.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import dotenv_values
from sqlalchemy.engine import make_url

from app.operator.wipe_errors import WipeError


def _container_environment(container: dict[str, Any]) -> dict[str, str]:
    """Read a container's ``KEY=value`` environment list from ``docker inspect`` as a mapping."""
    return dict(item.split("=", 1) for item in container["Config"]["Env"])


def verify_stack_containers(
    root: Path, database: dict[str, Any], app: dict[str, Any]
) -> tuple[int, str]:
    """Match the database and app containers to this checkout's local Compose contract.

    Parameters
    ----------
    root : Path
        Resolved checkout root whose ``data`` directory the app must mount.
    database : dict[str, Any]
        ``docker inspect`` record of the Compose ``db`` container.
    app : dict[str, Any]
        ``docker inspect`` record of the Compose ``app`` container.

    Returns
    -------
    tuple[int, str]
        The loopback host port the database publishes and the name of its data volume.
    """
    app_env = _container_environment(app)
    _require_live_development_app(app, app_env)
    _require_local_database_credentials(database, app_env)
    _require_checkout_data_mount(root, app, app_env)
    port = _loopback_database_port(database)
    _require_local_host_database_url(root, port)
    return port, _database_volume_name(database)


def _require_live_development_app(app: dict[str, Any], app_env: dict[str, str]) -> None:
    """Accept only the development app in live admin mode, served by one Uvicorn worker."""
    if app_env.get("MODE") != "dev" or app_env.get("DOCREVIEW_ADMIN_MODE") != "live":
        raise WipeError("Reset is only available for the live local development stack")
    _require_single_worker(app)


def _require_single_worker(app: dict[str, Any]) -> None:
    """Require the known single-worker Uvicorn development process contract.

    The request gate that holds admission during a reset lives in one worker process, so a
    second worker could keep serving requests while the database is removed.
    """
    command = app["Config"].get("Cmd") or []
    environment = _container_environment(app)
    if "uvicorn" not in command or any(
        environment.get(key, "1") != "1" for key in ("WEB_CONCURRENCY", "UVICORN_WORKERS")
    ):
        raise WipeError("Reset requires the single-worker Uvicorn development app")
    for index, argument in enumerate(command):
        if argument == "--workers" and command[index + 1 : index + 2] != ["1"]:
            raise WipeError("Reset requires one application worker")
        if argument.startswith("--workers=") and argument != "--workers=1":
            raise WipeError("Reset requires one application worker")


def _require_local_database_credentials(database: dict[str, Any], app_env: dict[str, str]) -> None:
    """Require the Compose database credentials and an app that connects to that database."""
    db_env = _container_environment(database)
    if any(
        db_env.get(key) != "filing" for key in ("POSTGRES_USER", "POSTGRES_DB", "POSTGRES_PASSWORD")
    ):
        raise WipeError("Database credentials differ from the local Compose contract")
    application_url = make_url(app_env.get("DATABASE_URL", ""))
    if (
        application_url.username,
        application_url.password,
        application_url.host,
        application_url.port or 5432,
        application_url.database,
    ) != (
        "filing",
        "filing",
        "db",
        5432,
        "filing",
    ):
        raise WipeError("Application database is not the local Compose database")


def _require_checkout_data_mount(root: Path, app: dict[str, Any], app_env: dict[str, str]) -> None:
    """Require the app's runtime files to be this checkout's bind-mounted data directory."""
    data_mounts = [item for item in app["Mounts"] if item["Destination"] == "/app/data"]
    if (
        len(data_mounts) != 1
        or data_mounts[0]["Type"] != "bind"
        or Path(data_mounts[0]["Source"]).resolve() != root / "data"
        or app_env.get("CORPUS_DIR") != "/app/data/corpus"
    ):
        raise WipeError("Application runtime files do not belong to this checkout")


def _loopback_database_port(database: dict[str, Any]) -> int:
    """Return the database's single published port after checking it listens on loopback only."""
    ports = database["NetworkSettings"]["Ports"].get("5432/tcp") or []
    if len(ports) != 1 or ports[0]["HostIp"] not in {"127.0.0.1"}:
        raise WipeError("Database must have one loopback-only published port")
    return int(ports[0]["HostPort"])


def _require_local_host_database_url(root: Path, port: int) -> None:
    """Refuse when host-side tools are configured to use a database outside this stack.

    A ``DATABASE_URL`` in the checkout's ``.env`` file takes precedence over the process
    environment.
    """
    configured = dotenv_values(root / ".env").get("DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not configured:
        return
    url = make_url(configured)
    if (
        url.host not in {"localhost", "127.0.0.1", "::1"}
        or (url.port or 5432) != port
        or url.database != "filing"
    ):
        raise WipeError("Host database configuration points outside the local stack")


def _database_volume_name(database: dict[str, Any]) -> str:
    """Return the named volume that holds the database files, the only volume a reset removes."""
    mounts = [m for m in database["Mounts"] if m["Destination"] == "/var/lib/postgresql/data"]
    if len(mounts) != 1 or mounts[0]["Type"] != "volume":
        raise WipeError("Database does not use the expected named volume")
    return mounts[0]["Name"]


def verify_database_volume(project: str, volume_info: dict[str, Any]) -> None:
    """Require a plain local volume that this checkout's Compose project created.

    Parameters
    ----------
    project : str
        Compose project name, which is the checkout directory name.
    volume_info : dict[str, Any]
        ``docker volume inspect`` record of the database volume.
    """
    if (volume_info.get("Labels") or {}).get("com.docker.compose.project") != project:
        raise WipeError("Database volume belongs to another project")
    if volume_info.get("Driver") != "local" or volume_info.get("Options"):
        raise WipeError("Database volume must use local storage without driver options")


def verify_compose_plan(compose: dict[str, Any], *, port: int, volume: str) -> None:
    """Require the Compose configuration to recreate the same loopback port and local volume.

    A reset recreates the database from this configuration, so an overlay that changed the
    port, the volume or its driver would recreate something other than what was inspected.

    Parameters
    ----------
    compose : dict[str, Any]
        Parsed ``docker compose config --format json`` output for this checkout.
    port : int
        Loopback host port the running database publishes.
    volume : str
        Name of the running database's data volume.
    """
    planned_db = compose["services"]["db"]
    planned_ports = planned_db.get("ports", [])
    planned_mounts = [
        item
        for item in planned_db.get("volumes", [])
        if item["target"] == "/var/lib/postgresql/data"
    ]
    planned_volume = (
        compose["volumes"].get(planned_mounts[0].get("source"), {})
        if len(planned_mounts) == 1
        else {}
    )
    if (
        len(planned_ports) != 1
        or planned_ports[0].get("host_ip") != "127.0.0.1"
        or int(planned_ports[0]["published"]) != port
        or int(planned_ports[0]["target"]) != 5432
        or len(planned_mounts) != 1
        or planned_mounts[0]["type"] != "volume"
        or planned_volume.get("name") != volume
        or planned_volume.get("external", False)
        or planned_volume.get("driver", "local") != "local"
        or planned_volume.get("driver_opts")
    ):
        raise WipeError("Development Compose configuration differs from the reset target")


def verify_gate_activity(
    activity: dict[str, Any],
    *,
    app_container: str,
    lease: tuple[str, str] | None,
    lease_instance: str | None,
) -> str:
    """Check the running app's request gate against this service's own reset hold.

    Parameters
    ----------
    activity : dict[str, Any]
        The gate's ``activity`` response.
    app_container : str
        ID of the app container the gate runs in.
    lease : tuple[str, str] | None
        The container and lease this service holds, or None when it holds nothing.
    lease_instance : str | None
        Gate instance that granted the held lease.

    Returns
    -------
    str
        The gate instance identity, which the preview records to detect a restarted app.
    """
    if activity.get("active_requests") != 0:
        raise WipeError("Finish active application requests before resetting")
    if activity.get("held") and (lease is None or lease[0] != app_container):
        raise WipeError("Another reset holds application request admission")
    instance = activity.get("instance")
    if not isinstance(instance, str) or not instance:
        raise WipeError("Application request gate identity is unavailable")
    if lease is not None and (not activity.get("held") or instance != lease_instance):
        raise WipeError("Application request gate restarted or lost the reset hold")
    return instance
