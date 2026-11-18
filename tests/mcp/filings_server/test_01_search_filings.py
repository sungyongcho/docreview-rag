"""Section 4.1: the existing search contract, unchanged, through a real MCP client."""

import asyncio
import json

from mcp import Client
import pytest

from app.tools.filings import SearchFilingsParams
from tests.mcp.support import (
    UNKNOWN_TOOLS,
    assert_internal_error,
    assert_unknown_tool,
    call_or_error,
    text_of,
)
from tests.support.controlled_filings import PRIVATE_DETAIL, SEARCH_CHUNK_ID
from tests.support.transport import PROTOCOL_MODE, ControlledServer

# (case, arguments, failed, system failure, retrievals reached); a correctable failure
# is an isError result, a system failure a JSON-RPC error, and the connection serves on.
CASES = [
    ("hits", {"query": "revenue"}, False, False, 1),
    ("empty", {"query": "no-match"}, False, False, 1),
    ("blank", {"query": "   "}, True, False, 0),
    ("zero-k", {"query": "revenue", "k": 0}, True, False, 0),
    ("boolean-k", {"query": "revenue", "k": True}, True, False, 0),
    ("string-k", {"query": "revenue", "k": "7"}, True, False, 0),
    ("missing-query", {}, True, False, 0),
    ("extra-field", {"query": "revenue", "unexpected": True}, True, False, 0),
    (
        "filters",
        {"query": "revenue", "k": 2, "issuers": ["TEST"], "fiscal_years": [2024]},
        False,
        False,
        1,
    ),
    ("runtime-error", {"query": "fail"}, True, True, 1),
    ("after-error", {"query": "revenue"}, False, False, 1),
]


@pytest.fixture(scope="module")
def observed(tmp_path_factory):
    """Run every case on one connection and keep each result with its data-layer events."""
    server = ControlledServer(tmp_path_factory.mktemp("search"))

    async def exercise():
        """List tools, run each search case with its events, then unknown names and a search."""
        async with Client(server.params, mode=PROTOCOL_MODE) as client:
            listing = await client.list_tools()
            results = {}
            for case, arguments, *_ in CASES:
                start = len(server.events())
                outcome = await call_or_error(client, "search_filings", arguments)
                results[case] = (*outcome, server.events(start))
            unknown = {
                name: await call_or_error(client, name, {"answer": "x"}) for name in UNKNOWN_TOOLS
            }
            after = await call_or_error(client, "search_filings", {"query": "revenue"})
        return listing, results, (unknown, after)

    return asyncio.run(exercise())


def test_server_publishes_the_existing_tools_and_schema(observed):
    """Three filing tools are listed with the registry's own input model."""
    listing, _, _ = observed
    assert [tool.name for tool in listing.tools] == [
        "search_filings",
        "compare_years",
        "fetch_chunk",
    ]
    assert listing.tools[0].input_schema == SearchFilingsParams.model_json_schema()


@pytest.mark.parametrize(("case", "arguments", "failed", "system", "retrievals"), CASES)
def test_search_outcome_matches_the_existing_contract(
    observed, case, arguments, failed, system, retrievals
):
    """Invalid input never reaches retrieval; each failure kind has its own channel."""
    _, results, _ = observed
    result, error, events = results[case]
    assert len(events) == retrievals
    if system:
        assert result is None
        assert_internal_error(error, "search_filings")
        assert PRIVATE_DETAIL not in str(error)
        return
    assert error is None
    assert result.is_error == failed
    text = text_of(result)
    assert PRIVATE_DETAIL not in text
    if not failed:
        assert json.loads(text) == result.structured_content


def test_hits_defaults_and_filters_reach_retrieval(observed):
    """The default k and the declared filters arrive at the retrieval boundary."""
    _, results, _ = observed
    (hit,) = results["hits"][0].structured_content["hits"]
    assert hit["chunk_id"] == SEARCH_CHUNK_ID
    assert results["empty"][0].structured_content == {"hits": []}
    assert results["hits"][2][0]["k"] == 5
    (filtered,) = results["filters"][2]
    assert filtered["k"] == 2
    assert filtered["filters"]["issuers"] == ["TEST"]
    assert filtered["filters"]["fiscal_years"] == [2024]


def test_an_unknown_tool_is_a_protocol_error_and_the_connection_serves_on(observed):
    """Unpublished names, the loop-owned final_answer included, get JSON-RPC -32602."""
    _, _, (unknown, after) = observed
    for name, outcome in unknown.items():
        assert_unknown_tool(outcome, name)
    result, error = after
    assert error is None
    assert not result.is_error
    assert result.structured_content["hits"]
