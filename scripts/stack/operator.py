"""Own one authenticated host Operations process for this checkout."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import secrets
import signal
import stat
import subprocess
import sys
import tempfile
import time
from typing import Any
from urllib.error import URLError
from urllib.request import ProxyHandler, Request, build_opener


class OperatorLifecycleError(RuntimeError):
    """A host operation could not safely start or stop its owned service."""


class LocalOperator:
    """Keep launch credentials private and verify process identity before stopping."""

    def __init__(self, root: Path) -> None:
        """Locate private per-user state for one repository."""
        self.root = root.resolve()
        identity = hashlib.sha256(str(self.root).encode()).hexdigest()[:12]
        self.directory = (
            Path(tempfile.gettempdir()) / f"docreview-operator-{os.getuid()}-{identity}"
        )
        self.directory.mkdir(mode=0o700, exist_ok=True)
        info = self.directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise OperatorLifecycleError(
                "Operations state directory must be private and owned by this user"
            )
        self.state_path = self.directory / "state.json"

    @contextmanager
    def _locked(self) -> Iterator[None]:
        """Serialize lifecycle updates without exposing tokens to other users."""
        descriptor = os.open(self.directory / "lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "w") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            yield

    def _read(self) -> dict[str, Any] | None:
        """Load only this launcher's private state; corrupt state fails closed."""
        try:
            value = json.loads(self.state_path.read_text())
        except FileNotFoundError:
            return None
        except (ValueError, OSError) as error:
            raise OperatorLifecycleError("Cannot read Operations launch state") from error
        if (
            not isinstance(value, dict)
            or not {"pid", "start_time", "token", "origin", "port"} <= value.keys()
        ):
            raise OperatorLifecycleError("Operations launch state is invalid")
        return value

    @staticmethod
    def _identity(pid: int) -> tuple[str, str, list[str]] | None:
        """Read Linux PID start time, working directory, and exact module argv."""
        process = Path("/proc") / str(pid)
        try:
            fields = (process / "stat").read_text().rsplit(")", 1)[1].split()
            if fields[0] == "Z":
                return None
            return (
                fields[19],
                str((process / "cwd").resolve(strict=True)),
                (process / "cmdline").read_text().split("\0"),
            )
        except FileNotFoundError, ProcessLookupError:
            return None
        except PermissionError as error:
            raise OperatorLifecycleError(
                "Cannot verify the saved Operations process identity"
            ) from error

    def _owned(self, state: dict[str, Any]) -> bool:
        """Reject PID reuse or a process belonging to another checkout."""
        identity = self._identity(int(state["pid"]))
        return (
            identity is not None
            and identity[0] == state["start_time"]
            and identity[1] == str(self.root)
            and identity[2][1:3] == ["-m", "app.operator"]
        )

    @staticmethod
    def _reachable(state: dict[str, Any]) -> bool:
        """Verify the exact saved token and origin over the read-only commands route."""
        request = Request(
            f"http://127.0.0.1:{state['port']}/commands",
            headers={"Origin": state["origin"], "Authorization": f"Bearer {state['token']}"},
        )
        try:
            with build_opener(ProxyHandler({})).open(request, timeout=1) as response:
                return response.status == 200
        except URLError, TimeoutError:
            return False

    @staticmethod
    def _public_environment(state: dict[str, Any]) -> dict[str, str]:
        """Return only the browser credentials needed by the live web container."""
        return {
            "NEXT_PUBLIC_OPERATOR_BASE_URL": f"http://127.0.0.1:{state['port']}",
            "NEXT_PUBLIC_OPERATOR_TOKEN": state["token"],
        }

    def environment(self) -> dict[str, str]:
        """Reuse a verified live service for non-starting Compose commands."""
        with self._locked():
            state = self._read()
            if state and self._owned(state) and self._reachable(state):
                return self._public_environment(state)
            return {"NEXT_PUBLIC_OPERATOR_BASE_URL": "", "NEXT_PUBLIC_OPERATOR_TOKEN": ""}

    def client_connection(self) -> tuple[str, str, str]:
        """Return verified live connection data even after an extreme reset removes .env."""
        with self._locked():
            state = self._read()
            if not state or not self._owned(state) or not self._reachable(state):
                raise OperatorLifecycleError("Start the development stack first: rag-dev up -d")
            return (f"http://127.0.0.1:{state['port']}", state["origin"], state["token"])

    def _stop(self, state: dict[str, Any]) -> None:
        """Gracefully stop only the identified service, retaining state on timeout."""
        if self._owned(state):
            os.kill(int(state["pid"]), signal.SIGTERM)
            deadline = time.monotonic() + 15
            while self._owned(state):
                if time.monotonic() >= deadline:
                    raise OperatorLifecycleError(
                        "Operations is still shutting down; retry after its running job finishes"
                    )
                time.sleep(0.1)
        self.state_path.unlink(missing_ok=True)

    def stop(self) -> None:
        """Remove a stale record or stop this checkout's owned Operations server."""
        with self._locked():
            state = self._read()
            if state:
                self._stop(state)

    def start(self, bindings: dict[str, str]) -> dict[str, str]:
        """Start or reuse a detached host service without launching an interactive shell."""
        origin = f"http://{bindings['DOCREVIEW_LOCAL_HOST']}:{bindings['APP_PORT']}"
        port = bindings["DOCREVIEW_OPERATOR_PORT"]
        with self._locked():
            previous = self._read()
            if previous and self._owned(previous):
                if (
                    previous["origin"] == origin
                    and previous["port"] == port
                    and self._reachable(previous)
                ):
                    return self._public_environment(previous)
                self._stop(previous)
            token = secrets.token_urlsafe(32)
            environment = (
                os.environ
                | bindings
                | {
                    "MODE": "dev",
                    "DOCREVIEW_OPERATOR_TOKEN": token,
                    "DOCREVIEW_OPERATOR_ORIGIN": origin,
                    "DOCREVIEW_OPERATOR_PORT": port,
                }
            )
            descriptor = os.open(
                self.directory / "operator.log",
                os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW,
                0o600,
            )
            with os.fdopen(descriptor, "ab") as log:
                process = subprocess.Popen(
                    [sys.executable, "-m", "app.operator"],
                    cwd=self.root,
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=log,
                    start_new_session=True,
                )
            identity = self._identity(process.pid)
            if identity is None:
                raise OperatorLifecycleError(
                    f"Operations exited before startup; inspect {self.directory / 'operator.log'}"
                )
            state = {
                "pid": process.pid,
                "start_time": identity[0],
                "token": token,
                "origin": origin,
                "port": port,
            }
            descriptor = os.open(
                self.state_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600
            )
            with os.fdopen(descriptor, "w") as handle:
                json.dump(state, handle)
            deadline = time.monotonic() + 10
            while process.poll() is None and time.monotonic() < deadline:
                if self._reachable(state):
                    return self._public_environment(state)
                time.sleep(0.1)
            self._stop(state)
            raise OperatorLifecycleError(
                f"Operations could not start on port {port}; "
                f"inspect {self.directory / 'operator.log'} (an existing server is not stopped)"
            )
