"""Adapters from provider results into strict observability traces."""

from __future__ import annotations

import json

from pydantic import BaseModel

from app.llm.schemas import ProviderResult
from app.observability.types import StepTrace, WorkflowNode


def step_trace_from_provider_result[OutputT: BaseModel](
    result: ProviderResult[OutputT],
    *,
    step: int,
    node: WorkflowNode,
) -> StepTrace:
    """Map one completed provider call onto its raw workflow trace.

    Parameters
    ----------
    result : ProviderResult[OutputT]
        Typed provider result for the call. ``ProviderResult`` is invariant in its
        output type, so the parameter is generic rather than widened to ``BaseModel``.
    step : int
        Positive provider-step number.
    node : WorkflowNode
        Workflow node responsible for the call.

    Returns
    -------
    StepTrace
        Strict trace containing raw output, the provider's own cost estimate, and
        canonical failure JSON when the result is not successful.

    Notes
    -----
    ``estimated_cost_usd`` is copied from the provider rather than recomputed, so the
    cost a report states is the one the provider budget actually enforced.
    """
    metadata = result.metadata
    error = None
    if result.refusal is not None:
        error = json.dumps(
            {"status": result.status, "refusal": result.refusal.model_dump(mode="json")},
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
        cached_input_tokens=metadata.cached_input_tokens,
        cache_write_input_tokens=metadata.cache_write_input_tokens,
        reasoning_tokens=metadata.reasoning_tokens,
        estimated_cost_usd=metadata.estimated_cost_usd,
        request_time_ms=metadata.request_time_ms,
        llm_output=metadata.llm_output,
        retries=metadata.retries,
        error=error,
    )
