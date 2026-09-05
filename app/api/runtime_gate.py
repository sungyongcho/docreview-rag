"""Authenticated local request admission for an explicitly confirmed runtime reset."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import secrets
import tempfile
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

CONTROL_PREFIX = "/_internal/reset/"
SAFE_READ_PATHS = frozenset({"/health", "/release", "/capabilities", "/limits"})


class ResetLease(BaseModel):
    """A caller-owned lease that can be released after an interrupted request."""

    model_config = ConfigDict(extra="forbid")
    lease: UUID


class RuntimeResetGate:
    """Keep request admission atomic on the single ASGI worker's event loop."""

    def __init__(self) -> None:
        """Construct inactive state without writing a token before application startup."""
        self.active_requests = 0
        self.instance = str(uuid4())
        self._lease: str | None = None
        self._token: str | None = None
        self._token_path: Path | None = None

    @asynccontextmanager
    async def lifespan(self, _app: FastAPI) -> AsyncIterator[None]:
        """Expose one owner-readable local control token for this worker's lifetime."""
        self._token = secrets.token_urlsafe(32)
        descriptor, filename = tempfile.mkstemp(
            prefix=f"docreview-runtime-gate-{os.getpid()}-", suffix=".json"
        )
        self._token_path = Path(filename)
        with os.fdopen(descriptor, "w") as stream:
            json.dump({"pid": os.getpid(), "token": self._token}, stream)
        try:
            yield
        finally:
            self._token_path.unlink(missing_ok=True)
            self._token_path = None
            self._token = None
            self._lease = None

    def authorize(self, request: Request) -> None:
        """Require both a container-loopback client and an undisclosed per-worker token."""
        supplied = request.headers.get("x-docreview-reset", "")
        if (
            request.client is None
            or request.client.host not in {"127.0.0.1", "::1"}
            or self._token is None
            or not supplied.isascii()
            or not secrets.compare_digest(supplied, self._token)
        ):
            raise HTTPException(403, "Runtime reset control is container-local only")

    def activity(self) -> dict[str, object]:
        """Publish capability and worker identity without exposing token or lease values."""
        return {
            "active_requests": self.active_requests,
            "held": self._lease is not None,
            "instance": self.instance,
        }

    def hold(self, lease: str) -> dict[str, str]:
        """Close admission only while idle, preserving idempotence for one exact lease."""
        if self.active_requests or self._lease not in {None, lease}:
            raise HTTPException(409, "Application requests or another reset are active")
        self._lease = lease
        return {"lease": lease, "instance": self.instance}

    def release(self, lease: str) -> None:
        """Release only the caller's lease; a repeated release is harmless."""
        if self._lease not in {None, lease}:
            raise HTTPException(409, "Reset lease does not match")
        self._lease = None


class RuntimeResetMiddleware:
    """Count requests through body, background-task, and streaming producer cleanup."""

    def __init__(self, app: ASGIApp, gate: RuntimeResetGate) -> None:
        """Attach the same gate instance used by the internal control routes."""
        self.app = app
        self.gate = gate

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Hold admission without releasing the count when only response headers finish."""
        path = scope.get("path", "")
        if (
            scope["type"] != "http"
            or path.startswith(CONTROL_PREFIX)
            or scope.get("method") == "OPTIONS"
            or scope.get("method") in {"GET", "HEAD"}
            and path in SAFE_READ_PATHS
        ):
            await self.app(scope, receive, send)
            return
        # These transitions contain no await: admission and hold are atomic on one worker.
        if self.gate._lease is not None:
            response = JSONResponse(
                {
                    "error": {
                        "code": "runtime_reset_held",
                        "message": "A confirmed local reset holds application requests.",
                        "details": [],
                    }
                },
                status_code=409,
            )
            await response(scope, receive, send)
            return
        self.gate.active_requests += 1
        try:
            await self.app(scope, receive, send)
        finally:
            self.gate.active_requests -= 1


def install_reset_gate(app: FastAPI, gate: RuntimeResetGate) -> None:
    """Install hidden authenticated controls on an explicitly enabled development app."""
    app.add_middleware(RuntimeResetMiddleware, gate=gate)

    @app.get(f"{CONTROL_PREFIX}activity", include_in_schema=False)
    async def activity(request: Request) -> dict[str, object]:
        """Inspect live request admission without changing it."""
        gate.authorize(request)
        return gate.activity()

    @app.post(f"{CONTROL_PREFIX}hold", include_in_schema=False)
    async def hold(request: Request, body: ResetLease) -> dict[str, str]:
        """Acquire an exact lease before the operator stops the application."""
        gate.authorize(request)
        return gate.hold(str(body.lease))

    @app.post(f"{CONTROL_PREFIX}release", include_in_schema=False)
    async def release(request: Request, body: ResetLease) -> dict[str, bool]:
        """Restore request admission after a reset aborts before application shutdown."""
        gate.authorize(request)
        gate.release(str(body.lease))
        return {"released": True}
