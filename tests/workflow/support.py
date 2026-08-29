"""Shared builders and constants for the workflow test area."""

from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from app.llm.schemas import ProviderBudget, ProviderMetadata, ProviderResult, TokenPricing
from app.observability.types import RunReport
from app.retrieval.types import ChunkHit

SOURCE_SHA256 = "a" * 64
CONTEXT_HEADER = "ACME FY2024 · Item 7"


def hit(chunk_id=1, *, body=None, doc_id="ACME-FY2024", score=1.0):
    """Build one retrieved chunk hit with optional replacements.

    Distinct chunks carry distinct text unless a case asks for a twin, so the default
    fixture is not silently collapsed by evidence text deduplication.
    """
    body = f"Revenue increased in period {chunk_id}." if body is None else body
    return ChunkHit(
        chunk_id=chunk_id,
        doc_id=doc_id,
        item="7",
        kind="text",
        citation=CONTEXT_HEADER,
        start_char=chunk_id * 100,
        end_char=chunk_id * 100 + 80,
        source_sha256=SOURCE_SHA256,
        body=body,
        context_header=CONTEXT_HEADER,
        index_text=f"{CONTEXT_HEADER}\n\n{body}",
        score=score,
    )


def pricing(*, input_per_million="0.40", output_per_million="1.60"):
    """Build the token prices a workflow test charges against."""
    return TokenPricing(
        input_per_million_usd=Decimal(input_per_million),
        output_per_million_usd=Decimal(output_per_million),
    )


def provider_budget(
    *,
    max_input_tokens=1_000,
    max_output_tokens=100,
    max_cost_usd="1",
    token_pricing=None,
):
    """Build the provider budget the nodes spend from."""
    return ProviderBudget(
        max_input_tokens=max_input_tokens,
        max_output_tokens=max_output_tokens,
        max_cost_usd=Decimal(max_cost_usd),
        pricing=token_pricing or pricing(),
    )


def metadata(output="{}"):
    """Build provider metadata for one completed node call."""
    return ProviderMetadata(
        provider="deterministic",
        model_name="deterministic-mock",
        api_url="deterministic://local",
        input_tokens=10,
        output_tokens=5,
        estimated_cost_usd=Decimal("0"),
        request_time_ms=1.0,
        retries=0,
        request_ids=("req-1",),
        llm_output=output,
        raw_outputs=(output,),
    )


def ok_result(parsed):
    """Build a successful provider result carrying one output."""
    return ProviderResult(status="ok", parsed=parsed, refusal=None, metadata=metadata())


def report_of(result: RunReport) -> Any:
    """Return a finished run's report payload for untyped JSON assertions.

    ``RunReport.report`` is optional JSON, so asserting on it directly forces every
    test to re-narrow the same value. The status assertions around each call already
    establish that a payload is present.
    """
    assert result.report is not None
    return result.report


def retriever_returning(hits: Sequence[ChunkHit], *, expect_k: int = 15):
    """Build a retriever that asserts the over-fetched depth and returns the hits."""

    async def retrieve(query: str, k: int, filters) -> Sequence[ChunkHit]:
        """Return the canned hits for one workflow retrieval."""
        assert k == expect_k
        assert filters.doc_ids == ()
        return hits

    return retrieve
