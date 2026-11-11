"""Budget, attempt and argument rules of the live MCP experiment runner.

The create-agent path is exercised offline: the real OpenAI SDK and ``ChatOpenAI``
talk to a fake HTTP endpoint that serves scripted token counts and Responses, and the
end-to-end run reaches the real stdio filings server with only its data layer
replaced. No request leaves the process and no database is used.
"""

import asyncio
from decimal import Decimal
from functools import partial
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Any, cast

from fastmcp.client.transports import StdioTransport
import httpx2
from langchain.mcp import MCPAdapter
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import BaseTool, tool
import mcp
import openai
from pydantic import SecretStr
import pytest
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app import config
from app.agent import stored_evidence
from app.agent.cell_answers import StoredCell
from app.agent.review_middleware import ReviewContext
from app.agent.tools import filings
from app.agent.tools.filings import FetchedChunk, build_default_registry
from app.agent.tools.registry import ToolError, execute_tool
from app.contracts.evidence import EvidenceCitation
from app.db.models import Chunk, ParsedTable
from app.db.session_factory import SessionFactory
from app.figures.answers import EvidenceText
from app.figures.tables import read_table_cells
from app.mcp import filings_server
from app.query.scope import issuer_names
from scripts.mcp import live
from scripts.mcp.live import (
    COUNTED_FIELDS,
    GENERATION_ONLY_FIELDS,
    BudgetExhaustedError,
    CappedEmbedding,
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
from tests.mcp.controlled_filings import ControlledSession, fixture_hit
from tests.mcp.support import REPO_ROOT, logged_events, module_server
from tests.scripts.mcp.cell_filings import (
    RESOLVER_IDENTITY,
    REVENUE_CELL,
    STABLE_KEY,
)
from tests.scripts.mcp.live_database import EMBEDDING_MODEL, seeded_database
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


CORPUS_DIR = REPO_ROOT / "data/corpus"  # the repository's own manifest, read only


def offline_settings(environment: str = "dev") -> SimpleNamespace:
    """Settings for an offline run: the named MODE, the free local embedder, no key."""
    return SimpleNamespace(
        environment=environment,
        embedding_provider="deterministic",
        openai_api_key=None,
        corpus_dir=CORPUS_DIR,
    )


def keyed_settings() -> SimpleNamespace:
    """Development settings with an offline-only key in the MODE-selected slot."""
    return SimpleNamespace(**vars(offline_settings()) | {"openai_api_key": SecretStr(FAKE_KEY)})


@pytest.fixture(autouse=True)
def development_mode(monkeypatch):
    """Run every test in development mode without reading any environment file."""
    monkeypatch.setattr(config, "get_settings", offline_settings)


class FakeEngine:
    """Stands in for the read-only engine of a test that never queries the database."""

    disposed = False

    async def dispose(self) -> None:
        """Record that the pool was released."""
        self.disposed = True


def serve_offline(monkeypatch, *, include_cells: bool) -> tuple[list[Any], FakeEngine]:
    """Run ``serve`` with the stdio transport replaced; return its registries and engine."""
    registries: list[Any] = []
    engine = FakeEngine()

    async def serve_stdio(registry) -> None:
        """Capture the registry the server would expose."""
        registries.append(registry)

    monkeypatch.setattr(filings_server, "serve", serve_stdio)
    monkeypatch.setattr(live, "read_only_engine", lambda: engine)
    asyncio.run(
        live.serve(Path("unused"), Reservation(Decimal("0.01"), 8), include_cells=include_cells)
    )
    return registries, engine


def test_production_mode_refuses_the_experiment_before_any_work(tmp_path, monkeypatch, capsys):
    """MODE=prod exits with code 2 before options, the index check or the run marker."""
    monkeypatch.setattr(config, "get_settings", lambda: offline_settings("prod"))

    async def require_indexed(issuer, years, **_):
        raise AssertionError("production mode must stop before the database")

    monkeypatch.setattr(live, "require_indexed", require_indexed)
    args = parser().parse_args(
        ["r", "--out", str(tmp_path), *AGENT_ARGV[1:], "--via", "create-agent"]
    )
    with pytest.raises(SystemExit) as stopped:
        asyncio.run(live.run(args))
    assert stopped.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == "" and "refusing MODE=prod" in captured.err
    assert not (tmp_path / "r").exists()


def test_production_mode_refuses_the_server_before_the_database(monkeypatch, capsys):
    """The server subprocess applies the same refusal before its engine or transport."""
    monkeypatch.setattr(config, "get_settings", lambda: offline_settings("prod"))

    def never(*_: object) -> Any:
        raise AssertionError("production mode must stop before the engine or transport")

    monkeypatch.setattr(live, "read_only_engine", never)
    monkeypatch.setattr(filings_server, "serve", never)
    with pytest.raises(SystemExit) as stopped:
        asyncio.run(live.serve(Path("unused"), Reservation(Decimal("0.01"), 8)))
    assert stopped.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == "" and "refusing MODE=prod" in captured.err


def test_development_mode_serves_the_registry_and_releases_the_pool(monkeypatch):
    """Under MODE=dev the server starts on the local embedder and disposes its engine."""
    registries, engine = serve_offline(monkeypatch, include_cells=False)
    assert len(registries) == 1 and engine.disposed
    assert registries[0].get("fetch_chunk").output is None


# The capped query embedder the server uses on the OpenAI embedding path
def embedding_client(sent: list[dict[str, Any]], billed: list[int]) -> openai.AsyncOpenAI:
    """An SDK client whose embeddings endpoint is served offline and records each body.

    Each reply bills the next of ``billed`` input tokens, or one token once they run out.
    """

    def respond(request: httpx2.Request) -> httpx2.Response:
        """Answer one embedding request with a unit vector and its billed tokens."""
        sent.append(json.loads(request.content))
        tokens = billed.pop(0) if billed else 1
        return httpx2.Response(
            200,
            json={
                "object": "list",
                "model": "text-embedding-3-large",
                "data": [{"object": "embedding", "index": 0, "embedding": [1.0] * 384}],
                "usage": {"prompt_tokens": tokens, "total_tokens": tokens},
            },
        )

    return openai.AsyncOpenAI(
        api_key=FAKE_KEY,
        max_retries=0,
        http_client=openai.DefaultAsyncHttpxClient(transport=httpx2.MockTransport(respond)),
    )


def capped(
    budget: Reservation, sent: list[dict[str, Any]], billed: tuple[int, ...] = ()
) -> CappedEmbedding:
    """The capped embedder over the offline endpoint billing ``billed`` tokens in turn."""
    client = embedding_client(sent, list(billed))
    return CappedEmbedding(budget, client=client, credential_slot="dev")


EMBEDDING_TOKEN_USD = Decimal("0.13") / Decimal(1_000_000)  # USD per embedding input token


def embed_twice(
    cap: str, billed: tuple[int, ...]
) -> tuple[Reservation, list[Any], Exception | None]:
    """Embed two queries under ``cap``; return the budget, the bodies sent and any refusal."""
    sent: list[dict[str, Any]] = []
    budget = Reservation(Decimal(cap), 8)
    provider = capped(budget, sent, billed)
    asyncio.run(provider.embed_query("revenue"))
    try:
        asyncio.run(provider.embed_query("revenue 2024"))
    except BudgetExhaustedError as error:
        return budget, sent, error
    return budget, sent, None


def test_a_query_embedding_is_reserved_then_sent_once():
    """An ordinary query reserves its estimate, sends one request and reports its usage."""
    sent: list[dict[str, Any]] = []
    budget = Reservation(Decimal("0.01"), 8)
    provider = capped(budget, sent)
    vector = asyncio.run(provider.embed_query("revenue"))
    assert len(vector) == 384 and [body["input"] for body in sent] == [["revenue"]]
    tokens = provider.count_input_tokens("revenue")
    assert budget.attempts == 1
    assert budget.reserved_usd == Decimal(tokens) * Decimal("0.13") / Decimal(1_000_000)
    assert provider.usage.requests == 1


def test_billed_embedding_usage_past_the_cap_blocks_the_next_query():
    """100,000 billed tokens ($0.013) under a $0.01 cap: the next query is never sent."""
    budget, sent, refused = embed_twice("0.01", (100_000,))
    assert refused is not None and len(sent) == 1
    assert budget.reserved_usd == Decimal("0.013")


def test_a_billed_excess_leaves_less_room_for_the_next_query():
    """Without the $0.0065 excess the second query would fit; with it, it is refused unsent."""
    budget, sent, refused = embed_twice(str(Decimal("0.0065") + EMBEDDING_TOKEN_USD / 2), (50_000,))
    assert refused is not None and len(sent) == 1
    assert budget.reserved_usd == Decimal("0.0065")


def test_a_billed_excess_that_still_fits_lets_the_next_query_run():
    """The excess is added and the next query is reserved and sent as usual."""
    budget, sent, refused = embed_twice("0.01", (50_000,))
    assert refused is None and len(sent) == 2
    tokens = capped(Reservation(Decimal(1), 1), []).count_input_tokens("revenue 2024")
    assert budget.reserved_usd == Decimal("0.0065") + tokens * EMBEDDING_TOKEN_USD


def test_an_exhausted_embedding_budget_is_not_a_correctable_tool_error():
    """Over the attempt count nothing is sent and the refusal is not a ToolError."""
    sent: list[dict[str, Any]] = []
    with pytest.raises(BudgetExhaustedError) as refused:
        asyncio.run(capped(Reservation(Decimal("0.01"), 0), sent).embed_query("revenue"))
    assert not isinstance(refused.value, ToolError)
    assert sent == []


@pytest.mark.parametrize(("attempts", "system_error"), [(8, False), (0, True)])
def test_a_search_over_the_embedding_cap_is_a_system_failure(
    tmp_path, monkeypatch, attempts, system_error
):
    """The registry reports a capped search as a system failure; an ordinary one succeeds."""

    async def retrieve(session: object, query: str, **kwargs: Any) -> SimpleNamespace:
        """Embed the query like retrieval does, then find nothing."""
        await kwargs["provider"].embed_query(query)
        return SimpleNamespace(hits=())

    monkeypatch.setattr(filings, "retrieve", retrieve)
    sent: list[dict[str, Any]] = []
    registry = build_default_registry(
        lambda: cast(AsyncSession, ControlledSession(tmp_path / "events.jsonl")),
        embedding_provider=capped(Reservation(Decimal("0.01"), attempts), sent),
    )
    outcome = asyncio.run(execute_tool(registry, "search_filings", {"query": "revenue"}))
    assert outcome.system_error is system_error
    if system_error:
        assert outcome.error == "BudgetExhaustedError: tool search_filings failed"
        assert sent == []
    else:
        assert (outcome.error, outcome.output, len(sent)) == (None, {"hits": []}, 1)


def test_the_openai_embedding_path_serves_a_capped_embedder(tmp_path, monkeypatch):
    """With OpenAI embeddings the server's registry embeds through the run's capped budget.

    The cell switch reaches this registry too.
    """
    settings = SimpleNamespace(
        environment="dev",
        embedding_provider="openai",
        embedding_model="text-embedding-3-large",
        openai_api_key=SecretStr(FAKE_KEY),
        openai_key_slot="dev",
    )
    monkeypatch.setattr(config, "get_settings", lambda: settings)
    providers: list[Any] = []

    def registry(sessions: object, **kwargs: Any) -> object:
        """Capture the embedding provider the server hands the registry."""
        providers.append((kwargs["embedding_provider"], kwargs["include_cells"]))
        return object()

    async def serve_stdio(registry: object) -> None:
        """Stand in for the stdio transport."""

    monkeypatch.setattr(filings, "build_default_registry", registry)
    monkeypatch.setattr(filings_server, "serve", serve_stdio)
    monkeypatch.setattr(live, "read_only_engine", FakeEngine)
    budget = Reservation(Decimal("0.01"), 8)
    asyncio.run(live.serve(tmp_path, budget, include_cells=True))
    [(provider, include_cells)] = providers
    assert isinstance(provider, CappedEmbedding) and provider.budget is budget
    assert include_cells is True
    assert journal(tmp_path / "budget.jsonl") == [("embedding", "reported")]


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

    async def require_indexed(issuer, years, **_):
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

    async def require_indexed(issuer, years, **_):
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


def ask_with_search(tmp_path: Path, search_filings: BaseTool) -> dict[str, Any]:
    """Ask once with ``search_filings`` as the only tool; the model calls it, then stops."""
    fake = FakeOpenAI(
        counts=[1000], replies=[response("search_fail", "search_filings", SEARCH, (900, 30))]
    )
    gate = ModelGate(
        Reservation(Decimal("0.09"), 2, journal=tmp_path / "budget.jsonl"), LUNA, 60_000
    )
    model = counted_model(LUNA, gate, api_key=FAKE_KEY, http_async_client=fake.client())
    agent = review_agent(model, [search_filings], contracts(), gate)
    return asyncio.run(ask_review_agent(agent, QUESTION, ReviewContext((2024,)), gate))


def test_trace_retains_tool_exception_without_private_details(tmp_path):
    """An unexpected tool exception ends the question and leaves a redacted dispatch failure."""

    @tool
    async def search_filings(query: str, issuers: list[str], fiscal_years: list[int]) -> str:
        """A test retrieval failure after actual tool dispatch."""
        raise RuntimeError("private database password=do-not-log")

    outcome = ask_with_search(tmp_path, search_filings)
    assert (outcome["status"], outcome["failure"]) == (
        "tool_error",
        "RuntimeError: agent run failed",
    )
    assert outcome["budget"]["attempts"] == 1
    assert "do-not-log" not in json.dumps(outcome)
    events = trace_events(tmp_path)
    failures = [e for e in events if e["event"] == "tool_error"]
    assert [e["layer"] for e in failures] == ["execution", "gate"]
    assert all(e["call_id"] == "search_fail" for e in failures)
    assert "do-not-log" not in (tmp_path / "trace.jsonl").read_text()


def test_a_tool_result_without_structured_content_still_reports_the_question(tmp_path):
    """A foreign tool's plain-text result makes the review raise; the run still reports."""

    @tool
    async def search_filings(query: str, issuers: list[str], fiscal_years: list[int]) -> str:
        """A search result with no structured content, as a foreign server may send."""
        return "TestCo revenue was 100 USD."

    outcome = ask_with_search(tmp_path, search_filings)
    assert (outcome["status"], outcome["answer"]) == ("tool_error", None)
    assert outcome["failure"] == "ValueError: tool search_filings evidence extraction failed"
    assert outcome["budget"]["reserved_usd"] == str(LUNA.reservation(1000))


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


def unfinished(output: list[dict[str, Any]], reason: str | None = None) -> dict[str, Any]:
    """A reply with ``output`` and no function call: incomplete for ``reason``, if given."""
    reply = response("call_none", "final_answer", FINAL, (900, 30))
    reply["output"] = output
    if reason is not None:
        reply |= {"status": "incomplete", "incomplete_details": {"reason": reason}}
    return reply


TEXT_ONLY = [
    {
        "type": "message",
        "id": "msg_1",
        "role": "assistant",
        "status": "completed",
        "content": [{"type": "output_text", "text": REVENUE, "annotations": []}],
    }
]


@pytest.mark.parametrize(
    ("reply", "status", "failure"),
    [
        (
            unfinished([], "max_output_tokens"),
            "budget_exceeded",
            "the output-token ceiling cut the provider turn off before it finished",
        ),
        (
            unfinished(TEXT_ONLY, "content_filter"),
            "provider_error",
            "the provider cut the turn off before it finished: content_filter",
        ),
        (
            unfinished(TEXT_ONLY),
            "no_answer",
            "the model ended its turn without a valid final_answer or tool call",
        ),
        (
            unfinished([]),
            "no_answer",
            "the model ended its turn without a valid final_answer or tool call",
        ),
    ],
    ids=["cut-off-by-ceiling", "cut-off-by-filter", "text-only", "empty"],
)
def test_a_turn_without_an_answer_reports_why(tmp_path, reply, status, failure):
    """A cut-off, filtered, text-only or empty turn ends with the loop's typed reason."""
    fake = FakeOpenAI(counts=[1000], replies=[reply])
    outcome, budget = ask_offline(tmp_path, fake)
    assert (outcome["status"], outcome["answer"], outcome["failure"]) == (status, None, failure)
    assert [path for path, _ in fake.requests] == [COUNT_PATH, RESPONSES_PATH]
    assert budget.reserved_usd == LUNA.reservation(1000)


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


def overrun(n: int, input_tokens: int) -> dict[str, Any]:
    """An uncited final answer whose reported input far exceeds the counted 1,000 tokens."""
    return response(f"call_{n}", "final_answer", FINAL, (input_tokens, 10))


def test_observed_usage_past_the_cap_is_spent_and_stops_the_next_turn(tmp_path):
    """$0.100012 observed against $0.0051652 reserved under $0.09: no further count or send."""
    fake = FakeOpenAI(counts=[1000, 1000], replies=[overrun(1, 500_000), uncited(2)])
    outcome, budget = ask_offline(tmp_path, fake, attempts=2)
    assert (outcome["status"], outcome["failure"]) == (
        "budget_exceeded",
        "observed model usage passed the approved cap",
    )
    assert [path for path, _ in fake.requests] == [COUNT_PATH, RESPONSES_PATH]
    # 500,000 input at $0.20/M plus 10 output at $1.20/M; reserved 1,000 at $0.25/M + 4,096 out.
    assert budget.reserved_usd == Decimal("0.100012")
    event = outcome["budget"]["observed"][0]
    assert Decimal(event["overrun_usd"]) == Decimal("0.100012") - LUNA.reservation(1000)
    assert outcome["budget"]["over_cap"] is True
    assert journal(tmp_path / "budget.jsonl")[-1] == ("model", "blocked")


def test_an_observed_excess_shrinks_the_room_for_later_turns(tmp_path):
    """After an excess, the next turn is counted, no longer fits under the cap, and is not sent."""
    fake = FakeOpenAI(counts=[1000, 1000], replies=[overrun(1, 30_000), absent_response()])
    cap = LUNA.reservation(1000) * 2
    outcome, budget = ask_offline(tmp_path, fake, cap=str(cap))
    assert outcome["status"] == "budget_exceeded"
    assert [path for path, _ in fake.requests] == [COUNT_PATH, RESPONSES_PATH, COUNT_PATH]
    assert budget.reserved_usd == Decimal("0.006012")
    assert outcome["budget"]["over_cap"] is False


def test_an_excess_that_still_fits_lets_the_question_finish(tmp_path):
    """The excess is added to the reservations and the next turn still runs to its answer."""
    fake = FakeOpenAI(counts=[1000, 1000], replies=[overrun(1, 30_000), absent_response()])
    outcome, budget = ask_offline(tmp_path, fake)
    assert outcome["status"] == "ok"
    assert budget.reserved_usd == Decimal("0.006012") + LUNA.reservation(1000)
    assert [e.get("overrun_usd") for e in outcome["budget"]["observed"]] == [
        str(Decimal("0.006012") - LUNA.reservation(1000)),
        None,
    ]


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


# The create-agent run as the script assembles it: cell format, cell gate, cell server
# AMD's manifest alias is "AMD"; without the issuer's names it qualifies "net revenue".
CELL_QUESTION = "What was AMD's net revenue in 2024?"
SELECTION = {
    "contract_version": "cell-v1",
    "label": "SUPPORTED",
    "reason": "selected",
    "selections": [
        {"cell_id": "2024:r1c1", "claimed_item": "revenue", "claimed_fiscal_year": 2024}
    ],
    "unresolved_chunk_ids": [],
}


def run_cell_question(
    tmp_path: Path,
    monkeypatch,
    replies: list[dict[str, Any]],
    server: Any = None,
    question: str = CELL_QUESTION,
    issuer: str | None = "AMD",
) -> SimpleNamespace:
    """Run ``run_review_agent_over_mcp`` over the cell server and the offline endpoint.

    Only the database is replaced: the engine is never queried and the stored-cell
    re-read returns the cell the server served. ``server`` replaces the cell server.
    The issuer's names come from the repository manifest, as ``run`` reads them.
    """
    fake = FakeOpenAI(counts=[1000, 1200, 1400][: len(replies)], replies=replies)
    monkeypatch.setattr(
        config,
        "get_settings",
        lambda: SimpleNamespace(environment="dev", openai_api_key=SecretStr(FAKE_KEY)),
    )
    contexts: list[ReviewContext] = []
    ask = live.ask_review_agent

    async def ask_keeping_context(agent: Any, question: str, context: ReviewContext, gate: Any):
        """Ask as the script does, keeping the review context the gate receives."""
        contexts.append(context)
        return await ask(agent, question, context, gate)

    monkeypatch.setattr(live, "ask_review_agent", ask_keeping_context)
    monkeypatch.setattr(live, "read_only_engine", FakeEngine)
    monkeypatch.setattr(
        live, "counted_model", partial(counted_model, http_async_client=fake.client())
    )
    reads: list[tuple[str, ...]] = []

    async def read_selected_cells(sessions: object, refs: tuple[str, ...]) -> dict[str, Any]:
        """Return each selected cell as the server stored it."""
        reads.append(refs)
        return {
            ref: StoredCell(ref, 2024, REVENUE_CELL, STABLE_KEY, RESOLVER_IDENTITY, Decimal(25785))
            for ref in refs
        }

    monkeypatch.setattr(stored_evidence, "read_selected_cells", read_selected_cells)
    log = tmp_path / "events.jsonl"
    log.touch()
    if server is None:
        server = module_server(
            "tests.scripts.mcp.cell_filings", str(log), env={"PYTHONPATH": str(REPO_ROOT)}
        )
    argv = ["r", "agent", "--issuer", "AMD", "--years", "2024", "--question", question]
    args = parser().parse_args([*argv, "--via", "create-agent", "--model-attempts", "3"])
    args.issuer = issuer
    settings = live.agent_model_settings(args)
    assert settings is not None
    names = issuer_names(args.issuer, CORPUS_DIR)
    outcome = asyncio.run(
        live.run_review_agent_over_mcp(server, tmp_path, args, settings, names=names)
    )
    return SimpleNamespace(outcome=outcome, fake=fake, reads=reads, log=log, contexts=contexts)


def test_the_script_answers_a_cell_question_end_to_end(tmp_path, monkeypatch):
    """Search, fetch with cells, select a cell: three counted turns end on the written answer.

    Dropping the cell format, the cell-mode review context or the cell server breaks it.
    """
    asked = run_cell_question(
        tmp_path,
        monkeypatch,
        [
            response("call_search", "search_filings", SEARCH, (990, 40)),
            response("call_fetch", "fetch_chunk", {"chunk_id": 2024}, (1190, 40)),
            response("call_final", "final_answer", SELECTION, (1390, 60)),
        ],
    )
    outcome = asked.outcome
    assert (outcome["status"], outcome["failure"]) == ("ok", None)
    assert outcome["answer"]["label"] == "SUPPORTED"
    assert "25,785" in outcome["answer"]["answer"]
    assert [c["chunk_id"] for c in outcome["answer"]["citations"]] == [2024]
    assert asked.reads == [("2024:r1c1",)]
    assert outcome["budget"]["attempts"] == 3
    assert [c.requested_items for c in asked.contexts] == [frozenset({"revenue"})]
    final = next(
        t for t in asked.fake.bodies(COUNT_PATH)[0]["tools"] if t["name"] == "final_answer"
    )
    assert "contract_version" in final["parameters"]["properties"]
    assert "2024:r1c1" in json.dumps(asked.fake.bodies(COUNT_PATH)[2]["input"])
    events = [e["event"] for e in logged_events(asked.log)]
    assert events[:2] == ["retrieval", "body_load"]


def test_a_written_final_answer_is_refused_on_the_cell_path(tmp_path, monkeypatch):
    """The script offers only the cell-selecting answer; a written one is returned unaccepted."""
    asked = run_cell_question(
        tmp_path,
        monkeypatch,
        [
            response("call_search", "search_filings", SEARCH, (990, 40)),
            response("call_fetch", "fetch_chunk", {"chunk_id": 2024}, (1190, 40)),
            response("call_final", "final_answer", FINAL, (1390, 60)),
        ],
    )
    assert (asked.outcome["status"], asked.outcome["answer"]) == ("budget_exceeded", None)
    assert asked.reads == []


def test_the_agent_run_starts_its_server_with_cells(tmp_path, monkeypatch):
    """run() passes --include-cells to the serve subprocess, which serves fetched cells."""
    servers: list[Any] = []

    async def run_review_agent_over_mcp(server, run_dir, args, settings, *, names) -> dict:
        """Capture the server the agent would start and the issuer names it would use."""
        servers.append(server)
        assert {"AMD", "ADVANCED MICRO DEVICES INC"} <= set(names)
        return {"status": "ok"}

    async def require_indexed(issuer, years, **_) -> None:
        """Stand in for the database index check."""

    monkeypatch.setattr(config, "get_settings", keyed_settings)
    monkeypatch.setattr(live, "require_indexed", require_indexed)
    monkeypatch.setattr(live, "run_review_agent_over_mcp", run_review_agent_over_mcp)
    argv = ["r", "--out", str(tmp_path), *AGENT_ARGV[1:], "--via", "create-agent"]
    asyncio.run(live.run(parser().parse_args(argv)))
    assert json.loads((tmp_path / "r" / "result.json").read_text()) == {"agent": {"status": "ok"}}
    registries, _ = serve_offline(monkeypatch, include_cells=True)
    assert registries[0].get("fetch_chunk").output is FetchedChunk
    started: list[bool] = []

    async def serve(run_dir, budget, *, include_cells=False) -> None:
        """Capture what the subprocess's command line asks serve for."""
        started.append(include_cells)

    monkeypatch.setattr(live, "serve", serve)
    assert servers[0].args[:2] == ["-m", "scripts.mcp.live"]
    live.main(servers[0].args[2:])
    assert started == [True]


# Every ending of a claimed run leaves a result
FAILING_SERVER = SimpleNamespace(
    command=sys.executable, args=["-c", "import sys; sys.exit(3)"], env=None
)


def test_a_server_that_fails_to_start_is_reported_without_a_model_turn(tmp_path, monkeypatch):
    """A server that exits at once ends the question as setup_error before any count."""
    asked = run_cell_question(tmp_path, monkeypatch, [], server=FAILING_SERVER)
    assert (asked.outcome["status"], asked.outcome["answer"]) == ("setup_error", None)
    assert asked.outcome["failure"].endswith(": server start failed")
    assert asked.fake.requests == [] and asked.outcome["budget"]["attempts"] == 0


@pytest.mark.parametrize(
    ("target", "attribute", "stage"),
    [(MCPAdapter, "list_tools", "tool listing"), (live, "review_agent", "agent build")],
    ids=["tool-listing", "agent-build"],
)
def test_a_setup_failure_after_the_server_started_is_reported(
    tmp_path, monkeypatch, target, attribute, stage
):
    """A tool-listing or agent-build failure is setup_error naming only its type and stage."""

    def fail(*_: object, **__: object) -> Any:
        raise RuntimeError(f"private detail {FAKE_KEY}")

    async def fail_async(*_: object, **__: object) -> Any:
        fail()

    monkeypatch.setattr(target, attribute, fail_async if attribute == "list_tools" else fail)
    asked = run_cell_question(tmp_path, monkeypatch, [])
    assert (asked.outcome["status"], asked.outcome["failure"]) == (
        "setup_error",
        f"RuntimeError: {stage} failed",
    )
    assert FAKE_KEY not in json.dumps(asked.outcome) and asked.fake.requests == []


class FakeClient:
    """Stands in for the MCP client of ``run``; fails where the test chooses."""

    start_error: BaseException | None = None
    call_error: BaseException | None = None
    stop_error: BaseException | None = None

    def __init__(self, server: object, **_: object) -> None:
        self.server = server

    async def __aenter__(self) -> FakeClient:
        """Start, or fail to start, the server."""
        if self.start_error is not None:
            raise self.start_error
        return self

    async def __aexit__(self, *_: object) -> None:
        """Stop the server, or fail to."""
        if self.stop_error is not None:
            raise self.stop_error

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> SimpleNamespace:
        """Return an empty search result, or fail."""
        if self.call_error is not None:
            raise self.call_error
        return SimpleNamespace(
            is_error=False, structured_content=None, model_dump=lambda **_: {"hits": []}
        )


SEARCH_ARGV = ["r", "search", "--issuer", "AMD", "--year", "2024", "--query", "revenue"]


def run_claimed(tmp_path: Path, monkeypatch, argv: list[str], **client: Any) -> Path:
    """Run ``run`` offline with a fake MCP client; return its run directory."""

    async def require_indexed(issuer, years, **_) -> None:
        """Stand in for the database index check."""

    monkeypatch.setattr(config, "get_settings", keyed_settings)
    monkeypatch.setattr(live, "require_indexed", require_indexed)
    monkeypatch.setattr(mcp, "Client", type("Client", (FakeClient,), client))
    asyncio.run(live.run(parser().parse_args([argv[0], "--out", str(tmp_path), *argv[1:]])))
    return tmp_path / argv[0]


def result_of(run_dir: Path) -> dict[str, Any]:
    """Read a run's result file."""
    return json.loads((run_dir / "result.json").read_text())


def test_an_ordinary_tool_run_records_its_result(tmp_path, monkeypatch):
    """A search that succeeds writes its normal record, without a status or failure."""
    run_dir = run_claimed(tmp_path, monkeypatch, SEARCH_ARGV)
    assert result_of(run_dir)["result"] == {"hits": []}
    assert "failure" not in result_of(run_dir)


def test_a_server_stop_failure_keeps_the_finished_tool_result(tmp_path, monkeypatch):
    """The search result is kept and the stop failure added beside it."""
    run_dir = run_claimed(tmp_path, monkeypatch, SEARCH_ARGV, stop_error=RuntimeError(FAKE_KEY))
    record = result_of(run_dir)
    assert record["result"] == {"hits": []}
    assert record["server_stop_failure"] == "RuntimeError: server stop failed"


def test_a_server_stop_failure_keeps_the_answered_cell_question(tmp_path, monkeypatch):
    """A question answered before its server failed to stop still reports ok."""
    stop, ask = MCPAdapter.__aexit__, live.ask_review_agent
    answered: list[dict[str, Any]] = []

    async def asked_once(*args: Any) -> dict[str, Any]:
        answered.append(await ask(*args))
        return answered[-1]

    async def failing_stop(self: MCPAdapter, *exc: Any) -> Any:
        await stop(self, *exc)
        if answered:  # the adapter also exits inner sessions while listing tools
            raise RuntimeError(FAKE_KEY)

    monkeypatch.setattr(live, "ask_review_agent", asked_once)
    monkeypatch.setattr(MCPAdapter, "__aexit__", failing_stop)
    asked = run_cell_question(
        tmp_path,
        monkeypatch,
        [
            response("call_search", "search_filings", SEARCH, (990, 40)),
            response("call_fetch", "fetch_chunk", {"chunk_id": 2024}, (1190, 40)),
            response("call_final", "final_answer", SELECTION, (1390, 60)),
        ],
    )
    assert asked.outcome["status"] == "ok"
    assert asked.outcome["server_stop_failure"] == "RuntimeError: server stop failed"


@pytest.mark.parametrize(
    ("argv", "client", "stage"),
    [
        (SEARCH_ARGV, {"start_error": RuntimeError(FAKE_KEY)}, "server start"),
        (SEARCH_ARGV, {"call_error": RuntimeError(FAKE_KEY)}, "tool call"),
        (AGENT_ARGV, {"start_error": RuntimeError(FAKE_KEY)}, "server start"),
    ],
    ids=["tool-server-start", "tool-call", "run-agent-server-start"],
)
def test_a_failed_claimed_run_records_how_it_ended(tmp_path, monkeypatch, argv, client, stage):
    """The exception propagates after result.json names its type and stage, nothing else."""
    with pytest.raises(RuntimeError):
        run_claimed(tmp_path, monkeypatch, argv, **client)
    record = result_of(tmp_path / "r")
    ending = record if "tool" in record else record["agent"]
    assert (ending["status"], ending["failure"]) == ("error", f"RuntimeError: {stage} failed")
    assert FAKE_KEY not in json.dumps(record)


@pytest.mark.parametrize(
    ("raised", "status", "failure"),
    [
        (RuntimeError(FAKE_KEY), "error", "RuntimeError: agent run failed"),
        (asyncio.CancelledError(), "interrupted", "CancelledError: agent run interrupted"),
    ],
    ids=["error", "cancelled"],
)
def test_a_create_agent_run_that_raises_still_records_and_keeps_its_marker(
    tmp_path, monkeypatch, raised, status, failure
):
    """An escaped error or cancellation is recorded, re-raised, and the run ID stays used."""

    async def run_review_agent_over_mcp(*_: object, **__: object) -> dict[str, Any]:
        raise raised

    monkeypatch.setattr(live, "run_review_agent_over_mcp", run_review_agent_over_mcp)
    argv = [*AGENT_ARGV, "--via", "create-agent"]
    with pytest.raises(type(raised)):
        run_claimed(tmp_path, monkeypatch, argv)
    assert result_of(tmp_path / "r")["agent"] == {
        "via": "create-agent",
        "answer": None,
        "status": status,
        "failure": failure,
    }
    with pytest.raises(SystemExit, match="already attempted"):
        run_claimed(tmp_path, monkeypatch, argv)


def test_an_agent_run_without_a_key_stops_before_claiming(tmp_path, monkeypatch):
    """A missing key slot is found before the attempt marker, so the run ID stays free."""
    run_claimed_args = ["r", "--out", str(tmp_path), *AGENT_ARGV[1:]]

    async def require_indexed(issuer, years, **_) -> None:
        """Stand in for the database index check."""

    monkeypatch.setattr(live, "require_indexed", require_indexed)
    with pytest.raises(SystemExit, match="OpenAI key slot"):
        asyncio.run(live.run(parser().parse_args(run_claimed_args)))
    assert not (tmp_path / "r").exists()


# The issuer's names reach the question's item reading
THREE_TURNS = [
    response("call_search", "search_filings", SEARCH, (990, 40)),
    response("call_fetch", "fetch_chunk", {"chunk_id": 2024}, (1190, 40)),
    response("call_final", "final_answer", SELECTION, (1390, 60)),
]


@pytest.mark.parametrize(
    ("question", "issuer", "items"),
    [
        ("What was AMD's Data Center revenue in 2024?", "AMD", frozenset()),
        (CELL_QUESTION, None, frozenset()),
    ],
    ids=["qualified-item", "no-issuer-filter"],
)
def test_a_qualifier_or_a_missing_filter_names_no_item(
    tmp_path, monkeypatch, question, issuer, items
):
    """A qualified item stays unread, and without a filter the company name qualifies it."""
    asked = run_cell_question(tmp_path, monkeypatch, THREE_TURNS, question=question, issuer=issuer)
    assert [c.requested_items for c in asked.contexts] == [items]


@pytest.mark.parametrize(
    ("write", "message"),
    [(None, "could not be read"), ("{}", "could not be read"), ("same", "not an issuer")],
    ids=["missing", "invalid", "unlisted-issuer"],
)
def test_an_unusable_manifest_stops_the_cell_run_before_claiming(
    tmp_path, monkeypatch, write, message
):
    """A missing, invalid or issuer-less manifest stops the run before its attempt marker."""
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    if write == "same":
        (corpus / "manifest.json").write_text((CORPUS_DIR / "manifest.json").read_text())
    elif write is not None:
        (corpus / "manifest.json").write_text(write)
    monkeypatch.setattr(
        config,
        "get_settings",
        lambda: SimpleNamespace(**vars(keyed_settings()) | {"corpus_dir": corpus}),
    )

    async def require_indexed(issuer, years, **_) -> None:
        """Stand in for the database index check."""

    monkeypatch.setattr(live, "require_indexed", require_indexed)
    issuer = "TESTCO" if write == "same" else "AMD"
    argv = ["r", "--out", str(tmp_path), "agent", "--issuer", issuer, "--years", "2024"]
    args = parser().parse_args([*argv, "--question", "Q?", "--via", "create-agent"])
    with pytest.raises(SystemExit, match=message):
        asyncio.run(live.run(args))
    assert not (tmp_path / "r").exists()


@pytest.mark.parametrize(
    ("argv", "current_tables"),
    [
        (SEARCH_ARGV, False),
        (["r", "compare", "--issuer", "AMD", "--years", "2023", "2024", "--query", "q"], False),
        (AGENT_ARGV, True),
        ([*AGENT_ARGV, "--via", "create-agent"], True),
    ],
    ids=["search", "compare", "run-agent", "create-agent"],
)
def test_only_agent_runs_require_current_stored_tables(tmp_path, monkeypatch, argv, current_tables):
    """Both agent paths judge figures from stored tables; single tool calls do not."""
    checked: list[bool] = []

    async def require_indexed(issuer, years, *, current_tables=False) -> None:
        checked.append(current_tables)
        raise SystemExit("checked")

    monkeypatch.setattr(config, "get_settings", keyed_settings)
    monkeypatch.setattr(live, "require_indexed", require_indexed)
    with pytest.raises(SystemExit, match="checked"):
        asyncio.run(live.run(parser().parse_args([argv[0], "--out", str(tmp_path), *argv[1:]])))
    assert checked == [current_tables]


# The read-only database boundary, on a disposable PostgreSQL database
def use_database(monkeypatch, url: str) -> None:
    """Point the scripts' settings at ``url`` without reading any environment file."""
    settings = SimpleNamespace(**vars(keyed_settings()) | {"database_url": url})
    settings.embedding_model = EMBEDDING_MODEL
    monkeypatch.setattr(config, "get_settings", lambda: settings)


async def write(url: str, statement: Any) -> None:
    """Run one write with a writable engine, as ingestion would."""
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await connection.execute(statement)
    finally:
        await engine.dispose()


@pytest.mark.live_postgres
def test_the_read_only_engine_reads_but_refuses_writes(monkeypatch):
    """A SELECT succeeds; creating a table fails as a read-only transaction."""

    async def scenario() -> None:
        """Read, then try to write, through the script's engine."""
        async with seeded_database(["AMD-FY2024"]) as url:
            use_database(monkeypatch, url)
            engine = live.read_only_engine()
            try:
                async with engine.connect() as connection:
                    assert await connection.scalar(text("SELECT count(*) FROM chunks")) > 0
                async with engine.connect() as connection:
                    with pytest.raises(DBAPIError, match="read-only transaction"):
                        await connection.execute(text("CREATE TABLE written (i int)"))
            finally:
                await engine.dispose()

    asyncio.run(scenario())


@pytest.mark.live_postgres
def test_require_indexed_checks_embeddings_and_current_tables(monkeypatch):
    """An embedded current year passes; a locally embedded or stale one stops the run."""

    async def scenario() -> None:
        """Check both years, then mark 2024's table as read by older code."""
        filings = ["AMD-FY2023", "AMD-FY2024"]
        async with seeded_database(filings, ["AMD-FY2024"], local=["AMD-FY2023"]) as url:
            use_database(monkeypatch, url)
            await live.require_indexed("AMD", [2024])
            await live.require_indexed("AMD", [2024], current_tables=True)
            with pytest.raises(SystemExit, match=r"no matching indexed chunks for \[2023\]"):
                await live.require_indexed("AMD", [2023, 2024])
            await write(
                url,
                update(ParsedTable)
                .where(ParsedTable.doc_id == "AMD-FY2024")
                .values(resolver_identity="0" * 64),
            )
            await live.require_indexed("AMD", [2024])
            with pytest.raises(SystemExit, match=r"\[2024\] built or read by other code"):
                await live.require_indexed("AMD", [2024], current_tables=True)

    asyncio.run(scenario())


@pytest.mark.live_postgres
def test_fetch_matches_database_compares_the_whole_stored_row(monkeypatch):
    """The stored row as served matches; one changed field does not."""

    async def scenario() -> None:
        """Compare the stored row, then a changed copy of it."""
        async with seeded_database(["AMD-FY2024"]) as url:
            use_database(monkeypatch, url)
            engine = create_async_engine(url, poolclass=NullPool)
            try:
                async with engine.connect() as connection:
                    chunk = (
                        await connection.execute(select(Chunk).order_by(Chunk.id).limit(1))
                    ).one()
            finally:
                await engine.dispose()
            payload = {
                "chunk_id": chunk.id,
                "doc_id": chunk.doc_id,
                "citation": chunk.citation,
                "start_char": chunk.start_char,
                "end_char": chunk.end_char,
                "source_sha256": chunk.source_sha256,
                "context_header": chunk.context_header,
                "body": chunk.body,
            }
            assert await live.fetch_matches_database(payload) is True
            assert await live.fetch_matches_database(payload | {"body": "changed"}) is False

    asyncio.run(scenario())
