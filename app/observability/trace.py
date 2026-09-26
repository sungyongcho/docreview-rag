"""Adapters from provider results into strict observability traces."""

from __future__ import annotations

import json

from pydantic import BaseModel

from app.llm.schemas import ProviderMetadata, ProviderResult
from app.observability.types import StepTrace, WorkflowNode


def step_trace_from_provider_metadata(
    metadata: ProviderMetadata,
    *,
    step: int,
    node: WorkflowNode,
    error: str | None = None,
) -> StepTrace:
    """Map the attempts one provider call sent onto its raw workflow trace.

    Parameters
    ----------
    metadata : ProviderMetadata
        Usage, latency and raw output of every attempt the call sent.
    step : int
        Positive provider-step number.
    node : WorkflowNode
        Workflow node responsible for the call.
    error : str | None
        Why the call failed, or ``None`` when it succeeded.

    Returns
    -------
    StepTrace
        Strict trace containing raw output, the provider's own cost estimate, and the
        given error.

    Notes
    -----
    A call can end without a provider result, as when the shared allowance denies its
    repair, yet its first attempt was billed. Tracing from the metadata alone keeps such
    an attempt in the run's usage like any other.
    """
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
        requests=metadata.requests,
        estimated_cost_usd=metadata.estimated_cost_usd,
        request_time_ms=metadata.request_time_ms,
        llm_output=metadata.llm_output,
        retries=metadata.retries,
        error=error,
        local_timings=metadata.local_timings,
    )


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
    error = None
    if result.refusal is not None:
        error = json.dumps(
            {"status": result.status, "refusal": result.refusal.model_dump(mode="json")},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    return step_trace_from_provider_metadata(result.metadata, step=step, node=node, error=error)
