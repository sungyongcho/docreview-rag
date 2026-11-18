"""Keep the agent loop's question-scoped rules around ``create_agent`` tool and model calls.

``run_agent`` validates every tool call strictly, reads only chunks the current
question retrieved and records the complete source identity of each result. Under
``create_agent`` the tools node runs the tools, so :class:`ReviewGate` applies the
same rules as tool-call middleware while execution itself stays with the bound tool,
such as an MCP adapter tool. Its model-call hook hands the structured ``final_answer``
the model proposes to the same review as the loop (:mod:`app.review`): the answer
stands alone, its citations match the ledger, and its figures pass the same figure
check, so it is accepted, reported as a period mismatch or withheld as ``UNVERIFIED``,
or returned to the model for revision; this module only turns that decision into
LangChain messages and state updates. :class:`StopOnSystemFailure` keeps the loop's other rule: a
system failure the model cannot correct ends the run instead of reaching the model as
though nothing were found.
"""

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
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
from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    ToolCall as MessageToolCall,
    ToolMessage,
)
from langgraph.errors import GraphBubbleUp
from langgraph.runtime import Runtime
from langgraph.types import Command
from mcp.shared.exceptions import MCPError
from mcp.types import INTERNAL_ERROR

from app.agent.loop import final_answer_spec
from app.contracts.answers import CellSelectionAnswer
from app.contracts.evidence import EvidenceCitation
from app.review.cell_answer import review_cell_answer
from app.review.evidence import CellReader, EvidenceReader
from app.review.final_answer import FINAL_NOT_ALONE, EvidenceReadError, FinalReview
from app.review.ledger import cell_record, citation_records, ledger_failure, merge_identities
from app.review.policy import POLICIES
from app.review.written_answer import review_written_answer
from app.tools.filings import FetchChunkParams, unretrieved_fetch
from app.tools.registry import (
    FINAL_ANSWER_NAME,
    Tool,
    ToolRegistry,
    safe_runtime_error,
    validate_arguments,
)

type EvidenceLedger = dict[int, dict[str, Any]]
type CellLedger = dict[str, dict[str, Any]]
type ToolHandler = Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]]
type ModelHandler = Callable[[ModelRequest[Any]], Awaitable[ModelResponse[Any]]]
type ModelResult = ModelResponse[Any] | AIMessage | ExtendedModelResponse[Any]


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
        Language the application writes its reports in, in either answer mode.
    cell_reader : CellReader | None
        App-internal reader of the selected cells as stored now; required in cell mode.
    """

    requested_fiscal_years: tuple[int, ...] = ()
    evidence_reader: EvidenceReader | None = None
    cell_answers: bool = False
    requested_items: frozenset[str] = frozenset()
    locale: Literal["en", "ko"] = field(kw_only=True)
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


def _returned_cells(message: ToolMessage, chunk_id: int) -> CellLedger:
    """Return the ledger records of the stored cells one fetch result carries."""
    artifact = message.artifact if isinstance(message.artifact, dict) else {}
    structured = artifact.get("structured_content")
    catalog = structured.get("table") if isinstance(structured, dict) else None
    if not isinstance(catalog, dict):
        return {}
    match catalog.get("status"):
        case "not_table" | "missing_records" | "stale_reading":
            return {}
        case "available":
            pass
        case _:
            raise ValueError("unknown cell catalog status")
    records: CellLedger = {}
    for cell in catalog["cells"]:
        records = merge_identities(records, {cell["ref"]: cell_record(cell, catalog, chunk_id)})
    return records


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

    ``period_mismatch`` and ``withheld`` hold the JSON form of
    :class:`~app.contracts.figures.PeriodMismatch` and
    :class:`~app.contracts.figures.FiguresWithheld` when the accepted report is a period
    mismatch or withholds its figures; otherwise they are ``None``.
    """

    evidence: Annotated[NotRequired[EvidenceLedger], merge_identities]
    cells: Annotated[NotRequired[CellLedger], merge_identities]
    cell_checks: NotRequired[list[dict[str, Any]] | None]
    period_mismatch: NotRequired[dict[str, Any] | None]
    withheld: NotRequired[dict[str, Any] | None]


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


def _decided(
    message: AIMessage, call: MessageToolCall, review: FinalReview, *, cells: bool
) -> ModelResponse | ExtendedModelResponse:
    """Return a rejected final call to the model, or end on the accepted report.

    An accepted call is acknowledged under its id, with the ``period_mismatch`` and
    ``withheld`` records of a report the review qualified as state updates, and with
    ``cell_checks`` whenever the answer selected cells. A plain written answer needs no
    update, because each question starts with all of them cleared.
    """
    report = review.report
    if report is None:
        assert review.problem is not None
        return _rejected(message, [call], review.problem)
    records: dict[str, dict[str, Any] | list[dict[str, Any]]] = {}
    if cells:
        records["cell_checks"] = list(review.cell_checks)
    if review.period_mismatch is not None:
        records["period_mismatch"] = review.period_mismatch.model_dump(mode="json")
    if review.withheld is not None:
        records["withheld"] = review.withheld.model_dump(mode="json")
    acknowledgement = ToolMessage(
        content=f"final_answer accepted as {report.label}",
        tool_call_id=call["id"],
        name=call["name"],
    )
    response = ModelResponse(result=[message, acknowledgement], structured_response=report)
    if not records:
        return response
    return ExtendedModelResponse(model_response=response, command=Command(update=records))


def _returned_identities(tool: Tool[Any], message: ToolMessage) -> tuple[EvidenceCitation, ...]:
    """Extract the complete source identities from a successful tool result.

    Raises
    ------
    ValueError
        If the result carries no structured content.
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
    return found


def retrieval_returned(messages: Sequence[AnyMessage], contracts: ToolRegistry) -> bool:
    """Whether a retrieval tool returned a result in this question.

    A question starts at its last human message. A retrieval tool is a registered tool
    with an evidence extractor; its non-error result counts even with no hits, while
    an error result, including one the gate refused, does not.
    """
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return False
        if (
            isinstance(message, ToolMessage)
            and message.status != "error"
            and message.name in contracts.names
            and contracts.get(message.name).evidence_ids is not None
        ):
            return True
    return False


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
            "withheld": None,
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
            An error result when the arguments are invalid or the fetch was not
            retrieved in this question; otherwise the tool's result, wrapped in a ledger
            update when it returned new identities.

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
        parameters = validate_arguments(tool, request.tool_call["args"])
        if isinstance(parameters, str):
            return _error(request.tool_call, parameters)
        evidence: EvidenceLedger = request.state.get("evidence") or {}
        unretrieved = unretrieved_fetch(parameters, evidence)
        if unretrieved is not None:
            return _error(request.tool_call, unretrieved)

        result = await handler(request)
        if not isinstance(result, ToolMessage) or result.status == "error":
            return result
        try:
            found = citation_records(_returned_identities(tool, result))
        except Exception as error:
            raise MCPError(
                code=INTERNAL_ERROR,
                message=safe_runtime_error(error, f"tool {tool.name} evidence extraction"),
            ) from error
        cells: CellLedger = {}
        if isinstance(parameters, FetchChunkParams):
            try:
                cells = _returned_cells(result, parameters.chunk_id)
            except Exception as error:
                raise MCPError(
                    code=INTERNAL_ERROR,
                    message=safe_runtime_error(error, f"tool {tool.name} cell catalog extraction"),
                ) from error
        failure = ledger_failure(merge_identities(evidence, found)) or ledger_failure(
            merge_identities(request.state.get("cells"), cells), cells=True
        )
        if failure is not None:
            raise MCPError(code=INTERNAL_ERROR, message=failure)
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
            :class:`ReviewContext` with its resolved locale.
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
        if not isinstance(context, ReviewContext):
            raise ValueError("review context with resolved locale is required")
        ledger: EvidenceLedger = request.state.get("evidence") or {}
        arguments_json = json.dumps(call["args"])
        try:
            if context.cell_answers:
                review = await review_cell_answer(
                    arguments_json,
                    ledger=request.state.get("cells") or {},
                    evidence=ledger,
                    cell_reader=context.cell_reader,
                    requested_items=context.requested_items,
                    requested_years=context.requested_fiscal_years,
                    searched=retrieval_returned(
                        request.state.get("messages") or [], self.contracts
                    ),
                    locale=context.locale,
                    passthrough=(GraphBubbleUp,),
                )
            else:
                review = await review_written_answer(
                    arguments_json,
                    {
                        key: EvidenceCitation.model_validate(record)
                        for key, record in ledger.items()
                    },
                    evidence_reader=context.evidence_reader,
                    requested_fiscal_years=context.requested_fiscal_years,
                    locale=context.locale,
                    policy=POLICIES["prebuilt"],
                    passthrough=(GraphBubbleUp,),
                )
        except EvidenceReadError as error:
            raise CitedEvidenceReadError(message, call, error.failure) from error
        return _decided(message, call, review, cells=context.cell_answers)


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
        failure = ledger_failure(state.get("evidence") or {}) or ledger_failure(
            state.get("cells") or {}, cells=True
        )
        if failure is None:
            return None
        return {"failure": failure, "jump_to": "end"}
