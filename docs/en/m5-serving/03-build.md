# M5 Build — A Surface Another Program Can Trust

## Until now it was a Python function

After M4 you can call `run_workflow()` and get an evidence-bound answer. But only inside a Python process.

Now it opens over HTTP. Then M6's demo UI and external clients can use it too.

Bolting on FastAPI routes seems like all it takes, but opening a boundary brings new problems.

- requests arrive **concurrently**; sessions and budgets must not mix
- input is **untrusted**; any JSON can arrive
- on failure **internal details must not leak** — a stack trace or SQL in the response is trouble
- M4's four terminal states have to **map to HTTP codes**

## Checkpoint map

| Order | Checkpoint | Goal | Canonical files |
|---:|---|---|---|
| 1 | M5.1 | Add a strict typed HTTP boundary | `app/api/` |
| 2 | M5.2 | Add deterministic runtime entrypoints | `app/config.py`, `app/api/runtime.py`, `app/main.py`, `app/cli.py` |
| 3 | M5.3 | Prove production composition across M2, M4, CLI, and HTTP | Existing M5 canonical files |
| 4 | M5.4 | Stream run progress over server-sent events | `app/api/routes/stream.py` |

It is built the way a request travels. The canonical files come before the command that exercises them, so a clean learning branch never has to import tomorrow's module.


---

## Tutorial — built in six sittings

M5 produces seventeen files and 1,647 lines of source. Each document targets **under 30 minutes** to read and implement.

| Document | Checkpoint | Files built | Approx. |
|---|---|---|---|
| [1. API schemas](tutorial/01-schemas.md) | M5.1 | `api/schemas.py` | 30 min |
| [2. Errors and dependencies](tutorial/02-errors-deps.md) | M5.1 | `api/errors.py`, `deps.py`, `__init__.py` | 25 min |
| [3. Routes](tutorial/03-routes.md) | M5.1 | seven `api/routes/`, `routes/__init__.py`, `app.py` | 25 min |
| [4. Runtime assembly](tutorial/04-runtime.md) | M5.2 | `api/runtime.py`, `main.py` | 30 min |
| [5. CLI and assembly checks](tutorial/05-cli.md) | M5.2–M5.3 | `cli.py` | 30 min |
| [6. Streaming](tutorial/06-streaming.md) | M5.4 | `api/routes/stream.py` | 25 min |

Follow them in order. Do not move on while a stretch's focused test is failing.

---

## Final quality gate

```bash
uv run pytest -o addopts="" -q
uv run ruff check .
uv run ruff format --check app/api app/cli.py app/main.py tests/api
uv run python scripts/check_doc_code.py docs/en/m5-serving/03-build.md docs/ko/m5-serving/03-build.md
git diff --check
```

Expected result: every command exits with status 0. Record the measured test total rather than copying an older count; no paid call belongs to this gate.

---

## Starting conditions

Install the locked environment and verify the M4 boundary first.

```bash
uv sync --group dev
uv run pytest tests/workflow -q
```

The tests in this chapter run through the FastAPI test client rather than a real server. The database and the LLM are replaced by injected doubles, so nothing is billed.

## Not all six stretches are equally hard

M5 contains no new algorithm. It is all boundaries and arrangement, so it reads differently from the previous chapters.

| Kind | Documents | Learning action |
|---|---|---|
| Contract declaration | 1 | **Write the model declarations** — confirm why public schemas differ from domain types |
| Boundary rules | 2 | **Implement** the error mapping yourself — spend the time here |
| Arrangement | 3, 4, 5, 6 | **Write the structure, then review the call order** |

If time is short, linger on document 2. It decides **what leaves in a response and what must not**, and a leak there makes the quality of everything else irrelevant.

## Concepts you meet here first

**Why public schemas and domain types are separated.** Serializing M2's `ChunkHit` or M4's workflow state straight to JSON is convenient. It also means the API contract breaks the moment an internal type changes, and fields that should stay internal leak outward. So the boundary carries its own response schemas and states the conversion explicitly.

**Dependency injection.** A route function never constructs its own database session or workflow runner; it receives what the framework supplies. Tests can put a double in that slot, and M2.7's rule that one request owns one session carries through to the HTTP boundary unchanged.

## M5.1 — Typed HTTP resources

Routes must not know the domain. They accept a request, validate it, hand it to an injected dependency, and convert the result into a public schema. The error path needs the most care here: let an exception through and a stack trace or SQL rides out in the response body. So M4's terminal states get an explicit mapping onto HTTP codes, and anything outside that mapping closes as a 500 carrying no internal detail.

**Document:** [1. API schemas](tutorial/01-schemas.md) through [3. Routes](tutorial/03-routes.md) · **Passing:** `uv run pytest tests/api/test_01_schemas.py tests/api/test_02_errors.py -q`

## M5.2 — Deterministic runtime entrypoints

`import app.main` alone must do nothing. If importing a module connects to a database or reads configuration, tests are dragged around by their environment and import order changes behaviour. So assembly gathers inside a factory function and configuration is read in exactly one place. The CLI uses the same factory, so calling over HTTP and calling from the command line return the same evidence.

**Document:** [4. Runtime assembly](tutorial/04-runtime.md), [5. CLI](tutorial/05-cli.md) · **Passing:** `uv run pytest tests/api/test_06_runtime.py tests/api/test_07_cli.py -q`

## M5.3 — Prove the production composition

Finally, confirm that M2's retrieval, M4's workflow, the CLI, and HTTP really do line up. The previous two checkpoints verified each piece separately; this one checks that the pieces run together on the same configuration and the same session rule.

**Document:** [5. CLI](tutorial/05-cli.md) · **Passing:** `uv run pytest tests/api/test_08_integration.py -q`

## M5.4 — Stream the run while it runs

The synchronous review endpoint answers once, after one retrieval and two guarded LLM calls. M5.4 adds `POST /review/stream`: the runner reports each committed node through an observer, the service seam carries it, and the route bridges it into server-sent events — `node` progress, the terminal `report`, and an explicit `done`. Failed runs stay structured reports; `error` is reserved for exceptions that produced no run at all.

**Document:** [6. Streaming](tutorial/06-streaming.md) · **Passing:** `uv run pytest tests/api/test_09_stream.py -q`

## What you should be able to explain now

- **What goes wrong when a domain type is serialized directly as a response?**
  - **Answer:** The internal type becomes the public API contract, so internal field changes can leak data or break clients unintentionally.
- **Why does an unmapped exception close as a 500 with nothing in the body?**
  - **Answer:** The current handler does not return an empty body. It sends a generic `internal_error` JSON envelope with status 500, while omitting the original exception message so paths, SQL, or credentials do not leak.
- **What exactly becomes unstable in tests when `import` alone has side effects?**
  - **Answer:** Test collection and even isolated imports begin depending on live databases or providers, so failures occur before the test can install controlled dependencies.
- **What justifies the CLI and HTTP sharing one factory?**
  - **Answer:** The current CLI and HTTP entry points do not share one factory: the CLI assembles retrieval and ingestion functions directly. Their behavior can therefore drift unless parity tests or a future shared composition boundary keep them aligned.
- **How does the rule that one request owns one session survive at the HTTP boundary?**
  - **Answer:** Routes call an injected service, and each service method opens and closes its own session for that request instead of sharing a route-level or global session.

## What this module hands to the next one

M5 completes a **working service**. It can be called over HTTP or the CLI, and either way returns the same evidence.

| What M5 produced | Receiver | What happens there |
|---|---|---|
| the `/retrieve` and `/review` endpoints | **M6** | called by the demo UI |
| the public `EvidenceHit` schema | **M6** | evidence card rendering |
| `/health` | **M7** | container health check |
| the OpenAPI document | **M6, M7** | the client contract |
| `app/cli.py` exit codes | **M7** | branching in deploy scripts |
| the `create_app()` factory | **M7** | container entrypoint |

The next two chapters differ in character. **M6 builds the screen people look at.** There, this project's central claim — "every piece of evidence can be checked against the source" — takes visible form. **M7 is deployment**, where the reason container packaging was deliberately deferred in M5 becomes clear.

## Machine-verified final reference

The chapters above are the build path. The generated section below is a byte-for-byte final reference against `reference_revision`, not a shortcut to use before M5.1. Use it after the checkpoints to compare the files you accumulated; if they differ, repair the checkpoint where the difference first appeared.

<!-- complete-files:start -->
## Reference baseline — the complete canonical files

Create or replace the canonical paths below directly. Do not create `_mine.py` or another learner-copy module. The earlier excerpts explain individual decisions; the blocks in this section are the finished files to compare against once a checkpoint is done. Preserve the shown type annotations and English comments; `pyproject.toml` is the authoritative Ruff policy.

### M5.1 — Complete checkpoint

#### Create or replace `app/api/__init__.py`

<!-- file: app/api/__init__.py -->
```python
"""Strict, injected synchronous HTTP boundary for M5."""

from app.api.app import create_api_app
from app.api.deps import ApiServices, get_api_services
from app.api.errors import ApiProblemError, bad_request, install_error_handlers, not_found
from app.api.routes import api_router
from app.api.runtime import RuntimeApiServices
from app.api.schemas import (
    ApiError,
    BudgetLimitFailure,
    DocumentListResponse,
    DocumentResource,
    ErrorResponse,
    EvalListResponse,
    EvalResultResource,
    EvidenceHit,
    IngestRequest,
    IngestResponse,
    RetrieveRequest,
    RetrieveResponse,
    ReviewRequest,
    RunResponse,
    TraceListResponse,
    ValidationIssue,
)

router = api_router

__all__ = [
    "ApiError",
    "ApiProblemError",
    "ApiServices",
    "BudgetLimitFailure",
    "DocumentListResponse",
    "DocumentResource",
    "ErrorResponse",
    "EvalListResponse",
    "EvalResultResource",
    "EvidenceHit",
    "IngestRequest",
    "IngestResponse",
    "RetrieveRequest",
    "RetrieveResponse",
    "ReviewRequest",
    "RuntimeApiServices",
    "RunResponse",
    "TraceListResponse",
    "ValidationIssue",
    "api_router",
    "bad_request",
    "create_api_app",
    "get_api_services",
    "install_error_handlers",
    "not_found",
    "router",
]
```

#### Create or replace `app/api/schemas.py`

<!-- file: app/api/schemas.py -->
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


class StreamNodeEvent(StrictApiModel):
    """One completed workflow node reported while a streamed review is running."""

    node: WorkflowNode
    evidence_count: NonnegativeInt
    relevant_count: NonnegativeInt
    step_count: NonnegativeInt


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

#### Create or replace `app/api/deps.py`

<!-- file: app/api/deps.py -->
```python
"""Injected application-service seam for the synchronous HTTP boundary."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from app.api.errors import ApiProblemError
from app.api.schemas import (
    DocumentResource,
    EvalResultResource,
    IngestRequest,
    RetrieveRequest,
    ReviewRequest,
)
from app.ingestion.seed import SeedResult
from app.observability import RunReport, StepTrace
from app.retrieval import ChunkHit, RetrievalResult
from app.workflow import NodeObserver


class ApiServices(Protocol):
    """All domain operations required by the seven HTTP resources."""

    async def retrieve(
        self,
        request: RetrieveRequest,
    ) -> RetrievalResult | Sequence[ChunkHit]:
        """Return ranked evidence without performing HTTP work."""
        ...

    async def list_documents(self) -> Sequence[DocumentResource]:
        """Return document resources in deterministic order."""
        ...

    async def ingest(self, request: IngestRequest) -> SeedResult:
        """Run one synchronous local-manifest ingestion operation."""
        ...

    async def review(self, request: ReviewRequest) -> RunReport:
        """Run and persist one complete evidence-checked workflow."""
        ...

    async def review_stream(
        self,
        request: ReviewRequest,
        on_node: NodeObserver,
    ) -> RunReport:
        """Run one reviewed workflow while reporting each completed node."""
        ...

    async def get_run(self, run_id: str) -> RunReport | None:
        """Return one persisted run or null when it does not exist."""
        ...

    async def get_traces(self, run_id: str) -> Sequence[StepTrace] | None:
        """Return ordered traces or null when the parent run does not exist."""
        ...

    async def list_eval_results(self, limit: int) -> Sequence[EvalResultResource]:
        """Return the newest persisted evaluation resources."""
        ...


def get_api_services() -> ApiServices:
    """Require production composition or a test override to inject services."""
    raise ApiProblemError(
        status_code=503,
        code="service_unavailable",
        message="API services are not configured.",
    )
```

#### Create or replace `app/api/errors.py`

<!-- file: app/api/errors.py -->
```python
"""Stable typed error handling for malformed and failed API requests."""

from __future__ import annotations

from collections.abc import Sequence

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.schemas import ApiError, ErrorResponse, ValidationIssue


class ApiProblemError(Exception):
    """An expected HTTP failure with a stable machine code."""

    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        details: Sequence[ValidationIssue] = (),
    ) -> None:
        super().__init__(message)
        if not 400 <= status_code <= 599:
            raise ValueError("API problem status must be between 400 and 599")
        self.status_code = status_code
        self.error = ApiError(code=code, message=message, details=tuple(details))


def bad_request(code: str, message: str) -> ApiProblemError:
    """Build one typed client-input failure."""
    return ApiProblemError(status_code=400, code=code, message=message)


def not_found(resource: str, identity: str) -> ApiProblemError:
    """Build one typed missing-resource failure."""
    return ApiProblemError(
        status_code=404,
        code=f"{resource}_not_found",
        message=f"{resource} {identity} was not found.",
    )


def _response(status_code: int, error: ApiError) -> JSONResponse:
    body = ErrorResponse(error=error)
    return JSONResponse(status_code=status_code, content=body.model_dump(mode="json"))


def _validation_issue(error: dict[str, object]) -> ValidationIssue:
    raw_location = error.get("loc", ())
    if not isinstance(raw_location, tuple | list):
        raw_location = (str(raw_location),)
    location = tuple(value if isinstance(value, int) else str(value) for value in raw_location)
    return ValidationIssue(
        location=location,
        message=str(error.get("msg", "Invalid request.")),
        error_type=str(error.get("type", "validation_error")),
    )


def install_error_handlers(app: FastAPI) -> None:
    """Install non-leaking error envelopes on one FastAPI application."""

    @app.exception_handler(ApiProblemError)
    async def api_problem_handler(request: Request, error: ApiProblemError) -> JSONResponse:
        return _response(error.status_code, error.error)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, error: RequestValidationError) -> JSONResponse:
        details = tuple(_validation_issue(issue) for issue in error.errors())
        return _response(
            422,
            ApiError(
                code="request_validation_failed",
                message="Request validation failed.",
                details=details,
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_handler(request: Request, error: StarletteHTTPException) -> JSONResponse:
        code = "route_not_found" if error.status_code == 404 else "http_error"
        message = str(error.detail) if isinstance(error.detail, str) else "HTTP request failed."
        return _response(error.status_code, ApiError(code=code, message=message))

    @app.exception_handler(Exception)
    async def internal_handler(request: Request, error: Exception) -> JSONResponse:
        return _response(
            500,
            ApiError(
                code="internal_error",
                message="The request could not be completed.",
            ),
        )
```

#### Create or replace `app/api/routes/__init__.py`

<!-- file: app/api/routes/__init__.py -->
```python
"""Resource-oriented M5 route collection."""

from fastapi import APIRouter

from app.api.routes import documents, eval, ingest, retrieve, review, runs, stream, traces

api_router = APIRouter()
for module in (retrieve, documents, ingest, review, stream, runs, traces, eval):
    api_router.include_router(module.router)

__all__ = ["api_router"]
```

#### Create or replace `app/api/routes/documents.py`

<!-- file: app/api/routes/documents.py -->
```python
"""Document collection resource route."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import ApiServices, get_api_services
from app.api.schemas import DocumentListResponse

router = APIRouter(tags=["documents"])
Services = Annotated[ApiServices, Depends(get_api_services)]


@router.get("/documents", response_model=DocumentListResponse)
async def list_documents(services: Services) -> DocumentListResponse:
    """Return the deterministic collection of ingested filings."""
    documents = tuple(await services.list_documents())
    return DocumentListResponse(documents=documents)
```

#### Create or replace `app/api/routes/eval.py`

<!-- file: app/api/routes/eval.py -->
```python
"""Persisted evaluation result collection route."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import ApiServices, get_api_services
from app.api.schemas import EvalListResponse

router = APIRouter(tags=["eval"])
Services = Annotated[ApiServices, Depends(get_api_services)]
Limit = Annotated[int, Query(ge=1, le=100)]


@router.get("/eval", response_model=EvalListResponse)
async def list_eval_results(
    services: Services,
    limit: Limit = 20,
) -> EvalListResponse:
    """Return the newest persisted retrieval evaluation results."""
    results = tuple(await services.list_eval_results(limit))
    return EvalListResponse(results=results)
```

#### Create or replace `app/api/routes/ingest.py`

<!-- file: app/api/routes/ingest.py -->
```python
"""Synchronous ingestion resource route."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import ApiServices, get_api_services
from app.api.schemas import IngestRequest, IngestResponse

router = APIRouter(tags=["ingest"])
Services = Annotated[ApiServices, Depends(get_api_services)]


@router.post("/ingest", response_model=IngestResponse)
async def ingest_manifest(request: IngestRequest, services: Services) -> IngestResponse:
    """Parse and persist one explicit local manifest before responding."""
    result = await services.ingest(request)
    return IngestResponse(documents=result.documents, chunks=result.chunks)
```

#### Create or replace `app/api/routes/retrieve.py`

<!-- file: app/api/routes/retrieve.py -->
```python
"""Retrieve resource route."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import ApiServices, get_api_services
from app.api.schemas import EvidenceHit, RetrieveRequest, RetrieveResponse
from app.retrieval import RetrievalResult

router = APIRouter(tags=["retrieve"])
Services = Annotated[ApiServices, Depends(get_api_services)]


@router.post("/retrieve", response_model=RetrieveResponse)
async def retrieve_evidence(request: RetrieveRequest, services: Services) -> RetrieveResponse:
    """Return source-cited ranked evidence for one validated query."""
    result = await services.retrieve(request)
    hits = result.hits if isinstance(result, RetrievalResult) else tuple(result)
    return RetrieveResponse(
        query=request.query,
        results=tuple(EvidenceHit.from_chunk_hit(hit) for hit in hits),
    )
```

#### Create or replace `app/api/routes/review.py`

<!-- file: app/api/routes/review.py -->
```python
"""Synchronous evidence-review resource route."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response

from app.api.deps import ApiServices, get_api_services
from app.api.schemas import ReviewRequest, RunResponse

router = APIRouter(tags=["review"])
Services = Annotated[ApiServices, Depends(get_api_services)]
STATUS_CODES = {
    "ok": 200,
    "budget_exceeded": 429,
    "schema_rejected": 502,
    "error": 503,
}


@router.post("/review", response_model=RunResponse)
async def review_query(
    request: ReviewRequest,
    response: Response,
    services: Services,
) -> RunResponse:
    """Complete one guarded workflow and return its terminal run resource."""
    result = RunResponse.from_run_report(await services.review(request))
    response.status_code = STATUS_CODES[result.status]
    return result
```

#### Create or replace `app/api/routes/runs.py`

<!-- file: app/api/routes/runs.py -->
```python
"""Persisted workflow run resource route."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path

from app.api.deps import ApiServices, get_api_services
from app.api.errors import not_found
from app.api.schemas import RunResponse

router = APIRouter(tags=["runs"])
Services = Annotated[ApiServices, Depends(get_api_services)]
RunPath = Annotated[
    str,
    Path(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"),
]


@router.get("/runs/{run_id}", response_model=RunResponse)
async def get_run(run_id: RunPath, services: Services) -> RunResponse:
    """Return one persisted run without executing it again."""
    result = await services.get_run(run_id)
    if result is None:
        raise not_found("run", run_id)
    return RunResponse.from_run_report(result)
```

#### Create or replace `app/api/routes/traces.py`

<!-- file: app/api/routes/traces.py -->
```python
"""Persisted provider trace collection route."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path

from app.api.deps import ApiServices, get_api_services
from app.api.errors import not_found
from app.api.schemas import TraceListResponse

router = APIRouter(tags=["traces"])
Services = Annotated[ApiServices, Depends(get_api_services)]
RunPath = Annotated[
    str,
    Path(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"),
]


@router.get("/runs/{run_id}/traces", response_model=TraceListResponse)
async def list_traces(run_id: RunPath, services: Services) -> TraceListResponse:
    """Return ordered raw provider traces for one persisted run."""
    traces = await services.get_traces(run_id)
    if traces is None:
        raise not_found("run", run_id)
    return TraceListResponse(run_id=run_id, traces=tuple(traces))
```

#### Create or replace `app/api/app.py`

<!-- file: app/api/app.py -->
```python
"""FastAPI application factory with explicit service injection."""

from fastapi import FastAPI

from app.api.deps import ApiServices, get_api_services
from app.api.errors import install_error_handlers
from app.api.routes import api_router


def create_api_app(services: ApiServices | None = None) -> FastAPI:
    """Create the synchronous M5 HTTP application without starting external services."""
    app = FastAPI(title="Document Review RAG API", version="0.1.0")
    install_error_handlers(app)
    app.include_router(api_router)
    if services is not None:
        app.dependency_overrides[get_api_services] = lambda: services
    return app
```

Run the checkpoint:

```bash
uv run pytest tests/api/test_01_schemas.py tests/api/test_02_errors.py tests/api/test_03_resources.py tests/api/test_04_operations.py tests/api/test_05_routes.py -q
```

**Expected:** every selected offline test passes. A declared integration test may skip only when its external service is unavailable.

**Stop:** do not continue if a test fails or skips because a required symbol is missing.

**Debug:** rerun the same pytest target with `-vv --tb=long`, then fix the first failing contract before continuing.

### M5.2 — Complete checkpoint

#### Create or replace `app/config.py`

<!-- file: app/config.py -->
```python
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

LexicalRanker = Literal["ts_rank_cd", "bm25"]
BM25Idf = Literal["lucene", "robertson"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://filing:filing@localhost:5432/filing"
    corpus_dir: Path = Path("data/corpus")
    embedding_provider: Literal["openai", "deterministic", "sbert"] = "openai"
    embedding_model: str = "text-embedding-3-small"
    # Local sentence-transformer used when embedding_provider is "sbert". The
    # default produces exactly 384 dimensions, matching embed_dim and the
    # database column, so no migration is needed to switch.
    sbert_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embed_dim: Literal[384] = 384
    embedding_batch_size: int = Field(default=128, gt=0, le=2048)
    openai_api_key: SecretStr | None = None
    lexical_ranker: LexicalRanker = "ts_rank_cd"
    # The lexical index is built with the "english" text-search configuration, so a
    # Korean query produces no lexical candidates and hybrid fusion silently degrades
    # to the vector arm. Enabling this makes retrieve() skip the lexical component for
    # a Korean query instead, which is observable in ComponentRankings. Off by default:
    # M8 measures the collapse before changing the shipped query path.
    query_language_routing: bool = False
    bm25_k1: float = Field(default=1.2, gt=0)
    bm25_b: float = Field(default=0.75, ge=0, le=1)
    bm25_idf: BM25Idf = "lucene"


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

#### Create or replace `app/api/runtime.py`

<!-- file: app/api/runtime.py -->
```python
"""Production database composition for the synchronous M5 HTTP resources."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Sequence
import json
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from openai import OpenAIError
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.api.deps import ApiServices
from app.api.errors import ApiProblemError, bad_request
from app.api.schemas import (
    DocumentResource,
    EvalResultResource,
    IngestRequest,
    RetrieveRequest,
    ReviewRequest,
)
from app.db.bootstrap import bootstrap_schema
from app.db.models import Chunk, Document, EvalResult, Run, Trace
from app.db.session import Session, engine
from app.ingestion.seed import SeedResult, persist_seed_batch, prepare_seed_batch
from app.llm import LLMProvider, ProviderBudget
from app.observability import RunReport, StepTrace, persist_run_report
from app.retrieval import (
    ChunkHit,
    DeterministicEmbeddingProvider,
    EmbeddingProvider,
    RetrievalFilters,
    RetrievalResult,
    retrieve,
)
from app.workflow import NodeObserver, WorkflowRequest, run_workflow


class SessionFactory(Protocol):
    """Build one caller-owned async session context."""

    def __call__(self) -> AsyncSession: ...


class RetrievalService(Protocol):
    """M2 retrieval call shape used by both retrieve and review resources."""

    def __call__(
        self,
        session: AsyncSession,
        query: str,
        *,
        provider: EmbeddingProvider | None,
        k: int,
        filters: RetrievalFilters,
    ) -> Awaitable[RetrievalResult]: ...


class WorkflowService(Protocol):
    """M4 workflow call shape used by the review resource."""

    def __call__(
        self,
        request: WorkflowRequest,
        *,
        retriever: Callable[
            [str, int, RetrievalFilters],
            Awaitable[RetrievalResult | Sequence[ChunkHit]],
        ],
        provider: LLMProvider,
        on_node: NodeObserver | None = None,
    ) -> Awaitable[RunReport]: ...


class RunPersister(Protocol):
    """M4 persistence call shape used after a workflow completes."""

    def __call__(
        self,
        session: AsyncSession,
        report: RunReport,
        *,
        secret_values: Iterable[str],
    ) -> Awaitable[Run]: ...


def _unavailable(code: str, message: str) -> ApiProblemError:
    return ApiProblemError(status_code=503, code=code, message=message)


def _document_resource(document: Document, chunk_count: int) -> DocumentResource:
    return DocumentResource(
        doc_id=document.doc_id,
        ticker=document.ticker,
        cik=document.cik,
        fiscal_year=document.fiscal_year,
        form=document.form,
        filing_date=document.filing_date,
        report_period=document.report_period,
        accession=document.accession,
        url=document.url,
        parse_status=document.parse_status,
        source_length=document.source_length,
        source_sha256=document.source_sha256,
        chunk_count=chunk_count,
    )


def _step_trace(trace: Trace) -> StepTrace:
    return StepTrace(
        step=trace.step,
        node=trace.node,
        model_name=trace.model_name,
        api_url=trace.api_url,
        input_tokens=trace.input_tokens,
        output_tokens=trace.output_tokens,
        request_time_ms=trace.request_time_ms,
        llm_output=trace.llm_output,
        retries=trace.retries,
        error=trace.error,
    )


def _run_report(run: Run, traces: Sequence[Trace]) -> RunReport:
    return RunReport(
        run_id=run.run_id,
        status=run.status,
        iterations=run.iterations,
        total_requests=run.total_requests,
        total_input_tokens=run.total_input_tokens,
        total_output_tokens=run.total_output_tokens,
        total_time_seconds=run.total_time_seconds,
        system_prompt=run.system_prompt,
        node_path=tuple(run.node_path),
        report=run.report,
        steps=tuple(_step_trace(trace) for trace in traces),
    )


class RuntimeApiServices(ApiServices):
    """Compose API resources over one session per synchronous request.

    Retrieval defaults to the configured embedding provider. Review is fail-closed until
    an LLM provider and its explicit budget are injected; the container therefore cannot
    make a paid model call from environment defaults alone.
    """

    def __init__(
        self,
        *,
        session_factory: SessionFactory = Session,
        database_engine: AsyncEngine = engine,
        embedding_provider: EmbeddingProvider | None = None,
        llm_provider: LLMProvider | None = None,
        provider_budget: ProviderBudget | None = None,
        retrieval_service: RetrievalService = retrieve,
        workflow_service: WorkflowService = run_workflow,
        run_persister: RunPersister = persist_run_report,
        run_id_factory: Callable[[], str] | None = None,
        secret_values: Iterable[str] = (),
    ) -> None:
        if (llm_provider is None) != (provider_budget is None):
            raise ValueError("llm_provider and provider_budget must be configured together")
        self._session_factory = session_factory
        self._database_engine = database_engine
        self._embedding_provider = (
            DeterministicEmbeddingProvider() if embedding_provider is None else embedding_provider
        )
        self._llm_provider = llm_provider
        self._provider_budget = provider_budget
        self._retrieval_service = retrieval_service
        self._workflow_service = workflow_service
        self._run_persister = run_persister
        self._run_id_factory = run_id_factory or (lambda: f"run-{uuid4().hex}")
        self._secret_values = tuple(secret_values)

    async def _retrieve_with_session(
        self,
        session: AsyncSession,
        query: str,
        k: int,
        filters: RetrievalFilters,
    ) -> RetrievalResult:
        return await self._retrieval_service(
            session,
            query,
            provider=self._embedding_provider,
            k=k,
            filters=filters,
        )

    async def retrieve(self, request: RetrieveRequest) -> RetrievalResult:
        """Call the M2 service through one request-owned database session."""
        try:
            async with self._session_factory() as session:
                return await self._retrieve_with_session(
                    session,
                    request.query,
                    request.k,
                    request.filters,
                )
        except OpenAIError as error:
            raise _unavailable(
                "provider_unavailable",
                f"Embedding provider is unavailable ({type(error).__name__}).",
            ) from error
        except SQLAlchemyError as error:
            raise _unavailable(
                "database_unavailable",
                f"Database is unavailable ({type(error).__name__}).",
            ) from error

    async def list_documents(self) -> Sequence[DocumentResource]:
        """Return filing resources with deterministic chunk counts."""
        statement = (
            select(Document, func.count(Chunk.id).label("chunk_count"))
            .outerjoin(Chunk, Chunk.doc_id == Document.doc_id)
            .group_by(Document.doc_id)
            .order_by(Document.ticker, Document.fiscal_year, Document.doc_id)
        )
        try:
            async with self._session_factory() as session:
                rows = (await session.execute(statement)).all()
        except SQLAlchemyError as error:
            raise _unavailable(
                "database_unavailable",
                f"Database is unavailable ({type(error).__name__}).",
            ) from error
        return tuple(_document_resource(document, count) for document, count in rows)

    async def ingest(self, request: IngestRequest) -> SeedResult:
        """Prepare locally, bootstrap explicitly, and preserve the M1 atomic upsert."""
        path = Path(request.manifest_path)
        if not path.is_file():
            raise bad_request("manifest_not_found", f"Manifest file was not found: {path}")
        try:
            batch = prepare_seed_batch(path, expected_documents=request.expected_documents)
        except json.JSONDecodeError as error:
            raise bad_request(
                "invalid_manifest_json",
                f"Manifest is not valid JSON at line {error.lineno} column {error.colno}.",
            ) from error
        except UnicodeDecodeError as error:
            raise bad_request(
                "invalid_manifest_encoding",
                "Manifest must be UTF-8 text.",
            ) from error
        except FileNotFoundError as error:
            raise bad_request(
                "corpus_file_not_found",
                f"Corpus file was not found: {error.filename}",
            ) from error
        except ValueError as error:
            raise bad_request("invalid_manifest", str(error)) from error

        try:
            await bootstrap_schema(self._database_engine)
            async with self._session_factory() as session:
                return await persist_seed_batch(
                    session,
                    batch,
                    chunk_batch_size=request.chunk_batch_size,
                )
        except SQLAlchemyError as error:
            raise _unavailable(
                "database_unavailable",
                f"Database is unavailable ({type(error).__name__}).",
            ) from error

    async def review(self, request: ReviewRequest) -> RunReport:
        """Call M4 over the same M2 seam and persist its structured terminal report."""
        return await self._review(request, on_node=None)

    async def review_stream(
        self,
        request: ReviewRequest,
        on_node: NodeObserver,
    ) -> RunReport:
        """Run one reviewed workflow while reporting each completed node."""
        return await self._review(request, on_node=on_node)

    async def _review(
        self,
        request: ReviewRequest,
        *,
        on_node: NodeObserver | None,
    ) -> RunReport:
        if self._llm_provider is None or self._provider_budget is None:
            raise _unavailable(
                "provider_unavailable",
                "Review requires an explicitly configured LLM provider and budget.",
            )
        workflow_request = WorkflowRequest(
            run_id=self._run_id_factory(),
            query=request.query,
            k=request.k,
            filters=request.filters,
            budget=request.budget,
            provider_budget=self._provider_budget,
            max_context_chars=request.max_context_chars,
        )
        try:
            async with self._session_factory() as session:

                async def retrieve_for_workflow(
                    query: str,
                    k: int,
                    filters: RetrievalFilters,
                ) -> RetrievalResult:
                    return await self._retrieve_with_session(session, query, k, filters)

                report = await self._workflow_service(
                    workflow_request,
                    retriever=retrieve_for_workflow,
                    provider=self._llm_provider,
                    on_node=on_node,
                )
                if session.in_transaction():
                    await session.rollback()
                async with session.begin():
                    await self._run_persister(
                        session,
                        report,
                        secret_values=self._secret_values,
                    )
                return report
        except SQLAlchemyError as error:
            raise _unavailable(
                "database_unavailable",
                f"Database is unavailable ({type(error).__name__}).",
            ) from error

    async def _trace_rows(self, session: AsyncSession, run_id: str) -> tuple[Trace, ...]:
        rows = await session.scalars(
            select(Trace).where(Trace.run_id == run_id).order_by(Trace.step)
        )
        return tuple(rows)

    async def get_run(self, run_id: str) -> RunReport | None:
        """Load one run and its ordered traces without executing workflow code."""
        try:
            async with self._session_factory() as session:
                run = await session.get(Run, run_id)
                if run is None:
                    return None
                traces = await self._trace_rows(session, run_id)
                return _run_report(run, traces)
        except SQLAlchemyError as error:
            raise _unavailable(
                "database_unavailable",
                f"Database is unavailable ({type(error).__name__}).",
            ) from error

    async def get_traces(self, run_id: str) -> Sequence[StepTrace] | None:
        """Load trace resources only when their parent run exists."""
        try:
            async with self._session_factory() as session:
                if await session.get(Run, run_id) is None:
                    return None
                traces = await self._trace_rows(session, run_id)
                return tuple(_step_trace(trace) for trace in traces)
        except SQLAlchemyError as error:
            raise _unavailable(
                "database_unavailable",
                f"Database is unavailable ({type(error).__name__}).",
            ) from error

    async def list_eval_results(self, limit: int) -> Sequence[EvalResultResource]:
        """Load newest evaluation records through their strict public schema."""
        statement = select(EvalResult).order_by(EvalResult.created_at.desc(), EvalResult.id.desc())
        try:
            async with self._session_factory() as session:
                rows = tuple(await session.scalars(statement.limit(limit)))
        except SQLAlchemyError as error:
            raise _unavailable(
                "database_unavailable",
                f"Database is unavailable ({type(error).__name__}).",
            ) from error
        return tuple(
            EvalResultResource(
                result_id=row.id,
                suite=row.suite,
                config=row.config,
                metrics={name: float(value) for name, value in row.metrics.items()},
                raw_artifact_path=row.raw_artifact_path,
                created_at=row.created_at,
            )
            for row in rows
        )
```

#### Create or replace `app/main.py`

<!-- file: app/main.py -->
```python
"""FastAPI runtime entrypoint without import-time database or provider calls."""

from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict

from app.api import ApiServices, RuntimeApiServices, create_api_app


class HealthResponse(BaseModel):
    """Stable process-liveness response used by container health checks."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["ok"] = "ok"


def create_app(services: ApiServices | None = None) -> FastAPI:
    """Build one API instance with an injectable database-backed service boundary."""
    active_services = RuntimeApiServices() if services is None else services
    application = create_api_app(active_services)

    @application.get(
        "/health",
        response_model=HealthResponse,
        tags=["runtime"],
        operation_id="runtime_health",
    )
    async def health() -> HealthResponse:
        return HealthResponse()

    return application


app = create_app()
```

#### Create or replace `app/cli.py`

<!-- file: app/cli.py -->
```python
"""Deterministic command-line entrypoints for retrieval, ingestion, and serving."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence
from dataclasses import asdict
from enum import IntEnum
import json
from pathlib import Path
import sys
from typing import Literal, TextIO

from openai import OpenAIError
from sqlalchemy.exc import SQLAlchemyError

from app.config import Settings, get_settings
from app.retrieval.types import ChunkHit, RetrievalFilters

ProviderName = Literal["deterministic", "openai"]


class ExitCode(IntEnum):
    """Stable process exit codes for expected CLI outcomes."""

    OK = 0
    INVALID_INPUT = 2
    INVALID_FILE = 3
    UNAVAILABLE = 4


class CliError(Exception):
    """An expected CLI failure with a stable machine-readable code."""

    def __init__(self, code: str, message: str, exit_code: ExitCode) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.exit_code = exit_code


class CliArgumentParser(argparse.ArgumentParser):
    """Convert argparse failures into the same JSON envelope as runtime failures."""

    def error(self, message: str) -> None:
        """Raise a structured CliError instead of printing usage and exiting."""
        raise CliError("invalid_arguments", message, ExitCode.INVALID_INPUT)


def _add_retrieve_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--query", required=True, help="Nonblank retrieval query.")
    parser.add_argument("-k", type=int, default=5, help="Number of fused hits to return.")
    parser.add_argument(
        "--candidate-k",
        type=int,
        help="Candidates per retrieval component; defaults to max(20, 4 * k).",
    )
    parser.add_argument(
        "--provider",
        choices=("deterministic", "openai"),
        default="deterministic",
        help="Embedding provider; deterministic is the offline default.",
    )
    parser.add_argument(
        "--embed-missing",
        action="store_true",
        help="Fill null chunk embeddings before retrieval.",
    )
    parser.add_argument("--doc-id", action="append", default=[], help="Exact document filter.")
    parser.add_argument("--ticker", action="append", default=[], help="Exact ticker filter.")
    parser.add_argument(
        "--fiscal-year",
        action="append",
        default=[],
        type=int,
        help="Exact fiscal-year filter.",
    )
    parser.add_argument("--form", action="append", default=[], help="Exact filing-form filter.")
    parser.add_argument("--item", action="append", default=[], help="Exact filing-item filter.")
    parser.add_argument(
        "--kind",
        action="append",
        default=[],
        choices=("text", "table"),
        help="Exact chunk-kind filter.",
    )


def _add_ingest_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--manifest",
        type=Path,
        required=True,
        help="Path to the corpus manifest JSON file.",
    )
    parser.add_argument(
        "--expected-documents",
        type=int,
        default=20,
        help="Fail unless the manifest contains this many documents.",
    )
    parser.add_argument(
        "--chunk-batch-size",
        type=int,
        default=500,
        help="Number of chunk rows per PostgreSQL upsert statement.",
    )
    parser.add_argument(
        "--create-schema",
        action="store_true",
        help="Create missing tables before ingestion; existing tables are not migrated.",
    )


def _add_serve_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--host", default="127.0.0.1", help="Interface address to bind.")
    parser.add_argument("--port", type=int, default=8000, help="TCP port to bind.")
    parser.add_argument("--workers", type=int, default=1, help="Number of Uvicorn workers.")
    parser.add_argument(
        "--log-level",
        choices=("critical", "error", "warning", "info", "debug", "trace"),
        default="info",
        help="Uvicorn log level.",
    )


def arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse one explicit runtime command without opening files or services."""
    parser = CliArgumentParser(prog="docreview", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    retrieve = subparsers.add_parser("retrieve", help="Retrieve cited filing evidence.")
    ingest = subparsers.add_parser("ingest", help="Upsert one local corpus manifest.")
    serve = subparsers.add_parser("serve", help="Run the FastAPI application with Uvicorn.")
    _add_retrieve_arguments(retrieve)
    _add_ingest_arguments(ingest)
    _add_serve_arguments(serve)
    return parser.parse_args(argv)


def _validate_arguments(args: argparse.Namespace) -> None:
    if args.command == "retrieve":
        if not args.query.strip():
            raise CliError(
                "empty_query",
                "query must not be blank",
                ExitCode.INVALID_INPUT,
            )
        if args.k <= 0:
            raise CliError("invalid_k", "k must be positive", ExitCode.INVALID_INPUT)
        if args.candidate_k is not None and args.candidate_k < args.k:
            raise CliError(
                "invalid_candidate_k",
                "candidate-k must be at least k",
                ExitCode.INVALID_INPUT,
            )
    elif args.command == "ingest":
        if args.expected_documents <= 0:
            raise CliError(
                "invalid_expected_documents",
                "expected-documents must be positive",
                ExitCode.INVALID_INPUT,
            )
        if args.chunk_batch_size <= 0:
            raise CliError(
                "invalid_chunk_batch_size",
                "chunk-batch-size must be positive",
                ExitCode.INVALID_INPUT,
            )
    elif args.command == "serve":
        if not args.host.strip():
            raise CliError("invalid_host", "host must not be blank", ExitCode.INVALID_INPUT)
        if not 1 <= args.port <= 65_535:
            raise CliError(
                "invalid_port",
                "port must be between 1 and 65535",
                ExitCode.INVALID_INPUT,
            )
        if args.workers <= 0:
            raise CliError(
                "invalid_workers",
                "workers must be positive",
                ExitCode.INVALID_INPUT,
            )


def _provider_settings(settings: Settings, provider: ProviderName) -> Settings:
    return settings.model_copy(update={"embedding_provider": provider})


def _filters(args: argparse.Namespace) -> RetrievalFilters:
    return RetrievalFilters(
        doc_ids=tuple(args.doc_id),
        tickers=tuple(args.ticker),
        fiscal_years=tuple(args.fiscal_year),
        forms=tuple(args.form),
        items=tuple(args.item),
        kinds=tuple(args.kind),
    )


def _evidence_payload(hit: ChunkHit) -> dict[str, object]:
    """Project the same public evidence fields exposed by the HTTP boundary."""
    from app.api.schemas import EvidenceHit

    return EvidenceHit.from_chunk_hit(hit).model_dump(mode="json")


async def _retrieve(args: argparse.Namespace) -> dict[str, object]:
    from app.db.session import Session
    from app.retrieval.embeddings import embed_missing_chunks, get_embedding_provider
    from app.retrieval.service import retrieve

    settings = _provider_settings(get_settings(), args.provider)
    provider = get_embedding_provider(settings)
    async with Session() as session:
        backfill = None
        if args.embed_missing:
            backfill = await embed_missing_chunks(session, provider)
        result = await retrieve(
            session,
            args.query,
            provider=provider,
            k=args.k,
            candidate_k=args.candidate_k,
            filters=_filters(args),
        )
    return {
        "status": "ok",
        "command": "retrieve",
        "query": args.query,
        "provider": settings.embedding_provider,
        "backfill": asdict(backfill) if backfill is not None else None,
        "hits": [_evidence_payload(hit) for hit in result.hits],
        "component_rankings": result.component_rankings.model_dump(mode="json"),
    }


def _checked_manifest(path: Path) -> Path:
    if not path.is_file():
        raise CliError(
            "manifest_not_found",
            f"manifest file does not exist: {path}",
            ExitCode.INVALID_FILE,
        )
    return path


async def _ingest(args: argparse.Namespace) -> dict[str, object]:
    from app.db.bootstrap import bootstrap_schema
    from app.db.session import Session, engine
    from app.ingestion.seed import persist_seed_batch, prepare_seed_batch

    manifest = _checked_manifest(args.manifest)
    try:
        batch = prepare_seed_batch(
            manifest,
            expected_documents=args.expected_documents,
        )
    except json.JSONDecodeError as error:
        raise CliError(
            "invalid_manifest_json",
            f"manifest is not valid JSON at line {error.lineno} column {error.colno}",
            ExitCode.INVALID_FILE,
        ) from error
    except UnicodeDecodeError as error:
        raise CliError(
            "invalid_manifest_encoding",
            "manifest must be UTF-8 text",
            ExitCode.INVALID_FILE,
        ) from error
    except FileNotFoundError as error:
        raise CliError(
            "corpus_file_not_found",
            f"corpus file does not exist: {error.filename}",
            ExitCode.INVALID_FILE,
        ) from error
    except ValueError as error:
        raise CliError(
            "invalid_manifest",
            str(error),
            ExitCode.INVALID_FILE,
        ) from error

    if args.create_schema:
        await bootstrap_schema(engine)
    async with Session() as session:
        result = await persist_seed_batch(
            session,
            batch,
            chunk_batch_size=args.chunk_batch_size,
        )
    return {
        "status": "ok",
        "command": "ingest",
        "manifest": str(manifest),
        "documents": result.documents,
        "chunks": result.chunks,
    }


async def _run_data_command(args: argparse.Namespace) -> dict[str, object]:
    if args.command == "retrieve":
        return await _retrieve(args)
    if args.command == "ingest":
        return await _ingest(args)
    raise AssertionError(f"unsupported data command: {args.command}")


def _serve(args: argparse.Namespace) -> None:
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        workers=args.workers,
        log_level=args.log_level,
    )


def _failure_payload(error: CliError) -> dict[str, object]:
    return {
        "status": "error",
        "error": {
            "code": error.code,
            "message": error.message,
        },
    }


def _write_json(value: dict[str, object], stream: TextIO) -> None:
    json.dump(value, stream, ensure_ascii=False, sort_keys=True)
    stream.write("\n")


def main(argv: Sequence[str] | None = None) -> int:
    """Run one command and return a stable process exit code."""
    try:
        args = arguments(argv)
        _validate_arguments(args)
        if args.command == "serve":
            _serve(args)
            return ExitCode.OK
        payload = asyncio.run(_run_data_command(args))
    except CliError as error:
        _write_json(_failure_payload(error), sys.stderr)
        return error.exit_code
    except OpenAIError as error:
        failure = CliError(
            "provider_unavailable",
            f"embedding provider is unavailable ({type(error).__name__})",
            ExitCode.UNAVAILABLE,
        )
        _write_json(_failure_payload(failure), sys.stderr)
        return failure.exit_code
    except SQLAlchemyError as error:
        failure = CliError(
            "database_unavailable",
            f"database is unavailable ({type(error).__name__})",
            ExitCode.UNAVAILABLE,
        )
        _write_json(_failure_payload(failure), sys.stderr)
        return failure.exit_code

    _write_json(payload, sys.stdout)
    return ExitCode.OK


def entrypoint() -> None:
    """Run the installed console script without printing a Python traceback."""
    raise SystemExit(main())


if __name__ == "__main__":
    entrypoint()
```

Run the checkpoint:

```bash
uv run pytest tests/api/test_06_cli.py tests/api/test_07_runtime.py -q
```

**Expected:** every selected offline test passes. A declared integration test may skip only when its external service is unavailable.

**Stop:** do not continue if a test fails or skips because a required symbol is missing.

**Debug:** rerun the same pytest target with `-vv --tb=long`, then fix the first failing contract before continuing.

### M5.3 — Complete checkpoint

Run the checkpoint:

```bash
uv run pytest tests/api/test_08_integration.py -q
```

**Expected:** every selected offline test passes. A declared integration test may skip only when its external service is unavailable.

**Stop:** do not continue if a test fails or skips because a required symbol is missing.

**Debug:** rerun the same pytest target with `-vv --tb=long`, then fix the first failing contract before continuing.

### M5.4 — Complete checkpoint

#### Create or replace `app/api/routes/stream.py`

<!-- file: app/api/routes/stream.py -->
```python
"""Server-sent-events streaming for the evidence-review workflow."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
import contextlib
import json
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.api.deps import ApiServices, get_api_services
from app.api.schemas import ReviewRequest, RunResponse, StreamNodeEvent
from app.observability import WorkflowNode
from app.workflow import WorkflowState

router = APIRouter(tags=["review"])
Services = Annotated[ApiServices, Depends(get_api_services)]

type _Event = tuple[str, str]


def _sse(event: str, data: str) -> str:
    """Format one server-sent event with a named type and single-line JSON data."""
    return f"event: {event}\ndata: {data}\n\n"


@router.post("/review/stream")
async def review_stream(request: ReviewRequest, services: Services) -> StreamingResponse:
    """Stream node completions while one guarded workflow runs, then its terminal run."""
    queue: asyncio.Queue[_Event | None] = asyncio.Queue()

    async def on_node(node: WorkflowNode, state: WorkflowState) -> None:
        event = StreamNodeEvent(
            node=node,
            evidence_count=len(state.evidence),
            relevant_count=len(state.relevant_chunk_ids),
            step_count=len(state.steps),
        )
        await queue.put(("node", event.model_dump_json()))

    async def run_review() -> None:
        try:
            report = await services.review_stream(request, on_node)
            payload = RunResponse.from_run_report(report).model_dump_json()
            await queue.put(("report", payload))
        except Exception as error:
            # str(error) can carry secrets (a SQLAlchemyError embeds the connection
            # string), so only the exception's class name leaves the process.
            payload = json.dumps({"error_type": type(error).__name__})
            await queue.put(("error", payload))
        finally:
            await queue.put(None)

    review_task = asyncio.create_task(run_review())

    async def events() -> AsyncIterator[str]:
        try:
            while (item := await queue.get()) is not None:
                yield _sse(*item)
            yield _sse("done", "{}")
        finally:
            # A disconnected client cancels the generator; stop the workflow with it.
            review_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await review_task

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"cache-control": "no-store"},
    )
```

Run the checkpoint:

```bash
uv run pytest tests/api/test_09_stream.py -q
```

**Expected:** every selected offline test passes. A declared integration test may skip only when its external service is unavailable.

**Stop:** do not continue if a test fails or skips because a required symbol is missing.

**Debug:** rerun the same pytest target with `-vv --tb=long`, then fix the first failing contract before continuing.

<!-- complete-files:end -->
