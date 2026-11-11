"""Resolved locales reach reports through the loop, middleware, workflow and cell gate."""

import asyncio
from decimal import Decimal
import json
from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool
from pydantic import BaseModel
import pytest

from app.agent.cell_answers import StoredCell, cell_digest, review_cell_selection
from app.agent.loop import run_agent
from app.agent.review_middleware import (
    ReviewContext,
    ReviewGate,
    StopOnSystemFailure,
    final_answer_format,
)
from app.agent.tools.registry import Tool, ToolRegistry
from app.agent.types import CellSelection, CellSelectionAnswer, ToolCall
from app.contracts.evidence import EvidenceCitation
from app.figures.answers import EvidenceText
from app.figures.tables import read_table_cells
from app.llm.schemas import AnswerDecision, ChunkRelevance, RelevanceJudgment
from app.workflow.nodes import check_node, grade_node, report_node, retrieve_node
from app.workflow.types import WorkflowRequest, initial_state
from tests.agent.support import RecordingToolProvider, ScriptedChatModel, turn
from tests.workflow.support import (
    INCOME_TABLE,
    USD_INCOME_TABLE,
    income_table_hit,
    ok_result,
    provider_budget,
)


class SearchParams(BaseModel):
    """Arguments of the network-free evidence tool."""

    query: str


@pytest.mark.parametrize("locale", ["en", "ko"])
@pytest.mark.parametrize("kind", ["unit", "direction", "period", "supported"])
def test_all_report_paths_use_the_resolved_locale(locale, kind):
    """The same checked evidence yields the same sentences wherever that report is available."""
    html = INCOME_TABLE if kind == "unit" else USD_INCOME_TABLE
    if kind == "direction":
        html = html.replace("Net revenue", "Net loss")
    hit, fragment = income_table_hit(html=html)
    readings = tuple(read_table_cells(fragment))
    citation = EvidenceCitation(
        chunk_id=hit.chunk_id,
        doc_id=hit.doc_id,
        citation=hit.citation,
        start_char=hit.start_char,
        end_char=hit.end_char,
        source_sha256=hit.source_sha256,
    )
    amount = "22,680" if kind == "period" else "25,785"
    item = "net loss" if kind == "direction" else "net revenue"
    # An English answer proves that the explicitly resolved locale owns report text.
    answer = f"FY2024 {item} was USD {amount} million."
    proposed = dict(
        label="SUPPORTED",
        answer=answer,
        citations=[citation.model_dump(mode="json")],
        rationale="Checked",
    )

    async def read(ids):
        """Return precisely the table used by all the checked paths."""
        return {hit.chunk_id: EvidenceText(hit.chunk_id, hit.body, hit.context_header, readings)}

    async def search(params):
        """Read the stored identity without network or database access."""
        return {"hits": [citation.model_dump(mode="json")]}

    @tool(response_format="content_and_artifact")
    async def search_notes(query: str):
        """Retrieve the synthetic source."""
        out = await search(SearchParams(query=query))
        return json.dumps(out), {"structured_content": out}

    registry = ToolRegistry()
    registry.register(
        Tool(
            name="search_notes",
            description="Retrieve source",
            parameters=SearchParams,
            run=search,
            evidence_ids=lambda out: (citation,),
        )
    )
    calls = [
        dict(name="search_notes", args={"query": "revenue"}, id="search", type="tool_call"),
        dict(name="final_answer", args=proposed, id="final", type="tool_call"),
    ]
    model = ScriptedChatModel.from_replies(*(AIMessage(content="", tool_calls=[c]) for c in calls))
    provider = RecordingToolProvider(
        [
            turn(
                tool_calls=(
                    ToolCall(call_id=c["id"], name=c["name"], arguments_json=json.dumps(c["args"])),
                )
            )
            for c in calls
        ]
    )
    agent = create_agent(
        model,
        [search_notes],
        middleware=[StopOnSystemFailure(), ReviewGate(registry)],
        response_format=final_answer_format(),
        context_schema=ReviewContext,
    )
    question = "매출은?" if locale == "ko" else "What was revenue?"

    async def run():
        """Invoke the public agent entry points with the explicit application locale."""
        direct = await run_agent(
            question,
            registry=registry,
            provider=provider,
            requested_fiscal_years=[2024],
            evidence_reader=read,
            locale=locale,
        )
        state = await agent.ainvoke(
            {"messages": [HumanMessage(question)]},
            context=ReviewContext((2024,), read, locale=locale),
        )
        return direct.answer, state["structured_response"]

    direct, middleware = asyncio.run(run())
    state = initial_state(
        WorkflowRequest(
            run_id="locale",
            query=question,
            requested_fiscal_years=(2024,),
            provider_budget=provider_budget(),
        )
    )
    state = grade_node(
        retrieve_node(state, [hit]),
        ok_result(
            RelevanceJudgment(
                grades=(ChunkRelevance(chunk_id=hit.chunk_id, relevant=True, reason="Relevant"),)
            )
        ),
    )
    workflow = report_node(
        check_node(
            state,
            ok_result(
                AnswerDecision(
                    label="SUPPORTED",
                    answer=answer,
                    citation_chunk_ids=(hit.chunk_id,),
                    reason="Checked",
                )
            ),
            {hit.chunk_id: readings},
        )
    ).report
    assert direct is not None and workflow is not None
    assert direct == middleware
    assert (direct.label, direct.answer, direct.rationale) == (
        workflow.label,
        workflow.answer,
        workflow.rationale,
    )
    if kind != "supported":
        assert ("확인" in direct.answer) if locale == "ko" else ("The " in direct.answer)

    year = 2023 if kind == "period" else 2024
    ref = f"{hit.chunk_id}:r1c1"
    cell: dict[str, Any] = dict(
        ref=ref,
        row_label=item,
        column_header=str(year),
        raw_text=amount,
        item="net income" if kind == "direction" else "revenue",
        fiscal_years=[year],
        scale="1000000",
        currency="$" if kind == "unit" else "USD",
        percent=False,
        complete=True,
        status="currency_unconfirmed"
        if kind == "unit"
        else "conflicting"
        if kind == "direction"
        else "known",
    )
    stored = StoredCell(
        ref, hit.chunk_id, cell, "stable", "resolver", Decimal(amount.replace(",", ""))
    )
    selected = review_cell_selection(
        CellSelectionAnswer(
            contract_version="cell-v1",
            label="SUPPORTED",
            reason="selected",
            selections=(
                CellSelection(cell_id=ref, claimed_item=cell["item"], claimed_fiscal_year=year),
            ),
            unresolved_chunk_ids=(),
        ),
        ledger={
            ref: dict(
                chunk_id=hit.chunk_id,
                stable_key="stable",
                resolver_identity="resolver",
                digest=cell_digest(cell),
            )
        },
        evidence={hit.chunk_id: citation.model_dump(mode="json")},
        stored={ref: stored},
        requested_items=frozenset({cell["item"]}),
        requested_years=[2024],
        searched=True,
        locale=locale,
    )
    if kind == "direction":
        assert selected.report is None and "conflicting" in selected.problem
    else:
        assert selected.report is not None and selected.report.label == direct.label
        if kind == "unit":
            assert (selected.report.answer, selected.report.rationale) == (
                direct.answer,
                direct.rationale,
            )
        elif kind == "period":
            expected = (
                "선택된 표의 칸은 2024 회계연도가 아니라 2023 회계연도의 값입니다."
                if locale == "ko"
                else "The selected table cells are for fiscal 2023, not fiscal 2024."
            )
            assert selected.report.answer == expected
