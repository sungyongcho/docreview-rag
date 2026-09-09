"""Preparation counts expose fixed aggregates without changing publication boundaries."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
import pytest

from app.api.app import create_api_app
from app.api.deps import get_api_services
from app.api.errors import ApiProblemError
from app.api.public_portfolio import PublicPortfolioReader


def _source(issuer="NVDA", year=2024, ready=True):
    """Include sensitive metadata to prove the projection never returns source DTOs."""
    return SimpleNamespace(
        registry="sec",
        issuer=issuer,
        fiscal_year=year,
        ready=ready,
        document_id="private-doc-id",
        blocker="/private/source/path",
    )


def _document(issuer="NVDA", year=2024):
    """Model an existing catalog row with exact active-provider counts."""
    return SimpleNamespace(
        registry="sec",
        issuer=issuer,
        fiscal_year=year,
        parse_status="parsed",
        chunk_count=10,
        embedded_chunks=6,
        doc_id="unpublished-secret",
        body="private",
    )


def _reader(*, schema="compatible", valid=True):
    """Only read methods exist on these independent corpus and catalog seams."""
    corpus = SimpleNamespace(
        snapshot=AsyncMock(
            return_value=SimpleNamespace(
                status=SimpleNamespace(database_connected=True, schema_status=schema),
                manifests=[SimpleNamespace(valid=valid)],
                sources=[_source(), _source("OTHER")],
            )
        )
    )
    catalog = SimpleNamespace(
        documents=AsyncMock(
            return_value=SimpleNamespace(
                documents=[_document(), _document("OTHER"), _document(year=2025)],
                next_cursor=None,
            )
        )
    )
    return PublicPortfolioReader(corpus, catalog), corpus, catalog


def test_fixed_pairs_project_only_counts_and_cache_reads():
    """Unpublished metadata may contribute counts but no identities or contents escape."""
    reader, corpus, catalog = _reader()

    async def exercise():
        """Read twice within one cache period."""
        first = await reader.read()
        second = await reader.read()
        return first, second

    first, second = asyncio.run(exercise())
    assert first is second
    assert len(first.pairs) == 18
    row = next(row for row in first.pairs if row.issuer == "NVDA" and row.fiscal_year == 2024)
    assert (
        row.source_documents,
        row.parsed_documents,
        row.chunks,
        row.embedded_chunks,
        row.pending_embeddings,
    ) == (1, 1, 10, 6, 4)
    assert sum(row.chunks for row in first.pairs) == 10
    payload = first.model_dump_json()
    for private in ("OTHER", "private", "unpublished", "doc_id", "body", "path"):
        assert private not in payload
    assert corpus.snapshot.await_count == catalog.documents.await_count == 1


@pytest.mark.parametrize(
    "schema,valid", [("unavailable", True), ("incompatible", True), ("compatible", False)]
)
def test_unknown_preparation_is_not_zero(schema, valid):
    """Schema or manifest problems return unavailable before projection."""
    reader, _, catalog = _reader(schema=schema, valid=valid)
    with pytest.raises(ApiProblemError) as caught:
        asyncio.run(reader.read())
    assert caught.value.status_code == 503
    catalog.documents.assert_not_awaited()


def test_catalog_pages_are_counted_and_overflow_is_not_truncated():
    """A complete bounded traversal sums both pages and refuses unfinished scans."""
    reader, _, catalog = _reader()
    catalog.documents.side_effect = [
        SimpleNamespace(documents=[_document()], next_cursor="next"),
        SimpleNamespace(documents=[_document(year=2023)], next_cursor=None),
    ]
    result = asyncio.run(reader.read())
    assert sum(row.chunks for row in result.pairs) == 20
    assert catalog.documents.await_args_list[1].kwargs["cursor"] == "next"
    reader, _, catalog = _reader()
    catalog.documents.return_value.next_cursor = "still-more"
    with pytest.raises(ApiProblemError) as caught:
        asyncio.run(reader.read())
    assert caught.value.status_code == 503
    assert catalog.documents.await_count == 10


def test_public_route_has_exact_schema_and_no_canned_success():
    """The metadata route exists independently of the protected document catalog."""
    application = create_api_app()
    application.dependency_overrides[get_api_services] = lambda: object()
    with TestClient(application) as client:
        response = client.get("/public/portfolio/preparation")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "portfolio_preparation_unavailable"
    schema = application.openapi()["components"]["schemas"]["PublicPortfolioPreparationPair"]
    assert set(schema["properties"]) == {
        "registry",
        "issuer",
        "fiscal_year",
        "source_documents",
        "parsed_documents",
        "chunks",
        "embedded_chunks",
        "pending_embeddings",
    }
