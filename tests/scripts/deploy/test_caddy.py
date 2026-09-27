"""Exercise the deployed Caddyfile with local Caddy 2.10 and a loopback HTTP server."""

import asyncio
from collections.abc import Iterable
import contextlib
from decimal import Decimal
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket
import subprocess
import threading
import time
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI, Request
import pytest
from starlette.requests import ClientDisconnect

from app.release.ai_allowance import SharedAIAllowance
from app.release.middleware import ReleaseGuardMiddleware, client_key

ROOT = Path(__file__).resolve().parents[3]
BODY_LIMIT = 256 * 1024
EXECUTION_PATHS = ("/retrieve", "/review", "/review/stream")
VISITOR_HEADERS = (
    "CF-Connecting-IP",
    "CF-Connecting-IPv6",
    "CF-Pseudo-IPv4",
    "True-Client-IP",
    "X-Real-IP",
    "Forwarded",
)


def docker(*args):
    """Run bounded commands against the local engine without pulling images."""
    return subprocess.run(
        ["docker", "--host", "unix:///var/run/docker.sock", *args],
        capture_output=True,
        text=True,
        timeout=20,
        check=True,
    ).stdout.strip()


@pytest.fixture(scope="module")
def proxy(tmp_path_factory):
    """Run the existing 2.10 image with temporary state and loopback-only listeners."""
    release_stream = threading.Event()
    guard_started = threading.Event()
    directory = tmp_path_factory.mktemp("caddy")
    ledger = SharedAIAllowance(directory / "limits.sqlite3", Decimal("1"), 1, 1)
    peer = Request({"type": "http", "client": ("127.0.0.1", 0), "headers": []})
    asyncio.run(ledger.admit(client_key(peer, trust_proxy_headers=False, salt=ledger.salt)))
    guard = ReleaseGuardMiddleware(FastAPI(), allowance=ledger, trust_proxy_headers=False)

    async def unexpected_execution(_request):
        """Fail if a request past the shared cap reaches application execution."""
        raise AssertionError("an exhausted request must not execute")

    class Backend(BaseHTTPRequestHandler):
        """Report received requests and hold an SSE stream open for a flush assertion."""

        protocol_version = "HTTP/1.1"

        def log_message(self, *_args):
            """Keep expected rejected-request disconnects out of test output."""

        def _read_body(self):
            """Read complete fixed-length or chunked bodies, excluding proxy aborts."""
            self.connection.settimeout(3)
            if self.headers.get("Transfer-Encoding") == "chunked":
                body = bytearray()
                while True:
                    size_line = self.rfile.readline()
                    if not size_line:
                        return None
                    size = int(size_line.split(b";")[0], 16)
                    if size == 0:
                        self.rfile.readline()
                        return bytes(body)
                    chunk = self.rfile.read(size)
                    if len(chunk) != size or self.rfile.read(2) != b"\r\n":
                        return None
                    body.extend(chunk)
            size = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(size)
            return body if len(body) == size else None

        def _guard_request(self):
            """Exercise the actual exhausted Python guard over this real proxy request."""
            guard_started.set()
            path, _, query = self.path.partition("?")
            scope = {
                "type": "http",
                "method": self.command,
                "scheme": "http",
                "path": path,
                "raw_path": path.encode(),
                "query_string": query.encode(),
                "headers": [
                    (key.lower().encode(), value.encode()) for key, value in self.headers.items()
                ],
                "client": self.client_address,
                "server": self.server.server_address,
            }

            async def receive():
                """Expose raw transport bytes or the proxy's oversized-body disconnect."""
                body = self._read_body()
                if body is None:
                    return {"type": "http.disconnect"}
                return {"type": "http.request", "body": body, "more_body": False}

            try:
                response = asyncio.run(
                    guard.dispatch(Request(scope, receive), unexpected_execution)
                )
            except ClientDisconnect:
                self.close_connection = True
                return
            self.send_response(response.status_code)
            for name, value in response.headers.items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(response.body)

        def _handle(self):
            """Echo complete bodies, invoke the real guard, or deliver a two-frame SSE stream."""
            if self.headers.get("X-Test-Deny") == "true":
                self._guard_request()
                return
            body = self._read_body()
            if body is None:
                self.close_connection = True
                return
            if self.headers.get("X-Test-Stream") == "true":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(b"data: first\n\n")
                self.wfile.flush()
                if release_stream.wait(10):
                    self.wfile.write(b"data: last\n\n")
                    self.wfile.flush()
                self.close_connection = True
                return
            payload = json.dumps(
                {
                    "path": self.path,
                    "method": self.command,
                    "size": len(body),
                    "headers": {key.lower(): value for key, value in self.headers.items()},
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            """Serve the readiness probe and non-execution requests."""
            self._handle()

        def do_POST(self):
            """Echo allowed execution payloads or stream SSE."""
            self._handle()

    backend = ThreadingHTTPServer(("127.0.0.1", 0), Backend)
    thread = threading.Thread(target=backend.serve_forever, daemon=True)
    thread.start()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    config = directory / "Caddyfile"
    source = (ROOT / "deploy/Caddyfile").read_text()
    config.write_text(
        "{\n\tadmin off\n\tauto_https off\n}\n"
        + source.replace(":80 {", f"http://127.0.0.1:{port} {{", 1).replace(
            "app:8000", f"127.0.0.1:{backend.server_port}"
        )
    )
    name = f"docreview-caddy-test-{uuid4().hex}"
    started = False
    try:
        docker(
            "run",
            "--detach",
            "--rm",
            "--pull=never",
            "--name",
            name,
            "--network=host",
            "--read-only",
            "--tmpfs=/config",
            "--tmpfs=/data",
            "--mount",
            f"type=bind,src={config},dst=/etc/caddy/Caddyfile,readonly",
            "caddy:2.10-alpine",
        )
        started = True
        version = docker("exec", name, "caddy", "version")
        assert version.startswith("v2.10."), version
        deadline = time.monotonic() + 5
        while True:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                    break
            except OSError:
                if time.monotonic() >= deadline:
                    pytest.fail(f"Caddy did not start: {docker('logs', name)}")
                time.sleep(0.02)
        yield SimpleNamespace(port=port, release_stream=release_stream, guard_started=guard_started)
    finally:
        release_stream.set()
        if started:
            docker("stop", "--time=2", name)
        backend.shutdown()
        backend.server_close()
        thread.join(timeout=3)


def request(
    proxy,
    path,
    *,
    method="POST",
    body: bytes | Iterable[bytes] = b"{}",
    headers=None,
    chunked=False,
):
    """Return one real proxy response without redirects or automatic retries."""
    with contextlib.closing(http.client.HTTPConnection("127.0.0.1", proxy.port, timeout=3)) as conn:
        conn.request(method, path, body, headers or {}, encode_chunked=chunked)
        response = conn.getresponse()
        return response.status, response.read()


def test_client_ip_headers_are_removed_and_forwarded_for_is_peer(proxy):
    """Spoofed visitor headers cannot reach the application or replace its peer key."""
    supplied = {header: "203.0.113.8" for header in VISITOR_HEADERS}
    supplied["X-Forwarded-For"] = "198.51.100.9, 203.0.113.8"
    supplied["CF-Connecting-IPv6"] = "2001:db8::8"
    supplied["Forwarded"] = 'for="[2001:db8::8]";proto=https'
    status, payload = request(proxy, "/review/", headers=supplied)
    assert status == 200
    observed = json.loads(payload)
    assert observed["path"] == "/review"
    assert observed["headers"]["x-forwarded-for"] == "127.0.0.1"
    assert observed["headers"]["x-docreview-public"] == "true"
    assert all(header.lower() not in observed["headers"] for header in VISITOR_HEADERS)


@pytest.mark.parametrize("path", EXECUTION_PATHS)
@pytest.mark.parametrize("suffix", ("", "/"))
@pytest.mark.parametrize("chunked", (False, True))
def test_execution_body_limit_accepts_boundary_and_rejects_next_byte(proxy, path, suffix, chunked):
    """Every protected path enforces exactly 256 KiB, including unknown-length bodies."""
    allowed = b"x" * BODY_LIMIT
    body = iter((allowed,)) if chunked else allowed
    status, payload = request(proxy, path + suffix, body=body, chunked=chunked)
    assert status == 200
    assert json.loads(payload)["size"] == BODY_LIMIT
    oversized = iter((allowed, b"x")) if chunked else allowed + b"x"
    status, _ = request(proxy, path + suffix, body=oversized, chunked=chunked)
    assert status == 413


@pytest.mark.parametrize(("method", "path"), (("GET", "/review/"), ("POST", "/health")))
def test_body_limit_is_scoped_to_execution_posts(proxy, method, path):
    """Unrelated methods and public paths retain the existing proxy behavior."""
    status, payload = request(proxy, path, method=method, body=b"x" * (BODY_LIMIT + 1))
    assert status == 200
    assert json.loads(payload)["size"] == BODY_LIMIT + 1


@pytest.mark.parametrize("path", EXECUTION_PATHS)
@pytest.mark.parametrize("suffix", ("", "/"))
@pytest.mark.parametrize("chunked", (False, True))
def test_size_rejection_precedes_the_python_guards_rate_denial(proxy, path, suffix, chunked):
    """Raw-body checking preserves Caddy's 413 while the exhausted Python guard never executes."""
    allowed = b"x" * BODY_LIMIT
    body = iter((allowed,)) if chunked else allowed
    status, payload = request(
        proxy, path + suffix, body=body, headers={"X-Test-Deny": "true"}, chunked=chunked
    )
    assert status == 429
    assert json.loads(payload)["error"]["code"] == "rate_limited"
    proxy.guard_started.clear()

    def oversized_body():
        """Finish the oversized upload only after the real upstream has started handling it."""
        yield b"x"
        assert proxy.guard_started.wait(2)
        yield b"x" * BODY_LIMIT

    headers = {"X-Test-Deny": "true"}
    if not chunked:
        headers["Content-Length"] = str(BODY_LIMIT + 1)
    status, _ = request(
        proxy, path + suffix, body=oversized_body(), headers=headers, chunked=chunked
    )
    assert status == 413


def test_sse_reaches_client_before_upstream_finishes(proxy):
    """The first SSE frame is readable while the backend still waits to send the last."""
    proxy.release_stream.clear()
    with contextlib.closing(http.client.HTTPConnection("127.0.0.1", proxy.port, timeout=3)) as conn:
        conn.request("POST", "/review/stream/", b"{}", {"X-Test-Stream": "true"})
        response = conn.getresponse()
        try:
            assert response.status == 200
            assert response.getheader("Content-Type") == "text/event-stream"
            assert response.readline() == b"data: first\n"
            assert response.readline() == b"\n"
            assert not proxy.release_stream.is_set()
        finally:
            proxy.release_stream.set()
        assert response.read() == b"data: last\n\n"
