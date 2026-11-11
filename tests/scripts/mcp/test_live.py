"""Budget, attempt and argument rules of the live MCP experiment runner.

The create-agent path is exercised offline: the real OpenAI SDK and ``ChatOpenAI``
talk to a fake HTTP endpoint that serves scripted token counts and Responses, and the
end-to-end run reaches the real stdio filings server with only its data layer
replaced. No request leaves the process and no database is used.
"""

import asyncio
from decimal import Decimal
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from fastmcp.client.transports import StdioTransport
import httpx2
from langchain.mcp import MCPAdapter
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import tool
import openai
import pytest

from app.agent.review_middleware import ReviewContext
from app.agent.tools.filings import build_default_registry
from app.contracts.evidence import EvidenceCitation
from app.db.session_factory import SessionFactory
from app.figures.answers import EvidenceText
from app.figures.tables import read_table_cells
from scripts.mcp import live
from scripts.mcp.live import (
    COUNTED_FIELDS,
    GENERATION_ONLY_FIELDS,
    BudgetExhaustedError,
    ModelGate,
    ModelSettings,
    Reservation,
    ask_review_agent,
    claim_attempt,
    counted_model,
    parser,
    resolve_model_settings,
    review_agent,
    tool_request,
)
from tests.mcp.controlled_filings import fixture_hit
from tests.mcp.support import logged_events, module_server
from tests.workflow.support import USD_INCOME_TABLE, income_table_hit

AGENT_ARGV = ["r", "agent", "--issuer", "AMD", "--years", "2023", "2024", "--question", "Q?"]
FAKE_KEY = "sk-test-offline-only"
COUNT_PATH = "/v1/responses/input_tokens"
RESPONSES_PATH = "/v1/responses"
QUESTION = "What was TestCo's FY2024 revenue?"
SEARCH = {"query": "revenue", "issuers": ["TEST"], "fiscal_years": [2024]}
REVENUE = "2024 net revenue was $25,785 million."
LUNA = resolve_model_settings(None, None, None, None, None)
OTHER = resolve_model_settings("acme-responses-1", Decimal("1.5"), Decimal("6"), 1000, None)


def test_reservation_keeps_failed_estimates_and_blocks_over_the_cap(tmp_path):
    """Every admitted estimate stays reserved; the next one over the cap is refused."""
    journal = tmp_path / "budget.jsonl"
    budget = Reservation(Decimal("0.01"), max_attempts=8, journal=journal)
    budget.reserve(Decimal("0.006"), "embedding")
    with pytest.raises(BudgetExhaustedError):
        budget.reserve(Decimal("0.005"), "embedding")
    assert budget.reserved_usd == Decimal("0.006")
    events = [json.loads(line) for line in journal.read_text().splitlines()]
    assert [event["status"] for event in events] == ["reserved", "blocked"]


def test_reservation_blocks_after_the_attempt_limit():
    """A free request still counts toward the approved number of attempts."""
    budget = Reservation(Decimal("1"), max_attempts=1)
    budget.reserve(Decimal("0"), "model")
    with pytest.raises(BudgetExhaustedError):
        budget.reserve(Decimal("0"), "model")


def test_a_run_id_can_be_attempted_only_once(tmp_path):
    """The exclusive marker refuses a repeated run before anything starts."""
    marker = claim_attempt(tmp_path / "run-1", {"command": "search"})
    assert json.loads(marker.read_text()) == {"command": "search"}
    with pytest.raises(SystemExit, match="already attempted"):
        claim_attempt(tmp_path / "run-1", {"command": "search"})


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (
            ["r", "search", "--issuer", "AMD", "--year", "2024", "--query", "revenue"],
            (
                "search_filings",
                {"query": "revenue", "k": 3, "issuers": ["AMD"], "fiscal_years": [2024]},
            ),
        ),
        (
            ["r", "compare", "--issuer", "AMD", "--years", "2023", "2024", "--query", "revenue"],
            (
                "compare_years",
                {"query": "revenue", "k": 3, "issuer": "AMD", "fiscal_years": [2023, 2024]},
            ),
        ),
        (["r", "fetch", "--chunk-id", "7"], ("fetch_chunk", {"chunk_id": 7})),
        (AGENT_ARGV, None),
    ],
)
def test_commands_map_to_one_tool_call_or_the_agent(argv, expected):
    """Single-call commands become their MCP tool request; agent has none."""
    assert tool_request(parser().parse_args(argv)) == expected


def test_agent_names_the_filings_it_asks_about():
    """The agent experiment refuses to parse without an issuer and years."""
    with pytest.raises(SystemExit):
        parser().parse_args(["r", "agent", "--question", "Q?"])


def test_agent_checks_the_index_before_claiming_the_run(tmp_path, monkeypatch):
    """An unindexed issuer stops the agent before its attempt marker or any paid call."""
    checked = []

    async def require_indexed(issuer, years):
        checked.append((issuer, years))
        raise SystemExit("not indexed")

    monkeypatch.setattr(live, "require_indexed", require_indexed)
    args = parser().parse_args([*AGENT_ARGV[:1], "--out", str(tmp_path), *AGENT_ARGV[1:]])

    with pytest.raises(SystemExit, match="not indexed"):
        asyncio.run(live.run(args))

    assert checked == [("AMD", [2023, 2024])]
    assert not (tmp_path / "r").exists()


# Model selection and options of the create-agent path
def test_the_registry_model_reserves_at_its_highest_input_rate():
    """Luna's cache-write rate 0.25 outranks its 0.20 input rate; reasoning stays medium."""
    assert (LUNA.model, LUNA.rate_source) == ("gpt-5.6-luna", "registry:2026-09-10")
    assert (LUNA.input_usd_per_million, LUNA.output_usd_per_million) == (
        Decimal("0.25"),
        Decimal("1.20"),
    )
    assert (LUNA.max_output_tokens, LUNA.reasoning_effort) == (4096, "medium")
    assert LUNA.reservation(1000) == Decimal("0.00025") + Decimal("0.0049152")


def test_another_registry_model_uses_its_own_rates():
    """Switching to Terra changes both rates; nothing is priced as Luna."""
    terra = resolve_model_settings("gpt-5.6-terra", None, None, 2048, "high")
    assert (terra.model, terra.input_usd_per_million, terra.output_usd_per_million) == (
        "gpt-5.6-terra",
        Decimal("2.50"),
        Decimal("12.00"),
    )
    assert (terra.max_output_tokens, terra.reasoning_effort) == (2048, "high")


def test_an_unregistered_model_runs_only_on_explicit_rates_without_a_reasoning_setting():
    """Both caller-supplied rates are applied as given and no reasoning effort is assumed."""
    assert (OTHER.model, OTHER.rate_source, OTHER.reasoning_effort) == (
        "acme-responses-1",
        "explicit",
        None,
    )
    assert OTHER.reservation(2000) == Decimal("0.003") + Decimal("0.006")
    with pytest.raises(ValueError, match="no registry rates"):
        resolve_model_settings("acme-responses-1", None, None, None, None)
    with pytest.raises(ValueError, match="go together"):
        resolve_model_settings("acme-responses-1", Decimal("1"), None, None, None)


@pytest.mark.parametrize(
    "options",
    [
        ["--input-usd-per-million", "0", "--output-usd-per-million", "1"],
        ["--input-usd-per-million", "-1", "--output-usd-per-million", "1"],
        ["--input-usd-per-million", "NaN", "--output-usd-per-million", "1"],
        ["--input-usd-per-million", "1", "--output-usd-per-million", "Infinity"],
        ["--input-usd-per-million", "cheap", "--output-usd-per-million", "1"],
        ["--max-output-tokens", "0"],
        ["--reasoning-effort", "extreme"],
    ],
)
def test_invalid_model_options_are_refused_while_parsing(options):
    """Rates must be positive and finite, output ceilings positive, efforts known."""
    with pytest.raises(SystemExit):
        parser().parse_args([*AGENT_ARGV, "--via", "create-agent", *options])


@pytest.mark.parametrize(
    ("options", "message"),
    [
        (["--model", "gpt-5.6-terra"], "--model apply only with --via create-agent"),
        (["--max-output-tokens", "100"], "--max-output-tokens apply only"),
        (["--locale", "ko"], "--locale apply only with --via create-agent"),
        (["--via", "create-agent", "--model", "acme-responses-1"], "no registry rates"),
        (
            ["--via", "create-agent", "--model", "x", "--input-usd-per-million", "1"],
            "go together",
        ),
        *[
            (["--via", "create-agent", "--model-cap", cap], "invalid create-agent budget")
            for cap in ("Infinity", "NaN", "-1", "not-a-price")
        ],
        *[
            (["--via", "create-agent", "--model-attempts", count], "invalid create-agent budget")
            for count in ("0", "-1", "65")
        ],
    ],
)
def test_model_options_fail_before_any_database_or_api_work(
    tmp_path, monkeypatch, options, message
):
    """Options run_agent would ignore, or an unpriceable model, stop before the index check."""
    checked = []

    async def require_indexed(issuer, years):
        checked.append((issuer, years))
        raise AssertionError("invalid model settings must stop before the index check")

    monkeypatch.setattr(live, "require_indexed", require_indexed)
    args = parser().parse_args(["r", "--out", str(tmp_path), *AGENT_ARGV[1:], *options])

    with pytest.raises(SystemExit, match=message):
        asyncio.run(live.run(args))

    assert checked == []
    assert not (tmp_path / "r").exists()


def test_the_default_agent_path_is_still_run_agent():
    """Without --via, the agent command parses exactly as before and needs no model settings."""
    args = parser().parse_args(AGENT_ARGV)
    assert (args.via, args.model_cap, args.model_attempts) == ("run-agent", "0.09", 8)
    assert live.agent_model_settings(args) is None


# An offline OpenAI endpoint for the real SDK
def response(call_id: str, name: str, arguments: dict[str, Any], usage: tuple[int, int]) -> dict:
    """A completed Responses body whose only output is one function call."""
    return {
        "id": f"resp_{call_id}",
        "object": "response",
        "created_at": 0,
        "status": "completed",
        "model": "served-model",
        "output": [
            {
                "type": "function_call",
                "id": f"fc_{call_id}",
                "call_id": call_id,
                "name": name,
                "arguments": json.dumps(arguments),
                "status": "completed",
            }
        ],
        "parallel_tool_calls": True,
        "tool_choice": "required",
        "tools": [],
        "usage": {
            "input_tokens": usage[0],
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens": usage[1],
            "output_tokens_details": {"reasoning_tokens": 3},
            "total_tokens": sum(usage),
        },
    }


class FakeOpenAI:
    """Serve scripted counts and responses over HTTP and record every request body.

    ``failures`` maps ``(path, n)``, the n-th request to a path, to an HTTP response
    or an exception raised in place of the scripted answer.
    """

    def __init__(self, counts=(), replies=(), failures=None) -> None:
        self.counts = list(counts)
        self.replies = list(replies)
        self.failures = failures or {}
        self.requests: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        """Record the request, then fail it or answer it from the script."""
        path = request.url.path
        assert request.headers["authorization"] == f"Bearer {FAKE_KEY}"
        self.requests.append((path, json.loads(request.content)))
        failure = self.failures.get((path, len(self.bodies(path))))
        if isinstance(failure, Exception):
            raise failure
        if failure is not None:
            return failure
        if path == COUNT_PATH:
            tokens = self.counts.pop(0)
            return httpx2.Response(
                200, json={"object": "response.input_tokens", "input_tokens": tokens}
            )
        assert path == RESPONSES_PATH
        return httpx2.Response(200, json=self.replies.pop(0))

    def bodies(self, path: str) -> list[dict[str, Any]]:
        """Bodies sent to one endpoint, in order."""
        return [body for sent, body in self.requests if sent == path]

    def client(self) -> Any:
        """An SDK HTTP client whose transport is this fake."""
        return openai.DefaultAsyncHttpxClient(transport=httpx2.MockTransport(self))


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
FINAL = {"label": "SUPPORTED", "answer": REVENUE, "citations": [CITED], "rationale": "cited"}


async def usd_table(chunk_ids: tuple[int, ...]) -> dict[int, EvidenceText]:
    """Read chunk 2024 as the income table with an explicit, test-added USD note."""
    table, fragment = income_table_hit(2024, html=USD_INCOME_TABLE)
    return {
        2024: EvidenceText(
            2024, table.body, table.context_header, tuple(read_table_cells(fragment))
        )
    }


def contracts():
    """The app's tool contracts; their run functions must never be needed."""
    return build_default_registry(cast(SessionFactory, object))


def journal(path: Path) -> list[tuple[str, str]]:
    """The (kind, status) of every budget event."""
    return [(e["kind"], e["status"]) for e in map(json.loads, path.read_text().splitlines())]


# One question end to end: real stdio MCP, fake OpenAI endpoint
@pytest.fixture(scope="module", params=[LUNA, OTHER], ids=["registry-luna", "explicit-model"])
def asked(request, tmp_path_factory) -> SimpleNamespace:
    """Search, read the result, then answer: two counted, reserved turns over real stdio."""
    settings: ModelSettings = request.param
    work = tmp_path_factory.mktemp("create_agent")
    fake = FakeOpenAI(
        counts=[1200, 1500],
        replies=[
            response("call_search", "search_filings", SEARCH, (1190, 40)),
            response("call_final", "final_answer", FINAL, (1490, 60)),
        ],
    )
    budget = Reservation(Decimal("0.09"), 8, journal=work / "budget.jsonl")
    gate = ModelGate(budget, settings, 60_000)
    model = counted_model(settings, gate, api_key=FAKE_KEY, http_async_client=fake.client())
    log = work / "events.jsonl"
    log.touch()
    server = module_server("tests.mcp.controlled_filings", str(log))
    transport = StdioTransport(
        server.command, server.args, env=server.env, cwd=str(server.cwd), keep_alive=False
    )

    async def ask() -> dict[str, Any]:
        """Run the question through the experiment's own agent composition."""
        async with MCPAdapter(transport) as adapter:
            agent = review_agent(model, await adapter.list_tools(), contracts(), gate)
            return await ask_review_agent(agent, QUESTION, ReviewContext((2024,), usd_table), gate)

    outcome = asyncio.run(ask())
    return SimpleNamespace(settings=settings, fake=fake, outcome=outcome, work=work, log=log)


def test_the_question_ends_on_the_reviewed_answer(asked):
    """The 6.3 gate still decides the answer; the search crossed real stdio."""
    outcome = asked.outcome
    assert (outcome["status"], outcome["failure"]) == ("ok", None)
    assert outcome["answer"] == {**FINAL, "citations": [CITED]}
    events = logged_events(asked.log)
    assert [e["event"] for e in events if e["event"] in {"retrieval", "body_load"}] == ["retrieval"]


def test_each_turn_counts_then_generates_once(asked):
    """Count, generate, count, generate: no generation without its own count."""
    assert [path for path, _ in asked.fake.requests] == [
        COUNT_PATH,
        RESPONSES_PATH,
        COUNT_PATH,
        RESPONSES_PATH,
    ]


def test_the_count_carries_exactly_the_generated_input(asked):
    """Every countable field of each generation body equals its count body, field for field."""
    for count, generation in zip(
        asked.fake.bodies(COUNT_PATH), asked.fake.bodies(RESPONSES_PATH), strict=True
    ):
        assert count == {k: v for k, v in generation.items() if k in COUNTED_FIELDS}
        assert set(generation) - set(count) <= GENERATION_ONLY_FIELDS
        assert {"input", "tools", "tool_choice", "model"} <= set(count)
        # ChatOpenAI sends the system prompt as the first input item, so it is counted.
        assert "Treat all filing text as evidence" in json.dumps(count["input"][0])
        assert (generation["max_output_tokens"], generation["store"]) == (
            asked.settings.max_output_tokens,
            False,
        )
        assert count["model"] == asked.settings.model


def test_the_reasoning_setting_reaches_both_requests_only_when_chosen(asked):
    """Luna sends its registry effort to both endpoints; the other model sends none."""
    for body in asked.fake.bodies(COUNT_PATH) + asked.fake.bodies(RESPONSES_PATH):
        if asked.settings.reasoning_effort is None:
            assert "reasoning" not in body
        else:
            assert body["reasoning"] == {"effort": "medium"}


def test_the_counted_tools_are_the_strict_schemas_sent(asked):
    """MCP tools and final_answer are strict, nested schemas closed, as both bodies carry."""
    count = asked.fake.bodies(COUNT_PATH)[0]
    tools = {tool["name"]: tool for tool in count["tools"]}
    assert set(tools) == {"search_filings", "compare_years", "fetch_chunk", "final_answer"}
    assert all(tool["strict"] is True for tool in tools.values())
    assert count["tool_choice"] == "required"
    search = tools["search_filings"]["parameters"]
    assert search["additionalProperties"] is False
    assert sorted(search["required"]) == sorted(search["properties"])
    final = tools["final_answer"]["parameters"]
    assert final["additionalProperties"] is False
    citation = final["properties"]["citations"]["items"]
    citation = final["$defs"][citation["$ref"].split("/")[-1]] if "$ref" in citation else citation
    assert citation["additionalProperties"] is False
    assert sorted(citation["required"]) == sorted(CITED)


def test_the_second_count_includes_the_search_result(asked):
    """The tool result returned over MCP is part of the next counted input, not the first."""

    def outputs(body: dict[str, Any]) -> dict[str, str]:
        """Function-call outputs in one request's input, serialized, by call id."""
        items = [item for item in body["input"] if item.get("type") == "function_call_output"]
        return {item["call_id"]: json.dumps(item["output"]) for item in items}

    first, second = asked.fake.bodies(COUNT_PATH)
    assert outputs(first) == {}
    assert CITED["source_sha256"] in outputs(second)["call_search"]


def test_reservations_and_observed_usage_are_recorded_apart(asked):
    """Reserved USD comes from the counts and output ceiling; usage is what the replies said."""
    settings, budget = asked.settings, asked.outcome["budget"]
    expected = settings.reservation(1200) + settings.reservation(1500)
    assert (budget["reserved_usd"], budget["attempts"]) == (str(expected), 2)
    assert budget["counted_input_tokens"] == 2700
    observed = [
        (o["response_id"], o["input_tokens"], o["output_tokens"]) for o in budget["observed"]
    ]
    assert observed == [("resp_call_search", 1190, 40), ("resp_call_final", 1490, 60)]
    assert asked.outcome["model"] == settings.record()
    turn = [("count", "counted"), ("model", "reserved"), ("model", "observed")]
    assert journal(asked.work / "budget.jsonl") == turn * 2
    text = (asked.work / "budget.jsonl").read_text()
    assert FAKE_KEY not in text and REVENUE not in text


def trace_events(work: Path) -> list[dict[str, Any]]:
    """Read the durable diagnostic events written by the experiment itself."""
    return [json.loads(line) for line in (work / "trace.jsonl").read_text().splitlines()]


def test_trace_distinguishes_mcp_dispatch_and_final_review(asked):
    """Real stdio search dispatch and accepted final feedback retain their call IDs."""
    events = trace_events(asked.work)
    assert [e["sequence"] for e in events] == list(range(1, len(events) + 1))
    dispatched = [e for e in events if (e["layer"], e["event"]) == ("execution", "tool_start")]
    assert [e["call"]["id"] for e in dispatched] == ["call_search"]
    final = [e for e in events if (e["layer"], e["event"]) == ("gate", "model_result")][-1]
    assert final["turn"] == 2 and final["report_label"] == "SUPPORTED"
    assert final["messages"][0]["tool_calls"][0]["args"] == FINAL
    assert final["messages"][1]["call_id"] == "call_final"
    assert final["messages"][1]["content"] == "final_answer accepted as SUPPORTED"
    assert FAKE_KEY not in (asked.work / "trace.jsonl").read_text()


def test_trace_keeps_gate_rejections_before_attempt_exhaustion(tmp_path):
    """A failed run still explains each refused final and the unsent next turn."""
    fake = FakeOpenAI(counts=[1000, 1000], replies=[uncited(1), uncited(2)])
    outcome, _ = ask_offline(tmp_path, fake, attempts=2)
    assert outcome["status"] == "budget_exceeded"
    events = trace_events(tmp_path)
    reviewed = [e for e in events if (e["layer"], e["event"]) == ("gate", "model_result")]
    assert len(reviewed) == 2
    for number, event in enumerate(reviewed, 1):
        assert event["has_structured_response"] is False
        feedback = event["messages"][1]
        assert feedback["call_id"] == f"call_{number}"
        assert feedback["status"] == "error" and "2024" in feedback["content"]
    assert events[-1]["event"] == "model_error" and events[-1]["turn"] == 3
    assert not any(e["layer"] == "execution" and e["turn"] == 3 for e in events)
    assert len(fake.bodies(RESPONSES_PATH)) == 2


def test_trace_does_not_call_a_gate_rejected_fetch_an_execution(tmp_path):
    """The evidence guard's rejection is visible without a false MCP dispatch event."""
    fake = FakeOpenAI(
        counts=[1000],
        replies=[response("fetch_unseen", "fetch_chunk", {"chunk_id": 2024}, (900, 30))],
    )
    outcome, _ = ask_offline(tmp_path, fake, attempts=1)
    assert outcome["status"] == "budget_exceeded"
    events = trace_events(tmp_path)
    feedback = [e for e in events if e["event"] == "tool_result"]
    assert len(feedback) == 1 and feedback[0]["layer"] == "gate"
    assert "was not retrieved in this question" in feedback[0]["messages"][0]["content"]
    assert not any(e["event"] == "tool_start" and e["layer"] == "execution" for e in events)


def test_trace_retains_tool_exception_without_private_details(tmp_path):
    """An unexpected tool exception propagates and leaves a redacted dispatch failure."""

    @tool
    async def search_filings(query: str, issuers: list[str], fiscal_years: list[int]) -> str:
        """A test retrieval failure after actual tool dispatch."""
        raise RuntimeError("private database password=do-not-log")

    fake = FakeOpenAI(
        counts=[1000], replies=[response("search_fail", "search_filings", SEARCH, (900, 30))]
    )
    gate = ModelGate(
        Reservation(Decimal("0.09"), 2, journal=tmp_path / "budget.jsonl"), LUNA, 60_000
    )
    model = counted_model(LUNA, gate, api_key=FAKE_KEY, http_async_client=fake.client())
    agent = review_agent(model, [search_filings], contracts(), gate)
    with pytest.raises(RuntimeError, match="private database"):
        asyncio.run(ask_review_agent(agent, QUESTION, ReviewContext((2024,)), gate))
    events = trace_events(tmp_path)
    failures = [e for e in events if e["event"] == "tool_error"]
    assert [e["layer"] for e in failures] == ["execution", "gate"]
    assert all(e["call_id"] == "search_fail" for e in failures)
    assert "do-not-log" not in (tmp_path / "trace.jsonl").read_text()


def test_trace_excludes_model_reasoning_and_redacts_credentials(tmp_path):
    """Trace projections omit model content and sanitize calls and bounded feedback."""
    trace = live.RunTrace(tmp_path / "trace.jsonl", ("configured-private-value",))
    messages = [
        AIMessage(
            content=[{"type": "reasoning", "text": "private-model-reasoning"}],
            tool_calls=[{"id": "a", "name": "search_filings", "args": {"query": FAKE_KEY}}],
        ),
        ToolMessage(
            content="x" * 15_990 + "configured-private-value" + "y" * 100, tool_call_id="a"
        ),
    ]
    trace.write("gate", "model_result", 1, messages=live.trace_messages(messages))
    content = trace.path.read_text()
    assert all(
        value not in content
        for value in [FAKE_KEY, "configured-private-value", "private-model-reasoning"]
    )
    assert trace_events(tmp_path)[0]["messages"][1]["content_truncated"] is True
    assert "configured" not in content


# Budget and count boundaries, without tools: an uncited final answer is refused
def ask_offline(
    tmp_path: Path, fake: FakeOpenAI, *, cap="0.09", attempts=8, max_input=60_000
) -> tuple[dict[str, Any], Reservation]:
    """Ask once with no tools, so each final answer is refused and the model asked again."""
    budget = Reservation(Decimal(cap), attempts, journal=tmp_path / "budget.jsonl")
    gate = ModelGate(budget, LUNA, max_input)
    model = counted_model(LUNA, gate, api_key=FAKE_KEY, http_async_client=fake.client())
    agent = review_agent(model, [], contracts(), gate)
    outcome = asyncio.run(ask_review_agent(agent, QUESTION, ReviewContext((2024,)), gate))
    return outcome, budget


def uncited(n: int) -> dict[str, Any]:
    """A final answer citing a chunk no tool returned, so the gate refuses it."""
    return response(f"call_{n}", "final_answer", FINAL, (900, 30))


def absent_response() -> dict[str, Any]:
    """Return a valid final answer with separate cache-read and cache-write usage."""
    reply = response(
        "call_absent",
        "final_answer",
        {"label": "NOT_IN_DOCS", "answer": "NOT_IN_DOCS", "citations": [], "rationale": "none"},
        (1000, 10),
    )
    reply["usage"]["input_tokens_details"] = {"cached_tokens": 100, "cache_write_tokens": 400}
    return reply


def test_observed_cost_includes_cache_writes_without_refunding_the_reservation(tmp_path):
    """SDK usage categories reach the journal and cost estimate; reservation stays whole."""
    fake = FakeOpenAI(counts=[1000], replies=[absent_response()])
    outcome, budget = ask_offline(tmp_path, fake)
    assert outcome["status"] == "ok"
    event = outcome["budget"]["observed"][0]
    assert (
        event["input_tokens"],
        event["cached_input_tokens"],
        event["cache_write_input_tokens"],
    ) == (1000, 100, 400)
    # 500 regular + 100 cached + 400 cache-write input tokens, plus 10 output tokens.
    assert Decimal(event["observed_usd"]) == Decimal("0.000214")
    assert budget.reserved_usd == Decimal("0.0051652")
    assert (
        json.loads((tmp_path / "budget.jsonl").read_text().splitlines()[-1])["observed_usd"]
        == (event["observed_usd"])
    )


@pytest.mark.parametrize("usage_kind", ["missing", "null", "invalid-details"])
def test_unavailable_usage_is_not_reported_as_zero_or_a_lost_response(tmp_path, usage_kind):
    """A response without usable accounting keeps its reservation and has no cost estimate."""
    reply = absent_response()
    if usage_kind == "missing":
        del reply["usage"]
    elif usage_kind == "null":
        reply["usage"] = None
    else:
        reply["usage"]["input_tokens_details"]["cached_tokens"] = 900
    fake = FakeOpenAI(counts=[1000], replies=[reply])
    outcome, budget = ask_offline(tmp_path, fake)
    assert outcome["status"] == "ok"
    event = outcome["budget"]["observed"][0]
    assert event["status"] == "usage_unavailable"
    assert event["observed_usd"] is None
    assert event["response_id"] == "resp_call_absent"
    assert event["reason"] == ("invalid" if usage_kind == "invalid-details" else "missing")
    assert budget.reserved_usd == Decimal("0.0051652")
    assert journal(tmp_path / "budget.jsonl") == [
        ("count", "counted"),
        ("model", "reserved"),
        ("model", "usage_unavailable"),
    ]


def test_zero_model_cap_is_valid_but_never_admits_a_generation(tmp_path):
    """A zero cap remains a supported no-generation budget, unlike negative or infinite caps."""
    args = parser().parse_args([*AGENT_ARGV, "--via", "create-agent", "--model-cap", "0"])
    assert live.agent_model_settings(args) is not None
    fake = FakeOpenAI(counts=[1000])
    outcome, budget = ask_offline(tmp_path, fake, cap="0")
    assert (outcome["status"], budget.attempts, budget.reserved_usd) == (
        "budget_exceeded",
        0,
        Decimal("0"),
    )
    assert [path for path, _ in fake.requests] == [COUNT_PATH]


@pytest.mark.parametrize(
    "failure",
    [
        httpx2.Response(500, json={"error": {"message": "server", "type": "server_error"}}),
        httpx2.Response(400, json={"error": {"message": "bad", "type": "invalid_request_error"}}),
        httpx2.ReadTimeout("count timed out"),
    ],
    ids=["server-error", "rejected", "timeout"],
)
def test_a_failed_count_sends_no_generation(tmp_path, failure):
    """No count, no generation: nothing is reserved and nothing is retried."""
    fake = FakeOpenAI(replies=[uncited(1)], failures={(COUNT_PATH, 1): failure})
    outcome, budget = ask_offline(tmp_path, fake)
    assert (outcome["status"], outcome["answer"]) == ("count_error", None)
    assert outcome["failure"].endswith("input token count failed")
    assert [path for path, _ in fake.requests] == [COUNT_PATH]
    assert (budget.reserved_usd, budget.attempts) == (Decimal("0"), 0)
    assert journal(tmp_path / "budget.jsonl") == [("count", "failed")]


def test_the_usd_cap_is_checked_after_the_count_and_blocks_the_next_turn(tmp_path):
    """The second turn is counted, found over the cap, and never generated."""
    fake = FakeOpenAI(counts=[1000, 1000], replies=[uncited(1), uncited(2)])
    cap = LUNA.reservation(1000) + Decimal("0.001")
    outcome, budget = ask_offline(tmp_path, fake, cap=str(cap))
    assert (outcome["status"], outcome["answer"]) == ("budget_exceeded", None)
    assert [path for path, _ in fake.requests] == [COUNT_PATH, RESPONSES_PATH, COUNT_PATH]
    assert (budget.reserved_usd, budget.attempts) == (LUNA.reservation(1000), 1)
    assert journal(tmp_path / "budget.jsonl")[-1] == ("model", "blocked")


def test_used_attempts_block_the_next_turn_before_its_count(tmp_path):
    """The attempt limit is shared by all turns of the question and stops even counting."""
    fake = FakeOpenAI(counts=[1000], replies=[uncited(1), uncited(2)])
    outcome, budget = ask_offline(tmp_path, fake, attempts=1)
    assert outcome["status"] == "budget_exceeded"
    assert [path for path, _ in fake.requests] == [COUNT_PATH, RESPONSES_PATH]
    assert budget.attempts == 1


def test_the_question_input_threshold_spans_turns(tmp_path):
    """Counted input accumulates; the turn that would pass the threshold is not generated."""
    fake = FakeOpenAI(counts=[1000, 600], replies=[uncited(1), uncited(2)])
    outcome, budget = ask_offline(tmp_path, fake, max_input=1500)
    assert outcome["status"] == "budget_exceeded"
    assert outcome["budget"]["counted_input_tokens"] == 1000
    assert [path for path, _ in fake.requests] == [COUNT_PATH, RESPONSES_PATH, COUNT_PATH]
    assert budget.attempts == 1


def test_a_lost_response_keeps_its_reservation_and_reports_no_answer(tmp_path):
    """A timed-out generation may have been billed: its reservation stays and is unknown."""
    fake = FakeOpenAI(
        counts=[1000],
        replies=[uncited(1)],
        failures={(RESPONSES_PATH, 1): httpx2.ReadTimeout("response lost")},
    )
    outcome, budget = ask_offline(tmp_path, fake)
    assert (outcome["status"], outcome["answer"]) == ("provider_error", None)
    assert [path for path, _ in fake.requests] == [COUNT_PATH, RESPONSES_PATH]
    assert (budget.reserved_usd, budget.attempts) == (LUNA.reservation(1000), 1)
    assert journal(tmp_path / "budget.jsonl") == [
        ("count", "counted"),
        ("model", "reserved"),
        ("model", "unknown"),
    ]


def test_a_model_call_outside_the_middleware_sends_nothing(tmp_path):
    """Without a turn opened by ReserveBeforeSend the model refuses before counting."""
    fake = FakeOpenAI(counts=[1000], replies=[uncited(1)])
    gate = ModelGate(Reservation(Decimal("0.09"), 8), LUNA, 60_000)
    model = counted_model(LUNA, gate, api_key=FAKE_KEY, http_async_client=fake.client())
    with pytest.raises(RuntimeError, match="outside a ReserveBeforeSend turn"):
        asyncio.run(model.ainvoke("hello"))
    assert fake.requests == []


def test_the_create_agent_path_selects_cells_and_its_server_returns_them(monkeypatch):
    """Offer the cell-selecting final answer and serve fetched chunks with their cells."""
    formats = []
    monkeypatch.setattr(
        live, "create_agent", lambda *_, **kw: formats.append(kw["response_format"])
    )
    gate = ModelGate(Reservation(Decimal("1"), 2), LUNA, 1000)
    model = counted_model(LUNA, gate, api_key=FAKE_KEY)
    review_agent(model, [], contracts(), gate, cells=True)
    review_agent(model, [], contracts(), gate)
    titles = [schema.schema["properties"].get("contract_version") for schema in formats]
    assert titles[0] is not None and titles[1] is None
    serve = parser().parse_args(["r", "serve", "--embedding-cap", "0.001", "--include-cells"])
    assert serve.serve_cells is True
