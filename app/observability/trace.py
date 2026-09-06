"""Adapters from provider results into strict observability traces."""

from __future__ import annotations

from collections.abc import Mapping
import json
from typing import Any, Protocol

from pydantic import BaseModel

from app.observability.types import StepTrace, WorkflowNode


class ProviderMetadataLike(Protocol):
    """Minimum trace-ready metadata required from an LLM provider boundary."""

    @property
    def model_name(self) -> str:
        """Provider model identifier."""
        ...

    @property
    def api_url(self) -> str:
        """Provider endpoint recorded for the request."""
        ...

    @property
    def input_tokens(self) -> int:
        """Input-token usage reported by the provider."""
        ...

    @property
    def output_tokens(self) -> int:
        """Output-token usage reported by the provider."""
        ...

    @property
    def request_time_ms(self) -> float:
        """Measured provider latency in milliseconds."""
        ...

    @property
    def llm_output(self) -> str:
        """Final raw provider output retained for tracing."""
        ...

    @property
    def retries(self) -> int:
        """Number of repair requests after the first attempt."""
        ...


class ProviderResultLike(Protocol):
    """Minimum typed provider result needed to retain a refusal reason."""

    @property
    def status(self) -> str:
        """Provider result status."""
        ...

    @property
    def metadata(self) -> ProviderMetadataLike:
        """Trace-ready metadata for the completed boundary call."""
        ...

    @property
    def refusal(self) -> object | None:
        """Typed refusal value when the status is not successful."""
        ...


def _jsonable_refusal(refusal: object) -> dict[str, Any]:
    """Return one refusal as a JSON-compatible mapping."""
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
    """Map provider metadata and refusal state without importing its implementation.

    Parameters
    ----------
    result : ProviderResultLike
        Structurally compatible provider result.
    step : int
        Positive provider-step number.
    node : WorkflowNode
        Workflow node responsible for the call.

    Returns
    -------
    StepTrace
        Strict trace containing raw output and canonical failure JSON when applicable.
    """
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
