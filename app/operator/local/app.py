"""Authenticated loopback API for fixed local-checkout operations."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.contracts.validation import StrictSchema
from app.observability.redaction import redact_sensitive_text
from app.operator.local.commands import CommandTarget
from app.operator.local.processes import JobResource, OperatorJobManager
from app.operator.local.receipts import LifecycleReceipt, lifecycle_receipts
from app.operator.reset.commands import WipeError, diagnose_wipe_error
from app.operator.reset.service import WipeService


class CommandResource(StrictSchema):
    """Public command metadata without an editable argv surface."""

    command_id: str
    label: str
    description: str
    category: str
    target: CommandTarget
    confirmation: str | None
    timeout_seconds: int


class StartJobRequest(StrictSchema):
    """Select one command by its immutable registry identifier."""

    command_id: str


class WipeStartRequest(StrictSchema):
    """Bind destructive execution to one verified preview and exact confirmation."""

    token: str
    confirmation: str


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
    async def wipe_preview(_authorized: None = Depends(authorize)) -> dict | JSONResponse:
        """Inspect a local-only reset without changing runtime data."""
        try:
            return await wipe.preview()
        except (WipeError, ValueError, OSError, KeyError, TypeError, IndexError) as error:
            return wipe_failure(error)

    @application.post("/wipe", status_code=202, response_model=None)
    async def start_wipe(
        body: WipeStartRequest, _authorized: None = Depends(authorize)
    ) -> dict | JSONResponse:
        """Start the exact confirmed reset while keeping its operator UI available."""
        try:
            return await wipe.start(body.token, body.confirmation)
        except (WipeError, ValueError, OSError, KeyError, TypeError, IndexError) as error:
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
