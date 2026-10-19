"""Recorded output of an evaluation retrieval strategy."""

from collections.abc import Mapping
from dataclasses import dataclass, field

from app.retrieval.types import ChunkHit


@dataclass(frozen=True, slots=True)
class Decomposition:
    """Actual sub-questions and any provider failure that caused single-query degradation."""

    sub_questions: tuple[str, ...]
    fallback_status: str | None


@dataclass(frozen=True, slots=True)
class EvaluationRetrieval:
    """Hits and optional measured decomposition from the same evaluation request.

    ``cell_spans`` holds the source cell spans of each table hit's fragment by chunk
    id; scoring requires them for every table hit it ranks.
    """

    hits: tuple[ChunkHit, ...]
    decomposition: Decomposition | None = None
    cell_spans: Mapping[int, tuple[tuple[int, int], ...]] = field(default_factory=dict)
