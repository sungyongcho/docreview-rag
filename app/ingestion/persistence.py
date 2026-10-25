"""Persist one validated source/chunk batch in a single database transaction."""

from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import Insert, insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Chunk as ChunkModel,
    ChunkTableCell,
    ChunkTableHeader,
    Corpus,
    Document,
    DocumentParse,
    ParsedStructure,
    ParsedTable,
    ProcessingSelection,
    SelectionArtifact,
    SourceArtifact as SourceArtifactModel,
    TableCaption,
    TableCell,
    TableCellSource,
    TableSourceCell,
)
from app.ingestion.pipeline import ChunkRecord, SeedBatch, structure_values
from app.ingestion.progress import OperationProgress, OperationProgressCallback
from app.ingestion.sources.models import DocumentReference
from app.ingestion.table_records import (
    TableRecord,
    builder_identity,
    resolver_identity,
    table_records,
)

DEFAULT_CHUNK_BATCH_SIZE = 500


@dataclass(frozen=True, slots=True)
class SeedResult:
    """Report immutable document and chunk counts after a committed seed operation."""

    documents: int
    chunks: int


def document_values(document: DocumentReference) -> dict[str, Any]:
    """Project the validated source identity into the existing database columns."""
    values = document.model_dump(mode="json")
    values["doc_id"] = values.pop("document_id")
    return values


def document_upsert_statement(records: Sequence[DocumentReference]) -> Insert:
    """Build a nonempty PostgreSQL document upsert keyed by ``doc_id``."""
    if not records:
        raise ValueError("document upsert requires at least one record")
    statement = insert(Document).values([document_values(record) for record in records])
    excluded = statement.excluded
    return statement.on_conflict_do_update(
        index_elements=[Document.doc_id],
        set_={
            "registry": excluded.registry,
            "language": excluded.language,
            "issuer": excluded.issuer,
            "issuer_id": excluded.issuer_id,
            "fiscal_year": excluded.fiscal_year,
            "form": excluded.form,
            "filing_date": excluded.filing_date,
            "report_period": excluded.report_period,
            "filing_id": excluded.filing_id,
            "source_url": excluded.source_url,
            "aliases": excluded.aliases,
            "sec": excluded.sec,
            "dart": excluded.dart,
        },
    )


def chunk_upsert_statement(records: Sequence[ChunkRecord]) -> Insert:
    """Build a nonempty chunk upsert keyed by stable source and content identity.

    Preserve embeddings only when indexed text is unchanged.
    """
    if not records:
        raise ValueError("chunk upsert requires at least one record")
    statement = insert(ChunkModel).values([record.values() for record in records])
    excluded = statement.excluded
    return statement.on_conflict_do_update(
        index_elements=[ChunkModel.stable_key],
        set_={
            "structure_id": excluded.structure_id,
            "ordinal": excluded.ordinal,
            "language": excluded.language,
            "lexical_text": excluded.lexical_text,
            "item": excluded.item,
            "kind": excluded.kind,
            "body": excluded.body,
            "context_header": excluded.context_header,
            "index_text": excluded.index_text,
            "start_char": excluded.start_char,
            "end_char": excluded.end_char,
            "source_sha256": excluded.source_sha256,
            "citation": excluded.citation,
        },
    )


def _batches(records: Sequence[ChunkRecord], size: int) -> Iterable[Sequence[ChunkRecord]]:
    """Yield positive bounded slices without materializing every batch."""
    if size <= 0:
        raise ValueError("chunk batch size must be positive")
    for start in range(0, len(records), size):
        yield records[start : start + size]


async def _persist_sources(session: AsyncSession, batch: SeedBatch) -> None:
    """Persist source and parse references inside the caller's atomic seed transaction."""
    corpora = {filing.source.corpus.corpus_id: filing.source.corpus for filing in batch.filings}
    for corpus in corpora.values():
        await session.execute(insert(Corpus).values(**corpus.model_dump()).on_conflict_do_nothing())
    for filing in batch.filings:
        source = filing.source
        artifact = source.artifact.model_dump(mode="json")
        artifact["doc_id"] = artifact.pop("document_id")
        await session.execute(
            insert(SourceArtifactModel)
            .values(corpus_id=source.corpus.corpus_id, **artifact)
            .on_conflict_do_nothing()
        )
        structure = structure_values(filing)
        await session.execute(insert(ParsedStructure).values(**structure).on_conflict_do_nothing())
        pointer = insert(DocumentParse).values(
            doc_id=source.document.document_id, structure_id=structure["structure_id"]
        )
        await session.execute(
            pointer.on_conflict_do_update(
                index_elements=[DocumentParse.doc_id],
                set_={"structure_id": pointer.excluded.structure_id},
            )
        )
    if batch.selection_id is not None:
        for corpus_id in corpora:
            await session.execute(
                insert(ProcessingSelection)
                .values(corpus_id=corpus_id, selection_id=batch.selection_id)
                .on_conflict_do_nothing()
            )
            await session.execute(
                delete(SelectionArtifact).where(
                    SelectionArtifact.corpus_id == corpus_id,
                    SelectionArtifact.selection_id == batch.selection_id,
                )
            )
            members = [
                {
                    "corpus_id": corpus_id,
                    "selection_id": batch.selection_id,
                    "artifact_id": filing.source.artifact.artifact_id,
                }
                for filing in batch.filings
                if filing.source.corpus.corpus_id == corpus_id
            ]
            if members:
                await session.execute(insert(SelectionArtifact).values(members))


def table_rows(record: TableRecord) -> dict[type, list[dict[str, Any]]]:
    """Project one table's records onto its rows, keyed by ORM model, in insert order.

    Chunk memberships are left out: they need the chunk ids the upsert assigned.
    """
    unit = record.unit
    source_cells = []
    for cell in record.source_cells:
        reading = cell.reading
        source_cells.append(
            {
                "table_id": record.table_id,
                "grid_row": cell.cell.row,
                "grid_column": cell.cell.column,
                "rowspan": cell.cell.rowspan,
                "colspan": cell.cell.colspan,
                "text": cell.cell.text,
                "start_char": cell.cell.start_char,
                "end_char": cell.cell.end_char,
                "reading_values": None if reading is None else sorted(reading.values),
                "reading_years": None if reading is None else sorted(reading.years),
                "reading_scale": None if reading is None else reading.scale,
                "reading_item": None if reading is None else reading.item,
                "reading_percent": None if reading is None else reading.percent,
                "reading_currency": None if reading is None else reading.currency,
                "reading_marked": None if reading is None else reading.marked,
                "reading_row_label": None if reading is None else reading.row_label,
            }
        )
    normalized = []
    sources = []
    for cell in record.cells:
        interpretation = cell.interpretation
        reading = interpretation.reading
        normalized.append(
            {
                "table_id": record.table_id,
                "source_row": cell.row,
                "column_index": cell.column,
                "text": cell.text,
                "column_header": cell.column_header,
                "status": interpretation.status,
                "status_reason": interpretation.reason,
                "value": interpretation.value,
                "value_row": None if reading is None else reading.row,
                "value_column": None if reading is None else reading.column,
            }
        )
        sources.extend(
            {
                "table_id": record.table_id,
                "source_row": cell.row,
                "column_index": cell.column,
                "ordinal": ordinal,
                "grid_row": source.row,
                "grid_column": source.column,
            }
            for ordinal, source in enumerate(cell.sources)
        )
    return {
        ParsedTable: [
            {
                "table_id": record.table_id,
                "doc_id": record.doc_id,
                "structure_id": record.structure_id,
                "start_char": record.start_char,
                "end_char": record.end_char,
                "header_rows": list(record.header_rows),
                "builder_identity": builder_identity(),
                "resolver_identity": resolver_identity(),
                "unit_status": unit.status,
                "unit_scale": unit.scale,
                "unit_percent": unit.percent,
                "unit_per_share_plain": unit.per_share_plain,
                "unit_currency": sorted(unit.currency),
            }
        ],
        TableCaption: [
            {
                "table_id": record.table_id,
                "ordinal": ordinal,
                "start_char": caption.start_char,
                "end_char": caption.end_char,
                "text": caption.text,
                "cells": [asdict(cell) for cell in caption.cells],
            }
            for ordinal, caption in enumerate(record.captions)
        ],
        TableSourceCell: source_cells,
        TableCell: normalized,
        TableCellSource: sources,
    }


def _slices(rows: list[dict[str, Any]], size: int = 1000) -> Iterable[list[dict[str, Any]]]:
    """Split insert rows so one statement stays under PostgreSQL's bind-parameter limit."""
    for start in range(0, len(rows), size):
        yield rows[start : start + size]


async def _persist_tables(session: AsyncSession, batch: SeedBatch) -> None:
    """Replace every stored table of the batch's documents and link it to its chunks."""
    records = table_records(
        batch.chunks, {record.doc_id: record.structure_id for record in batch.chunks}
    )
    doc_ids = [document.document_id for document in batch.documents]
    await session.execute(delete(ParsedTable).where(ParsedTable.doc_id.in_(doc_ids)))
    if not records:
        return
    rows: dict[type, list[dict[str, Any]]] = {}
    for record in records:
        for model, values in table_rows(record).items():
            rows.setdefault(model, []).extend(values)
    for model in (ParsedTable, TableCaption, TableSourceCell, TableCell, TableCellSource):
        for values in _slices(rows.get(model, [])):
            await session.execute(insert(model).values(values))
    keys = {member.chunk_stable_key for record in records for member in record.memberships}
    keys |= {header.chunk_stable_key for record in records for header in record.headers}
    stored = await session.execute(
        select(ChunkModel.stable_key, ChunkModel.id).where(ChunkModel.stable_key.in_(keys))
    )
    ids = {stable_key: chunk_id for stable_key, chunk_id in stored}
    memberships = [
        {
            "chunk_id": ids[member.chunk_stable_key],
            "ordinal": member.ordinal,
            "table_id": record.table_id,
            "source_row": member.row,
            "column_index": member.column,
            "text_start": member.text_start,
            "text_end": member.text_end,
        }
        for record in records
        for member in record.memberships
    ]
    for values in _slices(memberships):
        await session.execute(insert(ChunkTableCell).values(values))
    headers = [
        {
            "chunk_id": ids[header.chunk_stable_key],
            "ordinal": header.ordinal,
            "table_id": record.table_id,
            "grid_row": header.row,
            "grid_column": header.column,
        }
        for record in records
        for header in record.headers
    ]
    for values in _slices(headers):
        await session.execute(insert(ChunkTableHeader).values(values))


async def persist_seed_batch(
    session: AsyncSession,
    batch: SeedBatch,
    *,
    chunk_batch_size: int = DEFAULT_CHUNK_BATCH_SIZE,
    on_progress: OperationProgressCallback | None = None,
) -> SeedResult:
    """Upsert one batch and remove stale trailing chunks in one transaction.

    Reject active sessions and nonpositive chunk batch sizes before writing.
    """
    if session.in_transaction():
        raise RuntimeError("persist_seed_batch requires a session without an active transaction")
    if chunk_batch_size <= 0:
        raise ValueError("chunk batch size must be positive")

    chunk_keys: dict[str, list[str]] = {record.document_id: [] for record in batch.documents}
    for record in batch.chunks:
        chunk_keys[record.doc_id].append(record.stable_key)

    async with session.begin():
        if on_progress is not None:
            on_progress(OperationProgress("documents", 0, 1, "Upserting documents"))
        if batch.documents:
            await session.execute(document_upsert_statement(batch.documents))
            await _persist_sources(session, batch)
        if on_progress is not None:
            on_progress(OperationProgress("documents", 1, 1, f"{len(batch.documents)} documents"))
        chunk_batch_total = (len(batch.chunks) + chunk_batch_size - 1) // chunk_batch_size
        if on_progress is not None:
            on_progress(OperationProgress("chunks", 0, chunk_batch_total, "Storing chunk batches"))
        for position, records in enumerate(
            _batches(batch.chunks, chunk_batch_size),
            start=1,
        ):
            await session.execute(chunk_upsert_statement(records))
            if on_progress is not None:
                on_progress(
                    OperationProgress(
                        "chunks",
                        position,
                        chunk_batch_total,
                        f"{min(position * chunk_batch_size, len(batch.chunks))} chunks",
                    )
                )
        if on_progress is not None:
            on_progress(OperationProgress("cleanup", 0, len(chunk_keys), "Removing stale chunks"))
        for position, (doc_id, keys) in enumerate(chunk_keys.items(), start=1):
            await session.execute(
                delete(ChunkModel).where(
                    ChunkModel.doc_id == doc_id,
                    ChunkModel.stable_key.not_in(keys),
                )
            )
            if on_progress is not None:
                on_progress(OperationProgress("cleanup", position, len(chunk_keys), doc_id))
        if batch.documents:
            await _persist_tables(session, batch)

    return SeedResult(documents=len(batch.documents), chunks=len(batch.chunks))


async def persist_seed_batch_with_stats(
    session: AsyncSession,
    batch: SeedBatch,
    *,
    chunk_batch_size: int = DEFAULT_CHUNK_BATCH_SIZE,
    on_progress: OperationProgressCallback | None = None,
) -> SeedResult:
    """Persist one corpus batch, then rebuild its invalidated BM25 statistics."""
    from app.retrieval.indexing.bm25 import backfill_term_stats

    result = await persist_seed_batch(
        session,
        batch,
        chunk_batch_size=chunk_batch_size,
        on_progress=on_progress,
    )
    if on_progress is not None:
        on_progress(OperationProgress("bm25", 0, 1, "Rebuilding term statistics"))
    await backfill_term_stats(session)
    if on_progress is not None:
        on_progress(OperationProgress("bm25", 1, 1, "Term statistics rebuilt"))
    return result
