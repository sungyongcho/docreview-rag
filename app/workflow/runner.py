"""Thin deterministic orchestration over four pure workflow nodes."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
import time

from pydantic import BaseModel

from app.llm.provider import LLMProvider
from app.llm.schemas import (
    AnswerDecision,
    ProviderBudget,
    ProviderResult,
    RelevanceJudgment,
)
from app.observability.budget import pre_node_budget_guard
from app.observability.stages import stage
from app.observability.trace import step_trace_from_provider_result
from app.observability.types import (
    JsonObject,
    JsonValue,
    RunReport,
    WorkflowNode,
    build_run_report,
    derived_totals,
    validate_elapsed_seconds,
)
from app.release.ai_allowance import AIAllowanceError
from app.retrieval.service import RetrievalResult
from app.retrieval.types import ChunkHit, RetrievalFilters
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
type Retriever = Callable[[str, int, RetrievalFilters], Awaitable[RetrievalResult]]


def _elapsed(clock: Clock, started: float) -> float:
    """Return elapsed seconds, rejecting a clock that is not monotonic finite floats."""
    elapsed = validate_elapsed_seconds(clock()) - started
    if elapsed < 0:
        raise ValueError("workflow clock must be monotonic")
    return elapsed


def _reasons_json(state: WorkflowState) -> list[JsonValue]:
    """Serialize the degradation history a report carries alongside its outcome."""
    return [reason.model_dump(mode="json") for reason in state.reasons]


def _used_tokens(state: WorkflowState) -> tuple[int, int, int, int]:
    """Return total and priced-detail input tokens already consumed."""
    totals = derived_totals(node_path=state.node_path, steps=state.steps)
    return (
        totals["total_input_tokens"],
        totals["total_output_tokens"],
        totals["total_cached_input_tokens"],
        totals["total_cache_write_input_tokens"],
    )


def _effective_provider_budget(request: WorkflowRequest) -> ProviderBudget:
    """Combine the provider and workflow ceilings into the one the run may spend.

    The workflow ``Budget`` and the ``ProviderBudget`` both cap tokens. Enforcing them
    separately lets a call be admitted against one limit and then clamped by the other,
    which truncates generation instead of refusing. Reducing them to a single allowance
    first means the gate and the per-call cap always agree.

    Both ceilings are positive by the time this runs: the pre-node guard refuses a
    provider node whose workflow token budget is already spent, and ``ProviderBudget``
    cannot hold a non-positive limit.
    """
    return ProviderBudget(
        max_input_tokens=min(
            request.provider_budget.max_input_tokens,
            request.budget.max_input_tokens,
        ),
        max_output_tokens=min(
            request.provider_budget.max_output_tokens,
            request.budget.max_output_tokens,
        ),
        max_cost_usd=request.provider_budget.max_cost_usd,
        pricing=request.provider_budget.pricing,
    )


def _provider_allowance(
    request: WorkflowRequest,
    state: WorkflowState,
    node: GradeOrCheckNode,
) -> ProviderBudget | ProviderFailure:
    """Return the allowance the next provider call may spend, or a typed refusal.

    Parameters
    ----------
    request : WorkflowRequest
        Original cumulative provider and workflow limits.
    state : WorkflowState
        State whose traces contain usage already consumed.
    node : GradeOrCheckNode
        Provider-backed node that would execute next.

    Returns
    -------
    ProviderBudget | ProviderFailure
        Positive remaining allowance, or the typed refusal for an exhausted boundary.

    Notes
    -----
    ``ProviderBudget.exhausted_by`` is the single definition of exhaustion, so this gate
    and the provider's own boundary read the same limits; they differ only in what they
    judge. This gate asks inclusively whether another request may start on the usage
    already traced, while the provider judges each completed attempt exclusively and
    projects a prompt's size before sending it. The refusal returned here has the shape
    of the provider's own pre-request refusal: zero attempts and the ``BudgetExceeded``
    evidence from which ``failed`` derives the budget source.
    """
    used_input, used_output, used_cached, used_cache_write = _used_tokens(state)
    effective = _effective_provider_budget(request)
    if exceeded := effective.exhausted_by(
        input_tokens=used_input,
        output_tokens=used_output,
        cached_input_tokens=used_cached,
        cache_write_input_tokens=used_cache_write,
        attempts=0,
        inclusive=True,
    ):
        return ProviderFailure(
            node=node,
            status="budget_exceeded",
            attempts=0,
            details=(f"{exceeded.which}: used={exceeded.used} limit={exceeded.limit}",),
            budget=exceeded,
        )
    spent = effective.pricing.estimate(
        used_input,
        used_output,
        cached_input_tokens=used_cached,
        cache_write_input_tokens=used_cache_write,
    )
    return ProviderBudget(
        max_input_tokens=effective.max_input_tokens - used_input,
        max_output_tokens=effective.max_output_tokens - used_output,
        max_cost_usd=effective.max_cost_usd - spent,
        pricing=effective.pricing,
    )


def _traced[OutputT: BaseModel](
    state: WorkflowState,
    result: ProviderResult[OutputT],
    node: WorkflowNode,
) -> WorkflowState:
    """Append the raw trace for one provider call before its node interprets it."""
    trace = step_trace_from_provider_result(result, step=len(state.steps) + 1, node=node)
    return state.model_copy(update={"steps": (*state.steps, trace)})


def _committed(
    state: WorkflowState,
    node: WorkflowNode,
    failure: ProviderFailure | NodeError,
) -> WorkflowState:
    """Commit one typed failure as the node's outcome and keep it in the history."""
    return state.model_copy(
        update={
            "failure": failure,
            "reasons": (*state.reasons, failure),
            "node_path": (*state.node_path, node),
        }
    )


def _committed_failure(
    state: WorkflowState,
    node: WorkflowNode,
    error: Exception,
) -> WorkflowState:
    """Record one node exception without losing its type or an empty message."""
    message = str(error)
    if not message.strip():
        message = f"{node} failed without an error message"
    failure = NodeError(node=node, error_type=type(error).__name__, message=message)
    return _committed(state, node, failure)


def _result_hits(result: RetrievalResult) -> tuple[ChunkHit, ...]:
    """Return the hits of the retrieval result a retriever must produce."""
    if not isinstance(result, RetrievalResult):
        raise TypeError("retriever must return RetrievalResult")
    return result.hits


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
        Optional observer called after every committed node transition, including one
        that records a failure.

    Returns
    -------
    RunReport
        Complete success or typed failure report for every handled path.

    Raises
    ------
    TypeError
        If the request or provider violate the caller contract.
    ValueError
        If the clock is non-finite or moves backwards.

    Notes
    -----
    Every terminating report carries the degradation history under ``reasons``, so a
    failed run is as auditable as a successful one. A failure whose cause the workflow
    can describe is reported rather than raised; only a broken caller contract escapes.
    Observer exceptions propagate instead of becoming node failures.
    """
    if not isinstance(request, WorkflowRequest):
        raise TypeError("request must be a WorkflowRequest")
    if not isinstance(provider, LLMProvider):
        raise TypeError("provider must implement LLMProvider")

    state = initial_state(request)
    started = validate_elapsed_seconds(clock())

    async def notify(node: WorkflowNode, committed: WorkflowState) -> None:
        """Report one committed node to the optional observer."""
        if on_node is not None:
            await on_node(node, committed)

    def blocked_by_budget(current: WorkflowState, node: WorkflowNode) -> RunReport | None:
        """Apply the cumulative budget guard, keeping the run's reasons in its refusal."""
        refusal = pre_node_budget_guard(
            run_id=current.run_id,
            node=node,
            budget=request.budget,
            elapsed_seconds=_elapsed(clock, started),
            system_prompt=current.system_prompt,
            node_path=current.node_path,
            steps=current.steps,
        )
        if refusal is None:
            return None
        report: JsonObject = {**(refusal.report or {}), "reasons": _reasons_json(current)}
        return build_run_report(
            run_id=refusal.run_id,
            status=refusal.status,
            total_time_seconds=refusal.total_time_seconds,
            system_prompt=refusal.system_prompt,
            node_path=refusal.node_path,
            steps=refusal.steps,
            report=report,
        )

    def failed(current: WorkflowState) -> RunReport:
        """Build the terminating report for a state that already holds a failure."""
        if current.failure is None:
            raise ValueError("failure report requires a typed workflow failure")
        reason = current.failure.model_dump(mode="json")
        if isinstance(current.failure, ProviderFailure) and current.failure.budget is not None:
            resource = current.failure.budget.which
            source = "provider_budget"
            if resource in {"input_tokens", "output_tokens"}:
                name = "max_" + resource
                configured = getattr(request.provider_budget, name)
                requested = getattr(request.budget, name)
                source = (
                    "provider_budget"
                    if configured < requested
                    else "run_limits"
                    if requested < configured
                    else "both"
                )
            reason["budget_source"] = source
        report: JsonObject = {
            "reason": reason,
            "reasons": _reasons_json(current),
        }
        return build_run_report(
            run_id=current.run_id,
            status=run_status_for_failure(current.failure),
            total_time_seconds=_elapsed(clock, started),
            system_prompt=current.system_prompt,
            node_path=current.node_path,
            steps=current.steps,
            report=report,
        )

    async def finish(current: WorkflowState) -> RunReport:
        """Run the terminal report node and close the run."""
        if refusal := blocked_by_budget(current, "report"):
            return refusal
        async with stage("report") as measurement:
            try:
                current = report_node(current)
            except Exception as error:
                measurement.failed = True
                current = _committed_failure(current, "report", error)
                await notify("report", current)
                return failed(current)
        await notify("report", current)
        return build_run_report(
            run_id=current.run_id,
            status="ok",
            total_time_seconds=_elapsed(clock, started),
            system_prompt=current.system_prompt,
            node_path=current.node_path,
            steps=current.steps,
            report=current.report.model_dump(mode="json") if current.report else None,
        )

    async def complete_node(
        current: WorkflowState,
        node: GradeOrCheckNode,
    ) -> WorkflowState | RunReport:
        """Guard, call the provider, trace the call, and commit one graded node.

        A refusal the runner makes before the call is committed exactly like one the
        provider returns: the node joins the path, its stage ends failed, and the
        observer sees the failure.
        """
        if refusal := blocked_by_budget(current, node):
            return refusal
        allowance = _provider_allowance(request, current, node)
        if isinstance(allowance, ProviderFailure):
            async with stage(node) as measurement:
                measurement.failed = True
                current = _committed(current, node, allowance)
            await notify(node, current)
            return failed(current)
        async with stage(node) as measurement:
            try:
                if node == "grade":
                    graded = await provider.complete(
                        build_grade_prompt(current), RelevanceJudgment, allowance
                    )
                    current = grade_node(_traced(current, graded, node), graded)
                else:
                    decided = await provider.complete(
                        build_check_prompt(current), AnswerDecision, allowance
                    )
                    current = check_node(_traced(current, decided, node), decided)
            except AIAllowanceError:
                raise
            except Exception as error:
                current = _committed_failure(current, node, error)
            measurement.failed = current.failure is not None
        await notify(node, current)
        return failed(current) if current.failure is not None else current

    if refusal := blocked_by_budget(state, "retrieve"):
        return refusal
    async with stage("retrieve") as measurement:
        try:
            retrieval = await retriever(state.query, evidence_fetch_k(state), state.filters)
        except AIAllowanceError:
            raise
        except Exception as error:
            state = _committed_failure(state, "retrieve", error)
            await notify("retrieve", state)
            measurement.failed = True
            return failed(state)
        state = retrieve_node(state, _result_hits(retrieval))
    await notify("retrieve", state)

    if not state.evidence:
        return await finish(state)

    graded = await complete_node(state, "grade")
    if isinstance(graded, RunReport):
        return graded
    state = graded

    if not state.relevant_chunk_ids:
        return await finish(state)

    checked = await complete_node(state, "check")
    if isinstance(checked, RunReport):
        return checked
    return await finish(checked)
