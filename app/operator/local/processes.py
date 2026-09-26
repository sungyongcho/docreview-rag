"""Bounded supervision for fixed commands on the local checkout."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
import os
from pathlib import Path
import signal
from typing import Literal
from uuid import uuid4

from app.contracts.validation import StrictSchema
from app.observability.redaction import redact_sensitive_text
from app.operator.local.commands import COMMANDS, OperatorCommand

type JobStatus = Literal["running", "succeeded", "failed", "cancelled", "timed_out"]

MAX_LOG_CHARS = 256_000

MAX_HISTORY = 20


class JobResource(StrictSchema):
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
