# M5.1 Tutorial 1 — Routes must not know the domain

A route's job is kept minimal.

1. **Validate** the HTTP request. 2. Call **one injected service method**. 3. **Project** the domain result into a strict resource.

That is all. A route does not know how retrieval works or how many workflow nodes exist.

**Prerequisite:** M4 is complete and `uv run pytest tests/workflow -q` passes.

### Without this boundary

When transport and domain mix, this happens.

Retrieval parameter defaults creep into request parsing, route handlers learn a little of the workflow's control flow, and exception handling deals with HTTP status codes and domain failures at once.

Then **testing gets hard.** Testing retrieval logic requires standing up an HTTP client, and there is no telling a transport error from a domain error.

Keep the boundary and HTTP becomes **replaceable**. Add gRPC later or call it from a queue worker and everything below `ApiServices` is unchanged.

### Why the response schema is separate

`EvidenceHit` resembles M2's `ChunkHit` with slightly different fields. Why not just return `ChunkHit`?

Because **exposing the internal model makes that model the API contract.** Add a debugging field to `ChunkHit` later and it ships in the API response; remove a field and clients break.

So a projection layer exists. `index_text` being absent from the response is deliberate too — `body` and `context_header` are already there, so it is redundant, and clients have no need to know the internal indexing scheme.

### What to define, what to implement, and what to inspect

This document builds one file, `app/api/schemas.py`, in five steps. Routes and error handling come next.

| Area | Learning action | What to take away |
|---|---|---|
| Value vocabulary and `StrictApiModel` | **Define the settings schema** | The strictness of the API boundary |
| `ApiError` and `ErrorResponse` | **Write the model declarations** | Why failure gets one envelope |
| `EvidenceHit` | **Write the field mapping, then inspect the boundary conversion** | The gap between internal model and public resource |
| The request/response pairs | **Write the model declarations** | Each operation's input and output contract |
| `RunResponse` | **Implement** the discriminated union yourself | Carrying success and failure in one response |

### 1. The strictness of the API boundary

#### Create `app/api/schemas.py` — module header and value vocabulary

**Learning action — define the settings schema:** note that this file imports no M2 or M4 types.

```python
"""Strict HTTP request and response schemas for the M5 API."""

from __future__ import annotations

from datetime import datetime
import json
import math
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StrictFloat,
    StrictInt,
    StrictStr,
    TypeAdapter,
)
from pydantic.functional_validators import field_validator, model_validator

from app.observability import Budget, RunReport, StepTrace, WorkflowNode
from app.retrieval import ChunkHit, RetrievalFilters
from app.workflow import NodeError, ProviderFailure, WorkflowReport

NonBlank = Annotated[StrictStr, Field(min_length=1)]
PositiveInt = Annotated[StrictInt, Field(gt=0)]
NonnegativeInt = Annotated[StrictInt, Field(ge=0)]
NonnegativeFloat = Annotated[StrictFloat, Field(ge=0, allow_inf_nan=False)]
RunId = Annotated[StrictStr, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")]
SourceSha256 = Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]
JsonObject = dict[str, JsonValue]

```

**What to look for in the code**

- No domain module is imported. An API schema depending on the domain lets a domain change break the contract.
- The value aliases share names with M2's and M4's but are **redefined**. It looks like duplication, and it is what keeps the boundary independent.

#### Extend `app/api/schemas.py` — the error envelope

**Learning action — write the model declarations:** note why error responses share one shape.

<!-- src: app/api/schemas.py::StrictApiModel,ErrorResponse -->
```python
class StrictApiModel(BaseModel):
    """Frozen, non-coercing base for every API body."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ValidationIssue(StrictApiModel):
    """One stable request-validation detail without echoing submitted values."""

    location: tuple[StrictStr | StrictInt, ...]
    message: NonBlank
    error_type: NonBlank


class ApiError(StrictApiModel):
    """Machine-readable HTTP failure shared by all routes."""

    code: Annotated[StrictStr, Field(pattern=r"^[a-z][a-z0-9_]*$")]
    message: NonBlank
    details: tuple[ValidationIssue, ...] = ()

    @field_validator("message", mode="after")
    @classmethod
    def reject_blank_message(cls, value: str) -> str:
        """Reject error envelopes that cannot explain their failure."""
        if not value.strip():
            raise ValueError("error message must not be blank")
        return value


class ErrorResponse(StrictApiModel):
    """Top-level typed error envelope."""

    error: ApiError
```

**What to look for in the code**

- Every failure leaves as one `ErrorResponse`. A client does not parse differently per status code.
- `ValidationIssue` carries the field path and message. Emitting FastAPI's default errors verbatim would leak internal type names.
- `code` is a string identifier. Messages may change; the code is the contract.

### 2. The gap between internal model and public resource

#### Extend `app/api/schemas.py` — evidence hit and the retrieve operation

**Learning action — write the field mapping, then inspect the boundary conversion:** put `EvidenceHit` beside M2's `ChunkHit` and find the missing fields.

<!-- src: app/api/schemas.py::EvidenceHit,RetrieveResponse -->
```python
class EvidenceHit(StrictApiModel):
    """One retrieved evidence unit with complete source identity."""

    chunk_id: PositiveInt
    doc_id: NonBlank
    item: NonBlank | None
    kind: Literal["text", "table"]
    citation: NonBlank
    start_char: NonnegativeInt
    end_char: PositiveInt
    source_sha256: SourceSha256
    body: NonBlank
    context_header: StrictStr
    score: Annotated[StrictFloat, Field(allow_inf_nan=False)]

    @field_validator("doc_id", "item", "citation", "body", mode="after")
    @classmethod
    def reject_blank_text(cls, value: str | None) -> str | None:
        """Reject whitespace-only evidence identity and content."""
        if value is not None and not value.strip():
            raise ValueError("evidence text must not be blank")
        return value

    @model_validator(mode="after")
    def validate_span(self) -> Self:
        """Require a nonempty half-open source span."""
        if self.end_char <= self.start_char:
            raise ValueError("end_char must be greater than start_char")
        return self

    @classmethod
    def from_chunk_hit(cls, hit: ChunkHit) -> Self:
        """Project the public evidence fields from one validated retrieval hit."""
        if not isinstance(hit, ChunkHit):
            raise TypeError("evidence responses require ChunkHit values")
        return cls(
            chunk_id=hit.chunk_id,
            doc_id=hit.doc_id,
            item=hit.item,
            kind=hit.kind,
            citation=hit.citation,
            start_char=hit.start_char,
            end_char=hit.end_char,
            source_sha256=hit.source_sha256,
            body=hit.body,
            context_header=hit.context_header,
            score=hit.score,
        )


class RetrieveRequest(StrictApiModel):
    """One bounded evidence retrieval request."""

    query: NonBlank
    k: Annotated[StrictInt, Field(gt=0, le=100)] = 5
    filters: RetrievalFilters = Field(default_factory=RetrievalFilters)

    @field_validator("query", mode="after")
    @classmethod
    def reject_blank_query(cls, value: str) -> str:
        """Reject queries containing only whitespace."""
        if not value.strip():
            raise ValueError("query must not be blank")
        return value


class RetrieveResponse(StrictApiModel):
    """Ranked evidence for one query."""

    query: NonBlank
    results: tuple[EvidenceHit, ...]
```

**What to look for in the code**

- `index_text` is absent. It is reconstructible from `body` and `context_header`, and the internal indexing scheme is not the client's concern.
- Yet `start_char`, `end_char`, and `source_sha256` are present. M1.3's provenance contract reaches the API — a client can reopen the source.
- `score` does leave. M2.7 hid the **component** scores while publishing the fused one. It is needed to explain ranking, and with only one unit there is nothing to misread.

#### Extend `app/api/schemas.py` — document, ingest, and review operations

**Learning action — write the model declarations:** note which limit each request model carries.

<!-- src: app/api/schemas.py::DocumentResource,ReviewRequest -->
```python
class DocumentResource(StrictApiModel):
    """One ingested filing and its source identity."""

    doc_id: NonBlank
    ticker: NonBlank
    cik: PositiveInt
    fiscal_year: PositiveInt
    form: NonBlank
    filing_date: NonBlank
    report_period: NonBlank
    accession: NonBlank
    url: NonBlank
    parse_status: Literal["parsed", "needs_profile_update"]
    source_length: PositiveInt
    source_sha256: SourceSha256
    chunk_count: NonnegativeInt


class DocumentListResponse(StrictApiModel):
    """Deterministically ordered document resources."""

    documents: tuple[DocumentResource, ...]


class IngestRequest(StrictApiModel):
    """One explicit local manifest ingestion request."""

    manifest_path: NonBlank
    expected_documents: PositiveInt = 20
    chunk_batch_size: PositiveInt = 500

    @field_validator("manifest_path", mode="after")
    @classmethod
    def reject_blank_path(cls, value: str) -> str:
        """Reject an absent or whitespace-only manifest path."""
        if not value.strip():
            raise ValueError("manifest_path must not be blank")
        return value


class IngestResponse(StrictApiModel):
    """Committed corpus row counts from synchronous ingestion."""

    documents: NonnegativeInt
    chunks: NonnegativeInt


class ReviewRequest(StrictApiModel):
    """One synchronous evidence-checked workflow request."""

    query: NonBlank
    k: Annotated[StrictInt, Field(gt=0, le=100)] = 5
    filters: RetrievalFilters = Field(default_factory=RetrievalFilters)
    budget: Budget = Field(default_factory=Budget)
    max_context_chars: NonnegativeInt = 12_000

    @field_validator("query", mode="after")
    @classmethod
    def reject_blank_query(cls, value: str) -> str:
        """Reject review requests without an actual question."""
        if not value.strip():
            raise ValueError("query must not be blank")
        return value
```

**What to look for in the code**

- `ReviewRequest` carries a budget. A client may set workflow limits, but the values are schema-validated.
- `IngestRequest` accepts `expected_documents`. M1.4's fail-closed contract is exposed as an API parameter.

### 3. Carrying success and failure in one response

#### Extend `app/api/schemas.py` — the run response

**Learning action — implement the discriminated union:** note how `RunFailure` is discriminated and how `report` relates to `failure`.

<!-- src: app/api/schemas.py::BudgetLimitFailure,RunResponse -->
```python
class BudgetLimitFailure(StrictApiModel):
    """A workflow node blocked by one exhausted cumulative resource."""

    code: Literal["budget_exceeded"] = "budget_exceeded"
    resource: Literal["iterations", "input_tokens", "output_tokens", "wall_clock_s"]
    limit: StrictInt | StrictFloat
    observed: StrictInt | StrictFloat
    blocked_node: WorkflowNode

    @model_validator(mode="after")
    def validate_values(self) -> Self:
        """Keep budget evidence finite and nonnegative."""
        if any(
            isinstance(value, float) and not math.isfinite(value)
            for value in (self.limit, self.observed)
        ):
            raise ValueError("budget values must be finite")
        if self.limit < 0 or self.observed < 0:
            raise ValueError("budget values must be nonnegative")
        return self


RunFailure = Annotated[
    BudgetLimitFailure | ProviderFailure | NodeError,
    Field(discriminator="code"),
]
_RUN_FAILURE_ADAPTER = TypeAdapter(RunFailure)


class RunResponse(StrictApiModel):
    """One completed workflow run or its structured terminal failure."""

    run_id: RunId
    status: Literal["ok", "budget_exceeded", "schema_rejected", "error"]
    iterations: NonnegativeInt
    total_requests: NonnegativeInt
    total_input_tokens: NonnegativeInt
    total_output_tokens: NonnegativeInt
    total_time_seconds: NonnegativeFloat
    system_prompt: NonBlank
    node_path: tuple[WorkflowNode, ...]
    report: WorkflowReport | None
    failure: RunFailure | None

    @model_validator(mode="after")
    def validate_terminal_shape(self) -> Self:
        """Keep successful reports and terminal failures mutually exclusive."""
        if self.status == "ok":
            if self.report is None or self.failure is not None:
                raise ValueError("successful runs require only a workflow report")
        elif self.failure is None or self.report is not None:
            raise ValueError("failed runs require only a typed failure")
        return self

    @classmethod
    def from_run_report(cls, run: RunReport) -> Self:
        """Validate an observability report into its public resource shape."""
        if not isinstance(run, RunReport):
            raise TypeError("run responses require a RunReport")
        payload = run.report
        report: WorkflowReport | None = None
        failure: RunFailure | None = None
        if run.status == "ok":
            if payload is None:
                raise ValueError("successful run report payload is missing")
            report = WorkflowReport.model_validate_json(
                json.dumps(payload, allow_nan=False, separators=(",", ":"), sort_keys=True)
            )
        else:
            if payload is None:
                raise ValueError("failed run report payload is missing")
            raw_failure = payload.get("failure", payload.get("reason"))
            if raw_failure is None:
                raise ValueError("failed run report has no typed failure")
            failure = _RUN_FAILURE_ADAPTER.validate_json(
                json.dumps(raw_failure, allow_nan=False, separators=(",", ":"), sort_keys=True)
            )
        return cls(
            run_id=run.run_id,
            status=run.status,
            iterations=run.iterations,
            total_requests=run.total_requests,
            total_input_tokens=run.total_input_tokens,
            total_output_tokens=run.total_output_tokens,
            total_time_seconds=run.total_time_seconds,
            system_prompt=run.system_prompt,
            node_path=run.node_path,
            report=report,
            failure=failure,
        )
```

**What to look for in the code**

- `_RUN_FAILURE_ADAPTER` is a module-level `TypeAdapter` — built once, for the same reason as M3.1's loader.
- `RunResponse` exposes M4's four terminal states directly. `budget_exceeded` leaves as a **normal response**, not an HTTP 500. Exceeding a budget is not a server error.
- `report` and `failure` are exclusive. The rule M4.1's `ProviderResult` established is set up again at the API boundary.

#### Complete `app/api/schemas.py` — trace and evaluation resources

**Learning action — write the model declarations:** note what drops out when a trace leaves through the API.

<!-- src: app/api/schemas.py::TraceListResponse,EvalListResponse -->
```python
class TraceListResponse(StrictApiModel):
    """Ordered raw provider traces for one persisted run."""

    run_id: RunId
    traces: tuple[StepTrace, ...]

    @model_validator(mode="after")
    def validate_trace_order(self) -> Self:
        """Require trace steps to be contiguous and start at one."""
        expected = tuple(range(1, len(self.traces) + 1))
        if tuple(trace.step for trace in self.traces) != expected:
            raise ValueError("trace steps must be contiguous and start at 1")
        return self


class EvalResultResource(StrictApiModel):
    """One persisted retrieval evaluation result."""

    result_id: PositiveInt
    suite: NonBlank
    config: JsonObject
    metrics: dict[NonBlank, StrictFloat]
    raw_artifact_path: NonBlank
    created_at: datetime

    @field_validator("suite", "raw_artifact_path", mode="after")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        """Reject evaluation identity fields containing only whitespace."""
        if not value.strip():
            raise ValueError("evaluation text must not be blank")
        return value

    @field_validator("metrics", mode="after")
    @classmethod
    def validate_metrics(cls, values: dict[str, float]) -> dict[str, float]:
        """Reject blank metric names and nonfinite values."""
        if any(not key.strip() for key in values):
            raise ValueError("metric names must not be blank")
        if any(not math.isfinite(value) for value in values.values()):
            raise ValueError("metric values must be finite")
        return values


class EvalListResponse(StrictApiModel):
    """Newest persisted evaluation resources first."""

    results: tuple[EvalResultResource, ...]
```

**What to look for in the code**

- Traces are public. A client can see which provider calls happened — what M4.2 recorded gets used here.
- Evaluation results are read without rerunning. It only reads the `eval_results` M3 stored.

### What you should be able to explain now

- **What becomes the contract if an internal model is returned directly?**
  - **Answer:** Every internal field and future model change becomes part of the public API, including fields never intended for clients.
- **Why is `index_text` dropped from the response?**
  - **Answer:** It is redundant with `body` and `context_header`, and the internal indexing representation is not a client concern.
- **Why does M2.7 hide component scores while the fused score is published?**
  - **Answer:** Component scores use different units and can be misread, while the single fused score directly explains the final ranking.
- **Why is `budget_exceeded` not an HTTP 500?**
  - **Answer:** Budget exhaustion is an expected, typed workflow outcome rather than a malfunction of the HTTP server.
- **Why does the API schema import no domain types?**
  - **Answer:** The premise is false. Request and response models directly use `RetrievalFilters`, `Budget`, `WorkflowNode`, `WorkflowReport`, and `StepTrace`, so the current transport contract is coupled to those domain definitions.

---

[Module overview](../03-build.md) · [Next: Errors and dependencies →](02-errors-deps.md)
