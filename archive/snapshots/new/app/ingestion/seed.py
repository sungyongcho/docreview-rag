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
from app.ingestion.chunk import Chunk, chunk_filing
from app.ingestion.parser import ParsedFiling, parse_filing

EXPECTED_DOCUMENTS = 20
DEFAULT_CHUNK_BATCH_SIZE = 500
SHA256_RE = re.compile(r"[0-9a-f]{64}", re.ASCII)
PARSE_STATUSES = frozenset({"parsed", "needs_profile_update"})
ITEM_STATUSES = frozenset({"parsed", "empty_disclosure", "incorporated_by_reference"})


@dataclass(frozen=True, slots=True)
class DocumentRecord:
    """Validated values persisted in one ``documents`` row."""

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
        """Return SQL values in stable schema order."""
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
    """Validated values persisted in one ``chunks`` row."""

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
        if not self.doc_id:
            raise ValueError("chunk must have a document id")
        if self.kind not in {"text", "table"}:
            raise ValueError(f"unsupported chunk kind: {self.kind}")
        if self.ordinal < 0:
            raise ValueError(f"{self.doc_id} has a negative chunk ordinal")
        if not self.body:
            raise ValueError(f"{self.doc_id} chunk {self.ordinal} has an empty body")
        expected_index_text = (
            f"{self.context_header}\n\n{self.body}" if self.context_header else self.body
        )
        if self.index_text != expected_index_text:
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
    """A complete, validated persistence batch."""

    documents: tuple[DocumentRecord, ...]
    chunks: tuple[ChunkRecord, ...]

    def __post_init__(self) -> None:
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
    """Committed row counts for one seed operation."""

    documents: int
    chunks: int


def _require_sha256(value: str, *, owner: str) -> None:
    if SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{owner} must have a lowercase hexadecimal SHA-256")


def document_record(filing: ParsedFiling) -> DocumentRecord:
    """Convert one parsed filing to its deterministic database record."""
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
    """Convert and validate all chunks for one filing."""
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
        _require_sha256(chunk.source_sha256, owner=f"{filing.doc_id} chunk {chunk.ordinal}")

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
    """Convert one parsed filing and its chunks to validated records."""
    document = document_record(filing)
    return document, chunk_records(filing, chunks)


def load_manifest(path: Path) -> list[dict[str, Any]]:
    """Load a filing manifest and reject non-list top-level values."""
    entries = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(entries, list) or not all(isinstance(entry, dict) for entry in entries):
        raise ValueError("manifest must contain a JSON list of objects")
    return entries


def build_seed_batch(
    entries: Iterable[Mapping[str, Any]],
    *,
    expected_documents: int | None = None,
    parser: Callable[[dict[str, Any]], tuple[ParsedFiling, dict[str, Any]]] = parse_filing,
    chunker: Callable[[ParsedFiling], list[Chunk]] = chunk_filing,
) -> SeedBatch:
    """Parse and chunk manifest entries in deterministic document order."""
    ordered = sorted(
        (dict(entry) for entry in entries),
        key=lambda entry: (str(entry.get("ticker", "")), str(entry.get("report_date", ""))),
    )
    if expected_documents is not None and len(ordered) != expected_documents:
        raise ValueError(f"expected {expected_documents} manifest documents, found {len(ordered)}")

    documents: list[DocumentRecord] = []
    chunks: list[ChunkRecord] = []
    for entry in ordered:
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
    """Build the complete corpus batch before opening a database transaction."""
    path = manifest_path or get_settings().corpus_dir / "manifest.json"
    return build_seed_batch(load_manifest(path), expected_documents=expected_documents)


def document_upsert_statement(records: Sequence[DocumentRecord]) -> Insert:
    """Build a PostgreSQL document upsert keyed by ``doc_id``."""
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
    """Build a PostgreSQL chunk upsert keyed by ``(doc_id, ordinal)``."""
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
    if size <= 0:
        raise ValueError("chunk batch size must be positive")
    for start in range(0, len(records), size):
        yield records[start : start + size]


async def persist_seed_batch(
    session: AsyncSession,
    batch: SeedBatch,
    *,
    chunk_batch_size: int = DEFAULT_CHUNK_BATCH_SIZE,
) -> SeedResult:
    """Atomically upsert one batch and remove stale trailing chunk ordinals.

    The function owns exactly one transaction. Callers must pass an idle session;
    successful context exit commits, while any exception rolls back every document
    and chunk write in the batch.
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
    """Prepare and atomically persist the parsed filing corpus."""
    batch = prepare_seed_batch(manifest_path, expected_documents=expected_documents)
    return await persist_seed_batch(session, batch, chunk_batch_size=chunk_batch_size)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Upsert parsed SEC filing chunks into PostgreSQL.")
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


def main() -> None:
    """Run the command-line seed operation."""
    asyncio.run(_run_cli(_arguments()))


if __name__ == "__main__":
    main()
