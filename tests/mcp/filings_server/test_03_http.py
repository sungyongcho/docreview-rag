"""Section 4.5: the filings server over loopback Streamable HTTP keeps the stdio contract."""

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
import json
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
from types import SimpleNamespace
from typing import Any, cast

import httpx
from mcp import Client
import pytest

from app.agent.loop import run_agent
from app.agent.provider import DeterministicToolProvider, ProviderTurn
from app.agent.tools.filings import build_default_registry
from app.agent.types import ToolCall
from app.db.session_factory import SessionFactory
from app.mcp import filings_server
from app.mcp.client import mcp_tool_registry
from tests.mcp.controlled_filings import PRIVATE_DETAIL
from tests.mcp.support import (
    PROTOCOL_MODE,
    REPO_ROOT,
    is_system_error,
    logged_events,
    text_of,
)

STARTUP_SECONDS = 15
EVENT_SECONDS = 5
# Request _meta a 2026-07-28 client sends with every call.
META = {
    "io.modelcontextprotocol/protocolVersion": PROTOCOL_MODE,
    "io.modelcontextprotocol/clientInfo": {"name": "raw-test", "version": "1.0"},
    "io.modelcontextprotocol/clientCapabilities": {},
}
RAW_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
    "MCP-Protocol-Version": PROTOCOL_MODE,
}
# JSON-RPC code for a routing header that disagrees with the body (HEADER_MISMATCH).
HEADER_MISMATCH = -32020


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


@contextmanager
def http_server(log_path: Path) -> Iterator[tuple[str, subprocess.Popen[bytes]]]:
    """Run the controlled filings server over HTTP and always stop it afterwards."""
    log_path.touch()
    port = free_port()
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "tests.mcp.controlled_filings",
            str(log_path),
            "--http",
            str(port),
        ],
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


async def wait_for_event(log_path: Path, name: str) -> None:
    """Wait until the data layer logs ``name``; fail instead of hanging."""
    async with asyncio.timeout(EVENT_SECONDS):
        while not any(event["event"] == name for event in logged_events(log_path)):
            await asyncio.sleep(0.02)


# (case, arguments, failed, system failure, retrievals reached)
SEARCHES = [
    ("hits", {"query": "revenue"}, False, False, 1),
    ("empty", {"query": "no-match"}, False, False, 1),
    ("blank", {"query": "   "}, True, False, 0),
    ("boolean-k", {"query": "revenue", "k": True}, True, False, 0),
    ("runtime-error", {"query": "fail"}, True, True, 1),
]

# (case, (tool, arguments) the model calls before final_answer, status, body reads,
# rejected step indexes); the questions run in order on one HTTP client.
QUESTIONS = [
    (
        "fetch before search is refused, after search allowed",
        [
            ("fetch_chunk", {"chunk_id": 2024}),
            ("search_filings", {"query": "revenue", "issuers": ["TEST"], "fiscal_years": [2024]}),
            ("fetch_chunk", {"chunk_id": 2024}),
        ],
        "ok",
        [2024],
        [0],
    ),
    (
        "a new question starts with no evidence",
        [("fetch_chunk", {"chunk_id": 2024})],
        "ok",
        [],
        [0],
    ),
    (
        "a system failure ends the run",
        [("compare_years", {"query": "fail-2024", "issuer": "TEST", "fiscal_years": [2023, 2024]})],
        "tool_error",
        [],
        [0],
    ),
]


def rpc_message(response: httpx.Response) -> dict[str, Any]:
    """Read the single JSON-RPC message from a JSON or SSE response body."""
    if response.headers["content-type"].startswith("text/event-stream"):
        data = [line[5:].strip() for line in response.text.splitlines() if line.startswith("data:")]
        return json.loads(data[-1])
    return response.json()


async def exercise(url: str, log_path: Path, process: subprocess.Popen[bytes]) -> SimpleNamespace:
    """Drive every client-visible behavior against one running server."""
    contracts = build_default_registry(cast(SessionFactory, object))
    async with Client(url, mode=PROTOCOL_MODE) as client:
        listing = await client.list_tools()
        searches = {}
        for case, arguments, *_ in SEARCHES:
            start = len(logged_events(log_path))
            result = await client.call_tool("search_filings", arguments)
            searches[case] = (result, logged_events(log_path, start))
        unknown = await client.call_tool("final_answer", {"answer": "x"})
    alive_after_close = process.poll() is None

    finish = {
        "label": "NOT_IN_DOCS",
        "answer": "NOT_IN_DOCS",
        "citations": [],
        "rationale": "This HTTP test checks question scope, not answer quality.",
    }
    async with Client(url, mode=PROTOCOL_MODE) as client:
        bridge = await mcp_tool_registry(client, contracts)
        questions = {}
        for case, actions, *_ in QUESTIONS:
            start = len(logged_events(log_path))
            # Only the model's decisions are scripted; every tool call runs over HTTP.
            turns = [
                ProviderTurn(
                    output_text="",
                    input_tokens=0,
                    output_tokens=0,
                    tool_calls=(
                        ToolCall(call_id="call", name=name, arguments_json=json.dumps(arguments)),
                    ),
                )
                for name, arguments in [*actions, ("final_answer", finish)]
            ]
            result = await run_agent(
                case, registry=bridge, provider=DeterministicToolProvider(turns)
            )
            questions[case] = (result, logged_events(log_path, start))

    async with Client(url, mode=PROTOCOL_MODE) as client:
        call = asyncio.create_task(client.call_tool("search_filings", {"query": "slow"}))
        await wait_for_event(log_path, "slow_started")
        call.cancel()
        with pytest.raises(asyncio.CancelledError):
            await call
        await wait_for_event(log_path, "slow_finally")
    slow = [e["event"] for e in logged_events(log_path) if e["event"].startswith("slow_")]

    async with httpx.AsyncClient(headers=RAW_HEADERS) as raw:

        async def post(method: str, params: dict[str, Any], **headers: str) -> httpx.Response:
            """Send one raw JSON-RPC request with extra HTTP headers."""
            body = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": method,
                "params": {**params, "_meta": META},
            }
            return await raw.post(url, json=body, headers=headers)

        failing = {"name": "search_filings", "arguments": {"query": "fail"}}
        routed = {"Mcp-Method": "tools/call", "Mcp-Name": "search_filings"}
        raw_results = {
            "tool failure": await post("tools/call", failing, **routed),
            "missing routing header": await post("tools/call", failing),
            "foreign host": await post(
                "tools/list", {}, **{"Mcp-Method": "tools/list", "Host": "evil.example"}
            ),
        }
    return SimpleNamespace(
        contracts=contracts,
        listing=listing,
        searches=searches,
        unknown=unknown,
        alive_after_close=alive_after_close,
        questions=questions,
        slow=slow,
        raw=raw_results,
    )


@pytest.fixture(scope="module")
def observed(tmp_path_factory) -> SimpleNamespace:
    """Run all client scenarios against one controlled HTTP server."""
    log_path = tmp_path_factory.mktemp("http") / "events.jsonl"
    with http_server(log_path) as (url, process):
        return asyncio.run(exercise(url, log_path, process))


# The stdio tool contract, unchanged over HTTP
def test_http_publishes_the_same_tools_and_schemas(observed):
    """HTTP lists the three filing tools with the registry's own input models."""
    names = [tool.name for tool in observed.listing.tools]
    assert names == list(filings_server.EXPOSED_TOOLS)
    for tool in observed.listing.tools:
        assert tool.input_schema == observed.contracts.get(tool.name).parameters.model_json_schema()


@pytest.mark.parametrize(("case", "arguments", "failed", "system", "retrievals"), SEARCHES)
def test_http_search_outcomes_match_the_stdio_contract(
    observed, case, arguments, failed, system, retrievals
):
    """Validation, empty results and failures keep their meaning over HTTP."""
    result, events = observed.searches[case]
    assert result.is_error == failed
    assert is_system_error(result) == system
    assert len(events) == retrievals
    assert PRIVATE_DETAIL not in text_of(result)
    if not failed:
        assert json.loads(text_of(result)) == result.structured_content


def test_http_rejects_the_loop_owned_final_answer(observed):
    """final_answer is still not a server tool, and refusing it is not a system failure."""
    assert observed.unknown.is_error
    assert "unknown tool" in text_of(observed.unknown).lower()
    assert not is_system_error(observed.unknown)


# Client lifecycle and per-question evidence
def test_the_server_outlives_its_clients(observed):
    """Closing a client does not stop the HTTP server, which no client owns."""
    assert observed.alive_after_close


@pytest.mark.parametrize(("case", "actions", "status", "reads", "rejected"), QUESTIONS)
def test_question_scope_holds_over_http(observed, case, actions, status, reads, rejected):
    """Evidence stays per question in the client; system failures stop the run."""
    result, events = observed.questions[case]
    assert result.status == status
    errors = [
        index
        for index, item in enumerate(result.steps)
        if item.observations and item.observations[0].error is not None
    ]
    assert errors == rejected
    assert [event["chunk_id"] for event in events if event["event"] == "body_load"] == reads
    if status == "tool_error":
        assert result.failure == "MCPSystemError: tool compare_years failed"


def test_client_cancellation_cancels_the_running_tool(observed):
    """Cancelling a call closes its response stream, which cancels the server tool."""
    assert observed.slow == ["slow_started", "slow_cancelled", "slow_finally"]


# Raw requests: which layer reports each outcome
def test_a_tool_failure_is_http_200_with_a_system_marker(observed):
    """Tool failures live inside a successful HTTP response, with no session ID."""
    response = observed.raw["tool failure"]
    assert response.status_code == 200
    assert "mcp-session-id" not in response.headers
    result = rpc_message(response)["result"]
    assert result["isError"] is True
    assert result["_meta"][filings_server.SYSTEM_ERROR_META] is True
    assert PRIVATE_DETAIL not in response.text


def test_a_missing_routing_header_is_refused(observed):
    """A tools/call without Mcp-Method is rejected at the HTTP layer."""
    response = observed.raw["missing routing header"]
    assert response.status_code == 400
    assert rpc_message(response)["error"]["code"] == HEADER_MISMATCH


def test_a_foreign_host_is_refused_before_mcp(observed):
    """Loopback binding enables DNS-rebinding protection for other Host headers."""
    response = observed.raw["foreign host"]
    assert response.status_code == 421
    assert response.text == "Invalid Host header"


# Process shutdown and the command line
@pytest.mark.parametrize(
    ("stop", "exit_code"),
    [
        (signal.SIGTERM, 128 + signal.SIGTERM),
        # Ctrl-C: Python ends an uncaught KeyboardInterrupt by re-raising SIGINT.
        (signal.SIGINT, -signal.SIGINT),
    ],
)
def test_a_stop_signal_ends_the_server_after_its_finally_block(tmp_path, stop, exit_code):
    """SIGTERM and SIGINT stop the server only after the caller's finally block ran."""
    log_path = tmp_path / "events.jsonl"
    with http_server(log_path) as (_, process):
        process.send_signal(stop)
        assert process.wait(timeout=10) == exit_code
    assert [event["event"] for event in logged_events(log_path)] == ["server_stopped"]


@pytest.mark.parametrize(("argv", "port"), [([], None), (["--http", "8765"], 8765)])
def test_stdio_is_the_default_and_http_needs_a_port(argv, port):
    """Without --http the server keeps stdio; --http PORT selects HTTP."""
    assert filings_server.parse_http_port(argv) == port


@pytest.mark.parametrize(
    "argv",
    [["--http"], ["--http", "0"], ["--http", "65536"], ["--http", "web"], ["--host", "0.0.0.0"]],
)
def test_invalid_transport_arguments_exit_with_usage(argv, capsys):
    """Bad ports and unsupported options exit with code 2 and a stderr message."""
    with pytest.raises(SystemExit) as stopped:
        filings_server.parse_http_port(argv)
    assert stopped.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "usage:" in captured.err


def test_the_module_entry_point_parses_arguments_before_serving():
    """``python -m app.mcp.filings_server`` rejects a bad port without starting."""
    completed = subprocess.run(
        [sys.executable, "-m", "app.mcp.filings_server", "--http", "0"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 2
    assert completed.stdout == ""
    assert "port must be between 1 and 65535" in completed.stderr


def test_production_mode_is_refused_before_serving_http(monkeypatch, capsys):
    """MODE=prod exits with code 2 on stderr before the HTTP server or database starts."""

    async def serve_http(registry, *, port):
        """Fail the test if main reaches the HTTP transport."""
        raise AssertionError("the server must not start in production mode")

    monkeypatch.setattr(filings_server, "get_settings", lambda: SimpleNamespace(environment="prod"))
    monkeypatch.setattr(filings_server, "serve_http", serve_http)

    with pytest.raises(SystemExit) as stopped:
        asyncio.run(filings_server.main(8765))

    assert stopped.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "refusing MODE=prod" in captured.err
