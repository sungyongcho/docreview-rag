"""Strict final-answer contracts the agents propose and the review reports."""

from pydantic import TypeAdapter, ValidationError
import pytest

from app.contracts.answers import AgentAnswer, CellRef
from app.contracts.evidence import EvidenceCitation
from app.retrieval.tables import cell_ref, cell_ref_chunk


def supported_answer(*, chunk_id=7):
    """Build one supported answer carrying a single citation."""
    return AgentAnswer(
        label="SUPPORTED",
        answer="Revenue increased by ten percent.",
        citations=(
            EvidenceCitation(
                chunk_id=chunk_id,
                doc_id="NVDA-FY2024",
                citation="NVDA FY2024 · Item 7",
                start_char=700,
                end_char=750,
                source_sha256="a" * 64,
            ),
        ),
        rationale="The cited chunk states the increase.",
    )


def test_answer_label_contract_mirrors_the_m4_rules():
    """Require citations for a supported answer and forbid them for an absent one."""
    supported_answer()
    AgentAnswer(
        label="NOT_IN_DOCS",
        answer="NOT_IN_DOCS",
        citations=(),
        rationale="The filings do not discuss this topic.",
    )

    with pytest.raises(ValidationError):
        AgentAnswer(
            label="SUPPORTED",
            answer="Revenue increased.",
            citations=(),
            rationale="No evidence attached.",
        )
    with pytest.raises(ValidationError):
        AgentAnswer(
            label="NOT_IN_DOCS",
            answer="NOT_IN_DOCS",
            citations=supported_answer().citations,
            rationale="Absent answers must not cite.",
        )


def test_a_selection_accepts_the_refs_the_catalog_builds():
    """Accept the ref the stored-cell catalog builds and read its chunk back."""
    ref = cell_ref(1, 0, 0)
    assert TypeAdapter(CellRef).validate_python(ref) == ref
    assert cell_ref_chunk(cell_ref(42, 3, 1)) == 42
