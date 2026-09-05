"""Shared read-only document catalog with exact published-source visibility."""

from __future__ import annotations

import base64
from collections.abc import Callable
from urllib.parse import urlsplit

from sqlalchemy import Float, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement

from app.api.admin_schemas import (
    AdminDocumentResource,
    DocumentDetailResponse,
    DocumentEmbeddingStatus,
    DocumentFacetsResponse,
    DocumentFacetValue,
    DocumentInventoryResponse,
    DocumentSort,
)
from app.corpus_admin import CHUNK_PREVIEW_CHARS, CHUNK_PREVIEW_LIMIT
from app.db.models import Chunk, Document, EvaluationSnapshot, SnapshotDocument
from app.ingestion.company_names import CompanyNames
from app.observability.persistence import redact_sensitive_text


def public_source_url(value: str) -> str:
    """Return a web citation only when it contains no local path or credentials."""
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme in {"http", "https"}
            and parsed.hostname
            and not parsed.username
            and not parsed.password
        ):
            return value if redact_sensitive_text(value) == value else ""
    except ValueError:
        pass
    return ""


class DocumentCatalog:
    """Share inventory queries while keeping public visibility mandatory per instance."""

    def __init__(
        self,
        session_factory: Callable[[], AsyncSession],
        *,
        public_only: bool,
        company_names: Callable[[], CompanyNames] = dict,
    ) -> None:
        """Bind the caller's session factory and immutable catalog visibility."""
        self._session_factory = session_factory
        self._public_only = public_only
        self._company_names = company_names

    def _snapshot_filters(self) -> tuple[ColumnElement[bool], ...]:
        """Restrict the public surface to explicitly published ready snapshots."""
        return (
            (EvaluationSnapshot.public.is_(True), EvaluationSnapshot.status == "ready")
            if self._public_only
            else ()
        )

    def _published_identity(self) -> ColumnElement[bool]:
        """Match both document identity and source hash to avoid exposing later revisions."""
        return (
            select(SnapshotDocument.doc_id)
            .join(EvaluationSnapshot, EvaluationSnapshot.id == SnapshotDocument.snapshot_id)
            .where(
                SnapshotDocument.doc_id == Document.doc_id,
                SnapshotDocument.source_sha256 == Document.source_sha256,
                *self._snapshot_filters(),
            )
            .exists()
        )

    def _document_filters(self) -> tuple[ColumnElement[bool], ...]:
        """Apply the same visibility predicate to every public aggregate."""
        return (self._published_identity(),) if self._public_only else ()

    async def documents(
        self,
        *,
        query: str,
        registry: str,
        issuer: str,
        fiscal_year: int | None,
        language: str,
        form: str,
        parse_status: str,
        embedding_status: DocumentEmbeddingStatus | None,
        snapshot_id: int | None,
        sort: DocumentSort,
        descending: bool,
        cursor: str | None,
        limit: int,
    ) -> DocumentInventoryResponse:
        """Return one filtered, sortable, opaque-cursor document page."""
        names = self._company_names()
        filters = [self._published_identity()] if self._public_only else []
        if query:
            pattern = f"%{query.strip()}%"
            matching_companies = [
                (Document.registry == registry_name) & (Document.issuer == code)
                for (registry_name, code), name in names.items()
                if query.strip().casefold() in name.casefold()
            ]
            filters.append(
                or_(
                    Document.doc_id.ilike(pattern),
                    Document.issuer.ilike(pattern),
                    *matching_companies,
                )
            )
        for column, value in (
            (Document.registry, registry),
            (Document.issuer, issuer),
            (Document.language, language),
            (Document.form, form),
            (Document.parse_status, parse_status),
        ):
            if value:
                filters.append(column == value)
        if fiscal_year is not None:
            filters.append(Document.fiscal_year == fiscal_year)
        if snapshot_id is not None:
            filters.append(
                select(SnapshotDocument.doc_id)
                .join(EvaluationSnapshot, EvaluationSnapshot.id == SnapshotDocument.snapshot_id)
                .where(
                    *self._snapshot_filters(),
                    SnapshotDocument.snapshot_id == snapshot_id,
                    SnapshotDocument.doc_id == Document.doc_id,
                    SnapshotDocument.source_sha256 == Document.source_sha256,
                )
                .exists()
            )
        offset = 0
        if cursor:
            try:
                offset = int(base64.urlsafe_b64decode(cursor.encode()).decode())
            except (ValueError, UnicodeDecodeError) as error:
                raise ValueError("document cursor is invalid") from error
        if offset < 0:
            raise ValueError("document cursor is invalid")
        chunk_count = func.count(Chunk.id).label("chunk_count")
        embedded = func.count(Chunk.id).filter(Chunk.embedding.is_not(None)).label("embedded")
        text_chunks = func.count(Chunk.id).filter(Chunk.kind == "text").label("text_chunks")
        table_chunks = func.count(Chunk.id).filter(Chunk.kind == "table").label("table_chunks")
        snapshot_count = (
            select(func.count())
            .select_from(SnapshotDocument)
            .join(EvaluationSnapshot, EvaluationSnapshot.id == SnapshotDocument.snapshot_id)
            .where(
                *self._snapshot_filters(),
                SnapshotDocument.doc_id == Document.doc_id,
                SnapshotDocument.source_sha256 == Document.source_sha256,
            )
            .correlate(Document)
            .scalar_subquery()
            .label("snapshot_count")
        )
        coverage = (cast(embedded, Float) / func.nullif(cast(chunk_count, Float), 0.0)).label(
            "embedding_coverage"
        )
        having = []
        if embedding_status == "complete":
            having.extend((chunk_count > 0, embedded == chunk_count))
        elif embedding_status == "partial":
            having.extend((embedded > 0, embedded < chunk_count))
        elif embedding_status == "missing":
            having.append(embedded == 0)
        sort_columns = {
            "doc_id": Document.doc_id,
            "issuer": Document.issuer,
            "fiscal_year": Document.fiscal_year,
            "filing_date": Document.filing_date,
            "chunk_count": chunk_count,
            "embedding_coverage": coverage,
        }
        order = sort_columns[sort].desc() if descending else sort_columns[sort].asc()
        statement = (
            select(
                Document,
                chunk_count,
                embedded,
                text_chunks,
                table_chunks,
                snapshot_count,
            )
            .outerjoin(Chunk, Chunk.doc_id == Document.doc_id)
            .where(*filters)
            .group_by(Document.doc_id)
            .having(*having)
            .order_by(order, Document.doc_id)
            .offset(offset)
            .limit(limit)
        )
        filtered_documents = (
            select(Document.doc_id)
            .outerjoin(Chunk, Chunk.doc_id == Document.doc_id)
            .where(*filters)
            .group_by(Document.doc_id)
            .having(*having)
            .subquery()
        )
        count_statement = select(func.count()).select_from(filtered_documents)
        async with self._session_factory() as session:
            total = int(await session.scalar(count_statement) or 0)
            rows = (await session.execute(statement)).all()
        documents = tuple(
            AdminDocumentResource(
                doc_id=document.doc_id,
                registry=document.registry,
                language=document.language,
                issuer=document.issuer,
                issuer_name=names.get((document.registry, document.issuer)),
                issuer_id=document.issuer_id,
                fiscal_year=document.fiscal_year,
                form=document.form,
                filing_date=document.filing_date,
                report_period=document.report_period,
                filing_id=document.filing_id,
                source_url=public_source_url(document.source_url)
                if self._public_only
                else document.source_url,
                parse_status=document.parse_status,
                source_length=document.source_length,
                source_sha256=document.source_sha256,
                chunk_count=int(chunks),
                embedded_chunks=int(embedded_count),
                text_chunks=int(text_count),
                table_chunks=int(table_count),
                embedding_status=(
                    "complete"
                    if int(chunks) > 0 and int(embedded_count) == int(chunks)
                    else "partial"
                    if int(embedded_count) > 0
                    else "missing"
                ),
                snapshot_count=int(membership_count),
            )
            for (
                document,
                chunks,
                embedded_count,
                text_count,
                table_count,
                membership_count,
            ) in rows
        )
        next_offset = offset + len(documents)
        next_cursor = (
            base64.urlsafe_b64encode(str(next_offset).encode()).decode()
            if next_offset < total
            else None
        )
        return DocumentInventoryResponse(documents=documents, total=total, next_cursor=next_cursor)

    async def document_facets(self, registry: str = "") -> DocumentFacetsResponse:
        """Return deterministic live filter values and counts."""
        names = self._company_names()
        registry_filters = (Document.registry == registry,) if registry else ()
        document_filters = (*self._document_filters(), *registry_filters)

        async def values(
            column: InstrumentedAttribute[str | int],
        ) -> tuple[DocumentFacetValue, ...]:
            """Aggregate one safe ORM column into sorted facet values."""
            async with self._session_factory() as session:
                rows = (
                    await session.execute(
                        select(column, func.count())
                        .where(*document_filters)
                        .group_by(column)
                        .order_by(column)
                    )
                ).all()
            return tuple(
                DocumentFacetValue(value=str(value), count=int(count)) for value, count in rows
            )

        chunk_count = func.count(Chunk.id).label("chunk_count")
        embedded = func.count(Chunk.id).filter(Chunk.embedding.is_not(None)).label("embedded")
        async with self._session_factory() as session:
            coverage_rows = (
                await session.execute(
                    select(
                        Document.doc_id, Document.registry, Document.issuer, chunk_count, embedded
                    )
                    .outerjoin(Chunk, Chunk.doc_id == Document.doc_id)
                    .where(*document_filters)
                    .group_by(Document.doc_id)
                )
            ).all()
            snapshot_rows = (
                await session.execute(
                    select(
                        EvaluationSnapshot.id,
                        EvaluationSnapshot.label,
                        EvaluationSnapshot.status,
                        func.count(Document.doc_id)
                        if self._public_only
                        else func.count(SnapshotDocument.doc_id),
                    )
                    .outerjoin(
                        SnapshotDocument,
                        SnapshotDocument.snapshot_id == EvaluationSnapshot.id,
                    )
                    .outerjoin(
                        Document,
                        (Document.doc_id == SnapshotDocument.doc_id)
                        & (Document.source_sha256 == SnapshotDocument.source_sha256),
                    )
                    .where(*self._snapshot_filters(), *registry_filters)
                    .group_by(EvaluationSnapshot.id)
                    .order_by(EvaluationSnapshot.created_at.desc(), EvaluationSnapshot.id.desc())
                )
            ).all()
        status_counts = {"complete": 0, "partial": 0, "missing": 0}
        issuer_counts: dict[str, int] = {}
        issuer_names: dict[str, set[str | None]] = {}
        for _doc_id, registry, issuer, chunks, embedded_count in coverage_rows:
            issuer_counts[issuer] = issuer_counts.get(issuer, 0) + 1
            issuer_names.setdefault(issuer, set()).add(names.get((registry, issuer)))
            status = (
                "complete"
                if int(chunks) > 0 and int(embedded_count) == int(chunks)
                else "partial"
                if int(embedded_count) > 0
                else "missing"
            )
            status_counts[status] += 1
        return DocumentFacetsResponse(
            registries=await values(Document.registry),
            issuers=tuple(
                DocumentFacetValue(
                    value=issuer,
                    count=count,
                    label=f"{issuer} · {name}" if name is not None else None,
                )
                for issuer, count in sorted(issuer_counts.items())
                for name in [
                    next(iter(issuer_names[issuer])) if len(issuer_names[issuer]) == 1 else None
                ]
            ),
            years=await values(Document.fiscal_year),
            languages=await values(Document.language),
            forms=await values(Document.form),
            parse_statuses=await values(Document.parse_status),
            embedding_statuses=tuple(
                DocumentFacetValue(value=status, count=count)
                for status, count in status_counts.items()
                if count > 0
            ),
            snapshots=tuple(
                DocumentFacetValue(
                    value=str(snapshot_id),
                    count=int(count),
                    label=f"{label} · {status}",
                )
                for snapshot_id, label, status, count in snapshot_rows
                if int(count) > 0
            ),
        )

    async def document_detail(self, doc_id: str) -> DocumentDetailResponse | None:
        """Load a bounded published document preview without reading private corpus state."""
        async with self._session_factory() as session:
            document = await session.scalar(
                select(Document).where(Document.doc_id == doc_id, *self._document_filters())
            )
            if document is None:
                return None
            chunks = tuple(
                await session.scalars(
                    select(Chunk)
                    .where(Chunk.doc_id == doc_id)
                    .order_by(Chunk.ordinal)
                    .limit(CHUNK_PREVIEW_LIMIT)
                )
            )
            rows = (
                await session.execute(
                    select(
                        Chunk.kind,
                        Chunk.item,
                        Chunk.embedding_provider,
                        Chunk.embedding_model,
                        Chunk.embedding_dimensions,
                        func.count().label("count"),
                        func.count().filter(Chunk.embedding.is_not(None)).label("embedded"),
                    )
                    .where(Chunk.doc_id == doc_id)
                    .group_by(
                        Chunk.kind,
                        Chunk.item,
                        Chunk.embedding_provider,
                        Chunk.embedding_model,
                        Chunk.embedding_dimensions,
                    )
                )
            ).all()
            memberships = tuple(
                await session.scalars(
                    select(EvaluationSnapshot)
                    .join(SnapshotDocument, SnapshotDocument.snapshot_id == EvaluationSnapshot.id)
                    .where(
                        SnapshotDocument.doc_id == doc_id,
                        SnapshotDocument.source_sha256 == document.source_sha256,
                        *self._snapshot_filters(),
                    )
                    .order_by(EvaluationSnapshot.created_at.desc(), EvaluationSnapshot.id.desc())
                )
            )
        items: dict[str, int] = {}
        embeddings: dict[tuple[str, str, int], int] = {}
        for _kind, item, provider, model, dimensions, count, embedded in rows:
            section = item or "unsectioned"
            items[section] = items.get(section, 0) + int(count)
            if provider is not None and int(embedded) > 0:
                identity = (str(provider), str(model), int(dimensions))
                embeddings[identity] = embeddings.get(identity, 0) + int(embedded)
        metadata = {
            name: getattr(document, name)
            for name in (
                "doc_id",
                "registry",
                "language",
                "issuer",
                "issuer_id",
                "fiscal_year",
                "form",
                "parse_status",
                "filing_date",
                "report_period",
                "filing_id",
                "source_length",
                "source_sha256",
            )
        }
        metadata.update(
            issuer_name=self._company_names().get((document.registry, document.issuer)),
            source_url=public_source_url(document.source_url),
            chunk_count=sum(int(row[5]) for row in rows),
        )
        return DocumentDetailResponse.model_validate(
            {
                "document": metadata,
                "chunks": tuple(
                    {
                        "chunk_id": chunk.id,
                        "ordinal": chunk.ordinal,
                        "citation": chunk.citation,
                        "span": f"chars {chunk.start_char}-{chunk.end_char}",
                        "source_sha256": chunk.source_sha256,
                        "body": chunk.body[:CHUNK_PREVIEW_CHARS],
                    }
                    for chunk in chunks
                ),
                "text_chunks": sum(int(row[5]) for row in rows if row.kind == "text"),
                "table_chunks": sum(int(row[5]) for row in rows if row.kind == "table"),
                "embedded_chunks": sum(int(row.embedded) for row in rows),
                "item_counts": tuple(
                    {"item": item, "count": count} for item, count in sorted(items.items())
                ),
                "embedding_identities": tuple(
                    {"provider": key[0], "model": key[1], "dimensions": key[2], "count": count}
                    for key, count in sorted(embeddings.items())
                ),
                "snapshot_memberships": tuple(
                    {
                        "snapshot_id": snapshot.id,
                        "label": snapshot.label,
                        "status": snapshot.status,
                        "public": snapshot.public,
                        "created_at": snapshot.created_at,
                    }
                    for snapshot in memberships
                ),
            }
        )
