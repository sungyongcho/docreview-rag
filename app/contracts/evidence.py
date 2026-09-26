"""Source identity and answer invariants shared by review and tool execution."""

from collections.abc import Sequence
from typing import Annotated, Literal, Self

from pydantic import Field, StrictStr, model_validator

from app.contracts.validation import NonBlank, NonNegativeInt, PositiveInt, StrictSchema

SourceSha256 = Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]
AnswerLabel = Literal["SUPPORTED", "NOT_IN_DOCS"]


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


def validate_answer_citations(label: AnswerLabel, answer: str, chunk_ids: Sequence[int]) -> None:
    """Require unique evidence for support and no evidence for an absent answer."""
    if len(chunk_ids) != len(set(chunk_ids)):
        raise ValueError("citation chunk ids must be unique")
    if label == "SUPPORTED":
        if not chunk_ids:
            raise ValueError("SUPPORTED answers require at least one citation")
        if answer == "NOT_IN_DOCS":
            raise ValueError("SUPPORTED answers require a supported answer")
    else:
        if answer != "NOT_IN_DOCS":
            raise ValueError(
                'NOT_IN_DOCS answers must use exactly the string "NOT_IN_DOCS" as the answer'
            )
        if chunk_ids:
            raise ValueError("NOT_IN_DOCS answers must not carry citations")
