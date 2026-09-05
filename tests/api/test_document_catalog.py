"""Published inventory contracts against an explicitly isolated PostgreSQL database."""

import asyncio
import os
from uuid import uuid4

import pytest
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.document_catalog import DocumentCatalog, public_source_url
from app.corpus_admin import CHUNK_PREVIEW_CHARS, CHUNK_PREVIEW_LIMIT
from app.db.models import Base, Chunk, Document, EvalResult, EvaluationSnapshot, SnapshotDocument
from tests.live_postgres import live_postgres_unavailable


def test_public_source_url_rejects_local_paths_and_credentials() -> None:
    """Only credential-free absolute web citations cross the public boundary."""
    for value in (
        "/home/operator/secret.html",
        "file:///corpus/a.html",
        "http://user:pass@host/doc",
        "//host/doc",
        "https://opendart.fss.or.kr/api/document.xml?crtfc_key=private-key",
    ):
        assert public_source_url(value) == ""
    assert public_source_url("https://www.sec.gov/doc.html") == "https://www.sec.gov/doc.html"


@pytest.mark.live_postgres
def test_published_catalog_filters_identity_facets_detail_and_private_snapshot() -> None:
    """Public reads exclude hidden, archived, and replaced document revisions."""
    url = os.getenv("DOCREVIEW_CATALOG_TEST_DATABASE_URL")
    if not url:
        live_postgres_unavailable(
            "Set DOCREVIEW_CATALOG_TEST_DATABASE_URL to an isolated database."
        )

    async def exercise() -> None:
        """Create a temporary schema and verify the real SQL visibility predicate."""
        engine = create_async_engine(url)
        schema = f"catalog_test_{uuid4().hex}"
        async with engine.begin() as connection:
            await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            await connection.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
            await connection.run_sync(
                lambda sync_connection: Base.metadata.create_all(sync_connection, checkfirst=False)
            )
        async with engine.connect() as connection:
            await connection.execute(text(f'SET search_path TO "{schema}", public'))
            await connection.commit()
            transaction = await connection.begin()
            factory = async_sessionmaker(
                connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
            )
            async with factory() as session:
                for index, name in enumerate(("published", "private", "archived", "changed"), 1):
                    session.add(
                        Document(
                            doc_id=name,
                            registry="dart" if name == "private" else "sec",
                            language="ko" if name == "private" else "en",
                            issuer=name,
                            issuer_id=name,
                            fiscal_year=2020 + index,
                            form="사업보고서" if name == "private" else "10-K",
                            filing_date="2024-01-01",
                            report_period="2023-12-31",
                            filing_id=name,
                            source_url="/home/private/source.html",
                            parse_status="parsed",
                            item_index=[],
                            source_length=100,
                            source_sha256=str(index) * 64,
                        )
                    )
                    result = EvalResult(
                        suite=name, config={}, metrics={}, raw_artifact_path="/private/eval.json"
                    )
                    session.add(result)
                    await session.flush()
                    snapshot = EvaluationSnapshot(
                        label=name,
                        status="archived" if name == "archived" else "ready",
                        public=name != "private",
                        corpus_fingerprint="a" * 64,
                        profile={},
                        eval_result_id=result.id,
                    )
                    session.add(snapshot)
                    await session.flush()
                    session.add(
                        SnapshotDocument(
                            snapshot_id=snapshot.id,
                            doc_id=name,
                            source_sha256="f" * 64 if name == "changed" else str(index) * 64,
                            chunk_count=0,
                            embedding_fingerprint="a" * 64,
                        )
                    )
                    if name == "private":
                        private_id = snapshot.id
                        session.add(
                            SnapshotDocument(
                                snapshot_id=snapshot.id,
                                doc_id="published",
                                source_sha256="1" * 64,
                                chunk_count=0,
                                embedding_fingerprint="a" * 64,
                            )
                        )
                    if name == "published":
                        published_id = snapshot.id
                for ordinal in range(CHUNK_PREVIEW_LIMIT + 1):
                    body = "published evidence " * CHUNK_PREVIEW_CHARS
                    session.add(
                        Chunk(
                            doc_id="published",
                            language="en",
                            item="1A",
                            kind="text" if ordinal else "table",
                            ordinal=ordinal,
                            body=body,
                            context_header="Published filing",
                            index_text=body,
                            start_char=ordinal,
                            end_char=ordinal + len(body),
                            source_sha256="1" * 64,
                            citation="Published filing, Item 1A",
                        )
                    )
                await session.commit()
            catalog = DocumentCatalog(
                factory,
                public_only=True,
                company_names=lambda: {
                    ("sec", "published"): "Visible Company",
                    ("dart", "private"): "Hidden Company",
                    ("dart", "published"): "Unrelated Registry Company",
                },
            )
            parameters = dict(
                query="",
                registry="",
                issuer="",
                fiscal_year=None,
                language="",
                form="",
                parse_status="",
                embedding_status=None,
                snapshot_id=None,
                sort="doc_id",
                descending=False,
                cursor=None,
                limit=50,
            )
            page = await catalog.documents(**parameters)
            assert [document.doc_id for document in page.documents] == ["published"]
            assert page.total == 1 and page.documents[0].snapshot_count == 1
            assert page.documents[0].source_url == ""
            assert page.documents[0].issuer_name == "Visible Company"
            assert (await catalog.documents(**{**parameters, "snapshot_id": private_id})).total == 0
            assert (await catalog.documents(**{**parameters, "query": "private"})).total == 0
            named_page = await catalog.documents(**{**parameters, "query": "Visible Company"})
            assert named_page.total == 1
            assert (await catalog.documents(**{**parameters, "query": "Hidden Company"})).total == 0
            facets = await catalog.document_facets()
            assert [value.value for value in facets.issuers] == ["published"]
            assert facets.issuers[0].label == "published · Visible Company"
            assert [value.value for value in facets.snapshots] == [str(published_id)]
            assert (await catalog.document_facets(registry="sec")) == facets
            hidden_facets = await catalog.document_facets("dart")
            assert all(not values for values in hidden_facets.model_dump().values())
            admin_facets = await DocumentCatalog(factory, public_only=False).document_facets("dart")
            assert [value.value for value in admin_facets.issuers] == ["private"]
            assert [value.value for value in admin_facets.years] == ["2022"]
            assert [value.value for value in admin_facets.languages] == ["ko"]
            assert [value.value for value in admin_facets.forms] == ["사업보고서"]
            assert admin_facets.snapshots[0].count == 1
            detail = await catalog.document_detail("published")
            assert detail is not None and detail.document.source_url == ""
            assert detail.document.issuer_name == "Visible Company"
            assert detail.document.chunk_count == CHUNK_PREVIEW_LIMIT + 1
            assert len(detail.chunks) == CHUNK_PREVIEW_LIMIT
            assert all(len(chunk.body) == CHUNK_PREVIEW_CHARS for chunk in detail.chunks)
            assert detail.text_chunks == CHUNK_PREVIEW_LIMIT and detail.table_chunks == 1
            assert detail.embedded_chunks == 0 and not detail.embedding_identities
            assert detail.item_counts[0].count == CHUNK_PREVIEW_LIMIT + 1
            assert [membership.snapshot_id for membership in detail.snapshot_memberships] == [
                published_id
            ]
            for name in ("private", "archived", "changed", "missing"):
                assert await catalog.document_detail(name) is None
            assert (
                await DocumentCatalog(factory, public_only=False).documents(**parameters)
            ).total == 4
            async with factory() as session:
                await session.execute(
                    update(EvaluationSnapshot)
                    .where(EvaluationSnapshot.id == published_id)
                    .values(public=False)
                )
                await session.commit()
            assert (await catalog.documents(**parameters)).total == 0
            assert not (await catalog.document_facets()).issuers
            assert await catalog.document_detail("published") is None
            await transaction.rollback()
        await engine.dispose()

    asyncio.run(exercise())
