"""Typed terminal execution data shared by live responses and saved run details."""

import json
from typing import Self

from pydantic import Field, JsonValue

from app.llm.schemas import LocalModelTiming, StrictSchema
from app.observability.persistence import sanitize_json
from app.observability.stages import StageEvent
from app.observability.types import RunReport, WorkflowNode
from app.observability.usage import recorded_model_calls


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
    provider_timing: list[LocalModelTiming] | None = None
    timing_unavailable_reason: str | None = "not_recorded"
    error: str | None = None
    #: Estimated prompt size of a call refused before it was sent; absent otherwise.
    projected_input_tokens: int | None = None


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
    """Versioned execution envelope with explicitly optional measurements."""

    contract_version: int = 1
    path_decision: dict[str, JsonValue] | None = None
    total_elapsed_ms: float
    stages: list[StageEvent] = Field(default_factory=list)
    model_calls: list[ExecutionModelCall] = Field(default_factory=list)
    effective_settings: dict[str, JsonValue] | None = None
    provider_identity: dict[str, JsonValue] | None = None
    resolved_scope: dict[str, JsonValue] | None = None
    routing_queries: dict[str, str] | None = None
    stage_results: list[ExecutionStageResult] | None = None
    local_placement: dict[str, JsonValue] | None = None

    @classmethod
    def from_run_report(cls, run: RunReport) -> Self:
        """Project recorded execution data without reconstructing calls from raw traces."""
        context = run.request_context or {}
        projected_calls = []
        for call in recorded_model_calls(context):
            projected = dict(call)
            timings = projected.pop("local_timings")
            projected_calls.append(
                {
                    **projected,
                    "provider_timing": timings or None,
                    "timing_unavailable_reason": (
                        None
                        if timings
                        else "provider_does_not_report_timing"
                        if call.get("provider") in {"openai_responses", "openai"}
                        else "ollama_timing_not_recorded"
                        if call.get("provider") == "ollama"
                        else "not_recorded"
                    ),
                }
            )
        payload = {
            "total_elapsed_ms": context.get("total_elapsed_ms", run.total_time_seconds * 1000),
            "stages": context.get("stages", []),
            "model_calls": projected_calls,
            **{
                key: context.get(key)
                for key in (
                    "path_decision",
                    "effective_settings",
                    "provider_identity",
                    "resolved_scope",
                    "routing_queries",
                    "stage_results",
                    "local_placement",
                )
            },
        }
        return cls.model_validate_json(json.dumps(sanitize_json(payload)))
