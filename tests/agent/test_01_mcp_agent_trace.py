"""Section 6.1: a model's tool calls travel through MCPAdapter and create_agent to stdio and back.

The scripted model, not a real one, decides every call; the server is the production
filings server with only retrieval and the database replaced. This pins the wiring and
the result feedback, not reasoning, retrieval quality or any guard. Chunk ids equal
fiscal years only because the controlled fixture says so.
"""

import asyncio
from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, cast

from fastmcp.client.transports import StdioTransport
from langchain.agents import create_agent
from langchain.mcp import MCPAdapter
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool
import pytest

from app.agent.tools.filings import build_default_registry
from app.db.session_factory import SessionFactory
from app.mcp.filings_server import EXPOSED_TOOLS
from tests.agent.support import ModelRequest, ScriptedChatModel
from tests.mcp.controlled_filings import fixture_hit
from tests.mcp.support import logged_events, module_server

QUESTION = "What was TestCo revenue in FY2023 and FY2024?"
COMPARE = {"query": "revenue", "issuer": "TEST", "fiscal_years": [2023, 2024]}
FETCHES = {"call_fetch_1": {"chunk_id": 2024}, "call_fetch_2": {"chunk_id": 2023}}
USAGE = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}


@dataclass(frozen=True)
class Trace:
    """Everything one agent run left behind: model inputs, wire lines and data-layer events."""

    tools: list[BaseTool]
    requests: list[ModelRequest]
    messages: list[BaseMessage]
    wire_requests: list[dict[str, Any]]
    wire_responses: list[dict[str, Any]]
    events: list[dict[str, Any]]


def calls(*requested: tuple[str, str, dict[str, Any]]) -> AIMessage:
    """One scripted model reply requesting the given ``(id, name, args)`` tool calls."""
    return AIMessage(
        content="",
        tool_calls=[
            {"name": name, "args": args, "id": call_id, "type": "tool_call"}
            for call_id, name, args in requested
        ],
        usage_metadata=USAGE,
    )


def read_lines(path: Path) -> list[dict[str, Any]]:
    """Parse one JSONL direction recorded by the relay."""
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def tool_messages(messages: list[BaseMessage]) -> dict[str, ToolMessage]:
    """Index a model input's tool results by the call id each one answers."""
    return {m.tool_call_id: m for m in messages if isinstance(m, ToolMessage)}


def model_visible_json(message: ToolMessage) -> Any:
    """Parse the JSON the model reads from a tool result's ``content``, not its artifact.

    The installed adapter turns each MCP ``TextContent`` into one LangChain text block
    (``langchain/mcp/tools.py`` ``_convert_content_block``); the filings server sends its
    result as a single JSON text block, so exactly one text block is required here.
    """
    assert isinstance(message.content, list)
    texts = [block for block in message.content if isinstance(block, dict)]
    assert len(texts) == len(message.content) == 1
    (block,) = texts
    assert block["type"] == "text"
    return json.loads(block["text"])


@pytest.fixture(scope="module")
def trace(tmp_path_factory) -> Trace:
    """Run one question through create_agent over a recorded stdio relay to the server."""
    work = tmp_path_factory.mktemp("mcp_agent_trace")
    log_path = work / "events.jsonl"
    log_path.touch()
    relay = module_server(
        "tests.mcp.stdio_relay", str(work), "tests.mcp.controlled_filings", str(log_path)
    )
    transport = StdioTransport(
        relay.command, relay.args, env=relay.env, cwd=str(relay.cwd), keep_alive=False
    )
    model = ScriptedChatModel.from_replies(
        calls(("call_compare", "compare_years", COMPARE)),
        calls(*((call_id, "fetch_chunk", args) for call_id, args in FETCHES.items())),
        AIMessage(content="trace complete", usage_metadata=USAGE),
    )

    async def run() -> tuple[list[BaseTool], dict[str, Any]]:
        """Discover the server's tools, then answer the question with a middleware-free agent."""
        async with MCPAdapter(transport) as adapter:
            tools = await adapter.list_tools()
            agent = create_agent(model, tools)
            state = await agent.ainvoke({"messages": [HumanMessage(QUESTION)]})
        return tools, state

    tools, state = asyncio.run(run())
    return Trace(
        tools=tools,
        requests=model.requests,
        messages=state["messages"],
        wire_requests=read_lines(work / "requests.jsonl"),
        wire_responses=read_lines(work / "responses.jsonl"),
        events=logged_events(log_path),
    )


def test_discovered_tools_reach_the_model_with_the_published_schemas(trace):
    """The adapter keeps each published schema; every model request is bound to those tools."""
    # LangChain's conversion for the model is not key-for-key identical to the published
    # schema (in this run it dropped at least some title and description keys), so the
    # bound parameters are pinned to that conversion and to the published field contract.
    contracts = build_default_registry(cast(SessionFactory, object))
    published = {name: contracts.get(name).parameters.model_json_schema() for name in EXPOSED_TOOLS}
    assert {tool.name: tool.args_schema for tool in trace.tools} == published
    expected = [convert_to_openai_tool(tool) for tool in trace.tools]
    for request in trace.requests:
        assert request.kwargs["tools"] == expected
        for spec in request.kwargs["tools"]:
            parameters, schema = spec["function"]["parameters"], published[spec["function"]["name"]]
            assert parameters["properties"].keys() == schema["properties"].keys()
            assert parameters["required"] == schema["required"]
            assert parameters["additionalProperties"] is False


def test_the_wire_carries_one_compare_and_two_fetches_paired_by_rpc_id(trace):
    """Exactly the requested tools/call messages cross stdio, each answered under its own id."""
    tool_calls = [line for line in trace.wire_requests if line.get("method") == "tools/call"]
    sent = [(call["params"]["name"], call["params"]["arguments"]) for call in tool_calls]
    assert sent[0] == ("compare_years", COMPARE)
    # The two fetches of one model turn run concurrently: their order is not fixed.
    assert Counter(json.dumps(item, sort_keys=True) for item in sent[1:]) == Counter(
        json.dumps(("fetch_chunk", args), sort_keys=True) for args in FETCHES.values()
    )
    assert len({call["id"] for call in tool_calls}) == len(tool_calls)
    for call in tool_calls:
        (response,) = [line for line in trace.wire_responses if line.get("id") == call["id"]]
        result = response["result"]
        assert result.get("isError") is not True
        if call["params"]["name"] == "fetch_chunk":
            chunk_id = call["params"]["arguments"]["chunk_id"]
            assert result["structuredContent"]["chunk_id"] == chunk_id


def test_the_server_reads_each_fetched_chunk_once(trace):
    """The controlled data layer saw one retrieval per year and one body read per fetch."""
    retrievals = sorted(
        tuple(e["filters"]["fiscal_years"]) for e in trace.events if e["event"] == "retrieval"
    )
    assert retrievals == [(2023,), (2024,)]
    body_loads = sorted(e["chunk_id"] for e in trace.events if e["event"] == "body_load")
    assert body_loads == [2023, 2024]


def test_each_model_input_carries_the_results_under_their_call_ids(trace):
    """The second input holds the compare result, the third adds both fetched bodies."""
    first, second, third = trace.requests
    assert first.messages == [HumanMessage(QUESTION, id=first.messages[0].id)]

    (compare,) = tool_messages(second.messages).values()
    assert (compare.tool_call_id, compare.name, compare.status) == (
        "call_compare",
        "compare_years",
        "success",
    )
    expected_years = [(2023, [2023]), (2024, [2024])]
    # The model reads ``content``; ``artifact`` is application-side data it never sees.
    for result in (model_visible_json(compare), compare.artifact["structured_content"]):
        years = [(y["fiscal_year"], [h["chunk_id"] for h in y["hits"]]) for y in result["years"]]
        assert (result["issuer"], years) == ("TEST", expected_years)

    results = tool_messages(third.messages)
    assert set(results) == {"call_compare", *FETCHES}
    for call_id, args in FETCHES.items():
        fetched = results[call_id]
        assert (fetched.name, fetched.status) == ("fetch_chunk", "success")
        expected_body = fixture_hit(args["chunk_id"]).body
        for body in (model_visible_json(fetched), fetched.artifact["structured_content"]):
            assert (body["chunk_id"], body["body"]) == (args["chunk_id"], expected_body)


def test_the_run_ends_after_three_model_requests_with_no_further_tool_call(trace):
    """A reply without tool calls ends the loop; nothing more is sent to the model or server."""
    assert len(trace.requests) == 3
    final = trace.messages[-1]
    assert isinstance(final, AIMessage)
    assert final.content == "trace complete"
    assert final.tool_calls == []
    assert sum(1 for line in trace.wire_requests if line.get("method") == "tools/call") == 3
