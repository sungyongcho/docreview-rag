"""Candidate intake, machine validation, review queue, and fail-closed promotion."""

from __future__ import annotations

from collections.abc import Sequence
import json
from pathlib import Path
from typing import Annotated, Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr, TypeAdapter, ValidationError
from pydantic.functional_validators import field_validator

from app.evals.loader import DEFAULT_MANIFEST_PATH, GoldenDataError, validate_golden_sources
from app.evals.types import GoldenCase

# A committed answer span never exceeds this many raw characters. A wider span is
# reconnaissance, not an answer: it inflates IoU denominators and hides whether the
# generator actually located the evidence.
MAX_CANDIDATE_SPAN_CHARS: Final[int] = 2_500

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

    id: Annotated[StrictStr, Field(pattern=r"^m3s-[0-9]{2}$")]
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

    candidate_id: Annotated[StrictStr, Field(pattern=r"^m3s-[0-9]{2}$")]
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


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CurationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _read_json(path: Path) -> object:
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except CurationError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CurationError(f"cannot read valid UTF-8 JSON from {path}: {exc}") from exc


def _candidate_files(path: Path) -> list[Path]:
    if path.is_dir():
        files = sorted(path.glob("*.json"))
        if not files:
            raise CurationError(f"no candidate JSON files found in {path}")
        return files
    return [path]


def _normalized_question(question: str) -> str:
    return " ".join(question.casefold().split())


def _span_identities(case: GoldenCase) -> list[tuple[str, str, int, int]]:
    return [
        (answer.doc_id, answer.source_sha256, answer.start_char, answer.end_char)
        for answer in case.answers
    ]


def _validate_unique_candidates(candidates: Sequence[CandidateCase]) -> None:
    ids: set[str] = set()
    questions: set[str] = set()
    identities: set[tuple[str, str, int, int]] = set()
    for candidate in candidates:
        if candidate.id in ids:
            raise CurationError(f"duplicate candidate id: {candidate.id}")
        ids.add(candidate.id)

        normalized = _normalized_question(candidate.question)
        if normalized in questions:
            raise CurationError(f"duplicate normalized candidate question: {candidate.question}")
        questions.add(normalized)

        for identity in _span_identities(candidate):
            if identity in identities:
                raise CurationError(f"duplicate answer span identity in {candidate.id}")
            identities.add(identity)

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
    golden_questions = {_normalized_question(case.question) for case in golden_cases}
    golden_identities = {identity for case in golden_cases for identity in _span_identities(case)}
    for candidate in candidates:
        if _normalized_question(candidate.question) in golden_questions:
            raise CurationError(
                f"{candidate.id} duplicates a golden question: {candidate.question}"
            )
        for identity in _span_identities(candidate):
            if identity in golden_identities:
                raise CurationError(f"{candidate.id} reuses a golden answer span identity")


def load_candidate_cases(
    path: str | Path,
    *,
    golden_cases: Sequence[GoldenCase],
    manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
) -> list[CandidateCase]:
    """Load one file or a directory of candidate files and run every machine gate.

    Structural validation, uniqueness, disjointness from the committed golden set,
    and raw-source binding all run here, so a candidate that survives intake fails
    later only on human judgment, never on mechanics.
    """
    candidates: list[CandidateCase] = []
    for candidate_path in _candidate_files(Path(path)):
        payload = _read_json(candidate_path)
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
    """Load explicit review decisions. A missing file is an error, never an empty set."""
    decisions_path = Path(path)
    if not decisions_path.is_file():
        raise CurationError(f"decisions file does not exist: {decisions_path}")
    payload = _read_json(decisions_path)
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
    """Map every candidate id to pending, approved, or rejected.

    Every decision must name a known candidate, and at most one decision may exist
    per candidate. A candidate without a decision stays pending — silence never
    approves anything.
    """
    known = {candidate.id for candidate in candidates}
    if len(known) != len(candidates):
        raise CurationError("candidate ids must be unique")

    states: dict[str, CandidateState] = {candidate.id: "pending" for candidate in candidates}
    decided: set[str] = set()
    for decision in decisions:
        if decision.candidate_id not in known:
            raise CurationError(f"decision references unknown candidate: {decision.candidate_id}")
        if decision.candidate_id in decided:
            raise CurationError(f"duplicate review decision for {decision.candidate_id}")
        decided.add(decision.candidate_id)
        states[decision.candidate_id] = "approved" if decision.decision == "approve" else "rejected"
    return states


def review_queue_markdown(
    candidates: Sequence[CandidateCase],
    decisions: Sequence[ReviewDecision] = (),
) -> str:
    """Render the deterministic review queue an author walks before any promotion."""
    states = candidate_states(candidates, decisions)
    lines = [
        "| ID | Category | Facet | Positive source | Generator | Decision |",
        "|---|---|---|---|---|---|",
    ]
    for candidate in sorted(candidates, key=lambda case: case.id):
        doc_ids = sorted({answer.doc_id for answer in candidate.answers})
        source = ", ".join(doc_ids) if doc_ids else "none"
        lines.append(
            f"| {candidate.id} | {candidate.category} | {candidate.facet} | "
            f"{source} | {candidate.generator} | {states[candidate.id]} |"
        )
    return "\n".join(lines)


def _next_golden_number(golden_cases: Sequence[GoldenCase]) -> int:
    return max((int(case.id.split("-", 1)[1]) for case in golden_cases), default=0) + 1


def promote_approved(
    candidates: Sequence[CandidateCase],
    decisions: Sequence[ReviewDecision],
    golden_cases: Sequence[GoldenCase],
    *,
    manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
) -> tuple[GoldenCase, ...]:
    """Mint golden cases from explicitly approved candidates only.

    Promotion re-runs every machine gate — uniqueness, disjointness from the
    committed set, and raw-source binding for the approved cases — assigns the next
    free ``m3c`` ids in candidate-id order, and keeps the pinned pending-approval
    provenance: entering the golden pool queues a case for the author, it never
    certifies one.
    """
    _validate_unique_candidates(candidates)
    _validate_disjoint_from_golden(candidates, golden_cases)
    states = candidate_states(candidates, decisions)

    approved = [
        candidate
        for candidate in sorted(candidates, key=lambda case: case.id)
        if states[candidate.id] == "approved"
    ]
    try:
        validate_golden_sources(approved, manifest_path)
    except GoldenDataError as exc:
        raise CurationError(str(exc)) from exc
    number = _next_golden_number(golden_cases)
    promoted: list[GoldenCase] = []
    for candidate in approved:
        if number > 99:
            raise CurationError("golden id namespace m3c-NN is exhausted")
        payload = candidate.model_dump(mode="json", exclude={"generator"})
        payload["id"] = f"m3c-{number:02d}"
        try:
            promoted.append(GoldenCase.model_validate(payload))
        except ValidationError as exc:
            raise CurationError(f"promoted case from {candidate.id} is invalid: {exc}") from exc
        number += 1
    return tuple(promoted)


def write_golden_cases(path: str | Path, cases: Sequence[GoldenCase]) -> Path:
    """Write promoted cases as a golden-shaped JSON array for a reviewed merge."""
    target = Path(path)
    if target.suffix != ".json":
        raise CurationError(f"golden output must be a .json file: {target}")
    payload = [case.model_dump(mode="json") for case in cases]
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return target
