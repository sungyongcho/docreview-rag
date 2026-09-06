"""Built-in filing tools: typed wrappers over the M2 retrieval surface."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field
from pydantic.functional_validators import field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.registry import ToolRegistry
from app.agent.tools import Tool
from app.db.models import Chunk
from app.retrieval import DEFAULT_RRF_K, ChunkHit, EmbeddingProvider, RetrievalFilters, retrieve

DEFAULT_SEARCH_K = 5
SNIPPET_CHARS = 320
BODY_CHARS = 4_000


class ToolParams(BaseModel):
    """Closed base for tool parameters so unknown arguments always fail."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class SearchFilingsParams(ToolParams):
    """Arguments for one hybrid retrieval call."""

    query: Annotated[str, Field(min_length=1)]
    k: Annotated[int, Field(gt=0, le=20)] | None
    tickers: tuple[str, ...] | None
    fiscal_years: tuple[int, ...] | None
    forms: tuple[str, ...] | None


class FetchChunkParams(ToolParams):
    """Arguments for reading one retrieved chunk in full."""

    chunk_id: Annotated[int, Field(gt=0)]


class CompareYearsParams(ToolParams):
    """Arguments for retrieving the same question across fiscal years."""

    query: Annotated[str, Field(min_length=1)]
    ticker: Annotated[str, Field(min_length=1, max_length=16)]
    fiscal_years: tuple[int, ...]
    k: Annotated[int, Field(gt=0, le=10)] | None

    @field_validator("fiscal_years", mode="after")
    @classmethod
    def validate_years(cls, years: tuple[int, ...]) -> tuple[int, ...]:
        """Require a real comparison: two to four distinct years."""
        if not 2 <= len(years) <= 4:
            raise ValueError("fiscal_years must contain two to four years")
        if len(set(years)) != len(years):
            raise ValueError("fiscal_years must be unique")
        return years


def _hit_payload(hit: ChunkHit) -> dict[str, Any]:
    return {
        "chunk_id": hit.chunk_id,
        "doc_id": hit.doc_id,
        "citation": hit.citation,
        "score": hit.score,
        "snippet": hit.index_text[:SNIPPET_CHARS],
    }


def _search_evidence(output: dict[str, Any]) -> tuple[int, ...]:
    return tuple(hit["chunk_id"] for hit in output["hits"])


def _compare_evidence(output: dict[str, Any]) -> tuple[int, ...]:
    return tuple(hit["chunk_id"] for year in output["years"] for hit in year["hits"])


def _chunk_evidence(output: dict[str, Any]) -> tuple[int, ...]:
    return (output["chunk_id"],)


def build_default_registry(
    session: AsyncSession,
    *,
    embedding_provider: EmbeddingProvider | None = None,
    candidate_k: int | None = None,
    rrf_k: int = DEFAULT_RRF_K,
) -> ToolRegistry:
    """Register the built-in filing tools over one caller-owned session.

    Every tool is a thin typed wrapper: retrieval semantics stay in M2, and the
    tools only decide which arguments the model may vary and which payload
    fields become evidence.
    """

    async def search_filings(params: SearchFilingsParams) -> dict[str, Any]:
        result = await retrieve(
            session,
            params.query,
            provider=embedding_provider,
            k=params.k or DEFAULT_SEARCH_K,
            candidate_k=candidate_k,
            filters=RetrievalFilters(
                tickers=params.tickers or (),
                fiscal_years=params.fiscal_years or (),
                forms=params.forms or (),
            ),
            rrf_k=rrf_k,
        )
        return {"hits": [_hit_payload(hit) for hit in result.hits]}

    async def fetch_chunk(params: FetchChunkParams) -> dict[str, Any]:
        chunk = await session.get(Chunk, params.chunk_id)
        if chunk is None:
            raise ValueError(f"chunk {params.chunk_id} does not exist")
        return {
            "chunk_id": chunk.id,
            "doc_id": chunk.doc_id,
            "citation": chunk.citation,
            "context_header": chunk.context_header,
            "body": chunk.body[:BODY_CHARS],
        }

    async def compare_years(params: CompareYearsParams) -> dict[str, Any]:
        years: list[dict[str, Any]] = []
        for fiscal_year in sorted(params.fiscal_years):
            result = await retrieve(
                session,
                params.query,
                provider=embedding_provider,
                k=params.k or 3,
                candidate_k=candidate_k,
                filters=RetrievalFilters(
                    tickers=(params.ticker,),
                    fiscal_years=(fiscal_year,),
                ),
                rrf_k=rrf_k,
            )
            years.append(
                {
                    "fiscal_year": fiscal_year,
                    "hits": [_hit_payload(hit) for hit in result.hits],
                }
            )
        return {"ticker": params.ticker, "years": years}

    registry = ToolRegistry()
    registry.register(
        Tool(
            name="search_filings",
            description=(
                "Hybrid-search the 10-K corpus and return scored, citable chunks. "
                "Optional tickers, fiscal_years, and forms narrow the corpus; "
                "null means unrestricted."
            ),
            parameters=SearchFilingsParams,
            run=search_filings,
            evidence_ids=_search_evidence,
        )
    )
    registry.register(
        Tool(
            name="fetch_chunk",
            description="Read one previously retrieved chunk in full by its chunk_id.",
            parameters=FetchChunkParams,
            run=fetch_chunk,
            evidence_ids=_chunk_evidence,
        )
    )
    registry.register(
        Tool(
            name="compare_years",
            description=(
                "Run the same question against one ticker across two to four "
                "fiscal years and return the evidence grouped by year."
            ),
            parameters=CompareYearsParams,
            run=compare_years,
            evidence_ids=_compare_evidence,
        )
    )
    return registry
