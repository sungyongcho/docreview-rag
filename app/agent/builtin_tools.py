"""Built-in filing tools: typed wrappers over the M2 retrieval surface."""

from typing import TYPE_CHECKING, Annotated, Any, Protocol

from pydantic import BaseModel, ConfigDict, Field
from pydantic.functional_validators import field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.registry import ToolRegistry
from app.agent.tools import Tool
from app.agent.types import AgentCitation

if TYPE_CHECKING:
    from app.retrieval.embeddings import EmbeddingProvider
    from app.retrieval.service import RetrievalResult
    from app.retrieval.types import ChunkHit, RetrievalFilters
else:
    EmbeddingProvider = object
    ChunkHit = object
    RetrievalFilters = object

DEFAULT_RRF_K = 60


class _RetrievalResult(Protocol):
    """Materialized retrieval result required by the built-in tools."""

    @property
    def hits(self) -> tuple[ChunkHit, ...]:
        """Return immutable ranked hits."""
        ...


async def retrieve(
    session: AsyncSession,
    query: str,
    *,
    provider: EmbeddingProvider | None = None,
    k: int = 5,
    candidate_k: int | None = None,
    filters: RetrievalFilters | None = None,
    rrf_k: int = DEFAULT_RRF_K,
) -> _RetrievalResult:
    """Load the production retrieval service only when a tool actually runs."""
    from app.retrieval.service import retrieve as retrieve_service

    result: RetrievalResult = await retrieve_service(
        session,
        query,
        provider=provider,
        k=k,
        candidate_k=candidate_k,
        filters=filters,
        rrf_k=rrf_k,
    )
    return result


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
    """Materialize one hit as a JSON payload carrying its complete source identity."""
    return {
        "chunk_id": hit.chunk_id,
        "doc_id": hit.doc_id,
        "citation": hit.citation,
        "start_char": hit.start_char,
        "end_char": hit.end_char,
        "source_sha256": hit.source_sha256,
        "score": hit.score,
        "snippet": hit.index_text[:SNIPPET_CHARS],
    }


def _citation(payload: dict[str, Any]) -> AgentCitation:
    """Project one tool payload onto the immutable citation contract."""
    return AgentCitation(
        chunk_id=payload["chunk_id"],
        doc_id=payload["doc_id"],
        citation=payload["citation"],
        start_char=payload["start_char"],
        end_char=payload["end_char"],
        source_sha256=payload["source_sha256"],
    )


def _search_evidence(output: dict[str, Any]) -> tuple[AgentCitation, ...]:
    """Return the citation identity of every search hit."""
    return tuple(_citation(hit) for hit in output["hits"])


def _compare_evidence(output: dict[str, Any]) -> tuple[AgentCitation, ...]:
    """Return the citation identity of every hit across all compared years."""
    return tuple(_citation(hit) for year in output["years"] for hit in year["hits"])


def _chunk_evidence(output: dict[str, Any]) -> tuple[AgentCitation, ...]:
    """Return the citation identity of the single fetched chunk."""
    return (_citation(output),)


def build_default_registry(
    session: AsyncSession,
    *,
    embedding_provider: EmbeddingProvider | None = None,
    candidate_k: int | None = None,
    rrf_k: int = DEFAULT_RRF_K,
) -> ToolRegistry:
    """Register the built-in filing tools over one caller-owned session.

    Parameters
    ----------
    session : AsyncSession
        Caller-owned session reused only for short, sequential read transactions.
    embedding_provider : EmbeddingProvider | None
        Optional explicit query embedding provider.
    candidate_k : int | None
        Optional shared candidate depth for retrieval tools.
    rrf_k : int
        Positive reciprocal-rank-fusion constant.

    Returns
    -------
    ToolRegistry
        Three typed filing tools with complete evidence identity extractors.

    Notes
    -----
    Retrieval semantics remain in M2. Each tool materializes its payload and rolls
    back the read transaction before returning control to a later provider turn.
    """
    from app.retrieval.types import RetrievalFilters as RetrievalFiltersModel

    async def close_read_transaction() -> None:
        """Release a read transaction before control returns to the provider loop."""
        if session.in_transaction():
            await session.rollback()

    async def search_filings(params: SearchFilingsParams) -> dict[str, Any]:
        """Hybrid-search the corpus and materialize citable hits before releasing the read."""
        try:
            result = await retrieve(
                session,
                params.query,
                provider=embedding_provider,
                k=params.k or DEFAULT_SEARCH_K,
                candidate_k=candidate_k,
                filters=RetrievalFiltersModel(
                    tickers=params.tickers or (),
                    fiscal_years=params.fiscal_years or (),
                    forms=params.forms or (),
                ),
                rrf_k=rrf_k,
            )
            return {"hits": [_hit_payload(hit) for hit in result.hits]}
        finally:
            await close_read_transaction()

    async def fetch_chunk(params: FetchChunkParams) -> dict[str, Any]:
        """Read one stored chunk in full, rejecting ids the corpus does not contain."""
        from app.db.models import Chunk

        try:
            chunk = await session.get(Chunk, params.chunk_id)
            if chunk is None:
                raise ValueError(f"chunk {params.chunk_id} does not exist")
            return {
                "chunk_id": chunk.id,
                "doc_id": chunk.doc_id,
                "citation": chunk.citation,
                "start_char": chunk.start_char,
                "end_char": chunk.end_char,
                "source_sha256": chunk.source_sha256,
                "context_header": chunk.context_header,
                "body": chunk.body[:BODY_CHARS],
            }
        finally:
            await close_read_transaction()

    async def compare_years(params: CompareYearsParams) -> dict[str, Any]:
        """Retrieve the same question per sorted fiscal year, releasing each read in turn."""
        years: list[dict[str, Any]] = []
        for fiscal_year in sorted(params.fiscal_years):
            try:
                result = await retrieve(
                    session,
                    params.query,
                    provider=embedding_provider,
                    k=params.k or 3,
                    candidate_k=candidate_k,
                    filters=RetrievalFiltersModel(
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
            finally:
                await close_read_transaction()
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
