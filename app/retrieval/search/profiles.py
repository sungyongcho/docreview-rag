"""Bounded retrieval settings shared by evaluations and interactive requests."""

from collections.abc import Mapping, Sequence
from typing import Annotated, Final, Literal, NamedTuple, Self

from pydantic import BaseModel, Field, StrictBool, StrictFloat, StrictInt, model_validator

from app.config import DEFAULT_BM25_B, DEFAULT_BM25_IDF, DEFAULT_BM25_K1, BM25Idf, LexicalRanker
from app.contracts.validation import StrictSchema
from app.retrieval.ranking.fusion import DEFAULT_RRF_K
from app.retrieval.search.plan import RetrievalStrategy

type RerankerName = Literal["cross_encoder"]


class RetrievalProfile(StrictSchema):
    """One explicit bounded retrieval plan used only by the Custom preset."""

    strategy: RetrievalStrategy = "hybrid"
    k: Annotated[StrictInt, Field(gt=0, le=100)] = 5
    candidate_k: Annotated[StrictInt, Field(gt=0, le=500)] = 20
    rrf_k: Annotated[StrictInt, Field(gt=0, le=10_000)] = DEFAULT_RRF_K
    lexical_ranker: LexicalRanker | None = "ts_rank_cd"
    # An omitted BM25 value resolves through the server settings; see with_server_bm25.
    bm25_k1: Annotated[StrictFloat, Field(gt=0, allow_inf_nan=False)] = DEFAULT_BM25_K1
    bm25_b: Annotated[StrictFloat, Field(ge=0, le=1, allow_inf_nan=False)] = DEFAULT_BM25_B
    bm25_idf: BM25Idf = DEFAULT_BM25_IDF
    route_by_language: StrictBool = False
    reranker: RerankerName | None = None

    @model_validator(mode="after")
    def validate_plan(self) -> Self:
        """Reject contradictory strategy, lexical, routing, and depth settings."""
        if self.candidate_k < self.k:
            raise ValueError("candidate_k must be at least k")
        if self.strategy == "vector" and self.lexical_ranker is not None:
            raise ValueError("vector strategy must not name a lexical ranker")
        if self.strategy != "vector" and self.lexical_ranker is None:
            raise ValueError("lexical and hybrid strategies require a lexical ranker")
        if self.route_by_language and self.strategy != "hybrid":
            raise ValueError("language routing requires the hybrid strategy")
        if self.reranker is not None and self.strategy != "hybrid":
            raise ValueError("reranking requires the hybrid strategy")
        return self


class ServerBM25(NamedTuple):
    """Server BM25 settings for every value a retrieval plan does not state."""

    k1: float = DEFAULT_BM25_K1
    b: float = DEFAULT_BM25_B
    idf: BM25Idf = DEFAULT_BM25_IDF


_BUILTIN_BM25: Final[Mapping[str, object]] = {
    "bm25_k1": DEFAULT_BM25_K1,
    "bm25_b": DEFAULT_BM25_B,
    "bm25_idf": DEFAULT_BM25_IDF,
}
# The BM25 fields every retrieval plan carries, in their declaration order.
_BM25_FIELDS: Final = tuple(_BUILTIN_BM25)


def _inherit_server_bm25[P: BaseModel](
    retrieval: P, server: ServerBM25 | None, names: Sequence[str]
) -> P:
    """Replace the named BM25 fields of a retrieval plan with the server settings."""
    configured = server or ServerBM25()
    values = {
        "bm25_k1": float(configured.k1),
        "bm25_b": float(configured.b),
        "bm25_idf": configured.idf,
    }
    inherited = {name: values[name] for name in names}
    if not inherited:
        return retrieval
    return type(retrieval).model_validate({**retrieval.model_dump(), **inherited})


def with_server_bm25[P: BaseModel](retrieval: P, server: ServerBM25 | None = None) -> P:
    """Fill the BM25 values a retrieval plan does not state from the server settings.

    Parameters
    ----------
    retrieval : P
        A Custom, stored, or administrator retrieval plan with ``bm25_*`` fields.
    server : ServerBM25 | None
        The configured server values; ``None`` means the built-in defaults.

    Returns
    -------
    P
        The plan with the BM25 values a request selecting it actually uses.

    Notes
    -----
    A request or file states a value by supplying it, and a stated value wins. A
    shipped built-in preset goes through ``with_server_bm25_for_builtin`` instead.
    """
    unstated = [name for name in _BM25_FIELDS if name not in retrieval.model_fields_set]
    return _inherit_server_bm25(retrieval, server, unstated)


def with_server_bm25_for_builtin[P: BaseModel](retrieval: P, server: ServerBM25 | None = None) -> P:
    """Fill the BM25 values a shipped built-in preset does not tune from the server settings.

    Parameters and result follow ``with_server_bm25``. A built-in preset that repeats a
    built-in default carries no deliberate tuning, so that value inherits the server
    setting like an unstated one; a different built-in value is kept.
    """
    untuned = [
        name
        for name, default in _BUILTIN_BM25.items()
        if name not in retrieval.model_fields_set or getattr(retrieval, name) == default
    ]
    return _inherit_server_bm25(retrieval, server, untuned)
