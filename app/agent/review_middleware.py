"""Keep the agent loop's question-scoped rules around ``create_agent`` tool and model calls.

``run_agent`` validates every tool call strictly, reads only chunks the current
question retrieved and records the complete source identity of each result. Under
``create_agent`` the tools node runs the tools, so :class:`ReviewGate` applies the
same rules as tool-call middleware while execution itself stays with the bound tool,
such as an MCP adapter tool. Its model-call hook applies the loop's final-answer
policy to the structured ``final_answer`` the model proposes: the answer stands alone,
its citations match the ledger, and its figures pass the same figure check, so it is
accepted, reported as a period mismatch or withheld as ``UNVERIFIED``, or returned to
the model for revision. :class:`StopOnSystemFailure` keeps the loop's other rule: a
system failure the model cannot correct ends the run instead of reaching the model as
though nothing were found.
"""

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
import json
from typing import Annotated, Any, Literal, NotRequired

from langchain.agents.middleware import (
    AgentMiddleware,
    AgentState,
    ExtendedModelResponse,
    ModelRequest,
    ModelResponse,
    ToolCallRequest,
    hook_config,
)
from langchain.agents.structured_output import ToolStrategy
from langchain_core.messages import AIMessage, ToolCall as MessageToolCall, ToolMessage
from langgraph.errors import GraphBubbleUp
from langgraph.runtime import Runtime
from langgraph.types import Command
from mcp.shared.exceptions import MCPError
from mcp.types import INTERNAL_ERROR
from pydantic import BaseModel, ValidationError

from app.agent.cell_answers import StoredCell, cell_digest, review_cell_selection
from app.agent.final_answer import (
    FINAL_NOT_ALONE,
    EvidenceReader,
    as_report,
    final_answer_spec,
    judge_written_answer,
    validate_final_answer,
)
from app.agent.tools.filings import FetchChunkParams
from app.agent.tools.registry import FINAL_ANSWER_NAME, Tool, ToolRegistry, safe_runtime_error
from app.agent.types import AgentReportAnswer, CellSelectionAnswer, ToolCall
from app.contracts.evidence import EvidenceCitation
from app.llm.decoding import validation_errors

type EvidenceLedger = dict[int, dict[str, Any]]
type CellLedger = dict[str, dict[str, Any]]
type ToolHandler = Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]]
type ModelHandler = Callable[[ModelRequest[Any]], Awaitable[ModelResponse[Any]]]
type ModelResult = ModelResponse[Any] | AIMessage | ExtendedModelResponse[Any]

type CellReader = Callable[[tuple[str, ...]], Awaitable[Mapping[str, StoredCell]]]


@dataclass(frozen=True, slots=True)
class ReviewContext:
    """Per-question settings the final-answer review reads; the model never chooses them.

    Attributes
    ----------
    requested_fiscal_years : tuple[int, ...]
        Fiscal years the question asks about, as ``run_agent`` receives them.
    evidence_reader : EvidenceReader | None
        App-internal reader of the cited chunks' text and table readings for the
        figure check; not a tool. ``None`` leaves figures without readable evidence.
    cell_answers : bool
        Whether ``final_answer`` selects table cells (:class:`CellSelectionAnswer`,
        offered by ``final_answer_format(cells=True)``) instead of writing an answer.
    requested_items : frozenset[str]
        Financial items the question names, read by the application from its text.
    locale : Literal["en", "ko"]
        Language the application writes a cell-selected answer in.
    cell_reader : CellReader | None
        App-internal reader of the selected cells as stored now; required in cell mode.
    """

    requested_fiscal_years: tuple[int, ...] = ()
    evidence_reader: EvidenceReader | None = None
    cell_answers: bool = False
    requested_items: frozenset[str] = frozenset()
    locale: Literal["en", "ko"] = "en"
    cell_reader: CellReader | None = None


class CitedEvidenceReadError(RuntimeError):
    """The cited evidence of a final answer could not be read for the figure check.

    :class:`ReviewGate` raises it instead of judging the answer without its evidence;
    :class:`StopOnSystemFailure` turns it into the run's failure. ``failure`` is
    already redacted, and ``message``/``call`` are the model reply and the final call
    the failure must answer.
    """

    def __init__(self, message: AIMessage, call: MessageToolCall, failure: str) -> None:
        """Keep the reply and call to answer, and the redacted failure."""
        super().__init__(failure)
        self.message = message
        self.call = call
        self.failure = failure


CELL_FINAL_DESCRIPTION = (
    "Finish with the table cells that answer the question. Name cells only by the ref a "
    "fetch_chunk result listed in this question, with the item and fiscal year you claim "
    "for each; never write an amount, the application writes the answer. Use "
    "cannot_resolve with the retrieved chunk ids when the evidence relates to the "
    "question but no listed cell establishes the answer, and NOT_IN_DOCS with not_found "
    "only when the searched evidence holds no answer."
)


def final_answer_format(*, cells: bool = False) -> ToolStrategy[dict[str, Any]]:
    """Offer the strict ``final_answer`` schema as the agent's structured output.

    By default it is ``run_agent``'s written-answer schema; with ``cells`` it is the
    :class:`CellSelectionAnswer` schema that names table cells and no amount. The schema
    is plain JSON, so LangChain only parses the call's JSON and never validates it;
    :meth:`ReviewGate.awrap_model_call` owns validation and every accept, report or
    reject decision.
    """
    if cells:
        schema = CellSelectionAnswer.model_json_schema()
        return ToolStrategy(
            {**schema, "title": FINAL_ANSWER_NAME, "description": CELL_FINAL_DESCRIPTION}
        )
    spec = final_answer_spec()
    return ToolStrategy(
        {**spec["parameters"], "title": spec["name"], "description": spec["description"]}
    )


def merge_evidence(left: EvidenceLedger | None, right: EvidenceLedger | None) -> EvidenceLedger:
    """Combine evidence ledger updates; ``None`` clears the ledger, ``{}`` keeps it.

    Parameters
    ----------
    left : EvidenceLedger | None
        Ledger in the current graph state, absent before the first update.
    right : EvidenceLedger | None
        One update: newly returned identities, or ``None`` to start a new question.

    Returns
    -------
    EvidenceLedger
        The updated ledger. Updates from parallel tool calls are merged one after
        another, so each keeps the identities the others added.
    """
    if right is None:
        return {}
    return {**(left or {}), **right}


def merge_cells(left: CellLedger | None, right: CellLedger | None) -> CellLedger:
    """Combine cell ledger updates; ``None`` clears it and a disagreement is marked.

    Parameters
    ----------
    left : CellLedger | None
        Cells fetched so far in this question, absent before the first update.
    right : CellLedger | None
        One update: the cells one fetch returned, or ``None`` to start a new question.

    Returns
    -------
    CellLedger
        The merged ledger. When two updates, possibly from parallel calls in one step,
        record different contents under one ref, the ref keeps a ``conflict`` marker that
        :class:`StopOnSystemFailure` turns into the run's failure before the next model
        call.
    """
    if right is None:
        return {}
    merged = dict(left or {})
    for ref, record in right.items():
        known = merged.get(ref)
        merged[ref] = record if known is None or known == record else {"conflict": True}
    return merged


def cell_record(cell: dict[str, Any], catalog: dict[str, Any], chunk_id: int) -> dict[str, Any]:
    """Record one returned cell by the identity its content and source version fix."""
    return {
        "chunk_id": chunk_id,
        "stable_key": catalog["stable_key"],
        "resolver_identity": catalog["resolver_identity"],
        "digest": cell_digest(cell),
    }


def _returned_cells(message: ToolMessage, chunk_id: int) -> CellLedger:
    """Return the ledger records of the stored cells one fetch result carries."""
    artifact = message.artifact if isinstance(message.artifact, dict) else {}
    structured = artifact.get("structured_content")
    catalog = structured.get("table") if isinstance(structured, dict) else None
    if not isinstance(catalog, dict) or catalog.get("status") != "available":
        return {}
    return {cell["ref"]: cell_record(cell, catalog, chunk_id) for cell in catalog["cells"]}


def keep_first_failure(left: str | None, right: str | None) -> str | None:
    """Combine failure updates; ``None`` clears the failure, otherwise the first one stays.

    Parameters
    ----------
    left : str | None
        Failure in the current graph state, absent or ``None`` before one is recorded.
    right : str | None
        One update: a system failure's message, or ``None`` to start a new question.

    Returns
    -------
    str | None
        ``None`` for a new question; otherwise the failure already recorded, or this one.
        Parallel tool calls that fail in one step each answer their own call, and the
        run ends on whichever failure was recorded first.
    """
    if right is None:
        return None
    return right if left is None else left


class ReviewState(AgentState[Any]):
    """Agent state with this question's evidence identities and report records.

    ``period_mismatch`` and ``unit_unverified`` hold the JSON form of the loop's
    :class:`~app.agent.types.AgentPeriodMismatch` and
    :class:`~app.agent.types.AgentUnitUnverified` when the accepted report is a period
    mismatch or withholds its figures; otherwise they are ``None``.
    """

    evidence: Annotated[NotRequired[EvidenceLedger], merge_evidence]
    cells: Annotated[NotRequired[CellLedger], merge_cells]
    cell_checks: NotRequired[list[dict[str, Any]] | None]
    period_mismatch: NotRequired[dict[str, Any] | None]
    unit_unverified: NotRequired[dict[str, Any] | None]


class StopState(ReviewState):
    """Review state plus the system failure that ended this question, if any."""

    failure: Annotated[NotRequired[str | None], keep_first_failure]


def _error(call: MessageToolCall, text: str) -> ToolMessage:
    """Answer one call with a correctable error the model reads as its result."""
    return ToolMessage(
        content=f"ERROR: {text}", tool_call_id=call["id"], name=call["name"], status="error"
    )


def _rejected(message: AIMessage, calls: Sequence[MessageToolCall], text: str) -> ModelResponse:
    """Keep the model reply, answer each call with ``text`` and accept nothing."""
    return ModelResponse(
        result=[message, *(_error(call, text) for call in calls)], structured_response=None
    )


def _accepted(
    message: AIMessage,
    call: MessageToolCall,
    report: AgentReportAnswer,
    **records: dict[str, Any] | list[dict[str, Any]],
) -> ModelResponse | ExtendedModelResponse:
    """Acknowledge the final call under its id and end on ``report`` with its records.

    ``records`` are the ``period_mismatch``/``unit_unverified`` state updates of a
    report the loop qualifies; a plain answer needs none, because each question
    starts with both cleared.
    """
    acknowledgement = ToolMessage(
        content=f"final_answer accepted as {report.label}",
        tool_call_id=call["id"],
        name=call["name"],
    )
    response = ModelResponse(result=[message, acknowledgement], structured_response=report)
    if not records:
        return response
    return ExtendedModelResponse(model_response=response, command=Command(update=records))


def _validate(tool: Tool[Any], arguments: dict[str, Any]) -> BaseModel | str:
    """Validate arguments as strict JSON like ``execute_tool``; return the error text if invalid."""
    try:
        return tool.parameters.model_validate_json(json.dumps(arguments), strict=True)
    except ValidationError as error:
        return f"invalid arguments for {tool.name}: {'; '.join(validation_errors(error))}"
    except ValueError as error:
        return f"invalid arguments for {tool.name}: {error}"


def _returned_identities(tool: Tool[Any], message: ToolMessage) -> tuple[EvidenceCitation, ...]:
    """Extract the complete source identities from a successful tool result.

    Raises
    ------
    ValueError
        If the result carries no structured content or repeats a chunk id.
    TypeError
        If the extractor returns anything but citations.
    """
    if tool.evidence_ids is None:
        return ()
    artifact = message.artifact if isinstance(message.artifact, dict) else {}
    structured = artifact.get("structured_content")
    if not isinstance(structured, dict):
        raise ValueError(f"tool {tool.name} returned no structured content")
    found = tool.evidence_ids(structured)
    if not isinstance(found, tuple) or any(not isinstance(c, EvidenceCitation) for c in found):
        raise TypeError("evidence extractor must return EvidenceCitation values")
    if len({citation.chunk_id for citation in found}) != len(found):
        raise ValueError("evidence extractor returned duplicate chunk ids")
    return found


class ReviewGate(AgentMiddleware[ReviewState, ReviewContext]):
    """Question-scoped tool rules and the final-answer gate of ``run_agent``.

    Tool calls get strict arguments, a question-scoped fetch guard and an evidence
    ledger. A model reply that proposes ``final_answer`` is reviewed before the run
    may end on it; give the agent :func:`final_answer_format` as its response format
    and a :class:`ReviewContext` as its context.

    Parameters
    ----------
    contracts : ToolRegistry
        The app's own tools. Only their parameter models and evidence extraction are
        used; their ``run`` functions are never called, because the wrapped tool,
        such as an MCP adapter tool, executes the call.

    Notes
    -----
    The ledger and report records live in graph state (:class:`ReviewState`), never
    on the middleware, so one gate can serve concurrent runs and a checkpointed
    thread keeps them with the rest of its state. Each invocation is one question:
    ``before_agent`` clears the ledger, the report records and the structured
    response, so nothing retrieved, accepted or withheld for an earlier question on
    the same thread carries over. Rejections are error tool results the model can
    correct. Failures the model cannot correct raise instead: a successful tool
    result without structured content, or :class:`CitedEvidenceReadError`, which
    needs :class:`StopOnSystemFailure` in the stack to end the run as a failure.
    """

    state_schema = ReviewState

    def __init__(self, contracts: ToolRegistry) -> None:
        """Keep the app contracts for validation and evidence extraction; never run their tools."""
        super().__init__()
        self.contracts = contracts

    def before_agent(
        self, state: ReviewState, runtime: Runtime[ReviewContext]
    ) -> dict[str, Any] | None:
        """Start each invocation, one question, with no evidence, report or answer."""
        del state, runtime
        return {
            "evidence": None,
            "cells": None,
            "cell_checks": None,
            "period_mismatch": None,
            "unit_unverified": None,
            "structured_response": None,
        }

    async def awrap_tool_call(
        self, request: ToolCallRequest, handler: ToolHandler
    ) -> ToolMessage | Command[Any]:
        """Check one tool call before it runs, then record the identities it returned.

        Parameters
        ----------
        request : ToolCallRequest
            The model's call, the bound tool and the current graph state.
        handler : ToolHandler
            Runs the call through the inner middleware and the bound tool.

        Returns
        -------
        ToolMessage | Command[Any]
            An error result when the arguments are invalid, the fetch was not
            retrieved in this question or a returned identity conflicts with the
            ledger; otherwise the tool's result, wrapped in a ledger update when it
            returned new identities.

        Raises
        ------
        ValueError
            If a bound tool has no app contract, or a successful result's evidence
            cannot be extracted.
        """
        name = request.tool_call["name"]
        if name not in self.contracts.names:
            if request.tool is None:
                # Not bound either: the tools node answers with its own unknown-tool error.
                return await handler(request)
            raise ValueError(f"tool {name} is bound to the agent but has no app contract")
        tool = self.contracts.get(name)
        parameters = _validate(tool, request.tool_call["args"])
        if isinstance(parameters, str):
            return _error(request.tool_call, parameters)
        evidence: EvidenceLedger = request.state.get("evidence") or {}
        if isinstance(parameters, FetchChunkParams) and parameters.chunk_id not in evidence:
            return _error(
                request.tool_call,
                f"chunk {parameters.chunk_id} was not retrieved in this question; search first",
            )

        result = await handler(request)
        if not isinstance(result, ToolMessage) or result.status == "error":
            return result
        found = {c.chunk_id: c.model_dump(mode="json") for c in _returned_identities(tool, result)}
        conflict = next((k for k, v in found.items() if k in evidence and evidence[k] != v), None)
        if conflict is not None:
            return _error(
                request.tool_call,
                f"tool returned conflicting immutable identity for chunk {conflict}",
            )
        cells: CellLedger = {}
        if isinstance(parameters, FetchChunkParams):
            known: CellLedger = request.state.get("cells") or {}
            cells = _returned_cells(result, parameters.chunk_id)
            clash = next((r for r, v in cells.items() if r in known and known[r] != v), None)
            if clash is not None:
                return _error(
                    request.tool_call, f"tool returned conflicting content for cell {clash}"
                )
        if not found:
            return result
        update: dict[str, Any] = {"messages": [result], "evidence": found}
        if cells:
            update["cells"] = cells
        return Command(update=update)

    async def awrap_model_call(
        self, request: ModelRequest[Any], handler: ModelHandler
    ) -> ModelResult:
        """Accept, report or return the model's ``final_answer`` under the loop's policy.

        Parameters
        ----------
        request : ModelRequest[Any]
            The model call with the current graph state and the question's
            :class:`ReviewContext`, if one was given.
        handler : ModelHandler
            Calls the model through the inner middleware.

        Returns
        -------
        ModelResult
            The model's response unchanged when it proposes no final answer. Otherwise
            the reply with one tool result per call: an error for each call and no
            structured response when the answer must be revised, or an acknowledgement
            with the accepted report as the structured response, plus its period
            mismatch or withheld-figure record.

        Raises
        ------
        CitedEvidenceReadError
            If the evidence reader fails, so the answer is never judged without its
            evidence; :class:`StopOnSystemFailure` records it as the run's failure.
        """
        response = await handler(request)
        message = next((m for m in response.result if isinstance(m, AIMessage)), None)
        if message is None:
            return response
        finals = [call for call in message.tool_calls if call["name"] == FINAL_ANSWER_NAME]
        if not finals:
            return response
        if len(message.tool_calls) != 1:
            return _rejected(message, message.tool_calls, FINAL_NOT_ALONE)
        (call,) = finals
        context = request.runtime.context
        context = context if isinstance(context, ReviewContext) else ReviewContext()
        evidence = request.state.get("evidence") or {}
        if context.cell_answers:
            cells = request.state.get("cells") or {}
            return await self._review_cells(message, call, evidence, cells, context)
        return await self._review_final(message, call, evidence, context)

    async def _review_final(
        self,
        message: AIMessage,
        call: MessageToolCall,
        ledger: EvidenceLedger,
        context: ReviewContext,
    ) -> ModelResult:
        """Apply ``run_agent``'s final-answer steps to one lone ``final_answer`` call.

        Identity comes first, against this question's ledger; only a ``SUPPORTED``
        answer with matching citations has its cited evidence read and its figures
        checked, in the loop's order and with its report helpers.
        """
        evidence = {
            chunk_id: EvidenceCitation.model_validate(identity)
            for chunk_id, identity in ledger.items()
        }
        proposed = ToolCall(
            call_id=call["id"] or FINAL_ANSWER_NAME,
            name=FINAL_ANSWER_NAME,
            arguments_json=json.dumps(call["args"]),
        )
        answer, problem = validate_final_answer(proposed, evidence)
        if answer is not None and answer.label == "SUPPORTED":
            cited = tuple(citation.chunk_id for citation in answer.citations)
            reader = context.evidence_reader
            try:
                texts = await reader(cited) if reader is not None else {}
            except GraphBubbleUp:
                raise
            except Exception as error:
                failure = safe_runtime_error(error, "cited evidence read")
                raise CitedEvidenceReadError(message, call, failure) from error
            judged = judge_written_answer(answer, texts, context.requested_fiscal_years)
            if judged.report is None:
                answer, problem = None, judged.problem
            else:
                records: dict[str, dict[str, Any] | list[dict[str, Any]]] = {}
                if judged.unit_unverified is not None:
                    records["unit_unverified"] = judged.unit_unverified.model_dump(mode="json")
                if judged.period_mismatch is not None:
                    records["period_mismatch"] = judged.period_mismatch.model_dump(mode="json")
                return _accepted(message, call, judged.report, **records)
        if answer is None:
            return _rejected(message, [call], problem)
        return _accepted(message, call, as_report(answer))

    async def _review_cells(
        self,
        message: AIMessage,
        call: MessageToolCall,
        evidence: EvidenceLedger,
        cells: CellLedger,
        context: ReviewContext,
    ) -> ModelResult:
        """Check one cell-selecting ``final_answer`` and report the answer it assembles.

        The proposal names cells only; the stored cells are read again so a changed
        source ends the run instead of being reported, and the answer is written by the
        application from the stored values.
        """
        try:
            proposal = CellSelectionAnswer.model_validate_json(
                json.dumps(call["args"]), strict=True
            )
        except ValidationError as error:
            problem = f"invalid final_answer: {'; '.join(validation_errors(error))}"
            return _rejected(message, [call], problem)
        reader = context.cell_reader
        refs = tuple(selection.cell_id for selection in proposal.selections)
        try:
            if reader is None:
                raise RuntimeError("no stored cell reader is configured")
            # A ref this question did not fetch is refused by the review below, so it
            # is never read: only fetched cells are read again.
            fetched = bool(refs) and all(ref in cells for ref in refs)
            stored = await reader(refs) if fetched else {}
            verdict = review_cell_selection(
                proposal,
                ledger=cells,
                evidence=evidence,
                stored=stored,
                requested_items=context.requested_items,
                requested_years=context.requested_fiscal_years,
                locale=context.locale,
            )
        except GraphBubbleUp:
            raise
        except Exception as error:
            failure = safe_runtime_error(error, "stored cell read")
            raise CitedEvidenceReadError(message, call, failure) from error
        if verdict.report is None:
            assert verdict.problem is not None
            return _rejected(message, [call], verdict.problem)
        records: dict[str, dict[str, Any] | list[dict[str, Any]]] = {
            "cell_checks": list(verdict.checks)
        }
        if verdict.period_mismatch is not None:
            records["period_mismatch"] = verdict.period_mismatch.model_dump(mode="json")
        if verdict.unit_unverified is not None:
            records["unit_unverified"] = verdict.unit_unverified.model_dump(mode="json")
        return _accepted(message, call, verdict.report, **records)


class StopOnSystemFailure(AgentMiddleware[StopState]):
    """End the run, before another model call, when a filings tool reports a system failure.

    The filings server reports a failure the model cannot correct, such as a database
    error, as a JSON-RPC ``INTERNAL_ERROR`` that the MCP client raises as
    :class:`~mcp.shared.exceptions.MCPError`. This middleware turns that error into an
    error tool result for the failed call and a ``failure`` in graph state, and
    ``before_model`` then ends the run instead of letting the model read the failure as
    an empty search. Every other exception, including ``MCPError`` with another code,
    propagates unchanged.

    The gate's other system failure, a :class:`CitedEvidenceReadError` from reading a
    final answer's cited evidence, ends the run the same way: the final call is
    answered with the redacted error, nothing is accepted and the failure is recorded.

    Notes
    -----
    List it before :class:`ReviewGate` so it wraps the gate and the tool; an error raised
    there never reaches the gate's ledger update. Each invocation is one question:
    ``before_agent`` clears the previous question's failure on a checkpointed thread.
    """

    state_schema = StopState

    async def awrap_model_call(
        self, request: ModelRequest[Any], handler: ModelHandler
    ) -> ModelResult:
        """Return the inner response, or record a cited-evidence read failure instead.

        Parameters
        ----------
        request : ModelRequest[Any]
            The model call and the current graph state.
        handler : ModelHandler
            Calls the model through the inner middleware, including the gate.

        Returns
        -------
        ModelResult
            The inner response unchanged, or, when the gate could not read the cited
            evidence, the reply with an error result for the final call, no structured
            response and the failure's already-redacted message.
        """
        try:
            return await handler(request)
        except CitedEvidenceReadError as error:
            return ExtendedModelResponse(
                model_response=_rejected(error.message, [error.call], error.failure),
                command=Command(update={"failure": error.failure}),
            )

    def before_agent(self, state: StopState, runtime: Runtime[None]) -> dict[str, Any] | None:
        """Start each invocation, one question, without a recorded failure."""
        del state, runtime
        return {"failure": None}

    async def awrap_tool_call(
        self, request: ToolCallRequest, handler: ToolHandler
    ) -> ToolMessage | Command[Any]:
        """Return the inner result, or record a system failure instead of raising it.

        Parameters
        ----------
        request : ToolCallRequest
            The model's call, the bound tool and the current graph state.
        handler : ToolHandler
            Runs the call through the inner middleware and the bound tool.

        Returns
        -------
        ToolMessage | Command[Any]
            The inner result unchanged, or, for a system failure, an update with an
            error result answering the call and the failure's already-redacted message.

        Raises
        ------
        MCPError
            If the call failed with any JSON-RPC error other than ``INTERNAL_ERROR``.
        """
        try:
            return await handler(request)
        except MCPError as error:
            if error.code != INTERNAL_ERROR:
                raise
            call = request.tool_call
            # A failure is recorded even without a message; the state never holds "".
            failure = error.message or "filings tool reported an internal error"
            message = ToolMessage(
                content=f"ERROR: {failure}",
                tool_call_id=call["id"],
                name=call["name"],
                status="error",
            )
            return Command(update={"messages": [message], "failure": failure})

    @hook_config(can_jump_to=["end"])
    def before_model(self, state: StopState, runtime: Runtime[None]) -> dict[str, Any] | None:
        """End the run before the next model call once a system failure was recorded."""
        del runtime
        if state.get("failure") is not None:
            return {"jump_to": "end"}
        clash = next(
            (ref for ref, v in (state.get("cells") or {}).items() if v.get("conflict")), None
        )
        if clash is None:
            return None
        return {"failure": f"conflicting stored content for cell {clash}", "jump_to": "end"}
