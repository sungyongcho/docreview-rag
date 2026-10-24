"""Sections 6.2 A and C: question-scoped tool rules and system-failure stops on the MCP agent path.

Acceptance runs use the real stdio filings server (controlled data layer), MCPAdapter
and create_agent with ``[StopOnSystemFailure(), ReviewGate(...)]``; only the model is
scripted. Chunk ids equal fiscal years only in the fixture.
"""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, cast

from fastmcp.client.transports import StdioTransport
from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain.mcp import MCPAdapter
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.prebuilt.tool_node import ToolCallRequest, ToolRuntime
from langgraph.types import Command
from mcp.shared.exceptions import MCPError
from mcp.types import INTERNAL_ERROR, INVALID_PARAMS
import pytest

from app.agent.review_middleware import (
    ReviewGate,
    StopOnSystemFailure,
    keep_first_failure,
    merge_evidence,
)
from app.agent.tools.filings import build_default_registry
from app.contracts.evidence import EvidenceCitation
from app.db.session_factory import SessionFactory
from tests.agent.support import ScriptedChatModel
from tests.mcp.controlled_filings import fixture_hit
from tests.mcp.support import logged_events, module_server

USAGE = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
COMPARE = {"query": "revenue", "issuer": "TEST", "fiscal_years": [2023, 2024]}
FAILING = {**COMPARE, "query": "fail-2024"}
FAILURE = "RuntimeError: tool compare_years failed"
NOT_RETRIEVED = "was not retrieved in this question; search first"


def contracts():
    """The app's tool contracts; their run functions must never be needed."""
    return build_default_registry(cast(SessionFactory, object))


def identity(chunk_id: int) -> dict[str, Any]:
    """The complete source identity the controlled server returns for one chunk."""
    hit = fixture_hit(chunk_id)
    return EvidenceCitation(
        chunk_id=hit.chunk_id,
        doc_id=hit.doc_id,
        citation=hit.citation,
        start_char=hit.start_char,
        end_char=hit.end_char,
        source_sha256=hit.source_sha256,
    ).model_dump(mode="json")


def reply(*requested: tuple[str, str, dict[str, Any]], text: str = "") -> AIMessage:
    """One scripted model reply requesting ``(id, name, args)`` tool calls, or none."""
    return AIMessage(
        content=text,
        tool_calls=[
            {"name": name, "args": args, "id": call_id, "type": "tool_call"}
            for call_id, name, args in requested
        ],
        usage_metadata=USAGE,
    )


@dataclass(frozen=True)
class Run:
    """What the questions left behind: final states, model inputs, wire calls and data reads."""

    states: list[dict[str, Any]]
    model: ScriptedChatModel
    checkpoints: list[dict[str, Any]]
    tool_calls: list[dict[str, Any]]
    events: list[dict[str, Any]]

    def result(self, call_id: str) -> ToolMessage:
        """The tool result answering one call id in the last state."""
        (message,) = [
            m
            for m in self.states[-1]["messages"]
            if isinstance(m, ToolMessage) and m.tool_call_id == call_id
        ]
        return message

    def sent(self, name: str) -> list[dict[str, Any]]:
        """Arguments of every tools/call for ``name`` that crossed stdio, in any order."""
        return [c["params"]["arguments"] for c in self.tool_calls if c["params"]["name"] == name]

    def body_loads(self) -> list[int]:
        """Chunk ids whose body the controlled data layer read, sorted."""
        return sorted(e["chunk_id"] for e in self.events if e["event"] == "body_load")


def run_questions(work: Path, replies: Sequence[AIMessage], questions: Sequence[str]) -> Run:
    """Ask each question in turn on one checkpointed thread through one middleware stack."""
    log_path = work / "events.jsonl"
    log_path.touch()
    relay = module_server(
        "tests.mcp.stdio_relay", str(work), "tests.mcp.controlled_filings", str(log_path)
    )
    transport = StdioTransport(
        relay.command, relay.args, env=relay.env, cwd=str(relay.cwd), keep_alive=False
    )
    model = ScriptedChatModel.from_replies(*replies)
    config: Any = {"configurable": {"thread_id": "one thread"}}

    async def ask() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Run every question on the same thread, keeping each final and checkpointed state."""
        states, checkpoints = [], []
        # The stop wraps the gate; the two declare different state schemas the agent merges.
        middleware: list[AgentMiddleware[Any, Any]] = [
            StopOnSystemFailure(),
            ReviewGate(contracts()),
        ]
        async with MCPAdapter(transport) as adapter:
            agent = create_agent(
                model,
                await adapter.list_tools(),
                middleware=middleware,
                checkpointer=InMemorySaver(),
            )
            for question in questions:
                states.append(await agent.ainvoke({"messages": [HumanMessage(question)]}, config))
                checkpoints.append(dict((await agent.aget_state(config)).values))
        return states, checkpoints

    states, checkpoints = asyncio.run(ask())
    requests = [json.loads(line) for line in (work / "requests.jsonl").read_text().splitlines()]
    return Run(
        states=states,
        model=model,
        checkpoints=checkpoints,
        tool_calls=[r for r in requests if r.get("method") == "tools/call"],
        events=logged_events(log_path),
    )


def model_visible_json(message: ToolMessage) -> Any:
    """Parse the single JSON text block the adapter puts in a successful result's content."""
    assert isinstance(message.content, list) and len(message.content) == 1
    (block,) = message.content
    assert isinstance(block, dict) and block["type"] == "text"
    return json.loads(block["text"])


# Acceptance over the real stdio path
@pytest.fixture(scope="module")
def guarded(tmp_path_factory) -> Run:
    """Search, then a string id, an unretrieved id and a retrieved id, each in its own turn."""
    return run_questions(
        tmp_path_factory.mktemp("review_gate_guarded"),
        [
            reply(("call_compare", "compare_years", COMPARE)),
            reply(("call_string", "fetch_chunk", {"chunk_id": "2024"})),
            reply(("call_seven", "fetch_chunk", {"chunk_id": 7})),
            reply(("call_fetch", "fetch_chunk", {"chunk_id": 2024})),
            reply(text="done"),
        ],
        ["What was TestCo revenue in FY2023 and FY2024?"],
    )


def test_a_search_registers_identities_and_authorizes_the_next_fetch(guarded):
    """compare_years records exact identities; fetching 2024 then reaches the server."""
    assert guarded.states[-1]["evidence"] == {2023: identity(2023), 2024: identity(2024)}
    fetched = guarded.result("call_fetch")
    assert (fetched.name, fetched.status) == ("fetch_chunk", "success")
    body = model_visible_json(fetched)
    assert (body["chunk_id"], body["body"]) == (2024, fixture_hit(2024).body)
    assert guarded.sent("compare_years") == [COMPARE]
    assert guarded.sent("fetch_chunk") == [{"chunk_id": 2024}]
    assert guarded.body_loads() == [2024]


def test_a_string_chunk_id_is_refused_before_any_tools_call(guarded):
    """Strict validation rejects "2024" although integer 2024 is in the ledger."""
    refused = guarded.result("call_string")
    assert (refused.name, refused.status) == ("fetch_chunk", "error")
    assert str(refused.content).startswith("ERROR: invalid arguments for fetch_chunk:")
    assert {"chunk_id": "2024"} not in guarded.sent("fetch_chunk")


def test_an_unretrieved_chunk_is_refused_before_any_tools_call(guarded):
    """Chunk 7 exists in the fixture, but this question never retrieved it."""
    refused = guarded.result("call_seven")
    assert (refused.name, refused.status) == ("fetch_chunk", "error")
    assert refused.content == f"ERROR: chunk 7 {NOT_RETRIEVED}"
    assert {"chunk_id": 7} not in guarded.sent("fetch_chunk")
    assert 7 not in guarded.body_loads()


def test_the_model_reads_each_refusal_and_continues(guarded):
    """Refusals are tool results: every later model input carries them and the run ends."""
    assert len(guarded.model.requests) == 5
    last_input = guarded.model.requests[-1].messages
    answered = {m.tool_call_id: m.status for m in last_input if isinstance(m, ToolMessage)}
    assert answered == {
        "call_compare": "success",
        "call_string": "error",
        "call_seven": "error",
        "call_fetch": "success",
    }
    assert guarded.states[-1]["messages"][-1].content == "done"


def test_a_new_question_on_the_same_thread_starts_with_an_empty_ledger(tmp_path):
    """Question 1 retrieved 2024 into the checkpoint; question 2 still cannot fetch it."""
    run = run_questions(
        tmp_path,
        [
            reply(("q1_compare", "compare_years", COMPARE)),
            reply(text="q1 done"),
            reply(("q2_fetch", "fetch_chunk", {"chunk_id": 2024})),
            reply(text="q2 done"),
        ],
        ["Question 1", "Question 2"],
    )
    first, second = run.checkpoints
    assert first["evidence"] == {2023: identity(2023), 2024: identity(2024)}
    # The thread kept question 1's messages, so the reset is what refused the fetch.
    assert [m.content for m in second["messages"] if isinstance(m, HumanMessage)] == [
        "Question 1",
        "Question 2",
    ]
    refused = run.result("q2_fetch")
    assert (refused.status, refused.content) == ("error", f"ERROR: chunk 2024 {NOT_RETRIEVED}")
    assert second["evidence"] == {}
    assert run.sent("fetch_chunk") == []
    assert run.body_loads() == []


def test_parallel_fetches_in_one_reply_both_run_and_keep_the_ledger(tmp_path):
    """After a search, two fetches in one model reply both reach the server and keep both ids."""
    run = run_questions(
        tmp_path,
        [
            reply(("call_compare", "compare_years", COMPARE)),
            reply(
                ("call_fetch_1", "fetch_chunk", {"chunk_id": 2024}),
                ("call_fetch_2", "fetch_chunk", {"chunk_id": 2023}),
            ),
            reply(text="done"),
        ],
        ["What was TestCo revenue in FY2023 and FY2024?"],
    )
    for call_id, chunk_id in (("call_fetch_1", 2024), ("call_fetch_2", 2023)):
        fetched = run.result(call_id)
        assert fetched.status == "success"
        assert model_visible_json(fetched)["chunk_id"] == chunk_id
    last_input = run.model.requests[-1].messages
    answered = {m.tool_call_id: m.status for m in last_input if isinstance(m, ToolMessage)}
    assert answered == {
        "call_compare": "success",
        "call_fetch_1": "success",
        "call_fetch_2": "success",
    }
    assert run.states[-1]["evidence"] == {2023: identity(2023), 2024: identity(2024)}
    assert sorted(a["chunk_id"] for a in run.sent("fetch_chunk")) == [2023, 2024]
    assert run.body_loads() == [2023, 2024]


def test_a_system_failure_ends_the_run_before_another_model_call(tmp_path):
    """A failed compare is recorded and answered with an error; later replies stay unused."""
    run = run_questions(
        tmp_path,
        [
            reply(("call_failed", "compare_years", FAILING)),
            reply(("call_fetch", "fetch_chunk", {"chunk_id": 2024})),
            reply(text="answer that must not be produced"),
        ],
        ["What was TestCo revenue in FY2023 and FY2024?"],
    )
    final = run.states[-1]
    assert final["failure"] == FAILURE
    failed = run.result("call_failed")
    assert (failed.name, failed.status, failed.content) == (
        "compare_years",
        "error",
        f"ERROR: {FAILURE}",
    )
    # The run ends on the failure itself, not on a model answer.
    assert final["messages"][-1] is failed or final["messages"][-1] == failed
    assert final.get("structured_response") is None
    assert len(run.model.requests) == 1
    assert run.sent("compare_years") == [FAILING]
    assert run.sent("fetch_chunk") == []
    assert run.body_loads() == []
    # No identity was registered; a first question's cleared ledger may read as None.
    assert not final.get("evidence")


def test_two_failures_in_one_reply_answer_both_calls_and_end_once(tmp_path):
    """Parallel system failures in one step each get an error result; one failure is kept."""
    run = run_questions(
        tmp_path,
        [
            reply(
                ("call_failed_1", "compare_years", FAILING),
                ("call_failed_2", "compare_years", FAILING),
            ),
            reply(text="answer that must not be produced"),
        ],
        ["What was TestCo revenue in FY2023 and FY2024?"],
    )
    final = run.states[-1]
    assert final["failure"] == FAILURE
    for call_id in ("call_failed_1", "call_failed_2"):
        failed = run.result(call_id)
        assert (failed.status, failed.content) == ("error", f"ERROR: {FAILURE}")
    assert len(run.model.requests) == 1
    assert run.sent("compare_years") == [FAILING, FAILING]


def test_a_new_question_clears_the_failure_and_runs_normally(tmp_path):
    """Question 1 fails on a checkpointed thread; question 2 starts clean and completes."""
    run = run_questions(
        tmp_path,
        [
            reply(("q1_failed", "compare_years", FAILING)),
            reply(("q2_compare", "compare_years", COMPARE)),
            reply(("q2_fetch", "fetch_chunk", {"chunk_id": 2024})),
            reply(text="q2 done"),
        ],
        ["Question 1", "Question 2"],
    )
    first, second = run.checkpoints
    assert first["failure"] == FAILURE
    assert not first.get("evidence")
    assert second["failure"] is None
    assert run.result("q2_fetch").status == "success"
    assert second["evidence"] == {2023: identity(2023), 2024: identity(2024)}
    assert second["messages"][-1].content == "q2 done"
    # Question 1 used one model call; question 2 used its three.
    assert len(run.model.requests) == 4
    assert run.sent("fetch_chunk") == [{"chunk_id": 2024}]
    assert run.body_loads() == [2024]


# Focused checks of the ledger rules
def test_none_clears_the_ledger_and_an_empty_update_keeps_it():
    """Only None starts a new ledger; updates merge without dropping earlier identities."""
    ledger = {2023: identity(2023)}
    assert merge_evidence(ledger, None) == {}
    assert merge_evidence(ledger, {}) == ledger
    assert merge_evidence(ledger, {2024: identity(2024)}) == {
        2023: identity(2023),
        2024: identity(2024),
    }
    assert merge_evidence(None, {2024: identity(2024)}) == {2024: identity(2024)}


def gate_call(
    name: str, args: dict[str, Any], evidence: dict[int, Any], result: Any, *, bound: Any = None
):
    """Run the gate on one call against a stub handler; return its answer and handler calls."""
    seen: list[ToolCallRequest] = []

    async def handler(request: ToolCallRequest) -> Any:
        """Stand in for the bound tool, recording that it was reached."""
        seen.append(request)
        return result

    request = ToolCallRequest(
        tool_call={"name": name, "args": args, "id": "call_1", "type": "tool_call"},
        tool=bound,
        state={"messages": [], "evidence": evidence},
        runtime=cast(ToolRuntime, None),
    )
    answer = asyncio.run(ReviewGate(contracts()).awrap_tool_call(request, handler))
    return answer, seen


def fetched_result(**changes: Any) -> ToolMessage:
    """A successful fetch_chunk result for chunk 2024 with optional identity changes."""
    payload = {**identity(2024), "context_header": "", "body": "x", **changes}
    return ToolMessage(
        content=json.dumps(payload),
        tool_call_id="call_1",
        name="fetch_chunk",
        artifact={"structured_content": payload},
    )


def test_a_conflicting_identity_is_refused_instead_of_overwritten():
    """A result naming a known chunk with a different identity becomes an error, no update."""
    tampered = fetched_result(source_sha256="0" * 64)
    answer, seen = gate_call("fetch_chunk", {"chunk_id": 2024}, {2024: identity(2024)}, tampered)
    assert len(seen) == 1
    assert isinstance(answer, ToolMessage)
    assert (answer.status, answer.tool_call_id) == ("error", "call_1")
    assert answer.content == "ERROR: tool returned conflicting immutable identity for chunk 2024"


def test_a_matching_identity_keeps_the_result_and_its_call_id():
    """A consistent fetch returns its own message inside the ledger update."""
    result = fetched_result()
    answer, _ = gate_call("fetch_chunk", {"chunk_id": 2024}, {2024: identity(2024)}, result)
    assert isinstance(answer, Command)
    assert answer.update == {"messages": [result], "evidence": {2024: identity(2024)}}


def test_an_error_result_is_returned_without_touching_the_ledger():
    """A failed tool result passes through unchanged, so it can add no evidence."""
    failed = ToolMessage(
        content="boom", tool_call_id="call_1", name="compare_years", status="error"
    )
    answer, seen = gate_call("compare_years", COMPARE, {}, failed)
    assert (answer, len(seen)) == (failed, 1)


def test_an_unbound_unknown_tool_is_left_to_the_tools_node():
    """With no bound tool and no contract, the framework's own unknown-tool answer is used."""
    unknown = ToolMessage(content="not a valid tool", tool_call_id="call_1", status="error")
    answer, seen = gate_call("delete_filings", {}, {}, unknown)
    assert (answer, len(seen)) == (unknown, 1)


def test_a_bound_tool_without_an_app_contract_fails_loudly():
    """A tool the app cannot validate is a configuration error, never run unchecked."""
    with pytest.raises(ValueError, match="has no app contract"):
        gate_call("delete_filings", {}, {}, None, bound=object())


# Focused checks of the stop rules
def stop_call(raised: BaseException | None = None, result: Any = None):
    """Run StopOnSystemFailure on one compare call whose inner handler raises or returns."""

    async def handler(request: ToolCallRequest) -> Any:
        """Stand in for the gate and the bound tool."""
        del request
        if raised is not None:
            raise raised
        return result

    request = ToolCallRequest(
        tool_call={"name": "compare_years", "args": COMPARE, "id": "call_1", "type": "tool_call"},
        tool=None,
        state={"messages": []},
        runtime=cast(ToolRuntime, None),
    )
    return asyncio.run(StopOnSystemFailure().awrap_tool_call(request, handler))


def test_a_normal_result_passes_through_unchanged():
    """Only a raised system failure changes what the inner layers returned."""
    result = ToolMessage(content="ok", tool_call_id="call_1", name="compare_years")
    assert stop_call(result=result) is result


def test_an_internal_error_becomes_an_error_result_and_a_failure():
    """INTERNAL_ERROR answers the call with its redacted message and records the failure."""
    answer = stop_call(MCPError(code=INTERNAL_ERROR, message=FAILURE))
    assert isinstance(answer, Command)
    update = answer.update
    assert isinstance(update, dict)
    (message,) = update["messages"]
    assert (message.tool_call_id, message.name, message.status) == (
        "call_1",
        "compare_years",
        "error",
    )
    assert message.content == f"ERROR: {FAILURE}"
    assert update["failure"] == FAILURE


def test_other_json_rpc_errors_and_value_errors_propagate_unchanged():
    """The stop is only for the filings system-failure contract, never a catch-all."""
    invalid = MCPError(code=INVALID_PARAMS, message="bad params")
    with pytest.raises(MCPError) as caught:
        stop_call(invalid)
    assert caught.value is invalid
    with pytest.raises(ValueError, match="has no app contract"):
        stop_call(ValueError("tool x is bound to the agent but has no app contract"))


def test_before_model_ends_only_after_a_failure_and_before_agent_clears_it():
    """The end jump needs a recorded failure; each new invocation starts without one."""
    stop = StopOnSystemFailure()
    runtime = cast(Any, None)
    assert stop.before_model(cast(Any, {"messages": [], "failure": FAILURE}), runtime) == {
        "jump_to": "end"
    }
    assert stop.before_model(cast(Any, {"messages": [], "failure": None}), runtime) is None
    assert stop.before_model(cast(Any, {"messages": []}), runtime) is None
    assert stop.before_agent(cast(Any, {"messages": [], "failure": FAILURE}), runtime) == {
        "failure": None
    }


def test_none_clears_the_failure_and_the_first_recorded_failure_stays():
    """A new question clears the failure; a later failure in the same question never replaces it."""
    assert keep_first_failure("first", None) is None
    assert keep_first_failure(None, "first") == "first"
    assert keep_first_failure("first", "second") == "first"
