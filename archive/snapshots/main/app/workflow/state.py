from typing import TypedDict

from app.llm.schemas import ClaimReport
from app.retrieval.types import ChunkHit


class ReviewState(TypedDict):
    claim: str
    query: str
    evidence: list[ChunkHit]
    graded_sufficient: bool | None
    report: ClaimReport | None
    error: str | None
    retries: int
    retrieve_attempts: int
