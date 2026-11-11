"""A create_agent run that answers by selecting stored table cells."""

import asyncio
from decimal import Decimal
import json
from typing import Any, Literal, cast

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import StructuredTool, ToolException
import pytest

from app.agent.cell_answers import StoredCell
from app.agent.review_middleware import (
    ReviewContext,
    ReviewGate,
    StopOnSystemFailure,
    final_answer_format,
)
from app.agent.tools.filings import build_default_registry
from app.db.session_factory import SessionFactory
from tests.agent.support import ScriptedChatModel

USAGE = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
IDENTITY = {
    "chunk_id": 2024,
    "doc_id": "TESTCO-FY2024",
    "citation": "TestCo FY2024 · Item 8",
    "start_char": 0,
    "end_char": 120,
    "source_sha256": "a" * 64,
}
REVENUE = {
    "ref": "2024:r1c1",
    "row_label": "Net revenue",
    "column_header": "2024",
    "raw_text": "$ 25,785",
    "item": "revenue",
    "fiscal_years": [2024],
    "scale": "1000000",
    "currency": "USD",
    "percent": False,
    "status": "known",
    "complete": True,
}
SEARCH = {"query": "revenue", "k": None, "issuers": ["TEST"], "fiscal_years": [2024], "forms": None}


def catalog(cell: dict[str, Any]) -> dict[str, Any]:
    """Return chunk 2024's stored table with one cell."""
    return {
        "status": "available",
        "stable_key": "k" * 64,
        "resolver_identity": "r" * 64,
        "unit": {"status": "known", "scale": "1000000", "currency": ["USD"]},
        "cells": [cell],
    }


def tools(
    cell: dict[str, Any], search: Literal["hit", "none", "fail"] = "hit"
) -> list[StructuredTool]:
    """Stand-ins for the MCP tools that return structured content like the adapter does.

    ``search`` makes the search return chunk 2024, no hits, or a tool error.
    """

    def search_filings(**_: Any) -> tuple[str, dict[str, Any]]:
        """Return chunk 2024 as the one hit, no hits, or fail."""
        if search == "fail":
            raise ToolException("search failed")
        hits = [{**IDENTITY, "score": 1.0, "snippet": "Net revenue"}] if search == "hit" else []
        payload = {"hits": hits}
        return json.dumps(payload), {"structured_content": payload}

    def fetch_chunk(chunk_id: int) -> tuple[str, dict[str, Any]]:
        """Return chunk 2024 with its stored cells."""
        assert chunk_id == 2024
        payload = {**IDENTITY, "context_header": "", "body": "| x |", "table": catalog(cell)}
        return json.dumps(payload), {"structured_content": payload}

    contracts = build_default_registry(cast(SessionFactory, object), include_cells=True)
    return [
        StructuredTool.from_function(
            function,
            name=name,
            description=contracts.get(name).description,
            args_schema=contracts.get(name).parameters,
            response_format="content_and_artifact",
            handle_tool_error=True,
        )
        for name, function in (("search_filings", search_filings), ("fetch_chunk", fetch_chunk))
    ]


def reply(call_id: str, name: str, args: dict[str, Any]) -> AIMessage:
    """One scripted model turn with one tool call."""
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}],
        usage_metadata=USAGE,
    )


def selection(item: str = "revenue", year: int = 2024) -> dict[str, Any]:
    """The model's cell-selecting final answer for chunk 2024's cell."""
    return {
        "contract_version": "cell-v1",
        "label": "SUPPORTED",
        "reason": "selected",
        "selections": [{"cell_id": "2024:r1c1", "claimed_item": item, "claimed_fiscal_year": year}],
        "unresolved_chunk_ids": [],
    }


def ask(
    finals: list[dict[str, Any]],
    *,
    cell: dict[str, Any] = REVENUE,
    stored: dict[str, Any] | None = None,
    locale: Literal["en", "ko"] = "en",
    reads: list[tuple[str, ...]] | None = None,
    replies: list[AIMessage] | None = None,
    reader_configured: bool = True,
    search: Literal["hit", "none", "fail"] = "hit",
):
    """Search, fetch, then answer with each final in turn; return the state and model.

    ``reads`` collects the refs of every stored-cell read; ``replies`` replaces the
    whole scripted conversation; ``reader_configured`` False leaves out the reader;
    ``search`` is passed to :func:`tools`.
    """
    model = ScriptedChatModel.from_replies(
        *(
            replies
            if replies is not None
            else (
                reply("call_search", "search_filings", SEARCH),
                reply("call_fetch", "fetch_chunk", {"chunk_id": 2024}),
                *(
                    reply(f"call_final_{n}", "final_answer", final)
                    for n, final in enumerate(finals)
                ),
            )
        )
    )
    current = stored if stored is not None else cell

    async def reader(refs: tuple[str, ...]) -> dict[str, StoredCell]:
        """Return the selected cells as stored now."""
        if reads is not None:
            reads.append(refs)
        return {
            ref: StoredCell(ref, 2024, current, "k" * 64, "r" * 64, Decimal(25785)) for ref in refs
        }

    contracts = build_default_registry(cast(SessionFactory, object), include_cells=True)
    middleware: list[AgentMiddleware[Any, Any]] = [StopOnSystemFailure(), ReviewGate(contracts)]
    agent = create_agent(
        model,
        tools(cell, search),
        middleware=middleware,
        response_format=final_answer_format(cells=True),
        context_schema=ReviewContext,
    )
    context = ReviewContext(
        (2024,),
        cell_answers=True,
        requested_items=frozenset({"revenue"}),
        locale=locale,
        cell_reader=reader if reader_configured else None,
    )
    state = asyncio.run(
        agent.ainvoke({"messages": [HumanMessage("TestCo FY2024 revenue?")]}, context=context)
    )
    return state, model


def test_a_selected_cell_becomes_an_answer_the_application_wrote():
    """Search, fetch and select in three requests; the report states the stored value."""
    state, model = ask([selection()])
    report = state["structured_response"]
    assert len(model.requests) == 3
    assert report.label == "SUPPORTED"
    assert report.answer == "FY2024 Net revenue: 25,785 million USD."
    assert state["cell_checks"][0]["decision"] == "accepted"
    assert "2024:r1c1" in state["cells"]


def test_the_korean_answer_is_written_from_the_same_cell():
    """Write the Korean sentence from the same stored value and labels."""
    state, _ = ask([selection()], locale="ko")
    assert state["structured_response"].answer == "2024 회계연도 매출: 25,785 백만 USD."


def test_a_wrong_claim_is_returned_and_the_corrected_selection_accepted():
    """Answer the wrong claim under its call id, then accept the corrected selection."""
    state, model = ask([selection(item="net income"), selection()])
    errors = [
        m.content for m in state["messages"] if isinstance(m, ToolMessage) and m.status == "error"
    ]
    assert errors == ["ERROR: cell 2024:r1c1 is revenue, not net income"]
    assert len(model.requests) == 4
    assert state["structured_response"].label == "SUPPORTED"


def test_an_unconfirmed_currency_is_withheld_without_the_amount():
    """Report UNVERIFIED and keep the amount out of the public report."""
    dollar = {**REVENUE, "currency": "$", "status": "currency_unconfirmed"}
    state, _ = ask([selection()], cell=dollar)
    report = state["structured_response"]
    assert report.label == "UNVERIFIED"
    assert "25,785" not in report.answer + report.rationale
    assert state["withheld"] == {"figures": ["$ 25,785"], "causes": ["currency"]}


def test_a_held_cell_claimed_as_another_item_is_returned_before_it_is_withheld():
    """Tell the model a held cell is not its claim, then withhold the corrected selection."""
    dollar = {**REVENUE, "currency": "$", "status": "currency_unconfirmed"}
    state, model = ask([selection(item="net income"), selection()], cell=dollar)
    errors = [
        m.content for m in state["messages"] if isinstance(m, ToolMessage) and m.status == "error"
    ]
    assert errors == ["ERROR: cell 2024:r1c1 is revenue, not net income"]
    assert len(model.requests) == 4
    assert state["structured_response"].label == "UNVERIFIED"


def test_a_cell_changed_after_its_fetch_ends_the_run_without_another_request():
    """Stop as a failure instead of answering from a cell whose content changed."""
    changed = {**REVENUE, "raw_text": "$ 99,999"}
    state, model = ask([selection(), selection()], stored=changed)
    assert len(model.requests) == 3
    assert state.get("structured_response") is None
    assert state["failure"] == "StaleCellError: stored cell read failed"


def test_a_missing_stored_cell_reader_ends_the_run_as_a_failure():
    """Stop instead of answering when no stored cell reader is configured."""
    state, model = ask([selection(), selection()], reader_configured=False)
    assert len(model.requests) == 3
    assert state.get("structured_response") is None
    assert state["failure"] == "RuntimeError: stored cell read failed"


def test_a_selected_cell_of_another_year_is_reported_as_a_period_mismatch():
    """Report the selected cell's own year through the gate, without its amount."""
    older = {**REVENUE, "fiscal_years": [2023], "column_header": "2023"}
    state, model = ask([selection(year=2023)], cell=older)
    report = state["structured_response"]
    assert len(model.requests) == 3
    assert report.label == "PERIOD_MISMATCH"
    assert report.answer == "The selected table cells are for fiscal 2023, not fiscal 2024."
    assert state["period_mismatch"] == {
        "requested_fiscal_years": [2024],
        "evidenced_fiscal_years": [2023],
        "figures": ["$ 25,785"],
    }
    assert state["cell_checks"][0]["decision"] == "other period"


def test_a_cell_that_was_not_fetched_is_returned_without_reading_it():
    """Refuse a ref outside this question's fetches before any stored cell is read."""
    stray = selection()
    stray["selections"][0]["cell_id"] = "2024:r9c9"
    reads: list[tuple[str, ...]] = []
    state, model = ask([stray, selection()], reads=reads)
    errors = [
        m.content for m in state["messages"] if isinstance(m, ToolMessage) and m.status == "error"
    ]
    assert errors == [
        "ERROR: cell 2024:r9c9 was not returned by a fetch in this question; fetch its chunk"
    ]
    assert reads == [("2024:r1c1",)]
    assert len(model.requests) == 4
    assert state["structured_response"].label == "SUPPORTED"


ABSENT = {**selection(), "label": "NOT_IN_DOCS", "reason": "not_found", "selections": []}
UNSEARCHED = (
    "ERROR: no search has returned in this question; search the filings before reporting not_found"
)


def errors_of(state: dict[str, Any]) -> list[Any]:
    """The error tool results the run answered, in order."""
    return [
        m.content for m in state["messages"] if isinstance(m, ToolMessage) and m.status == "error"
    ]


@pytest.mark.parametrize("search", ["hit", "none"])
def test_not_found_before_any_search_is_returned_and_accepted_after_one(search):
    """Refuse a first-turn not_found, then accept it after a search, even one with no hits."""
    state, model = ask(
        [],
        search=search,
        replies=[
            reply("call_final_0", "final_answer", ABSENT),
            reply("call_search", "search_filings", SEARCH),
            reply("call_final_1", "final_answer", ABSENT),
        ],
    )
    assert errors_of(state) == [UNSEARCHED]
    assert len(model.requests) == 3
    report = state["structured_response"]
    assert (report.label, report.answer) == ("NOT_IN_DOCS", "NOT_IN_DOCS")
    assert bool(state["evidence"]) is (search == "hit")


def test_a_failed_search_is_not_a_search():
    """Keep refusing not_found after a search that ended in a tool error."""
    state, model = ask(
        [],
        search="fail",
        replies=[
            reply("call_search", "search_filings", SEARCH),
            reply("call_final_0", "final_answer", ABSENT),
            AIMessage(content="No answer.", usage_metadata=USAGE),
        ],
    )
    errors = errors_of(state)
    assert len(errors) == 2 and errors[1] == UNSEARCHED
    assert "search failed" in errors[0]
    assert len(model.requests) == 3
    assert state.get("structured_response") is None
