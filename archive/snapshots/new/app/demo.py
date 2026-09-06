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
