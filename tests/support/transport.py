"""Stand-ins for the tool transport: MCP servers to connect to and an MCP client.

- :func:`module_server` launches any server module, real or controlled, over stdio;
- :class:`ControlledServer` is the real filings server with only its data layer
  replaced (:mod:`tests.support.controlled_filings`), optionally behind a relay that
  records every JSON-RPC line (:mod:`tests.support.stdio_relay`), or served over HTTP;
- :class:`ScriptedMCPClient` stands in for an MCP client, for code that only needs
  a client to list tools and call them, or that must see one fail.
"""

import asyncio
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from typing import Any, Self

from fastmcp.client.transports import StdioTransport
from mcp import StdioServerParameters
from mcp.types import CallToolResult, ListToolsResult, Tool

from tests.support import REPO_ROOT

PROTOCOL_MODE = "2026-07-28"
CONTROLLED_FILINGS = "tests.support.controlled_filings"
CELL_FILINGS = "tests.support.cell_filings"
STDIO_RELAY = "tests.support.stdio_relay"
STARTUP_SECONDS = 15
EVENT_SECONDS = 5


def module_server(
    module: str, *args: str, env: dict[str, str] | None = None
) -> StdioServerParameters:
    """Launch ``python -m module`` from the repository root as a stdio server."""
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", module, *args],
        env={**os.environ, **(env or {})},
        cwd=REPO_ROOT,
    )


def stdio_transport(params: StdioServerParameters) -> StdioTransport:
    """The same stdio server as a FastMCP transport, for LangChain's MCP adapter."""
    return StdioTransport(
        params.command,
        params.args,
        env=params.env,
        cwd=None if params.cwd is None else str(params.cwd),
        keep_alive=False,
    )


def read_jsonl(path: Path, start: int = 0) -> list[dict[str, Any]]:
    """Parse the JSON lines of ``path`` after line ``start``; a missing file has none."""
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines[start:]]


class ControlledServer:
    """The real filings MCP server with only its data layer replaced.

    ``work`` holds ``events.jsonl``, where the server logs every retrieval and chunk
    body read, so a test can tell which requests reached the data layer. With
    ``relayed`` the server runs behind a stdio relay that records each JSON-RPC
    direction in ``requests.jsonl`` and ``responses.jsonl`` beside it. ``module``
    selects the server variant (the plain controlled server or the stored-cell one),
    and ``server_args`` are passed to it unchanged.
    """

    def __init__(
        self,
        work: Path,
        *server_args: str,
        relayed: bool = False,
        module: str = CONTROLLED_FILINGS,
        env: dict[str, str] | None = None,
    ) -> None:
        work.mkdir(parents=True, exist_ok=True)
        self.work = work
        self.log = work / "events.jsonl"
        self.log.touch()
        self.module = module
        arguments = (str(self.log), *server_args)
        if relayed:
            self.params = module_server(STDIO_RELAY, str(work), module, *arguments, env=env)
        else:
            self.params = module_server(module, *arguments, env=env)

    def transport(self) -> StdioTransport:
        """This server as a FastMCP transport, for LangChain's MCP adapter."""
        return stdio_transport(self.params)

    def events(self, start: int = 0) -> list[dict[str, Any]]:
        """Data-layer events the server logged after event number ``start``."""
        return read_jsonl(self.log, start)

    def body_loads(self, start: int = 0) -> list[int]:
        """Chunk ids whose body the data layer read after event number ``start``."""
        return [e["chunk_id"] for e in self.events(start) if e["event"] == "body_load"]

    def requests(self, start: int = 0) -> list[dict[str, Any]]:
        """JSON-RPC requests the relay recorded after request number ``start``."""
        return read_jsonl(self.work / "requests.jsonl", start)

    def tool_calls(self, start: int = 0) -> list[dict[str, Any]]:
        """The params of every ``tools/call`` the relay recorded after request ``start``."""
        return [r["params"] for r in self.requests(start) if r.get("method") == "tools/call"]

    def responses(self) -> list[dict[str, Any]]:
        """JSON-RPC messages the relay recorded from the server."""
        return read_jsonl(self.work / "responses.jsonl")

    async def wait_for_event(self, name: str) -> None:
        """Wait until the data layer logs ``name``; fail instead of hanging."""
        async with asyncio.timeout(EVENT_SECONDS):
            while not any(event["event"] == name for event in self.events()):
                await asyncio.sleep(0.02)

    @contextmanager
    def http(self) -> Iterator[tuple[str, subprocess.Popen[bytes]]]:
        """Serve over Streamable HTTP on a free loopback port and always stop afterwards.

        Yields the MCP endpoint URL and the server process.
        """
        port = free_port()
        process = subprocess.Popen(
            [sys.executable, "-m", self.module, str(self.log), "--http", str(port)],
            cwd=REPO_ROOT,
        )
        try:
            wait_listening(port, process)
            yield f"http://127.0.0.1:{port}/mcp", process
        finally:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def free_port() -> int:
    """Ask the OS for a loopback port that is free right now."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_listening(port: int, process: subprocess.Popen[bytes]) -> None:
    """Wait until the port accepts connections; fail instead of hanging."""
    deadline = time.monotonic() + STARTUP_SECONDS
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError(f"server exited early with code {process.returncode}")
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            return
        except OSError:
            time.sleep(0.1)
    raise AssertionError(f"server did not listen on port {port}")


EMPTY_SEARCH = CallToolResult(content=[], structured_content={"hits": []})


class ScriptedMCPClient:
    """MCP client stand-in: lists fixed tools, answers every call alike, fails on cue.

    Every ``call_tool`` returns ``result``, or raises ``call_error``, and is recorded
    in ``calls``. ``start_error`` and ``stop_error`` fail entering and leaving the
    client context, as a server that does not start or stop would. Calling the
    instance like the ``mcp.Client`` class records the server it was asked to start
    and returns the instance, so it can be patched over that class.
    """

    def __init__(
        self,
        result: CallToolResult = EMPTY_SEARCH,
        *,
        tools: Sequence[Tool] = (),
        call_error: BaseException | None = None,
        start_error: BaseException | None = None,
        stop_error: BaseException | None = None,
    ) -> None:
        self.result = result
        self.tools = list(tools)
        self.call_error = call_error
        self.start_error = start_error
        self.stop_error = stop_error
        self.servers: list[object] = []
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, server: object, **options: object) -> Self:
        """Record the server a caller asked to start and hand out this client."""
        del options
        self.servers.append(server)
        return self

    async def __aenter__(self) -> Self:
        """Start, or fail to start, the server."""
        if self.start_error is not None:
            raise self.start_error
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        """Stop the server, or fail to."""
        if self.stop_error is not None:
            raise self.stop_error

    async def list_tools(self) -> ListToolsResult:
        """List the fixed tools."""
        return ListToolsResult(tools=list(self.tools))

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> CallToolResult:
        """Record the call, then raise the fixed error or return the fixed result."""
        self.calls.append((name, arguments))
        if self.call_error is not None:
            raise self.call_error
        return self.result
