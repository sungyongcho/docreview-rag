"""Company labels use explicit manifest names and preserve unknown issuer identity."""

import json
from pathlib import Path

from app.ingestion.company_names import company_names_from_entries, read_company_names


def test_company_names_use_manifest_metadata_without_guessing_codes() -> None:
    """SEC aliases and DART official names label their own registry identity only."""
    names = company_names_from_entries(
        [
            {"ticker": "NVDA", "aliases": ["NVDA", "NVIDIA", "NVIDIA Corporation"]},
            {"ticker": "UNKNOWN", "aliases": ["UNKNOWN", "unknown"]},
            {
                "registry": "dart",
                "issuer": "005930",
                "corp_name": "삼성전자",
                "aliases": ["Samsung Electronics", "005930"],
            },
            {"registry": "dart", "issuer": "000660", "aliases": ["SK하이닉스", "000660"]},
        ]
    )
    assert names == {
        ("sec", "NVDA"): "NVIDIA",
        ("dart", "005930"): "삼성전자",
        ("dart", "000660"): "SK하이닉스",
    }
    assert names.get(("dart", "NVDA")) is None


def test_conflicting_company_names_are_not_assigned_to_a_code() -> None:
    """Conflicting source metadata cannot silently name the wrong company."""
    assert (
        company_names_from_entries(
            [
                {"ticker": "SAME", "aliases": ["SAME", "First Company"]},
                {"ticker": "SAME", "aliases": ["SAME", "Second Company"]},
            ]
        )
        == {}
    )


def test_company_names_refresh_optional_manifest_metadata(tmp_path: Path, caplog) -> None:
    """New acquisition metadata appears without retaining stale names or hiding read errors."""
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps([{"ticker": "NVDA", "aliases": ["NVDA", "NVIDIA"]}]))
    assert read_company_names(tmp_path) == {("sec", "NVDA"): "NVIDIA"}
    path.write_text("[]")
    assert read_company_names(tmp_path) == {}
    path.write_text("broken JSON")
    assert read_company_names(tmp_path) == {}
    assert "Company labels unavailable for manifest.json (JSONDecodeError)" in caplog.text
