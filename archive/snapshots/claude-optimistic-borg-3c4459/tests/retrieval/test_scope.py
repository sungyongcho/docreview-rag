"""Manifest alias and query-scope regression tests."""

import pytest

from app.retrieval.scope import ManifestScopeIndex, QueryScopeError, resolve_query_scope
from app.retrieval.types import RetrievalFilters

ENTRIES = (
    {
        "ticker": "NVDA",
        "report_date": "2024-01-28",
        "aliases": ["NVDA", "NVIDIA", "NVIDIA Corporation"],
    },
    {
        "registry": "dart",
        "issuer": "005930",
        "fiscal_year": 2024,
        "form": "사업보고서",
        "aliases": ["삼성전자", "Samsung Electronics", "005930"],
    },
    {
        "registry": "dart",
        "issuer": "000660",
        "fiscal_year": 2024,
        "form": "사업보고서",
        "aliases": ["SK하이닉스", "SK hynix", "000660"],
    },
)


def index() -> ManifestScopeIndex:
    """Return the minimal mixed-registry alias index."""
    return ManifestScopeIndex.from_entries(ENTRIES)


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
        {
            "ticker": "AMD",
            "report_date": "2024-01-01",
            "aliases": ["nvidia"],
        },
    )

    with pytest.raises(ValueError, match="maps to both"):
        ManifestScopeIndex.from_entries(conflicting)
