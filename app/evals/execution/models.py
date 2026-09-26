"""Recorded output of an evaluation retrieval strategy."""

from dataclasses import dataclass

from app.retrieval.types import ChunkHit


@dataclass(frozen=True, slots=True)
class Decomposition:
    """Actual sub-questions and any provider failure that caused single-query degradation."""

    sub_questions: tuple[str, ...]
    fallback_status: str | None


@dataclass(frozen=True, slots=True)
class EvaluationRetrieval:
    """Hits and optional measured decomposition from the same evaluation request."""

    hits: tuple[ChunkHit, ...]
    decomposition: Decomposition | None = None
