"""Official identity binding validates exact bytes without changing source or golden records."""

import json

from app.evals.golden.binding import bind_golden, matrix_scope
from tests.evals.support import source_bound_golden


def test_binding_changes_only_runtime_answer_ids(tmp_path):
    """An exact official filing and hash can resolve a changed local document identifier."""
    payload, manifest, requirements = source_bound_golden(tmp_path)
    before = manifest.read_bytes()
    bound = bind_golden(payload, manifest, "sec", requirements_path=requirements)
    assert bound.ready
    assert bound.cases[0].answers[0].doc_id == "sec-current"
    assert payload[0]["answers"][0]["doc_id"] == "NVDA-FY2024"
    assert manifest.read_bytes() == before
    assert bound.cases[0].human_verified is False
    assert bound.sources[0].filing_id
    assert matrix_scope(manifest, "sec").selections[0].selection_id == "evaluation-scope"


def test_wrong_hash_is_not_repaired_or_relabelled(tmp_path):
    """A matching company and filing cannot authorize evidence from different bytes."""
    payload, manifest, requirements = source_bound_golden(tmp_path)
    payload[0]["answers"][0]["source_sha256"] = "0" * 64
    bound = bind_golden(payload, manifest, "sec", requirements_path=requirements)
    assert not bound.ready
    assert bound.sources[0].state == "source_invalid"
    assert bound.sources[0].detail is not None
    assert "hash does not match" in bound.sources[0].detail
    assert bound.cases[0].answers[0].doc_id == "NVDA-FY2024"


def test_missing_registry_and_other_receipt_are_not_substituted(tmp_path):
    """Missing exact receipts remain actionable source requirements, never best-effort aliases."""
    payload, manifest, requirements = source_bound_golden(tmp_path)
    mismatch = bind_golden(payload, manifest, "dart", requirements_path=requirements)
    assert mismatch.sources[0].state == "source_invalid"
    requirement = json.loads(requirements.read_text())
    requirement["NVDA-FY2024"]["filing_id"] = "different-official-filing"
    requirements.write_text(json.dumps(requirement))
    bound = bind_golden(payload, manifest, "sec", requirements_path=requirements)
    assert bound.sources[0].state == "source_missing"
    assert bound.sources[0].issuer == "NVDA"


def test_user_golden_can_reference_current_document_id(tmp_path):
    """User evidence uses current IDs while retaining the same exact-source checks."""
    payload, manifest, requirements = source_bound_golden(tmp_path)
    payload[0]["answers"][0]["doc_id"] = "sec-current"
    assert bind_golden(payload, manifest, "sec", requirements_path=requirements).ready
