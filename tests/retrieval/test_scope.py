"""Manifest alias and query-scope regression tests."""

from datetime import date
from typing import Literal

import pytest

from app.ingestion.manifest import DartMetadata, DocumentReference, SecMetadata
from app.retrieval.scope import ManifestScopeIndex, QueryScopeError, resolve_query_scope
from app.retrieval.types import RetrievalFilters


def _document(
    registry: Literal["sec", "dart"],
    issuer: str,
    issuer_id: str,
    filing_id: str,
    aliases: tuple[str, ...],
) -> DocumentReference:
    """Construct current common filing metadata for the alias scope fixtures."""
    return DocumentReference(
        document_id=f"{issuer}-FY2024",
        registry=registry,
        language="en" if registry == "sec" else "ko",
        issuer=issuer,
        issuer_id=issuer_id,
        filing_id=filing_id,
        fiscal_year=2024,
        form="10-K" if registry == "sec" else "사업보고서",
        filing_date=date(2024, 2, 21) if registry == "sec" else date(2025, 3, 11),
        report_period=date(2024, 1, 28) if registry == "sec" else date(2024, 12, 31),
        source_url=f"https://example.test/{filing_id}",
        aliases=aliases,
        sec=SecMetadata(cik=issuer_id, accession=filing_id, primary_document="report.htm")
        if registry == "sec"
        else None,
        dart=DartMetadata(
            corp_code=issuer_id,
            receipt_number=filing_id,
            report_code="11011",
            report_name="사업보고서 (2024.12)",
        )
        if registry == "dart"
        else None,
    )


ENTRIES = (
    _document(
        "sec",
        "NVDA",
        "0001045810",
        "0001045810-24-000029",
        ("NVDA", "NVIDIA", "NVIDIA Corporation"),
    ),
    _document(
        "dart",
        "005930",
        "00126380",
        "20250311001085",
        ("삼성전자", "Samsung Electronics", "005930"),
    ),
    _document("dart", "000660", "00164779", "20250319000665", ("SK하이닉스", "SK hynix", "000660")),
)


def index() -> ManifestScopeIndex:
    """Return the minimal mixed-registry alias index."""
    return ManifestScopeIndex.from_entries(ENTRIES)


def test_display_name_resolves_only_when_that_company_has_documents() -> None:
    """Reuse approved display names for present issuers without admitting absent catalog entries."""
    entry = ENTRIES[0].model_copy(update={"aliases": ("NVDA", "NVIDIA CORP")})
    scope_index = ManifestScopeIndex.from_entries((entry,))
    assert [item.issuer for item in scope_index.named_target("NVIDIA")] == ["NVDA"]
    assert resolve_query_scope("NVIDIA's revenue", scope_index).filters.issuers == ("NVDA",)
    assert scope_index.named_target("Intel") == ()
    assert scope_index.named_target("SanDisk") == ()
    assert scope_index.named_target("NVIDIA competitor") == ()


@pytest.mark.parametrize("alias", ["삼성전자", "Samsung Electronics", "005930"])
def test_samsung_aliases_resolve_to_dart_korean(alias: str) -> None:
    """Resolve every committed Samsung spelling to one canonical corpus scope."""
    scope = resolve_query_scope(f"{alias} 매출", index())

    assert scope.source == "alias"
    assert scope.filters.issuers == ("005930",)
    assert scope.filters.registries == ("dart",)
    assert scope.filters.languages == ("ko",)


def test_multiple_issuers_and_scripts_remain_multiple() -> None:
    """Keep Korean and English lexical lanes for a cross-registry comparison."""
    scope = resolve_query_scope("삼성전자와 NVIDIA revenue 비교", index())

    assert scope.filters.issuers == ("005930", "NVDA")
    assert scope.filters.registries == ("dart", "sec")
    assert scope.filters.languages == ("en", "ko")


def test_explicit_issuer_suppresses_query_aliases() -> None:
    """Honor an explicit drawer company without silently adding a query company."""
    scope = resolve_query_scope(
        "삼성전자와 비교",
        index(),
        explicit_filters=RetrievalFilters(issuers=("NVDA",)),
    )

    assert scope.source == "explicit"
    assert scope.filters.issuers == ("NVDA",)
    assert tuple(match.issuer for match in scope.suppressed_aliases) == ("005930",)


def test_explicit_corpus_rejects_alias_from_another_registry() -> None:
    """Refuse a DART issuer under explicit SEC scope instead of widening retrieval."""
    with pytest.raises(QueryScopeError, match="outside the selected corpus") as caught:
        resolve_query_scope("삼성전자 매출", index(), corpus_scope="sec")

    assert caught.value.code == "query_scope_conflict"


def test_alias_free_query_uses_every_visible_script() -> None:
    """Fall back to both script languages when no company alias is present."""
    scope = resolve_query_scope("메모리 revenue trend", index())

    assert scope.source == "query_language"
    assert scope.filters.languages == ("en", "ko")


def test_normalized_alias_conflict_is_rejected() -> None:
    """Reject an ambiguous alias before it can route a user to the wrong issuer."""
    conflicting = (
        *ENTRIES,
        _document("sec", "AMD", "0000002488", "0000002488-24-000012", ("nvidia",)),
    )

    with pytest.raises(ValueError, match="maps to both"):
        ManifestScopeIndex.from_entries(conflicting)


def test_same_issuer_filings_merge_acquired_and_existing_aliases() -> None:
    """An acquired official name must not disable routing for the entire corpus."""
    older = _document(
        "sec", "INTC", "0000050863", "0000050863-24-000010", ("INTC", "Intel", "Intel Corporation")
    ).model_copy(update={"document_id": "INTC-FY2023", "fiscal_year": 2023})
    newer = _document("sec", "INTC", "0000050863", "0000050863-25-000009", ("intc", "INTEL CORP"))
    merged = ManifestScopeIndex.from_entries((*ENTRIES, older, newer))
    intel = next(item for item in merged.issuers if item.issuer == "INTC")
    assert intel.aliases == ("INTC", "Intel", "INTEL CORP", "Intel Corporation")
    for alias in ("INTC", "Intel Corporation", "INTEL CORP"):
        assert resolve_query_scope(f"{alias} revenue", merged).filters.issuers == ("INTC",)
    assert resolve_query_scope(
        "What drove NVIDIA data center revenue growth?", merged
    ).filters.issuers == ("NVDA",)
    assert merged.documents[older.document_id].fiscal_year == 2023
    assert merged.documents[newer.document_id].fiscal_year == 2024


def test_merged_aliases_still_reject_a_different_canonical_owner() -> None:
    """Merging one issuer's aliases never authorizes ambiguous cross-issuer routing."""
    older = ENTRIES[0]
    newer = older.model_copy(
        update={"document_id": "NVDA-FY2023", "aliases": ("NVDA", "Shared name")}
    )
    other = _document("sec", "INTC", "0000050863", "0000050863-25-000009", ("INTC", "shared NAME"))
    with pytest.raises(ValueError, match="maps to both"):
        ManifestScopeIndex.from_entries((older, newer, other))


def test_alias_union_does_not_accept_duplicates_inside_one_filing() -> None:
    """Only equivalent names across filings are deduplicated; malformed entries still fail."""
    malformed = ENTRIES[0].model_copy(update={"aliases": ("NVIDIA", " nvidia ")})
    with pytest.raises(ValueError, match="normalized duplicate"):
        ManifestScopeIndex.from_entries((malformed,))
