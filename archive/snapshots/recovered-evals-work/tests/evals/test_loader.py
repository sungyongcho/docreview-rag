"""Strict golden JSON parsing and source-citation rejection paths."""

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from app.evals.loader import GoldenDataError, load_golden_cases


def _temporary_contract(tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    """Write a one-document corpus and return its manifest and matching case."""
    source = tmp_path / "source.html"
    raw = "<p>Answer 42.</p>"
    source.write_text(raw, encoding="utf-8")
    start = raw.index("Answer")
    end = start + len("Answer 42.")
    digest = hashlib.sha256(raw.encode()).hexdigest()

    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            [
                {
                    "ticker": "TEST",
                    "report_date": "2024-12-31",
                    "file": str(source),
                }
            ]
        ),
        encoding="utf-8",
    )
    case: dict[str, Any] = {
        "id": "m3c-01",
        "question": "What is the answer?",
        "category": "simple_lookup",
        "facet": "factual",
        "tags": [],
        "answers": [
            {
                "doc_id": "TEST-FY2024",
                "source_sha256": digest,
                "start_char": start,
                "end_char": end,
            }
        ],
        "expected_label": "SUPPORTED",
        "reference_answer": "42.",
        "note": "Temporary loader case.",
        "curation_status": "agent-curated",
        "approval_status": "pending-author-approval",
        "human_verified": False,
    }
    return manifest, case


def _write_cases(path: Path, cases: list[dict[str, Any]]) -> None:
    """Write golden cases to one JSON file."""
    path.write_text(json.dumps(cases), encoding="utf-8")


def test_loader_accepts_a_case_bound_to_its_exact_source_snapshot(tmp_path):
    """Load one case whose span matches the cited digest and offsets."""
    manifest, case = _temporary_contract(tmp_path)
    golden = tmp_path / "retrieval.json"
    _write_cases(golden, [case])

    cases = load_golden_cases(golden, manifest_path=manifest)

    assert [loaded.id for loaded in cases] == ["m3c-01"]


def test_loader_rejects_duplicate_json_keys_and_non_array_roots(tmp_path):
    """Reject silently merged duplicate keys and non-array golden roots."""
    manifest, _case = _temporary_contract(tmp_path)
    golden = tmp_path / "retrieval.json"
    golden.write_text('[{"id":"m3c-01","id":"m3c-02"}]', encoding="utf-8")
    with pytest.raises(GoldenDataError, match="duplicate JSON key"):
        load_golden_cases(golden, manifest_path=manifest)

    golden.write_text("{}", encoding="utf-8")
    with pytest.raises(GoldenDataError, match="root must be a JSON array"):
        load_golden_cases(golden, manifest_path=manifest)


@pytest.mark.parametrize("corruption", ["hash", "bounds", "document", "empty"])
def test_loader_rejects_invalid_source_citations(tmp_path, corruption):
    """Reject spans with a stale digest, out-of-bounds end, unknown document, or no text."""
    manifest, case = _temporary_contract(tmp_path)
    answer = case["answers"][0]
    if corruption == "hash":
        answer["source_sha256"] = "0" * 64
    elif corruption == "bounds":
        answer["end_char"] = 10_000
    elif corruption == "document":
        answer["doc_id"] = "MISSING-FY2024"
    else:
        answer["start_char"] = 0
        answer["end_char"] = 3

    golden = tmp_path / "retrieval.json"
    _write_cases(golden, [case])
    with pytest.raises(GoldenDataError):
        load_golden_cases(golden, manifest_path=manifest)


@pytest.mark.parametrize("duplicate", ["id", "question"])
def test_loader_rejects_ids_and_questions_reused_within_one_suite(tmp_path, duplicate):
    """Reject an id or question that another case in the same suite already claimed."""
    manifest, case = _temporary_contract(tmp_path)
    other = {**case, "id": "m3c-02", "question": "A different question?"}
    other[duplicate] = case[duplicate]
    golden = tmp_path / "retrieval.json"
    _write_cases(golden, [case, other])

    with pytest.raises(GoldenDataError, match=f"duplicate .*{duplicate}"):
        load_golden_cases(golden, manifest_path=manifest)


def test_a_directory_is_not_a_golden_suite(tmp_path):
    """Reject a directory, whose sibling files are separate suites sharing case ids."""
    manifest, case = _temporary_contract(tmp_path)
    golden_dir = tmp_path / "golden"
    golden_dir.mkdir()
    _write_cases(golden_dir / "retrieval.json", [case])
    _write_cases(golden_dir / "retrieval_ko.json", [case])

    with pytest.raises(GoldenDataError, match="cannot read valid UTF-8 JSON"):
        load_golden_cases(golden_dir, manifest_path=manifest)


def test_loader_rejects_answer_identity_reused_by_another_case(tmp_path):
    """Reject one exact answer span claimed by two different cases."""
    manifest, case = _temporary_contract(tmp_path)
    other = {**case, "id": "m3c-02", "question": "Which value is disclosed?"}
    golden = tmp_path / "retrieval.json"
    _write_cases(golden, [case, other])

    with pytest.raises(GoldenDataError, match=f"duplicate answer span identity in {other['id']}"):
        load_golden_cases(golden, manifest_path=manifest)


def test_manifest_entries_without_a_usable_document_identity_are_rejected(tmp_path):
    """Reject a manifest entry the registry adapter cannot turn into a document id."""
    manifest, case = _temporary_contract(tmp_path)
    manifest.write_text(json.dumps([{"report_date": "2024-12-31", "file": "x"}]), encoding="utf-8")
    golden = tmp_path / "retrieval.json"
    _write_cases(golden, [case])

    with pytest.raises(GoldenDataError, match="no usable document identity"):
        load_golden_cases(golden, manifest_path=manifest)
