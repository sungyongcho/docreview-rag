"""Adapters from provider results into strict observability traces."""

from __future__ import annotations

from collections.abc import Mapping
import json
from typing import Any, Protocol

from pydantic import BaseModel

from app.observability.types import StepTrace, WorkflowNode


class ProviderMetadataLike(Protocol):
    """Minimum trace-ready metadata required from an LLM provider boundary."""

    model_name: str
    api_url: str
    input_tokens: int
    output_tokens: int
    request_time_ms: float
    llm_output: str
    retries: int


class ProviderResultLike(Protocol):
    """Minimum typed provider result needed to retain a refusal reason."""

    status: str
    metadata: ProviderMetadataLike
    refusal: object | None


def _jsonable_refusal(refusal: object) -> dict[str, Any]:
    if isinstance(refusal, BaseModel):
        return refusal.model_dump(mode="json")
    if isinstance(refusal, Mapping):
        return dict(refusal)
    return {"message": str(refusal)}


def step_trace_from_provider_result(
    result: ProviderResultLike,
    *,
    step: int,
    node: WorkflowNode,
) -> StepTrace:
    """Map trace-ready provider metadata and typed refusal state without importing it."""
    metadata = result.metadata
    error = None
    if result.status != "ok":
        failure = (
            _jsonable_refusal(result.refusal)
            if result.refusal is not None
            else {"message": "provider returned a non-ok result without refusal details"}
        )
        error = json.dumps(
            {"status": result.status, "refusal": failure},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    return StepTrace(
        step=step,
        node=node,
        model_name=metadata.model_name,
        api_url=metadata.api_url,
        input_tokens=metadata.input_tokens,
        output_tokens=metadata.output_tokens,
        request_time_ms=metadata.request_time_ms,
        llm_output=metadata.llm_output,
        retries=metadata.retries,
        error=error,
    )
