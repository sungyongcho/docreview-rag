# M4.3 Tutorial 8 — The runner stays thin

Tutorial 7 left a deliberate hole. Four pure nodes now exist, and not one of them can call anything: `retrieve_node` needs hits it cannot fetch, `grade_node` and `check_node` interpret provider results they cannot request. Purity has to be paid for somewhere, and this file is the bill — with pure nodes, all the I/O collects here. The runner does three things — check the budget, call the provider, hand the result to a node.

If this layer is absent or wrong, the failure mode is concrete: a provider exception escapes to the caller with no record of the tokens it already burned, or a call goes out after the budget is spent. So the whole file serves one testable invariant: **every exit from `run_workflow` is a `RunReport`, and every provider call that actually happened has a `StepTrace` in it.** There are twelve `return` statements in `run_workflow`, and every one of them returns a `RunReport`.

**Prerequisite:** `workflow/prompts.py` and `nodes.py` are written through tutorial 7.

### There are two layers of budget

`WorkflowRequest` carries two budgets: `budget` (the whole workflow) and `provider_budget` (one call). How they interlock is the crux of this document.

Before a node runs, the workflow budget is checked; on passing, each **token** axis of the call receives the smaller of the remaining workflow budget and the provider budget. That is what keeps one call from swallowing the whole token allowance. Cost is the exception — the box below — and missing that exception means being wrong about every call after the first.

> **Concept — two budgets on two different axes**
>
> For tokens the two budgets genuinely cross. The per-call cap is fixed for the whole run, the workflow remainder shrinks as steps spend tokens, and each call receives the minimum of the two — two axes, one `min`.
>
> For cost there is no second axis. `Budget` has four fields — iterations, input tokens, output tokens, wall-clock seconds — and no cost field at all. The subtraction therefore takes everything the run has spent so far away from `provider_budget.max_cost_usd`, which quietly turns the "per-call" cost cap into a cumulative cap over the whole run: the first call may spend up to the full cap, and every later call only gets what the earlier ones left.
>
> Same object, two different semantics across its fields. Reading `ProviderBudget` as "per-call" everywhere is the natural mistake, and it is wrong for exactly one field.

### Failure still reaches the report

When a node fails, the runner **skips every later provider call** and ends the run at once. Be precise about where it ends: all three failure paths return `_failure_report(...)` directly, and `_failure_report` calls `build_run_report` — not `report_node`. The report *node* is for healthy runs; a failed run still gets a full `RunReport`, just not by that route.

So the guarantee this section's title promises is "always a `RunReport`", not "always the report node". The tests measure the difference: on the schema-rejected path the recorded `node_path` is `("retrieve", "grade")`, and on the retrieval-exception path it is `("retrieve",)` — no `"report"` entry in either, yet both runs end with a typed failure report, and no path exits by exception.

### What to define, what to implement, and what to inspect

| Area | Learning action | What to take away |
|---|---|---|
| `make_session_retriever` | **Define the structure** | Making retrieval injectable |
| `_remaining_provider_budget` | **Implement** the budget composition yourself | How the two budgets interlock |
| `_failure_report` and `_node_error` | **Write the field mapping** | The path that moves failure into a report |
| `run_workflow` | **Implement** the execution order yourself | The guard-call-node repetition |
| `app/workflow/__init__.py` | **Define the structure** | The surface M4 publishes |

### 1. Making retrieval injectable

#### Create `app/workflow/runner.py` — module header

**Learning action — define the structure:** M2, M4.1, M4.2, and M4.3 all converge here.

```python
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
    NodeError,
    WorkflowRequest,
    WorkflowState,
    evidence_fetch_k,
    initial_state,
    run_status_for_failure,
)
```

#### Extend `app/workflow/runner.py` — clock and retriever aliases

**Learning action — define the settings schema:** this `Clock` returns a `float`, unlike M3's and M4.1's.

<!-- src: app/workflow/runner.py::Clock,Retriever -->
```python
type Clock = Callable[[], float]
type NodeObserver = Callable[[WorkflowNode, WorkflowState], Awaitable[None]]
type Retriever = Callable[
    [str, int, RetrievalFilters],
    Awaitable[RetrievalResult | Sequence[ChunkHit]],
]
```

**What to look for in the code**

- This `Clock` is `float` seconds and defaults to `time.perf_counter`. M3's and M4.1's clocks are a *different* alias that happens to share the name: `app/llm` defines `Clock` as returning `int` with `time.perf_counter_ns` as the default — integer nanoseconds. The two aliases are unrelated types in different modules; neither imports the other. Here the workflow budget measures seconds via `max_wall_clock_s`, so this clock's unit matches the limit it is compared against, with no conversion step in between to get wrong.

- `NodeObserver` first appears here and the runner's body never explains it, so read it now: an async callable that receives the node name and the committed state after each node. `run_workflow` accepts one as `on_node` and awaits it after every completed transition — that one function type is the entire streaming interface, in place of an event system.

- `Retriever` is deliberately wider than M2's return type: it accepts `RetrievalResult` *or* a plain sequence of `ChunkHit`, so a test can hand the runner a bare list without building the full result wrapper.

#### Extend `app/workflow/runner.py` — retriever and guard

**Learning action — define the structure:** note how `make_session_retriever` hides the session.

<!-- src: app/workflow/runner.py::make_session_retriever,_guard -->
```python
def make_session_retriever(
    session: AsyncSession,
    *,
    provider: RetrievalEmbeddingProvider | None = None,
    candidate_k: int | None = None,
    rrf_k: int = DEFAULT_RRF_K,
) -> Retriever:
    """Close the M2 retrieval service over one caller-owned database session."""

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
```

**What to look for in the code**

- `make_session_retriever` captures the session in a closure. `run_workflow` can call retrieval while knowing nothing about a session — the same shape as M2.7's adapters.
- `_guard` is a thin wrapper over M4.2's `pre_node_budget_guard`, and pulling arguments out of the state is precisely why it exists: the guard takes seven keyword arguments, five of them read off the same two objects every time, and it is called at six places inside `run_workflow`. Without the wrapper each of those six sites would repeat the full argument list, and one drifting copy would be a budget bug no type checker flags.

> **Concept — a closure as dependency injection**
>
> `make_session_retriever` does not return data; it returns the inner async function. That function keeps the variables of its enclosing call alive — the session, the embedding provider, the candidate width, the RRF constant — even after the outer function has returned. Calling it later replays a fully configured retrieval without any of those values traveling as arguments.
>
> The payoff is in the signature: the returned callable matches the three-argument `Retriever` alias, so `run_workflow` receives "a thing that turns a query into hits" and nothing more. Sessions, providers, and tuning constants stay the caller's business, and a test can substitute a four-line async function for the entire M2 stack — the runner cannot tell the difference.
>
> M3's evaluation loop used the same move to bind strategies, and this module's provider docs hide an HTTP client the same way. By now this is the project's standard answer to "how does I/O get in without the core knowing."

### 2. How the two budgets interlock

#### Extend `app/workflow/runner.py` — remaining budget

**Learning action — implement the budget composition:** work out what each of the two `min`s and the one `max` prevents.

<!-- src: app/workflow/runner.py::_remaining_provider_budget -->
```python
def _remaining_provider_budget(
    request: WorkflowRequest,
    state: WorkflowState,
) -> ProviderBudget:
    used_input = sum(step.input_tokens for step in state.steps)
    used_output = sum(step.output_tokens for step in state.steps)
    input_remaining = min(
        request.provider_budget.max_input_tokens,
        request.budget.max_input_tokens - used_input,
    )
    output_remaining = min(
        request.provider_budget.max_output_tokens,
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
```

**What to look for in the code**

- It is `min(provider limit, remaining workflow allowance)` — but the two operands are not symmetric in meaning. The provider limit is a fixed per-call cap that never changes across the run; the workflow remainder shrinks with every step. Early in a run the fixed cap usually wins the `min`; late in a run the remainder does. "Neither can exceed the other" is true and teaches nothing — what matters is *which* operand binds when.
- `<= 0` raises instead of clamping. Reaching that point means **the guard did not run first**, so it is treated as a programming error rather than quietly passing zero along — the box below shows why that is the only way to reach it.
- Cost floors at `max(Decimal(0), ...)` instead of raising. It cannot mirror the token treatment, because the guard never checks cost — `Budget` has no cost field — so an overspent cost cap is a legitimate state at this line, not proof of a skipped guard. The floor is load-bearing too: `ProviderBudget` validates `max_cost_usd` as nonnegative, so without the `max` an overspent run would crash on model construction right here instead of letting the provider refuse the next call cleanly.

> **Concept — why the guard makes the raise unreachable**
>
> The two functions agree on their arithmetic. The pre-node guard blocks entry when an observed sum is greater than or equal to its limit, and this function subtracts exactly those sums from exactly those limits. So when the guard ran and passed, every used total is strictly below its workflow limit, and the subtraction is at least one token. The per-call caps are validated positive by their own model, so the outer `min` is positive too.
>
> That is why the check is a `raise` and not a clamp: it is not handling a runtime condition, it is asserting a call-order contract. The only way to make it fire is to call this function without running the guard first — a bug in the runner, and exactly what an exception is for. The agreement between the guard's greater-or-equal and this function's positive-remainder check is load-bearing; relax either side and a zero-token budget could slip through to a provider.

The value this function returns has a short, sharp lifecycle: born fresh before each provider call, never stored in state, consumed immediately by `provider.complete`. Inside `complete` it shrinks a second time — tutorial 3's repair loop subtracts each attempt's spend before the next request — so the same allowance narrows at two levels: once per node here, once per attempt there.

### 3. Moving failure into a report

#### Extend `app/workflow/runner.py` — failure report

**Learning action — write the field mapping:** note which M4.2 function `_failure_report` calls.

<!-- src: app/workflow/runner.py::_failure_report,_result_hits -->
```python
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
```

**What to look for in the code**

- `run_status_for_failure` turns a workflow failure into M4.2's `RunStatus`. Be precise about the "one place" claim: this *direction* — workflow failure to run status — lives only here. The opposite direction, provider status into a typed workflow failure, happened in `nodes.py` in tutorial 7. One mapping per direction, each in a single place, is the actual invariant.
- `_node_error` substitutes for an empty message. Exceptions whose `str(error)` is empty do occur — a bare `raise RuntimeError()` is enough — and they would otherwise leave a failure record whose message field says nothing.
- `_result_hits` accepts both return shapes. M2.7's `RetrievalResult` is not a list — it is a wrapper carrying `.hits` plus strategy metadata, which is why the first branch unwraps it. A plain sequence also works, while a string is rejected: a string *is* a `Sequence`, and without the explicit check each character would be accepted as a retrieval hit and fail much later with a far worse error.
- `_failure_report` refuses a healthy state: raising when `state.failure` is `None` means the function can never fabricate a failure report out of a successful run.

### 4. The guard-call-node repetition

#### Complete `app/workflow/runner.py` — running the workflow

**Learning action — implement the execution order:** implement the loop over the four nodes yourself. What precedes each node is the point.

<!-- src: app/workflow/runner.py::run_workflow -->
```python
async def run_workflow(
    request: WorkflowRequest,
    *,
    retriever: Retriever,
    provider: LLMProvider,
    clock: Clock = time.perf_counter,
    on_node: NodeObserver | None = None,
) -> RunReport:
    """Execute retrieve, grade, check, and report with one guard before each node.

    ``on_node`` is awaited after every completed node transition with the node
    name and the committed state, so callers can stream progress; observer
    exceptions propagate to the caller instead of becoming node failures.
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
```

**What to look for in the code**

- Each node follows **guard → provider call → node**. The guard comes first, so with no budget the call never happens. Measured: with a zero budget the run refuses before doing anything at all — `node_path == ()`, the report names `blocked_node == "retrieve"`, and the retriever counts zero calls.
- When the guard returns a report, the runner returns it immediately. A `RunReport` with status `budget_exceeded` leaves, and that too is a normal termination. Mid-run the same mechanism works cumulatively: give the run five input tokens, let grade spend exactly five, and the check guard blocks with `resource == "input_tokens"` and `blocked_node == "check"` — after exactly one prompt was sent.
- Once `state.failure` exists, later provider calls are skipped — and the run ends right there with `_failure_report`, not at `report_node`. The retrieve path returns from inside its `except`; the grade and check paths fall through to `if state.failure is not None` immediately below and return. No failure path keeps walking the graph.
- `try/except` wraps the provider call and the node together. A raising node becomes a `NodeError` in the state — and stops the workflow; it does not continue. Measured: a retriever that raises `RuntimeError("database unavailable")` ends the run with status `"error"`, `node_path == ("retrieve",)`, and the full error message preserved in the report.
- A trace attaches to every provider call, and the order matters: the trace is committed to state *before* `grade_node` / `check_node` interprets the result. A node that then rejects or raises still leaves the call's trace behind — the failed call consumed real tokens, and this ordering is what keeps M4.2's totals accurate on the failure path. Measured: on the schema-rejected run, `total_requests == 2` while `len(result.steps) == 1` with `retries == 1` — the repair attempt lives inside the one trace, not lost beside it.

> **Concept — the walrus in the guard line**
>
> `:=` is an assignment expression: it assigns and yields the value in one expression, so `if blocked := ...` both stores the guard's verdict and tests it. The guard returns a report when a limit is exhausted and `None` otherwise, and `None` is falsy — the line reads as "if the guard blocked, return what it built."
>
> Written without it, every guard site becomes two lines — assign, then test — and there are six guard sites in `run_workflow`. The walrus is why the guard discipline costs one visible line per node instead of two, which keeps the repetition small enough to read at a glance.

The docstring calls this "deterministic graph orchestration", yet there is no graph structure anywhere — the obvious alternative is a node list iterated in a loop, or a workflow-graph library. Rejected, because this graph is tiny and its edges are the interesting part: four nodes, two data-driven short-circuits, three exception edges, a guard before every node. Encoded as data, each edge becomes a configuration entry executed by an engine you would then have to read; written straight-line, every one of the twelve exits is a literal `return` you can put a finger on, and the whole control flow is testable by asserting `node_path`. The price is repetition — the guard block six times, the failure exit three times — and the file pays it deliberately: repeating a two-line pattern is cheaper to audit than indirection. A graph engine earns its keep when nodes are added at runtime or run concurrently; nothing here does either.

A second deliberate decision hides in the docstring: `on_node` observer exceptions **propagate** instead of becoming `NodeError`s. The observer is the caller's own code — a UI update, a log line — and a bug in it is the caller's bug; recording it as a workflow failure would file the crash under the wrong owner. The observer test pins the other half of the contract: across a successful run the observer sees the four nodes with step counts `[0, 1, 2, 2]` — retrieval adds no trace, each provider call adds one, and `report` adds none.

Both short-circuit paths — `not state.evidence` and `not state.relevant_chunk_ids` — end with status `"ok"`, not some third status. Finding nothing is a correct answer to some questions, and the report says so honestly: on the empty-retrieval run the label is `NOT_IN_DOCS`, the first reason code is `retrieval_empty`, and `node_path == ("retrieve", "report")` with `steps == ()` and `provider.prompts == ()` — both LLM calls provably skipped, zero tokens spent. Keeping "empty but healthy" apart from `budget_exceeded` and `error` in the status field is what lets a caller alert on the latter two without treating the former as an incident.

`state` is bound twelve times through the function — once by `initial_state`, then every rebinding is either a node's return value or one of five `model_copy(update=...)` calls on the frozen model. Nothing mutates in place, so at any line the current `state` is a complete committed snapshot: what `notify` hands the observer is exactly what the next node will see, and no exception can leave a half-updated state behind. That is tutorial 6's immutability promise doing its paid work.

One thing `run_workflow` pointedly does not do: persist. It returns the `RunReport` and touches no database — the conversion seam built in tutorial 5, `report_to_records` and `persist_run_report`, belongs to the caller, and the success test exercises it explicitly by calling `report_to_records(result)` and asserting the records mirror the report. M5's service layer will own the session and the write; the runner stays usable without a database at all, which is why every test in this file runs against pure fakes.

#### Create `app/workflow/__init__.py` — public API

**Learning action — define the structure:** the surface M5 will depend on. Check that both runner aliases — `NodeObserver` and `Retriever` — are exported: leave `NodeObserver` off and every caller that wants to type its observer has to import from `app.workflow.runner` directly.

```python
"""Typed evidence-checked workflow with deterministic graph orchestration."""

from app.workflow.nodes import check_node, grade_node, report_node, retrieve_node
from app.workflow.prompts import build_check_prompt, build_grade_prompt
from app.workflow.runner import NodeObserver, Retriever, make_session_retriever, run_workflow
from app.workflow.types import (
    DEFAULT_SYSTEM_PROMPT,
    CitationsFiltered,
    ContextTruncated,
    DocumentQuotaApplied,
    DuplicateEvidenceText,
    DuplicateRetrievedChunks,
    EvidenceCitation,
    GradeCoverageIncomplete,
    GradeReferencesFiltered,
    NodeError,
    ProviderFailure,
    RelevanceBelowThreshold,
    RetrievalEmpty,
    SupportedWithoutCitations,
    WorkflowReason,
    WorkflowReport,
    WorkflowRequest,
    WorkflowState,
    evidence_fetch_k,
    initial_state,
)

__all__ = [
    "DEFAULT_SYSTEM_PROMPT",
    "CitationsFiltered",
    "ContextTruncated",
    "DocumentQuotaApplied",
    "DuplicateEvidenceText",
    "DuplicateRetrievedChunks",
    "EvidenceCitation",
    "GradeCoverageIncomplete",
    "GradeReferencesFiltered",
    "NodeError",
    "ProviderFailure",
    "RelevanceBelowThreshold",
    "RetrievalEmpty",
    "NodeObserver",
    "Retriever",
    "SupportedWithoutCitations",
    "WorkflowReason",
    "WorkflowReport",
    "WorkflowRequest",
    "WorkflowState",
    "build_check_prompt",
    "build_grade_prompt",
    "check_node",
    "evidence_fetch_k",
    "grade_node",
    "initial_state",
    "make_session_retriever",
    "report_node",
    "retrieve_node",
    "run_workflow",
]
```

### Focused tests and the contracts they protect

```bash
uv run pytest tests/workflow/test_04_nodes.py tests/workflow/test_05_runner.py -q
```

The runner suite doubles as the measured record behind this page's claims. The success path pins `node_path == ("retrieve", "grade", "check", "report")` while `steps` holds only `("grade", "check")` — four nodes walked, two provider calls made, the cleanest proof that iterations count nodes, steps count provider calls, and the two are *supposed* to differ. The same test pins `total_requests == 2` and `total_input_tokens == 20`. And the retriever fake asserts it receives `k == 15`, not the request's default of 5: `evidence_fetch_k` widens the request by the over-fetch factor of 3 so selection can still fill its slots after dedup and the per-document quota remove hits — tutorial 6 owns that arithmetic.

| Value the test breaks | Contract being protected |
|---|---|
| A citation of a chunk ID absent from evidence | An invented ID never leaves as a citation. |
| `SUPPORTED` with no surviving citation | An ungrounded supported answer is downgraded. |
| Budget exhaustion mid-workflow | Later calls are skipped and a `budget_exceeded` report is returned. |
| An exception raised by a node | It becomes a `NodeError` and survives in the report. |
| A provider budget larger than the workflow budget | One call never swallows the whole allowance. |

### What you should be able to explain now

- **Why are there two budgets, and how do they interlock?**
  - **Answer:** The workflow budget caps the whole run and the provider budget caps one call; each call receives the smaller of its provider limit and the workflow allowance still remaining. That is the token story only — cost has no workflow-level field, so the per-call cost cap is drawn down cumulatively across the run.
- **Why does `_remaining_provider_budget` raise on `<= 0`?**
  - **Answer:** A nonpositive remainder means the pre-node guard was skipped, so it is treated as a programming error instead of passing an invalid budget to the provider.
- **Why does it matter that a failed node still reaches the report node?**
  - **Answer:** The current runner does not do that: it returns `_failure_report` immediately instead of routing to `report_node`. The direct path still produces a `RunReport` containing the typed failure, so the run does not end silently.
- **Why must a failed provider call still leave a trace?**
  - **Answer:** The failed call still consumed tokens, money, and time, and its trace keeps both totals and diagnosis accurate.
- **Why does `_result_hits` reject a string?**
  - **Answer:** A string is a Python `Sequence` and would otherwise pass the shape check while its characters were mistaken for retrieval hits.

---

[← Previous: Prompts and nodes](07-prompts-nodes.md) · [Module overview](../03-build.md)
