"""Budget, attempt and argument rules of the live MCP experiment runner."""

from decimal import Decimal
import json

import pytest

from scripts.mcp.live import (
    BudgetExhaustedError,
    Reservation,
    claim_attempt,
    parser,
    tool_request,
)


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
        (["r", "agent", "--question", "Q?"], None),
    ],
)
def test_commands_map_to_one_tool_call_or_the_agent(argv, expected):
    """Single-call commands become their MCP tool request; agent has none."""
    assert tool_request(parser().parse_args(argv)) == expected
