"""Server-sent-events streaming for the evidence-review workflow."""

import asyncio
from collections.abc import AsyncGenerator, Mapping
import contextlib
import logging
from typing import Annotated, Literal

from anyio import CancelScope
from fastapi import APIRouter, Header
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask
from starlette.types import Receive, Scope, Send

from app.api.deps import Services
from app.api.errors import ApiProblemError
from app.api.evidence import EvidenceSelection
from app.api.schemas import (
    ApiError,
    ErrorResponse,
    RetrieveRequest,
    RetrieveResponse,
    ReviewRequest,
    RunResponse,
    StreamNodeEvent,
)
from app.observability.stages import StageEvent, record_stages
from app.observability.types import WorkflowNode
from app.workflow.types import WorkflowState

router = APIRouter(tags=["review"])

type _Event = tuple[str, str]

logger = logging.getLogger(__name__)


class _ClosingStreamingResponse(StreamingResponse):
    """Close the body iterator even when an ASGI send fails."""

    media_type = "text/event-stream"

    def __init__(
        self,
        content: AsyncGenerator[str],
        status_code: int = 200,
        headers: Mapping[str, str] | None = None,
        media_type: str | None = None,
        background: BackgroundTask | None = None,
    ) -> None:
        self._closable_content = content
        super().__init__(
            content,
            status_code=status_code,
            headers=headers,
            media_type=media_type or self.media_type,
            background=background,
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            await self._closable_content.aclose()


def _sse(event: str, data: str) -> str:
    """Format one server-sent event with a named type and single-line JSON data."""
    return f"event: {event}\ndata: {data}\n\n"


@router.post(
    "/review/stream",
    response_class=_ClosingStreamingResponse,
    responses={
        200: {
            "description": "Server-sent workflow progress and terminal report events.",
            "content": {"text/event-stream": {"schema": {"type": "string"}}},
        }
    },
)
async def review_stream(
    request: ReviewRequest,
    services: Services,
    telemetry: Annotated[Literal["stages"] | None, Header(alias="X-DocReview-Telemetry")] = None,
) -> StreamingResponse:
    """Stream node progress and one secret-safe terminal result.

    Parameters
    ----------
    request : ReviewRequest
        Validated review request.
    services : Services
        Injected service boundary with observer support.
    telemetry : Literal["stages"] | None
        Opt-in for additive stage events; omitted headers retain the legacy event sequence.

    Returns
    -------
    StreamingResponse
        SSE stream containing ``node`` events, one ``report`` or ``error``, and
        a final ``done`` marker.

    Notes
    -----
    The producer begins with iterator consumption and is cancelled when the body
    iterator closes, including ASGI send failures and client disconnects.
    """
    queue: asyncio.Queue[_Event | None] = asyncio.Queue()

    async def on_node(node: WorkflowNode, state: WorkflowState) -> None:
        """Queue one progress event per completed node, preserving arrival order."""
        event = StreamNodeEvent(
            node=node,
            evidence_count=len(state.evidence),
            relevant_count=len(state.relevant_chunk_ids),
            step_count=len(state.steps),
        )
        await queue.put(("node", event.model_dump_json()))

    async def on_stage(event: StageEvent) -> None:
        """Queue measured transitions separately from the legacy committed-node events."""
        await queue.put(("stage", event.model_dump_json()))

    async def run_review() -> None:
        """Run the workflow, ending the queue with a report, a typed error, or both closed."""
        with record_stages(on_stage if telemetry == "stages" else None):
            try:
                active_request = request
                if request.evidence_selection is None and hasattr(services, "retrieve"):
                    prepared = await services.retrieve(
                        RetrieveRequest(
                            query=request.query,
                            session_profile=request.session_profile,
                            k=request.k,
                            filters=request.filters,
                        )
                    )
                    if isinstance(prepared, RetrieveResponse):
                        await queue.put(("candidates", prepared.model_dump_json()))
                        if prepared.candidate_token is not None:
                            active_request = request.model_copy(
                                update={
                                    "evidence_selection": EvidenceSelection(
                                        candidate_token=prepared.candidate_token
                                    )
                                }
                            )
                report = await services.review(active_request, on_node)
                payload = RunResponse.from_run_report(report).model_dump_json()
                await queue.put(("report", payload))
            except ApiProblemError as error:
                payload = ErrorResponse(error=error.error).model_dump_json()
                await queue.put(("error", payload))
            except Exception as error:
                logger.error(
                    "Unhandled streamed review error",
                    exc_info=(type(error), error, error.__traceback__),
                )
                payload = ErrorResponse(
                    error=ApiError(
                        code="internal_error",
                        message="The request could not be completed.",
                    )
                ).model_dump_json()
                await queue.put(("error", payload))
            finally:
                await queue.put(None)

    async def events() -> AsyncGenerator[str]:
        """Drain the queue into SSE frames and cancel the producer when the body closes."""
        review_task = asyncio.create_task(run_review())
        try:
            while (item := await queue.get()) is not None:
                yield _sse(*item)
            yield _sse("done", "{}")
        finally:
            # A disconnected client cancels the generator; stop the workflow with it.
            review_task.cancel()
            # The disconnect scope must not cancel the producer's resource cleanup again.
            with CancelScope(shield=True), contextlib.suppress(asyncio.CancelledError):
                await review_task

    return _ClosingStreamingResponse(
        events(),
        headers={"cache-control": "no-store", "x-accel-buffering": "no"},
    )
