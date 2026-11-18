"""The final answers an agent proposes and the report the review makes of them.

The model finishes an agent run with ``final_answer``: either a written
:class:`AgentAnswer` or, in the cell-selecting mode, a :class:`CellSelectionAnswer`
that names table cells and no amount. The review (:mod:`app.review`) checks the
proposal and reports an :class:`AgentReportAnswer`, whose label only the review may
widen to a period mismatch or ``UNVERIFIED``.
"""

from typing import Annotated, Literal, Self

from pydantic import Field, StrictInt, StrictStr
from pydantic.functional_validators import model_validator

from app.contracts.evidence import (
    AnswerLabel,
    EvidenceCitation,
    ReportLabel,
    validate_answer_citations,
)
from app.contracts.validation import NonBlank, PositiveInt, StrictSchema


class AgentAnswer(StrictSchema):
    """The final supported or absent answer with verified source citations."""

    label: AnswerLabel
    answer: NonBlank
    citations: tuple[EvidenceCitation, ...]
    rationale: NonBlank

    @model_validator(mode="after")
    def validate_label_contract(self) -> Self:
        """Keep supported and absent answers mutually exclusive."""
        validate_answer_citations(
            self.label, self.answer, tuple(citation.chunk_id for citation in self.citations)
        )
        return self


class AgentReportAnswer(AgentAnswer):
    """The answer a run reports.

    Only the review, never the model, reports a period mismatch or withholds figures
    whose scale, currency or direction it cannot confirm (``UNVERIFIED``).
    """

    label: ReportLabel


CELL_CONTRACT_VERSION = "cell-v1"
MAX_CELL_SELECTIONS = 20

CellRef = Annotated[StrictStr, Field(pattern=r"^[1-9][0-9]*:r[0-9]+c[0-9]+$")]


class CellSelection(StrictSchema):
    """One table cell the model selects, with the item and fiscal year it claims for it."""

    cell_id: CellRef
    claimed_item: NonBlank
    claimed_fiscal_year: Annotated[StrictInt, Field(ge=1900, le=2100)]


class CellSelectionAnswer(StrictSchema):
    """A final answer that names table cells instead of writing amounts.

    ``reason`` says how the proposal answers: ``selected`` cells, ``cannot_resolve``
    when the retrieved chunks relate to the question but no single cell can be
    established, or ``not_found`` when the searched evidence holds no answer. The
    application checks the selection and writes the reported answer itself.
    """

    contract_version: Literal["cell-v1"]
    label: AnswerLabel
    reason: Literal["selected", "cannot_resolve", "not_found"]
    selections: Annotated[tuple[CellSelection, ...], Field(max_length=MAX_CELL_SELECTIONS)]
    unresolved_chunk_ids: Annotated[tuple[PositiveInt, ...], Field(max_length=MAX_CELL_SELECTIONS)]
