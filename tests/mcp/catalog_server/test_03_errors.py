"""Section 3.4: protocol errors versus tool results that report a failure."""

import asyncio
import json
import subprocess
import sys

from mcp import Client

from tests.mcp.support import PROTOCOL_MODE, REPO_ROOT, module_server, text_of, write_catalog

META = {
    "io.modelcontextprotocol/protocolVersion": PROTOCOL_MODE,
    "io.modelcontextprotocol/clientInfo": {"name": "error-test", "version": "1.0"},
    "io.modelcontextprotocol/clientCapabilities": {},
}


def test_tool_failures_and_empty_results_stay_in_the_tool_result(tmp_path):
    """Missing catalogs and unknown tools set isError; an empty catalog does not."""
    manifest = tmp_path / "manifest.json"

    async def exercise():
        server = module_server("app.mcp.catalog_server", env={"CORPUS_DIR": str(tmp_path)})
        async with Client(server, mode=PROTOCOL_MODE) as client:
            missing = await client.call_tool("list_corpus", {})
            unknown = await client.call_tool("search_everything", {})
            write_catalog(tmp_path, 0)
            empty = await client.call_tool("list_corpus", {})
            write_catalog(tmp_path, 2)
            restored = await client.call_tool("list_corpus", {})
        return missing, unknown, empty, restored

    assert not manifest.exists()
    missing, unknown, empty, restored = asyncio.run(exercise())
    assert missing.is_error and text_of(missing)
    assert unknown.is_error
    assert not empty.is_error
    assert empty.structured_content == {"result": []}
    assert not restored.is_error
    assert len(restored.structured_content["result"]) == 2


def test_invalid_request_parameters_are_a_protocol_error_and_the_server_continues():
    """A non-string tool name gets JSON-RPC -32602 by ID; the next request succeeds."""
    requests = [
        {
            "jsonrpc": "2.0",
            "id": 101,
            "method": "tools/call",
            "params": {"name": 123, "arguments": {}, "_meta": META},
        },
        {"jsonrpc": "2.0", "id": 102, "method": "tools/list", "params": {"_meta": META}},
    ]
    responses = {}
    with subprocess.Popen(
        [sys.executable, "-m", "app.mcp.catalog_server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        cwd=REPO_ROOT,
    ) as server:
        assert server.stdin is not None and server.stdout is not None
        for request in requests:
            server.stdin.write(json.dumps(request) + "\n")
            server.stdin.flush()
            response = json.loads(server.stdout.readline())
            responses[response["id"]] = response
        server.stdin.close()
        assert server.wait(timeout=30) == 0
    assert responses[101]["error"]["code"] == -32602
    assert "result" not in responses[101]
    assert [tool["name"] for tool in responses[102]["result"]["tools"]] == ["list_corpus"]
