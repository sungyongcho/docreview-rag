"""Budget, attempt and argument rules of the live MCP experiment runner."""

import asyncio
from decimal import Decimal
import json

import pytest

from scripts.mcp import live
from scripts.mcp.live import (
    BudgetExhaustedError,
    Reservation,
    claim_attempt,
    parser,
    tool_request,
)

AGENT_ARGV = ["r", "agent", "--issuer", "AMD", "--years", "2023", "2024", "--question", "Q?"]


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
