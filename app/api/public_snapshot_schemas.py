"""Bounded public views of immutable evaluation evidence."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.evals.types import GoldenSpan


class PublicGoldenCase(BaseModel):
    """Question and expected evidence without internal curation notes."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    question: str
    category: str
    facet: str
    tags: tuple[str, ...]
    answers: tuple[GoldenSpan, ...]
    expected_label: str
    reference_answer: str


class PublicSnapshotDataset(BaseModel):
    """One filtered page from the exact published golden version."""

    snapshot_id: int
    suite: str
    golden_sha256: str
    revision_id: int | None
    version: int | None
    total: int
    offset: int
    limit: int
    cases: tuple[PublicGoldenCase, ...]


class PublicEvaluationCase(BaseModel):
    """Recorded case metrics; no retrieval is performed when reading them."""

    case_id: str
    question: str
    latency_ms: float
    first_relevant_rank: int | None = None
    recall_at_k: float | None = None
    hit_at_k: float | None = None
    reciprocal_rank: float | None = None


class PublicSnapshotEvaluation(BaseModel):
    """One filtered page of a published evaluation's recorded evidence."""

    snapshot_id: int
    eval_result_id: int
    suite: str
    created_at: datetime
    config: dict[str, str | int | float | bool | None]
    metrics: dict[str, float]
    total: int
    offset: int
    limit: int
    cases: tuple[PublicEvaluationCase, ...]
