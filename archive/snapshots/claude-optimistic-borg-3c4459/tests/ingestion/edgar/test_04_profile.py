"""Per-issuer profile selection and its fallback across fiscal years."""

import json
from pathlib import Path
from types import ModuleType

SAMPLE = {
    "segmentation": {"type": "number", "rules": [{"font_weight": 700}]},
    "validation": {"expected_items": 23, "must_have": ["1"]},
}


def test_missing_profile_returns_none(
    edgar_module: ModuleType,
    isolated_profiles: Path,
) -> None:
    """Use None to signal that a filing year still needs profile bootstrapping."""
    assert edgar_module.load_profile("ZZZZ", 2024) is None


def test_profile_save_load_roundtrip(
    edgar_module: ModuleType,
    isolated_profiles: Path,
) -> None:
    """Return the same complete profile that was persisted for a year."""
    edgar_module.save_profile("TEST", 2024, SAMPLE)
    assert edgar_module.load_profile("TEST", 2024) == SAMPLE


def test_profile_year_keys_are_strings_and_sorted(
    edgar_module: ModuleType,
    isolated_profiles: Path,
) -> None:
    """Store JSON year keys as ascending strings regardless of insertion order."""
    for year in (2023, 2019, 2021):
        edgar_module.save_profile("TEST", year, SAMPLE)

    data = json.loads((isolated_profiles / "TEST.json").read_text())

    assert list(data["profiles"]) == ["2019", "2021", "2023"]


def test_unknown_year_falls_back_to_the_newest_profile(
    edgar_module: ModuleType,
    isolated_profiles: Path,
) -> None:
    """Fall back to the newest learned year rather than the first bootstrap year.

    Layouts evolve forward, so an old exceptional filing must not become the default.
    """
    edgar_module.save_profile("TEST", 2019, {**SAMPLE, "learned_from": "old"})
    edgar_module.save_profile("TEST", 2023, {**SAMPLE, "learned_from": "new"})
    edgar_module.save_profile("TEST", 2020, {**SAMPLE, "learned_from": "older"})
    data = json.loads((isolated_profiles / "TEST.json").read_text())

    assert data["default_year"] == "2023"
    assert edgar_module.load_profile("TEST", 1999)["learned_from"] == "new"


def test_each_profile_year_is_self_contained(
    edgar_module: ModuleType,
    isolated_profiles: Path,
) -> None:
    """Keep each year complete so loading requires no merge semantics."""
    first = {
        "segmentation": {"type": "number", "rules": [{"font_size": 10.0}]},
        "validation": {"expected_items": 21},
    }
    second = {"segmentation": {"type": "xref"}, "validation": {"must_have": ["8"]}}
    edgar_module.save_profile("TEST", 2019, first)
    edgar_module.save_profile("TEST", 2023, second)

    assert edgar_module.load_profile("TEST", 2019) == first
    assert edgar_module.load_profile("TEST", 2023) == second
    assert "rules" not in edgar_module.load_profile("TEST", 2023)["segmentation"]


def test_failed_bootstrap_profile_is_not_saved(
    edgar_module: ModuleType,
    isolated_profiles: Path,
    tmp_path: Path,
) -> None:
    """Leave a newly learned profile on disk only after successful validation."""
    source = tmp_path / "unstructured.html"
    source.write_text("<html><body><p>Unstructured filing body</p></body></html>")
    entry = {
        "ticker": "TEST",
        "report_date": "2024-12-31",
        "file": str(source),
    }

    result, profile = edgar_module.parse_filing(entry)

    assert result.profile_used == "bootstrap"
    assert result.parse_status == "needs_profile_update"
    assert profile["segmentation"] == {"type": "undefined"}
    assert not (isolated_profiles / "TEST.json").exists()
