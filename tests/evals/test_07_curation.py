"""M3.5 candidate curation, fail-closed promotion, and taxonomy breakdown tests."""

import hashlib
import json
import os
from pathlib import Path

import pytest

from app.evals.scoring import CaseScore
from app.evals.types import GoldenCase
from tests.support import REPO, need, optional_module

C = optional_module(os.getenv("EVAL_CURATION_MODULE", "app.evals.curation"))
B = optional_module(os.getenv("EVAL_BREAKDOWN_MODULE", "app.evals.breakdown"))

GOLDEN_PATH = REPO / "data" / "golden" / "retrieval.json"
MANIFEST_PATH = REPO / "data" / "corpus" / "manifest.json"
CANDIDATES_PATH = REPO / "data" / "golden" / "candidates" / "r1.json"

COMMITTED_CANDIDATE_COUNT = 4
COMMITTED_ABSENT_CANDIDATE_COUNT = 1


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
    candidate_path = tmp_path / "candidates.json"
    candidate_path.write_text(json.dumps(candidates), encoding="utf-8")
    golden_cases = [GoldenCase.model_validate(case) for case in golden]
    return C.load_candidate_cases(candidate_path, golden_cases=golden_cases, manifest_path=manifest)


def _case_score(case_id: str, recall: float, rank: int | None, k: int = 5) -> CaseScore:
    return CaseScore(
        case_id=case_id,
        k=k,
        gold_span_count=1,
        matched_gold_count=int(recall),
        recall_at_k=recall,
        hit_at_k=float(bool(rank)),
        reciprocal_rank=1.0 / rank if rank else 0.0,
        first_relevant_rank=rank,
    )


def _golden(case_id: str, category: str, facet: str, question: str) -> GoldenCase:
    absent = category == "absent"
    return GoldenCase.model_validate(
        {
            "id": case_id,
            "question": question,
            "category": category,
            "facet": facet,
            "tags": [],
            "answers": []
            if absent
            else [
                {
                    "doc_id": "TEST-FY2024",
                    "source_sha256": "a" * 64,
                    "start_char": int(case_id[4:]) * 10,
                    "end_char": int(case_id[4:]) * 10 + 5,
                }
            ],
            "expected_label": "NOT_IN_DOCS" if absent else "SUPPORTED",
            "reference_answer": "NOT_IN_DOCS" if absent else "A value.",
            "note": "Breakdown fixture.",
            "curation_status": "agent-curated",
            "approval_status": "pending-author-approval",
            "human_verified": False,
        }
    )


def test_committed_candidates_pass_every_machine_gate_and_stay_pending(E):
    need(E, "load_golden_cases")
    need(C, "candidate_states", "load_candidate_cases")
    golden_cases = E.load_golden_cases(GOLDEN_PATH, manifest_path=MANIFEST_PATH)
    candidates = C.load_candidate_cases(
        CANDIDATES_PATH, golden_cases=golden_cases, manifest_path=MANIFEST_PATH
    )

    assert len(candidates) == COMMITTED_CANDIDATE_COUNT
    absent = [candidate for candidate in candidates if candidate.category == "absent"]
    assert len(absent) == COMMITTED_ABSENT_CANDIDATE_COUNT
    assert all(candidate.id.startswith("m3s-") for candidate in candidates)
    assert all(candidate.generator.strip() for candidate in candidates)
    states = C.candidate_states(candidates)
    assert set(states.values()) == {"pending"}


def test_candidate_schema_inherits_golden_invariants(tmp_path):
    need(C, "CandidateCase")
    _manifest, _golden_case, candidate = _temporary_contract(tmp_path)
    assert C.CandidateCase.model_validate(candidate).generator == "claude-fable-5"

    for corruption in (
        {"id": "m3c-01"},
        {"generator": "   "},
        {"generator": "claude|fable-5"},
        {"category": "absent"},
        {"approval_status": "author-approved"},
        {"human_verified": True},
    ):
        with pytest.raises(ValueError):
            C.CandidateCase.model_validate({**candidate, **corruption})

    with pytest.raises(ValueError):
        C.CandidateCase.model_validate(
            {key: value for key, value in candidate.items() if key != "generator"}
        )


def test_intake_rejects_duplicates_golden_collisions_and_wide_spans(tmp_path):
    need(C, "CurationError", "load_candidate_cases")
    manifest, golden, candidate = _temporary_contract(tmp_path)

    twin = {**candidate, "id": "m3s-02"}
    with pytest.raises(C.CurationError, match="duplicate normalized candidate question"):
        _load(tmp_path, [candidate, twin], [golden], manifest)

    echo = {**candidate, "question": golden["question"].upper()}
    with pytest.raises(C.CurationError, match="duplicates a golden question"):
        _load(tmp_path, [echo], [golden], manifest)

    reuse = {**candidate, "answers": golden["answers"]}
    with pytest.raises(C.CurationError, match="reuses a golden answer span identity"):
        _load(tmp_path, [reuse], [golden], manifest)

    wide = {
        **candidate,
        "answers": [{**candidate["answers"][0], "end_char": 10_000}],
    }
    with pytest.raises(C.CurationError, match="reconnaissance"):
        _load(tmp_path, [wide], [golden], manifest)


def test_intake_wraps_source_binding_failures_as_curation_errors(tmp_path):
    need(C, "CurationError", "load_candidate_cases")
    manifest, golden, candidate = _temporary_contract(tmp_path)
    stale = {
        **candidate,
        "answers": [{**candidate["answers"][0], "source_sha256": "0" * 64}],
    }
    with pytest.raises(C.CurationError, match="source hash does not match"):
        _load(tmp_path, [stale], [golden], manifest)


def test_decisions_are_explicit_and_absence_stays_pending(tmp_path):
    need(C, "CandidateCase", "CurationError", "ReviewDecision", "candidate_states")
    need(C, "load_review_decisions")
    _manifest, _golden_case, candidate = _temporary_contract(tmp_path)
    candidates = [C.CandidateCase.model_validate(candidate)]

    with pytest.raises(C.CurationError, match="does not exist"):
        C.load_review_decisions(tmp_path / "missing.json")

    decision = {
        "candidate_id": "m3s-01",
        "decision": "reject",
        "reviewer": "author",
        "note": "The question is ambiguous.",
    }
    decisions_path = tmp_path / "decisions.json"
    decisions_path.write_text(json.dumps([decision, decision]), encoding="utf-8")
    with pytest.raises(C.CurationError, match="duplicate review decision"):
        C.load_review_decisions(decisions_path)

    decisions_path.write_text(json.dumps([decision]), encoding="utf-8")
    decisions = C.load_review_decisions(decisions_path)
    assert C.candidate_states(candidates, decisions) == {"m3s-01": "rejected"}
    assert C.candidate_states(candidates) == {"m3s-01": "pending"}

    stray = C.ReviewDecision.model_validate({**decision, "candidate_id": "m3s-99"})
    with pytest.raises(C.CurationError, match="unknown candidate"):
        C.candidate_states(candidates, [stray])

    with pytest.raises(C.CurationError, match="candidate ids must be unique"):
        C.candidate_states([candidates[0], candidates[0]])
    with pytest.raises(C.CurationError, match="duplicate review decision"):
        C.candidate_states(candidates, [decisions[0], decisions[0]])


def test_review_queue_markdown_is_deterministic(tmp_path):
    need(C, "CandidateCase", "ReviewDecision", "review_queue_markdown")
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
        C.CandidateCase.model_validate(second),
        C.CandidateCase.model_validate(candidate),
    ]
    decisions = [
        C.ReviewDecision.model_validate(
            {
                "candidate_id": "m3s-01",
                "decision": "approve",
                "reviewer": "author",
                "note": "Span and wording verified.",
            }
        )
    ]

    assert C.review_queue_markdown(candidates, decisions) == (
        "| ID | Category | Facet | Positive source | Generator | Decision |\n"
        "|---|---|---|---|---|---|\n"
        "| m3s-01 | exact_number | numeric | TEST-FY2024 | claude-fable-5 | approved |\n"
        "| m3s-02 | absent | policy | none | claude-fable-5 | pending |"
    )


def test_promotion_mints_next_ids_and_keeps_pending_provenance(tmp_path):
    need(C, "CandidateCase", "load_candidate_cases", "promote_approved", "ReviewDecision")
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
        return C.ReviewDecision.model_validate(
            {
                "candidate_id": candidate_id,
                "decision": decision,
                "reviewer": "author",
                "note": "Reviewed against the raw source.",
            }
        )

    golden_cases = [GoldenCase.model_validate(golden)]
    promoted = C.promote_approved(
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

    assert C.promote_approved(candidates, [], golden_cases, manifest_path=manifest) == ()


def test_promotion_rejects_an_exhausted_id_namespace(tmp_path):
    need(C, "CurationError", "load_candidate_cases", "promote_approved", "ReviewDecision")
    manifest, golden, candidate = _temporary_contract(tmp_path)
    candidates = _load(tmp_path, [candidate], [golden], manifest)
    decision = C.ReviewDecision.model_validate(
        {
            "candidate_id": "m3s-01",
            "decision": "approve",
            "reviewer": "author",
            "note": "Reviewed against the raw source.",
        }
    )
    full = [GoldenCase.model_validate({**golden, "id": "m3c-99"})]

    with pytest.raises(C.CurationError, match="exhausted"):
        C.promote_approved(candidates, [decision], full, manifest_path=manifest)


def test_promotion_rebinds_approved_spans_to_the_raw_source(tmp_path):
    need(C, "CandidateCase", "CurationError", "promote_approved", "ReviewDecision")
    manifest, golden, candidate = _temporary_contract(tmp_path)
    stale = C.CandidateCase.model_validate(
        {**candidate, "answers": [{**candidate["answers"][0], "source_sha256": "0" * 64}]}
    )
    decision = C.ReviewDecision.model_validate(
        {
            "candidate_id": "m3s-01",
            "decision": "approve",
            "reviewer": "author",
            "note": "Approved before the source drifted.",
        }
    )

    with pytest.raises(C.CurationError, match="source hash does not match"):
        C.promote_approved(
            [stale], [decision], [GoldenCase.model_validate(golden)], manifest_path=manifest
        )


def test_promotion_without_approvals_skips_irrelevant_manifest_io(tmp_path):
    need(C, "CandidateCase", "promote_approved")
    _manifest, golden, candidate = _temporary_contract(tmp_path)

    assert (
        C.promote_approved(
            [C.CandidateCase.model_validate(candidate)],
            [],
            [GoldenCase.model_validate(golden)],
            manifest_path=tmp_path / "missing-manifest.json",
        )
        == ()
    )


def test_written_promotions_reload_as_golden_cases(E, tmp_path):
    need(E, "load_golden_cases")
    need(C, "CurationError", "load_candidate_cases", "promote_approved", "ReviewDecision")
    need(C, "write_golden_cases")
    manifest, golden, candidate = _temporary_contract(tmp_path)
    candidates = _load(tmp_path, [candidate], [golden], manifest)
    decision = C.ReviewDecision.model_validate(
        {
            "candidate_id": "m3s-01",
            "decision": "approve",
            "reviewer": "author",
            "note": "Reviewed against the raw source.",
        }
    )
    promoted = C.promote_approved(
        candidates, [decision], [GoldenCase.model_validate(golden)], manifest_path=manifest
    )

    with pytest.raises(C.CurationError, match="must be a .json file"):
        C.write_golden_cases(tmp_path / "promoted.txt", promoted)

    target = C.write_golden_cases(tmp_path / "promoted.json", promoted)
    reloaded = E.load_golden_cases(target, manifest_path=manifest)
    assert [case.id for case in reloaded] == ["m3c-02"]

    original = target.read_bytes()
    with pytest.raises(C.CurationError, match="already exists"):
        C.write_golden_cases(target, [])
    assert target.read_bytes() == original


def test_breakdown_groups_in_declaration_order_with_macro_averages():
    need(B, "breakdown_by_category", "breakdown_by_facet")
    cases = [
        _golden("m3c-01", "multi_hop", "comparison", "How did margin change?"),
        _golden("m3c-02", "simple_lookup", "factual", "What was disclosed?"),
        _golden("m3c-03", "simple_lookup", "risk", "Which risk is named?"),
        _golden("m3c-04", "absent", "policy", "What dividend was declared?"),
    ]
    scores = [
        _case_score("m3c-01", 0.0, None),
        _case_score("m3c-02", 1.0, 1),
        _case_score("m3c-03", 1.0, 2),
    ]

    by_category = B.breakdown_by_category(cases, scores)
    assert [(group.group, group.case_count) for group in by_category] == [
        ("simple_lookup", 2),
        ("multi_hop", 1),
    ]
    assert by_category[0].recall_at_k == 1.0
    assert by_category[0].mrr == 0.75
    assert by_category[1].hit_rate_at_k == 0.0

    by_facet = B.breakdown_by_facet(cases, scores)
    assert [group.group for group in by_facet] == ["factual", "comparison", "risk"]
    assert all(group.k == 5 for group in by_facet)


def test_breakdown_rejects_partial_stray_or_mixed_scoring():
    need(B, "breakdown_by_category")
    cases = [
        _golden("m3c-01", "simple_lookup", "factual", "What was disclosed?"),
        _golden("m3c-02", "exact_number", "numeric", "How much revenue?"),
        _golden("m3c-03", "absent", "policy", "What dividend was declared?"),
    ]
    complete = [_case_score("m3c-01", 1.0, 1), _case_score("m3c-02", 0.0, None)]

    with pytest.raises(ValueError, match="missing a score"):
        B.breakdown_by_category(cases, complete[:1])
    with pytest.raises(ValueError, match="unknown golden case"):
        B.breakdown_by_category(cases, [*complete, _case_score("m3c-09", 1.0, 1)])
    with pytest.raises(ValueError, match="absent case cannot carry"):
        B.breakdown_by_category(cases, [*complete, _case_score("m3c-03", 1.0, 1)])
    with pytest.raises(ValueError, match="duplicate case score"):
        B.breakdown_by_category(cases, [*complete, _case_score("m3c-01", 1.0, 1)])
    with pytest.raises(ValueError, match="same k"):
        B.breakdown_by_category(cases, [complete[0], _case_score("m3c-02", 0.0, None, k=10)])
    with pytest.raises(ValueError, match="scores must not be empty"):
        B.breakdown_by_category(cases, [])

    duplicate_id = _golden("m3c-01", "multi_hop", "comparison", "How did it change?")
    with pytest.raises(ValueError, match="duplicate golden case id"):
        B.breakdown_by_category([cases[0], duplicate_id], complete[:1])


def test_breakdown_markdown_renders_the_exact_table():
    need(B, "breakdown_by_category", "breakdown_markdown")
    cases = [
        _golden("m3c-01", "simple_lookup", "factual", "What was disclosed?"),
        _golden("m3c-02", "simple_lookup", "risk", "Which risk is named?"),
    ]
    scores = [_case_score("m3c-01", 1.0, 1), _case_score("m3c-02", 0.0, None)]
    groups = B.breakdown_by_category(cases, scores)

    assert B.breakdown_markdown("Category", groups) == (
        "| Category | Cases | Recall@k | Hit rate@k | MRR |\n"
        "|---|---:|---:|---:|---:|\n"
        "| simple_lookup | 2 | 0.500000 | 0.500000 | 0.500000 |"
    )
    with pytest.raises(ValueError, match="must not be empty"):
        B.breakdown_markdown("Category", [])
    with pytest.raises(ValueError, match="dimension must not be blank"):
        B.breakdown_markdown("   ", groups)

    assert B.breakdown_by_category(cases, list(reversed(scores))) == groups
