"""Typed terminal execution data shared by live responses and saved run details."""

from pydantic import Field, JsonValue

from app.llm.schemas import LocalModelTiming, StrictSchema
from app.observability.stages import StageEvent
from app.observability.types import WorkflowNode


class ExecutionModelCall(StrictSchema):
    """One measured call with explicit provider and optional server timing evidence."""

    step: int
    node: WorkflowNode | None = None
    model: str
    attempts: int
    elapsed_ms: float
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int | None = None
    cache_write_input_tokens: int | None = None
    reasoning_tokens: int | None = None
    estimated_cost_usd: str | None = None
    provider: str = "unknown"
    local: bool | None = None
    credential_slot: str = "unknown"
    local_timings: list[LocalModelTiming] = Field(default_factory=list)
    provider_timing: list[LocalModelTiming] | None = None
    timing_unavailable_reason: str | None = "not_recorded"
    error: str | None = None


class ExecutionCandidate(StrictSchema):
    """Rank and identity of a candidate observed at a committed workflow stage."""

    chunk_id: int
    doc_id: str
    citation: str
    rank: int
    score: float | None


class ExecutionStageResult(StrictSchema):
    """Actual stage output; null separates unrecorded data from a measured empty set."""

    node: WorkflowNode
    candidates: list[ExecutionCandidate] | None = None
    evidence_chunk_ids: list[int] | None = None
    kept_chunk_ids: list[int] | None = None
    rejected_chunk_ids: list[int] | None = None
    decision: dict[str, JsonValue] | None = None
    reasons: list[dict[str, JsonValue]] | None = None
    failure: dict[str, JsonValue] | None = None
    intent: dict[str, JsonValue] | None = None


class ExecutionData(StrictSchema):
    """Versioned execution envelope; absent historical fields remain explicitly null."""

    contract_version: int = 1
    total_elapsed_ms: float
    stages: list[StageEvent] = Field(default_factory=list)
    model_calls: list[ExecutionModelCall] = Field(default_factory=list)
    effective_settings: dict[str, JsonValue] | None = None
    provider_identity: dict[str, JsonValue] | None = None
    resolved_scope: dict[str, JsonValue] | None = None
    routing_queries: dict[str, str] | None = None
    stage_results: list[ExecutionStageResult] | None = None
    local_placement: dict[str, JsonValue] | None = None
