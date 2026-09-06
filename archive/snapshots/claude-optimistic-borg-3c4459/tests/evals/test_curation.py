"""Candidate intake, explicit review decisions, and fail-closed promotion."""

import hashlib
import json
from pathlib import Path

import pytest

from app.evals.curation import (
    CandidateCase,
    CurationError,
    ReviewDecision,
    candidate_states,
    load_candidate_cases,
    load_review_decisions,
    promote_approved,
    review_queue_markdown,
    write_golden_cases,
)
from app.evals.loader import load_golden_cases
from app.evals.types import GoldenCase


def _temporary_contract(tmp_path: Path) -> tuple[Path, dict, dict]:
    """Build one tiny corpus with a manifest, one golden case, and one candidate."""
    raw = "<p>Revenue was 42 dollars.</p><p>Margin was 9 percent.</p>"
    source = tmp_path / "source.html"
    source.write_text(raw, encoding="utf-8")
    digest = hashlib.sha256(raw.encode()).hexdigest()

    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps([{"ticker": "TEST", "report_date": "2024-12-31", "file": str(source)}]),
        encoding="utf-8",
    )

    def span(marker: str) -> dict:
        start = raw.index(marker)
        return {
            "doc_id": "TEST-FY2024",
            "source_sha256": digest,
            "start_char": start,
            "end_char": start + len(marker),
        }

    golden = {
        "id": "m3c-01",
        "question": "What was the revenue?",
        "category": "simple_lookup",
        "facet": "factual",
        "tags": [],
        "answers": [span("Revenue was 42 dollars.")],
        "expected_label": "SUPPORTED",
        "reference_answer": "42 dollars.",
        "note": "Temporary golden case.",
        "curation_status": "agent-curated",
        "approval_status": "pending-author-approval",
        "human_verified": False,
    }
    candidate = {
        "id": "m3s-01",
        "question": "What was the margin?",
        "category": "exact_number",
        "facet": "numeric",
        "tags": [],
        "answers": [span("Margin was 9 percent.")],
        "expected_label": "SUPPORTED",
        "reference_answer": "9 percent.",
        "note": "Temporary candidate case.",
        "curation_status": "agent-curated",
        "approval_status": "pending-author-approval",
        "human_verified": False,
        "generator": "claude-fable-5",
    }
    return manifest, golden, candidate


def _load(tmp_path: Path, candidates: list[dict], golden: list[dict], manifest: Path):
    """Write and load one candidate batch against a golden suite."""
    candidate_path = tmp_path / "candidates.json"
    candidate_path.write_text(json.dumps(candidates), encoding="utf-8")
    golden_cases = [GoldenCase.model_validate(case) for case in golden]
    return load_candidate_cases(candidate_path, golden_cases=golden_cases, manifest_path=manifest)


def test_candidate_schema_inherits_golden_invariants(tmp_path):
    """Inherit every golden invariant while pinning the candidate id and generator."""
    _manifest, _golden_case, candidate = _temporary_contract(tmp_path)
    assert CandidateCase.model_validate(candidate).generator == "claude-fable-5"

    for corruption in (
        {"id": "m3c-01"},
        {"generator": "   "},
        {"generator": "claude|fable-5"},
        {"category": "absent"},
        {"approval_status": "author-approved"},
        {"human_verified": True},
    ):
        with pytest.raises(ValueError):
            CandidateCase.model_validate({**candidate, **corruption})

    with pytest.raises(ValueError):
        CandidateCase.model_validate(
            {key: value for key, value in candidate.items() if key != "generator"}
        )


def test_intake_rejects_duplicates_golden_collisions_and_wide_spans(tmp_path):
    """Reject repeated identities, golden collisions, and reconnaissance-width spans."""
    manifest, golden, candidate = _temporary_contract(tmp_path)

    twin = {**candidate, "id": "m3s-02"}
    with pytest.raises(CurationError, match="duplicate normalized candidate question"):
        _load(tmp_path, [candidate, twin], [golden], manifest)

    echo = {**candidate, "question": golden["question"].upper()}
    with pytest.raises(CurationError, match="duplicates a golden question"):
        _load(tmp_path, [echo], [golden], manifest)

    reuse = {**candidate, "answers": golden["answers"]}
    with pytest.raises(CurationError, match="reuses a golden answer span identity"):
        _load(tmp_path, [reuse], [golden], manifest)

    wide = {
        **candidate,
        "answers": [{**candidate["answers"][0], "end_char": 10_000}],
    }
    with pytest.raises(CurationError, match="reconnaissance"):
        _load(tmp_path, [wide], [golden], manifest)


def test_intake_wraps_source_binding_failures_as_curation_errors(tmp_path):
    """Report a broken source citation in the curation error domain."""
    manifest, golden, candidate = _temporary_contract(tmp_path)
    stale = {
        **candidate,
        "answers": [{**candidate["answers"][0], "source_sha256": "0" * 64}],
    }
    with pytest.raises(CurationError, match="source hash does not match"):
        _load(tmp_path, [stale], [golden], manifest)


def test_decisions_are_explicit_and_absence_stays_pending(tmp_path):
    """Resolve a candidate only through an explicit verdict; silence stays pending."""
    _manifest, _golden_case, candidate = _temporary_contract(tmp_path)
    candidates = [CandidateCase.model_validate(candidate)]

    with pytest.raises(CurationError, match="does not exist"):
        load_review_decisions(tmp_path / "missing.json")

    decision = {
        "candidate_id": "m3s-01",
        "decision": "reject",
        "reviewer": "author",
        "note": "The question is ambiguous.",
    }
    decisions_path = tmp_path / "decisions.json"
    decisions_path.write_text(json.dumps([decision, decision]), encoding="utf-8")
    with pytest.raises(CurationError, match="duplicate review decision"):
        load_review_decisions(decisions_path)

    decisions_path.write_text(json.dumps([decision]), encoding="utf-8")
    decisions = load_review_decisions(decisions_path)
    assert candidate_states(candidates, decisions) == {"m3s-01": "rejected"}
    assert candidate_states(candidates) == {"m3s-01": "pending"}

    stray = ReviewDecision.model_validate({**decision, "candidate_id": "m3s-99"})
    with pytest.raises(CurationError, match="unknown candidate"):
        candidate_states(candidates, [stray])

    with pytest.raises(CurationError, match="candidate ids must be unique"):
        candidate_states([candidates[0], candidates[0]])
    with pytest.raises(CurationError, match="duplicate review decision"):
        candidate_states(candidates, [decisions[0], decisions[0]])


def test_review_queue_markdown_is_deterministic(tmp_path):
    """Render the review queue in id order with each candidate's resolved state."""
    _manifest, _golden_case, candidate = _temporary_contract(tmp_path)
    second = {
        **candidate,
        "id": "m3s-02",
        "question": "Which fact is absent from every filing?",
        "category": "absent",
        "facet": "policy",
        "answers": [],
        "expected_label": "NOT_IN_DOCS",
        "reference_answer": "NOT_IN_DOCS",
    }
    candidates = [
        CandidateCase.model_validate(second),
        CandidateCase.model_validate(candidate),
    ]
    decisions = [
        ReviewDecision.model_validate(
            {
                "candidate_id": "m3s-01",
                "decision": "approve",
                "reviewer": "author",
                "note": "Span and wording verified.",
            }
        )
    ]

    assert review_queue_markdown(candidates, decisions) == (
        "| ID | Category | Facet | Positive source | Generator | Decision |\n"
        "|---|---|---|---|---|---|\n"
        "| m3s-01 | exact_number | numeric | TEST-FY2024 | claude-fable-5 | approved |\n"
        "| m3s-02 | absent | policy | none | claude-fable-5 | pending |"
    )


def test_promotion_mints_next_ids_and_keeps_pending_provenance(tmp_path):
    """Mint the next golden ids for approvals without certifying them."""
    manifest, golden, candidate = _temporary_contract(tmp_path)
    second = {
        **candidate,
        "id": "m3s-02",
        "question": "Which fact is absent from every filing?",
        "category": "absent",
        "facet": "policy",
        "answers": [],
        "expected_label": "NOT_IN_DOCS",
        "reference_answer": "NOT_IN_DOCS",
    }
    narrowed = {**candidate["answers"][0], "end_char": candidate["answers"][0]["end_char"] - 1}
    third = {
        **candidate,
        "id": "m3s-03",
        "question": "How wide was the margin?",
        "answers": [narrowed],
    }
    candidates = _load(tmp_path, [candidate, second, third], [golden], manifest)

    def decide(candidate_id: str, decision: str) -> object:
        return ReviewDecision.model_validate(
            {
                "candidate_id": candidate_id,
                "decision": decision,
                "reviewer": "author",
                "note": "Reviewed against the raw source.",
            }
        )

    golden_cases = [GoldenCase.model_validate(golden)]
    promoted = promote_approved(
        candidates,
        [decide("m3s-03", "approve"), decide("m3s-01", "approve"), decide("m3s-02", "reject")],
        golden_cases,
        manifest_path=manifest,
    )

    assert [case.id for case in promoted] == ["m3c-02", "m3c-03"]
    assert [case.question for case in promoted] == [
        "What was the margin?",
        "How wide was the margin?",
    ]
    for case in promoted:
        assert type(case) is GoldenCase
        assert case.approval_status == "pending-author-approval"
        assert case.human_verified is False
        assert "generator" not in case.model_dump()

    assert promote_approved(candidates, [], golden_cases, manifest_path=manifest) == ()


def test_promotion_rejects_an_exhausted_id_namespace(tmp_path):
    """Refuse to promote once the two-digit golden id namespace is full."""
    manifest, golden, candidate = _temporary_contract(tmp_path)
    candidates = _load(tmp_path, [candidate], [golden], manifest)
    decision = ReviewDecision.model_validate(
        {
            "candidate_id": "m3s-01",
            "decision": "approve",
            "reviewer": "author",
            "note": "Reviewed against the raw source.",
        }
    )
    full = [GoldenCase.model_validate({**golden, "id": "m3c-99"})]

    with pytest.raises(CurationError, match="exhausted"):
        promote_approved(candidates, [decision], full, manifest_path=manifest)


def test_promotion_rebinds_approved_spans_to_the_raw_source(tmp_path):
    """Rebind every approved span to the raw source before minting an id."""
    manifest, golden, candidate = _temporary_contract(tmp_path)
    stale = CandidateCase.model_validate(
        {**candidate, "answers": [{**candidate["answers"][0], "source_sha256": "0" * 64}]}
    )
    decision = ReviewDecision.model_validate(
        {
            "candidate_id": "m3s-01",
            "decision": "approve",
            "reviewer": "author",
            "note": "Approved before the source drifted.",
        }
    )

    with pytest.raises(CurationError, match="source hash does not match"):
        promote_approved(
            [stale], [decision], [GoldenCase.model_validate(golden)], manifest_path=manifest
        )


def test_promotion_without_approvals_skips_irrelevant_manifest_io(tmp_path):
    """Return empty without touching the manifest when nothing was approved."""
    _manifest, golden, candidate = _temporary_contract(tmp_path)

    assert (
        promote_approved(
            [CandidateCase.model_validate(candidate)],
            [],
            [GoldenCase.model_validate(golden)],
            manifest_path=tmp_path / "missing-manifest.json",
        )
        == ()
    )


def test_written_promotions_reload_as_golden_cases(tmp_path):
    """Write promotions to a new file that reloads as golden cases and is never overwritten."""
    manifest, golden, candidate = _temporary_contract(tmp_path)
    candidates = _load(tmp_path, [candidate], [golden], manifest)
    decision = ReviewDecision.model_validate(
        {
            "candidate_id": "m3s-01",
            "decision": "approve",
            "reviewer": "author",
            "note": "Reviewed against the raw source.",
        }
    )
    promoted = promote_approved(
        candidates, [decision], [GoldenCase.model_validate(golden)], manifest_path=manifest
    )

    with pytest.raises(CurationError, match="must be a .json file"):
        write_golden_cases(tmp_path / "promoted.txt", promoted)

    target = write_golden_cases(tmp_path / "promoted.json", promoted)
    reloaded = load_golden_cases(target, manifest_path=manifest)
    assert [case.id for case in reloaded] == ["m3c-02"]

    original = target.read_bytes()
    with pytest.raises(CurationError, match="already exists"):
        write_golden_cases(target, promoted)
    assert target.read_bytes() == original

    with pytest.raises(CurationError, match="cases must not be empty"):
        write_golden_cases(tmp_path / "empty.json", ())
    assert not (tmp_path / "empty.json").exists()


def test_a_candidate_directory_is_loaded_as_one_sorted_batch(tmp_path):
    """Load every candidate file in a directory as a single cross-file batch."""
    manifest, golden, candidate = _temporary_contract(tmp_path)
    narrowed = {**candidate["answers"][0], "end_char": candidate["answers"][0]["end_char"] - 1}
    second = {
        **candidate,
        "id": "m3s-02",
        "question": "How wide was the margin?",
        "answers": [narrowed],
    }
    batch = tmp_path / "batch"
    batch.mkdir()
    (batch / "r2.json").write_text(json.dumps([second]), encoding="utf-8")
    (batch / "r1.json").write_text(json.dumps([candidate]), encoding="utf-8")
    golden_cases = [GoldenCase.model_validate(golden)]

    loaded = load_candidate_cases(batch, golden_cases=golden_cases, manifest_path=manifest)
    assert [case.id for case in loaded] == ["m3s-01", "m3s-02"]

    (batch / "r3.json").write_text(json.dumps([{**second, "id": "m3s-01"}]), encoding="utf-8")
    with pytest.raises(CurationError, match="duplicate candidate id"):
        load_candidate_cases(batch, golden_cases=golden_cases, manifest_path=manifest)

    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(CurationError, match="no candidate JSON files found"):
        load_candidate_cases(empty, golden_cases=golden_cases, manifest_path=manifest)


def test_intake_rejects_a_repeated_id_or_span_between_two_candidates(tmp_path):
    """Reject a batch that repeats an id or an answer span across two candidates."""
    manifest, golden, candidate = _temporary_contract(tmp_path)
    narrowed = {**candidate["answers"][0], "end_char": candidate["answers"][0]["end_char"] - 1}

    same_id = {**candidate, "question": "How wide was the margin?", "answers": [narrowed]}
    with pytest.raises(CurationError, match="duplicate candidate id: m3s-01"):
        _load(tmp_path, [candidate, same_id], [golden], manifest)

    same_span = {**candidate, "id": "m3s-02", "question": "How wide was the margin?"}
    with pytest.raises(CurationError, match="duplicate answer span identity in m3s-02"):
        _load(tmp_path, [candidate, same_span], [golden], manifest)


def test_unreadable_or_misshaped_candidate_files_fail_in_the_curation_domain(tmp_path):
    """Report every reader and schema failure as a curation error, not a golden one."""
    manifest, golden, candidate = _temporary_contract(tmp_path)
    golden_cases = [GoldenCase.model_validate(golden)]
    path = tmp_path / "candidates.json"

    def load() -> list[CandidateCase]:
        """Load the rewritten candidate file under the standard contract."""
        return load_candidate_cases(path, golden_cases=golden_cases, manifest_path=manifest)

    path.write_text('[{"id": "m3s-01", "id": "m3s-02"}]', encoding="utf-8")
    with pytest.raises(CurationError, match="duplicate JSON key: id"):
        load()

    path.write_text("[{", encoding="utf-8")
    with pytest.raises(CurationError, match="cannot read valid UTF-8 JSON"):
        load()

    path.write_text(json.dumps(candidate), encoding="utf-8")
    with pytest.raises(CurationError, match="candidate file root must be a JSON array"):
        load()

    path.write_text(json.dumps([{"id": "m3s-01"}]), encoding="utf-8")
    with pytest.raises(CurationError, match="invalid candidate cases"):
        load()


def test_misshaped_decision_files_fail_in_the_curation_domain(tmp_path):
    """Report a non-array decision root and an invalid decision as curation errors."""
    path = tmp_path / "decisions.json"

    path.write_text(json.dumps({"candidate_id": "m3s-01"}), encoding="utf-8")
    with pytest.raises(CurationError, match="decisions file root must be a JSON array"):
        load_review_decisions(path)

    path.write_text(json.dumps([{"candidate_id": "m3s-01"}]), encoding="utf-8")
    with pytest.raises(CurationError, match="invalid review decisions"):
        load_review_decisions(path)


def test_promotion_ignores_foreign_namespaces_and_mints_the_requested_prefix(tmp_path):
    """Reserve numbers only inside the target namespace, whatever else the suite holds."""
    manifest, golden, candidate = _temporary_contract(tmp_path)
    candidates = _load(tmp_path, [candidate], [golden], manifest)
    decision = ReviewDecision.model_validate(
        {
            "candidate_id": "m3s-01",
            "decision": "approve",
            "reviewer": "author",
            "note": "Reviewed against the raw source.",
        }
    )
    foreign = [
        GoldenCase.model_validate({**golden, "id": "ko-simple-07"}),
        GoldenCase.model_validate(
            {**golden, "id": "golden", "question": "Which value is disclosed?"}
        ),
    ]

    promoted = promote_approved(candidates, [decision], foreign, manifest_path=manifest)
    assert [case.id for case in promoted] == ["m3c-01"]

    joined = promote_approved(
        candidates, [decision], foreign, manifest_path=manifest, golden_prefix="ko"
    )
    assert [case.id for case in joined] == ["ko-01"]


def test_the_review_queue_refuses_an_empty_batch_and_escapes_every_cell(tmp_path):
    """Refuse an empty queue and keep an unconstrained document id inside its cell."""
    _manifest, _golden_case, candidate = _temporary_contract(tmp_path)

    with pytest.raises(CurationError, match="candidates must not be empty"):
        review_queue_markdown([])

    hostile = CandidateCase.model_validate(
        {
            **candidate,
            "answers": [{**candidate["answers"][0], "doc_id": "TEST|X\nm3s-99"}],
        }
    )
    assert review_queue_markdown([hostile]) == (
        "| ID | Category | Facet | Positive source | Generator | Decision |\n"
        "|---|---|---|---|---|---|\n"
        "| m3s-01 | exact_number | numeric | TEST\\|X m3s-99 | claude-fable-5 | pending |"
    )


def test_a_promotion_artifact_creates_its_parent_directory(tmp_path):
    """Write into a directory that does not exist yet instead of failing on it."""
    manifest, golden, candidate = _temporary_contract(tmp_path)
    candidates = _load(tmp_path, [candidate], [golden], manifest)
    decision = ReviewDecision.model_validate(
        {
            "candidate_id": "m3s-01",
            "decision": "approve",
            "reviewer": "author",
            "note": "Reviewed against the raw source.",
        }
    )
    promoted = promote_approved(
        candidates, [decision], [GoldenCase.model_validate(golden)], manifest_path=manifest
    )

    target = write_golden_cases(tmp_path / "rounds" / "r1" / "promoted.json", promoted)
    assert load_golden_cases(target, manifest_path=manifest) == list(promoted)
