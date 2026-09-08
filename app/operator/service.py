"""Authenticated loopback API for fixed local-checkout operations."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
import os
from pathlib import Path
import signal
from typing import Literal
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from app.observability.persistence import redact_sensitive_text
from app.operator.commands import COMMANDS, CommandTarget, OperatorCommand
from app.operator.lifecycle_receipts import LifecycleReceipt, lifecycle_receipts
from app.operator.wipe import WipeError, WipeService, diagnose_wipe_error

type JobStatus = Literal["running", "succeeded", "failed", "cancelled", "timed_out"]

MAX_LOG_CHARS = 256_000
MAX_HISTORY = 20


class StrictOperatorModel(BaseModel):
    """Frozen strict base for the local operator API."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class CommandResource(StrictOperatorModel):
    """Public command metadata without an editable argv surface."""

    command_id: str
    label: str
    description: str
    category: str
    target: CommandTarget
    confirmation: str | None
    timeout_seconds: int


class StartJobRequest(StrictOperatorModel):
    """Select one command by its immutable registry identifier."""

    command_id: str


class WipePreviewRequest(StrictOperatorModel):
    """Select the explicit reset mode; ordinary browser requests remain unchanged."""

    extreme: bool = False


class BrowserClearedRequest(StrictOperatorModel):
    """Identify the exact reset acknowledged by the browser after storage deletion."""

    operation_id: str


class WipeStartRequest(StrictOperatorModel):
    """Bind destructive execution to one verified preview and exact confirmation."""

    token: str
    confirmation: str
    backup_confirmed: bool = False


class JobResource(StrictOperatorModel):
    """Bounded command execution state returned to the browser."""

    job_id: str
    command_id: str
    label: str
    status: JobStatus
    output: str
    exit_code: int | None
    started_at: datetime
    finished_at: datetime | None


@dataclass(slots=True)
class _Job:
    """Mutable process state held only by one local service instance."""

    job_id: str
    command: OperatorCommand
    status: JobStatus = "running"
    output: str = ""
    exit_code: int | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    process: asyncio.subprocess.Process | None = None
    stop_reason: JobStatus | None = None

    def resource(self) -> JobResource:
        """Freeze the current internal state for one API response."""
        return JobResource(
            job_id=self.job_id,
            command_id=self.command.command_id,
            label=self.command.label,
            status=self.status,
            output=self.output,
            exit_code=self.exit_code,
            started_at=self.started_at,
            finished_at=self.finished_at,
        )


class OperatorJobManager:
    """Run at most one fixed command and retain bounded recent evidence."""

    def __init__(
        self,
        root: Path,
        commands: Mapping[str, OperatorCommand] = COMMANDS,
    ) -> None:
        self._root = root.resolve()
        self._commands = commands
        self._jobs: dict[str, _Job] = {}
        self._order: deque[str] = deque()
        self._active: _Job | None = None
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    @property
    def commands(self) -> Mapping[str, OperatorCommand]:
        """Expose the immutable registry for resource projection."""
        return self._commands

    async def start(self, command_id: str) -> JobResource:
        """Start one registered operation or reject concurrent work."""
        async with self._lock:
            if self._active is not None and self._active.status == "running":
                raise RuntimeError("another operator command is already running")
            try:
                command = self._commands[command_id]
            except KeyError as error:
                raise KeyError(f"unknown operator command: {command_id}") from error
            job = _Job(job_id=str(uuid4()), command=command)
            self._jobs[job.job_id] = job
            self._order.appendleft(job.job_id)
            while len(self._order) > MAX_HISTORY:
                self._jobs.pop(self._order.pop(), None)
            self._active = job
            self._task = asyncio.create_task(self._run(job))
            return job.resource()

    def jobs(self) -> tuple[JobResource, ...]:
        """Return newest-first bounded job snapshots."""
        return tuple(self._jobs[job_id].resource() for job_id in self._order)

    def job(self, job_id: str) -> JobResource | None:
        """Return one known job snapshot."""
        job = self._jobs.get(job_id)
        return job.resource() if job is not None else None

    async def cancel(self, job_id: str) -> JobResource:
        """Cancel one running process group and preserve its final output."""
        job = self._jobs.get(job_id)
        if job is None:
            raise KeyError(job_id)
        if job.status != "running" or job.process is None:
            return job.resource()
        job.stop_reason = "cancelled"
        await self._terminate(job.process)
        if self._task is not None:
            await self._task
        return job.resource()

    async def close(self) -> None:
        """Stop an active child before the loopback service exits."""
        if self._active is not None and self._active.status == "running":
            await self.cancel(self._active.job_id)

    async def _run(self, job: _Job) -> None:
        """Execute one argv command with timeout and bounded redacted output."""
        command = job.command
        cwd = (self._root / command.cwd).resolve()
        if cwd != self._root and self._root not in cwd.parents:
            job.status = "failed"
            job.output = "Command working directory escaped the repository."
            job.finished_at = datetime.now(UTC)
            return
        environment = {**os.environ, **dict(command.environment)}
        try:
            job.process = await asyncio.create_subprocess_exec(
                *command.argv,
                cwd=cwd,
                env=environment,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                start_new_session=True,
            )
            assert job.process.stdout is not None
            reader = asyncio.create_task(self._capture(job, job.process.stdout))
            try:
                job.exit_code = await asyncio.wait_for(
                    job.process.wait(),
                    timeout=command.timeout_seconds,
                )
            except TimeoutError:
                job.stop_reason = "timed_out"
                await self._terminate(job.process)
                job.exit_code = job.process.returncode
            await reader
            job.status = job.stop_reason or ("succeeded" if job.exit_code == 0 else "failed")
        except Exception as error:
            job.status = "failed"
            self._append(job, f"{type(error).__name__}: {error}\n")
        finally:
            job.finished_at = datetime.now(UTC)
            if self._active is job:
                self._active = None

    async def _capture(
        self,
        job: _Job,
        stream: asyncio.StreamReader,
    ) -> None:
        """Capture one merged output stream without letting logs grow unbounded."""
        while chunk := await stream.read(4_096):
            self._append(job, chunk.decode("utf-8", errors="replace"))

    @staticmethod
    def _append(job: _Job, text: str) -> None:
        """Append redacted text while retaining only the newest bounded tail."""
        job.output = (job.output + redact_sensitive_text(text))[-MAX_LOG_CHARS:]

    @staticmethod
    async def _terminate(process: asyncio.subprocess.Process) -> None:
        """Terminate the complete child process group, escalating after five seconds."""
        if process.returncode is not None:
            return
        os.killpg(process.pid, signal.SIGTERM)
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except TimeoutError:
            os.killpg(process.pid, signal.SIGKILL)
            await process.wait()


def create_operator_app(
    *,
    token: str,
    allowed_origin: str,
    root: Path,
    manager: OperatorJobManager | None = None,
) -> FastAPI:
    """Create the authenticated loopback command application."""
    if not token.strip():
        raise ValueError("operator token must not be blank")
    parsed_origin = urlparse(allowed_origin)
    if (
        parsed_origin.scheme != "http"
        or parsed_origin.hostname not in {"127.0.0.1", "localhost"}
        or parsed_origin.port is None
        or parsed_origin.path not in {"", "/"}
        or parsed_origin.username is not None
        or parsed_origin.password is not None
        or parsed_origin.query
        or parsed_origin.fragment
    ):
        raise ValueError("operator origin must be the local Next development server")
    allowed_origins = {f"http://{host}:{parsed_origin.port}" for host in ("127.0.0.1", "localhost")}
    active_manager = manager or OperatorJobManager(root)
    wipe = WipeService(root, lambda: any(job.status == "running" for job in active_manager.jobs()))

    @asynccontextmanager
    async def lifespan(_application: FastAPI) -> AsyncIterator[None]:
        """Stop active child processes when the loopback service exits."""
        yield
        await wipe.close()
        await active_manager.close()

    application = FastAPI(
        title="DocReview Local Operations",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=sorted(allowed_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["authorization", "content-type"],
    )

    async def authorize(request: Request) -> None:
        """Require the launch token and a loopback origin on the configured web port."""
        if request.headers.get("origin") not in allowed_origins:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "operator origin rejected")
        if request.headers.get("authorization") != f"Bearer {token}":
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "operator token rejected")

    @application.get("/wipe/capability")
    async def wipe_capability(_authorized: None = Depends(authorize)) -> dict:
        """Verify all preview prerequisites without acquiring a hold or issuing a token."""
        return await wipe.capability()

    def wipe_failure(error: Exception) -> JSONResponse:
        """Preserve the legacy detail string and attach actionable reset diagnostics."""
        return JSONResponse(
            status_code=409,
            content={
                "detail": redact_sensitive_text(str(error)),
                "diagnosis": diagnose_wipe_error(error),
            },
        )

    @application.post("/wipe/recover", response_model=None)
    async def recover_wipe(_authorized: None = Depends(authorize)) -> dict | JSONResponse:
        """Release a recorded request hold without resuming an interrupted reset."""
        try:
            return await wipe.recover()
        except (WipeError, ValueError, OSError, KeyError, TypeError, IndexError) as error:
            return wipe_failure(error)

    @application.post("/wipe/preview", response_model=None)
    async def wipe_preview(
        body: WipePreviewRequest | None = None, _authorized: None = Depends(authorize)
    ) -> dict | JSONResponse:
        """Inspect a local-only reset without changing runtime data."""
        try:
            return await wipe.preview(extreme=bool(body and body.extreme))
        except (WipeError, ValueError, OSError, KeyError, TypeError, IndexError) as error:
            return wipe_failure(error)

    @application.post("/wipe", status_code=202, response_model=None)
    async def start_wipe(
        body: WipeStartRequest, _authorized: None = Depends(authorize)
    ) -> dict | JSONResponse:
        """Start the exact confirmed reset while keeping its operator UI available."""
        try:
            return await wipe.start(
                body.token, body.confirmation, backup_confirmed=body.backup_confirmed
            )
        except (WipeError, ValueError, OSError, KeyError, TypeError, IndexError) as error:
            return wipe_failure(error)

    @application.post("/wipe/browser-cleared", response_model=None)
    async def browser_cleared(
        body: BrowserClearedRequest, request: Request, _authorized: None = Depends(authorize)
    ) -> dict | JSONResponse:
        """Record a same-operation browser acknowledgement through existing local auth."""
        try:
            return wipe.acknowledge_browser(body.operation_id, request.headers["origin"])
        except WipeError as error:
            return wipe_failure(error)

    @application.get("/wipe")
    async def wipe_status(_authorized: None = Depends(authorize)) -> dict:
        """Return reset progress independently of application or database availability."""
        return wipe.result()

    @application.get("/lifecycle/receipts", response_model=tuple[LifecycleReceipt, ...])
    def read_lifecycle_receipts(
        _authorized: None = Depends(authorize),
    ) -> tuple[LifecycleReceipt, ...]:
        """Expose existing reset receipts through the same authenticated local operator."""
        try:
            return lifecycle_receipts(root)
        except (OSError, ValueError) as error:
            raise HTTPException(503, "Fresh-start receipt could not be read.") from error

    @application.get("/commands", response_model=tuple[CommandResource, ...])
    async def commands(_authorized: None = Depends(authorize)) -> tuple[CommandResource, ...]:
        """List fixed operations without exposing an editable argv."""
        return tuple(
            CommandResource(
                command_id=command.command_id,
                label=command.label,
                description=command.description,
                category=command.category,
                target=command.target,
                confirmation=command.confirmation,
                timeout_seconds=command.timeout_seconds,
            )
            for command in active_manager.commands.values()
        )

    @application.post("/jobs", response_model=JobResource, status_code=202)
    async def start_job(
        body: StartJobRequest,
        _authorized: None = Depends(authorize),
    ) -> JobResource:
        """Start one allowlisted command by identifier."""
        async with wipe.lock:
            if wipe.result()["status"] == "running":
                raise HTTPException(409, "Reset is running")
            try:
                return await active_manager.start(body.command_id)
            except KeyError as error:
                raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
            except RuntimeError as error:
                raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error

    @application.get("/jobs", response_model=tuple[JobResource, ...])
    async def jobs(_authorized: None = Depends(authorize)) -> tuple[JobResource, ...]:
        """List recent local operations newest first."""
        return active_manager.jobs()

    @application.get("/jobs/{job_id}", response_model=JobResource)
    async def job(job_id: str, _authorized: None = Depends(authorize)) -> JobResource:
        """Return one operation or a typed not-found response."""
        resource = active_manager.job(job_id)
        if resource is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "operator job not found")
        return resource

    @application.post("/jobs/{job_id}/cancel", response_model=JobResource)
    async def cancel_job(job_id: str, _authorized: None = Depends(authorize)) -> JobResource:
        """Cancel one running command process group."""
        try:
            return await active_manager.cancel(job_id)
        except KeyError as error:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "operator job not found") from error

    return application
