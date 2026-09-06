"""Strict HTTP request and response schemas for the M5 API."""

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

from app.observability import Budget, RunReport, StepTrace, WorkflowNode, redact_sensitive_text
from app.retrieval import ChunkHit, RetrievalFilters
from app.workflow import NodeError, ProviderFailure, WorkflowReport

NonBlank = Annotated[StrictStr, Field(min_length=1)]
PositiveInt = Annotated[StrictInt, Field(gt=0)]
NonnegativeInt = Annotated[StrictInt, Field(ge=0)]
NonnegativeFloat = Annotated[StrictFloat, Field(ge=0, allow_inf_nan=False)]
RunId = Annotated[StrictStr, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")]
SourceSha256 = Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]
JsonObject = dict[str, JsonValue]


def _sanitize_public_json(value: JsonValue) -> JsonValue:
    """Redact recognizable credentials from one public JSON value."""
    if isinstance(value, str):
        return redact_sensitive_text(value)
    if isinstance(value, dict):
        sanitized: dict[str, JsonValue] = {}
        for key, child in value.items():
            sanitized_key = redact_sensitive_text(str(key))
            if sanitized_key in sanitized:
                raise ValueError(f"redaction produced duplicate public key: {sanitized_key!r}")
            sanitized[sanitized_key] = _sanitize_public_json(child)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_public_json(child) for child in value]
    return value


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
            return self
        if self.failure is None or self.report is not None:
            raise ValueError("failed runs require only a typed failure")
        if self.status == "budget_exceeded":
            matches = isinstance(self.failure, BudgetLimitFailure) or (
                isinstance(self.failure, ProviderFailure)
                and self.failure.status == "budget_exceeded"
            )
        elif self.status == "schema_rejected":
            matches = (
                isinstance(self.failure, ProviderFailure)
                and self.failure.status == "schema_rejected"
            )
        else:
            matches = isinstance(self.failure, NodeError) or (
                isinstance(self.failure, ProviderFailure)
                and self.failure.status in {"provider_refused", "provider_error"}
            )
        if not matches:
            raise ValueError("run status must match its typed failure")
        return self

    @classmethod
    def from_run_report(cls, run: RunReport) -> Self:
        """Validate an observability report into its public resource shape.

        Parameters
        ----------
        run : RunReport
            Internal terminal report to sanitize and project.

        Returns
        -------
        Self
            Public run with mutually consistent status and typed terminal payload.

        Raises
        ------
        TypeError
            If ``run`` is not a strict ``RunReport``.
        ValueError
            If the internal terminal payload is missing or malformed.

        Notes
        -----
        Recognizable credentials are removed before public Pydantic validation.
        """
        if not isinstance(run, RunReport):
            raise TypeError("run responses require a RunReport")
        payload_value = _sanitize_public_json(run.report) if run.report is not None else None
        payload = payload_value if isinstance(payload_value, dict) else None
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
            system_prompt=redact_sensitive_text(run.system_prompt),
            node_path=run.node_path,
            report=report,
            failure=failure,
        )


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


class StreamNodeEvent(StrictApiModel):
    """One completed workflow node reported while a streamed review is running."""

    node: WorkflowNode
    evidence_count: NonnegativeInt
    relevant_count: NonnegativeInt
    step_count: NonnegativeInt
