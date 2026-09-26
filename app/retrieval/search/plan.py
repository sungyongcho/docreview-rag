"""Validated search settings shared by interactive retrieval and evaluation arms."""

from typing import Annotated, Literal, Self

from pydantic import Field, StrictInt, model_validator

from app.config import DEFAULT_BM25_B, DEFAULT_BM25_IDF, DEFAULT_BM25_K1, BM25Idf, LexicalRanker
from app.contracts.validation import StrictSchema
from app.retrieval.search.bm25 import validate_bm25_parameters

type RetrievalStrategy = Literal["vector", "lexical", "hybrid"]


class SearchPlan(StrictSchema):
    """Resolved ranking choices, independent of one call's requested evidence depth."""

    strategy: RetrievalStrategy = "hybrid"
    candidate_k: Annotated[StrictInt, Field(gt=0)] | None = None
    rrf_k: Annotated[StrictInt, Field(gt=0)] = 60
    lexical_ranker: LexicalRanker | None = "ts_rank_cd"
    bm25_k1: float = DEFAULT_BM25_K1
    bm25_b: float = DEFAULT_BM25_B
    bm25_idf: BM25Idf = DEFAULT_BM25_IDF
    route_by_language: bool = False

    @model_validator(mode="after")
    def validate_ranking(self) -> Self:
        """Require the selected lexical lane and valid BM25 numeric parameters."""
        if self.strategy != "vector" and self.lexical_ranker is None:
            raise ValueError("lexical and hybrid strategies require a lexical ranker")
        validate_bm25_parameters(self.bm25_k1, self.bm25_b, self.bm25_idf, parameter_prefix="bm25_")
        return self

    def candidate_limit(self, k: int) -> int:
        """Resolve automatic overfetch without silently widening an explicit limit."""
        if isinstance(k, bool) or not isinstance(k, int) or k <= 0:
            raise ValueError("k must be a positive integer")
        limit = max(20, 4 * k) if self.candidate_k is None else self.candidate_k
        if limit < k:
            raise ValueError("candidate_k must be at least k")
        return limit
