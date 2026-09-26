"""Persist one validated source/chunk batch in a single database transaction."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import Insert, insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Chunk as ChunkModel,
    Corpus,
    Document,
    DocumentParse,
    ParsedStructure,
    ProcessingSelection,
    SelectionArtifact,
    SourceArtifact as SourceArtifactModel,
)
from app.ingestion.pipeline import ChunkRecord, SeedBatch, structure_values
from app.ingestion.progress import OperationProgress, OperationProgressCallback
from app.ingestion.sources.models import DocumentReference

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
