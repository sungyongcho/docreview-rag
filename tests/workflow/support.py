"""Shared builders and constants for the workflow test area."""

from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from app.llm.schemas import ProviderBudget, ProviderMetadata, ProviderResult, TokenPricing
from app.observability.types import RunReport
from app.retrieval.search.service import ComponentRankings, RetrievalResult
from app.retrieval.types import ChunkHit

SOURCE_SHA256 = "a" * 64
CONTEXT_HEADER = "ACME FY2024 · Item 7"


def hit(chunk_id=1, *, body=None, doc_id="ACME-FY2024"):
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
        score=1.0,
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


def metadata():
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
        requests=1,
        request_ids=("req-1",),
        llm_output="{}",
        raw_outputs=("{}",),
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


def retrieval_result(hits: Sequence[ChunkHit]) -> RetrievalResult:
    """Wrap canned hits in the retrieval envelope the workflow runner requires."""
    return RetrievalResult(
        hits=tuple(hits),
        candidates=tuple(hits),
        score_stage="rrf",
        component_rankings=ComponentRankings(vector=(), lexical=()),
    )


def retriever_returning(hits: Sequence[ChunkHit]):
    """Build a retriever that asserts the over-fetched depth and returns the hits."""

    async def retrieve(query: str, k: int, filters) -> RetrievalResult:
        """Return the canned hits for one workflow retrieval."""
        assert k == 15
        assert filters.doc_ids == ()
        return retrieval_result(hits)

    return retrieve


# AMD FY2024 consolidated statement of operations, as the filing lays it out.
INCOME_TABLE = (
    "<table><tr><td>(In millions)</td><td>December 28, 2024</td>"
    "<td>December 30, 2023</td></tr>"
    "<tr><td>Net revenue</td><td>$ 25,785</td><td>$ 22,680</td></tr></table>"
)


def income_table_hit(chunk_id=7) -> tuple[ChunkHit, dict[str, object]]:
    """Chunk the AMD income table through the real chunker as one retrieved table hit."""
    from dataclasses import asdict

    from app.ingestion.chunking import chunk_filing, compose_index_text
    from app.ingestion.parsing.models import Block
    from tests.ingestion.chunk.support import build_filing

    block = Block("table", "", html=INCOME_TABLE, source_pos=0, end_pos=len(INCOME_TABLE))
    filing = build_filing([block])
    filing.source_length = len(INCOME_TABLE)
    (chunk,) = chunk_filing(filing)
    assert chunk.table_fragment is not None
    table = ChunkHit(
        chunk_id=chunk_id,
        doc_id="AMD-FY2024",
        item="8",
        kind="table",
        citation="AMD FY2024 · Item 8",
        start_char=0,
        end_char=len(INCOME_TABLE),
        source_sha256=SOURCE_SHA256,
        body=chunk.body,
        context_header=chunk.context_header,
        index_text=compose_index_text(chunk.context_header, chunk.body),
        score=1.0,
    )
    return table, asdict(chunk.table_fragment)
