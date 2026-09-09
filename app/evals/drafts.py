"""Bounded authoring records kept separately from executable golden-case validation."""

from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    TypeAdapter,
    field_validator,
)

from app.evals.loader import GoldenDataError, validate_unique_cases
from app.evals.types import GoldenCase, GoldenCaseId, GoldenCategory, GoldenFacet, GoldenTag


class DraftFieldIssue(BaseModel):
    """An actionable field path without submitted values or internal validator text."""

    location: tuple[str | int, ...]
    code: str
    message: str


class DraftInputError(GoldenDataError):
    """Reject structurally invalid authoring input while preserving incomplete drafts."""

    def __init__(self, issues: tuple[DraftFieldIssue, ...]) -> None:
        self.issues = issues
        super().__init__("Check the indicated question fields.")


class DraftConflictError(GoldenDataError):
    """A file changed since the editor loaded its expected content hash."""


class DraftSpan(BaseModel):
    """Permit unfinished source coordinates but never arbitrary JSON types."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    doc_id: Annotated[StrictStr, Field(max_length=128)] = ""
    source_sha256: Annotated[StrictStr, Field(max_length=64)] = ""
    start_char: Annotated[StrictInt, Field(ge=0)] | None = None
    end_char: Annotated[StrictInt, Field(ge=0)] | None = None


class GoldenDraftCase(BaseModel):
    """Persist work in progress without claiming executable ground truth."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    id: GoldenCaseId
    question: Annotated[StrictStr, Field(max_length=20000)] = ""
    category: GoldenCategory | None = None
    facet: GoldenFacet = "factual"
    tags: Annotated[tuple[GoldenTag, ...], Field(max_length=30)] = ()
    answers: Annotated[tuple[DraftSpan, ...], Field(max_length=100)] = ()
    expected_label: Literal["SUPPORTED", "NOT_IN_DOCS"] | None = None
    reference_answer: Annotated[StrictStr, Field(max_length=100000)] = ""
    note: Annotated[StrictStr, Field(max_length=20000)] = ""
    curation_status: Literal["agent-curated", "user-authored"] = "user-authored"
    approval_status: Literal["pending-author-approval"] = "pending-author-approval"
    human_verified: Literal[False] = False

    @field_validator("human_verified", mode="before")
    @classmethod
    def literal_unverified(cls, value: object) -> object:
        """Never convert a false-like value into a human review claim."""
        if value is not False:
            raise ValueError("human_verified must be false")
        return value

    @field_validator("tags", mode="after")
    @classmethod
    def unique_tags(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Preserve tag order while removing normalized duplicates."""
        return tuple(dict.fromkeys(value))

    def missing(self) -> tuple[DraftFieldIssue, ...]:
        """Locate completeness failures before invoking the strict executable schema."""
        issues: list[DraftFieldIssue] = []

        def add(field: str, message: str) -> None:
            """Append one precise missing-field diagnosis."""
            issues.append(DraftFieldIssue(location=(field,), code="incomplete", message=message))

        if not self.question.strip():
            add("question", "Enter the evaluation question.")
        if self.category is None:
            add("category", "Choose whether the original documents can answer this question.")
        if not self.note.strip():
            add("note", "Enter a review note for this question.")
        if self.category == "absent":
            if self.answers:
                add("answers", "Absent-evidence questions must have no source spans.")
            if self.expected_label != "NOT_IN_DOCS" or self.reference_answer != "NOT_IN_DOCS":
                add("expected_label", "Absent-evidence questions must use NOT_IN_DOCS.")
        elif self.category is not None:
            if self.expected_label != "SUPPORTED":
                add("expected_label", "This question type must expect SUPPORTED.")
            if not self.reference_answer.strip() or self.reference_answer == "NOT_IN_DOCS":
                add(
                    "reference_answer",
                    "Enter the reference answer supported by the original document.",
                )
            if not self.answers:
                add("answers", "Add at least one original-source span.")
            for index, span in enumerate(self.answers):
                checks = {
                    "doc_id": bool(span.doc_id.strip()) and len(span.doc_id) <= 32,
                    "source_sha256": len(span.source_sha256) == 64
                    and all(c in "0123456789abcdef" for c in span.source_sha256),
                    "end_char": span.start_char is not None
                    and span.end_char is not None
                    and span.end_char > span.start_char,
                }
                for field, valid in checks.items():
                    if not valid:
                        issues.append(
                            DraftFieldIssue(
                                location=("answers", index, field),
                                code="incomplete",
                                message="Complete the original-source coordinates.",
                            )
                        )
        return tuple(issues)


DRAFT_CASES = TypeAdapter(Annotated[list[GoldenDraftCase], Field(max_length=10000)])


def executable_cases(payload: object) -> list[GoldenCase]:
    """Reject the whole dataset when any draft is incomplete, never silently dropping cases."""
    drafts = DRAFT_CASES.validate_python(payload)
    issues = tuple(
        issue.model_copy(update={"location": ("cases", index, *issue.location)})
        for index, case in enumerate(drafts)
        for issue in case.missing()
    )
    if issues:
        raise DraftInputError(issues)
    cases = [GoldenCase.model_validate(case.model_dump(mode="json")) for case in drafts]
    validate_unique_cases(cases)
    return cases


def unique_draft_ids(cases: list[GoldenDraftCase]) -> None:
    """Allow incomplete text to repeat while preserving stable question identities."""
    if len({case.id for case in cases}) != len(cases):
        raise DraftInputError(
            (
                DraftFieldIssue(
                    location=("id",), code="duplicate", message="Question IDs must be unique."
                ),
            )
        )
