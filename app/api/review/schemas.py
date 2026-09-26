"""Review requests, evidence resources, and persisted run responses."""

import json
from typing import Annotated, Literal, Self

from pydantic import (
    BeforeValidator,
    Field,
    JsonValue,
    StrictInt,
    StrictStr,
    TypeAdapter,
)
from pydantic.functional_validators import model_validator

from app.api.review.evidence import EvidenceSelection
from app.api.review.execution import ExecutionData
from app.api.review.profiles import ResolvedRetrievalProfile, ReviewSessionProfile
from app.contracts.evidence import SourceSha256
from app.contracts.validation import (
    FiniteFloat,
    NonBlank,
    NonNegativeDecimal,
    NonNegativeFloat,
    NonNegativeInt,
    PositiveInt,
    StrictSchema,
    tuple_from_json_array,
)
from app.evals.contracts import EvalResultResource
from app.ingestion.parsing.registry import section_title as registry_section_title
from app.observability.redaction import redact_sensitive_text, sanitize_json
from app.observability.types import (
    BudgetLimitFailure,
    RunId,
    RunReport,
    RunStatus,
    StepTrace,
    WorkflowNode,
)
from app.query.intent import ConversationTurn
from app.query.scope import ResolvedQueryScope
from app.retrieval.types import ChunkHit
from app.workflow.types import NodeError, ProviderFailure, WorkflowReport, run_status_for_failure

JsonObject = dict[str, JsonValue]


class ValidationIssue(StrictSchema):
    """One stable request-validation detail without echoing submitted values."""

    location: tuple[StrictStr | StrictInt, ...]
    message: NonBlank
    error_type: NonBlank


class ApiError(StrictSchema):
    """Machine-readable HTTP failure shared by all routes."""

    code: Annotated[StrictStr, Field(pattern=r"^[a-z][a-z0-9_]*$")]
    message: NonBlank
    details: tuple[ValidationIssue, ...] = ()
    path_decision: JsonObject | None = Field(default=None, exclude_if=lambda value: value is None)
    detail: str | None = Field(default=None, exclude_if=lambda value: value is None)
    path: str | None = Field(default=None, exclude_if=lambda value: value is None)
    cause: (
        Literal["missing_file", "invalid_json", "invalid_manifest", "alias_conflict", "permission"]
        | None
    ) = Field(default=None, exclude_if=lambda value: value is None)
    corpus_job: JsonObject | None = Field(default=None, exclude_if=lambda value: value is None)
    failed_stage: Literal["path", "gate"] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )


class ErrorResponse(StrictSchema):
    """Top-level typed error envelope."""

    error: ApiError


class EvidenceHit(StrictSchema):
    """One retrieved evidence unit with complete source identity."""

    chunk_id: PositiveInt
    doc_id: NonBlank
    item: NonBlank | None
    section_title: NonBlank | None
    kind: Literal["text", "table"]
    citation: NonBlank
    start_char: NonNegativeInt
    end_char: PositiveInt
    source_sha256: SourceSha256
    body: NonBlank
    context_header: StrictStr
    score: FiniteFloat

    @model_validator(mode="after")
    def validate_span(self) -> Self:
        """Require a nonempty half-open source span."""
        if self.end_char <= self.start_char:
            raise ValueError("end_char must be greater than start_char")
        return self

    @classmethod
    def from_chunk_hit(cls, hit: ChunkHit, *, registry: str | None = None) -> Self:
        """Project the public evidence fields from one validated retrieval hit.

        ``registry`` names the publishing registry when the caller knows it; otherwise the
        section title is resolved from the item code alone.
        """
        if not isinstance(hit, ChunkHit):
            raise TypeError("evidence responses require ChunkHit values")
        return cls(
            chunk_id=hit.chunk_id,
            doc_id=hit.doc_id,
            item=hit.item,
            section_title=registry_section_title(hit.item, registry),
            kind=hit.kind,
            citation=hit.citation,
            start_char=hit.start_char,
            end_char=hit.end_char,
            source_sha256=hit.source_sha256,
            body=hit.body,
            context_header=hit.context_header,
            score=hit.score,
        )


class CandidateComponentRank(StrictSchema):
    """One retrieval lane's 1-based rank contribution for a candidate."""

    lane: Literal["vector", "lexical"]
    language: Literal["en", "ko"] | None = None
    rank: PositiveInt


class EvidenceCandidate(EvidenceHit):
    """One inspectable candidate with filing and rank provenance."""

    rank: PositiveInt
    registry: NonBlank
    language: NonBlank
    issuer: NonBlank
    fiscal_year: PositiveInt
    form: NonBlank
    score_stage: Literal["rrf", "reranker"]
    rank_score: FiniteFloat
    component_ranks: tuple[CandidateComponentRank, ...] = ()


class RetrieveRequest(StrictSchema):
    """One bounded evidence retrieval request."""

    query: NonBlank
    session_profile: ReviewSessionProfile = Field(default_factory=ReviewSessionProfile)
    conversation_history: Annotated[
        tuple[ConversationTurn, ...], BeforeValidator(tuple_from_json_array), Field(max_length=6)
    ] = ()


class RetrieveResponse(StrictSchema):
    """Ranked evidence for one query."""

    query: NonBlank
    results: tuple[EvidenceHit, ...]
    candidates: tuple[EvidenceCandidate, ...]
    candidate_token: NonBlank | None
    candidate_expires_at: NonNegativeInt
    score_stage: Literal["rrf", "reranker"]
    component_rankings: dict[str, JsonValue]
    resolved_profile: ResolvedRetrievalProfile
    resolved_scope: ResolvedQueryScope | None = None
    path_decision: JsonObject | None = None


class DocumentResource(StrictSchema):
    """One ingested filing and its source identity."""

    doc_id: NonBlank
    registry: NonBlank
    language: NonBlank
    issuer: NonBlank
    issuer_id: NonBlank
    fiscal_year: PositiveInt
    form: NonBlank
    filing_date: NonBlank
    report_period: NonBlank
    filing_id: NonBlank
    source_url: NonBlank
    parse_status: Literal["parsed", "needs_profile_update"]
    source_length: PositiveInt
    source_sha256: SourceSha256
    chunk_count: NonNegativeInt


class DocumentListResponse(StrictSchema):
    """Deterministically ordered document resources."""

    documents: tuple[DocumentResource, ...]


class ReviewRequest(StrictSchema):
    """One synchronous evidence-checked workflow request."""

    query: NonBlank
    session_profile: ReviewSessionProfile = Field(default_factory=ReviewSessionProfile)
    evidence_selection: EvidenceSelection | None = None
    conversation_history: Annotated[
        tuple[ConversationTurn, ...],
        BeforeValidator(tuple_from_json_array),
        Field(max_length=6),
    ] = ()


RunFailure = Annotated[
    BudgetLimitFailure | ProviderFailure | NodeError,
    Field(discriminator="code"),
]


class ConversationReport(StrictSchema):
    """One retrieval-free canned or provider-backed casual response."""

    report_kind: Literal["conversation"] = "conversation"
    answer: NonBlank
    response_source: Literal["canned", "engine"]


_RUN_FAILURE_ADAPTER = TypeAdapter(RunFailure)


class RunResponse(StrictSchema):
    """One completed workflow run or its structured terminal failure."""

    run_id: RunId
    status: RunStatus
    iterations: NonNegativeInt
    total_requests: NonNegativeInt
    total_input_tokens: NonNegativeInt
    total_output_tokens: NonNegativeInt
    total_cached_input_tokens: NonNegativeInt
    total_cache_write_input_tokens: NonNegativeInt
    total_reasoning_tokens: NonNegativeInt
    total_estimated_cost_usd: NonNegativeDecimal
    total_time_seconds: NonNegativeFloat
    system_prompt: NonBlank
    node_path: tuple[WorkflowNode, ...]
    report: WorkflowReport | ConversationReport | None
    failure: RunFailure | None
    execution: ExecutionData | None = None

    @model_validator(mode="after")
    def validate_terminal_shape(self) -> Self:
        """Keep successful reports and terminal failures mutually exclusive.

        The failed-status check delegates to the domain's ``run_status_for_failure``
        so the API cannot maintain a private inverse table that drifts from the
        mapping the runner persists with.
        """
        if self.status == "ok":
            if self.report is None or self.failure is not None:
                raise ValueError("successful runs require only a workflow report")
            return self
        if self.failure is None or self.report is not None:
            raise ValueError("failed runs require only a typed failure")
        expected = (
            "budget_exceeded"
            if isinstance(self.failure, BudgetLimitFailure)
            else run_status_for_failure(self.failure)
        )
        if self.status != expected:
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
        payload_value = sanitize_json(run.report) if run.report is not None else None
        payload = payload_value if isinstance(payload_value, dict) else None
        report: WorkflowReport | ConversationReport | None = None
        failure: RunFailure | None = None
        if run.status == "ok":
            if payload is None:
                raise ValueError("successful run report payload is missing")
            serialized = json.dumps(
                payload,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            report = (
                ConversationReport.model_validate_json(serialized)
                if payload.get("report_kind") == "conversation"
                else WorkflowReport.model_validate_json(serialized)
            )
        else:
            if payload is None:
                raise ValueError("failed run report payload is missing")
            # "reason" is the only terminal-failure key the workflow runner writes;
            # accepting aliases here would let fixtures diverge from production.
            raw_failure = payload.get("reason")
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
            total_cached_input_tokens=run.total_cached_input_tokens,
            total_cache_write_input_tokens=run.total_cache_write_input_tokens,
            total_reasoning_tokens=run.total_reasoning_tokens,
            total_estimated_cost_usd=run.total_estimated_cost_usd,
            total_time_seconds=run.total_time_seconds,
            system_prompt=redact_sensitive_text(run.system_prompt),
            node_path=run.node_path,
            report=report,
            failure=failure,
            execution=ExecutionData.from_run_report(run),
        )


class TraceListResponse(StrictSchema):
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


class EvalListResponse(StrictSchema):
    """Newest persisted evaluation resources first."""

    results: tuple[EvalResultResource, ...]


class StreamNodeEvent(StrictSchema):
    """One completed workflow node reported while a streamed review is running."""

    node: WorkflowNode
    evidence_count: NonNegativeInt
    relevant_count: NonNegativeInt
    step_count: NonNegativeInt
