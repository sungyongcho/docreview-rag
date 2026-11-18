"""Every cell of the policy table matches what its path does.

Each observer runs the workflow nodes, ``run_agent`` and the prebuilt agent on the same
checked evidence and names the behaviour it saw in the vocabulary of one
:class:`~app.review.policy.AnswerPolicy` field. The table is right only when every
path's observed behaviour equals the value the table declares for it.
"""

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import fields
import json
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from pydantic import BaseModel, ValidationError
import pytest

from app.agent.loop import run_agent
from app.agent.prebuilt import build_review_agent
from app.agent.review_middleware import ReviewContext
from app.agent.types import AgentResult, ToolCall
from app.amendments.policy import EvidenceWithheldError
from app.contracts.evidence import EvidenceCitation, EvidenceHold
from app.contracts.figures import FiguresUnverified
from app.figures.answers import EvidenceText
from app.figures.tables import read_table_cells
from app.llm.schemas import AnswerDecision, ChunkRelevance, RelevanceJudgment
from app.review.evidence import StoredCell
from app.review.policy import POLICIES, AnswerPath, AnswerPolicy
from app.tools.registry import Tool, ToolRegistry
from app.workflow.nodes import check_node, grade_node, report_node, retrieve_node
from app.workflow.types import (
    EvidenceHeld,
    SupportDowngraded,
    WorkflowReport,
    WorkflowRequest,
    initial_state,
)
from tests.support.models import ScriptedChatModel, ScriptedToolProvider, turn
from tests.workflow.support import USD_INCOME_TABLE, income_table_hit, ok_result, provider_budget

HIT, FRAGMENT = income_table_hit(html=USD_INCOME_TABLE)
READINGS = tuple(read_table_cells(FRAGMENT))
CITATION = EvidenceCitation(
    chunk_id=HIT.chunk_id,
    doc_id=HIT.doc_id,
    citation=HIT.citation,
    start_char=HIT.start_char,
    end_char=HIT.end_char,
    source_sha256=HIT.source_sha256,
)
CONFIRMED = "FY2024 net revenue was USD 25,785 million."
UNCONFIRMED = "FY2024 net revenue was USD 99,999 million."
FOREIGN = CITATION.model_copy(update={"chunk_id": HIT.chunk_id + 1000})
ABSENT: dict[str, Any] = dict(
    label="NOT_IN_DOCS", answer="NOT_IN_DOCS", citations=[], rationale="Not found"
)
CELLS_NOT_FOUND: dict[str, Any] = dict(
    contract_version="cell-v1",
    label="NOT_IN_DOCS",
    reason="not_found",
    selections=[],
    unresolved_chunk_ids=[],
)
HELD_LATER = EvidenceHold(
    registry="SEC", issuer="AMD", fiscal_year=2024, reason="amendment_pending"
)


def written(answer: str, citation: EvidenceCitation = CITATION) -> dict[str, Any]:
    """A SUPPORTED written final answer citing one chunk."""
    return dict(
        label="SUPPORTED",
        answer=answer,
        citations=[citation.model_dump(mode="json")],
        rationale="Checked",
    )


async def read_retrieved(ids: tuple[int, ...]) -> Mapping[int, EvidenceText]:
    """Read the cited table exactly as it was retrieved."""
    del ids
    return {HIT.chunk_id: EvidenceText(HIT.chunk_id, HIT.body, HIT.context_header, READINGS)}


async def read_held(ids: tuple[int, ...]) -> Mapping[int, EvidenceText]:
    """Refuse the cited chunk: a later filing holds it back since it was retrieved."""
    raise EvidenceWithheldError(ids)


async def read_no_cells(refs: tuple[str, ...]) -> Mapping[str, StoredCell]:
    """Read no stored cell; a not_found answer selects none."""
    del refs
    return {}


# Workflow


def workflow_report(
    decision: AnswerDecision,
    *,
    relevant: bool = True,
    holds: tuple[EvidenceHold, ...] = (),
) -> WorkflowReport:
    """Retrieve the table, grade it and check and report ``decision`` on the workflow."""
    state = initial_state(
        WorkflowRequest(
            run_id="policy",
            query="What was FY2024 revenue?",
            locale="en",
            requested_fiscal_years=(2024,),
            provider_budget=provider_budget(),
        )
    )
    graded = grade_node(
        retrieve_node(state, [HIT], holds),
        ok_result(
            RelevanceJudgment(
                grades=(ChunkRelevance(chunk_id=HIT.chunk_id, relevant=relevant, reason="Graded"),)
            )
        ),
    )
    report = report_node(check_node(graded, ok_result(decision), {HIT.chunk_id: READINGS})).report
    assert report is not None
    return report


def supported_decision(answer: str) -> AnswerDecision:
    """The workflow's SUPPORTED decision citing the retrieved table."""
    return AnswerDecision(
        label="SUPPORTED", answer=answer, citation_chunk_ids=(HIT.chunk_id,), reason="Checked"
    )


# Agents


def registry_and_tool() -> tuple[ToolRegistry, Any]:
    """The same network-free search, as an app contract and as a bound LangChain tool."""

    class SearchParams(BaseModel):
        """Arguments of the evidence tool."""

        query: str

    async def search(params: SearchParams) -> dict[str, Any]:
        """Return the stored identity of the table."""
        del params
        return {"hits": [CITATION.model_dump(mode="json")]}

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
            evidence_ids=lambda out: (CITATION,),
        )
    )
    return registry, search_notes


def agent_calls(*finals: dict[str, Any]) -> list[dict[str, Any]]:
    """One search, then each proposed final answer in turn."""
    return [
        dict(name="search_notes", args={"query": "revenue"}, id="search", type="tool_call"),
        *(
            dict(name="final_answer", args=final, id=f"final-{index}", type="tool_call")
            for index, final in enumerate(finals)
        ),
    ]


def run_loop(*finals: dict[str, Any], reader: Callable[..., Any] = read_retrieved) -> AgentResult:
    """Run ``run_agent`` on a search and the proposed final answers."""
    registry, _ = registry_and_tool()
    provider = ScriptedToolProvider(
        [
            turn(
                tool_calls=(
                    ToolCall(call_id=c["id"], name=c["name"], arguments_json=json.dumps(c["args"])),
                )
            )
            for c in agent_calls(*finals)
        ]
    )
    return asyncio.run(
        run_agent(
            "What was FY2024 revenue?",
            registry=registry,
            provider=provider,
            requested_fiscal_years=[2024],
            evidence_reader=reader,
            locale="en",
        )
    )


def run_prebuilt(
    *finals: dict[str, Any],
    reader: Callable[..., Any] = read_retrieved,
    cells: bool = False,
) -> dict[str, Any]:
    """Run the prebuilt agent on a search and the proposed final answers."""
    registry, search_notes = registry_and_tool()
    model = ScriptedChatModel.from_replies(
        *(AIMessage(content="", tool_calls=[c]) for c in agent_calls(*finals))
    )
    agent = build_review_agent(model, [search_notes], registry, cells=cells)
    context = ReviewContext(
        (2024,), reader, locale="en", cell_answers=cells, cell_reader=read_no_cells
    )
    return asyncio.run(
        agent.ainvoke({"messages": [HumanMessage("What was FY2024 revenue?")]}, context=context)
    )


def loop_rejection(result: AgentResult) -> str | None:
    """The error the loop sent back for the first proposed final answer, if any."""
    observation = result.steps[1].observations
    return observation[0].error if observation else None


def prebuilt_rejection(state: dict[str, Any]) -> str | None:
    """The error the gate sent back for the first proposed final answer, if any."""
    for message in state["messages"]:
        if isinstance(message, ToolMessage) and message.tool_call_id == "final-0":
            return str(message.content) if message.status == "error" else None
    raise AssertionError("the first final answer was not answered")


# Observers: one per policy field, naming what each path did.


def observe_unverified_figures(path: AnswerPath) -> str:
    """What a SUPPORTED answer with an unconfirmed figure became."""
    returned = "final_answer states figures its cited evidence does not confirm"
    match path:
        case "workflow":
            report = workflow_report(supported_decision(UNCONFIRMED))
            unverified = any(isinstance(r, FiguresUnverified) for r in report.reasons)
            return "report_not_in_docs" if report.label == "NOT_IN_DOCS" and unverified else "?"
        case "loop":
            result = run_loop(written(UNCONFIRMED), ABSENT)
            rejection = loop_rejection(result) or ""
            return "return_to_model" if rejection.startswith(returned) else "?"
        case "prebuilt":
            state = run_prebuilt(written(UNCONFIRMED), ABSENT)
            rejection = prebuilt_rejection(state) or ""
            return "return_to_model" if rejection.startswith(f"ERROR: {returned}") else "?"


def observe_cited_evidence(path: AnswerPath) -> str:
    """Whether a hold appearing after retrieval stops the answer from being judged."""
    failure = "EvidenceWithheldError: cited evidence read failed"
    match path:
        case "workflow":
            # The check takes the retrieved hit as it is: a hold the retrieval found is
            # reported as a reason, and the answer is still judged from that evidence.
            report = workflow_report(supported_decision(CONFIRMED), holds=(HELD_LATER,))
            held = any(isinstance(r, EvidenceHeld) for r in report.reasons)
            return "as_retrieved" if report.label == "SUPPORTED" and held else "?"
        case "loop":
            result = run_loop(written(CONFIRMED), reader=read_held)
            return (
                "reread_at_answer"
                if (result.status, result.failure)
                == (
                    "tool_error",
                    failure,
                )
                else "?"
            )
        case "prebuilt":
            state = run_prebuilt(written(CONFIRMED), reader=read_held)
            answered = state.get("structured_response") is not None
            return "reread_at_answer" if state["failure"] == failure and not answered else "?"


def observe_foreign_citations(path: AnswerPath) -> str:
    """What a SUPPORTED answer citing evidence the path did not admit became."""
    returned = "final_answer cites chunk ids no tool returned in this run"
    match path:
        case "workflow":
            report = workflow_report(supported_decision(CONFIRMED), relevant=False)
            downgraded = any(isinstance(r, SupportDowngraded) for r in report.reasons)
            return (
                "downgrade_to_not_in_docs" if report.label == "NOT_IN_DOCS" and downgraded else "?"
            )
        case "loop":
            rejection = loop_rejection(run_loop(written(CONFIRMED, FOREIGN), ABSENT)) or ""
            return "return_to_model" if rejection.startswith(returned) else "?"
        case "prebuilt":
            state = run_prebuilt(written(CONFIRMED, FOREIGN), ABSENT)
            rejection = prebuilt_rejection(state) or ""
            return "return_to_model" if rejection.startswith(f"ERROR: {returned}") else "?"


def observe_cell_answers(path: AnswerPath) -> bool:
    """Whether a cell-selecting final answer can end the run."""
    match path:
        case "workflow":
            try:
                AnswerDecision.model_validate(CELLS_NOT_FOUND)
            except ValidationError:
                return False
            return True
        case "loop":
            result = run_loop(CELLS_NOT_FOUND, ABSENT)
            return not (loop_rejection(result) or "").startswith("invalid final_answer")
        case "prebuilt":
            state = run_prebuilt(CELLS_NOT_FOUND, cells=True)
            return prebuilt_rejection(state) is None and state["structured_response"] is not None


OBSERVERS: dict[str, Callable[[AnswerPath], object]] = {
    "unverified_figures": observe_unverified_figures,
    "cited_evidence": observe_cited_evidence,
    "foreign_citations": observe_foreign_citations,
    "cell_answers": observe_cell_answers,
}
PATHS: tuple[AnswerPath, ...] = ("workflow", "loop", "prebuilt")


def test_every_policy_field_has_an_observer_and_every_path_a_row():
    """A new field or path cannot enter the table without a behavioural check."""
    assert set(OBSERVERS) == {field.name for field in fields(AnswerPolicy)}
    assert set(POLICIES) == set(PATHS)


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("field", list(OBSERVERS))
def test_each_cell_matches_what_the_path_does(field, path):
    """Run the path and compare the behaviour it shows with the value the table declares."""
    assert OBSERVERS[field](path) == getattr(POLICIES[path], field)
