"""Section 3.3: what actually crosses stdio between the client and the server."""

import asyncio

from mcp import Client

from tests.mcp.support import write_catalog
from tests.support.transport import PROTOCOL_MODE, STDIO_RELAY, module_server, read_jsonl


def test_each_request_carries_the_version_and_gets_one_matching_response(tmp_path):
    """Discovery, listing and a call each pair with exactly one response by ID."""
    write_catalog(tmp_path, 1)
    trace = tmp_path / "trace"
    trace.mkdir()

    async def exercise():
        """Discover, list tools and call list_corpus through the recording relay."""
        relay = module_server(
            STDIO_RELAY,
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
    requests = read_jsonl(trace / "requests.jsonl")
    responses = read_jsonl(trace / "responses.jsonl")
    calls = [request for request in requests if "id" in request]
    assert {"server/discover", "tools/list", "tools/call"} <= {call["method"] for call in calls}
    for call in calls:
        matching = [response for response in responses if response.get("id") == call["id"]]
        assert len(matching) == 1, call["method"]
        assert "result" in matching[0], call["method"]
        meta = call["params"]["_meta"]
        assert meta["io.modelcontextprotocol/protocolVersion"] == PROTOCOL_MODE
