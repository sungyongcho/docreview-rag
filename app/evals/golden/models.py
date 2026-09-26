"""Strict, source-stable value objects for retrieval evaluation data."""

from collections.abc import Iterable
from typing import Annotated, Literal, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    TypeAdapter,
    field_validator,
    model_validator,
)

from app.contracts.evidence import SourceSha256

GoldenCategory = Literal["simple_lookup", "exact_number", "multi_hop", "absent"]
GoldenFacet = Literal["factual", "comparison", "risk", "policy", "numeric"]
ExpectedLabel = Literal["SUPPORTED", "NOT_IN_DOCS"]

# Case ids and tags are both lowercase hyphenated slugs. Which prefixes a given
# golden file uses is suite policy, checked next to that suite's other expectations.
SLUG_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
GoldenCaseId = Annotated[StrictStr, Field(pattern=SLUG_PATTERN)]


def normalize_golden_tag(value: str) -> str:
    """Keep readable multilingual labels and reject empty or control-character tags."""
    import unicodedata

    value = unicodedata.normalize("NFC", value).strip()
    if (
        not value
        or len(value) > 64
        or any(unicodedata.category(char).startswith("C") for char in value)
    ):
        raise ValueError("Tags must contain 1–64 printable characters")
    return value


GoldenTag = Annotated[StrictStr, AfterValidator(normalize_golden_tag)]


class GoldenSpan(BaseModel):
    """One half-open answer span in an immutable raw filing snapshot.

    The type blocks empty and reversed intervals and pins both coordinates to
    one exact source snapshot, so an answer can never drift to other bytes.
    """

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

    @property
    def identity(self) -> tuple[str, str, int, int]:
        """Return the exact source coordinates that make two spans the same span.

        Every uniqueness and relevance check compares spans through this tuple, so
        the snapshot digest is part of identity: the same offsets in a different
        snapshot are a different span.
        """
        return (self.doc_id, self.source_sha256, self.start_char, self.end_char)


class GoldenCase(BaseModel):
    """One reviewed-question candidate and its retrieval ground truth.

    The validators keep positive and absent contracts mutually exclusive and
    pin the provenance fields to their pre-review literals, so unreviewed data
    can never present itself as approved.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: GoldenCaseId
    question: Annotated[StrictStr, Field(min_length=1)]
    category: GoldenCategory
    facet: GoldenFacet
    tags: tuple[GoldenTag, ...]
    answers: tuple[GoldenSpan, ...]
    expected_label: ExpectedLabel
    reference_answer: Annotated[StrictStr, Field(min_length=1)]
    note: Annotated[StrictStr, Field(min_length=1)]
    curation_status: Literal["agent-curated", "user-authored"]
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
            raise ValueError("text field must not be blank.")
        return value

    @field_validator("tags", mode="after")
    @classmethod
    def reject_duplicate_tags(cls, tags: tuple[str, ...]) -> tuple[str, ...]:
        """Collapse repeated tags in first-seen order so membership stays unambiguous."""
        if len(tags) != len(set(tags)):
            return tuple(dict.fromkeys(tags))
        return tags

    @model_validator(mode="after")
    def validate_label_and_answers(self) -> Self:
        """Keep positive and absent-case contracts mutually exclusive."""
        identities = {answer.identity for answer in self.answers}

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


class GoldenDataError(ValueError):
    """A golden file or its cited source snapshot violates the golden-data contract."""


class SourceMissingError(GoldenDataError):
    """A cited source artifact must be acquired before evaluation can run."""


def normalized_question(question: str) -> str:
    """Return the casefolded single-space form every duplicate check compares."""
    return " ".join(question.casefold().split())


def validate_unique_cases(cases: Iterable[GoldenCase]) -> None:
    """Reject id, question, and answer-identity duplicates across one batch.

    Parameters
    ----------
    cases : Iterable[GoldenCase]
        Every case in the batch, checked as one unit.

    Raises
    ------
    GoldenDataError
        If two cases share an id, a casefolded whitespace-normalized question,
        or one exact answer-span identity.

    Notes
    -----
    Span identity is compared across cases; duplicates inside one case are
    already rejected by ``GoldenCase`` itself.
    """
    ids: set[str] = set()
    questions: set[str] = set()
    answer_identities: set[tuple[str, str, int, int]] = set()

    for case in cases:
        if case.id in ids:
            raise GoldenDataError(f"duplicate golden case id: {case.id}")
        ids.add(case.id)

        normalized = normalized_question(case.question)
        if normalized in questions:
            raise GoldenDataError(f"duplicate normalized golden case question: {case.question}")
        questions.add(normalized)

        for answer in case.answers:
            if answer.identity in answer_identities:
                raise GoldenDataError(f"duplicate answer span identity in {case.id}")
            answer_identities.add(answer.identity)


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
