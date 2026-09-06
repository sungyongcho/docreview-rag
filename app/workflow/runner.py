"""Thin deterministic orchestration over four pure workflow nodes."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from decimal import Decimal
import time

from sqlalchemy.ext.asyncio import AsyncSession

from app.llm import AnswerDecision, LLMProvider, ProviderBudget, RelevanceJudgment
from app.observability import (
    RunReport,
    WorkflowNode,
    build_run_report,
    pre_node_budget_guard,
    step_trace_from_provider_result,
)
from app.retrieval import (
    DEFAULT_RRF_K,
    ChunkHit,
    EmbeddingProvider as RetrievalEmbeddingProvider,
    RetrievalFilters,
    RetrievalResult,
    retrieve,
)
from app.workflow.nodes import check_node, grade_node, report_node, retrieve_node
from app.workflow.prompts import build_check_prompt, build_grade_prompt
from app.workflow.types import (
    GradeOrCheckNode,
    NodeError,
    ProviderFailure,
    WorkflowRequest,
    WorkflowState,
    evidence_fetch_k,
    initial_state,
    run_status_for_failure,
)

type Clock = Callable[[], float]
type NodeObserver = Callable[[WorkflowNode, WorkflowState], Awaitable[None]]
type Retriever = Callable[
    [str, int, RetrievalFilters],
    Awaitable[RetrievalResult | Sequence[ChunkHit]],
]


def make_session_retriever(
    session: AsyncSession,
    *,
    provider: RetrievalEmbeddingProvider | None = None,
    candidate_k: int | None = None,
    rrf_k: int = DEFAULT_RRF_K,
) -> Retriever:
    """Close the retrieval service over one caller-owned database session.

    Parameters
    ----------
    session : AsyncSession
        Session reused for every retrieval in the workflow run.
    provider : RetrievalEmbeddingProvider | None
        Optional vector embedding provider.
    candidate_k : int | None
        Optional candidate-pool override.
    rrf_k : int
        Reciprocal-rank-fusion constant.

    Returns
    -------
    Retriever
        Async callable matching the workflow retrieval boundary.

    Notes
    -----
    Session and provider ownership remain with the caller.
    """

    async def retrieve_for_workflow(
        query: str,
        k: int,
        filters: RetrievalFilters,
    ) -> RetrievalResult:
        return await retrieve(
            session,
            query,
            provider=provider,
            k=k,
            candidate_k=candidate_k,
            filters=filters,
            rrf_k=rrf_k,
        )

    return retrieve_for_workflow


def _elapsed(clock: Clock, started: float) -> float:
    current = clock()
    if isinstance(current, bool) or not isinstance(current, float):
        raise ValueError("workflow clock must return float seconds")
    elapsed = current - started
    if elapsed < 0:
        raise ValueError("workflow clock must be monotonic")
    return elapsed


def _guard(
    state: WorkflowState,
    request: WorkflowRequest,
    node: WorkflowNode,
    *,
    elapsed_seconds: float,
) -> RunReport | None:
    return pre_node_budget_guard(
        run_id=state.run_id,
        node=node,
        budget=request.budget,
        elapsed_seconds=elapsed_seconds,
        system_prompt=state.system_prompt,
        node_path=state.node_path,
        steps=state.steps,
    )


def _remaining_provider_budget(
    request: WorkflowRequest,
    state: WorkflowState,
) -> ProviderBudget:
    """Return the smaller cumulative provider and workflow allowance.

    Parameters
    ----------
    request : WorkflowRequest
        Original workflow and provider limits.
    state : WorkflowState
        State whose traces contain usage already consumed.

    Returns
    -------
    ProviderBudget
        Positive remaining token allowance and nonnegative remaining cost.

    Raises
    ------
    ValueError
        If a pre-node guard was skipped after token capacity was exhausted.
    """
    used_input = sum(step.input_tokens for step in state.steps)
    used_output = sum(step.output_tokens for step in state.steps)
    input_remaining = min(
        request.provider_budget.max_input_tokens - used_input,
        request.budget.max_input_tokens - used_input,
    )
    output_remaining = min(
        request.provider_budget.max_output_tokens - used_output,
        request.budget.max_output_tokens - used_output,
    )
    if input_remaining <= 0 or output_remaining <= 0:
        raise ValueError("pre-node budget guard must run before computing provider allowance")
    spent = request.provider_budget.pricing.estimate(used_input, used_output)
    cost_remaining = max(Decimal(0), request.provider_budget.max_cost_usd - spent)
    return ProviderBudget(
        max_input_tokens=input_remaining,
        max_output_tokens=output_remaining,
        max_cost_usd=cost_remaining,
        pricing=request.provider_budget.pricing,
    )


def _provider_budget_failure(
    request: WorkflowRequest,
    state: WorkflowState,
    node: GradeOrCheckNode,
) -> ProviderFailure | None:
    """Return a typed failure when no cumulative provider allowance remains.

    Parameters
    ----------
    request : WorkflowRequest
        Original cumulative provider limits and prices.
    state : WorkflowState
        State whose traces contain prior provider usage.
    node : GradeOrCheckNode
        Provider-backed node that would execute next.

    Returns
    -------
    ProviderFailure | None
        Typed pre-call refusal at an exhausted boundary, otherwise ``None``.

    Notes
    -----
    Positive-priced cost blocks on equality. Zero-priced providers may continue with
    a zero cost ceiling.
    """
    used_input = sum(step.input_tokens for step in state.steps)
    used_output = sum(step.output_tokens for step in state.steps)
    spent = request.provider_budget.pricing.estimate(used_input, used_output)
    if used_input >= request.provider_budget.max_input_tokens:
        details = (
            f"input_tokens: used={used_input} limit={request.provider_budget.max_input_tokens}",
        )
    elif used_output >= request.provider_budget.max_output_tokens:
        details = (
            f"output_tokens: used={used_output} limit={request.provider_budget.max_output_tokens}",
        )
    else:
        pricing = request.provider_budget.pricing
        priced = pricing.input_per_million_usd > 0 or pricing.output_per_million_usd > 0
        if not priced or spent < request.provider_budget.max_cost_usd:
            return None
        details = (
            f"estimated_cost_usd: used={spent} limit={request.provider_budget.max_cost_usd}",
        )
    return ProviderFailure(node=node, status="budget_exceeded", details=details)


def _failure_report(
    state: WorkflowState,
    *,
    elapsed_seconds: float,
) -> RunReport:
    if state.failure is None:
        raise ValueError("failure report requires a typed workflow failure")
    return build_run_report(
        run_id=state.run_id,
        status=run_status_for_failure(state.failure),
        total_time_seconds=elapsed_seconds,
        system_prompt=state.system_prompt,
        node_path=state.node_path,
        steps=state.steps,
        report={"failure": state.failure.model_dump(mode="json")},
    )


def _node_error(node: WorkflowNode, error: Exception) -> NodeError:
    message = str(error)
    if not message.strip():
        message = f"{node} failed without an error message"
    return NodeError(
        node=node,
        error_type=type(error).__name__,
        message=message,
    )


def _result_hits(result: RetrievalResult | Sequence[ChunkHit]) -> tuple[ChunkHit, ...]:
    if isinstance(result, RetrievalResult):
        return result.hits
    if isinstance(result, str | bytes | bytearray) or not isinstance(result, Sequence):
        raise TypeError("retriever must return RetrievalResult or a sequence of ChunkHit")
    return tuple(result)


async def run_workflow(
    request: WorkflowRequest,
    *,
    retriever: Retriever,
    provider: LLMProvider,
    clock: Clock = time.perf_counter,
    on_node: NodeObserver | None = None,
) -> RunReport:
    """Execute the guarded retrieve, grade, check, and report sequence.

    Parameters
    ----------
    request : WorkflowRequest
        Validated query, filters, and cumulative limits.
    retriever : Retriever
        Async retrieval boundary.
    provider : LLMProvider
        Shared structured-output provider for grade and check.
    clock : Clock
        Monotonic seconds clock used for budgets and reports.
    on_node : NodeObserver | None
        Optional observer called after committed node transitions.

    Returns
    -------
    RunReport
        Complete success or typed failure report for every handled path.

    Raises
    ------
    TypeError
        If request, provider, retrieval output, or clock values violate boundaries.
    ValueError
        If the clock is non-finite, moves backwards, or an invariant fails.

    Notes
    -----
    Workflow and provider budgets are checked before provider-backed nodes. Observer
    exceptions propagate instead of becoming node failures.
    """
    if not isinstance(request, WorkflowRequest):
        raise TypeError("request must be a WorkflowRequest")
    if not isinstance(provider, LLMProvider):
        raise TypeError("provider must implement LLMProvider")

    async def notify(node: WorkflowNode, committed: WorkflowState) -> None:
        if on_node is not None:
            await on_node(node, committed)

    state = initial_state(request)
    started = clock()
    if isinstance(started, bool) or not isinstance(started, float):
        raise ValueError("workflow clock must return float seconds")

    if blocked := _guard(state, request, "retrieve", elapsed_seconds=_elapsed(clock, started)):
        return blocked
    try:
        retrieval = await retriever(state.query, evidence_fetch_k(state), state.filters)
        state = retrieve_node(state, _result_hits(retrieval))
    except Exception as error:
        failure = _node_error("retrieve", error)
        state = state.model_copy(
            update={
                "failure": failure,
                "reasons": (*state.reasons, failure),
                "node_path": (*state.node_path, "retrieve"),
            }
        )
        return _failure_report(state, elapsed_seconds=_elapsed(clock, started))
    await notify("retrieve", state)

    if not state.evidence:
        if blocked := _guard(state, request, "report", elapsed_seconds=_elapsed(clock, started)):
            return blocked
        state = report_node(state)
        await notify("report", state)
        return build_run_report(
            run_id=state.run_id,
            status="ok",
            total_time_seconds=_elapsed(clock, started),
            system_prompt=state.system_prompt,
            node_path=state.node_path,
            steps=state.steps,
            report=state.report.model_dump(mode="json") if state.report else None,
        )

    if blocked := _guard(state, request, "grade", elapsed_seconds=_elapsed(clock, started)):
        return blocked
    if failure := _provider_budget_failure(request, state, "grade"):
        state = state.model_copy(update={"failure": failure, "reasons": (*state.reasons, failure)})
        return _failure_report(state, elapsed_seconds=_elapsed(clock, started))
    try:
        grade_result = await provider.complete(
            build_grade_prompt(state),
            RelevanceJudgment,
            _remaining_provider_budget(request, state),
        )
        grade_trace = step_trace_from_provider_result(
            grade_result,
            step=len(state.steps) + 1,
            node="grade",
        )
        state = state.model_copy(update={"steps": (*state.steps, grade_trace)})
        state = grade_node(state, grade_result)
    except Exception as error:
        failure = _node_error("grade", error)
        state = state.model_copy(
            update={
                "failure": failure,
                "reasons": (*state.reasons, failure),
                "node_path": (*state.node_path, "grade"),
            }
        )
    if state.failure is not None:
        return _failure_report(state, elapsed_seconds=_elapsed(clock, started))
    await notify("grade", state)

    if not state.relevant_chunk_ids:
        if blocked := _guard(state, request, "report", elapsed_seconds=_elapsed(clock, started)):
            return blocked
        state = report_node(state)
        await notify("report", state)
        return build_run_report(
            run_id=state.run_id,
            status="ok",
            total_time_seconds=_elapsed(clock, started),
            system_prompt=state.system_prompt,
            node_path=state.node_path,
            steps=state.steps,
            report=state.report.model_dump(mode="json") if state.report else None,
        )

    if blocked := _guard(state, request, "check", elapsed_seconds=_elapsed(clock, started)):
        return blocked
    if failure := _provider_budget_failure(request, state, "check"):
        state = state.model_copy(update={"failure": failure, "reasons": (*state.reasons, failure)})
        return _failure_report(state, elapsed_seconds=_elapsed(clock, started))
    try:
        check_result = await provider.complete(
            build_check_prompt(state),
            AnswerDecision,
            _remaining_provider_budget(request, state),
        )
        check_trace = step_trace_from_provider_result(
            check_result,
            step=len(state.steps) + 1,
            node="check",
        )
        state = state.model_copy(update={"steps": (*state.steps, check_trace)})
        state = check_node(state, check_result)
    except Exception as error:
        failure = _node_error("check", error)
        state = state.model_copy(
            update={
                "failure": failure,
                "reasons": (*state.reasons, failure),
                "node_path": (*state.node_path, "check"),
            }
        )
    if state.failure is not None:
        return _failure_report(state, elapsed_seconds=_elapsed(clock, started))
    await notify("check", state)

    if blocked := _guard(state, request, "report", elapsed_seconds=_elapsed(clock, started)):
        return blocked
    state = report_node(state)
    await notify("report", state)
    return build_run_report(
        run_id=state.run_id,
        status="ok",
        total_time_seconds=_elapsed(clock, started),
        system_prompt=state.system_prompt,
        node_path=state.node_path,
        steps=state.steps,
        report=state.report.model_dump(mode="json") if state.report else None,
    )
