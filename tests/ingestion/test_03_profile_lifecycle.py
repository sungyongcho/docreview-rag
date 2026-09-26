"""Profile learning, persistence, and convergence over repeated corpus passes."""

import json
from pathlib import Path
from types import ModuleType

from app.ingestion.sources.models import FilingSource
from tests.ingestion.support import copy_filing_source


# Repeated learning and failed-profile recovery
def test_profiles_converge_on_the_third_corpus_pass(
    edgar_module: ModuleType,
    manifest: tuple[FilingSource, ...],
    tmp_path: Path,
) -> None:
    """Converge after missing historical years self-heal across three passes."""
    amd = sorted(
        (
            copy_filing_source(entry, tmp_path)
            for entry in manifest
            if entry.document.issuer == "AMD"
        ),
        key=lambda entry: entry.document.report_period,
    )
    passes = []
    for _ in range(3):
        used = {}
        for entry in amd:
            result, _profile = edgar_module.parse_filing(entry)
            assert result.parse_status == "parsed", (
                f"{result.source.document.document_id}: parse warnings {result.warnings}"
            )
            used[result.source.document.fiscal_year] = result.profile_used
        passes.append(used)

    assert passes[0] == {
        2019: "bootstrap",
        2020: "saved",
        2021: "relearned",
        2022: "saved",
        2023: "relearned",
        2024: "saved",
    }
    assert passes[1] == {
        2019: "saved",
        2020: "relearned",
        2021: "saved",
        2022: "relearned",
        2023: "saved",
        2024: "saved",
    }
    assert passes[2] == dict.fromkeys(range(2019, 2025), "saved")
    saved = json.loads((tmp_path / "sec/AMD/profile.json").read_text())
    assert saved["issuer"] == "AMD"
    assert saved["default_year"] == "2023"


def test_failed_profile_is_relearned_before_it_is_saved(
    edgar_module: ModuleType,
    manifest: tuple[FilingSource, ...],
    tmp_path: Path,
) -> None:
    """Persist only a profile that successfully reparses and validates the filing."""
    entry = next(
        item
        for item in manifest
        if item.document.issuer == "NVDA" and item.document.fiscal_year == 2024
    )
    entry = copy_filing_source(entry, tmp_path / "corpus")
    profile_path = entry.corpus_root / "sec/NVDA/profile.json"
    invalid_profile = {
        "segmentation": {"type": "number", "rules": [{"font_size": 99.0}]},
        "validation": {"expected_items": 23, "must_have": ["1", "1A", "7", "8"]},
    }
    edgar_module.save_profile(profile_path, "NVDA", 2024, invalid_profile)
    other_issuer = entry.corpus_root / "sec/AMD/profile.json"
    other_corpus = tmp_path / "other-corpus/sec/NVDA/profile.json"
    edgar_module.save_profile(other_issuer, "AMD", 2024, invalid_profile)
    edgar_module.save_profile(other_corpus, "NVDA", 2024, invalid_profile)
    unrelated = {path: path.read_bytes() for path in (other_issuer, other_corpus)}

    result, _profile = edgar_module.parse_filing(entry)

    saved = json.loads(profile_path.read_text())["profiles"]["2024"]
    assert result.profile_used == "relearned"
    assert result.parse_status == "parsed"
    assert saved["segmentation"]["rules"][0]["font_size"] != 99.0
    assert {path: path.read_bytes() for path in unrelated} == unrelated
