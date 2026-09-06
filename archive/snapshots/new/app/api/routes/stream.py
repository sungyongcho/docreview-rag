"""Server-sent-events streaming for the evidence-review workflow."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
import contextlib
import json
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.api.deps import ApiServices, get_api_services
from app.api.schemas import ReviewRequest, RunResponse, StreamNodeEvent
from app.observability import WorkflowNode
from app.workflow import WorkflowState

router = APIRouter(tags=["review"])
Services = Annotated[ApiServices, Depends(get_api_services)]

type _Event = tuple[str, str]


def _sse(event: str, data: str) -> str:
    """Format one server-sent event with a named type and single-line JSON data."""
    return f"event: {event}\ndata: {data}\n\n"


@router.post("/review/stream")
async def review_stream(request: ReviewRequest, services: Services) -> StreamingResponse:
    """Stream node completions while one guarded workflow runs, then its terminal run."""
    queue: asyncio.Queue[_Event | None] = asyncio.Queue()

    async def on_node(node: WorkflowNode, state: WorkflowState) -> None:
        event = StreamNodeEvent(
            node=node,
            evidence_count=len(state.evidence),
            relevant_count=len(state.relevant_chunk_ids),
            step_count=len(state.steps),
        )
        await queue.put(("node", event.model_dump_json()))

    async def run_review() -> None:
        try:
            report = await services.review_stream(request, on_node)
            payload = RunResponse.from_run_report(report).model_dump_json()
            await queue.put(("report", payload))
        except Exception as error:
            # str(error) can carry secrets (a SQLAlchemyError embeds the connection
            # string), so only the exception's class name leaves the process.
            payload = json.dumps({"error_type": type(error).__name__})
            await queue.put(("error", payload))
        finally:
            await queue.put(None)

    review_task = asyncio.create_task(run_review())

    async def events() -> AsyncIterator[str]:
        try:
            while (item := await queue.get()) is not None:
                yield _sse(*item)
            yield _sse("done", "{}")
        finally:
            # A disconnected client cancels the generator; stop the workflow with it.
            review_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await review_task

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"cache-control": "no-store"},
    )
