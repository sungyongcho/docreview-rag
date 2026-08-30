"""Profile learning, persistence, and convergence over repeated corpus passes."""

import json
from pathlib import Path
from types import ModuleType

import pytest

from tests.ingestion.golden import PROFILE_YEARS


# Bootstrap result structure
@pytest.mark.parametrize("ticker", sorted(PROFILE_YEARS))
def test_bootstrapped_corpus_profile_shape(
    ticker: str,
    parsed: dict,
    profiles_dir: Path,
) -> None:
    """Preserve the expected default year and explicitly learned years per ticker."""
    default_year, years = PROFILE_YEARS[ticker]
    data = json.loads((profiles_dir / f"{ticker}.json").read_text())

    assert data["default_year"] == default_year
    assert sorted(data["profiles"], key=int) == years


def test_xref_profile_has_no_expected_item_count(parsed: dict, profiles_dir: Path) -> None:
    """Omit expected_items for xref because each filing index supplies its own Items."""
    data = json.loads((profiles_dir / "INTC.json").read_text())
    profile = data["profiles"]["2019"]

    assert profile["segmentation"] == {"type": "xref"}
    assert "expected_items" not in profile["validation"]


# Repeated learning and failed-profile recovery
def test_profiles_converge_on_the_third_corpus_pass(
    edgar_module: ModuleType,
    manifest: list[dict],
    isolated_profiles: Path,
) -> None:
    """Converge after missing historical years self-heal across three passes."""
    amd = sorted(
        (entry for entry in manifest if entry["ticker"] == "AMD"),
        key=lambda entry: entry["report_date"],
    )
    passes = []
    for _ in range(3):
        used = {}
        for entry in amd:
            result, _profile = edgar_module.parse_filing(entry)
            assert result.parse_status == "parsed", (
                f"{result.doc_id}: parse warnings {result.warnings}"
            )
            used[result.fiscal_year] = result.profile_used
        passes.append(used)

    assert passes[0] == {
        2019: "bootstrap",
        2020: "saved",
        2021: "relearned",
        2022: "saved",
        2023: "relearned",
    }
    assert passes[1] == {
        2019: "saved",
        2020: "relearned",
        2021: "saved",
        2022: "relearned",
        2023: "saved",
    }
    assert passes[2] == dict.fromkeys(range(2019, 2024), "saved")


def test_failed_profile_is_relearned_before_it_is_saved(
    edgar_module: ModuleType,
    manifest: list[dict],
    isolated_profiles: Path,
) -> None:
    """Persist only a profile that successfully reparses and validates the filing."""
    entry = next(
        item
        for item in manifest
        if item["ticker"] == "NVDA" and item["report_date"].startswith("2024")
    )
    edgar_module.save_profile(
        "NVDA",
        2024,
        {
            "segmentation": {"type": "number", "rules": [{"font_size": 99.0}]},
            "validation": {
                "expected_items": 23,
                "must_have": ["1", "1A", "7", "8"],
            },
        },
    )
    result, _profile = edgar_module.parse_filing(entry)

    saved = json.loads((isolated_profiles / "NVDA.json").read_text())["profiles"]["2024"]
    assert result.profile_used == "relearned"
    assert result.parse_status == "parsed"
    assert saved["segmentation"]["rules"][0]["font_size"] != 99.0
