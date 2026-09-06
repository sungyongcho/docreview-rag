"""L1: strict JSON loading, corpus binding, and committed-set balance."""

from collections import Counter
import hashlib
import json
from pathlib import Path

from bs4 import BeautifulSoup
import pytest

from tests.evals.golden import (
    ABSENT_CASE_COUNT,
    CASE_COUNT,
    CATEGORY_COUNTS,
    DEMO_HERO_COUNT,
    FACET_COUNTS,
    MAX_ANSWER_SPAN_CHARS,
    POSITIVE_CASE_COUNT,
    POSITIVE_DOCUMENT_COUNT,
    POSITIVE_TICKER_COUNTS,
)
from tests.support import REPO, need

GOLDEN_PATH = REPO / "data" / "golden" / "retrieval.json"
MANIFEST_PATH = REPO / "data" / "corpus" / "manifest.json"


def _temporary_contract(tmp_path: Path) -> tuple[Path, Path, dict]:
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
    case = {
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
    return source, manifest, case


def _write_cases(path: Path, cases) -> None:
    path.write_text(json.dumps(cases), encoding="utf-8")


def test_committed_suite_loads_with_exact_balance_and_pending_status(E):
    need(E, "load_golden_cases")
    cases = E.load_golden_cases(GOLDEN_PATH, manifest_path=MANIFEST_PATH)
    positive = [case for case in cases if case.category != "absent"]
    absent = [case for case in cases if case.category == "absent"]

    assert len(cases) == CASE_COUNT
    assert len(positive) == POSITIVE_CASE_COUNT
    assert len(absent) == ABSENT_CASE_COUNT
    assert Counter(case.category for case in cases) == CATEGORY_COUNTS
    assert Counter(case.facet for case in cases) == FACET_COUNTS
    assert sum("demo-hero" in case.tags for case in cases) == DEMO_HERO_COUNT
    assert all(case.curation_status == "agent-curated" for case in cases)
    assert all(case.approval_status == "pending-author-approval" for case in cases)
    assert all(case.human_verified is False for case in cases)


def test_positive_cases_cover_every_filing_and_are_ticker_balanced(E):
    need(E, "load_golden_cases")
    cases = E.load_golden_cases(GOLDEN_PATH, manifest_path=MANIFEST_PATH)
    positive = [case for case in cases if case.answers]
    doc_ids = {answer.doc_id for case in positive for answer in case.answers}
    tickers = Counter(next(iter(case.answers)).doc_id.split("-", 1)[0] for case in positive)

    assert len(doc_ids) == POSITIVE_DOCUMENT_COUNT
    assert tickers == POSITIVE_TICKER_COUNTS


def test_every_positive_span_is_narrow_visible_and_hash_bound(E):
    need(E, "load_golden_cases")
    cases = E.load_golden_cases(GOLDEN_PATH, manifest_path=MANIFEST_PATH)
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    paths = {
        f"{entry['ticker']}-FY{entry['report_date'][:4]}": REPO / entry["file"]
        for entry in manifest
    }
    identities = set()

    for case in cases:
        for answer in case.answers:
            raw_bytes = paths[answer.doc_id].read_bytes()
            raw = raw_bytes.decode("utf-8")
            identity = (
                answer.doc_id,
                answer.source_sha256,
                answer.start_char,
                answer.end_char,
            )
            assert identity not in identities
            identities.add(identity)
            assert hashlib.sha256(raw_bytes).hexdigest() == answer.source_sha256
            assert 0 <= answer.start_char < answer.end_char <= len(raw)
            assert answer.end_char - answer.start_char <= MAX_ANSWER_SPAN_CHARS
            evidence = BeautifulSoup(
                raw[answer.start_char : answer.end_char], "html.parser"
            ).get_text(" ", strip=True)
            assert evidence, f"{case.id} has no visible source evidence"


def test_loader_rejects_duplicate_json_keys_and_non_array_roots(E, tmp_path):
    need(E, "GoldenDataError", "load_golden_cases")
    _source, manifest, _case = _temporary_contract(tmp_path)
    golden = tmp_path / "retrieval.json"
    golden.write_text('[{"id":"m3c-01","id":"m3c-02"}]', encoding="utf-8")
    with pytest.raises(E.GoldenDataError, match="duplicate JSON key"):
        E.load_golden_cases(golden, manifest_path=manifest)

    golden.write_text("{}", encoding="utf-8")
    with pytest.raises(E.GoldenDataError, match="root must be a JSON array"):
        E.load_golden_cases(golden, manifest_path=manifest)


@pytest.mark.parametrize("corruption", ["hash", "bounds", "document", "empty"])
def test_loader_rejects_invalid_source_citations(E, tmp_path, corruption):
    need(E, "GoldenDataError", "load_golden_cases")
    _source, manifest, case = _temporary_contract(tmp_path)
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
    with pytest.raises(E.GoldenDataError):
        E.load_golden_cases(golden, manifest_path=manifest)


@pytest.mark.parametrize("duplicate", ["id", "question"])
def test_directory_loader_rejects_cross_file_duplicates(E, tmp_path, duplicate):
    need(E, "GoldenDataError", "load_golden_cases")
    _source, manifest, case = _temporary_contract(tmp_path)
    golden_dir = tmp_path / "golden"
    golden_dir.mkdir()
    first = golden_dir / "a.json"
    second = golden_dir / "b.json"
    _write_cases(first, [case])
    other = {**case, "id": "m3c-02", "question": "A different question?"}
    other[duplicate] = case[duplicate]
    _write_cases(second, [other])

    with pytest.raises(E.GoldenDataError, match=f"duplicate .*{duplicate}"):
        E.load_golden_cases(golden_dir, manifest_path=manifest)


def test_loader_rejects_answer_identity_reused_by_another_case(E, tmp_path):
    need(E, "GoldenDataError", "load_golden_cases")
    _source, manifest, case = _temporary_contract(tmp_path)
    other = {**case, "id": "m3c-02", "question": "Which value is disclosed?"}
    golden = tmp_path / "retrieval.json"
    _write_cases(golden, [case, other])

    with pytest.raises(E.GoldenDataError, match=f"duplicate answer span identity in {other['id']}"):
        E.load_golden_cases(golden, manifest_path=manifest)
