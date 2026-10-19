"""Section 4.6: run_agent over MCP keeps question scope and stops on system failures."""

import asyncio
import json
from typing import cast

from mcp import Client
import pytest

from app.agent.loop import run_agent
from app.agent.provider import DeterministicToolProvider, ProviderTurn
from app.agent.tools.filings import build_default_registry
from app.agent.types import ToolCall
from app.db.session_factory import SessionFactory
from app.mcp.client import mcp_tool_registry
from tests.mcp.support import PROTOCOL_MODE, controlled_filings, logged_events

SEARCH_2023 = {"query": "revenue", "issuers": ["TEST"], "fiscal_years": [2023]}
SEARCH_2024 = {**SEARCH_2023, "fiscal_years": [2024]}
COMPARE = {"query": "revenue", "issuer": "TEST", "fiscal_years": [2023, 2024]}
FINISH = {
    "label": "NOT_IN_DOCS",
    "answer": "NOT_IN_DOCS",
    "citations": [],
    "rationale": "This test checks dispatch, not financial answer quality.",
}


def step(name, arguments):
    """Build one deterministic model decision; all tool execution stays real."""
    call = ToolCall(call_id="call", name=name, arguments_json=json.dumps(arguments))
    return ProviderTurn(output_text="", input_tokens=0, output_tokens=0, tool_calls=(call,))


def fetch(chunk_id):
    """Ask to read one chunk body."""
    return step("fetch_chunk", {"chunk_id": chunk_id})


# (case, model steps before final_answer, status, body reads, rejected step indexes)
QUESTIONS = [
    (
        "first question accumulates both years",
        [
            fetch(2023),
            step("search_filings", SEARCH_2023),
            step("search_filings", SEARCH_2024),
            fetch(2023),
            fetch(2024),
        ],
        "ok",
        [2023, 2024],
        [0],
    ),
    (
        "next question on the same connection starts empty",
        [fetch(2023), fetch(2024), step("search_filings", SEARCH_2024), fetch(2024), fetch(2023)],
        "ok",
        [2024],
        [0, 1, 4],
    ),
    (
        "empty search cannot grant access",
        [step("search_filings", {**SEARCH_2023, "query": "no-match"}), fetch(2023)],
        "ok",
        [],
        [1],
    ),
    (
        "failed comparison ends the run as a tool error",
        [step("compare_years", {**COMPARE, "query": "fail-2024"}), fetch(2023), fetch(2024)],
        "tool_error",
        [],
        [0],
    ),
    (
        "successful comparison grants both returned ids",
        [step("compare_years", COMPARE), fetch(2023), fetch(2024)],
        "ok",
        [2023, 2024],
        [],
    ),
    (
        "schema validation precedes the fetch guard",
        [step("fetch_chunk", {"chunk_id": []}), fetch(0)],
        "ok",
        [],
        [0, 1],
    ),
]


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    """Run every question in order through one MCP connection and one bridge."""
    log_path = tmp_path_factory.mktemp("client") / "events.jsonl"
    contracts = build_default_registry(cast(SessionFactory, object))

    async def exercise():
        async with Client(controlled_filings(log_path), mode=PROTOCOL_MODE) as client:
            bridge = await mcp_tool_registry(client, contracts)
            observed = {}
            for case, steps, *_ in QUESTIONS:
                start = len(logged_events(log_path))
                result = await run_agent(
                    case,
                    registry=bridge,
                    provider=DeterministicToolProvider([*steps, step("final_answer", FINISH)]),
                )
                observed[case] = (result, logged_events(log_path, start))
        return bridge, observed

    return asyncio.run(exercise())


def test_bridge_keeps_the_app_contracts_and_the_server_description(runs):
    """Discovered tools reuse the app's models; descriptions come from the server."""
    bridge, _ = runs
    assert bridge.names == ("compare_years", "fetch_chunk", "search_filings")
    assert "does not extract revenue values" in bridge.get("compare_years").description


@pytest.mark.parametrize(("case", "steps", "status", "reads", "rejected"), QUESTIONS)
def test_question_scope_over_mcp(runs, case, steps, status, reads, rejected):
    """Only retrieved chunks are read, per question, and system failures stop the run."""
    _, observed = runs
    result, events = observed[case]
    assert result.status == status
    errors = [
        index
        for index, item in enumerate(result.steps)
        if item.observations and item.observations[0].error is not None
    ]
    assert errors == rejected
    assert [event["chunk_id"] for event in events if event["event"] == "body_load"] == reads
    if status == "tool_error":
        assert len(result.steps) == 1
        assert result.failure == "MCPSystemError: tool compare_years failed"
