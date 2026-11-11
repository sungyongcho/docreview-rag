"""Section 6.3: create_agent's final-answer gate reports what run_agent reports.

Each case runs twice with the same search, scripted replies, citations and evidence
reader: once through ``run_agent`` over the official MCP client bridge, once through
``create_agent`` with ``MCPAdapter``, ``StopOnSystemFailure``, ``ReviewGate`` and
``final_answer_format()``. Both reach the real stdio filings server through a recording
relay; only retrieval, the database, the evidence reader and the model are synthetic.
``USD_INCOME_TABLE`` adds an explicit currency to AMD's layout for these checks; it is
not evidence that a filing states one. Chunk 2024 holds that table only in the reader.
"""

import asyncio
from dataclasses import dataclass
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from fastmcp.client.transports import StdioTransport
from langchain.agents import create_agent
from langchain.agents.middleware import (
    AgentMiddleware,
    ExtendedModelResponse,
    ModelResponse,
)
from langchain.mcp import MCPAdapter
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.tools import BaseTool
from langgraph.checkpoint.memory import InMemorySaver
from mcp import Client
import pytest

from app.agent.loop import UNIT_UNVERIFIED_ANSWER, run_agent
from app.agent.review_middleware import (
    FINAL_NOT_ALONE,
    CitedEvidenceReadError,
    ReviewContext,
    ReviewGate,
    StopOnSystemFailure,
    final_answer_format,
)
from app.agent.tools.filings import build_default_registry
from app.agent.tools.registry import ToolRegistry
from app.agent.types import AgentReportAnswer, AgentResult, ToolCall
from app.contracts.evidence import EvidenceCitation
from app.db.session_factory import SessionFactory
from app.figures.answers import EvidenceText
from app.figures.tables import read_table_cells
from app.mcp.client import mcp_tool_registry
from tests.agent.support import RecordingToolProvider, ScriptedChatModel, turn
from tests.mcp.controlled_filings import PRIVATE_DETAIL, fixture_hit
from tests.mcp.support import PROTOCOL_MODE, logged_events, module_server
from tests.workflow.support import INCOME_TABLE, USD_INCOME_TABLE, income_table_hit

QUESTION = "What was TestCo's FY2024 revenue?"
YEARS = (2024,)
SEARCH = {"query": "revenue", "issuers": ["TEST"], "fiscal_years": [2024]}
FAILING = {"query": "fail-2024", "issuer": "TEST", "fiscal_years": [2023, 2024]}
REVENUE = "2024 net revenue was $25,785 million."
USAGE = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
READ_FAILURE = "RuntimeError: cited evidence read failed"

type Call = tuple[str, str, dict[str, Any]]


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


CITED = identity(2024)
ABSENT = {"label": "NOT_IN_DOCS", "answer": "NOT_IN_DOCS", "citations": [], "rationale": "none"}


def supported(text: str, citation: dict[str, Any] = CITED) -> dict[str, Any]:
    """A SUPPORTED final answer citing one identity."""
    return {"label": "SUPPORTED", "answer": text, "citations": [citation], "rationale": "cited"}


def contracts() -> ToolRegistry:
    """The app's tool contracts; their run functions must never be needed."""
    return build_default_registry(cast(SessionFactory, object))


class Reader:
    """Evidence reader fixture for chunk 2024 that records each read.

    ``usd`` is the table with an explicit currency, ``as_filed`` AMD's "$"-only table,
    ``prose`` the fixture body and ``broken`` a database failure with private detail.
    """

    def __init__(self, kind: str) -> None:
        self.kind = kind
        self.reads: list[tuple[int, ...]] = []

    async def __call__(self, chunk_ids: tuple[int, ...]) -> dict[int, EvidenceText]:
        """Record the read, then return chunk 2024's evidence or fail."""
        self.reads.append(chunk_ids)
        if self.kind == "broken":
            raise RuntimeError(PRIVATE_DETAIL)
        if self.kind == "prose":
            hit = fixture_hit(2024)
            return {2024: EvidenceText(2024, hit.body, hit.context_header)}
        html = USD_INCOME_TABLE if self.kind == "usd" else INCOME_TABLE
        table, fragment = income_table_hit(2024, html=html)
        return {
            2024: EvidenceText(
                2024, table.body, table.context_header, tuple(read_table_cells(fragment))
            )
        }


def one(call_id: str, name: str, args: dict[str, Any]) -> tuple[Call, ...]:
    """A model turn with one call."""
    return ((call_id, name, args),)


@dataclass(frozen=True)
class Case:
    """Model turns after the opening search, the reader and what both paths must report."""

    name: str
    replies: tuple[tuple[Call, ...], ...]
    reader: str | None
    status: str
    label: str | None
    requests: int
    rejected: tuple[str, ...] = ()

    def turns(self) -> list[tuple[Call, ...]]:
        """Every scripted turn: the search for FY2024 first, then the case's replies."""
        return [one("call_search", "search_filings", SEARCH), *self.replies]


def revised(*first: Call) -> tuple[tuple[Call, ...], ...]:
    """A turn the gate or a tool must reject, then a corrected NOT_IN_DOCS answer."""
    return (first, one("call_2", "final_answer", ABSENT))


CASES = [
    # The 11 prepared cases: 9 basic and 2 extras.
    Case("currency unknown", (one("call_1", "final_answer", supported(REVENUE)),),
         "as_filed", "ok", "UNVERIFIED", 2),
    Case("verified figure", (one("call_1", "final_answer", supported(REVENUE)),),
         "usd", "ok", "SUPPORTED", 2),
    Case("wrong unit and row",
         revised(("call_1", "final_answer",
                  supported("2024 operating income was 25,785 billion won."))),
         "usd", "ok", "NOT_IN_DOCS", 3, ("call_1",)),
    Case("other-period figure",
         (one("call_1", "final_answer", supported("2024 net revenue was $22,680 million.")),),
         "usd", "ok", "PERIOD_MISMATCH", 2),
    Case("prose-only figure",
         revised(("call_1", "final_answer", supported("Revenue was 100 USD."))),
         "prose", "ok", "NOT_IN_DOCS", 3, ("call_1",)),
    Case("no evidence_reader",
         revised(("call_1", "final_answer", supported("Revenue was 100 USD."))),
         None, "ok", "NOT_IN_DOCS", 3, ("call_1",)),
    Case("tampered sha256",
         revised(("call_1", "final_answer",
                  supported("No figures here.", {**CITED, "source_sha256": "0" * 64}))),
         "usd", "ok", "NOT_IN_DOCS", 3, ("call_1",)),
    # Chunk 2023 exists on the server but this question searched only FY2024.
    Case("fetch before search", revised(("call_1", "fetch_chunk", {"chunk_id": 2023})),
         None, "ok", "NOT_IN_DOCS", 3, ("call_1",)),
    Case("system failure", revised(("call_1", "compare_years", FAILING)),
         None, "tool_error", None, 2, ("call_1",)),
    Case("string chunk id", revised(("call_1", "fetch_chunk", {"chunk_id": "2024"})),
         None, "ok", "NOT_IN_DOCS", 3, ("call_1",)),
    Case("final with other call",
         revised(("call_1a", "final_answer", ABSENT),
                 ("call_1b", "fetch_chunk", {"chunk_id": 2024})),
         None, "ok", "NOT_IN_DOCS", 3, ("call_1a", "call_1b")),
    # Further citation and failure cases.
    Case("citation never retrieved",
         revised(("call_1", "final_answer", supported(REVENUE, identity(2023)))),
         "usd", "ok", "NOT_IN_DOCS", 3, ("call_1",)),
    Case("malformed final answer",
         revised(("call_1", "final_answer",
                  {"label": "SUPPORTED", "answer": REVENUE, "citations": [CITED]})),
         "usd", "ok", "NOT_IN_DOCS", 3, ("call_1",)),
    Case("evidence read fails", revised(("call_1", "final_answer", supported(REVENUE))),
         "broken", "tool_error", None, 2, ("call_1",)),
]  # fmt: skip
ACCEPTED = [case for case in CASES if case.label not in (None, "NOT_IN_DOCS")]
# What each rejection must say, so a wrong reason cannot pass as the same call id.
REASONS = {
    "wrong unit and row": "does not confirm for 2024: 25,785 (operating income)",
    "prose-only figure": "does not confirm for 2024: 100 (revenue)",
    "no evidence_reader": "does not confirm for 2024: 100 (revenue)",
    "tampered sha256": "citation identity does not match retrieved evidence: 2024",
    "fetch before search": "chunk 2023 was not retrieved in this question; search first",
    "system failure": "tool compare_years failed",
    "string chunk id": "invalid arguments for fetch_chunk: chunk_id",
    "final with other call": FINAL_NOT_ALONE,
    "citation never retrieved": "cites chunk ids no tool returned in this run: 2023",
    "malformed final answer": "invalid final_answer: rationale",
    "evidence read fails": READ_FAILURE,
}
# (run_agent failure, create_agent failure): the loop names the client's exception type,
# the stop records the server's redacted message; both end before another model call.
FAILURES = {
    "system failure": (
        "MCPError: tool compare_years failed",
        "RuntimeError: tool compare_years failed",
    ),
    "evidence read fails": (READ_FAILURE, READ_FAILURE),
}
# (period mismatch record, withheld-figure record) as JSON; every other case has neither.
MISMATCH = {
    "requested_fiscal_years": [2024],
    "evidenced_fiscal_years": [2023],
    "figures": ["22,680"],
}
HELD = {"figures": ["25,785"]}
RECORDS = {"currency unknown": (None, HELD), "other-period figure": (MISMATCH, None)}


class Wire:
    """One relayed controlled server: tool calls on the wire and data-layer body reads."""

    def __init__(self, work: Path) -> None:
        work.mkdir()
        self.work = work
        self.log = work / "events.jsonl"
        self.log.touch()
        self.params = module_server(
            "tests.mcp.stdio_relay", str(work), "tests.mcp.controlled_filings", str(self.log)
        )

    def transport(self) -> StdioTransport:
        """The same relayed server as a FastMCP transport for MCPAdapter."""
        return StdioTransport(
            self.params.command,
            self.params.args,
            env=self.params.env,
            cwd=str(self.params.cwd),
            keep_alive=False,
        )

    def requests(self) -> list[dict[str, Any]]:
        """Every JSON-RPC request the client has sent so far."""
        path = self.work / "requests.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def mark(self) -> tuple[int, int]:
        """Positions in both recordings before a case starts."""
        return len(self.requests()), len(logged_events(self.log))

    def since(self, mark: tuple[int, int]) -> tuple[list[dict[str, Any]], list[int]]:
        """The tools/call params sent and the chunk bodies loaded after ``mark``."""
        sent = [r["params"] for r in self.requests()[mark[0] :] if r.get("method") == "tools/call"]
        events = logged_events(self.log, mark[1])
        return sent, [e["chunk_id"] for e in events if e["event"] == "body_load"]


@dataclass
class Direct:
    """One run_agent run: its result, model requests, wire calls, body loads and reads."""

    result: AgentResult
    provider: RecordingToolProvider
    sent: list[dict[str, Any]]
    loads: list[int]
    reads: list[tuple[int, ...]]

    @property
    def report(self) -> dict[str, Any] | None:
        """The reported answer as JSON, if any."""
        answer = self.result.answer
        return None if answer is None else answer.model_dump(mode="json")

    def errors(self) -> dict[str, str]:
        """Every error observation as the model would read it, by call id."""
        return {
            o.call_id: f"ERROR: {o.error}"
            for step in self.result.steps
            for o in step.observations
            if o.error is not None
        }


@dataclass
class Agent:
    """One create_agent run: its final state, model requests, wire calls, loads and reads."""

    state: dict[str, Any]
    model: ScriptedChatModel
    sent: list[dict[str, Any]]
    loads: list[int]
    reads: list[tuple[int, ...]]

    @property
    def status(self) -> str:
        """``tool_error`` when a system failure ended the run, else ``ok``."""
        return "tool_error" if self.state.get("failure") else "ok"

    @property
    def report(self) -> dict[str, Any] | None:
        """The accepted report as JSON; it must be the gate's typed report, not raw args."""
        answer = self.state.get("structured_response")
        if answer is None:
            return None
        assert isinstance(answer, AgentReportAnswer)
        return answer.model_dump(mode="json")

    def errors(self) -> dict[str, str]:
        """Every error tool result in the final state, by call id."""
        return {
            m.tool_call_id: str(m.content)
            for m in self.state["messages"]
            if isinstance(m, ToolMessage) and m.status == "error"
        }


def provider_turns(case: Case) -> list[Any]:
    """The case's turns as run_agent provider turns."""
    return [
        turn(
            tool_calls=tuple(
                ToolCall(call_id=i, name=n, arguments_json=json.dumps(a)) for i, n, a in calls
            )
        )
        for calls in case.turns()
    ]


def replies(turns: list[tuple[Call, ...]]) -> list[AIMessage]:
    """The same turns as scripted LangChain replies."""
    return [
        AIMessage(
            content="",
            tool_calls=[{"name": n, "args": a, "id": i, "type": "tool_call"} for i, n, a in calls],
            usage_metadata=USAGE,
        )
        for calls in turns
    ]


def review_agent(model: ScriptedChatModel, tools: list[BaseTool], checkpointer=None):
    """The section's composition: the stop wraps the gate, final_answer is the response."""
    middleware: list[AgentMiddleware[Any, Any]] = [StopOnSystemFailure(), ReviewGate(contracts())]
    return create_agent(
        model,
        tools,
        middleware=middleware,
        response_format=final_answer_format(),
        context_schema=ReviewContext,
        checkpointer=checkpointer,
    )


async def run_direct(bridge: ToolRegistry, case: Case, wire: Wire) -> Direct:
    """Run one case through run_agent over the MCP bridge."""
    provider = RecordingToolProvider(provider_turns(case))
    reader = Reader(case.reader) if case.reader else None
    mark = wire.mark()
    result = await run_agent(
        QUESTION,
        registry=bridge,
        provider=provider,
        requested_fiscal_years=YEARS,
        evidence_reader=reader,
    )
    sent, loads = wire.since(mark)
    return Direct(result, provider, sent, loads, reader.reads if reader else [])


async def run_through_agent(tools: list[BaseTool], case: Case, wire: Wire) -> Agent:
    """Run one case through create_agent with the review middleware."""
    model = ScriptedChatModel.from_replies(*replies(case.turns()))
    reader = Reader(case.reader) if case.reader else None
    mark = wire.mark()
    state = await review_agent(model, tools).ainvoke(
        {"messages": [HumanMessage(QUESTION)]}, context=ReviewContext(YEARS, reader)
    )
    sent, loads = wire.since(mark)
    return Agent(dict(state), model, sent, loads, reader.reads if reader else [])


@pytest.fixture(scope="module")
def outcomes(tmp_path_factory) -> dict[str, tuple[Direct, Agent]]:
    """Every case through both paths, each path on its own relayed server."""
    root = tmp_path_factory.mktemp("final_gate")
    direct_wire, agent_wire = Wire(root / "direct"), Wire(root / "agent")

    async def run_all() -> dict[str, tuple[Direct, Agent]]:
        """Run the baseline first, then the agent, case by case."""
        async with Client(direct_wire.params, mode=PROTOCOL_MODE) as client:
            bridge = await mcp_tool_registry(client, contracts())
            direct = {case.name: await run_direct(bridge, case, direct_wire) for case in CASES}
        async with MCPAdapter(agent_wire.transport()) as adapter:
            tools = await adapter.list_tools()
            agent = {case.name: await run_through_agent(tools, case, agent_wire) for case in CASES}
        return {name: (direct[name], agent[name]) for name in direct}

    return asyncio.run(run_all())


def by_name(cases: list[Case]):
    """Parametrize over cases with their names as test ids."""
    return pytest.mark.parametrize("case", cases, ids=[case.name for case in cases])


# Both paths over the real stdio server
@by_name(CASES)
def test_both_paths_end_with_the_same_report_and_model_requests(case, outcomes):
    """Status, label, the full report with citations and the request count all match."""
    direct, agent = outcomes[case.name]
    assert (direct.result.status, agent.status) == (case.status, case.status)
    assert direct.report == agent.report
    assert (direct.report or {}).get("label") == case.label
    assert len(direct.provider.requests) == len(agent.model.requests) == case.requests


@by_name(CASES)
def test_both_paths_keep_the_same_period_and_withheld_figure_records(case, outcomes):
    """Only a period mismatch or a withheld figure leaves a record, the same on both paths."""
    direct, agent = outcomes[case.name]
    expected = RECORDS.get(case.name, (None, None))
    direct_records = tuple(
        None if record is None else record.model_dump(mode="json")
        for record in (direct.result.period_mismatch, direct.result.unit_unverified)
    )
    agent_records = (agent.state.get("period_mismatch"), agent.state.get("unit_unverified"))
    assert direct_records == agent_records == expected


@by_name([case for case in CASES if case.rejected])
def test_rejections_answer_the_same_calls_for_the_same_reason(case, outcomes):
    """Each refused call is answered under its own id; a correctable one reaches the model."""
    direct, agent = outcomes[case.name]
    errors = agent.errors()
    assert set(errors) == set(case.rejected)
    assert all(REASONS[case.name] in text for text in errors.values())
    if case.status == "tool_error":
        assert (direct.result.failure, agent.state["failure"]) == FAILURES[case.name]
        return
    assert direct.errors() == errors
    replayed = {
        item["call_id"]: item["output"]
        for item in direct.provider.requests[-1][1]
        if item.get("type") == "function_call_output"
    }
    fed = {
        m.tool_call_id: m.content
        for m in agent.model.requests[-1].messages
        if isinstance(m, ToolMessage) and m.status == "error"
    }
    assert {i: replayed[i] for i in case.rejected} == {i: fed[i] for i in case.rejected} == errors


@by_name(ACCEPTED)
def test_an_accepted_report_keeps_its_citation_and_acknowledges_its_call(case, outcomes):
    """The report cites the full identity; a withheld figure never appears in its body."""
    _, agent = outcomes[case.name]
    report = agent.report
    assert report is not None and report["citations"] == [CITED]
    if case.label == "UNVERIFIED":
        assert report["answer"] == UNIT_UNVERIFIED_ANSWER
        assert not any(character.isdigit() for character in report["answer"])
    elif case.label == "SUPPORTED":
        assert report["answer"] == REVENUE
    else:
        assert "22,680" in report["answer"] and "2023" in report["answer"]
    acknowledgement = agent.state["messages"][-1]
    assert isinstance(acknowledgement, ToolMessage)
    assert (acknowledgement.tool_call_id, acknowledgement.name, acknowledgement.status) == (
        "call_1",
        "final_answer",
        "success",
    )
    assert acknowledgement.content == f"final_answer accepted as {case.label}"


@by_name(CASES)
def test_no_case_sends_a_fetch_and_both_read_the_same_evidence(case, outcomes):
    """Refused fetches and a fetch beside final_answer never cross stdio on either path."""
    direct, agent = outcomes[case.name]
    expected = ["search_filings", *(["compare_years"] if case.name == "system failure" else [])]
    sent = [[call["name"] for call in path.sent] for path in (direct, agent)]
    assert sent == [expected, expected]
    assert direct.loads == agent.loads == []
    assert direct.reads == agent.reads


@by_name([case for case in CASES if case.status == "tool_error"])
def test_a_failure_ends_without_an_answer_or_private_detail(case, outcomes):
    """The response format is configured, yet nothing is accepted and no detail leaks."""
    _, agent = outcomes[case.name]
    assert agent.state.get("structured_response") is None
    final = agent.state["messages"][-1]
    assert isinstance(final, ToolMessage) and final.status == "error"
    assert all(PRIVATE_DETAIL not in str(m.content) for m in agent.state["messages"])


# One checkpointed thread, several new questions
def ask_on_one_thread(work: Path, questions: list[tuple[list[tuple[Call, ...]], Reader]]):
    """Ask each question on one checkpointed thread; return its states and the model."""
    wire = Wire(work)
    model = ScriptedChatModel.from_replies(*replies([t for turns, _ in questions for t in turns]))
    config: Any = {"configurable": {"thread_id": "one thread"}}

    async def ask() -> list[dict[str, Any]]:
        """Invoke each question with its own context and keep the checkpointed values."""
        states = []
        async with MCPAdapter(wire.transport()) as adapter:
            agent = review_agent(model, await adapter.list_tools(), InMemorySaver())
            for number, (_, reader) in enumerate(questions, 1):
                await agent.ainvoke(
                    {"messages": [HumanMessage(f"Question {number}")]},
                    config,
                    context=ReviewContext(YEARS, reader),
                )
                states.append(dict((await agent.aget_state(config)).values))
        return states

    return asyncio.run(ask()), model


def question(prefix: str, *calls: tuple[str, dict[str, Any]]) -> list[tuple[Call, ...]]:
    """One question's turns: its own FY2024 search, then one call per turn."""
    turns = [one(f"{prefix}_search", "search_filings", SEARCH)]
    return turns + [one(f"{prefix}_{n}", name, args) for n, (name, args) in enumerate(calls, 1)]


def records(state: dict[str, Any]) -> tuple[Any, ...]:
    """The answer label and every per-question record a state holds."""
    answer = state.get("structured_response")
    label = answer.label if isinstance(answer, AgentReportAnswer) else answer
    return label, state.get("period_mismatch"), state.get("unit_unverified"), state.get("failure")


def test_each_new_question_starts_without_the_previous_report(tmp_path):
    """Withheld, period, answer and failure records never leak into the next question."""
    states, model = ask_on_one_thread(
        tmp_path / "thread",
        [
            (question("q1", ("final_answer", supported(REVENUE))), Reader("as_filed")),
            (question("q2", ("final_answer", supported("2024 net revenue was $22,680 million."))),
             Reader("usd")),
            (question("q3", ("compare_years", FAILING)), Reader("usd")),
            (question("q4", ("final_answer", supported(REVENUE))), Reader("usd")),
        ],
    )  # fmt: skip
    assert [records(state) for state in states] == [
        ("UNVERIFIED", None, HELD, None),
        ("PERIOD_MISMATCH", MISMATCH, None, None),
        (None, None, None, "RuntimeError: tool compare_years failed"),
        ("SUPPORTED", None, None, None),
    ]
    assert len(model.requests) == 8


def test_a_failed_read_after_an_accepted_answer_ends_with_no_answer(tmp_path):
    """The earlier SUPPORTED answer is gone, the final call gets the error, the model is idle."""
    broken = Reader("broken")
    states, model = ask_on_one_thread(
        tmp_path / "thread",
        [
            (question("q1", ("final_answer", supported(REVENUE))), Reader("usd")),
            (question("q2", ("final_answer", supported(REVENUE)), ("final_answer", ABSENT)),
             broken),
        ],
    )  # fmt: skip
    first, second = states
    assert records(first) == ("SUPPORTED", None, None, None)
    assert records(second) == (None, None, None, READ_FAILURE)
    final = second["messages"][-1]
    assert isinstance(final, ToolMessage)
    assert (final.tool_call_id, final.status, final.content) == (
        "q2_1",
        "error",
        f"ERROR: {READ_FAILURE}",
    )
    assert broken.reads == [(2024,)]
    # q1 used two model calls, q2 two; its scripted correction is never requested.
    assert len(model.requests) == 4
    assert all(PRIVATE_DETAIL not in str(m.content) for m in second["messages"])


# Focused checks of the model-call hooks
def model_call(
    gate_or_stop: AgentMiddleware[Any, Any], reply: AIMessage | Exception, reader: Reader | None
) -> Any:
    """Run one middleware's model hook against a stub handler that replies or raises."""
    calls: list[Any] = []

    async def handler(request: Any) -> ModelResponse:
        """Stand in for the model and any inner middleware."""
        calls.append(request)
        if isinstance(reply, Exception):
            raise reply
        return ModelResponse(result=[reply], structured_response=None)

    request = SimpleNamespace(
        state={"messages": [], "evidence": {2024: CITED}},
        runtime=SimpleNamespace(context=ReviewContext(YEARS, reader)),
    )
    answer = asyncio.run(gate_or_stop.awrap_model_call(cast(Any, request), handler))
    assert len(calls) == 1
    return answer


def final_reply(args: dict[str, Any]) -> AIMessage:
    """A reply proposing one final answer."""
    return replies([one("call_final", "final_answer", args)])[0]


def test_a_reply_without_final_answer_passes_through_unchanged():
    """Tool requests are left to the tools node; the gate adds nothing."""
    reply = replies([one("call_search", "search_filings", SEARCH)])[0]
    response = model_call(ReviewGate(contracts()), reply, Reader("usd"))
    assert isinstance(response, ModelResponse)
    assert response.result == [reply] and response.structured_response is None


def test_without_the_stop_a_failed_read_raises_instead_of_answering():
    """The gate never judges an answer whose evidence it could not read."""
    with pytest.raises(CitedEvidenceReadError) as caught:
        model_call(ReviewGate(contracts()), final_reply(supported(REVENUE)), Reader("broken"))
    assert caught.value.failure == READ_FAILURE
    assert caught.value.call["id"] == "call_final"
    assert PRIVATE_DETAIL not in str(caught.value)


def test_the_stop_records_only_a_read_failure_as_the_run_failure():
    """A read failure answers the final call and records it; other errors propagate."""
    reply = final_reply(supported(REVENUE))
    failed = CitedEvidenceReadError(reply, reply.tool_calls[0], READ_FAILURE)
    response = model_call(StopOnSystemFailure(), failed, None)
    assert isinstance(response, ExtendedModelResponse)
    assert response.command is not None and response.command.update == {"failure": READ_FAILURE}
    message, error = response.model_response.result
    assert message is reply and response.model_response.structured_response is None
    assert isinstance(error, ToolMessage)
    assert (error.tool_call_id, error.status, error.content) == (
        "call_final",
        "error",
        f"ERROR: {READ_FAILURE}",
    )
    with pytest.raises(RuntimeError, match="model unavailable"):
        model_call(StopOnSystemFailure(), RuntimeError("model unavailable"), None)


def test_an_accepted_final_becomes_the_typed_report_with_one_acknowledgement():
    """The structured response is the gate's report, not LangChain's unvalidated dict."""
    response = model_call(ReviewGate(contracts()), final_reply(supported(REVENUE)), Reader("usd"))
    assert isinstance(response, ModelResponse)
    assert isinstance(response.structured_response, AgentReportAnswer)
    messages: list[BaseMessage] = response.result
    assert [type(m) for m in messages] == [AIMessage, ToolMessage]
