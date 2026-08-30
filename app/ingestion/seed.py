"""Deterministic PostgreSQL persistence for source-cited filing chunks."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any

from sqlalchemy import case, delete
from sqlalchemy.dialects.postgresql import Insert, insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import Chunk as ChunkModel, Document
from app.ingestion.chunk import Chunk, ChunkConfig, chunk_filing, compose_index_text
from app.ingestion.parser import ParsedFiling
from app.ingestion.registry import registry_for, registry_name, resolve_registry

# One manifest describes one corpus, so the count belongs to the manifest a caller
# names rather than to this module; EXPECTED_DOCUMENTS is the committed EDGAR corpus.
DEFAULT_MANIFEST_NAME = "manifest.json"
EXPECTED_DOCUMENTS = 20
# Corpus language tags this module is willing to persist. A row tagged outside this
# set would silently fall through every language-filtered retrieval path.
LANGUAGES = frozenset({"en", "ko"})
DEFAULT_CHUNK_BATCH_SIZE = 500
SHA256_RE = re.compile(r"[0-9a-f]{64}", re.ASCII)
PARSE_STATUSES = frozenset({"parsed", "needs_profile_update"})
ITEM_STATUSES = frozenset({"parsed", "empty_disclosure", "incorporated_by_reference"})

# One manifest entry in, one parsed filing and its segmentation profile out.
type FilingParser = Callable[[dict[str, Any]], tuple[ParsedFiling, dict[str, Any]]]


@dataclass(frozen=True, slots=True)
class DocumentRecord:
    """Preserve validated immutable values for one ``documents`` row.

    Construction rejects missing filing metadata, invalid item-index entries, and
    source identities that cannot safely own persisted chunk provenance.
    """

    doc_id: str
    registry: str
    language: str
    issuer: str
    issuer_id: str
    fiscal_year: int
    form: str
    filing_date: str
    report_period: str
    filing_id: str
    source_url: str
    parse_status: str
    item_index: tuple[dict[str, Any], ...]
    source_length: int
    source_sha256: str

    def __post_init__(self) -> None:
        """Reject incomplete identity, invalid statuses, and unsafe source metadata."""
        required = {
            "doc_id": self.doc_id,
            "registry": self.registry,
            "language": self.language,
            "issuer": self.issuer,
            "issuer_id": self.issuer_id,
            "form": self.form,
            "filing_date": self.filing_date,
            "report_period": self.report_period,
            "filing_id": self.filing_id,
            "source_url": self.source_url,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            owner = self.doc_id or "<unknown>"
            raise ValueError(f"{owner} is missing metadata: {', '.join(missing)}")
        if self.fiscal_year <= 0:
            raise ValueError(f"{self.doc_id} has an invalid fiscal year")
        if self.parse_status not in PARSE_STATUSES:
            raise ValueError(f"{self.doc_id} has an invalid parse status")
        if self.language not in LANGUAGES:
            raise ValueError(f"{self.doc_id} has an unsupported language: {self.language!r}")
        for position, entry in enumerate(self.item_index):
            if not isinstance(entry, dict):
                raise ValueError(f"{self.doc_id} item index {position} is not an object")
            item = entry.get("item")
            status = entry.get("status")
            if not isinstance(item, str) or not item:
                raise ValueError(f"{self.doc_id} item index {position} has no item")
            if status not in ITEM_STATUSES:
                raise ValueError(f"{self.doc_id} item index {position} has an invalid status")
        try:
            json.dumps(self.item_index, sort_keys=True)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{self.doc_id} has a non-JSON item index") from exc
        if self.source_length <= 0:
            raise ValueError(f"{self.doc_id} has no canonical source length")
        _require_sha256(self.source_sha256, owner=self.doc_id)

    def values(self) -> dict[str, Any]:
        """Return SQL values, converting the immutable item index for JSONB binding."""
        return {
            "doc_id": self.doc_id,
            "registry": self.registry,
            "language": self.language,
            "issuer": self.issuer,
            "issuer_id": self.issuer_id,
            "fiscal_year": self.fiscal_year,
            "form": self.form,
            "filing_date": self.filing_date,
            "report_period": self.report_period,
            "filing_id": self.filing_id,
            "source_url": self.source_url,
            "parse_status": self.parse_status,
            "item_index": list(self.item_index),
            "source_length": self.source_length,
            "source_sha256": self.source_sha256,
        }


@dataclass(frozen=True, slots=True)
class ChunkRecord:
    """Preserve validated immutable values for one ``chunks`` row.

    Construction binds indexed text, source coordinates, citation, and source hash so
    later embedding invalidation can rely on one internally consistent record.
    """

    doc_id: str
    language: str
    item: str | None
    kind: str
    ordinal: int
    body: str
    context_header: str
    index_text: str
    start_char: int
    end_char: int
    source_sha256: str
    citation: str

    def __post_init__(self) -> None:
        """Reject invalid content, index text, source spans, and citations."""
        if not self.doc_id:
            raise ValueError("chunk must have a document id")
        if self.kind not in {"text", "table"}:
            raise ValueError(f"unsupported chunk kind: {self.kind}")
        if self.language not in LANGUAGES:
            raise ValueError(
                f"{self.doc_id} chunk {self.ordinal} has an unsupported language: {self.language!r}"
            )
        if self.ordinal < 0:
            raise ValueError(f"{self.doc_id} has a negative chunk ordinal")
        if not self.body:
            raise ValueError(f"{self.doc_id} chunk {self.ordinal} has an empty body")
        if self.index_text != compose_index_text(self.context_header, self.body):
            raise ValueError(f"{self.doc_id} chunk {self.ordinal} has inconsistent index text")
        if not 0 <= self.start_char < self.end_char:
            raise ValueError(f"{self.doc_id} chunk {self.ordinal} has an invalid source span")
        _require_sha256(
            self.source_sha256,
            owner=f"{self.doc_id} chunk {self.ordinal}",
        )
        if not self.citation:
            raise ValueError(f"{self.doc_id} chunk {self.ordinal} has no citation")

    def values(self) -> dict[str, Any]:
        """Return SQL values without an embedding payload."""
        return {
            "doc_id": self.doc_id,
            "language": self.language,
            "item": self.item,
            "kind": self.kind,
            "ordinal": self.ordinal,
            "body": self.body,
            "context_header": self.context_header,
            "index_text": self.index_text,
            "start_char": self.start_char,
            "end_char": self.end_char,
            "source_sha256": self.source_sha256,
            "citation": self.citation,
        }


@dataclass(frozen=True, slots=True)
class SeedBatch:
    """Preserve a complete source-consistent batch in deterministic row order.

    Construction rejects duplicate or unsorted records, unknown document references,
    divergent source hashes, out-of-bounds spans, and non-dense chunk ordinals.
    """

    documents: tuple[DocumentRecord, ...]
    chunks: tuple[ChunkRecord, ...]

    def __post_init__(self) -> None:
        """Reject unordered, disconnected, or source-inconsistent records."""
        doc_ids = [record.doc_id for record in self.documents]
        if len(doc_ids) != len(set(doc_ids)):
            raise ValueError("seed batch contains duplicate document ids")
        if doc_ids != sorted(doc_ids):
            raise ValueError("seed batch documents must be sorted by doc_id")

        documents_by_id = {record.doc_id: record for record in self.documents}
        known_docs = set(documents_by_id)
        by_doc: dict[str, list[int]] = {doc_id: [] for doc_id in doc_ids}
        previous_key: tuple[str, int] | None = None
        for record in self.chunks:
            if record.doc_id not in known_docs:
                raise ValueError(f"chunk references an unknown document: {record.doc_id}")
            document = documents_by_id[record.doc_id]
            if record.source_sha256 != document.source_sha256:
                raise ValueError(f"chunk source SHA-256 differs from document: {record.doc_id}")
            if record.end_char > document.source_length:
                raise ValueError(f"chunk source span exceeds document length: {record.doc_id}")
            key = (record.doc_id, record.ordinal)
            if previous_key is not None and key <= previous_key:
                raise ValueError("seed batch chunks must be unique and sorted")
            previous_key = key
            by_doc[record.doc_id].append(record.ordinal)

        for doc_id, ordinals in by_doc.items():
            if ordinals != list(range(len(ordinals))):
                raise ValueError(f"chunk ordinals must be dense for {doc_id}")


@dataclass(frozen=True, slots=True)
class SeedResult:
    """Report immutable document and chunk counts after a committed seed operation."""

    documents: int
    chunks: int


def _require_sha256(value: str, *, owner: str) -> None:
    """Require one canonical lowercase SHA-256 identity."""
    if SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{owner} must have a lowercase hexadecimal SHA-256")


def registry_chunker(filing: ParsedFiling) -> list[Chunk]:
    """Chunk one filing at its registry's measured chunk target.

    Each corpus carries its own profile (EDGAR 1200, DART 600), so the default
    seeding path must not flatten every registry onto one constant; a caller
    measuring a different target still injects its own chunker.
    """
    target = registry_for(filing.registry).chunk_target
    return chunk_filing(filing, ChunkConfig(target_text_chars=target))


def document_record(filing: ParsedFiling) -> DocumentRecord:
    """Build an immutable document record from registry-neutral filing identity.

    The mutable item index is copied through JSON before validation.
    """
    try:
        item_index = tuple(json.loads(json.dumps(filing.item_index, sort_keys=True)))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{filing.doc_id} has a non-JSON item index") from exc
    return DocumentRecord(
        doc_id=filing.doc_id,
        registry=filing.registry,
        language=registry_for(filing.registry).language,
        issuer=filing.issuer,
        issuer_id=filing.issuer_id,
        fiscal_year=filing.fiscal_year,
        form=filing.form,
        filing_date=filing.filing_date,
        report_period=filing.report_period,
        filing_id=filing.filing_id,
        source_url=filing.source_url,
        parse_status=filing.parse_status,
        item_index=item_index,
        source_length=filing.source_length,
        source_sha256=filing.source_sha256,
    )


def chunk_records(filing: ParsedFiling, chunks: Sequence[Chunk]) -> tuple[ChunkRecord, ...]:
    """Build chunk records after validating ownership, order, and provenance.

    Input order is preserved and ordinals must be dense.
    """
    records: list[ChunkRecord] = []
    language = registry_for(filing.registry).language
    for expected_ordinal, chunk in enumerate(chunks):
        if chunk.doc_id != filing.doc_id:
            raise ValueError(
                f"chunk document mismatch: expected {filing.doc_id}, found {chunk.doc_id}"
            )
        if chunk.ordinal != expected_ordinal:
            raise ValueError(f"chunk ordinals must be dense for {filing.doc_id}")
        if chunk.kind not in {"text", "table"}:
            raise ValueError(f"unsupported chunk kind: {chunk.kind}")
        if not chunk.body:
            raise ValueError(f"{filing.doc_id} chunk {chunk.ordinal} has an empty body")
        if not 0 <= chunk.start_char < chunk.end_char <= filing.source_length:
            raise ValueError(f"{filing.doc_id} chunk {chunk.ordinal} has an invalid source span")
        if chunk.source_sha256 != filing.source_sha256:
            raise ValueError(
                f"{filing.doc_id} chunk {chunk.ordinal} has a different source SHA-256"
            )

        records.append(
            ChunkRecord(
                doc_id=chunk.doc_id,
                language=language,
                item=chunk.item,
                kind=chunk.kind,
                ordinal=chunk.ordinal,
                body=chunk.body,
                context_header=chunk.context_header,
                index_text=chunk.content,
                start_char=chunk.start_char,
                end_char=chunk.end_char,
                source_sha256=chunk.source_sha256,
                citation=chunk.citation,
            )
        )
    return tuple(records)


def filing_records(
    filing: ParsedFiling, chunks: Sequence[Chunk]
) -> tuple[DocumentRecord, tuple[ChunkRecord, ...]]:
    """Build one document record and its validated chunk records."""
    document = document_record(filing)
    return document, chunk_records(filing, chunks)


def load_manifest(path: Path) -> list[dict[str, Any]]:
    """Load a UTF-8 JSON manifest and require a list of objects."""
    entries = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(entries, list) or not all(isinstance(entry, dict) for entry in entries):
        raise ValueError("manifest must contain a JSON list of objects")
    return entries


def _ordered_manifest_entries(
    entries: Iterable[Mapping[str, Any]], expected_documents: int | None
) -> list[dict[str, Any]]:
    """Copy, count, and deterministically order manifest entries.

    Each registry orders its own entries by its own keys, and the registry name leads
    the sort so a manifest holding one registry keeps the order it has today while a
    mixed manifest is still totally ordered.
    """
    ordered = [dict(entry) for entry in entries]
    if expected_documents is not None and len(ordered) != expected_documents:
        raise ValueError(f"expected {expected_documents} manifest documents, found {len(ordered)}")
    ordered.sort(key=lambda entry: (registry_name(entry), *resolve_registry(entry).sort_key(entry)))
    return ordered


def parse_seed_filings(
    entries: Iterable[Mapping[str, Any]],
    *,
    expected_documents: int | None = None,
    parser: FilingParser | None = None,
) -> tuple[ParsedFiling, ...]:
    """Parse copied manifest entries once in deterministic input-adapter order.

    Validate the expected count before invoking the parser. Each entry is parsed by the
    registry it names unless ``parser`` overrides that for every entry.
    """
    filings: list[ParsedFiling] = []
    for entry in _ordered_manifest_entries(entries, expected_documents):
        filing, _profile = (parser or resolve_registry(entry).parse)(entry)
        filings.append(filing)
    return tuple(filings)


def build_seed_batch_from_filings(
    filings: Iterable[ParsedFiling],
    *,
    chunker: Callable[[ParsedFiling], list[Chunk]] = registry_chunker,
) -> SeedBatch:
    """Chunk parsed filings and return records in deterministic database order."""
    documents: list[DocumentRecord] = []
    chunks: list[ChunkRecord] = []
    for filing in filings:
        document, filing_chunks = filing_records(filing, chunker(filing))
        documents.append(document)
        chunks.extend(filing_chunks)

    documents.sort(key=lambda record: record.doc_id)
    chunks.sort(key=lambda record: (record.doc_id, record.ordinal))
    return SeedBatch(tuple(documents), tuple(chunks))


def build_seed_batch(
    entries: Iterable[Mapping[str, Any]],
    *,
    expected_documents: int | None = None,
    parser: FilingParser | None = None,
    chunker: Callable[[ParsedFiling], list[Chunk]] = registry_chunker,
) -> SeedBatch:
    """Parse and chunk manifest entries into a deterministic seed batch.

    Each entry is parsed by the registry it names unless ``parser`` overrides that.
    """
    documents: list[DocumentRecord] = []
    chunks: list[ChunkRecord] = []
    for entry in _ordered_manifest_entries(entries, expected_documents):
        filing, _profile = (parser or resolve_registry(entry).parse)(entry)
        document, filing_chunks = filing_records(filing, chunker(filing))
        documents.append(document)
        chunks.extend(filing_chunks)

    documents.sort(key=lambda record: record.doc_id)
    chunks.sort(key=lambda record: (record.doc_id, record.ordinal))
    return SeedBatch(tuple(documents), tuple(chunks))


def prepare_seed_batch(
    manifest_path: Path | None = None,
    *,
    manifest_name: str = DEFAULT_MANIFEST_NAME,
    expected_documents: int | None = EXPECTED_DOCUMENTS,
    parser: FilingParser | None = None,
    chunker: Callable[[ParsedFiling], list[Chunk]] = registry_chunker,
) -> SeedBatch:
    """Prepare and validate one complete corpus before any transaction opens.

    Use the named manifest under the configured corpus directory unless an explicit
    path is supplied. ``parser`` and ``chunker`` reach ``build_seed_batch`` unchanged,
    so a caller measuring a different chunk target does not lose registry dispatch.
    """
    path = manifest_path or get_settings().corpus_dir / manifest_name
    return build_seed_batch(
        load_manifest(path),
        expected_documents=expected_documents,
        parser=parser,
        chunker=chunker,
    )


def document_upsert_statement(records: Sequence[DocumentRecord]) -> Insert:
    """Build a nonempty PostgreSQL document upsert keyed by ``doc_id``."""
    if not records:
        raise ValueError("document upsert requires at least one record")
    statement = insert(Document).values([record.values() for record in records])
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
            "parse_status": excluded.parse_status,
            "item_index": excluded.item_index,
            "source_length": excluded.source_length,
            "source_sha256": excluded.source_sha256,
        },
    )


def chunk_upsert_statement(records: Sequence[ChunkRecord]) -> Insert:
    """Build a nonempty chunk upsert keyed by document and ordinal.

    Preserve embeddings only when indexed text is unchanged.
    """
    if not records:
        raise ValueError("chunk upsert requires at least one record")
    statement = insert(ChunkModel).values([record.values() for record in records])
    excluded = statement.excluded
    return statement.on_conflict_do_update(
        index_elements=[ChunkModel.doc_id, ChunkModel.ordinal],
        set_={
            "language": excluded.language,
            "item": excluded.item,
            "kind": excluded.kind,
            "body": excluded.body,
            "context_header": excluded.context_header,
            "index_text": excluded.index_text,
            "start_char": excluded.start_char,
            "end_char": excluded.end_char,
            "source_sha256": excluded.source_sha256,
            "citation": excluded.citation,
            "embedding": case(
                (ChunkModel.index_text == excluded.index_text, ChunkModel.embedding),
                else_=None,
            ),
        },
    )


def _batches(records: Sequence[ChunkRecord], size: int) -> Iterable[Sequence[ChunkRecord]]:
    """Yield positive bounded slices without materializing every batch."""
    if size <= 0:
        raise ValueError("chunk batch size must be positive")
    for start in range(0, len(records), size):
        yield records[start : start + size]


async def persist_seed_batch(
    session: AsyncSession, batch: SeedBatch, *, chunk_batch_size: int = DEFAULT_CHUNK_BATCH_SIZE
) -> SeedResult:
    """Upsert one batch and remove stale trailing chunks in one transaction.

    Reject active sessions and nonpositive chunk batch sizes before writing.
    """
    if session.in_transaction():
        raise RuntimeError("persist_seed_batch requires a session without an active transaction")
    if chunk_batch_size <= 0:
        raise ValueError("chunk batch size must be positive")

    chunk_counts = dict.fromkeys((record.doc_id for record in batch.documents), 0)
    for record in batch.chunks:
        chunk_counts[record.doc_id] += 1

    async with session.begin():
        if batch.documents:
            await session.execute(document_upsert_statement(batch.documents))
        for records in _batches(batch.chunks, chunk_batch_size):
            await session.execute(chunk_upsert_statement(records))
        for doc_id, count in chunk_counts.items():
            await session.execute(
                delete(ChunkModel).where(
                    ChunkModel.doc_id == doc_id,
                    ChunkModel.ordinal >= count,
                )
            )

    return SeedResult(documents=len(batch.documents), chunks=len(batch.chunks))


async def _persist_seed_batch_with_bm25_stats(
    session: AsyncSession,
    batch: SeedBatch,
    *,
    chunk_batch_size: int = DEFAULT_CHUNK_BATCH_SIZE,
) -> SeedResult:
    """Persist one corpus batch, then rebuild its invalidated BM25 statistics."""
    from app.retrieval.bm25 import backfill_term_stats

    result = await persist_seed_batch(session, batch, chunk_batch_size=chunk_batch_size)
    await backfill_term_stats(session)
    return result


async def seed_corpus(
    session: AsyncSession,
    manifest_path: Path | None = None,
    *,
    expected_documents: int | None = EXPECTED_DOCUMENTS,
    chunk_batch_size: int = DEFAULT_CHUNK_BATCH_SIZE,
) -> SeedResult:
    """Prepare and persist the corpus, then rebuild BM25 statistics.

    Database writes remain on the caller's event loop. Corpus persistence and
    statistic rebuild each own a separate transaction.
    """
    batch = await asyncio.to_thread(
        prepare_seed_batch,
        manifest_path,
        expected_documents=expected_documents,
    )
    return await _persist_seed_batch_with_bm25_stats(
        session,
        batch,
        chunk_batch_size=chunk_batch_size,
    )


async def _run_cli(args: argparse.Namespace) -> None:
    """Execute optional schema creation and one seed-plus-statistics operation."""
    from app.db.bootstrap import bootstrap_schema
    from app.db.session import Session, engine

    batch = prepare_seed_batch(args.manifest, expected_documents=args.expected_documents)
    if args.create_schema:
        await bootstrap_schema(engine)
    async with Session() as session:
        result = await _persist_seed_batch_with_bm25_stats(
            session,
            batch,
            chunk_batch_size=args.chunk_batch_size,
        )
    print(f"Committed {result.documents} documents and {result.chunks} chunks.")


def main() -> None:
    """Run optional schema bootstrap, corpus persistence, and statistics rebuild."""

    def _arguments() -> argparse.Namespace:
        """Parse seed CLI arguments."""
        parser = argparse.ArgumentParser(description="Upsert parsed filing chunks into PostgreSQL.")
        parser.add_argument("--manifest", type=Path, help="Path to the corpus manifest JSON file.")
        parser.add_argument(
            "--expected-documents",
            type=int,
            default=EXPECTED_DOCUMENTS,
            help="Fail unless the manifest has this many documents.",
        )
        parser.add_argument(
            "--chunk-batch-size",
            type=int,
            default=DEFAULT_CHUNK_BATCH_SIZE,
            help="Number of chunk rows per PostgreSQL upsert statement.",
        )
        parser.add_argument(
            "--create-schema",
            action="store_true",
            help="Create missing tables before seeding; this does not migrate existing tables.",
        )
        return parser.parse_args()

    asyncio.run(_run_cli(_arguments()))


if __name__ == "__main__":
    main()
