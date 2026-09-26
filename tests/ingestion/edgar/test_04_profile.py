"""Per-issuer profile selection and its fallback across fiscal years."""

import json
from pathlib import Path
from types import ModuleType

SAMPLE = {
    "segmentation": {"type": "number", "rules": [{"font_weight": 700}]},
    "validation": {"expected_items": 23, "must_have": ["1"]},
}


def test_unknown_year_falls_back_to_the_newest_profile(
    edgar_module: ModuleType,
    tmp_path: Path,
) -> None:
    """Fall back to the newest learned year rather than the first bootstrap year.

    Layouts evolve forward, so an old exceptional filing must not become the default.
    """
    profile_path = tmp_path / "sec/TEST/profile.json"
    edgar_module.save_profile(profile_path, "TEST", 2019, {**SAMPLE, "learned_from": "old"})
    edgar_module.save_profile(profile_path, "TEST", 2023, {**SAMPLE, "learned_from": "new"})
    edgar_module.save_profile(profile_path, "TEST", 2020, {**SAMPLE, "learned_from": "older"})
    data = json.loads(profile_path.read_text())

    assert data["default_year"] == "2023"
    assert edgar_module.load_profile(profile_path, 1999)["learned_from"] == "new"


def test_each_profile_year_is_self_contained(
    edgar_module: ModuleType,
    tmp_path: Path,
) -> None:
    """Keep each year complete so loading requires no merge semantics."""
    profile_path = tmp_path / "sec/TEST/profile.json"
    first = {
        "segmentation": {"type": "number", "rules": [{"font_size": 10.0}]},
        "validation": {"expected_items": 21},
    }
    second = {"segmentation": {"type": "xref"}, "validation": {"must_have": ["8"]}}
    edgar_module.save_profile(profile_path, "TEST", 2019, first)
    edgar_module.save_profile(profile_path, "TEST", 2023, second)

    assert edgar_module.load_profile(profile_path, 2019) == first
    assert edgar_module.load_profile(profile_path, 2023) == second
    assert "rules" not in edgar_module.load_profile(profile_path, 2023)["segmentation"]


def test_failed_bootstrap_profile_is_not_saved(
    edgar_module: ModuleType,
    tmp_path: Path,
) -> None:
    """Leave a newly learned profile on disk only after successful validation."""
    source = tmp_path / "unstructured.html"
    source.write_text("<html><body><p>Unstructured filing body</p></body></html>")
    from tests.ingestion.support import filing_document, filing_source

    entry = filing_source(source, document=filing_document(issuer="TEST"))

    result, profile = edgar_module.parse_filing(entry)

    assert result.profile_used == "bootstrap"
    assert result.parse_status == "needs_profile_update"
    assert profile["segmentation"] == {"type": "undefined"}
    assert not (tmp_path / "sec/TEST/profile.json").exists()
