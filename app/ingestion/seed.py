"""Deterministic, idempotent PostgreSQL persistence for parsed filing chunks.

M1.4 persists retrieval text and source provenance only. Embeddings remain null
until the retrieval milestone supplies and evaluates an embedding provider.
"""

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
from app.ingestion.chunk import Chunk, chunk_filing, compose_index_text
from app.ingestion.parser import ParsedFiling, parse_filing

EXPECTED_DOCUMENTS = 20
DEFAULT_CHUNK_BATCH_SIZE = 500
SHA256_RE = re.compile(r"[0-9a-f]{64}", re.ASCII)
PARSE_STATUSES = frozenset({"parsed", "needs_profile_update"})
ITEM_STATUSES = frozenset({"parsed", "empty_disclosure", "incorporated_by_reference"})


@dataclass(frozen=True, slots=True)
class DocumentRecord:
    """Preserve validated immutable values for one ``documents`` row.

    Construction rejects missing filing metadata, invalid item-index entries, and
    source identities that cannot safely own persisted chunk provenance.
    """

    doc_id: str
    ticker: str
    cik: int
    fiscal_year: int
    form: str
    filing_date: str
    report_period: str
    accession: str
    url: str
    parse_status: str
    item_index: tuple[dict[str, Any], ...]
    source_length: int
    source_sha256: str

    def __post_init__(self) -> None:
        """Validate document values before persistence.

        Raises
        ------
        ValueError
            If required metadata is missing, constrained values are invalid, the item index
            cannot be serialized as JSON, or the source metadata is invalid.
        """
        required = {
            "doc_id": self.doc_id,
            "ticker": self.ticker,
            "form": self.form,
            "filing_date": self.filing_date,
            "report_period": self.report_period,
            "accession": self.accession,
            "url": self.url,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            owner = self.doc_id or "<unknown>"
            raise ValueError(f"{owner} is missing metadata: {', '.join(missing)}")
        if self.cik <= 0:
            raise ValueError(f"{self.doc_id} has an invalid CIK")
        if self.fiscal_year <= 0:
            raise ValueError(f"{self.doc_id} has an invalid fiscal year")
        if self.parse_status not in PARSE_STATUSES:
            raise ValueError(f"{self.doc_id} has an invalid parse status")
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
        """Build SQL values in stable schema order.

        Returns
        -------
        dict[str, Any]
            Fresh mapping accepted by the PostgreSQL document insert statement.

        Notes
        -----
        The immutable item-index tuple is converted to a list for JSONB binding.
        """
        return {
            "doc_id": self.doc_id,
            "ticker": self.ticker,
            "cik": self.cik,
            "fiscal_year": self.fiscal_year,
            "form": self.form,
            "filing_date": self.filing_date,
            "report_period": self.report_period,
            "accession": self.accession,
            "url": self.url,
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
        """Validate chunk content and source provenance before persistence.

        Raises
        ------
        ValueError
            If required chunk data is missing or its kind, ordinal, index text, source span,
            source hash, or citation is invalid.
        """
        if not self.doc_id:
            raise ValueError("chunk must have a document id")
        if self.kind not in {"text", "table"}:
            raise ValueError(f"unsupported chunk kind: {self.kind}")
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
        """Build SQL values without an embedding payload.

        Returns
        -------
        dict[str, Any]
            Fresh mapping accepted by the PostgreSQL chunk insert statement.

        Notes
        -----
        Embeddings remain outside M1.4 persistence and are populated by retrieval code.
        """
        return {
            "doc_id": self.doc_id,
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
        """Validate ordering and cross-record source invariants.

        Raises
        ------
        ValueError
            If documents or chunks are duplicated, unsorted, disconnected, inconsistent with
            their source document, outside its bounds, or have non-dense ordinals.
        """
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
    """Validate one canonical lowercase SHA-256 identity.

    Parameters
    ----------
    value : str
        Digest expected to contain exactly 64 lowercase hexadecimal characters.
    owner : str
        Record identity included in a validation failure.

    Raises
    ------
    ValueError
        If ``value`` is not a canonical lowercase SHA-256 digest.
    """
    if SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{owner} must have a lowercase hexadecimal SHA-256")


def document_record(filing: ParsedFiling) -> DocumentRecord:
    """Convert one parsed filing to its deterministic database record.

    Parameters
    ----------
    filing : ParsedFiling
        Parsed filing whose metadata and source identity will be persisted.

    Returns
    -------
    DocumentRecord
        Validated document values detached from the mutable parser output.

    Raises
    ------
    ValueError
        If the CIK, item index, document metadata, or source identity is invalid.
    """
    try:
        cik = int(filing.cik)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{filing.doc_id} has an invalid CIK") from exc
    try:
        item_index = tuple(json.loads(json.dumps(filing.item_index, sort_keys=True)))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{filing.doc_id} has a non-JSON item index") from exc
    return DocumentRecord(
        doc_id=filing.doc_id,
        ticker=filing.ticker,
        cik=cik,
        fiscal_year=filing.fiscal_year,
        form=filing.form,
        filing_date=filing.filing_date,
        report_period=filing.report_period,
        accession=filing.accession,
        url=filing.source_url,
        parse_status=filing.parse_status,
        item_index=item_index,
        source_length=filing.source_length,
        source_sha256=filing.source_sha256,
    )


def chunk_records(filing: ParsedFiling, chunks: Sequence[Chunk]) -> tuple[ChunkRecord, ...]:
    """Convert and validate all chunks for one filing.

    Parameters
    ----------
    filing : ParsedFiling
        Parsed filing that owns the chunks and their source coordinates.
    chunks : Sequence[Chunk]
        Source-ordered chunks expected to have dense ordinals.

    Returns
    -------
    tuple[ChunkRecord, ...]
        Validated persistence records in input order.

    Raises
    ------
    ValueError
        If chunk ownership, ordering, content, kind, span, or source identity is invalid.
    """
    records: list[ChunkRecord] = []
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
    """Convert one parsed filing and its chunks to validated records.

    Parameters
    ----------
    filing : ParsedFiling
        Parsed filing that owns the document row and every supplied chunk.
    chunks : Sequence[Chunk]
        Source-ordered chunks expected to have dense ordinals.

    Returns
    -------
    tuple[DocumentRecord, tuple[ChunkRecord, ...]]
        Validated document record and its immutable chunk records.

    Raises
    ------
    ValueError
        If document metadata, chunk ownership, ordering, content, or provenance is invalid.
    """
    document = document_record(filing)
    return document, chunk_records(filing, chunks)


def load_manifest(path: Path) -> list[dict[str, Any]]:
    """Load a filing manifest and reject non-object entries.

    Parameters
    ----------
    path : Path
        UTF-8 JSON manifest to read.

    Returns
    -------
    list[dict[str, Any]]
        Manifest objects in their stored order.

    Raises
    ------
    OSError
        If the manifest cannot be read.
    json.JSONDecodeError
        If the file does not contain valid JSON.
    ValueError
        If the top-level value is not a list of objects.
    """
    entries = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(entries, list) or not all(isinstance(entry, dict) for entry in entries):
        raise ValueError("manifest must contain a JSON list of objects")
    return entries


def _ordered_manifest_entries(
    entries: Iterable[Mapping[str, Any]], expected_documents: int | None
) -> list[dict[str, Any]]:
    """Copy, count, and deterministically order manifest entries."""
    ordered = [dict(entry) for entry in entries]
    if expected_documents is not None and len(ordered) != expected_documents:
        raise ValueError(f"expected {expected_documents} manifest documents, found {len(ordered)}")
    ordered.sort(
        key=lambda entry: (str(entry.get("ticker", "")), str(entry.get("report_date", "")))
    )
    return ordered


def parse_seed_filings(
    entries: Iterable[Mapping[str, Any]],
    *,
    expected_documents: int | None = None,
    parser: Callable[[dict[str, Any]], tuple[ParsedFiling, dict[str, Any]]] = parse_filing,
) -> tuple[ParsedFiling, ...]:
    """Parse manifest entries once in deterministic document order.

    Parameters
    ----------
    entries : Iterable[Mapping[str, Any]]
        Filing manifest entries to copy, validate, sort, and parse.
    expected_documents : int | None, optional
        Required number of manifest entries, or ``None`` to accept any count.
    parser : Callable, optional
        Filing parser used exactly once for each copied manifest entry.

    Returns
    -------
    tuple[ParsedFiling, ...]
        Mutable parsed filings ordered by manifest ticker and report date.

    Raises
    ------
    ValueError
        If the manifest count is not the expected value.
    """
    filings: list[ParsedFiling] = []
    for entry in _ordered_manifest_entries(entries, expected_documents):
        filing, _profile = parser(entry)
        filings.append(filing)
    return tuple(filings)


def build_seed_batch_from_filings(
    filings: Iterable[ParsedFiling],
    *,
    chunker: Callable[[ParsedFiling], list[Chunk]] = chunk_filing,
) -> SeedBatch:
    """Chunk already parsed filings into one deterministic persistence batch.

    Parameters
    ----------
    filings : Iterable[ParsedFiling]
        Parsed filings to convert without parsing their source documents again.
    chunker : Callable, optional
        Chunk builder used once for each parsed filing.

    Returns
    -------
    SeedBatch
        Validated records sorted by document ID and chunk ordinal.

    Raises
    ------
    ValueError
        If any generated record violates a seed invariant.
    """
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
    parser: Callable[[dict[str, Any]], tuple[ParsedFiling, dict[str, Any]]] = parse_filing,
    chunker: Callable[[ParsedFiling], list[Chunk]] = chunk_filing,
) -> SeedBatch:
    """Parse and chunk manifest entries in deterministic document order.

    Parameters
    ----------
    entries : Iterable[Mapping[str, Any]]
        Filing manifest entries to copy, sort, parse, and chunk.
    expected_documents : int | None, optional
        Required number of manifest entries, or ``None`` to accept any count.
    parser : Callable, optional
        Filing parser used for each copied manifest entry.
    chunker : Callable, optional
        Chunk builder used for each parsed filing.

    Returns
    -------
    SeedBatch
        Validated records sorted by document ID and chunk ordinal.

    Raises
    ------
    ValueError
        If the manifest count or any generated record violates a seed invariant.
    """
    documents: list[DocumentRecord] = []
    chunks: list[ChunkRecord] = []
    for entry in _ordered_manifest_entries(entries, expected_documents):
        filing, _profile = parser(entry)
        document, filing_chunks = filing_records(filing, chunker(filing))
        documents.append(document)
        chunks.extend(filing_chunks)

    documents.sort(key=lambda record: record.doc_id)
    chunks.sort(key=lambda record: (record.doc_id, record.ordinal))
    return SeedBatch(tuple(documents), tuple(chunks))


def prepare_seed_batch(
    manifest_path: Path | None = None, *, expected_documents: int | None = EXPECTED_DOCUMENTS
) -> SeedBatch:
    """Build the complete corpus batch before opening a database transaction.

    Parameters
    ----------
    manifest_path : Path | None, optional
        Explicit manifest path, or the configured corpus manifest when omitted.
    expected_documents : int | None, optional
        Required manifest size, or ``None`` to accept any number of documents.

    Returns
    -------
    SeedBatch
        Fully parsed, chunked, validated, and deterministically sorted persistence batch.

    Raises
    ------
    OSError
        If the manifest or a filing source cannot be read.
    json.JSONDecodeError
        If the manifest does not contain valid JSON.
    ValueError
        If the manifest count or any parsed record violates a seed invariant.

    Notes
    -----
    All CPU and file work completes before a caller opens the persistence transaction.
    """
    path = manifest_path or get_settings().corpus_dir / "manifest.json"
    return build_seed_batch(load_manifest(path), expected_documents=expected_documents)


def document_upsert_statement(records: Sequence[DocumentRecord]) -> Insert:
    """Build a PostgreSQL document upsert keyed by ``doc_id``.

    Parameters
    ----------
    records : Sequence[DocumentRecord]
        Validated document rows to insert or update.

    Returns
    -------
    Insert
        PostgreSQL insert statement with a ``doc_id`` conflict action.

    Raises
    ------
    ValueError
        If ``records`` is empty.
    """
    if not records:
        raise ValueError("document upsert requires at least one record")
    statement = insert(Document).values([record.values() for record in records])
    excluded = statement.excluded
    return statement.on_conflict_do_update(
        index_elements=[Document.doc_id],
        set_={
            "ticker": excluded.ticker,
            "cik": excluded.cik,
            "fiscal_year": excluded.fiscal_year,
            "form": excluded.form,
            "filing_date": excluded.filing_date,
            "report_period": excluded.report_period,
            "accession": excluded.accession,
            "url": excluded.url,
            "parse_status": excluded.parse_status,
            "item_index": excluded.item_index,
            "source_length": excluded.source_length,
            "source_sha256": excluded.source_sha256,
        },
    )


def chunk_upsert_statement(records: Sequence[ChunkRecord]) -> Insert:
    """Build a PostgreSQL chunk upsert keyed by ``(doc_id, ordinal)``.

    Parameters
    ----------
    records : Sequence[ChunkRecord]
        Validated chunk rows to insert or update.

    Returns
    -------
    Insert
        PostgreSQL insert statement that preserves embeddings for unchanged index text.

    Raises
    ------
    ValueError
        If ``records`` is empty.
    """
    if not records:
        raise ValueError("chunk upsert requires at least one record")
    statement = insert(ChunkModel).values([record.values() for record in records])
    excluded = statement.excluded
    return statement.on_conflict_do_update(
        index_elements=[ChunkModel.doc_id, ChunkModel.ordinal],
        set_={
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
    """Yield bounded slices without materializing all batches at once.

    Parameters
    ----------
    records : Sequence[ChunkRecord]
        Source-ordered chunk records to partition.
    size : int
        Positive maximum records yielded per slice.

    Yields
    ------
    Sequence[ChunkRecord]
        Consecutive slices that preserve the input order.

    Raises
    ------
    ValueError
        If ``size`` is not positive.
    """
    if size <= 0:
        raise ValueError("chunk batch size must be positive")
    for start in range(0, len(records), size):
        yield records[start : start + size]


async def persist_seed_batch(
    session: AsyncSession, batch: SeedBatch, *, chunk_batch_size: int = DEFAULT_CHUNK_BATCH_SIZE
) -> SeedResult:
    """Atomically upsert one batch and remove stale trailing chunk ordinals.

    Parameters
    ----------
    session : AsyncSession
        Idle SQLAlchemy session that will own the seed transaction.
    batch : SeedBatch
        Complete validated document and chunk records to persist.
    chunk_batch_size : int, optional
        Maximum number of chunk rows in each upsert statement.

    Returns
    -------
    SeedResult
        Document and chunk counts after the transaction commits.

    Raises
    ------
    RuntimeError
        If ``session`` already has an active transaction.
    ValueError
        If ``chunk_batch_size`` is not positive.

    Notes
    -----
    The function owns exactly one transaction. Successful context exit commits every write;
    any exception rolls back the complete batch.
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


async def seed_corpus(
    session: AsyncSession,
    manifest_path: Path | None = None,
    *,
    expected_documents: int | None = EXPECTED_DOCUMENTS,
    chunk_batch_size: int = DEFAULT_CHUNK_BATCH_SIZE,
) -> SeedResult:
    """Prepare and atomically persist the parsed filing corpus.

    Parameters
    ----------
    session : AsyncSession
        Idle SQLAlchemy session used for persistence.
    manifest_path : Path | None, optional
        Manifest path, or ``None`` to use the configured corpus manifest.
    expected_documents : int | None, optional
        Required manifest size, or ``None`` to accept any number of documents.
    chunk_batch_size : int, optional
        Maximum number of chunk rows in each upsert statement.

    Returns
    -------
    SeedResult
        Committed document and chunk counts.

    Raises
    ------
    OSError
        If corpus preparation cannot read a required file.
    json.JSONDecodeError
        If the manifest does not contain valid JSON.
    ValueError
        If preparation or persistence validation fails.
    RuntimeError
        If the supplied session already owns an active transaction.

    Notes
    -----
    CPU- and file-intensive corpus preparation runs in a worker thread. Database writes remain
    on the caller's event loop and use one transaction.
    """
    batch = await asyncio.to_thread(
        prepare_seed_batch,
        manifest_path,
        expected_documents=expected_documents,
    )
    return await persist_seed_batch(session, batch, chunk_batch_size=chunk_batch_size)


def main() -> None:
    """Run the command-line seed operation.

    Raises
    ------
    SystemExit
        If command-line parsing fails or requests help.

    Notes
    -----
    The CLI prepares the full batch before opening a session, optionally creates missing
    schema objects, and prints counts only after the persistence transaction commits.
    """

    def _arguments() -> argparse.Namespace:
        """Parse seed CLI arguments."""
        parser = argparse.ArgumentParser(
            description="Upsert parsed SEC filing chunks into PostgreSQL."
        )
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

    async def _run_cli(args: argparse.Namespace) -> None:
        """Execute optional schema creation and one atomic seed transaction."""
        from app.db.bootstrap import bootstrap_schema
        from app.db.session import Session, engine

        batch = prepare_seed_batch(args.manifest, expected_documents=args.expected_documents)
        if args.create_schema:
            await bootstrap_schema(engine)
        async with Session() as session:
            result = await persist_seed_batch(
                session,
                batch,
                chunk_batch_size=args.chunk_batch_size,
            )
        print(f"Committed {result.documents} documents and {result.chunks} chunks.")

    asyncio.run(_run_cli(_arguments()))


if __name__ == "__main__":
    main()
