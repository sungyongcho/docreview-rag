"""Deterministic tests for the portfolio demo boundary."""

import asyncio
import builtins
from dataclasses import replace
from typing import cast

from gradio.data_classes import JsonData
import pytest

from app.api.errors import ApiProblemError
from app.api.schemas import RetrieveRequest, ReviewRequest
from app.demo import (
    CannedDemoService,
    DemoResult,
    DemoTrace,
    LiveDemoService,
    RuntimeDemoService,
    RuntimeMode,
    build_demo,
    render_result,
)
from app.observability.cost import estimate_cost_usd
from app.observability.types import JsonObject, RunReport, RunStatus, StepTrace, WorkflowNode
from app.retrieval.service import ComponentRankings, RetrievalResult
from app.retrieval.types import ChunkHit, RetrievalFilters


def _hit() -> ChunkHit:
    """Build one retrieval hit with complete source identity."""
    return ChunkHit(
        chunk_id=7,
        doc_id="acme-2024",
        item="8",
        kind="text",
        citation="Acme 10-K (2024), Item 8",
        start_char=10,
        end_char=30,
        source_sha256="b" * 64,
        body="Revenue was $12.4 million.",
        context_header="Acme",
        index_text="Acme\n\nRevenue was $12.4 million.",
        score=0.9,
    )


def _retrieval(hit: ChunkHit | None = None) -> RetrievalResult:
    """Build one retrieval result carrying the given hit, or none."""
    hits = (hit,) if hit is not None else ()
    return RetrievalResult(
        hits=hits,
        score_stage="rrf",
        component_rankings=ComponentRankings(
            vector=tuple(item.chunk_id for item in hits),
            lexical=(),
        ),
    )


def _run_report(
    payload: JsonObject,
    *,
    status: RunStatus = "ok",
    steps: tuple[StepTrace, ...] = (),
) -> RunReport:
    """Build one run report around the given payload and traces."""
    node_path = cast(tuple[WorkflowNode, ...], tuple(step.node for step in steps))
    return RunReport(
        run_id="demo-run",
        status=status,
        iterations=len(node_path),
        total_requests=sum(1 + step.retries for step in steps),
        total_input_tokens=sum(step.input_tokens for step in steps),
        total_output_tokens=sum(step.output_tokens for step in steps),
        total_time_seconds=0.1,
        system_prompt="Use only retrieved evidence.",
        node_path=node_path,
        report=payload,
        steps=steps,
    )


def _supported_payload(hit: ChunkHit) -> JsonObject:
    """Build a supported workflow payload citing the given hit."""
    return {
        "label": "SUPPORTED",
        "answer": "Acme reported $12.4 million in revenue.",
        "citations": [
            {
                "chunk_id": hit.chunk_id,
                "doc_id": hit.doc_id,
                "citation": hit.citation,
                "start_char": hit.start_char,
                "end_char": hit.end_char,
                "source_sha256": hit.source_sha256,
            }
        ],
        "rationale": "The cited filing text states the amount.",
        "reasons": [],
    }


def _not_in_docs_payload() -> JsonObject:
    """Build an absent workflow payload that cites nothing."""
    return {
        "label": "NOT_IN_DOCS",
        "answer": "NOT_IN_DOCS",
        "citations": [],
        "rationale": "The supplied evidence does not answer the question.",
        "reasons": [],
    }


def test_canned_mode_exposes_supported_evidence_and_zero_cost() -> None:
    """Show the canned answer as supported, with its citation and no cost."""
    result = CannedDemoService().run("What revenue did Acme report?")

    answer, support, trace, evidence = render_result(result)

    assert result.supported is True
    assert "Supported" in answer
    assert "supplied documents" in support
    assert "estimated_cost_usd=0.000000" in trace
    assert evidence[0]["citation"] == "Acme 10-K (2024), Item 8, p. 42"
    assert evidence[0]["span"] == "chars 1204-1297"
    assert evidence[0]["chunk_id"] == 42


@pytest.mark.parametrize(
    "query",
    [
        "What is Acme's CEO favorite color?",
        "What revenue did Globex report in 1999?",
    ],
)
def test_canned_mode_contrasts_not_in_documents_without_fake_evidence(query: str) -> None:
    """Answer an unanswerable question as absent, inventing no evidence."""
    result = CannedDemoService().run(query)

    _, support, trace, evidence = render_result(result)

    assert result.supported is False
    assert "Not in" in support
    assert "retrieval_empty" in trace
    assert evidence == []


def test_live_service_is_injectable_and_rendering_has_no_secret_fields() -> None:
    """Take the service by injection, and redact every secret before rendering."""
    injected = CannedDemoService()
    result = LiveDemoService(injected).run("revenue")
    leaked = replace(
        result.trace,
        model="api_key=sk-test-secret-123456",
        estimated_cost_usd="api_key=sk-cost-secret-123456",
        error="send Bearer abc.def-123 now",
    )
    rendered = render_result(
        DemoResult(
            "answer api_key=sk-test-secret-123456",
            result.supported,
            result.evidence,
            leaked,
        )
    )

    assert "sk-test-secret-123456" not in str(rendered)
    assert "sk-cost-secret-123456" not in str(rendered)
    assert "abc.def-123" not in str(rendered)
    assert "[REDACTED]" in str(rendered)
    assert rendered[2].startswith("mode=canned")


def test_demo_result_rejects_unexpected_service_shape() -> None:
    """Fail on a service that returns something other than a demo result."""

    class BadService:
        """Service returning something that is not a demo result."""

        def run(self, query: str) -> DemoResult:
            """Return a value of the wrong shape."""
            return "not a result"  # type: ignore[return-value]

    with pytest.raises(AttributeError):
        render_result(BadService().run("query"))


def test_runtime_adapter_consumes_real_m5_retrieval_result_and_filters() -> None:
    """Pass the issuer filter through and read the served result's own shape."""
    hit = _hit()

    class FakeServices:
        """Services asserting the query path never reviews."""

        async def retrieve(self, request: RetrieveRequest) -> RetrievalResult:
            """Return the staged retrieval result."""
            assert request.filters.issuers == ("ACME",)
            result = _retrieval(hit)
            assert not hasattr(result, "results")
            return result

        async def review(self, request: ReviewRequest) -> RunReport:
            """Return the staged run report."""
            raise AssertionError("query mode must not call review")

    result = asyncio.run(
        RuntimeDemoService(FakeServices()).run_async(
            "revenue", filters=RetrievalFilters(issuers=("ACME",))
        )
    )

    assert result.evidence[0].chunk_id == 7
    assert result.trace.mode == "query"
    assert result.supported is None
    assert render_result(result)[1] == "Retrieved evidence candidates; support was not reviewed."


def test_runtime_adapter_fail_closed_error_is_typed_and_non_secret() -> None:
    """Report a refused provider by its code, with the credential redacted."""

    class RefusingServices:
        """Services refusing retrieval with a typed provider error."""

        async def retrieve(self, request: RetrieveRequest) -> RetrievalResult:
            """Return the staged retrieval result."""
            raise ApiProblemError(
                status_code=503,
                code="provider_unavailable",
                message="Provider refused Bearer abc.def-123.",
            )

        async def review(self, request: ReviewRequest) -> RunReport:
            """Return the staged run report."""
            raise AssertionError("review must not run after retrieval refusal")

    result = asyncio.run(RuntimeDemoService(RefusingServices()).run_async("revenue"))

    assert result.trace.status == "provider_unavailable"
    assert result.trace.error == "Provider refused Bearer [REDACTED]"
    assert "abc.def-123" not in str(render_result(result))


def test_runtime_review_uses_typed_answer_citations_and_cost() -> None:
    """Carry the reviewed citations and the cost the provider call reported."""
    hit = _hit()
    trace = StepTrace(
        step=1,
        node="check",
        model_name="gpt-4.1-mini",
        api_url="https://example.test/responses",
        input_tokens=10,
        output_tokens=5,
        estimated_cost_usd=estimate_cost_usd("gpt-4.1-mini", 10, 5),
        request_time_ms=1.0,
        llm_output="{}",
        retries=0,
    )

    class ReviewingServices:
        """Services returning one staged retrieval and review."""

        async def retrieve(self, request: RetrieveRequest) -> RetrievalResult:
            """Return the staged retrieval result."""
            return _retrieval(hit)

        async def review(self, request: ReviewRequest) -> RunReport:
            """Return the staged run report."""
            return _run_report(_supported_payload(hit), steps=(trace,))

    result = asyncio.run(
        RuntimeDemoService(ReviewingServices()).run_async("revenue", mode="review")
    )

    assert result.answer == "Acme reported $12.4 million in revenue."
    assert result.supported is True
    assert tuple(item.chunk_id for item in result.evidence) == (hit.chunk_id,)
    assert result.trace.status == "ok"
    assert result.trace.estimated_cost_usd == "0.000012"


def test_runtime_review_not_in_docs_discards_retrieval_candidates() -> None:
    """Drop the retrieved candidates when the review answers absent."""
    hit = _hit()

    class ReviewingServices:
        """Services returning one staged retrieval and review."""

        async def retrieve(self, request: RetrieveRequest) -> RetrievalResult:
            """Return the staged retrieval result."""
            return _retrieval(hit)

        async def review(self, request: ReviewRequest) -> RunReport:
            """Return the staged run report."""
            return _run_report(_not_in_docs_payload())

    result = asyncio.run(
        RuntimeDemoService(ReviewingServices()).run_async("favorite color", mode="review")
    )

    assert result.answer == "NOT_IN_DOCS"
    assert result.supported is False
    assert result.evidence == ()
    assert render_result(result)[1] == "Not in the supplied documents."


def test_runtime_review_rejects_mismatched_source_identity() -> None:
    """Refuse a citation whose source identity differs from what was retrieved."""
    hit = _hit()
    payload = _supported_payload(hit)
    citations = cast(list[dict[str, object]], payload["citations"])
    citations[0]["source_sha256"] = "c" * 64

    class ReviewingServices:
        """Services returning one staged retrieval and review."""

        async def retrieve(self, request: RetrieveRequest) -> RetrievalResult:
            """Return the staged retrieval result."""
            return _retrieval(hit)

        async def review(self, request: ReviewRequest) -> RunReport:
            """Return the staged run report."""
            return _run_report(payload)

    result = asyncio.run(
        RuntimeDemoService(ReviewingServices()).run_async("revenue", mode="review")
    )

    assert result.supported is False
    assert result.evidence == ()
    assert result.trace.status == "evidence_mismatch"


def test_runtime_review_failure_never_reuses_retrieval_as_support() -> None:
    """Keep retrieved candidates out of a failed review's evidence."""
    hit = _hit()
    failure: JsonObject = {
        "reason": {
            "code": "node_error",
            "node": "retrieve",
            "error_type": "RuntimeError",
            "message": "database unavailable",
        }
    }

    class ReviewingServices:
        """Services returning one staged retrieval and review."""

        async def retrieve(self, request: RetrieveRequest) -> RetrievalResult:
            """Return the staged retrieval result."""
            return _retrieval(hit)

        async def review(self, request: ReviewRequest) -> RunReport:
            """Return the staged run report."""
            return _run_report(failure, status="error")

    result = asyncio.run(
        RuntimeDemoService(ReviewingServices()).run_async("revenue", mode="review")
    )

    assert result.supported is False
    assert result.evidence == ()
    assert result.trace.status == "error"
    assert result.trace.error == "Review ended with node_error."


def test_runtime_mode_is_validated_at_the_ui_boundary() -> None:
    """Reject an unknown mode before either service is called."""

    class UnusedServices:
        """Services asserting neither call is reached."""

        async def retrieve(self, request: RetrieveRequest) -> RetrievalResult:
            """Return the staged retrieval result."""
            raise AssertionError("invalid mode must fail before retrieval")

        async def review(self, request: ReviewRequest) -> RunReport:
            """Return the staged run report."""
            raise AssertionError("invalid mode must fail before review")

    with pytest.raises(ValueError, match="runtime mode"):
        asyncio.run(
            RuntimeDemoService(UnusedServices()).run_async(
                "revenue",
                mode=cast(RuntimeMode, "canned"),
            )
        )


def test_runtime_invalid_request_returns_a_safe_ui_result() -> None:
    """Turn a rejected request into a safe result rather than an exception."""

    class UnusedServices:
        """Services asserting neither call is reached."""

        async def retrieve(self, request: RetrieveRequest) -> RetrievalResult:
            """Return the staged retrieval result."""
            raise AssertionError("invalid request must fail before retrieval")

        async def review(self, request: ReviewRequest) -> RunReport:
            """Return the staged run report."""
            raise AssertionError("invalid request must fail before review")

    result = asyncio.run(RuntimeDemoService(UnusedServices()).run_async(""))

    assert result.supported is False
    assert result.evidence == ()
    assert result.trace.status == "invalid_request"
    assert "request constraints" in (result.trace.error or "")


def test_demo_result_rejects_support_evidence_mismatch() -> None:
    """Refuse a result claiming support while carrying no evidence."""
    with pytest.raises(ValueError, match="supported"):
        DemoResult(
            answer="unsupported",
            supported=True,
            evidence=(),
            trace=DemoTrace(
                mode="canned",
                status="retrieval_empty",
                model="deterministic",
                requests=0,
                input_tokens=0,
                output_tokens=0,
                estimated_cost_usd="0.000000",
            ),
        )


def test_build_demo_executes_the_canned_gradio_callback_without_launching() -> None:
    """Run the interface callback without starting a server."""
    demo = build_demo()

    response = asyncio.run(
        demo.process_api(
            1,
            ["What revenue did Acme report?", "canned", 5],
            simple_format=True,
        )
    )

    assert demo.is_running is False
    assert response["data"][1] == "Supported by the supplied documents."
    evidence = response["data"][3]
    assert isinstance(evidence, JsonData)
    assert isinstance(evidence.root, list)
    first_card = evidence.root[0]
    assert isinstance(first_card, dict)
    assert first_card["chunk_id"] == 42


def test_build_demo_maps_missing_optional_dependency(monkeypatch: pytest.MonkeyPatch) -> None:
    """Name the missing optional dependency instead of failing obscurely."""
    import_module = builtins.__import__

    def block_gradio(
        name: str,
        globals: dict[str, object] | None = None,
        locals: dict[str, object] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> object:
        """Stand in for the import so the optional dependency looks absent."""
        if name == "gradio":
            raise ImportError("blocked for test")
        return import_module(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", block_gradio)

    with pytest.raises(RuntimeError, match="optional 'demo' dependency"):
        build_demo()


def test_build_demo_redacts_the_release_notice() -> None:
    """Keep a secret out of the notice the interface publishes."""
    demo = build_demo(release_notice="api_key=sk-release-secret-123456")
    config = demo.get_config_file()

    assert "sk-release-secret-123456" not in str(config)
    assert "[REDACTED]" in str(config)
