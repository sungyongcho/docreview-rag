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
            {
                "corpus": {"corpus_id": "test", "name": "Test"},
                "documents": [
                    {
                        "document_id": "TEST-FY2024",
                        "registry": "sec",
                        "language": "en",
                        "issuer": "TEST",
                        "issuer_id": "0000000001",
                        "filing_id": "0000000001-24-000001",
                        "fiscal_year": 2024,
                        "form": "10-K",
                        "filing_date": "2025-01-01",
                        "report_period": "2024-12-31",
                        "source_url": "https://example.org/source",
                        "sec": {
                            "cik": "0000000001",
                            "accession": "0000000001-24-000001",
                            "primary_document": "source.html",
                        },
                    }
                ],
                "artifacts": [
                    {
                        "artifact_id": "source",
                        "document_id": "TEST-FY2024",
                        "role": "primary",
                        "path": "source.html",
                        "sha256": digest,
                        "byte_length": len(raw.encode()),
                        "encoding": "utf-8",
                        "acquisition": {
                            "acquired_at": "2025-01-01T00:00:00Z",
                            "url": "https://example.org/source",
                            "media_type": "text/html",
                        },
                    }
                ],
                "selections": [{"selection_id": "sec-evaluation", "artifact_ids": ["source"]}],
            }
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
    """Reject malformed catalogs before resolving golden document identities."""
    manifest, case = _temporary_contract(tmp_path)
    manifest.write_text(json.dumps([{"report_date": "2024-12-31", "file": "x"}]), encoding="utf-8")
    golden = tmp_path / "retrieval.json"
    _write_cases(golden, [case])

    with pytest.raises(GoldenDataError, match="invalid corpus manifest"):
        load_golden_cases(golden, manifest_path=manifest)


def test_loader_rejects_artifact_bytes_changed_after_acquisition(tmp_path):
    """Verify acquired bytes even when the golden still names the original digest."""
    manifest, case = _temporary_contract(tmp_path)
    golden = tmp_path / "retrieval.json"
    _write_cases(golden, [case])
    (tmp_path / "source.html").write_text("<p>Changed.</p>")
    with pytest.raises(GoldenDataError, match="artifact bytes disagree"):
        load_golden_cases(golden, manifest_path=manifest)


def test_loader_requires_a_known_processing_selection(tmp_path):
    """Never expand an unknown selection into the whole catalog."""
    manifest, case = _temporary_contract(tmp_path)
    golden = tmp_path / "retrieval.json"
    _write_cases(golden, [case])
    with pytest.raises(GoldenDataError, match="unknown processing selection"):
        load_golden_cases(golden, manifest_path=manifest, selection_id="missing")


def test_loader_distinguishes_acquired_bytes_from_decoded_source_digest(tmp_path):
    """Bind Korean offsets to decoded text while verifying original encoded bytes."""
    manifest, case = _temporary_contract(tmp_path)
    raw = "<p>정답입니다.</p>"
    acquired = raw.encode("cp949")
    (tmp_path / "source.html").write_bytes(acquired)
    catalog = json.loads(manifest.read_text())
    artifact = catalog["artifacts"][0]
    artifact.update(
        encoding="cp949", sha256=hashlib.sha256(acquired).hexdigest(), byte_length=len(acquired)
    )
    manifest.write_text(json.dumps(catalog))
    case["answers"][0].update(
        source_sha256=hashlib.sha256(raw.encode()).hexdigest(), start_char=3, end_char=9
    )
    golden = tmp_path / "retrieval.json"
    _write_cases(golden, [case])
    loaded = load_golden_cases(golden, manifest_path=manifest)
    assert loaded[0].answers[0].source_sha256 != artifact["sha256"]
