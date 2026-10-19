"""Section 3.3: what actually crosses stdio between the client and the server."""

import asyncio
import json

from mcp import Client

from tests.mcp.support import PROTOCOL_MODE, module_server, write_catalog


def read_lines(path):
    """Parse one recorded JSONL direction."""
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_each_request_carries_the_version_and_gets_one_matching_response(tmp_path):
    """Discovery, listing and a call each pair with exactly one response by ID."""
    write_catalog(tmp_path, 1)
    trace = tmp_path / "trace"
    trace.mkdir()

    async def exercise():
        relay = module_server(
            "tests.mcp.stdio_relay",
            str(trace),
            "app.mcp.catalog_server",
            env={"CORPUS_DIR": str(tmp_path)},
        )
        async with Client(relay, mode=PROTOCOL_MODE) as client:
            await client.session.send_discover(PROTOCOL_MODE)
            await client.list_tools()
            result = await client.call_tool("list_corpus", {})
            assert not result.is_error

    asyncio.run(exercise())
    requests = read_lines(trace / "requests.jsonl")
    responses = read_lines(trace / "responses.jsonl")
    calls = [request for request in requests if "id" in request]
    assert {"server/discover", "tools/list", "tools/call"} <= {call["method"] for call in calls}
    for call in calls:
        matching = [response for response in responses if response.get("id") == call["id"]]
        assert len(matching) == 1, call["method"]
        assert "result" in matching[0], call["method"]
        meta = call["params"]["_meta"]
        assert meta["io.modelcontextprotocol/protocolVersion"] == PROTOCOL_MODE
