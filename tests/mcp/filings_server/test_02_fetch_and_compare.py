"""Section 4.3: chunk reading and year comparison keep source identity and error kinds."""

import asyncio
import hashlib

from mcp import Client
import pytest

from app.agent.tools.filings import CompareYearsParams
from tests.mcp.controlled_filings import FAILING_CHUNK_ID, PRIVATE_DETAIL, fixture_hit
from tests.mcp.support import (
    PROTOCOL_MODE,
    assert_internal_error,
    call_or_error,
    controlled_filings,
    logged_events,
    text_of,
)

BASE = {"query": "revenue", "issuer": "TEST", "fiscal_years": [2024, 2023]}
# (case, arguments, failed, system failure, years retrieved)
COMPARE_CASES = [
    ("both-years", BASE, False, False, [2023, 2024]),
    ("empty-2024", {**BASE, "query": "empty-2024"}, False, False, [2023, 2024]),
    ("both-empty", {**BASE, "query": "both-empty"}, False, False, [2023, 2024]),
    (
        "second-year-failure",
        {**BASE, "query": "fail-2024", "fiscal_years": [2023, 2024, 2025]},
        True,
        True,
        [2023, 2024],
    ),
    ("blank-query", {**BASE, "query": " "}, True, False, []),
    ("zero-k", {**BASE, "k": 0}, True, False, []),
    ("duplicate-year", {**BASE, "fiscal_years": [2023, 2023]}, True, False, []),
    ("one-year", {**BASE, "fiscal_years": [2023]}, True, False, []),
    ("missing-issuer", {"query": "revenue", "fiscal_years": [2023, 2024]}, True, False, []),
    ("after-error", {**BASE, "k": 2}, False, False, [2023, 2024]),
]
# (case, chunk id, failed, system failure)
FETCH_CASES = [
    ("existing", 2024, False, False),
    ("unknown", 99, True, False),
    ("database-failure", FAILING_CHUNK_ID, True, True),
    ("not-an-id", 0, True, False),
    ("after-failure", 2023, False, False),
]


@pytest.fixture(scope="module")
def observed(tmp_path_factory):
    """Run every comparison and read on one connection with their data-layer events."""
    log_path = tmp_path_factory.mktemp("compare") / "events.jsonl"

    async def call_all(client, name, cases, arguments_of):
        """Call ``name`` once per case, keeping its result or JSON-RPC error and its events."""
        results = {}
        for case in cases:
            start = len(logged_events(log_path))
            outcome = await call_or_error(client, name, arguments_of(case))
            results[case[0]] = (*outcome, logged_events(log_path, start))
        return results

    async def exercise():
        async with Client(controlled_filings(log_path), mode=PROTOCOL_MODE) as client:
            listing = await client.list_tools()
            compare = await call_all(client, "compare_years", COMPARE_CASES, lambda c: c[1])
            fetch = await call_all(client, "fetch_chunk", FETCH_CASES, lambda c: {"chunk_id": c[1]})
        return listing, compare, fetch

    return asyncio.run(exercise())


def test_compare_schema_is_the_existing_model(observed):
    """compare_years publishes the registry's input model."""
    listing, _, _ = observed
    tools = {tool.name: tool for tool in listing.tools}
    assert tools["compare_years"].input_schema == CompareYearsParams.model_json_schema()
    assert "does not extract revenue values" in tools["compare_years"].description


@pytest.mark.parametrize(("case", "arguments", "failed", "system", "years"), COMPARE_CASES)
def test_compare_groups_years_or_fails_whole(observed, case, arguments, failed, system, years):
    """Years are retrieved in order; any failure returns no partial years."""
    _, results, _ = observed
    result, error, events = results[case]
    assert [event["filters"]["fiscal_years"][0] for event in events] == years
    assert all(event["k"] == arguments.get("k", 3) for event in events)
    if system:
        # A JSON-RPC error carries no result, so 2023's retrieved hits cannot leak out.
        assert result is None
        assert_internal_error(error, "compare_years")
        assert PRIVATE_DETAIL not in str(error)
        assert "TEST-2023" not in str(error)
        return
    assert error is None
    assert result.is_error == failed
    text = text_of(result)
    if failed:
        assert result.structured_content is None
        assert PRIVATE_DETAIL not in text
        assert "TEST-2023" not in text
        return
    output = result.structured_content
    assert output["issuer"] == "TEST"
    assert [row["fiscal_year"] for row in output["years"]] == [2023, 2024]
    for row in output["years"]:
        empty = case == "both-empty" or (case == "empty-2024" and row["fiscal_year"] == 2024)
        assert [hit["chunk_id"] for hit in row["hits"]] == ([] if empty else [row["fiscal_year"]])


@pytest.mark.parametrize(("case", "chunk_id", "failed", "system"), FETCH_CASES)
def test_fetch_returns_full_identity_or_a_typed_failure(observed, case, chunk_id, failed, system):
    """A stored chunk returns its hash and span; failures say whether to retry."""
    _, _, results = observed
    result, error, events = results[case]
    assert len(events) == (0 if case == "not-an-id" else 1)
    if system:
        assert result is None
        assert_internal_error(error, "fetch_chunk")
        assert PRIVATE_DETAIL not in str(error)
        return
    assert error is None
    assert result.is_error == failed
    if failed:
        assert PRIVATE_DETAIL not in text_of(result)
        return
    hit = fixture_hit(chunk_id)
    assert result.structured_content == {
        "chunk_id": chunk_id,
        "doc_id": hit.doc_id,
        "citation": hit.citation,
        "start_char": 0,
        "end_char": len(hit.body),
        "source_sha256": hashlib.sha256(hit.body.encode()).hexdigest(),
        "context_header": "",
        "body": hit.body,
    }
