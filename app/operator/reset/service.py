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
import tempfile
import time
from typing import Any
from uuid import uuid4

from app.atomic_write import write_text_atomically
from app.observability.redaction import redact_sensitive_text
from app.operator.reset.commands import WipeCommandRunner, WipeError, diagnose_wipe_error
from app.operator.reset.files import list_runtime_files, remove_runtime_file
from app.operator.reset.inspection import (
    verify_compose_plan,
    verify_database_volume,
    verify_gate_activity,
    verify_stack_containers,
)


class WipeService:
    """Bind a short-lived preview to local Docker identity and exact runtime files."""

    def __init__(self, root: Path, busy: Callable[[], bool]) -> None:
        """Keep confirmation state outside the database being reset."""
        self.root = root.resolve()
        self.busy = busy
        self._preview: dict[str, Any] | None = None
        self.lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None
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
            if (
                not isinstance(recorded, dict)
                or set(recorded) != {"result", "lease", "lease_instance", "lease_daemon"}
                or not isinstance(recorded["result"], dict)
            ):
                raise WipeError("Reset audit does not match the current format")
            self._result = recorded["result"]
            if recorded["lease"] is not None:
                self._lease = tuple(recorded["lease"])
                self._lease_instance = recorded["lease_instance"]
                self._lease_daemon = recorded["lease_daemon"]
                if self._lease_daemon is None:
                    raise WipeError("Reset audit daemon identity is missing")
            if self._result["status"] == "running":
                self._result.update(status="interrupted", message="Operator restarted during reset")
        docker_host: str | None = None
        if self._lease_daemon is not None:
            # A recorded reset hold pins every Docker command to the daemon it was taken on.
            docker_host = self._lease_daemon["endpoint"]
        self.commands = WipeCommandRunner(self.root, docker_host=docker_host)

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

    async def inspect(self) -> dict[str, Any]:
        """Reject nonlocal targets and active work before exposing a deletion preview."""
        if self.busy():
            raise WipeError(
                "Finish active local operations before resetting", code="active_local_operations"
            )
        daemon = await self.commands.verify_docker_identity()
        rows = []
        for service in ("db", "app"):
            ids = (
                await self.commands.run(
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
            row = json.loads(await self.commands.run("docker", "inspect", ids[0]))[0]
            labels = row["Config"]["Labels"]
            if (
                Path(labels.get("com.docker.compose.project.working_dir", "")).resolve()
                != self.root
            ):
                raise WipeError("Container belongs to another checkout")
            rows.append(row)
        database, app = rows
        port, volume = verify_stack_containers(self.root, database, app)
        volume_info = json.loads(await self.commands.run("docker", "volume", "inspect", volume))[0]
        verify_database_volume(self.root.name, volume_info)
        compose_json = await self.commands.run(
            *self.commands.compose_command("config", "--format", "json")
        )
        compose = json.loads(compose_json)
        self._compose_json = compose_json
        verify_compose_plan(compose, port=port, volume=volume)
        tables = (
            await self.commands.query_database(
                database["Id"],
                "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename",
            )
        ).split()
        counts = {}
        for table in tables:
            if not table.replace("_", "").isalnum():
                raise WipeError("Unexpected database table identifier")
            counts[table] = int(
                await self.commands.query_database(
                    database["Id"], f'SELECT count(*) FROM "{table}"'
                )
            )
        for table in ("operator_jobs",):
            if table in counts and int(
                await self.commands.query_database(
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
            activity = await self.commands.request_runtime_gate(app["Id"], "activity")
            instance = verify_gate_activity(
                activity,
                app_container=app["Id"],
                lease=self._lease,
                lease_instance=self._lease_instance,
            )
        elif self._stopped_app != app["Id"]:
            raise WipeError("Start the development app before inspecting its request activity")
        else:
            instance = self._lease_instance
            if int(
                await self.commands.query_database(
                    database["Id"],
                    "SELECT count(*) FROM pg_stat_activity WHERE datname='filing' "
                    "AND backend_type='client backend' AND pid <> pg_backend_pid()",
                )
            ):
                raise WipeError("Close other database clients before resetting")
        tracked = set((await self.commands.run("git", "ls-files", "-z")).split("\0"))
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
            "files": list_runtime_files(self.root, tracked),
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
                daemon = await self.commands.verify_docker_identity()
                if self._lease_daemon is None or any(
                    self._lease_daemon.get(key) != daemon.get(key) for key in ("id", "endpoint")
                ):
                    raise WipeError("Docker target changed; inspect the interrupted reset manually")
                container, lease = self._lease
                present = (
                    await self.commands.run(
                        "docker", "ps", "-aq", "--no-trunc", "--filter", f"id={container}"
                    )
                ).split()
                if present and present != [container]:
                    raise WipeError("Interrupted application container identity is ambiguous")
                row = (
                    json.loads(await self.commands.run("docker", "inspect", container))[0]
                    if present
                    else None
                )
                if row is not None and row["State"]["Running"]:
                    activity = await self.commands.request_runtime_gate(container, "activity")
                    if activity.get("instance") == self._lease_instance:
                        await self.commands.request_runtime_gate(
                            container, "release", {"lease": lease}
                        )
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

    def _persist(self) -> None:
        """Atomically preserve minimal local reset progress without corpus contents."""
        progress = {
            "result": self._result,
            "lease": self._lease,
            "lease_instance": self._lease_instance,
            "lease_daemon": self._lease_daemon,
        }
        write_text_atomically(
            self._audit,
            json.dumps(progress),
            mode=0o600,
            apply_umask=True,
            encoding=None,
        )

    def _stage(self, name: str) -> None:
        """Record the next operation before attempting it."""
        self._result["stage"] = name
        self._persist()

    async def _execute(self, target: dict[str, Any]) -> None:
        """Reset one explicit volume and allowlisted files, reporting partial failures."""
        try:
            await self.commands.run(
                str(self.root / ".venv/bin/python"),
                "-c",
                "from app.db.bootstrap import bootstrap_schema",
            )
            self._lease = (target["app_container"], str(uuid4()))
            self._lease_instance = target["gate_instance"]
            self._lease_daemon = target["daemon"]
            self._stage("hold_requests")
            held = await self.commands.request_runtime_gate(
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
            await self.commands.run("docker", "stop", target["app_container"])
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
            await self.commands.run("docker", "stop", target["database_container"])
            await self.commands.run("docker", "rm", target["database_container"])
            await self.commands.run("docker", "volume", "rm", target["volume"])
            self._result["completed"].append("database_removed")
            self._stage("runtime_files")
            removed = 0
            for item in target["files"]:
                remove_runtime_file(self.root, item)
                removed += 1
                self._result["removed_files"] = removed
                self._persist()
            self._result["completed"].append("runtime_files_removed")
            self._stage("empty_schema")
            await self.commands.run(
                *self.commands.compose_command("up", "-d", "--wait", "db", frozen=True),
                input_text=compose_json,
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
            await self.commands.run(
                str(self.root / ".venv/bin/python"), "-c", code, environment=environment
            )
            self._result["completed"].append("empty_schema_created")
            self._stage("restart_app")
            await self.commands.run(
                *self.commands.compose_command(
                    "up", "-d", "--no-deps", "--wait", "app", frozen=True
                ),
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
                        await self.commands.request_runtime_gate(
                            container, "release", {"lease": lease}
                        )
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
