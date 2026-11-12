"""Source identity and answer invariants shared by review and tool execution."""

from collections.abc import Sequence
from typing import Annotated, Literal, Self

from pydantic import Field, StrictStr, model_validator

from app.contracts.validation import NonBlank, NonNegativeInt, PositiveInt, StrictSchema

SourceSha256 = Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]
# What a model may answer. Only the server reports a period mismatch, after checking
# the answer's figures against the periods of the cells it cites, or UNVERIFIED, when
# the unit of the figures' cited evidence, or of the answer, cannot be established.
AnswerLabel = Literal["SUPPORTED", "NOT_IN_DOCS"]
ReportLabel = Literal["SUPPORTED", "NOT_IN_DOCS", "PERIOD_MISMATCH", "UNVERIFIED"]


class EvidenceCitation(StrictSchema):
    """Complete immutable identity of a nonempty interval in one source chunk."""

    chunk_id: PositiveInt
    doc_id: NonBlank
    citation: NonBlank
    start_char: NonNegativeInt
    end_char: PositiveInt
    source_sha256: SourceSha256

    @model_validator(mode="after")
    def validate_span(self) -> Self:
        """Require a nonempty half-open source interval."""
        if self.end_char <= self.start_char:
            raise ValueError("end_char must be greater than start_char")
        return self


HoldReason = Literal[
    "amendment_pending", "report_missing", "order_unknown", "not_indexed", "item_withheld"
]


class EvidenceHold(StrictSchema):
    """Evidence a search could not use for one issuer's report period, and why.

    A later filing of the period keeps it out of use: an amendment nobody has reviewed
    yet (``amendment_pending``), an amendment whose report is unknown
    (``report_missing``), filings that cannot be ordered (``order_unknown``), a newer
    report that is not indexed (``not_indexed``), or Items a review withheld
    (``item_withheld``). ``items`` names the withheld Items; an empty tuple means the
    whole report period.
    """

    registry: NonBlank
    issuer: NonBlank
    fiscal_year: PositiveInt
    reason: HoldReason
    items: tuple[NonBlank, ...] = ()


def validate_answer_citations(label: ReportLabel, answer: str, chunk_ids: Sequence[int]) -> None:
    """Require unique evidence for cited answers and no evidence for an absent answer."""
    if len(chunk_ids) != len(set(chunk_ids)):
        raise ValueError("citation chunk ids must be unique")
    if label != "NOT_IN_DOCS":
        if not chunk_ids:
            raise ValueError(f"{label} answers require at least one citation")
        if answer == "NOT_IN_DOCS":
            raise ValueError(f"{label} answers require a supported answer")
    else:
        if answer != "NOT_IN_DOCS":
            raise ValueError(
                'NOT_IN_DOCS answers must use exactly the string "NOT_IN_DOCS" as the answer'
            )
        if chunk_ids:
            raise ValueError("NOT_IN_DOCS answers must not carry citations")
