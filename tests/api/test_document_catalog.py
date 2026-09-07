"""Published inventory contracts against an explicitly isolated PostgreSQL database."""

import asyncio
import hashlib
import os
from uuid import uuid4

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.document_catalog import DocumentCatalog, public_source_url
from app.api.runtime import RuntimeApiServices
from app.corpus_admin import CHUNK_PREVIEW_CHARS, CHUNK_PREVIEW_LIMIT
from app.db.models import (
    Base,
    Chunk,
    ChunkEmbedding,
    Corpus,
    Document,
    DocumentParse,
    EvalResult,
    EvaluationSnapshot,
    ParsedStructure,
    SnapshotDocument,
    SourceArtifact,
)
from app.retrieval.embeddings import DeterministicEmbeddingProvider, EmbeddingIdentity
from tests.ingestion.support import filing_document
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
                session.add(Corpus(corpus_id="catalog", name="Catalog test"))
                await session.flush()
                for index, name in enumerate(("published", "private", "archived", "changed"), 1):
                    reference = filing_document(
                        registry="dart" if name == "private" else "sec",
                        issuer=name,
                        document_id=name,
                        fiscal_year=2020 + index,
                        filing_id="20250311001085"
                        if name == "private"
                        else f"0001045810-24-{index:06d}",
                    )
                    metadata = reference.model_dump(mode="json")
                    metadata.pop("document_id")
                    metadata["source_url"] = "/home/private/source.html"
                    session.add(Document(doc_id=name, **metadata))
                    await session.flush()
                    session.add(
                        SourceArtifact(
                            corpus_id="catalog",
                            artifact_id=name,
                            doc_id=name,
                            role="primary",
                            path=f"{name}.html",
                            sha256=str(index) * 64,
                            byte_length=100,
                            encoding="utf-8",
                            acquisition={},
                        )
                    )
                    await session.flush()
                    session.add(
                        ParsedStructure(
                            structure_id=str(index) * 64,
                            corpus_id="catalog",
                            artifact_id=name,
                            artifact_sha256=str(index) * 64,
                            parser_identity="catalog-test",
                            source_sha256=str(index) * 64,
                            source_length=100,
                            structure={},
                            parse_status="parsed",
                            item_index=[],
                        )
                    )
                    await session.flush()
                    session.add(DocumentParse(doc_id=name, structure_id=str(index) * 64))
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
                            stable_key=hashlib.sha256(f"published:{ordinal}".encode()).hexdigest(),
                            structure_id="1" * 64,
                            index_text_sha256=hashlib.sha256(body.encode()).hexdigest(),
                            index_text=body,
                            start_char=ordinal,
                            end_char=ordinal + len(body),
                            source_sha256="1" * 64,
                            citation="Published filing, Item 1A",
                        )
                    )
                await session.flush()
                first_chunk = await session.scalar(select(Chunk).order_by(Chunk.id).limit(1))
                assert first_chunk is not None
                for model, tokenizer, input_hash in (
                    ("catalog", "cl100k_base", first_chunk.index_text_sha256),
                    ("other-model", "cl100k_base", first_chunk.index_text_sha256),
                    ("catalog", "other-tokenizer", first_chunk.index_text_sha256),
                    ("catalog", "cl100k_base", "e" * 64),
                ):
                    session.add(
                        ChunkEmbedding(
                            chunk_id=first_chunk.id,
                            input_sha256=input_hash,
                            provider="test",
                            model=model,
                            dimensions=384,
                            tokenizer=tokenizer,
                            embedding=[1.0, *([0.0] * 383)],
                        )
                    )
                await session.commit()
            catalog = DocumentCatalog(
                factory,
                public_only=True,
                embedding_identity=EmbeddingIdentity("test", "catalog", 384, "cl100k_base"),
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
            runtime = RuntimeApiServices(
                session_factory=factory, embedding_provider=DeterministicEmbeddingProvider()
            )
            runtime_documents = await runtime.list_documents()
            assert len(runtime_documents) == 4
            assert all(
                document.parse_status == "parsed" and document.source_length == 100
                for document in runtime_documents
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
            assert [(value.value, value.count) for value in facets.sections] == [("1A", 1)]
            assert [value.value for value in facets.snapshots] == [str(published_id)]
            assert (await catalog.document_facets(registry="sec")) == facets
            hidden_facets = await catalog.document_facets("dart")
            assert all(not values for values in hidden_facets.model_dump().values())
            admin_facets = await DocumentCatalog(
                factory,
                public_only=False,
                embedding_identity=EmbeddingIdentity("test", "catalog", 384, "cl100k_base"),
            ).document_facets("dart")
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
            assert detail.embedded_chunks == 1
            assert len(detail.embedding_identities) == 1
            assert detail.embedding_identities[0].model == "catalog"
            assert detail.embedding_identities[0].tokenizer == "cl100k_base"
            assert detail.embedding_identities[0].count == 1
            assert page.documents[0].embedded_chunks == 1
            assert page.documents[0].embedding_status == "partial"
            assert detail.item_counts[0].count == CHUNK_PREVIEW_LIMIT + 1
            assert [membership.snapshot_id for membership in detail.snapshot_memberships] == [
                published_id
            ]
            for name in ("private", "archived", "changed", "missing"):
                assert await catalog.document_detail(name) is None
            assert (
                await DocumentCatalog(
                    factory,
                    public_only=False,
                    embedding_identity=EmbeddingIdentity("test", "catalog", 384, "cl100k_base"),
                ).documents(**parameters)
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


@pytest.mark.parametrize("operation", ["documents", "document_facets", "document_detail"])
def test_catalog_rejects_drift_before_data_queries(monkeypatch, operation):
    """All catalog entry points fail with a typed error before querying missing ORM objects."""
    from unittest.mock import AsyncMock, Mock

    import app.api.document_catalog as module
    from app.api.errors import ApiProblemError
    from app.db.bootstrap import SchemaDriftError

    session = AsyncMock()
    session.__aenter__.return_value = session
    monkeypatch.setattr(
        module,
        "ensure_complete_schema",
        AsyncMock(side_effect=SchemaDriftError("missing chunk_embeddings")),
    )
    catalog = DocumentCatalog(
        Mock(return_value=session),
        public_only=False,
        embedding_identity=EmbeddingIdentity("deterministic", "test", 384, "test"),
    )
    if operation == "documents":
        pending = catalog.documents(
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
            limit=10,
        )
    elif operation == "document_detail":
        pending = catalog.document_detail("test")
    else:
        pending = catalog.document_facets()
    with pytest.raises(ApiProblemError) as error:
        asyncio.run(pending)
    assert error.value.status_code == 503
    assert error.value.error.code == "schema_not_ready"
    session.execute.assert_not_called()
    session.scalar.assert_not_called()
