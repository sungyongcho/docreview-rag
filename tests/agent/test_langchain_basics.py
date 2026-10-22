"""Sections 5.2-5.3: what LangChain chat models and messages keep and lose from our boundary."""

import asyncio
from decimal import Decimal
import json
import math

from langchain_core.exceptions import OutputParserException
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
    convert_to_openai_messages,
)
from langchain_core.output_parsers.openai_tools import make_invalid_tool_call, parse_tool_call
import pytest

from app.agent.provider import DeterministicToolProvider
from app.agent.tools.filings import build_default_registry
from app.agent.types import ToolCall
from app.llm.decoding import strict_json_loads
from scripts.mcp.live import BudgetExhaustedError, Reservation
from tests.agent.support import FakeSessionFactory, ScriptedChatModel, turn

CALL_ID = "call_1"
SEARCH = {"query": "revenue", "issuers": ["TEST"], "fiscal_years": [2024]}
QUESTION = "What was TestCo revenue in FY2024?"


def ai_tool_call(name, args, call_id=CALL_ID):
    """One scripted model reply that requests a single tool call with fixture usage."""
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}],
        usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
    )


def raw_call(arguments):
    """An OpenAI-style raw tool call whose arguments are the model's original string."""
    return {"id": CALL_ID, "function": {"name": "fetch_chunk", "arguments": arguments}}


# The two response boundaries
def test_both_boundaries_carry_the_same_tool_request():
    """Our ProviderTurn keeps the raw argument string; an AIMessage carries a parsed dict."""
    sessions = FakeSessionFactory()
    registry = build_default_registry(sessions)
    call = ToolCall(call_id=CALL_ID, name="search_filings", arguments_json=json.dumps(SEARCH))
    direct = asyncio.run(
        DeterministicToolProvider([turn(tool_calls=(call,))]).turn(
            "instructions",
            [{"role": "user", "content": QUESTION}],
            registry.specs(),
            max_output_tokens=800,
        )
    )
    model = ScriptedChatModel.from_replies(ai_tool_call("search_filings", SEARCH))
    message = asyncio.run(
        model.bind_tools(registry.specs()).ainvoke(
            [SystemMessage("instructions"), HumanMessage(QUESTION)]
        )
    )

    (requested,) = message.tool_calls
    (ours,) = direct.tool_calls
    assert isinstance(ours.arguments_json, str)
    assert (requested["id"], requested["name"]) == (ours.call_id, ours.name)
    assert requested["args"] == json.loads(ours.arguments_json)
    usage = message.usage_metadata
    assert usage is not None
    assert (usage["input_tokens"], usage["output_tokens"]) == (
        direct.input_tokens,
        direct.output_tokens,
    )
    # A tool request is only a message: neither boundary ran the tool.
    assert sessions.sessions == []


def test_bound_tools_reach_the_model_request_unchanged():
    """bind_tools sends our strict Responses specs as they are; nothing runs a tool."""
    sessions = FakeSessionFactory()
    registry = build_default_registry(sessions)
    model = ScriptedChatModel.from_replies(AIMessage(content="no tools needed"))
    asyncio.run(model.bind_tools(registry.specs()).ainvoke([HumanMessage(QUESTION)]))

    (request,) = model.requests
    assert request.kwargs["tools"] == registry.specs()
    assert sessions.sessions == []


def test_text_that_announces_a_tool_is_not_a_tool_request():
    """Only tool_calls request a tool; prose saying so requests nothing."""
    model = ScriptedChatModel.from_replies(AIMessage(content="I will search the filings now."))
    message = asyncio.run(model.ainvoke([HumanMessage(QUESTION)]))
    assert isinstance(message, AIMessage)
    assert message.tool_calls == []


# Message roles and tool request/result association
def test_langchain_messages_convert_to_chat_completions_roles():
    """LangChain message types convert to OpenAI chat-completions roles and tool links."""
    # This is LangChain's own converter, not our wire format: run_agent replays
    # Responses function_call/function_call_output items (app/agent/loop.py).
    messages = [
        SystemMessage("instructions"),
        HumanMessage(QUESTION),
        ai_tool_call("search_filings", SEARCH),
        ToolMessage(content='{"hits":[]}', tool_call_id=CALL_ID),
    ]
    assert [message.type for message in messages] == ["system", "human", "ai", "tool"]
    wire = convert_to_openai_messages(messages)
    assert [item["role"] for item in wire] == ["system", "user", "assistant", "tool"]
    assert wire[3]["tool_call_id"] == wire[2]["tool_calls"][0]["id"] == CALL_ID


def test_the_model_sees_each_tool_result_under_its_call_id():
    """A second request carries the tool result linked to the call that asked for it."""
    model = ScriptedChatModel.from_replies(
        ai_tool_call("fetch_chunk", {"chunk_id": 7}), AIMessage(content="done")
    )
    history = [HumanMessage(QUESTION)]
    request = asyncio.run(model.ainvoke(history))
    assert isinstance(request, AIMessage)
    refused = ToolMessage(
        content="ERROR: chunk 7 was not retrieved in this question; search first",
        tool_call_id=request.tool_calls[0]["id"],
        status="error",
    )
    asyncio.run(model.ainvoke([*history, request, refused]))

    first, second = model.requests
    assert first.messages == history
    tool_messages = [m for m in second.messages if isinstance(m, ToolMessage)]
    assert [(m.tool_call_id, m.status) for m in tool_messages] == [(CALL_ID, "error")]


def test_a_tool_artifact_is_kept_but_not_sent_to_the_model():
    """ToolMessage.artifact stays on the message; convert_to_openai_messages drops it.

    This pins that one converter, not every provider integration.
    """
    artifact = {"hits": [{"chunk_id": 7, "citation": "TEST 10-K 2024"}]}
    message = ToolMessage(content="1 hit", tool_call_id=CALL_ID, artifact=artifact)
    (wire,) = convert_to_openai_messages([message])
    assert message.artifact == artifact
    assert "artifact" not in wire
    assert "TEST 10-K 2024" not in json.dumps(wire)


def test_unparseable_arguments_are_kept_as_an_invalid_tool_call():
    """The parser rejects malformed arguments; the test then builds the invalid entry itself.

    This is not a provider integration preserving the raw string automatically.
    """
    raw = raw_call('{"chunk_id": 7,,}')
    with pytest.raises(OutputParserException):
        parse_tool_call(raw, return_id=True)
    invalid = make_invalid_tool_call(raw, "malformed JSON")
    message = AIMessage(content="", invalid_tool_calls=[invalid])
    assert message.tool_calls == []
    assert [(c["id"], c["args"]) for c in message.invalid_tool_calls] == [
        (CALL_ID, '{"chunk_id": 7,,}')
    ]


# Spending is reserved before a request, never after it
def send_after_reserving(budget, model, estimate):
    """Reserve the estimate, then send; report whether the outcome is known."""
    budget.reserve(estimate, "model")
    try:
        asyncio.run(model.ainvoke([HumanMessage(QUESTION)]))
    except TimeoutError:
        return "unknown"
    return "answered"


def test_a_reservation_blocks_requests_before_they_are_sent():
    """Rejected estimates send nothing; an unknown outcome keeps its reservation."""
    budget = Reservation(cap_usd=Decimal("0.05"), max_attempts=8)
    model = ScriptedChatModel.from_replies(
        ai_tool_call("search_filings", SEARCH),
        failures={2: TimeoutError("simulated lost response; billing unknown")},
    )
    calls = []

    assert send_after_reserving(budget, model, Decimal("0.02")) == "answered"
    calls.append(len(model.requests))
    with pytest.raises(BudgetExhaustedError):
        send_after_reserving(budget, model, Decimal("0.04"))
    calls.append(len(model.requests))
    assert send_after_reserving(budget, model, Decimal("0.02")) == "unknown"
    calls.append(len(model.requests))
    with pytest.raises(BudgetExhaustedError):
        send_after_reserving(budget, model, Decimal("0.02"))
    calls.append(len(model.requests))

    assert calls == [1, 1, 2, 2]
    assert (budget.reserved_usd, budget.attempts) == (Decimal("0.04"), 2)


def test_usage_metadata_arrives_only_with_the_reply():
    """Token usage is known after a request returns, so it cannot gate that request."""
    model = ScriptedChatModel.from_replies(ai_tool_call("search_filings", SEARCH))
    assert model.requests == []
    message = asyncio.run(model.ainvoke([HumanMessage(QUESTION)]))
    assert isinstance(message, AIMessage)
    assert len(model.requests) == 1
    assert message.usage_metadata is not None


# What LangChain's argument parsing loses compared with our strict parser
def test_a_duplicate_argument_key_is_silently_resolved_to_the_last_value():
    """LangChain keeps the last duplicate; our strict parser refuses the arguments."""
    arguments = '{"chunk_id":7,"chunk_id":8}'
    parsed = parse_tool_call(raw_call(arguments), return_id=True)
    assert parsed is not None
    assert parsed["args"] == {"chunk_id": 8}
    with pytest.raises(ValueError, match="duplicate JSON key"):
        strict_json_loads(arguments)


def test_a_non_finite_argument_is_accepted_as_nan():
    """LangChain turns NaN into a float NaN; our strict parser refuses it."""
    arguments = '{"chunk_id":NaN}'
    parsed = parse_tool_call(raw_call(arguments), return_id=True)
    assert parsed is not None
    assert isinstance(parsed["args"]["chunk_id"], float)
    assert math.isnan(parsed["args"]["chunk_id"])
    with pytest.raises(ValueError, match="non-finite"):
        strict_json_loads(arguments)
