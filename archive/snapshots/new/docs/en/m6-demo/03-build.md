# M6 Build — Legible to Someone Who Did Not Build It

## An API convinces nobody

After M5 the system is complete. `curl` the `/review` endpoint and an evidence-bound answer comes back as JSON.

Show that JSON to a hiring manager or a colleague, though, and nothing about it looks remarkable. This project's central claim — **"every answer is verifiable against source coordinates"** — is buried in field names.

M6 makes it visible. Three things get surfaced.

- is this answer **supported by the documents, or not** (M4's `NOT_IN_DOCS` earns its keep)
- **where in the source** the evidence came from (coordinates and hash)
- was a provider **actually called**, and what did it cost

## No second reasoning path for the screen

This is the most common temptation when building a UI. The shape the API returns does not quite fit the screen, so the demo computes something slightly different.

At that moment **what the demo shows and what the system does diverge.** It works in the demo and the real API behaves differently — the worst possible state for a portfolio.

So `app/demo.py` **only projects.** Taking a typed M5 result and converting it into Gradio values is all it does. No judgment, no filtering, no recomputation.

## Checkpoint map

| Order | Step | Concept | Main files | State |
|---:|---|---|---|---|
| 1 | M6.1 | Make evidence and refusal behavior visible | `app/demo.py` | Complete |
| 2 | M6.2 | Turn measurements and tradeoffs into an honest portfolio | `README.md`, bilingual reports, M6 docs | Complete |
| 3 | M6.3 | Prove the demo against the production M5 seam | Existing demo/runtime files | Complete |

---

## M6.1 — A Gradio demo that shows the evidence

### Why there are two modes

The demo has a **canned** mode and a **runtime** mode.

Canned mode returns deterministic evidence. It calls no provider, so it is **free** and needs no network. Whoever opens the link sees the same screen every time.

Runtime mode delegates to the real M5 seam. Use it to show the thing actually working.

Leave a portfolio demo public and there is no telling who will call it or how often. Defaulting to the free path lets it stay open without worrying about a leaked API key or a cost spike. **Having credentials does not automatically enable paid calls** — the same rule confirmed in M5.3 carries over here.

### The path from service result to screen

1. A Gradio event sends the query, mode, and retrieval limit to an injected `DemoService`. 2. Canned mode returns deterministic evidence; runtime mode delegates through the M5 service seam. 3. Both paths produce one immutable `DemoResult`. 4. `render_result()` converts that result into answer, support, trace, and evidence outputs.

| Contract | Fields | Screen role |
|---|---|---|
| `DemoEvidence` | `citation`, `span`, `source_sha256`, `chunk_id`, `body` | Gives the evidence panel both human and machine source identity. |
| `DemoTrace` | `mode`, `status`, `model`, requests, token counts, estimated cost, latency, optional error | Shows whether a provider ran, what it consumed, and why it failed. |
| `DemoResult` | `answer`, `supported`, `evidence`, `trace` | Carries every value needed to render one query without recomputing domain logic. |

`render_result()` is that projection in full. In the code, each evidence item forwards `citation`, `span`, `source_sha256`, `chunk_id`, and `body` as-is. **Putting coordinates and hashes on screen is the point** — a reviewer can open the source directly with those values.

The trace line is the same. `mode`, `status`, `model`, request count, token counts, estimated cost, and latency all show verbatim. **If the model was not called, the screen says so**, removing any room to suspect the demo is really showing hardcoded answers.

### What to define, what to implement, and what to inspect

One file, `app/demo.py`, in six steps. It is screen code with not one line of domain logic.

| Area | Learning action | What to take away |
|---|---|---|
| `DemoEvidence`, `DemoTrace`, `DemoResult` | **Write the record declarations** | The minimum set of values a screen needs |
| `DemoService` and `M5Service` | **Review the design decision** | How the demo holds M5 loosely |
| `CannedDemoService` | **Define the structure** | Why the free default path is deterministic |
| `RuntimeDemoService` | **Implement** the boundary conversion yourself | Where an M5 result becomes a screen value |
| `render_result` | **Write the field mapping** | Why coordinates and hashes go on screen |
| `build_demo` | **Define the structure** | Event wiring and the default mode |

### 1. The minimum set of values a screen needs

#### Create `app/demo.py` — module header

**Learning action — define the structure:** `gradio` and M5's seam sit side by side in the imports.

```python
"""Small, deterministic Gradio portfolio demo for the M5 serving surface."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Literal, Protocol

from app.api.errors import ApiProblemError
from app.api.schemas import RetrieveRequest, ReviewRequest
from app.retrieval import ChunkHit, RetrievalFilters, RetrievalResult
```

#### Extend `app/demo.py` — demo records

**Learning action — write the record declarations:** trace which M2 or M4 value each of the three records derives from.

<!-- src: app/demo.py::HERO_EXAMPLES,DemoResult -->
```python
HERO_EXAMPLES = (
    "What revenue did Acme report in fiscal year 2024?",
    "What does the filing say about an acquisition?",
)


@dataclass(frozen=True)
class DemoEvidence:
    """Public evidence identity shown in the demo."""

    citation: str
    span: str
    source_sha256: str
    chunk_id: int
    body: str


@dataclass(frozen=True)
class DemoTrace:
    """Trace and cost summary with no provider secrets."""

    mode: str
    status: str
    model: str
    requests: int
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: str
    latency_ms: float = 0.0
    error: str | None = None


@dataclass(frozen=True)
class DemoResult:
    """Complete renderable result for one demo query."""

    answer: str
    supported: bool
    evidence: tuple[DemoEvidence, ...]
    trace: DemoTrace
```

**What to look for in the code**

- `DemoEvidence` carries `span` and `source_sha256`. **Putting coordinates and hashes on screen is the point** — a reviewer can open the source directly with those values.
- `DemoTrace` carries `mode`, `status`, `model`, request count, token counts, estimated cost, and latency. If the model was not called, **the screen says so**, removing any room to suspect the demo is really showing hardcoded answers.
- `HERO_EXAMPLES` is a constant. It stops whoever opens the link from facing a blank screen with no idea what to ask.

### 2. How the demo holds M5 loosely

#### Extend `app/demo.py` — service protocols

**Learning action — review the design decision:** note that `M5Service` describes only part of `ApiServices`, not all of it.

<!-- src: app/demo.py::DemoService,M5Service -->
```python
class DemoService(Protocol):
    """Injectable service boundary for deterministic or live demo mode."""

    def run(self, query: str) -> DemoResult: ...


class M5Service(Protocol):
    """Minimal API seam required by the live adapter."""

    async def retrieve(self, request: RetrieveRequest) -> RetrievalResult: ...

    async def review(self, request: ReviewRequest): ...
```

**What to look for in the code**

- `M5Service` describes only the methods the demo actually uses. Demanding all of `ApiServices` would force demo tests to imitate seven methods.
- `DemoService` is the screen-side contract. Canned and runtime share one shape.

### 3. The free default path

#### Extend `app/demo.py` — the canned service

**Learning action — define the structure:** note what canned mode does *not* do.

<!-- src: app/demo.py::CannedDemoService,LiveDemoService -->
```python
class CannedDemoService:
    """Offline examples that make supported and unsupported behavior obvious."""

    def run(self, query: str) -> DemoResult:
        normalized = query.strip().lower()
        supported = "revenue" in normalized or "acme" in normalized
        if supported:
            evidence = (
                DemoEvidence(
                    citation="Acme 10-K (2024), Item 8, p. 42",
                    span="chars 1204-1297",
                    source_sha256="a" * 64,
                    chunk_id=42,
                    body="Revenue increased to $12.4 million in fiscal year 2024.",
                ),
            )
            answer = "Supported by the filing: Acme reported $12.4 million in 2024 revenue."
        else:
            evidence = ()
            answer = "Not supported by the supplied documents; the demo will not guess."
        return DemoResult(
            answer=answer,
            supported=supported,
            evidence=evidence,
            trace=DemoTrace(
                mode="canned",
                status="ok" if supported else "retrieval_empty",
                model="deterministic",
                requests=0,
                input_tokens=0,
                output_tokens=0,
                estimated_cost_usd="0.000000",
            ),
        )


class LiveDemoService:
    """Adapter for an injected local service; credentials never enter the UI."""

    def __init__(self, callback: DemoService) -> None:
        self._callback = callback

    def run(self, query: str) -> DemoResult:
        return self._callback.run(query)
```

**What to look for in the code**

- It calls no provider and no database. It is **free and needs no network.** Whoever opens the link sees the same screen every time.
- `status` is `"canned"`. It goes straight to the screen, so the fact that this is not real inference is never hidden.

### 4. Where an M5 result becomes a screen value

#### Extend `app/demo.py` — the runtime service

**Learning action — implement the boundary conversion:** implement the part that builds a `DemoTrace` from M5's result yourself.

<!-- src: app/demo.py::RuntimeDemoService -->
```python
class RuntimeDemoService:
    """Use the injected M5 services; never discover credentials or call providers."""

    def __init__(self, services: M5Service) -> None:
        self._services = services

    async def run_async(
        self,
        query: str,
        *,
        mode: Literal["query", "review"] = "query",
        k: int = 5,
        filters: RetrievalFilters | None = None,
    ) -> DemoResult:
        started = time.perf_counter()
        try:
            request_filters = filters or RetrievalFilters()
            retrieval = await self._services.retrieve(
                RetrieveRequest(query=query, k=k, filters=request_filters)
            )
            evidence = tuple(_evidence(item) for item in retrieval.hits)
            if mode == "review":
                report = await self._services.review(
                    ReviewRequest(query=query, k=k, filters=request_filters)
                )
                answer = (
                    str(report.report) if report.report is not None else "No report was produced."
                )
                trace = DemoTrace(
                    mode="review",
                    status=report.status,
                    model=report.steps[-1].model_name if report.steps else "none",
                    requests=report.total_requests,
                    input_tokens=report.total_input_tokens,
                    output_tokens=report.total_output_tokens,
                    estimated_cost_usd="not computed by the API seam",
                    latency_ms=(time.perf_counter() - started) * 1000,
                )
            else:
                answer = "Evidence retrieved; review mode was not requested."
                trace = DemoTrace(
                    mode="query",
                    status="ok" if evidence else "retrieval_empty",
                    model="retrieval",
                    requests=0,
                    input_tokens=0,
                    output_tokens=0,
                    estimated_cost_usd="0.000000",
                    latency_ms=(time.perf_counter() - started) * 1000,
                )
            return DemoResult(answer, bool(evidence), evidence, trace)
        except ApiProblemError as error:
            return DemoResult(
                answer="The service is unavailable; no provider call was attempted.",
                supported=False,
                evidence=(),
                trace=DemoTrace(
                    mode=mode,
                    status=error.error.code,
                    model="none",
                    requests=0,
                    input_tokens=0,
                    output_tokens=0,
                    estimated_cost_usd="0.000000",
                    latency_ms=(time.perf_counter() - started) * 1000,
                    error=error.error.message,
                ),
            )
```

**What to look for in the code**

- **No second inference path is built.** It calls M5's seam as-is and only moves the result into screen values. That is what guarantees the demo shows the real system.
- Exceptions are caught into `DemoTrace.error`. The demo never sprays a stack trace onto the screen.
- Cost and tokens come from M4.2's report. The demo does not count them itself.

### 5. Putting coordinates and hashes on screen

#### Extend `app/demo.py` — rendering the result

**Learning action — write the field mapping:** note which fields each evidence item forwards untouched.

<!-- src: app/demo.py::_evidence,render_result -->
```python
def _evidence(item: ChunkHit) -> DemoEvidence:
    """Convert one M5 evidence card without retaining internal fields."""
    return DemoEvidence(
        citation=item.citation,
        span=f"chars {item.start_char}-{item.end_char}",
        source_sha256=item.source_sha256,
        chunk_id=item.chunk_id,
        body=item.body,
    )


def render_result(result: DemoResult) -> tuple[str, str, str, list[dict[str, object]]]:
    """Convert typed result data into safe Gradio values."""
    evidence = [
        {
            "citation": item.citation,
            "span": item.span,
            "source_sha256": item.source_sha256,
            "chunk_id": item.chunk_id,
            "body": item.body,
        }
        for item in result.evidence
    ]
    trace = (
        f"mode={result.trace.mode} | status={result.trace.status} | model={result.trace.model}\n"
        f"requests={result.trace.requests} | input_tokens={result.trace.input_tokens} | "
        f"output_tokens={result.trace.output_tokens} | "
        f"estimated_cost_usd={result.trace.estimated_cost_usd} | "
        f"latency_ms={result.trace.latency_ms:.2f}"
    )
    if result.trace.error:
        trace += f"\nerror={result.trace.error}"
    support = (
        "Supported by the supplied documents."
        if result.supported
        else "Not in the supplied documents."
    )
    return result.answer, support, trace, evidence
```

**What to look for in the code**

- `citation`, `span`, `source_sha256`, `chunk_id`, and `body` pass through **as-is**. Nothing is reprocessed.
- The trace is a single line of text. `error` is appended only on failure.
- The return is a four-value tuple matching the order of Gradio's four output components.

### 6. Event wiring and the default mode

#### Complete `app/demo.py` — assembling the demo

**Learning action — define the structure:** note the default mode and why it is that one.

<!-- src: app/demo.py::build_demo -->
```python
def build_demo(
    service: DemoService | None = None,
    *,
    release_notice: str | None = None,
):
    """Build the UI without starting a server or retaining secrets in client state."""
    try:
        import gradio as gr
    except ImportError as error:
        raise RuntimeError(
            "Install the optional 'demo' dependency to launch the Gradio UI."
        ) from error

    selected_service = service or CannedDemoService()
    selected_notice = release_notice or (
        "Deployment mode: local runtime; provider access depends on server configuration."
        if isinstance(selected_service, RuntimeDemoService)
        else "Deployment mode: canned fixture; provider requests and cost are zero."
    )

    async def submit(
        query: str,
        mode: str,
        k: int,
    ) -> tuple[str, str, str, list[dict[str, object]]]:
        if isinstance(selected_service, RuntimeDemoService):
            result = await selected_service.run_async(query, mode=mode, k=k)
        else:
            result = selected_service.run(query)
        return render_result(result)

    with gr.Blocks(title="Document Review Evidence Demo") as demo:
        gr.Markdown(
            "# Document Review Evidence Demo\n"
            "Explore cited answers without exposing provider secrets.\n\n"
            f"**{selected_notice}**"
        )
        query = gr.Textbox(label="Ask about the filing", value=HERO_EXAMPLES[0])
        gr.Examples(examples=[[example] for example in HERO_EXAMPLES], inputs=query)
        modes = (
            ["query", "review"] if isinstance(selected_service, RuntimeDemoService) else ["canned"]
        )
        mode = gr.Radio(modes, value=modes[0], label="Mode")
        k = gr.Slider(1, 10, value=5, step=1, label="Evidence count")
        run = gr.Button("Review evidence", variant="primary")
        answer = gr.Markdown(label="Answer")
        support = gr.Markdown(label="Evidence boundary")
        trace = gr.Markdown(label="Trace and cost transparency")
        evidence = gr.JSON(label="Evidence cards")
        run.click(submit, inputs=[query, mode, k], outputs=[answer, support, trace, evidence])
    return demo
```

**What to look for in the code**

- The default mode is canned. **Having credentials does not automatically enable paid calls** — the rule confirmed in M5.3 carries over here.
- `service` is injected. A test can insert a fake and verify only the screen wiring.
- There is not one line of domain logic. This file moves values and wires events.

Append the module execution guard at the end of the file. Those two lines are what make `python -m app.demo` work.

```python
if __name__ == "__main__":
    build_demo().launch()
```

### Launch the smallest honest demo

Prerequisite: M5.3 passes; Python 3.14+, uv, and loopback port 7861 are available.

```bash
uv sync --locked --extra demo
uv run pytest tests/demo -q
uv run --extra demo python - <<'PY'
from app.demo import build_demo

demo = build_demo()
_, local_url, _ = demo.launch(
    server_name="127.0.0.1",
    server_port=7861,
    prevent_thread_lock=True,
    quiet=True,
)
print(local_url)
demo.close()
PY
```

Read the green result as evidence for the claim made in this chapter, and no broader.

Locked sync completes without changing `uv.lock`, every demo test passes, the printed URL is `http://127.0.0.1:7861/`, and the server closes cleanly. The UI distinguishes supported from unsupported answers and exposes evidence identity without exposing secrets.

Do not start M6.2 if the dependency lock changes unexpectedly, collection skips a missing canonical symbol, canned mode can call a provider, evidence identity is absent, or loopback launch and close fail.

When the result disagrees with the chapter, trace the first boundary that changed:

- If import or collection fails, compare `app/demo.py` with the complete M6.1 block above.
- If outputs have the wrong shape, trace `DemoResult` -> `render_result()` -> Gradio output components in `build_demo()`.
- If the smoke command cannot bind, free port 7861 or choose another loopback port in both `server_port` and the expected URL; do not expose the server publicly.

## M6.2 — A portfolio is an evidence map, not a technology list

There is one easy mistake to make in this project's documentation: listing technologies — **"uses PostgreSQL, pgvector, FastAPI, LangGraph."**

To a reader that carries no information. Having used something is different from having used it well, and following a tutorial is different from having solved a problem.

So M6.2's rules are these.

**Every quantitative claim must point at something in the repository.** A test, a raw M3 artifact, a measured report. To write "recall 0.82," the file that number came from has to be committed.

**Every limitation must sit beside the result it constrains.** Push limitations to the end and nobody reads them. That the golden data has not been human-verified belongs directly next to the evaluation number.

**Commands say which path they are.** Canned, local runtime, paid, or deployment. A reader who copies and pastes must not get an unexpected bill.

Notice that this principle is the same one running through the whole project. M1.1's coordinates, M3's golden evidence, M4's citation checks — all of it was **"attach evidence to every claim."** Documentation is no exception.

### Turn measurements into a reader’s path

1. Raw M3 artifacts provide measurements. 2. Architecture and evaluation documents explain boundaries, tradeoffs, and results. 3. Failure analysis connects bad outcomes to deterministic guards and tests. 4. Locale-specific M6 guides lead the reader from setup to verification. 5. The root README exposes only commands and claims supported by those artifacts.

### Write the portfolio from evidence outward

M6.2 adds no application module. Update and verify the existing documentation surfaces in this order:

1. `docs/en/architecture.md` 2. `docs/ko/architecture.md` 3. `docs/en/eval-report.md` 4. `docs/ko/eval-report.md` 5. `docs/en/failure-analysis.md` 6. `docs/ko/failure-analysis.md` 7. `docs/en/m6-demo/00-README.md` through `docs/en/m6-demo/05-verify.md` 8. `docs/ko/m6-demo/00-README.md` through `docs/ko/m6-demo/05-verify.md` 9. `docs/00-README.md` 10. `docs/project/module-plan.md` 11. `README.md`

### Let the documentation check itself

Prerequisite: M5.3 and M6.1 pass, and every reported M3 measurement points to a committed raw artifact.

```bash
uv run pytest tests/test_doc_sync.py tests/test_doc_parity.py -q
```

Read the green result as evidence for the claim made in this chapter, and no broader.

Every selected test passes. Source-linked blocks, bilingual structure, relative links, and protected technical literals remain synchronized; no measured claim is accepted merely because it sounds plausible.

Do not start M6.3 if a measurement lacks repository evidence, a canned result is labeled live, a placeholder is presented as a screenshot, a command cannot be copied, or EN/KO structure differs.

When the result disagrees with the chapter, trace the first boundary that changed:

- For source-sync failures, use the first reported document and source marker; repair the prose or canonical source instead of weakening the checker.
- For parity failures, compare the reported structural field in the EN/KO pair while keeping ordinary Korean prose translated.
- For link failures, resolve the target from the current locale directory, not from the repository root.

## M6.3 — Proving the demo shows the real thing

The same kind of check as M5.3. The pieces can each pass and the assembly still be wrong.

M6.1's rendering tests ran on canned data. M6.2's documentation checks looked only at text. **Both can pass and the real demo still break** if the runtime adapter returns a different shape.

For a portfolio that is fatal. Worse than the screen breaking in front of someone you sent the link to is the screen looking fine while it was actually hardcoded.

So M6.3 checks three things.

- does the demo consume **real M5 runtime results**
- do all interfaces present mode, evidence, and limitations **consistently**
- was the full-suite result **freshly measured** (rather than copied from an earlier total)

The last sounds trivial and is not. Copy a number like a test count from an earlier document and from that moment the documentation's numbers drift from reality. **A measurement written into documentation has to be one that was actually taken then.**

### Reconnect the polished surface to production

1. The Gradio event enters `RuntimeDemoService`. 2. Query mode consumes `RetrievalResult.hits`; review mode consumes the M4 terminal report. 3. Both paths map into `DemoResult` and reuse `render_result()`. 4. Integration tests compare the demo seam with the M5 HTTP/CLI evidence contract. 5. Documentation records only the freshly observed behavior.

### Audit the joins instead of adding code

M6.3 adds no second implementation. Re-read and verify these existing files in order:

1. `app/demo.py` 2. `app/api/runtime.py` 3. `tests/demo/test_demo.py` 4. `tests/api/test_08_integration.py` 5. `README.md` 6. `docs/en/m6-demo/05-verify.md` 7. `docs/ko/m6-demo/05-verify.md`

### Run the demo through the real seam

Prerequisite: M6.1 and M6.2 pass, and the M5 `RetrievalResult` domain type is available.

```bash
uv run pytest tests/demo tests/api/test_08_integration.py -q
```

Read the green result as evidence for the claim made in this chapter, and no broader.

Every selected test passes. Runtime results use the production `RetrievalResult.hits` shape, CLI/API/demo evidence agrees, and canned versus runtime labeling remains explicit.

M6 is incomplete if collection skips a missing canonical symbol, the production return shape is bypassed, a runtime run is labeled canned or the reverse, a screenshot is stale or unlabeled, ambient credentials activate a provider, or evidence differs across surfaces.

When the result disagrees with the chapter, trace the first boundary that changed:

- For return-shape failures, inspect the adapter from `RetrievalResult.hits` to `DemoEvidence`; do not add a demo-only retrieval model.
- For mode-label failures, trace the selected service and mode before changing rendered text.
- For evidence mismatches, compare citation, span, source hash, chunk ID, and body at the M5 boundary and the demo projection.

## Final quality gate

```bash
uv run pytest -o addopts="" -q
uv run ruff check --no-fix app tests scripts
uv run ruff format --check app tests scripts
uv run python scripts/check_doc_code.py docs/en/m6-demo/03-build.md docs/ko/m6-demo/03-build.md
uv run pytest tests/test_doc_sync.py tests/test_doc_parity.py -q
git diff --check
```

Expected result: every command exits with status 0. Record the measured full-suite result and its intentional skips instead of copying an older count.

---

## What this module hands to the next one

After M6 the system is **showable**. What remains is deployment.

| What M6 produced | Receiver | What happens there |
|---|---|---|
| `app/demo.py` | **M7** | demo container entrypoint |
| canned mode | **M7** | public deployment without credentials |
| portfolio documentation | **M7** | artifacts included in the release |
| documentation sync tests | **M7** | CI gates |

The next chapter, M7, deploys it. The same principle continues there — **having credentials is not consent, and a public demo is not the whole system.** Release configuration has to be deterministic, and what was actually published has to be distinguished from what is merely metadata.

## What you should be able to explain now

- **Why must there be no second reasoning path built for the screen?**
  - **Answer:** A separate screen-side path could drift from the M5 logic and display a result the real system never produced. Reusing the M5 seam keeps the demo a projection of the same reasoning path.
- **Why must canned mode and live runtime mode be distinguished on screen?**
  - **Answer:** Canned mode uses deterministic prepared evidence without a provider call, while runtime mode executes the real M5 path. Labeling them prevents a free fixture from being mistaken for live inference and makes cost claims honest.
- **What difference does exposing coordinates and hashes on screen make to what the demo claims?**
  - **Answer:** Coordinates identify the exact source span, and the hash identifies the source snapshot in which that span is valid. A reviewer can therefore verify the evidence directly instead of trusting a citation label.
- **What does it mean to write a portfolio as an evidence map rather than a technology list?**
  - **Answer:** Each claim is linked to the artifact, command, test, or measurement that supports it, with limitations beside the affected result. Technology names alone show what was used, not what was proved.
- **What happens to a document when a test count is copied from an earlier one?**
  - **Answer:** The copied count becomes stale as the suite changes, so the document starts presenting an old number as a current measurement. Test counts must be measured again when they are reported.
- **What proves that what the demo shows is the real thing?**
  - **Answer:** No single current check proves the full UI-to-M5 path. Demo route tests verify evidence and mode labels with a controlled service, while M5 API integration tests verify the production runtime separately. A direct UI-to-production-runtime integration test would be needed for complete end-to-end proof.

## Machine-verified final reference

The chapters above are the build path. The generated section below is a byte-for-byte final reference against `reference_revision`, not a prerequisite to use before M6.1. Use it to compare the finished files after the three checkpoints.

<!-- complete-files:start -->
## Reference baseline — the complete canonical files

Create or replace the canonical paths below directly. Do not create `_mine.py` or another learner-copy module. The earlier excerpts explain individual decisions; the blocks in this section are the finished files to compare against once a checkpoint is done. Preserve the shown type annotations and English comments; `pyproject.toml` is the authoritative Ruff policy.

### M6.1 — Complete checkpoint

#### Create or replace `app/demo.py`

<!-- file: app/demo.py -->
```python
"""Small, deterministic Gradio portfolio demo for the M5 serving surface."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Literal, Protocol

from app.api.errors import ApiProblemError
from app.api.schemas import RetrieveRequest, ReviewRequest
from app.retrieval import ChunkHit, RetrievalFilters, RetrievalResult

HERO_EXAMPLES = (
    "What revenue did Acme report in fiscal year 2024?",
    "What does the filing say about an acquisition?",
)


@dataclass(frozen=True)
class DemoEvidence:
    """Public evidence identity shown in the demo."""

    citation: str
    span: str
    source_sha256: str
    chunk_id: int
    body: str


@dataclass(frozen=True)
class DemoTrace:
    """Trace and cost summary with no provider secrets."""

    mode: str
    status: str
    model: str
    requests: int
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: str
    latency_ms: float = 0.0
    error: str | None = None


@dataclass(frozen=True)
class DemoResult:
    """Complete renderable result for one demo query."""

    answer: str
    supported: bool
    evidence: tuple[DemoEvidence, ...]
    trace: DemoTrace


class DemoService(Protocol):
    """Injectable service boundary for deterministic or live demo mode."""

    def run(self, query: str) -> DemoResult: ...


class M5Service(Protocol):
    """Minimal API seam required by the live adapter."""

    async def retrieve(self, request: RetrieveRequest) -> RetrievalResult: ...

    async def review(self, request: ReviewRequest): ...


class CannedDemoService:
    """Offline examples that make supported and unsupported behavior obvious."""

    def run(self, query: str) -> DemoResult:
        normalized = query.strip().lower()
        supported = "revenue" in normalized or "acme" in normalized
        if supported:
            evidence = (
                DemoEvidence(
                    citation="Acme 10-K (2024), Item 8, p. 42",
                    span="chars 1204-1297",
                    source_sha256="a" * 64,
                    chunk_id=42,
                    body="Revenue increased to $12.4 million in fiscal year 2024.",
                ),
            )
            answer = "Supported by the filing: Acme reported $12.4 million in 2024 revenue."
        else:
            evidence = ()
            answer = "Not supported by the supplied documents; the demo will not guess."
        return DemoResult(
            answer=answer,
            supported=supported,
            evidence=evidence,
            trace=DemoTrace(
                mode="canned",
                status="ok" if supported else "retrieval_empty",
                model="deterministic",
                requests=0,
                input_tokens=0,
                output_tokens=0,
                estimated_cost_usd="0.000000",
            ),
        )


class LiveDemoService:
    """Adapter for an injected local service; credentials never enter the UI."""

    def __init__(self, callback: DemoService) -> None:
        self._callback = callback

    def run(self, query: str) -> DemoResult:
        return self._callback.run(query)


class RuntimeDemoService:
    """Use the injected M5 services; never discover credentials or call providers."""

    def __init__(self, services: M5Service) -> None:
        self._services = services

    async def run_async(
        self,
        query: str,
        *,
        mode: Literal["query", "review"] = "query",
        k: int = 5,
        filters: RetrievalFilters | None = None,
    ) -> DemoResult:
        started = time.perf_counter()
        try:
            request_filters = filters or RetrievalFilters()
            retrieval = await self._services.retrieve(
                RetrieveRequest(query=query, k=k, filters=request_filters)
            )
            evidence = tuple(_evidence(item) for item in retrieval.hits)
            if mode == "review":
                report = await self._services.review(
                    ReviewRequest(query=query, k=k, filters=request_filters)
                )
                answer = (
                    str(report.report) if report.report is not None else "No report was produced."
                )
                trace = DemoTrace(
                    mode="review",
                    status=report.status,
                    model=report.steps[-1].model_name if report.steps else "none",
                    requests=report.total_requests,
                    input_tokens=report.total_input_tokens,
                    output_tokens=report.total_output_tokens,
                    estimated_cost_usd="not computed by the API seam",
                    latency_ms=(time.perf_counter() - started) * 1000,
                )
            else:
                answer = "Evidence retrieved; review mode was not requested."
                trace = DemoTrace(
                    mode="query",
                    status="ok" if evidence else "retrieval_empty",
                    model="retrieval",
                    requests=0,
                    input_tokens=0,
                    output_tokens=0,
                    estimated_cost_usd="0.000000",
                    latency_ms=(time.perf_counter() - started) * 1000,
                )
            return DemoResult(answer, bool(evidence), evidence, trace)
        except ApiProblemError as error:
            return DemoResult(
                answer="The service is unavailable; no provider call was attempted.",
                supported=False,
                evidence=(),
                trace=DemoTrace(
                    mode=mode,
                    status=error.error.code,
                    model="none",
                    requests=0,
                    input_tokens=0,
                    output_tokens=0,
                    estimated_cost_usd="0.000000",
                    latency_ms=(time.perf_counter() - started) * 1000,
                    error=error.error.message,
                ),
            )


def _evidence(item: ChunkHit) -> DemoEvidence:
    """Convert one M5 evidence card without retaining internal fields."""
    return DemoEvidence(
        citation=item.citation,
        span=f"chars {item.start_char}-{item.end_char}",
        source_sha256=item.source_sha256,
        chunk_id=item.chunk_id,
        body=item.body,
    )


def render_result(result: DemoResult) -> tuple[str, str, str, list[dict[str, object]]]:
    """Convert typed result data into safe Gradio values."""
    evidence = [
        {
            "citation": item.citation,
            "span": item.span,
            "source_sha256": item.source_sha256,
            "chunk_id": item.chunk_id,
            "body": item.body,
        }
        for item in result.evidence
    ]
    trace = (
        f"mode={result.trace.mode} | status={result.trace.status} | model={result.trace.model}\n"
        f"requests={result.trace.requests} | input_tokens={result.trace.input_tokens} | "
        f"output_tokens={result.trace.output_tokens} | "
        f"estimated_cost_usd={result.trace.estimated_cost_usd} | "
        f"latency_ms={result.trace.latency_ms:.2f}"
    )
    if result.trace.error:
        trace += f"\nerror={result.trace.error}"
    support = (
        "Supported by the supplied documents."
        if result.supported
        else "Not in the supplied documents."
    )
    return result.answer, support, trace, evidence


def build_demo(
    service: DemoService | None = None,
    *,
    release_notice: str | None = None,
):
    """Build the UI without starting a server or retaining secrets in client state."""
    try:
        import gradio as gr
    except ImportError as error:
        raise RuntimeError(
            "Install the optional 'demo' dependency to launch the Gradio UI."
        ) from error

    selected_service = service or CannedDemoService()
    selected_notice = release_notice or (
        "Deployment mode: local runtime; provider access depends on server configuration."
        if isinstance(selected_service, RuntimeDemoService)
        else "Deployment mode: canned fixture; provider requests and cost are zero."
    )

    async def submit(
        query: str,
        mode: str,
        k: int,
    ) -> tuple[str, str, str, list[dict[str, object]]]:
        if isinstance(selected_service, RuntimeDemoService):
            result = await selected_service.run_async(query, mode=mode, k=k)
        else:
            result = selected_service.run(query)
        return render_result(result)

    with gr.Blocks(title="Document Review Evidence Demo") as demo:
        gr.Markdown(
            "# Document Review Evidence Demo\n"
            "Explore cited answers without exposing provider secrets.\n\n"
            f"**{selected_notice}**"
        )
        query = gr.Textbox(label="Ask about the filing", value=HERO_EXAMPLES[0])
        gr.Examples(examples=[[example] for example in HERO_EXAMPLES], inputs=query)
        modes = (
            ["query", "review"] if isinstance(selected_service, RuntimeDemoService) else ["canned"]
        )
        mode = gr.Radio(modes, value=modes[0], label="Mode")
        k = gr.Slider(1, 10, value=5, step=1, label="Evidence count")
        run = gr.Button("Review evidence", variant="primary")
        answer = gr.Markdown(label="Answer")
        support = gr.Markdown(label="Evidence boundary")
        trace = gr.Markdown(label="Trace and cost transparency")
        evidence = gr.JSON(label="Evidence cards")
        run.click(submit, inputs=[query, mode, k], outputs=[answer, support, trace, evidence])
    return demo


if __name__ == "__main__":
    build_demo().launch()
```

Run the checkpoint:

```bash
uv run pytest tests/demo -q
```

**Expected:** every selected offline test passes. A declared integration test may skip only when its external service is unavailable.

**Stop:** do not continue if a test fails or skips because a required symbol is missing.

**Debug:** rerun the same pytest target with `-vv --tb=long`, then fix the first failing contract before continuing.

### M6.2 — Complete checkpoint

Run the checkpoint:

```bash
uv run pytest tests/test_doc_sync.py tests/test_doc_parity.py -q
```

**Expected:** every selected offline test passes. A declared integration test may skip only when its external service is unavailable.

**Stop:** do not continue if a test fails or skips because a required symbol is missing.

**Debug:** rerun the same pytest target with `-vv --tb=long`, then fix the first failing contract before continuing.

### M6.3 — Complete checkpoint

Run the checkpoint:

```bash
uv run pytest tests/demo tests/api/test_08_integration.py -q
```

**Expected:** every selected offline test passes. A declared integration test may skip only when its external service is unavailable.

**Stop:** do not continue if a test fails or skips because a required symbol is missing.

**Debug:** rerun the same pytest target with `-vv --tb=long`, then fix the first failing contract before continuing.

<!-- complete-files:end -->
