"""Section 3.5: closing the client ends the server, and cancellation reaches the tool."""

import asyncio
from contextlib import suppress
import json
import os
from pathlib import Path
import sys

from mcp import Client, StdioServerParameters
import pytest

from tests.mcp.support import PROTOCOL_MODE

SERVER_SOURCE = '''"""Temporary asynchronous server for a cancellation experiment."""
import json
import os
from pathlib import Path
from typing import TypedDict
import anyio
from mcp.server import MCPServer

class Status(TypedDict):
    """Structured observation of the temporary server."""
    pid: int
    events: list[str]

server = MCPServer("Lifecycle test")
events = []
log = Path(__file__).with_name("events.json")

def record(event):
    """Persist observable events without writing logs to protocol stdout."""
    events.append(event)
    log.write_text(json.dumps(events))

@server.tool()
async def wait_for_work() -> str:
    """Wait long enough for the client to cancel this asynchronous operation."""
    record("started")
    try:
        await anyio.sleep(60)
        record("completed")
        return "finished"
    except anyio.get_cancelled_exc_class():
        record("cancelled")
        raise
    finally:
        record("finally")

@server.tool()
def status() -> Status:
    """Report this process identity and recorded tool events."""
    return {"pid": os.getpid(), "events": list(events)}

if __name__ == "__main__":
    server.run(transport="stdio")
'''


def alive(pid: int) -> bool:
    """Check whether the observed child process still exists."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


async def wait_for_event(path: Path, event: str) -> None:
    """Wait for server evidence, bounded so a failed experiment cannot hang."""
    async with asyncio.timeout(5):
        while True:
            if path.exists():
                with suppress(json.JSONDecodeError):  # The server may be mid-write.
                    if event in json.loads(path.read_text()):
                        return
            await asyncio.sleep(0.02)


async def exercise(directory: Path, cancel: bool) -> tuple[int, list[str]]:
    """Run one child lifetime; optionally cancel a tool call before closing."""
    server = directory / "server.py"
    server.write_text(SERVER_SOURCE)
    events = directory / "events.json"
    parameters = StdioServerParameters(command=sys.executable, args=[str(server)])
    async with Client(parameters, mode=PROTOCOL_MODE) as client:
        initial = await client.call_tool("status", {})
        pid = initial.structured_content["pid"]
        assert alive(pid)
        if cancel:
            task = asyncio.create_task(client.call_tool("wait_for_work", {}))
            await wait_for_event(events, "started")
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            assert task.cancelled()
            await wait_for_event(events, "finally")
        after = await client.call_tool("status", {})
        assert after.structured_content["pid"] == pid
        assert alive(pid)
    async with asyncio.timeout(5):
        while alive(pid):
            await asyncio.sleep(0.02)
    return pid, after.structured_content["events"]


@pytest.mark.parametrize(
    ("cancel", "expected"), [(False, []), (True, ["started", "cancelled", "finally"])]
)
def test_server_process_ends_with_the_client(tmp_path, cancel, expected):
    """The same connection survives a cancelled call, and closing reaps the child."""
    pid, events = asyncio.run(exercise(tmp_path, cancel))
    assert events == expected
    assert not alive(pid)
