"""Exercise manifest identity, source integrity, and generated schema contracts."""

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path

from pydantic import ValidationError
import pytest

from app.ingestion.manifest import Manifest, SourceArtifact


def manifest_payload():
    """Return a complete acquired SEC filing with an explicit selection."""
    return {
        "corpus": {"corpus_id": "acceptance", "name": "Acceptance filings"},
        "documents": [
            {
                "document_id": "NVDA-FY2024",
                "registry": "sec",
                "language": "en",
                "issuer": "NVDA",
                "issuer_id": "0001045810",
                "filing_id": "0001045810-24-000029",
                "fiscal_year": 2024,
                "form": "10-K",
                "filing_date": "2024-02-21",
                "report_period": "2024-01-28",
                "source_url": "https://www.sec.gov/filing",
                "sec": {
                    "cik": "0001045810",
                    "accession": "0001045810-24-000029",
                    "primary_document": "nvda.htm",
                },
            }
        ],
        "artifacts": [
            {
                "artifact_id": "nvda-source",
                "document_id": "NVDA-FY2024",
                "role": "primary",
                "path": "sec/nvda.htm",
                "sha256": hashlib.sha256(b"source").hexdigest(),
                "byte_length": 6,
                "encoding": "utf-8",
                "acquisition": {
                    "acquired_at": datetime.now(UTC).isoformat(),
                    "url": "https://www.sec.gov/filing",
                    "media_type": "text/html",
                },
            }
        ],
        "selections": [{"selection_id": "tutorial", "artifact_ids": ["nvda-source"]}],
    }


def test_roundtrip_and_source_verification(tmp_path):
    """Publication and source decoding preserve the validated manifest."""
    manifest = Manifest.model_validate(manifest_payload())
    path = tmp_path / "manifest.json"
    manifest.write(path)
    assert path.stat().st_mode & 0o044 == 0o044
    assert Manifest.read(path) == manifest
    (tmp_path / "sec").mkdir()
    source = tmp_path / "sec/nvda.htm"
    source.write_bytes(b"source")
    assert manifest.artifacts[0].read(tmp_path) == "source"
    source.write_bytes(b"change")
    with pytest.raises(ValueError, match="bytes disagree"):
        manifest.artifacts[0].read(tmp_path)


@pytest.mark.parametrize(
    "path", ["/tmp/source", "../source", "a/../b", "a//b", "./a", "C:/a", "a\\b"]
)
def test_unsafe_paths_rejected(path):
    """Serialized paths cannot escape or ambiguously identify the corpus."""
    payload = manifest_payload()["artifacts"][0]
    payload["path"] = path
    with pytest.raises(ValidationError, match="corpus-relative"):
        SourceArtifact.model_validate(payload)


def test_symlink_escape_rejected(tmp_path):
    """A syntactically safe path cannot resolve outside its corpus."""
    root = tmp_path / "corpus"
    root.mkdir()
    (tmp_path / "nvda.htm").write_bytes(b"source")
    (root / "sec").symlink_to(tmp_path, target_is_directory=True)
    artifact = Manifest.model_validate(manifest_payload()).artifacts[0]
    with pytest.raises(ValueError, match="outside"):
        artifact.read(root)


@pytest.mark.parametrize("mutation", ["duplicate", "dangling", "registry", "selection", "legacy"])
def test_invalid_references_rejected(mutation):
    """Disconnected and ambiguous manifest contracts fail before processing."""
    payload = manifest_payload()
    if mutation == "duplicate":
        payload["documents"].append(payload["documents"][0])
    elif mutation == "dangling":
        payload["artifacts"][0]["document_id"] = "unknown"
    elif mutation == "registry":
        payload["documents"][0]["registry"] = "dart"
    elif mutation == "selection":
        payload["selections"][0]["artifact_ids"] = ["unknown"]
    else:
        payload["schema_version"] = 2
    with pytest.raises(ValidationError):
        Manifest.model_validate(payload)


def test_generated_schema_matches_python():
    """The published schema is generated from the exact Python contract."""
    schema_path = Path(__file__).resolve().parents[2] / "schemas/manifest.schema.json"
    assert json.loads(schema_path.read_text()) == Manifest.model_json_schema()


def test_mixed_registry_selection_is_exact(tmp_path):
    """Mixed catalogs resolve only selected documents without derived manifests."""
    payload = manifest_payload()
    payload["documents"].append(
        {
            "document_id": "005930-FY2024",
            "registry": "dart",
            "language": "ko",
            "issuer": "005930",
            "issuer_id": "00126380",
            "filing_id": "20250311001085",
            "fiscal_year": 2024,
            "form": "annual_report",
            "filing_date": "2025-03-11",
            "report_period": "2024-12-31",
            "source_url": "https://dart.fss.or.kr/report",
            "dart": {
                "corp_code": "00126380",
                "receipt_number": "20250311001085",
                "report_code": "11011",
                "report_name": "사업보고서",
            },
        }
    )
    manifest = Manifest.model_validate(payload)
    selected = manifest.selected_sources("tutorial", tmp_path)
    assert [source.document.document_id for source in selected] == ["NVDA-FY2024"]
    assert Manifest.model_validate_json(manifest.model_dump_json()) == manifest
    with pytest.raises(ValueError, match="unknown processing selection"):
        manifest.selected_sources("missing", tmp_path)


def test_failed_publish_preserves_manifest(tmp_path, monkeypatch):
    """A failed atomic replacement retains the prior destination bytes."""
    manifest = Manifest.model_validate(manifest_payload())
    path = tmp_path / "manifest.json"
    path.write_text("existing")

    def fail_replace(*args):
        """Simulate a filesystem publication error."""
        raise OSError("publication failed")

    monkeypatch.setattr("app.ingestion.manifest.os.replace", fail_replace)
    with pytest.raises(OSError, match="publication failed"):
        manifest.write(path)
    assert path.read_text() == "existing"
    assert list(tmp_path.iterdir()) == [path]
