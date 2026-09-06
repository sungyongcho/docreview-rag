"""Strict, source-stable value objects for retrieval evaluation data."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr
from pydantic.functional_validators import field_validator, model_validator

GoldenCategory = Literal["simple_lookup", "exact_number", "multi_hop", "absent"]
GoldenFacet = Literal["factual", "comparison", "risk", "policy", "numeric"]
ExpectedLabel = Literal["SUPPORTED", "NOT_IN_DOCS"]
GoldenTag = Annotated[StrictStr, Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")]
SourceSha256 = Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]


class GoldenSpan(BaseModel):
    """One half-open answer span in an immutable raw filing snapshot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    doc_id: Annotated[StrictStr, Field(min_length=1, max_length=32)]
    source_sha256: SourceSha256
    start_char: Annotated[StrictInt, Field(ge=0)]
    end_char: Annotated[StrictInt, Field(gt=0)]

    @model_validator(mode="after")
    def validate_half_open_span(self) -> Self:
        """Reject empty or reversed source intervals."""
        if self.end_char <= self.start_char:
            raise ValueError("end_char must be greater than start_char")
        return self


class GoldenCase(BaseModel):
    """One reviewed-question candidate and its retrieval ground truth."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: Annotated[StrictStr, Field(pattern=r"^m3c-[0-9]{2}$")]
    question: Annotated[StrictStr, Field(min_length=1)]
    category: GoldenCategory
    facet: GoldenFacet
    tags: tuple[GoldenTag, ...]
    answers: tuple[GoldenSpan, ...]
    expected_label: ExpectedLabel
    reference_answer: Annotated[StrictStr, Field(min_length=1)]
    note: Annotated[StrictStr, Field(min_length=1)]
    curation_status: Literal["agent-curated"]
    approval_status: Literal["pending-author-approval"]
    human_verified: Literal[False]

    @field_validator("human_verified", mode="before")
    @classmethod
    def require_literal_false(cls, value: object) -> object:
        """Reject false-like values that could imply an ambiguous review status."""
        if value is not False:
            raise ValueError("human_verified must be the JSON boolean false")
        return value

    @field_validator("question", "reference_answer", "note", mode="after")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        """Reject strings that contain only whitespace."""
        if not value.strip():
            raise ValueError("text fields must not be blank")
        return value

    @field_validator("tags", mode="after")
    @classmethod
    def reject_duplicate_tags(cls, tags: tuple[str, ...]) -> tuple[str, ...]:
        """Keep tag membership unambiguous without silently rewriting input."""
        if len(tags) != len(set(tags)):
            raise ValueError("tags must be unique")
        return tags

    @model_validator(mode="after")
    def validate_label_and_answers(self) -> Self:
        """Keep positive and absent-case contracts mutually exclusive."""
        identities = {
            (answer.doc_id, answer.source_sha256, answer.start_char, answer.end_char)
            for answer in self.answers
        }
        if len(identities) != len(self.answers):
            raise ValueError("answer spans must be unique within a case")

        if self.category == "absent":
            if self.answers:
                raise ValueError("absent cases must not contain answer spans")
            if self.expected_label != "NOT_IN_DOCS":
                raise ValueError("absent cases must expect NOT_IN_DOCS")
            if self.reference_answer != "NOT_IN_DOCS":
                raise ValueError("absent cases must use the NOT_IN_DOCS reference answer")
        else:
            if not self.answers:
                raise ValueError("positive cases must contain at least one answer span")
            if self.expected_label != "SUPPORTED":
                raise ValueError("positive cases must expect SUPPORTED")
            if self.reference_answer == "NOT_IN_DOCS":
                raise ValueError("positive cases must include a supported reference answer")
        return self
