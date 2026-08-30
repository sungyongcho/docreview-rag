"""Validate and promote golden candidates without mutating the committed suite.

Candidate intake reuses the golden loader's source-binding contract. Promotion emits
a separate file and never certifies or merges a case automatically.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
import re
from typing import Annotated, Final, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictStr,
    TypeAdapter,
    ValidationError,
    field_validator,
)

from app.evals.artifacts import JSON_SUFFIX, encode_json_document, read_strict_json
from app.evals.loader import (
    DEFAULT_MANIFEST_PATH,
    GoldenDataError,
    normalized_question,
    validate_golden_sources,
    validate_unique_cases,
)
from app.evals.reporting import markdown_table
from app.evals.types import GoldenCase

# A committed answer span never exceeds this many raw characters. A wider span is
# reconnaissance, not an answer: it inflates IoU denominators and hides whether the
# generator actually located the evidence.
MAX_CANDIDATE_SPAN_CHARS: Final[int] = 2_500

# Candidates and golden cases share one numbered namespace shape so promotion is a
# rename, not a reformat. Both prefixes are values rather than literals scattered
# through the module because a second suite (M10's Korean cases) enters through this
# same gate and must not have M3's prefix minted into it.
CANDIDATE_ID_PREFIX: Final[str] = "m3s"
DEFAULT_GOLDEN_ID_PREFIX: Final[str] = "m3c"
ID_NUMBER_WIDTH: Final[int] = 2
MAX_ID_NUMBER: Final[int] = 10**ID_NUMBER_WIDTH - 1
# One shape, many suites: any module's candidate namespace ("m3s", "m10s") passes,
# while promotion still refuses to mint a golden id the target suite already uses.
CANDIDATE_ID_PATTERN: Final[str] = rf"^m[0-9]+s-[0-9]{{{ID_NUMBER_WIDTH}}}$"

DecisionLabel = Literal["approve", "reject"]
CandidateState = Literal["pending", "approved", "rejected"]


class CurationError(ValueError):
    """A candidate file, review decision, or promotion violates the curation contract."""


class CandidateCase(GoldenCase):
    """One generated golden candidate that has not earned an ``m3c`` id yet.

    A candidate carries the full golden payload plus generator provenance, so every
    golden invariant is inherited and enforced at intake. Only promotion may mint a
    golden id, and a candidate can never claim any status beyond the pinned pending
    literals it inherits.
    """

    id: Annotated[StrictStr, Field(pattern=CANDIDATE_ID_PATTERN)]
    generator: Annotated[StrictStr, Field(min_length=1)]

    @field_validator("generator", mode="after")
    @classmethod
    def reject_blank_generator(cls, value: str) -> str:
        """Keep generator provenance non-empty, single-line, and table-safe."""
        if not value.strip():
            raise ValueError("generator must not be blank")
        if "|" in value or "\n" in value:
            raise ValueError("generator must not contain pipes or newlines")
        return value


class ReviewDecision(BaseModel):
    """One explicit human verdict on one candidate. Absence of a verdict is pending."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: Annotated[StrictStr, Field(pattern=CANDIDATE_ID_PATTERN)]
    decision: DecisionLabel
    reviewer: Annotated[StrictStr, Field(min_length=1)]
    note: Annotated[StrictStr, Field(min_length=1)]

    @field_validator("reviewer", "note", mode="after")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        """Reject strings that contain only whitespace."""
        if not value.strip():
            raise ValueError("text fields must not be blank")
        return value


CANDIDATE_CASES = TypeAdapter(list[CandidateCase])
REVIEW_DECISIONS = TypeAdapter(list[ReviewDecision])


def _candidate_files(path: Path) -> list[Path]:
    """Resolve one candidate file or the sorted JSON files in a directory.

    Parameters
    ----------
    path : Path
        Candidate JSON file or directory.

    Returns
    -------
    list[Path]
        One explicit file or every ``*.json`` file in deterministic order.

    Raises
    ------
    CurationError
        If ``path`` is a directory without candidate JSON files.
    """
    if path.is_dir():
        files = sorted(path.glob("*.json"))
        if not files:
            raise CurationError(f"no candidate JSON files found in {path}")
        return files
    return [path]


def _validate_unique_candidates(candidates: Sequence[CandidateCase]) -> None:
    """Reject duplicate candidate identities and reconnaissance spans.

    Parameters
    ----------
    candidates : Sequence[CandidateCase]
        Candidate batch checked as one intake unit.

    Raises
    ------
    CurationError
        If ids, normalized questions, or answer identities repeat, or if an answer
        span exceeds ``MAX_CANDIDATE_SPAN_CHARS``.

    Notes
    -----
    The three identity checks are the suite's own uniqueness scan, reused so a
    candidate that could not survive promotion fails at intake. Only the width gate
    is specific to unadmitted candidates.
    """
    validate_unique_cases(candidates, error=CurationError, label="candidate")
    for candidate in candidates:
        for answer in candidate.answers:
            width = answer.end_char - answer.start_char
            if width > MAX_CANDIDATE_SPAN_CHARS:
                raise CurationError(
                    f"{candidate.id} span is reconnaissance, not an answer: "
                    f"{width} > {MAX_CANDIDATE_SPAN_CHARS} chars"
                )


def _validate_disjoint_from_golden(
    candidates: Sequence[CandidateCase],
    golden_cases: Sequence[GoldenCase],
) -> None:
    """Reject candidate questions and spans already present in the golden suite.

    Parameters
    ----------
    candidates : Sequence[CandidateCase]
        Candidate batch seeking admission.
    golden_cases : Sequence[GoldenCase]
        Committed suite whose questions and answer identities are reserved.

    Raises
    ------
    CurationError
        If a candidate repeats a normalized golden question or answer identity.
    """
    golden_questions = {normalized_question(case.question) for case in golden_cases}
    golden_identities = {answer.identity for case in golden_cases for answer in case.answers}
    for candidate in candidates:
        if normalized_question(candidate.question) in golden_questions:
            raise CurationError(
                f"{candidate.id} duplicates a golden question: {candidate.question}"
            )
        for answer in candidate.answers:
            if answer.identity in golden_identities:
                raise CurationError(f"{candidate.id} reuses a golden answer span identity")


def load_candidate_cases(
    path: str | Path,
    *,
    golden_cases: Sequence[GoldenCase],
    manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
) -> list[CandidateCase]:
    """Load generated candidates through every mechanical intake gate.

    Parameters
    ----------
    path : str | Path
        Candidate JSON file or directory of candidate files.
    golden_cases : Sequence[GoldenCase]
        Committed cases used for collision checks.
    manifest_path : str | Path
        Corpus manifest used to rebind every positive answer span.

    Returns
    -------
    list[CandidateCase]
        Candidates that passed schema, uniqueness, disjointness, and source checks.

    Raises
    ------
    CurationError
        If candidate parsing, validation, collision checks, or source binding fails.

    Notes
    -----
    A successful intake establishes only mechanical validity. Human judgment remains
    an explicit later decision.
    """
    candidates: list[CandidateCase] = []
    for candidate_path in _candidate_files(Path(path)):
        payload = read_strict_json(candidate_path, error=CurationError)
        if not isinstance(payload, list):
            raise CurationError(f"candidate file root must be a JSON array: {candidate_path}")
        try:
            candidates.extend(CANDIDATE_CASES.validate_python(payload))
        except ValidationError as exc:
            raise CurationError(f"invalid candidate cases in {candidate_path}: {exc}") from exc

    _validate_unique_candidates(candidates)
    _validate_disjoint_from_golden(candidates, golden_cases)
    try:
        validate_golden_sources(candidates, manifest_path)
    except GoldenDataError as exc:
        raise CurationError(str(exc)) from exc
    return candidates


def load_review_decisions(path: str | Path) -> list[ReviewDecision]:
    """Load one explicit and auditable decision per reviewed candidate.

    Parameters
    ----------
    path : str | Path
        Required JSON decision file.

    Returns
    -------
    list[ReviewDecision]
        Validated decisions in file order.

    Raises
    ------
    CurationError
        If the file is missing or invalid, or repeats a candidate decision.

    Notes
    -----
    A missing file is an error rather than an empty decision set so a mistyped path
    cannot masquerade as a completed review with no approvals.
    """
    decisions_path = Path(path)
    if not decisions_path.is_file():
        raise CurationError(f"decisions file does not exist: {decisions_path}")
    payload = read_strict_json(decisions_path, error=CurationError)
    if not isinstance(payload, list):
        raise CurationError(f"decisions file root must be a JSON array: {decisions_path}")
    try:
        decisions = REVIEW_DECISIONS.validate_python(payload)
    except ValidationError as exc:
        raise CurationError(f"invalid review decisions in {decisions_path}: {exc}") from exc

    seen: set[str] = set()
    for decision in decisions:
        if decision.candidate_id in seen:
            raise CurationError(f"duplicate review decision for {decision.candidate_id}")
        seen.add(decision.candidate_id)
    return decisions


def candidate_states(
    candidates: Sequence[CandidateCase],
    decisions: Sequence[ReviewDecision] = (),
) -> dict[str, CandidateState]:
    """Resolve every candidate to pending, approved, or rejected.

    Parameters
    ----------
    candidates : Sequence[CandidateCase]
        Candidates whose states are required.
    decisions : Sequence[ReviewDecision]
        Explicit reviewer decisions; omission means pending.

    Returns
    -------
    dict[str, CandidateState]
        Candidate ids mapped to their resolved state.

    Raises
    ------
    CurationError
        If candidate ids repeat, a decision names an unknown candidate, or a
        candidate has more than one decision.

    Notes
    -----
    The state dictionary is also the uniqueness and decision ledger, avoiding
    parallel sets that could drift from the returned state. Silence never approves
    a candidate.
    """
    states: dict[str, CandidateState] = {}
    for candidate in candidates:
        if candidate.id in states:
            raise CurationError("candidate ids must be unique")
        states[candidate.id] = "pending"

    for decision in decisions:
        if decision.candidate_id not in states:
            raise CurationError(f"decision references unknown candidate: {decision.candidate_id}")
        if states[decision.candidate_id] != "pending":
            raise CurationError(f"duplicate review decision for {decision.candidate_id}")
        states[decision.candidate_id] = "approved" if decision.decision == "approve" else "rejected"
    return states


def review_queue_markdown(
    candidates: Sequence[CandidateCase],
    decisions: Sequence[ReviewDecision] = (),
) -> str:
    """Render the deterministic queue reviewed before promotion.

    Parameters
    ----------
    candidates : Sequence[CandidateCase]
        Candidates displayed in id order.
    decisions : Sequence[ReviewDecision]
        Explicit decisions used to label each queue row.

    Returns
    -------
    str
        Markdown table with one row per candidate.

    Raises
    ------
    CurationError
        If ``candidates`` is empty, or if ids or decisions violate
        ``candidate_states``.

    Notes
    -----
    An empty queue is an error rather than a heading-only table, so a batch that
    failed to load and a review round with nothing to review cannot render
    identically to the reviewer.
    """
    if not candidates:
        raise CurationError("candidates must not be empty")
    states = candidate_states(candidates, decisions)
    return markdown_table(
        ["ID", "Category", "Facet", "Positive source", "Generator", "Decision"],
        ["left", "left", "left", "left", "left", "left"],
        [
            [
                candidate.id,
                candidate.category,
                candidate.facet,
                ", ".join(sorted({answer.doc_id for answer in candidate.answers})) or "none",
                candidate.generator,
                states[candidate.id],
            ]
            for candidate in sorted(candidates, key=lambda case: case.id)
        ],
    )


def _next_golden_number(golden_cases: Sequence[GoldenCase], prefix: str) -> int:
    """Return the first free number in one prefixed golden id namespace.

    Parameters
    ----------
    golden_cases : Sequence[GoldenCase]
        Committed suite, which may mix namespaces or ids of any other slug shape.
    prefix : str
        Namespace whose numbered ids reserve a range.

    Returns
    -------
    int
        One past the highest reserved number, or 1 when none is reserved.

    Notes
    -----
    Only ids of the exact ``prefix-NN`` shape reserve a number. ``GoldenCase.id``
    admits any lowercase slug, so splitting on the first hyphen and calling ``int``
    would raise on ids such as ``ko-simple-01`` or ``golden``; matching the shape
    instead both keeps the failure impossible and leaves foreign namespaces alone.
    """
    pattern = re.compile(rf"^{re.escape(prefix)}-([0-9]{{{ID_NUMBER_WIDTH}}})$")
    reserved = [
        int(match.group(1))
        for match in (pattern.match(case.id) for case in golden_cases)
        if match is not None
    ]
    return max(reserved, default=0) + 1


def promote_approved(
    candidates: Sequence[CandidateCase],
    decisions: Sequence[ReviewDecision],
    golden_cases: Sequence[GoldenCase],
    *,
    manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
    golden_prefix: str = DEFAULT_GOLDEN_ID_PREFIX,
) -> tuple[GoldenCase, ...]:
    """Mint new golden ids for explicitly approved candidates.

    Parameters
    ----------
    candidates : Sequence[CandidateCase]
        Full candidate batch whose mechanics are revalidated.
    decisions : Sequence[ReviewDecision]
        Explicit decisions controlling which candidates advance.
    golden_cases : Sequence[GoldenCase]
        Committed suite that reserves questions, spans, and existing ids.
    manifest_path : str | Path
        Corpus manifest used to rebind approved positive spans.
    golden_prefix : str
        Id namespace the promoted cases join. It must be the prefix of the suite
        in ``golden_cases``, because minting one suite's prefix into another
        produces ids that suite's own loader would never have issued.

    Returns
    -------
    tuple[GoldenCase, ...]
        Approved candidates in candidate-id order with newly minted ids.

    Raises
    ------
    CurationError
        If validation fails or the numbered golden id namespace is exhausted.

    Notes
    -----
    With no approvals, promotion returns after candidate and decision validation and
    performs no irrelevant manifest I/O. Approved cases are rebound to the raw source
    and retain pending author approval; admission never mints certification.
    """
    _validate_unique_candidates(candidates)
    _validate_disjoint_from_golden(candidates, golden_cases)
    states = candidate_states(candidates, decisions)

    approved = [
        candidate
        for candidate in sorted(candidates, key=lambda case: case.id)
        if states[candidate.id] == "approved"
    ]
    if not approved:
        return ()

    try:
        validate_golden_sources(approved, manifest_path)
    except GoldenDataError as exc:
        raise CurationError(str(exc)) from exc
    number = _next_golden_number(golden_cases, golden_prefix)
    promoted: list[GoldenCase] = []
    for candidate in approved:
        if number > MAX_ID_NUMBER:
            raise CurationError(
                f"golden id namespace {golden_prefix}-{'N' * ID_NUMBER_WIDTH} is exhausted"
            )
        payload = candidate.model_dump(mode="json", exclude={"generator"})
        payload["id"] = f"{golden_prefix}-{number:0{ID_NUMBER_WIDTH}d}"
        try:
            promoted.append(GoldenCase.model_validate(payload))
        except ValidationError as exc:
            raise CurationError(f"promoted case from {candidate.id} is invalid: {exc}") from exc
        number += 1
    return tuple(promoted)


def write_golden_cases(path: str | Path, cases: Sequence[GoldenCase]) -> Path:
    """Create a new golden-shaped JSON artifact for a reviewed merge.

    Parameters
    ----------
    path : str | Path
        New ``.json`` destination; an existing path is never overwritten.
    cases : Sequence[GoldenCase]
        Promoted cases to serialize in their supplied order.

    Returns
    -------
    Path
        Created artifact path.

    Raises
    ------
    CurationError
        If the destination is not JSON, ``cases`` is empty, or the path exists.

    Notes
    -----
    This writer never edits ``retrieval.json``. Merging the new artifact into the
    committed suite remains a separate reviewed release operation. An empty
    ``cases`` is refused because ``promote_approved`` returns empty on a round with
    no approvals, and a committed ``[]`` file would read as a promotion whose cases
    were removed rather than as a round that promoted nothing.

    The encoding comes from ``encode_json_document`` so a promoted file and a run
    artifact are written by one contract; only the key order differs, because a
    golden file's field order is part of what a reviewer reads.
    """
    target = Path(path)
    if target.suffix != JSON_SUFFIX:
        raise CurationError(f"golden output must be a .json file: {target}")
    if not cases:
        raise CurationError("cases must not be empty")
    serialized = encode_json_document(
        [case.model_dump(mode="json") for case in cases],
        sort_keys=False,
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("x", encoding="utf-8") as output:
            output.write(serialized)
    except FileExistsError as exc:
        raise CurationError(f"golden output already exists: {target}") from exc
    return target
