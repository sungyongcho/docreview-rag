"""Request-local stage clocks shared by streamed and persisted review reports."""

from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import wraps
import time
from typing import Literal

from app.llm.schemas import NonNegativeFloat, ProviderMetadata, StrictSchema
from app.observability.types import JsonObject, WorkflowNode
from app.observability.usage import provider_identity


class StageEvent(StrictSchema):
    """One measured stage transition; an active stage has no completed duration."""

    node: WorkflowNode
    phase: Literal["start", "end"]
    status: Literal["running", "completed", "failed"]
    started_at: str
    elapsed_ms: NonNegativeFloat | None = None
    total_elapsed_ms: NonNegativeFloat
    resolved_scope: JsonObject | None = None


type StageObserver = Callable[[StageEvent], Awaitable[None]]


@dataclass
class StageRecorder:
    """Hold only the current request's clocks and completed stage events."""

    observer: StageObserver | None = None
    started: float = field(default_factory=time.perf_counter)
    events: list[StageEvent] = field(default_factory=list)
    model_calls: list[JsonObject] = field(default_factory=list)


@dataclass
class StageMeasurement:
    """Allow handled domain failures to mark their completed stage accurately."""

    failed: bool = False
    resolved_scope: JsonObject | None = None


_NODE: ContextVar[WorkflowNode | None] = ContextVar("review_active_stage", default=None)
_ACTIVE: ContextVar[StageRecorder | None] = ContextVar("review_stage_recorder", default=None)


@contextmanager
def record_stages(observer: StageObserver | None = None) -> Iterator[StageRecorder]:
    """Reuse a stream's recorder or isolate a new synchronous review's measurements."""
    current = _ACTIVE.get()
    if current is not None:
        yield current
        return
    recorder = StageRecorder(observer=observer)
    token = _ACTIVE.set(recorder)
    try:
        yield recorder
    finally:
        _ACTIVE.reset(token)


def stage_metadata() -> JsonObject:
    """Return completed measurements suitable for the existing JSONB run context."""
    recorder = _ACTIVE.get()
    if recorder is None:
        return {}
    return {
        "stages": [event.model_dump(mode="json") for event in recorder.events],
        "total_elapsed_ms": max(0.0, (time.perf_counter() - recorder.started) * 1000),
        "model_calls": list(recorder.model_calls),
    }


def record_model_call(metadata: ProviderMetadata) -> None:
    """Retain safe provider timing for gate and routing calls as well as traced calls."""
    recorder = _ACTIVE.get()
    if recorder is None:
        return
    recorder.model_calls.append(
        {
            "step": len(recorder.model_calls) + 1,
            "node": _NODE.get(),
            "model": metadata.model_name,
            "attempts": metadata.retries + 1,
            "elapsed_ms": metadata.request_time_ms,
            "input_tokens": metadata.input_tokens,
            "output_tokens": metadata.output_tokens,
            "cached_input_tokens": metadata.cached_input_tokens,
            "cache_write_input_tokens": metadata.cache_write_input_tokens,
            "reasoning_tokens": metadata.reasoning_tokens,
            "estimated_cost_usd": str(metadata.estimated_cost_usd),
            **provider_identity(api_url=metadata.api_url),
            "local_timings": [
                timing.model_dump(mode="json", exclude_none=True)
                for timing in metadata.local_timings
            ],
        }
    )


@asynccontextmanager
async def stage(node: WorkflowNode) -> AsyncIterator[StageMeasurement]:
    """Emit a start before work and a measured end for success, failure, or cancellation."""
    recorder = _ACTIVE.get()
    measurement = StageMeasurement()
    if recorder is None:
        yield measurement
        return
    started = time.perf_counter()
    started_at = datetime.now(UTC).isoformat()
    initial = StageEvent(
        node=node,
        phase="start",
        status="running",
        started_at=started_at,
        total_elapsed_ms=max(0.0, (started - recorder.started) * 1000),
    )
    if recorder.observer is not None:
        await recorder.observer(initial)
    token = _NODE.set(node)
    try:
        yield measurement
    except BaseException:
        measurement.failed = True
        raise
    finally:
        _NODE.reset(token)
        ended = time.perf_counter()
        event = StageEvent(
            node=node,
            phase="end",
            status="failed" if measurement.failed else "completed",
            resolved_scope=measurement.resolved_scope,
            started_at=started_at,
            elapsed_ms=max(0.0, (ended - started) * 1000),
            total_elapsed_ms=max(0.0, (ended - recorder.started) * 1000),
        )
        recorder.events.append(event)
        if recorder.observer is not None:
            await recorder.observer(event)


def capture_stages[**P, R](function: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
    """Give public and admin review entry points the same request-local recorder."""

    @wraps(function)
    async def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
        """Keep measurements alive through execution and persistence."""
        with record_stages():
            return await function(*args, **kwargs)

    return wrapped


def observed_stage[**P, R](
    node: WorkflowNode,
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Measure one complete async stage without changing its public call signature."""

    def decorate(function: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        """Wrap an async boundary while preserving FastAPI and protocol introspection."""

        @wraps(function)
        async def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
            """Record the actual interval of the decorated operation."""
            async with stage(node):
                return await function(*args, **kwargs)

        return wrapped

    return decorate
