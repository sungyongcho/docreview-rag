"""Built-in filing tools: typed wrappers over the M2 retrieval surface."""

from collections.abc import Callable, Sequence
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field
from pydantic.functional_validators import field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.registry import ToolRegistry
from app.agent.tools import Tool, ToolError
from app.agent.types import AgentCitation
from app.db.models import Chunk
from app.retrieval.embeddings import EmbeddingIdentity, EmbeddingProvider, get_embedding_provider
from app.retrieval.hybrid import DEFAULT_RRF_K
from app.retrieval.service import retrieve
from app.retrieval.types import ChunkHit, RetrievalFilters

type SessionFactory = Callable[[], AsyncSession]

DEFAULT_SEARCH_K = 5
MAX_SEARCH_K = 20
SNIPPET_CHARS = 320
BODY_CHARS = 4_000


class _QueryEmbeddingCache(EmbeddingProvider):
    """Embed each distinct query text once across one tool call's retrievals.

    ``compare_years`` runs the same question through retrieval once per fiscal
    year, and each retrieval embeds its query. Cached by exact text, the 2-4
    embedding round trips collapse to one while a translated or rewritten
    component query still embeds separately, so routing arms stay correct.
    """

    def __init__(self, inner: EmbeddingProvider) -> None:
        self.dimensions = inner.dimensions
        self._inner = inner
        self._vectors: dict[str, list[float]] = {}

    @property
    def identity(self) -> EmbeddingIdentity:
        """Retain the wrapped provider's exact vector configuration."""
        return self._inner.identity

    @property
    def max_input_tokens(self) -> int:
        """Retain the wrapped model's complete input limit."""
        return self._inner.max_input_tokens

    def count_input_tokens(self, text: str) -> int:
        """Count with the wrapped model's tokenizer without changing its input."""
        return self._inner.count_input_tokens(text)

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Delegate batch embedding unchanged; only queries repeat here."""
        return await self._inner.embed_documents(texts)

    async def embed_query(self, text: str) -> list[float]:
        """Embed one query, reusing the vector for a text seen before."""
        vector = self._vectors.get(text)
        if vector is None:
            vector = await self._inner.embed_query(text)
            self._vectors[text] = vector
        return vector


class ToolParams(BaseModel):
    """Closed base for tool parameters so unknown arguments always fail."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class SearchFilingsParams(ToolParams):
    """Arguments for one hybrid retrieval call.

    Optional fields default to ``None`` so tolerant surfaces (MCP clients) may
    omit them; the strict provider schema still requires every field because
    strict decoding strips defaults and marks all properties required.
    """

    query: Annotated[str, Field(min_length=1)]
    k: Annotated[int, Field(gt=0, le=MAX_SEARCH_K)] | None = None
    issuers: tuple[str, ...] | None = None
    fiscal_years: tuple[int, ...] | None = None
    forms: tuple[str, ...] | None = None


class FetchChunkParams(ToolParams):
    """Arguments for reading one retrieved chunk in full."""

    chunk_id: Annotated[int, Field(gt=0)]


class CompareYearsParams(ToolParams):
    """Arguments for retrieving the same question across fiscal years."""

    query: Annotated[str, Field(min_length=1)]
    issuer: Annotated[str, Field(min_length=1, max_length=32)]
    fiscal_years: tuple[int, ...]
    k: Annotated[int, Field(gt=0, le=10)] | None = None

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
    session_factory: SessionFactory,
    *,
    embedding_provider: EmbeddingProvider | None = None,
    candidate_k: int | None = None,
    rrf_k: int = DEFAULT_RRF_K,
    search_k: int = DEFAULT_SEARCH_K,
) -> ToolRegistry:
    """Register the built-in filing tools over a per-call session factory.

    Parameters
    ----------
    session_factory : SessionFactory
        Callable producing one fresh ``AsyncSession`` per tool invocation, e.g.
        the application ``async_sessionmaker``. Because every call owns its own
        session, concurrent tool calls (the MCP transport dispatches each request
        in its own task) cannot interleave reads on shared state.
    embedding_provider : EmbeddingProvider | None
        Optional explicit query embedding provider.
    candidate_k : int | None
        Optional shared candidate depth for retrieval tools.
    rrf_k : int
        Positive reciprocal-rank-fusion constant.
    search_k : int
        Hit count ``search_filings`` uses when the caller omits ``k``.

    Returns
    -------
    ToolRegistry
        Three typed filing tools with complete evidence identity extractors.

    Raises
    ------
    ValueError
        If ``search_k`` leaves the range the ``search_filings`` schema accepts.

    Notes
    -----
    Retrieval semantics remain in M2. Each tool opens its session on entry and the
    context exit rolls the read transaction back, so no read survives past the
    tool call that started it.
    """
    if not 0 < search_k <= MAX_SEARCH_K:
        raise ValueError(f"search_k must be between 1 and {MAX_SEARCH_K}")

    async def search_filings(params: SearchFilingsParams) -> dict[str, Any]:
        """Hybrid-search the corpus and materialize citable hits before releasing the read."""
        async with session_factory() as session:
            result = await retrieve(
                session,
                params.query,
                provider=embedding_provider,
                k=params.k or search_k,
                candidate_k=candidate_k,
                filters=RetrievalFilters(
                    issuers=params.issuers or (),
                    fiscal_years=params.fiscal_years or (),
                    forms=params.forms or (),
                ),
                rrf_k=rrf_k,
            )
            return {"hits": [_hit_payload(hit) for hit in result.hits]}

    async def fetch_chunk(params: FetchChunkParams) -> dict[str, Any]:
        """Read one stored chunk in full, rejecting ids the corpus does not contain."""
        async with session_factory() as session:
            chunk = await session.get(Chunk, params.chunk_id)
            if chunk is None:
                raise ToolError(f"chunk {params.chunk_id} does not exist")
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

    async def compare_years(params: CompareYearsParams) -> dict[str, Any]:
        """Retrieve the same question per sorted fiscal year over one short-lived session."""
        provider = _QueryEmbeddingCache(
            embedding_provider if embedding_provider is not None else get_embedding_provider()
        )
        async with session_factory() as session:
            years: list[dict[str, Any]] = []
            for fiscal_year in sorted(params.fiscal_years):
                result = await retrieve(
                    session,
                    params.query,
                    provider=provider,
                    k=params.k or 3,
                    candidate_k=candidate_k,
                    filters=RetrievalFilters(
                        issuers=(params.issuer,),
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
            return {"issuer": params.issuer, "years": years}

    registry = ToolRegistry()
    registry.register(
        Tool(
            name="search_filings",
            description=(
                "Hybrid-search the 10-K corpus and return scored, citable chunks. "
                "Optional issuers, fiscal_years, and forms narrow the corpus; "
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
                "Run the same question against one issuer across two to four "
                "fiscal years and return the evidence grouped by year."
            ),
            parameters=CompareYearsParams,
            run=compare_years,
            evidence_ids=_compare_evidence,
        )
    )
    return registry
