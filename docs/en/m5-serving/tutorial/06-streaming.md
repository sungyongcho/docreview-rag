# M5.4 Tutorial 6 — Stream the run while it is still running

`POST /review` answers once, at the end. Between the request and that answer sit one retrieval and two guarded LLM calls, and the caller sees none of it. **A client that waits ten seconds on a silent connection cannot tell a slow run from a dead one, and a UI built on that endpoint has nothing to render until everything is already over.**

The workflow itself has always had progress to report — four node transitions — but the HTTP boundary threw that structure away.

**Prerequisite:** tutorials 1–5 are complete and `uv run pytest tests/api/test_08_integration.py -q` passes.

### One-way progress wants SSE, not WebSocket

The client never talks back during a run: it submits one request and consumes progress. That is exactly the shape of Server-Sent Events — a plain HTTP response with `content-type: text/event-stream` whose body is a sequence of `event:`/`data:` line pairs. No connection upgrade, no message routing, and every browser can consume it with `EventSource`.

**The stream carries four event types with one meaning each: `node` for a completed workflow node, `report` for the terminal run, `error` for an unexpected exception, and `done` as the explicit end-of-stream marker.** A failed run is not an `error` — budget exhaustion and schema refusals are structured outcomes, so they arrive as a `report` whose `status` says what happened, exactly as the synchronous endpoint reports them.

### The observer crosses two seams without breaking either

The runner gained one optional parameter: `run_workflow(..., on_node=...)` awaits the observer after every committed node transition with the node name and the committed state. The default is `None`, so every existing caller — and every test written before this tutorial — behaves identically.

The service boundary mirrors it: `ApiServices.review_stream(request, on_node)` runs the same guarded, persisted review as `review`, with node reporting attached. **The route owns the queue and the SSE formatting; the runner owns the node semantics; the service seam in between stays a plain awaited call — no layer knows how the other two work.**

### What to define, what to implement, and what to inspect

| Area | Learning action | What to take away |
|---|---|---|
| `StreamNodeEvent` | **Write the model declaration** | The smallest progress payload worth sending |
| `review_stream` service seam | **Inspect the boundary conversion** | How an observer crosses layers without coupling them |
| `_sse` and the stream route | **Implement** the queue bridge yourself | Why a queue separates producing from sending |

### 1. The progress payload

#### Extend `app/api/schemas.py` — the node event

**Learning action — write the model declaration:** decide what a progress consumer actually needs before the terminal report exists.

<!-- src: app/api/schemas.py::StreamNodeEvent -->
```python
class StreamNodeEvent(StrictApiModel):
    """One completed workflow node reported while a streamed review is running."""

    node: WorkflowNode
    evidence_count: NonnegativeInt
    relevant_count: NonnegativeInt
    step_count: NonnegativeInt
```

**What to look for in the code**

- Three counters and a node name. No chunk bodies, no scores, no partial answers — **anything a progress event leaks becomes public API surface, so the event carries only what a progress bar can use.**
- The counts come from the committed workflow state, so `evidence_count` after `retrieve` and `step_count` after `grade` and `check` tell the consumer which stage did the work.

### 2. The queue bridge

#### Create `app/api/routes/stream.py` — the SSE route

**Learning action — implement the queue bridge:** trace who puts into the queue, who reads from it, and which task ends first.

<!-- src: app/api/routes/stream.py::_sse,review_stream -->
```python
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
```

**What to look for in the code**

- The workflow runs in its own task and only ever **puts**; the response generator only ever **gets**. **The queue is what lets a slow client and a fast workflow proceed at their own pace without either blocking the other's logic.**
- `None` is the producer's end-of-stream sentinel, placed in `finally` so it is sent whether the review returned, failed, or raised. The consumer emits `done` only after seeing it — the client can always distinguish a finished stream from a cut connection.
- The broad `except` exists because this response has already started. **Once the first byte of a `200` stream is on the wire, an exception can no longer become a status code — a typed `error` event is the only honest channel left.**
- The generator's `finally` cancels the review task. When a client disconnects mid-run, the server does not keep paying for LLM calls nobody will read.
- HTTP-level validation still happens before any of this: a blank query never reaches the stream and fails as a plain `422`, exactly like the synchronous endpoint.

### Focused tests and the contract they keep

```bash
uv run pytest tests/api/test_09_stream.py -q
```

| What the test breaks | Contract it protects |
|---|---|
| A full successful run | Events arrive as `node`×4, then `report`, then `done`, in order |
| A budget-exhausted run | Structured failures arrive as a `report`, never as an `error` |
| A service that raises | Unexpected exceptions become one typed `error` event before `done` |
| A blank query | Request validation still fails as `422` before the stream starts |

### What you should be able to explain now

The answers are in the **bold key sentences** above. Connect each answer to the seam that owns it.

- **Why does the synchronous endpoint alone make a progress UI impossible?**
  - **Answer:** It answers once at the end, so a waiting client cannot distinguish a slow run from a dead one and has nothing to render until the run is over.
- **Why is a failed run a `report` event rather than an `error` event?**
  - **Answer:** Budget exhaustion and refusals are structured outcomes with a status of their own; `error` is reserved for exceptions that produced no terminal run at all.
- **Why does the route need a queue instead of yielding from the observer directly?**
  - **Answer:** Producing and sending run at different speeds in different tasks; the queue decouples them so neither blocks the other's logic.
- **Why can an exception mid-stream not become an HTTP status code?**
  - **Answer:** The `200` header and earlier bytes are already sent; the only honest channel left inside the body is a typed `error` event.
- **What stops the server from finishing a run nobody is listening to?**
  - **Answer:** Client disconnect finalizes the generator, whose `finally` cancels the review task before more provider calls are made.

---

[← Previous: CLI and assembly](05-cli.md) · [Module overview](../03-build.md)
