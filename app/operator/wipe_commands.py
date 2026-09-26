"""Reset commands scoped to one checkout, with Docker pinned to a verified local Unix socket."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import signal
import stat
from typing import Any
from urllib.parse import urlparse

from app.observability.persistence import redact_sensitive_text
from app.operator.wipe_errors import WipeError

# Environment variables that could send a Docker command to a daemon other than the pinned one.
DOCKER_TARGET_VARIABLES = ("DOCKER_CONTEXT", "DOCKER_HOST", "DOCKER_TLS", "DOCKER_TLS_VERIFY")

# Runs inside the app container, so it reaches the request gate over the container loopback and
# reads the gate token from the container's own /tmp instead of exposing it to the host.
RUNTIME_GATE_CLIENT = """import json, os, pathlib, stat, sys, urllib.error, urllib.request
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


class WipeCommandRunner:
    """Run exact reset commands in one checkout against one verified local Docker daemon.

    The Docker endpoint is resolved once and then passed explicitly to every later Docker
    command, so a context or environment change during a reset cannot redirect its deletions
    to another daemon.
    """

    def __init__(self, root: Path, *, docker_host: str | None = None) -> None:
        """Pin to a recorded endpoint, or start unpinned until the first identity check.

        Parameters
        ----------
        root : Path
            Resolved checkout root used as the working directory and Compose project.
        docker_host : str | None, optional
            Endpoint of the daemon a recorded reset hold was taken on. ``None`` leaves the
            runner unpinned until ``verify_docker_identity`` resolves the local socket.
        """
        self.root = root
        self._docker_host = docker_host

    async def run(
        self,
        *argv: str,
        environment: dict[str, str] | None = None,
        input_text: str | None = None,
    ) -> str:
        """Run exact arguments with bounded, redacted failure reporting."""
        environment = dict(os.environ if environment is None else environment)
        if argv[0] == "docker" and argv[1] != "context" and self._docker_host is not None:
            argv = ("docker", "--host", self._docker_host, *argv[1:])
            for key in DOCKER_TARGET_VARIABLES:
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
            await _kill_process_group(process)
            raise WipeError("Local reset command timed out") from None
        except asyncio.CancelledError:
            await _kill_process_group(process)
            raise
        if process.returncode:
            raise WipeError(redact_sensitive_text(stderr.decode(errors="replace")[-2000:]))
        return stdout.decode()

    async def verify_docker_identity(self) -> dict[str, Any]:
        """Pin all commands to a verified local Unix socket and daemon identity."""
        if self._docker_host is None:
            self._docker_host = await self._local_socket_endpoint()
        socket_path = Path(urlparse(self._docker_host).path)
        metadata = socket_path.stat()
        if not stat.S_ISSOCK(metadata.st_mode):
            raise WipeError("Docker endpoint is not a local Unix socket")
        daemon_id = (await self.run("docker", "info", "--format", "{{.ID}}")).strip()
        if not daemon_id:
            raise WipeError("Docker daemon identity is unavailable")
        return {
            "endpoint": self._docker_host,
            "id": daemon_id,
            "socket_device": metadata.st_dev,
            "socket_inode": metadata.st_ino,
        }

    async def _local_socket_endpoint(self) -> str:
        """Resolve the configured Docker endpoint and accept only an absolute local Unix socket.

        A TCP or SSH endpoint could reach a remote or forwarded daemon, so it is refused before
        any container is inspected.
        """
        context = os.environ.get("DOCKER_CONTEXT")
        host = os.environ.get("DOCKER_HOST") if not context else None
        if not host:
            arguments = (context,) if context else ()
            metadata = json.loads(await self.run("docker", "context", "inspect", *arguments))
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
        return f"unix://{Path(parsed.path).resolve()}"

    def compose_command(self, *arguments: str, frozen: bool = False) -> tuple[str, ...]:
        """Use only this checkout and the explicit development overlay.

        Parameters
        ----------
        *arguments : str
            Compose subcommand and its arguments.
        frozen : bool, default False
            Read the configuration from stdin, so a reset recreates services from the exact
            configuration verified during the preview instead of re-reading the files.
        """
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

    async def query_database(self, container: str, query: str) -> str:
        """Query the verified database directly without using external connection settings."""
        return (
            await self.run(
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

    async def request_runtime_gate(
        self, container: str, action: str, payload: dict[str, str] | None = None
    ) -> dict[str, Any]:
        """Contact the verified app's request gate only through its container loopback."""
        return json.loads(
            await self.run(
                "docker",
                "exec",
                container,
                "python",
                "-c",
                RUNTIME_GATE_CLIENT,
                action,
                json.dumps(payload),
            )
        )


async def _kill_process_group(process: asyncio.subprocess.Process) -> None:
    """Stop Docker CLI children before releasing an interrupted reset."""
    if process.returncode is None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await process.wait()
