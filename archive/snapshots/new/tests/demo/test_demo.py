"""Deterministic tests for the portfolio demo boundary."""

import asyncio
from dataclasses import replace

import pytest

from app.api.errors import ApiProblemError
from app.demo import (
    CannedDemoService,
    DemoResult,
    LiveDemoService,
    RuntimeDemoService,
    render_result,
)
from app.retrieval import ChunkHit, ComponentRankings, RetrievalFilters, RetrievalResult


def test_canned_mode_exposes_supported_evidence_and_zero_cost() -> None:
    result = CannedDemoService().run("What revenue did Acme report?")

    answer, support, trace, evidence = render_result(result)

    assert result.supported is True
    assert "Supported" in answer
    assert "supplied documents" in support
    assert "estimated_cost_usd=0.000000" in trace
    assert evidence[0]["citation"] == "Acme 10-K (2024), Item 8, p. 42"
    assert evidence[0]["span"] == "chars 1204-1297"
    assert evidence[0]["chunk_id"] == 42


def test_canned_mode_contrasts_not_in_documents_without_fake_evidence() -> None:
    result = CannedDemoService().run("What is the CEO's favorite color?")

    _, support, trace, evidence = render_result(result)

    assert result.supported is False
    assert "Not in" in support
    assert "retrieval_empty" in trace
    assert evidence == []


def test_live_service_is_injectable_and_rendering_has_no_secret_fields() -> None:
    injected = CannedDemoService()
    result = LiveDemoService(injected).run("revenue")
    leaked = replace(result.trace, model="local-injected-provider")
    rendered = render_result(DemoResult(result.answer, result.supported, result.evidence, leaked))

    assert "api_key" not in str(rendered).lower()
    assert "secret" not in str(rendered).lower()
    assert rendered[2].startswith("mode=canned")


def test_demo_result_rejects_unexpected_service_shape() -> None:
    class BadService:
        def run(self, query: str) -> DemoResult:
            return "not a result"  # type: ignore[return-value]

    with pytest.raises(AttributeError):
        render_result(BadService().run("query"))


def test_runtime_adapter_consumes_real_m5_retrieval_result_and_filters() -> None:
    hit = ChunkHit(
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

    class FakeServices:
        async def retrieve(self, request):
            assert request.filters.tickers == ("ACME",)
            result = RetrievalResult(
                hits=(hit,),
                component_rankings=ComponentRankings(vector=(hit.chunk_id,), lexical=()),
            )
            assert not hasattr(result, "results")
            return result

        async def review(self, request):
            raise AssertionError("query mode must not call review")

    result = asyncio.run(
        RuntimeDemoService(FakeServices()).run_async(
            "revenue", filters=RetrievalFilters(tickers=("ACME",))
        )
    )

    assert result.evidence[0].chunk_id == 7
    assert result.trace.mode == "query"


def test_runtime_adapter_fail_closed_error_is_typed_and_non_secret() -> None:
    class RefusingServices:
        async def retrieve(self, request):
            raise ApiProblemError(
                status_code=503, code="provider_unavailable", message="Provider unavailable."
            )

        async def review(self, request):
            raise AssertionError("review must not run after retrieval refusal")

    result = asyncio.run(RuntimeDemoService(RefusingServices()).run_async("revenue"))

    assert result.trace.status == "provider_unavailable"
    assert result.trace.error == "Provider unavailable."
    assert "secret" not in str(render_result(result)).lower()
