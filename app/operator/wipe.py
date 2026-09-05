"""Explicit, local-only reset of one verified checkout's runtime data."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shlex
import signal
import stat
import tempfile
import time
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from dotenv import dotenv_values
from sqlalchemy.engine import make_url

from app.observability.persistence import redact_sensitive_text


class WipeError(RuntimeError):
    """A reset cannot safely proceed against its declared target."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "reset_precondition_failed",
        details: dict[str, Any] | None = None,
        remediation: list[str] | None = None,
    ) -> None:
        """Attach safe diagnostic evidence while preserving the existing error message."""
        super().__init__(message)
        self.diagnosis = {
            "code": code,
            "details": details or {},
            "remediation": remediation
            or ["Resolve the reported condition, then check reset availability again."],
        }


def diagnose_wipe_error(error: Exception) -> dict[str, Any]:
    """Keep known reset evidence and identify unclassified inspection failures honestly."""
    if isinstance(error, WipeError):
        return error.diagnosis
    return {
        "code": "reset_inspection_failed",
        "details": {"error_type": type(error).__name__},
        "remediation": [
            "The cause is unknown. Review the operator error and local service status, "
            "then check reset availability again."
        ],
    }


class WipeService:
    """Bind a short-lived preview to local Docker identity and exact runtime files."""

    def __init__(self, root: Path, busy: Callable[[], bool]) -> None:
        """Keep confirmation state outside the database being reset."""
        self.root = root.resolve()
        self.busy = busy
        self._preview: dict[str, Any] | None = None
        self.lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None
        self._docker_host: str | None = None
        self._lease: tuple[str, str] | None = None
        self._lease_instance: str | None = None
        self._lease_daemon: dict[str, Any] | None = None
        self._stopped_app: str | None = None
        self._operation_fd: int | None = None
        self._compose_json: str | None = None
        self._result: dict[str, Any] = {"status": "idle", "completed": []}
        identity = hashlib.sha256(str(self.root).encode()).hexdigest()[:16]
        self._audit = Path(tempfile.gettempdir()) / f"docreview-wipe-{os.getuid()}-{identity}.json"
        self._operation_path = self._audit.with_suffix(".lock")
        if self._audit.is_symlink():
            raise WipeError("Reset audit path must not be a symbolic link")
        if self._audit.exists():
            recorded = json.loads(self._audit.read_text())
            self._result = recorded.get("result", recorded)
            if recorded.get("lease"):
                self._lease = tuple(recorded["lease"])
                self._lease_instance = recorded["lease_instance"]
                self._lease_daemon = recorded["lease_daemon"]
                self._docker_host = self._lease_daemon["endpoint"]
            if self._result["status"] == "running":
                self._result.update(status="interrupted", message="Operator restarted during reset")

    def _acquire_operation(self) -> None:
        """Serialize reset writers across operator processes for the same checkout."""
        descriptor = os.open(
            self._operation_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600
        )
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            os.close(descriptor)
            raise WipeError("Another operator owns this checkout's reset") from error
        self._operation_fd = descriptor

    def _release_operation(self) -> None:
        """Release a completed or interrupted writer without removing the shared lock file."""
        if self._operation_fd is not None:
            os.close(self._operation_fd)
            self._operation_fd = None

    async def _run(
        self,
        *argv: str,
        environment: dict[str, str] | None = None,
        input_text: str | None = None,
    ) -> str:
        """Run exact arguments with bounded, redacted failure reporting."""
        environment = dict(os.environ if environment is None else environment)
        if argv[0] == "docker" and argv[1] != "context" and self._docker_host is not None:
            argv = ("docker", "--host", self._docker_host, *argv[1:])
            for key in ("DOCKER_CONTEXT", "DOCKER_HOST", "DOCKER_TLS", "DOCKER_TLS_VERIFY"):
                environment.pop(key, None)
        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=self.root,
            env=environment,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.PIPE if input_text is not None else None,
            start_new_session=True,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(input_text.encode() if input_text is not None else None), 180
            )
        except TimeoutError:
            await self._terminate(process)
            raise WipeError("Local reset command timed out") from None
        except asyncio.CancelledError:
            await self._terminate(process)
            raise
        if process.returncode:
            raise WipeError(redact_sensitive_text(stderr.decode(errors="replace")[-2000:]))
        return stdout.decode()

    async def _terminate(self, process: asyncio.subprocess.Process) -> None:
        """Stop Docker CLI children before releasing an interrupted reset."""
        if process.returncode is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await process.wait()

    async def _docker_identity(self) -> dict[str, Any]:
        """Pin all commands to a verified local Unix socket and daemon identity."""
        if self._docker_host is None:
            context = os.environ.get("DOCKER_CONTEXT")
            host = os.environ.get("DOCKER_HOST") if not context else None
            if not host:
                arguments = (context,) if context else ()
                metadata = json.loads(await self._run("docker", "context", "inspect", *arguments))
                host = metadata[0]["Endpoints"]["docker"]["Host"]
            parsed = urlparse(host)
            if (
                parsed.scheme != "unix"
                or parsed.netloc
                or not Path(parsed.path).is_absolute()
                or parsed.query
                or parsed.fragment
            ):
                raise WipeError("Reset requires a local Docker Unix socket")
            self._docker_host = f"unix://{Path(parsed.path).resolve()}"
        socket_path = Path(urlparse(self._docker_host).path)
        metadata = socket_path.stat()
        if not stat.S_ISSOCK(metadata.st_mode):
            raise WipeError("Docker endpoint is not a local Unix socket")
        daemon_id = (await self._run("docker", "info", "--format", "{{.ID}}")).strip()
        if not daemon_id:
            raise WipeError("Docker daemon identity is unavailable")
        return {
            "endpoint": self._docker_host,
            "id": daemon_id,
            "socket_device": metadata.st_dev,
            "socket_inode": metadata.st_ino,
        }

    def _compose(self, *arguments: str, frozen: bool = False) -> tuple[str, ...]:
        """Use only this checkout and the explicit development overlay."""
        return (
            "docker",
            "compose",
            "--project-directory",
            str(self.root),
            "-p",
            self.root.name,
            *(
                ("-f", "-")
                if frozen
                else ("-f", "docker/docker-compose.yml", "-f", "docker/docker-compose.dev.yml")
            ),
            *arguments,
        )

    def _permission_error(self, path: Path, *, operation: str) -> WipeError:
        """Explain the denied operation without changing owners, modes, or runtime data."""
        uid = os.geteuid()
        details: dict[str, Any] = {
            "path": path.relative_to(self.root).as_posix(),
            "operation": operation,
            "operator_uid": uid,
            "operator_gid": os.getegid(),
            "operator_groups": sorted(set(os.getgroups()) | {os.getegid()}),
        }
        for key, item in (("file", path), ("parent", path.parent)):
            try:
                metadata = item.stat()
            except OSError:
                details[key] = {"path": str(item), "metadata": "unavailable"}
            else:
                details[key] = {
                    "path": str(item),
                    "uid": metadata.st_uid,
                    "gid": metadata.st_gid,
                    "mode": f"{stat.S_IMODE(metadata.st_mode):04o}",
                }
        actions = {
            "remove": "removed",
            "read": "read",
            "enumerate": "enumerated",
        }
        commands = (
            [f"sudo setfacl -m u:{uid}:rwx -- {shlex.quote(str(path))}"]
            if operation == "enumerate"
            else [
                f"sudo setfacl -m u:{uid}:rwx -- {shlex.quote(str(path.parent))}",
                f"sudo setfacl -m u:{uid}:r -- {shlex.quote(str(path))}",
            ]
        )
        return WipeError(
            f"Runtime file cannot be {actions[operation]} by this operator: {details['path']}",
            code="runtime_file_permission",
            details=details,
            remediation=[
                "The operator needs file read access and parent directory read, write, and "
                "search access. Ask the owner or administrator to grant these while preserving "
                "the application's existing access.",
                "If POSIX ACLs are supported, an administrator can run these targeted commands "
                "manually; they do not delete data:",
                *commands,
                "If access is still denied, check parent traversal permissions, sticky bits, "
                "ACLs, and read-only mounts. Then check reset availability again.",
            ],
        )

    def _files(self, tracked: set[str]) -> list[dict[str, Any]]:
        """Enumerate runtime-only paths while preserving every tracked file and source JSON."""
        candidates: list[Path] = []

        def inaccessible(error: OSError) -> None:
            """Refuse an incomplete preview instead of silently skipping unreadable directories."""
            if isinstance(error, PermissionError) and error.filename:
                raise self._permission_error(Path(error.filename), operation="enumerate") from error
            raise WipeError("Runtime files could not be fully enumerated") from error

        for name in ("data/corpus", "data/eval_runs", "data/local-settings"):
            directory = self.root / name
            if not directory.exists():
                continue
            if directory.is_symlink() or directory.resolve() != directory.absolute():
                raise WipeError(f"Runtime directory contains a symbolic link: {name}")
            for parent, directories, filenames in os.walk(directory, onerror=inaccessible):
                if any((Path(parent) / child).is_symlink() for child in directories):
                    raise WipeError(f"Runtime directory contains a symbolic link: {name}")
                candidates.extend(
                    path
                    for filename in filenames
                    if name != "data/corpus" or Path(filename).suffix in {".html", ".xml", ".zip"}
                    for path in (Path(parent) / filename,)
                )
        result = []
        for path in sorted(set(candidates)):
            relative = path.relative_to(self.root).as_posix()
            if relative in tracked:
                continue
            if path.is_symlink() or path.resolve() != path.absolute():
                raise WipeError(f"Runtime path contains a symbolic link: {relative}")
            if not path.is_file():
                continue
            if not os.access(path.parent, os.W_OK | os.X_OK, effective_ids=True):
                raise self._permission_error(path, operation="remove")
            metadata = path.stat()
            parent_metadata = path.parent.stat()
            if parent_metadata.st_mode & stat.S_ISVTX and os.geteuid() not in {
                0,
                metadata.st_uid,
                parent_metadata.st_uid,
            }:
                raise self._permission_error(path, operation="remove")
            try:
                fingerprint = hashlib.sha256(path.read_bytes()).hexdigest()
            except PermissionError as error:
                raise self._permission_error(path, operation="read") from error
            result.append(
                {
                    "path": relative,
                    "bytes": metadata.st_size,
                    "sha256": fingerprint,
                }
            )
        return result

    async def _runtime_request(
        self, container: str, action: str, payload: dict[str, str] | None = None
    ) -> dict[str, Any]:
        """Contact the verified app's request gate only through its container loopback."""
        code = """import json, os, pathlib, stat, sys, urllib.error, urllib.request
live = []
for path in pathlib.Path('/tmp').glob('docreview-runtime-gate-*.json'):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor) as stream:
        metadata = os.fstat(stream.fileno())
        if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o600:
            sys.exit('Runtime reset token file permissions are invalid')
        if metadata.st_uid != os.getuid():
            sys.exit('Runtime reset token file owner differs from application user')
        record = json.load(stream)
    pid = record.get('pid')
    if type(pid) is not int or pid <= 0:
        sys.exit('Runtime reset token process identity is invalid')
    if pathlib.Path('/proc', str(pid)).exists():
        live.append(record)
if len(live) != 1:
    sys.exit('Reset requires exactly one live application gate worker')
payload = json.loads(sys.argv[2])
request = urllib.request.Request(
    'http://127.0.0.1:8000/_internal/reset/' + sys.argv[1],
    data=json.dumps(payload).encode() if payload is not None else None,
    headers={'Content-Type': 'application/json', 'X-DocReview-Reset': live[0]['token']},
    method='POST' if payload is not None else 'GET',
)
try:
    with urllib.request.urlopen(request, timeout=10) as response:
        print(response.read().decode())
except urllib.error.HTTPError as error:
    sys.exit('Runtime reset gate rejected the request: HTTP ' + str(error.code))
"""
        return json.loads(
            await self._run(
                "docker", "exec", container, "python", "-c", code, action, json.dumps(payload)
            )
        )

    def _check_single_worker(self, app: dict[str, Any]) -> None:
        """Require the known single-worker Uvicorn development process contract."""
        command = app["Config"].get("Cmd") or []
        environment = dict(item.split("=", 1) for item in app["Config"]["Env"])
        if "uvicorn" not in command or any(
            environment.get(key, "1") != "1" for key in ("WEB_CONCURRENCY", "UVICORN_WORKERS")
        ):
            raise WipeError("Reset requires the single-worker Uvicorn development app")
        for index, argument in enumerate(command):
            if argument == "--workers" and command[index + 1 : index + 2] != ["1"]:
                raise WipeError("Reset requires one application worker")
            if argument.startswith("--workers=") and argument != "--workers=1":
                raise WipeError("Reset requires one application worker")

    async def inspect(self, *, details: bool = True) -> dict[str, Any]:
        """Reject nonlocal targets and active work before exposing a deletion preview."""
        if self.busy():
            raise WipeError(
                "Finish active local operations before resetting", code="active_local_operations"
            )
        daemon = await self._docker_identity()
        rows = []
        for service in ("db", "app"):
            ids = (
                await self._run(
                    "docker",
                    "ps",
                    "-aq",
                    "--filter",
                    f"label=com.docker.compose.project={self.root.name}",
                    "--filter",
                    f"label=com.docker.compose.service={service}",
                )
            ).split()
            if len(ids) != 1:
                raise WipeError(f"Expected exactly one local {service} container")
            row = json.loads(await self._run("docker", "inspect", ids[0]))[0]
            labels = row["Config"]["Labels"]
            if (
                Path(labels.get("com.docker.compose.project.working_dir", "")).resolve()
                != self.root
            ):
                raise WipeError("Container belongs to another checkout")
            rows.append(row)
        database, app = rows
        app_env = dict(item.split("=", 1) for item in app["Config"]["Env"])
        if app_env.get("MODE") != "dev" or app_env.get("DOCREVIEW_ADMIN_MODE") != "live":
            raise WipeError("Reset is only available for the live local development stack")
        self._check_single_worker(app)
        db_env = dict(item.split("=", 1) for item in database["Config"]["Env"])
        if any(
            db_env.get(key) != "filing"
            for key in ("POSTGRES_USER", "POSTGRES_DB", "POSTGRES_PASSWORD")
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
        data_mounts = [item for item in app["Mounts"] if item["Destination"] == "/app/data"]
        if (
            len(data_mounts) != 1
            or data_mounts[0]["Type"] != "bind"
            or Path(data_mounts[0]["Source"]).resolve() != self.root / "data"
            or app_env.get("CORPUS_DIR") != "/app/data/corpus"
        ):
            raise WipeError("Application runtime files do not belong to this checkout")
        ports = database["NetworkSettings"]["Ports"].get("5432/tcp") or []
        if len(ports) != 1 or ports[0]["HostIp"] not in {"127.0.0.1"}:
            raise WipeError("Database must have one loopback-only published port")
        port = int(ports[0]["HostPort"])
        configured = dotenv_values(self.root / ".env").get("DATABASE_URL") or os.environ.get(
            "DATABASE_URL"
        )
        if configured:
            url = make_url(configured)
            if (
                url.host not in {"localhost", "127.0.0.1", "::1"}
                or (url.port or 5432) != port
                or url.database != "filing"
            ):
                raise WipeError("Host database configuration points outside the local stack")
        mounts = [m for m in database["Mounts"] if m["Destination"] == "/var/lib/postgresql/data"]
        if len(mounts) != 1 or mounts[0]["Type"] != "volume":
            raise WipeError("Database does not use the expected named volume")
        volume = mounts[0]["Name"]
        volume_info = json.loads(await self._run("docker", "volume", "inspect", volume))[0]
        if (volume_info.get("Labels") or {}).get("com.docker.compose.project") != self.root.name:
            raise WipeError("Database volume belongs to another project")
        if volume_info.get("Driver") != "local" or volume_info.get("Options"):
            raise WipeError("Database volume must use local storage without driver options")
        compose_json = await self._run(*self._compose("config", "--format", "json"))
        compose = json.loads(compose_json)
        self._compose_json = compose_json
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
        tables = (
            (
                await self._sql(
                    database["Id"],
                    "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename",
                )
            ).split()
            if details
            else []
        )
        counts = {}
        for table in tables:
            if not table.replace("_", "").isalnum():
                raise WipeError("Unexpected database table identifier")
            counts[table] = int(await self._sql(database["Id"], f'SELECT count(*) FROM "{table}"'))
        for table in ("operator_jobs",):
            if table in counts and int(
                await self._sql(
                    database["Id"],
                    f"SELECT count(*) FROM {table} WHERE status IN ('queued','running','pending')",
                )
            ):
                raise WipeError(
                    "Finish active jobs and review runs before resetting",
                    code="active_jobs",
                    details={"table": table},
                    remediation=[
                        "Wait for queued or running jobs to finish, or cancel them in Jobs. "
                        "Then check reset availability again."
                    ],
                )
        if app.get("State", {}).get("Running"):
            activity = await self._runtime_request(app["Id"], "activity")
            if activity.get("active_requests") != 0:
                raise WipeError("Finish active application requests before resetting")
            if activity.get("held") and (self._lease is None or self._lease[0] != app["Id"]):
                raise WipeError("Another reset holds application request admission")
            instance = activity.get("instance")
            if not isinstance(instance, str) or not instance:
                raise WipeError("Application request gate identity is unavailable")
            if self._lease is not None and (
                not activity.get("held") or instance != self._lease_instance
            ):
                raise WipeError("Application request gate restarted or lost the reset hold")
        elif self._stopped_app != app["Id"]:
            raise WipeError("Start the development app before inspecting its request activity")
        else:
            instance = self._lease_instance
            if details and int(
                await self._sql(
                    database["Id"],
                    "SELECT count(*) FROM pg_stat_activity WHERE datname='filing' "
                    "AND backend_type='client backend' AND pid <> pg_backend_pid()",
                )
            ):
                raise WipeError("Close other database clients before resetting")
        tracked = set((await self._run("git", "ls-files", "-z")).split("\0")) if details else set()
        return {
            "project": self.root.name,
            "daemon": daemon,
            "compose_sha256": hashlib.sha256(compose_json.encode()).hexdigest(),
            "database_container": database["Id"],
            "app_container": app["Id"],
            "gate_instance": instance,
            "volume": volume,
            "port": port,
            "tables": counts,
            "files": self._files(tracked) if details else [],
        }

    async def capability(self) -> dict[str, Any]:
        """Verify every preview prerequisite without issuing a token or changing runtime data."""
        async with self.lock:
            try:
                if self._task is not None and not self._task.done():
                    raise WipeError("Reset is already running")
                if self._lease is not None:
                    raise WipeError(
                        "Release the interrupted reset hold before requesting a preview"
                    )
                await self.inspect()
            except (WipeError, ValueError, OSError, KeyError, TypeError, IndexError) as error:
                return {
                    "available": False,
                    "reason": redact_sensitive_text(str(error)),
                    "checked_at": datetime.now(UTC).isoformat(),
                    "diagnosis": diagnose_wipe_error(error),
                }
            return {
                "available": True,
                "reason": None,
                "checked_at": datetime.now(UTC).isoformat(),
                "diagnosis": None,
            }

    async def _sql(self, container: str, query: str) -> str:
        """Query the verified database directly without using external connection settings."""
        return (
            await self._run(
                "docker",
                "exec",
                container,
                "psql",
                "-U",
                "filing",
                "-d",
                "filing",
                "-At",
                "-v",
                "ON_ERROR_STOP=1",
                "-c",
                query,
            )
        ).strip()

    async def preview(self) -> dict[str, Any]:
        """Issue one confirmation token for the current target, valid for five minutes."""
        async with self.lock:
            if self._task and not self._task.done():
                raise WipeError("Reset is already running")
            if self._lease is not None:
                raise WipeError("Release the interrupted reset hold before requesting a preview")
            target = await self.inspect()
            self._preview = {"token": str(uuid4()), "expires": time.time() + 300, "target": target}
            return {
                **self._preview,
                "confirmation": f"WIPE {self.root.name}",
                "preserved": [
                    "Code and Git files",
                    ".env and keys",
                    "Tutorials and images",
                    "Manifest, golden, and profile sources",
                    "Unrelated files",
                ],
                "backup": False,
            }

    async def start(self, token: str, confirmation: str) -> dict[str, Any]:
        """Consume an unchanged preview once, then execute the reset asynchronously."""
        async with self.lock:
            preview = self._preview
            if not preview or token != preview["token"] or time.time() > preview["expires"]:
                raise WipeError("Reset preview is missing or expired")
            if confirmation != f"WIPE {self.root.name}":
                raise WipeError("Confirmation text does not match")
            self._acquire_operation()
            try:
                target = await self.inspect()
                if target != preview["target"]:
                    self._preview = None
                    raise WipeError("Reset targets changed; preview them again")
            except BaseException:
                self._release_operation()
                raise
            self._preview = None
            self._result = {
                "id": str(uuid4()),
                "status": "running",
                "stage": "starting",
                "completed": [],
                "message": "Reset started; no backup will be made",
            }
            try:
                self._persist()
                self._task = asyncio.create_task(self._execute(target))
            except BaseException:
                self._result.update(status="failed", message="Reset could not persist its start")
                self._release_operation()
                raise
            return self.result()

    def result(self) -> dict[str, Any]:
        """Return reset evidence independently of the wiped database."""
        result = deepcopy(self._result)
        result["recovery_required"] = self._lease is not None
        result["retryable"] = result["status"] in {"failed", "interrupted"} and self._lease is None
        if result["status"] in {"failed", "interrupted"}:
            result["recovery"] = [
                "Review the recorded stage and completed steps; reset never resumes automatically.",
                *(
                    ["Release the retained reset hold before requesting another preview."]
                    if self._lease
                    else []
                ),
                "Restore stopped development services and verify database schema readiness.",
                "Retry only with a fresh preview and exact confirmation; no backup exists.",
            ]
        return result

    async def recover(self) -> dict[str, Any]:
        """Explicitly release only a recorded admission hold without retrying data deletion."""
        async with self.lock:
            if self._task is not None and not self._task.done():
                raise WipeError("Reset is already running")
            if self._lease is None:
                return self.result()
            self._acquire_operation()
            try:
                daemon = await self._docker_identity()
                if self._lease_daemon is None or any(
                    self._lease_daemon.get(key) != daemon.get(key) for key in ("id", "endpoint")
                ):
                    raise WipeError("Docker target changed; inspect the interrupted reset manually")
                container, lease = self._lease
                present = (
                    await self._run(
                        "docker", "ps", "-aq", "--no-trunc", "--filter", f"id={container}"
                    )
                ).split()
                if present and present != [container]:
                    raise WipeError("Interrupted application container identity is ambiguous")
                row = (
                    json.loads(await self._run("docker", "inspect", container))[0]
                    if present
                    else None
                )
                if row is not None and row["State"]["Running"]:
                    activity = await self._runtime_request(container, "activity")
                    if activity.get("instance") == self._lease_instance:
                        await self._runtime_request(container, "release", {"lease": lease})
                self._lease = None
                self._lease_instance = None
                self._lease_daemon = None
                self._result.pop("recovery_error", None)
                self._persist()
            finally:
                self._release_operation()
            return self.result()

    async def close(self) -> None:
        """Join cancellation so a restarted operator cannot leave reset children running."""
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                self._result.update(status="interrupted", message="Operator stopped during reset")
                self._persist()
                self._release_operation()

    def _remove_file(self, item: dict[str, Any]) -> None:
        """Unlink a verified runtime entry through directory descriptors without following links."""
        relative = Path(item["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise WipeError("Runtime file escaped the checkout")
        directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for component in relative.parts[:-1]:
                child = os.open(
                    component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory
                )
                os.close(directory)
                directory = child
            descriptor = os.open(
                relative.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
            )
            with os.fdopen(descriptor, "rb") as stream:
                opened = os.fstat(stream.fileno())
                if (
                    not stat.S_ISREG(opened.st_mode)
                    or hashlib.file_digest(stream, "sha256").hexdigest() != item["sha256"]
                ):
                    raise WipeError(f"File changed during reset: {item['path']}")
                current = os.stat(relative.name, dir_fd=directory, follow_symlinks=False)
                if (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
                    raise WipeError(f"File changed during reset: {item['path']}")
                os.unlink(relative.name, dir_fd=directory)
        finally:
            os.close(directory)

    def _persist(self) -> None:
        """Atomically preserve minimal local reset progress without corpus contents."""
        descriptor, filename = tempfile.mkstemp(
            prefix=self._audit.name + ".", dir=self._audit.parent
        )
        temporary = Path(filename)
        with os.fdopen(descriptor, "w") as stream:
            json.dump(
                {
                    "result": self._result,
                    "lease": self._lease,
                    "lease_instance": self._lease_instance,
                    "lease_daemon": self._lease_daemon,
                },
                stream,
            )
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(self._audit)

    def _stage(self, name: str) -> None:
        """Record the next operation before attempting it."""
        self._result["stage"] = name
        self._persist()

    async def _execute(self, target: dict[str, Any]) -> None:
        """Reset one explicit volume and allowlisted files, reporting partial failures."""
        try:
            await self._run(
                str(self.root / ".venv/bin/python"),
                "-c",
                "from app.db.bootstrap import bootstrap_schema",
            )
            self._lease = (target["app_container"], str(uuid4()))
            self._lease_instance = target["gate_instance"]
            self._lease_daemon = target["daemon"]
            self._stage("hold_requests")
            held = await self._runtime_request(
                target["app_container"], "hold", {"lease": self._lease[1]}
            )
            if (
                held.get("lease") != self._lease[1]
                or held.get("instance") != target["gate_instance"]
            ):
                raise WipeError("Application request gate changed while acquiring the reset hold")
            if await self.inspect() != target:
                raise WipeError("Runtime changed before stopping the app; no data was deleted")
            self._stage("stop_app")
            await self._run("docker", "stop", target["app_container"])
            self._result["completed"].append("app_stopped")
            self._stopped_app = target["app_container"]
            self._lease = None
            self._lease_daemon = None
            if await self.inspect() != target:
                raise WipeError("Runtime changed while stopping the app; no data was deleted")
            compose_json = self._compose_json
            if (
                compose_json is None
                or hashlib.sha256(compose_json.encode()).hexdigest() != target["compose_sha256"]
            ):
                raise WipeError("The verified Compose configuration is unavailable")
            self._stage("database_volume")
            await self._run("docker", "stop", target["database_container"])
            await self._run("docker", "rm", target["database_container"])
            await self._run("docker", "volume", "rm", target["volume"])
            self._result["completed"].append("database_removed")
            self._stage("runtime_files")
            removed = 0
            for item in target["files"]:
                self._remove_file(item)
                removed += 1
                self._result["removed_files"] = removed
                self._persist()
            self._result["completed"].append("runtime_files_removed")
            self._stage("empty_schema")
            await self._run(
                *self._compose("up", "-d", "--wait", "db", frozen=True), input_text=compose_json
            )
            recreated = await self.inspect()
            if any(recreated[key] != target[key] for key in ("daemon", "volume", "port")):
                raise WipeError("Recreated database differs from the verified local target")
            environment = dict(os.environ)
            environment["DOCREVIEW_WIPE_DATABASE"] = (
                f"postgresql+asyncpg://filing:filing@127.0.0.1:{target['port']}/filing"
            )
            code = """import asyncio, os
from sqlalchemy.ext.asyncio import create_async_engine
from app.db.bootstrap import bootstrap_schema
async def main():
    engine = create_async_engine(os.environ['DOCREVIEW_WIPE_DATABASE'])
    try:
        await bootstrap_schema(engine)
    finally:
        await engine.dispose()
asyncio.run(main())
"""
            await self._run(
                str(self.root / ".venv/bin/python"), "-c", code, environment=environment
            )
            self._result["completed"].append("empty_schema_created")
            self._stage("restart_app")
            await self._run(
                *self._compose("up", "-d", "--no-deps", "--wait", "app", frozen=True),
                input_text=compose_json,
            )
            self._stopped_app = None
            self._lease_instance = None
            after = await self.inspect()
            required_tables = {"documents", "chunks", "runs", "operator_jobs", "eval_results"}
            if not required_tables.issubset(after["tables"]) or any(after["tables"].values()):
                raise WipeError("Database postcondition failed: expected empty runtime tables")
            if after["files"]:
                raise WipeError("File postcondition failed: runtime files remain")
            self._result.update(
                status="succeeded",
                stage="complete",
                message="Runtime data cleared; the browser can now reset its DocReview data",
            )
        except asyncio.CancelledError:
            self._result.update(status="interrupted", message="Operator stopped during reset")
        except (WipeError, OSError, ValueError, KeyError, TypeError, IndexError) as error:
            self._result.update(status="failed", message=redact_sensitive_text(str(error)))
        finally:
            if self._lease is not None:
                container, lease = self._lease
                if "app_stopped" not in self._result["completed"]:
                    try:
                        await self._runtime_request(container, "release", {"lease": lease})
                    except (WipeError, OSError, ValueError, KeyError) as error:
                        self._result["recovery_error"] = redact_sensitive_text(str(error))
                    else:
                        self._lease = None
                        self._lease_instance = None
                        self._lease_daemon = None
            try:
                self._persist()
            finally:
                self._stopped_app = None
                if self._lease is None:
                    self._lease_instance = None
                self._release_operation()
