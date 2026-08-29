"""Inline golden-case and hit builders shared by the evaluation tests."""

from app.evals.types import GoldenCase, GoldenSpan
from app.retrieval.types import ChunkHit

SOURCE_SHA256 = "a" * 64


def positive_case(case_id: str = "m3c-01") -> GoldenCase:
    """Build a source-bearing case that :func:`relevant_hit` answers."""
    return GoldenCase(
        id=case_id,
        question="What evidence is supported?",
        category="simple_lookup",
        facet="factual",
        tags=("runner",),
        answers=(
            GoldenSpan(
                doc_id="NVDA-FY2024",
                source_sha256=SOURCE_SHA256,
                start_char=100,
                end_char=200,
            ),
        ),
        expected_label="SUPPORTED",
        reference_answer="Supported evidence.",
        note="Deterministic runner fixture.",
        curation_status="agent-curated",
        approval_status="pending-author-approval",
        human_verified=False,
    )


def absent_case(case_id: str = "m3c-02") -> GoldenCase:
    """Build an absent case that carries no answer span."""
    return GoldenCase(
        id=case_id,
        question="What evidence is absent?",
        category="absent",
        facet="risk",
        tags=("negative",),
        answers=(),
        expected_label="NOT_IN_DOCS",
        reference_answer="NOT_IN_DOCS",
        note="Retrieval-only metrics do not score absence.",
        curation_status="agent-curated",
        approval_status="pending-author-approval",
        human_verified=False,
    )


def relevant_hit() -> ChunkHit:
    """Build the hit that covers the positive case's gold span."""
    return ChunkHit(
        chunk_id=1,
        doc_id="NVDA-FY2024",
        item="7",
        kind="text",
        citation="NVDA FY2024 · Item 7",
        start_char=90,
        end_char=210,
        source_sha256=SOURCE_SHA256,
        body="Supported evidence.",
        context_header="NVDA FY2024 · Item 7",
        index_text="NVDA FY2024 · Item 7\n\nSupported evidence.",
        score=1.0,
    )
