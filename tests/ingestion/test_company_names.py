"""Optional display labels come only from common manifest document aliases."""

from app.ingestion.company_names import company_names_from_entries, read_company_names
from app.ingestion.manifest import CorpusIdentity, Manifest
from tests.ingestion.support import filing_document


def test_company_names_use_explicit_aliases_without_guessing_codes():
    """Keep official source labels scoped to their publishing registry."""
    documents = [
        filing_document(aliases=("NVDA", "NVIDIA")),
        filing_document(issuer="UNKNOWN", aliases=("UNKNOWN", "unknown")),
        filing_document(registry="dart", aliases=("삼성전자", "Samsung Electronics")),
    ]
    assert company_names_from_entries(documents) == {
        ("sec", "NVDA"): "NVIDIA",
        ("dart", "005930"): "삼성전자",
    }


def test_conflicting_company_names_are_not_assigned_to_a_code():
    """Refuse an ambiguous alias shared by repeated issuer metadata."""
    assert (
        company_names_from_entries(
            [
                filing_document(aliases=("First Company",)),
                filing_document(aliases=("Second Company",)),
            ]
        )
        == {}
    )


def test_optional_company_names_refresh_and_report_invalid_catalog(tmp_path, caplog):
    """Read current aliases from one manifest and report unavailable metadata."""
    path = tmp_path / "manifest.json"
    catalog = Manifest(
        corpus=CorpusIdentity(corpus_id="test", name="Test"),
        documents=(filing_document(aliases=("NVIDIA",)),),
    )
    catalog.write(path)
    assert read_company_names(tmp_path) == {("sec", "NVDA"): "NVIDIA"}
    Manifest(corpus=catalog.corpus).write(path)
    assert read_company_names(tmp_path) == {}
    path.write_text("[]")
    assert read_company_names(tmp_path) == {}
    assert "Company labels unavailable" in caplog.text
