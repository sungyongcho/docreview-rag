"""Secret-safe Gradio projection for canned and injected M5 demo services."""

from dataclasses import dataclass
import time
from typing import TYPE_CHECKING, Literal, Protocol

from pydantic import ValidationError

from app.api.errors import ApiProblemError
from app.api.schemas import RetrieveRequest, ReviewRequest, RunResponse
from app.observability.cost import UnknownModelPriceError, estimate_trace_cost_usd
from app.observability.persistence import redact_sensitive_text
from app.observability.types import RunReport
from app.retrieval.service import RetrievalResult
from app.retrieval.types import ChunkHit, RetrievalFilters
from app.workflow.types import EvidenceCitation

if TYPE_CHECKING:
    from gradio import Blocks as GradioBlocks
else:
    GradioBlocks = object

type RuntimeMode = Literal["query", "review"]
type DemoMode = Literal["canned", "query", "review"]

HERO_EXAMPLES = (
    "What revenue did Acme report in fiscal year 2024?",
    "What does the filing say about an acquisition?",
)

_CANNED_REVENUE_QUERIES = frozenset(
    {
        "revenue",
        "what revenue did acme report",
        "what revenue did acme report in fiscal year 2024",
    }
)


@dataclass(frozen=True)
class DemoEvidence:
    """Source identity and text exposed for one supported demo claim."""

    citation: str
    span: str
    source_sha256: str
    chunk_id: int
    body: str


@dataclass(frozen=True)
class DemoTrace:
    """Public execution summary that excludes credentials and raw provider output."""

    mode: DemoMode
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
    """Renderable answer with supported, unsupported, or unreviewed evidence state."""

    answer: str
    supported: bool | None
    evidence: tuple[DemoEvidence, ...]
    trace: DemoTrace

    def __post_init__(self) -> None:
        """Reject support labels that contradict the evidence collection."""
        if self.supported is True and not self.evidence:
            raise ValueError("supported results require evidence")
        if self.supported is False and self.evidence:
            raise ValueError("supported must match the presence of evidence")


class DemoService(Protocol):
    """Injectable service boundary for deterministic or live demo mode."""

    def run(self, query: str) -> DemoResult:
        """Return one renderable result without UI or network concerns."""
        ...


class M5Service(Protocol):
    """Minimal API seam required by the live adapter."""

    async def retrieve(self, request: RetrieveRequest) -> RetrievalResult:
        """Return ranked evidence for one strict retrieval request."""
        ...

    async def review(self, request: ReviewRequest) -> RunReport:
        """Return one secret-safe terminal workflow report."""
        ...


class CannedDemoService:
    """Exact offline fixtures that never generalize beyond declared questions."""

    def run(self, query: str) -> DemoResult:
        """Resolve a query against the fixed zero-cost demonstration cases.

        Parameters
        ----------
        query : str
            User text matched against the declared canned question set.

        Returns
        -------
        DemoResult
            Supported revenue evidence for an exact fixture or an unsupported result.

        Notes
        -----
        Broad keyword matching is forbidden because it can attach the Acme revenue
        answer to unrelated companies or questions.
        """
        normalized = " ".join(query.casefold().split()).rstrip("?.!")
        supported = normalized in _CANNED_REVENUE_QUERIES
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
    """Synchronous adapter that delegates only to an explicitly injected service."""

    def __init__(self, callback: DemoService) -> None:
        self._callback = callback

    def run(self, query: str) -> DemoResult:
        """Delegate one query without discovering credentials or other services."""
        return self._callback.run(query)


class RuntimeDemoService:
    """Project explicitly injected M5 operations without discovering credentials."""

    def __init__(self, services: M5Service) -> None:
        self._services = services

    async def run_async(
        self,
        query: str,
        *,
        mode: RuntimeMode = "query",
        k: int = 5,
        filters: RetrievalFilters | None = None,
    ) -> DemoResult:
        """Run retrieval or review mode and produce one fail-closed UI result.

        Parameters
        ----------
        query : str
            User question validated by the M5 request models.
        mode : RuntimeMode
            Retrieval-only projection or evidence-checked workflow review.
        k : int
            Positive retrieval limit passed to both M5 operations.
        filters : RetrievalFilters | None
            Optional filing filters shared by retrieval and review.

        Returns
        -------
        DemoResult
            Public result whose support state agrees with its displayed evidence.

        Raises
        ------
        ValueError
            If a runtime caller bypasses the declared mode type.

        Notes
        -----
        Review mode performs a separate retrieval to obtain evidence bodies because
        ``RunReport`` carries citation identity but not chunk text. Every cited identity
        must match that retrieval or the result is rejected as unsupported.
        """
        if mode not in ("query", "review"):
            raise ValueError("runtime mode must be 'query' or 'review'")
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
                return _review_result(report, retrieval, started=started)
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
                return DemoResult(answer, None, evidence, trace)
        except ValidationError:
            return DemoResult(
                answer="The request was invalid; no result was accepted.",
                supported=False,
                evidence=(),
                trace=DemoTrace(
                    mode=mode,
                    status="invalid_request",
                    model="none",
                    requests=0,
                    input_tokens=0,
                    output_tokens=0,
                    estimated_cost_usd="0.000000",
                    latency_ms=(time.perf_counter() - started) * 1000,
                    error="Query and evidence count must satisfy the request constraints.",
                ),
            )
        except ApiProblemError as error:
            return DemoResult(
                answer="The service is unavailable; no result was accepted.",
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
                    error=redact_sensitive_text(error.error.message),
                ),
            )


def _estimated_cost(report: RunReport) -> str:
    """Format a pinned trace estimate or expose that model pricing is unavailable."""
    try:
        return format(estimate_trace_cost_usd(report.steps), "f")
    except UnknownModelPriceError:
        return "unavailable"


def _report_trace(
    report: RunReport,
    *,
    started: float,
    status: str,
    error: str | None = None,
) -> DemoTrace:
    """Build a secret-safe review trace from one terminal report.

    Parameters
    ----------
    report : RunReport
        Terminal workflow report whose counters and steps determine the trace.
    started : float
        Monotonic start value used only for UI latency.
    status : str
        Public review status, including local evidence-mismatch failures.
    error : str | None
        Optional already-public failure description.

    Returns
    -------
    DemoTrace
        Review trace with a pinned cost estimate when the model is known.
    """
    return DemoTrace(
        mode="review",
        status=status,
        model=(redact_sensitive_text(report.steps[-1].model_name) if report.steps else "none"),
        requests=report.total_requests,
        input_tokens=report.total_input_tokens,
        output_tokens=report.total_output_tokens,
        estimated_cost_usd=_estimated_cost(report),
        latency_ms=(time.perf_counter() - started) * 1000,
        error=redact_sensitive_text(error) if error is not None else None,
    )


def _matching_evidence(
    retrieval: RetrievalResult,
    citations: tuple[EvidenceCitation, ...],
) -> tuple[DemoEvidence, ...] | None:
    """Match final citations to independently retrieved bodies by complete identity.

    Parameters
    ----------
    retrieval : RetrievalResult
        Ranked hits fetched for display before the review workflow.
    citations : tuple[EvidenceCitation, ...]
        Validated citations accepted by the terminal workflow report.

    Returns
    -------
    tuple[DemoEvidence, ...] | None
        Cited evidence in report order, or ``None`` when any identity differs.
    """
    hits_by_id = {hit.chunk_id: hit for hit in retrieval.hits}
    matched: list[DemoEvidence] = []
    for citation in citations:
        hit = hits_by_id.get(citation.chunk_id)
        if hit is None or (
            hit.doc_id != citation.doc_id
            or hit.citation != citation.citation
            or hit.start_char != citation.start_char
            or hit.end_char != citation.end_char
            or hit.source_sha256 != citation.source_sha256
        ):
            return None
        matched.append(_evidence(hit))
    return tuple(matched)


def _review_result(
    report: RunReport,
    retrieval: RetrievalResult,
    *,
    started: float,
) -> DemoResult:
    """Project a terminal review and reject malformed or mismatched support claims.

    Parameters
    ----------
    report : RunReport
        Internal terminal report returned by the injected M5 service.
    retrieval : RetrievalResult
        Separate retrieval used to supply evidence bodies to the UI.
    started : float
        Monotonic start value used for end-to-end demo latency.

    Returns
    -------
    DemoResult
        Supported output only when the final label and every evidence identity agree.
    """
    try:
        public_run = RunResponse.from_run_report(report)
    except TypeError, ValueError:
        return DemoResult(
            answer="The review response was invalid; no result was accepted.",
            supported=False,
            evidence=(),
            trace=_report_trace(
                report,
                started=started,
                status="invalid_response",
                error="The review response failed validation.",
            ),
        )

    if public_run.status != "ok" or public_run.report is None:
        failure_code = (
            public_run.failure.code if public_run.failure is not None else public_run.status
        )
        return DemoResult(
            answer="The review did not produce an accepted answer.",
            supported=False,
            evidence=(),
            trace=_report_trace(
                report,
                started=started,
                status=public_run.status,
                error=f"Review ended with {failure_code}.",
            ),
        )

    workflow_report = public_run.report
    if workflow_report.label == "NOT_IN_DOCS":
        return DemoResult(
            answer=workflow_report.answer,
            supported=False,
            evidence=(),
            trace=_report_trace(report, started=started, status=public_run.status),
        )

    matched = _matching_evidence(retrieval, workflow_report.citations)
    if not matched:
        return DemoResult(
            answer="The reviewed evidence could not be matched; no result was accepted.",
            supported=False,
            evidence=(),
            trace=_report_trace(
                report,
                started=started,
                status="evidence_mismatch",
                error="Cited evidence did not match the retrieved source identity.",
            ),
        )
    return DemoResult(
        answer=workflow_report.answer,
        supported=True,
        evidence=matched,
        trace=_report_trace(report, started=started, status=public_run.status),
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
    """Convert one typed result into the four public Gradio output values.

    Parameters
    ----------
    result : DemoResult
        Validated answer, support, evidence, and trace state.

    Returns
    -------
    tuple[str, str, str, list[dict[str, object]]]
        Answer text, support label, trace text, and evidence-card dictionaries.

    Notes
    -----
    Answer and trace strings are redacted again at the final presentation boundary.
    Evidence bodies remain source-exact so their spans and hashes stay auditable.
    """
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
        f"mode={result.trace.mode} | status={redact_sensitive_text(result.trace.status)} | "
        f"model={redact_sensitive_text(result.trace.model)}\n"
        f"requests={result.trace.requests} | input_tokens={result.trace.input_tokens} | "
        f"output_tokens={result.trace.output_tokens} | "
        f"estimated_cost_usd={result.trace.estimated_cost_usd} | "
        f"latency_ms={result.trace.latency_ms:.2f}"
    )
    if result.trace.error:
        trace += f"\nerror={redact_sensitive_text(result.trace.error)}"
    trace = redact_sensitive_text(trace)
    if result.supported is True:
        support = "Supported by the supplied documents."
    elif result.supported is False:
        support = "Not in the supplied documents."
    elif result.evidence:
        support = "Retrieved evidence candidates; support was not reviewed."
    else:
        support = "No evidence was retrieved; support was not reviewed."
    return redact_sensitive_text(result.answer), support, trace, evidence


def build_demo(
    service: DemoService | RuntimeDemoService | None = None,
    *,
    release_notice: str | None = None,
) -> GradioBlocks:
    """Build the UI without launching a server or retaining provider secrets.

    Parameters
    ----------
    service : DemoService | RuntimeDemoService | None
        Explicit synchronous fixture or asynchronous M5 adapter. The canned fixture
        is used when omitted.
    release_notice : str | None
        Optional deployment label shown above the controls.

    Returns
    -------
    Blocks
        Constructed Gradio application with one public submit event.

    Raises
    ------
    RuntimeError
        If the optional Gradio dependency is unavailable or incomplete.

    Notes
    -----
    Construction performs no provider or database work. The module entry point binds
    only to loopback and disables Gradio sharing explicitly.
    """
    try:
        from gradio import (
            JSON,
            Blocks,
            Button,
            Examples,
            Markdown,
            Radio,
            Slider,
            Textbox,
        )
    except ImportError as error:
        raise RuntimeError(
            "Install the optional 'demo' dependency to launch the Gradio UI."
        ) from error

    selected_service = service or CannedDemoService()
    if isinstance(selected_service, RuntimeDemoService):
        default_notice = (
            "Deployment mode: local runtime; provider access depends on server configuration."
        )
        modes = ["query", "review"]
    elif isinstance(selected_service, CannedDemoService):
        default_notice = "Deployment mode: canned fixture; provider requests and cost are zero."
        modes = ["canned"]
    else:
        default_notice = "Deployment mode: injected service; verify its provenance and cost."
        modes = ["injected"]
    selected_notice = redact_sensitive_text(release_notice or default_notice)

    async def submit(
        query: str,
        mode: str,
        k: int,
    ) -> tuple[str, str, str, list[dict[str, object]]]:
        """Run the selected backend for one validated UI event."""
        if isinstance(selected_service, RuntimeDemoService):
            if mode not in ("query", "review"):
                raise ValueError("runtime mode must be 'query' or 'review'")
            result = await selected_service.run_async(query, mode=mode, k=k)
        else:
            if mode != modes[0]:
                raise ValueError(f"mode must be {modes[0]!r}")
            result = selected_service.run(query)
        return render_result(result)

    with Blocks(title="Document Review Evidence Demo") as demo:
        Markdown(
            "# Document Review Evidence Demo\n"
            "Explore cited answers without exposing provider secrets.\n\n"
            f"**{selected_notice}**"
        )
        query = Textbox(label="Ask about the filing", value=HERO_EXAMPLES[0])
        Examples(examples=[[example] for example in HERO_EXAMPLES], inputs=query)
        mode = Radio(modes, value=modes[0], label="Mode")
        k = Slider(1, 10, value=5, step=1, label="Evidence count")
        run = Button("Review evidence", variant="primary")
        answer = Markdown(label="Answer")
        support = Markdown(label="Evidence boundary")
        trace = Markdown(label="Trace and cost transparency")
        evidence = JSON(label="Evidence cards")
        run.click(submit, inputs=[query, mode, k], outputs=[answer, support, trace, evidence])
    return demo


if __name__ == "__main__":
    build_demo().launch(server_name="127.0.0.1", share=False)
