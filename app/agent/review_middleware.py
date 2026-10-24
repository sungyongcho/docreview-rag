"""Keep the agent loop's question-scoped tool rules around ``create_agent`` tool calls.

``run_agent`` validates every tool call strictly, reads only chunks the current
question retrieved and records the complete source identity of each result. Under
``create_agent`` the tools node runs the tools, so :class:`ReviewGate` applies the
same rules as tool-call middleware while execution itself stays with the bound tool,
such as an MCP adapter tool. :class:`StopOnSystemFailure` keeps the loop's other
rule: a system failure the model cannot correct ends the run instead of reaching the
model as though nothing were found.
"""

from collections.abc import Awaitable, Callable
import json
from typing import Annotated, Any, NotRequired

from langchain.agents.middleware import (
    AgentMiddleware,
    AgentState,
    ToolCallRequest,
    hook_config,
)
from langchain_core.messages import ToolMessage
from langgraph.runtime import Runtime
from langgraph.types import Command
from mcp.shared.exceptions import MCPError
from mcp.types import INTERNAL_ERROR
from pydantic import BaseModel, ValidationError

from app.agent.tools.filings import FetchChunkParams
from app.agent.tools.registry import Tool, ToolRegistry
from app.contracts.evidence import EvidenceCitation
from app.llm.decoding import validation_errors

type EvidenceLedger = dict[int, dict[str, Any]]
type ToolHandler = Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]]


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
    return left or right


class ReviewState(AgentState[Any]):
    """Agent state with the identities this question's tools returned, by chunk id."""

    evidence: Annotated[NotRequired[EvidenceLedger], merge_evidence]


class StopState(ReviewState):
    """Review state plus the system failure that ended this question, if any."""

    failure: Annotated[NotRequired[str | None], keep_first_failure]


def _error(request: ToolCallRequest, text: str) -> ToolMessage:
    """Answer one tool call with a correctable error the model reads as its result."""
    call = request.tool_call
    return ToolMessage(
        content=f"ERROR: {text}", tool_call_id=call["id"], name=call["name"], status="error"
    )


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


class ReviewGate(AgentMiddleware[ReviewState]):
    """Strict arguments, a question-scoped fetch guard and an evidence ledger for tool calls.

    Parameters
    ----------
    contracts : ToolRegistry
        The app's own tools. Only their parameter models and evidence extraction are
        used; their ``run`` functions are never called, because the wrapped tool,
        such as an MCP adapter tool, executes the call.

    Notes
    -----
    The ledger lives in graph state (``ReviewState.evidence``), never on the
    middleware, so one gate can serve concurrent runs and a checkpointed thread
    keeps its ledger with the rest of its state. Each invocation is one question:
    ``before_agent`` clears the ledger, so identities retrieved for an earlier
    question on the same thread cannot authorize a fetch. Rejections are error tool
    results the model can correct. Failures the model cannot correct, such as a
    successful result without structured content, raise instead.
    """

    state_schema = ReviewState

    def __init__(self, contracts: ToolRegistry) -> None:
        """Keep the app contracts for validation and evidence extraction; never run their tools."""
        super().__init__()
        self.contracts = contracts

    def before_agent(self, state: ReviewState, runtime: Runtime[None]) -> dict[str, Any] | None:
        """Start each invocation, one question, with an empty evidence ledger."""
        del state, runtime
        return {"evidence": None}

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
            return _error(request, parameters)
        evidence: EvidenceLedger = request.state.get("evidence") or {}
        if isinstance(parameters, FetchChunkParams) and parameters.chunk_id not in evidence:
            return _error(
                request,
                f"chunk {parameters.chunk_id} was not retrieved in this question; search first",
            )

        result = await handler(request)
        if not isinstance(result, ToolMessage) or result.status == "error":
            return result
        found = {c.chunk_id: c.model_dump(mode="json") for c in _returned_identities(tool, result)}
        conflict = next((k for k, v in found.items() if k in evidence and evidence[k] != v), None)
        if conflict is not None:
            return _error(
                request, f"tool returned conflicting immutable identity for chunk {conflict}"
            )
        if not found:
            return result
        return Command(update={"messages": [result], "evidence": found})


class StopOnSystemFailure(AgentMiddleware[StopState]):
    """End the run, before another model call, when a filings tool reports a system failure.

    The filings server reports a failure the model cannot correct, such as a database
    error, as a JSON-RPC ``INTERNAL_ERROR`` that the MCP client raises as
    :class:`~mcp.shared.exceptions.MCPError`. This middleware turns that error into an
    error tool result for the failed call and a ``failure`` in graph state, and
    ``before_model`` then ends the run instead of letting the model read the failure as
    an empty search. Every other exception, including ``MCPError`` with another code,
    propagates unchanged.

    Notes
    -----
    List it before :class:`ReviewGate` so it wraps the gate and the tool; an error raised
    there never reaches the gate's ledger update. Each invocation is one question:
    ``before_agent`` clears the previous question's failure on a checkpointed thread.
    """

    state_schema = StopState

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
            message = ToolMessage(
                content=f"ERROR: {error.message}",
                tool_call_id=call["id"],
                name=call["name"],
                status="error",
            )
            return Command(update={"messages": [message], "failure": error.message})

    @hook_config(can_jump_to=["end"])
    def before_model(self, state: StopState, runtime: Runtime[None]) -> dict[str, Any] | None:
        """End the run before the next model call once a system failure was recorded."""
        del runtime
        return {"jump_to": "end"} if state.get("failure") else None
