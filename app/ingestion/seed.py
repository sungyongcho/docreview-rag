"""Deterministic PostgreSQL persistence for source-cited filing chunks."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass, replace
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import Insert, insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
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
from app.ingestion.chunk import (
    Chunk,
    ChunkConfig,
    ChunkKind,
    TableFragment,
    chunk_filing,
    compose_index_text,
)
from app.ingestion.manifest import (
    DartMetadata,
    DocumentReference,
    FilingSource,
    Manifest,
    SecMetadata,
)
from app.ingestion.parser import ParsedFiling
from app.ingestion.progress import OperationProgress, OperationProgressCallback
from app.ingestion.registry import REGISTRIES, registry_for
from app.retrieval.korean import lexical_plan

if TYPE_CHECKING:
    from app.retrieval.embeddings import EmbeddingProvider

# One manifest describes one corpus, so the count belongs to the manifest a caller
# names rather than to this module. There is no default count: the corpus is widened
# from the command line now, so a module that asserted a size would be asserting one
# particular day's corpus. A caller that wants the guard passes the number it expects.
DEFAULT_MANIFEST_NAME = "manifest.json"
# Corpus language tags this module is willing to persist: exactly the languages some
# registry adapter publishes in. A row tagged outside this set would silently fall
# through every language-filtered retrieval path.
LANGUAGES = frozenset(registry.language for registry in REGISTRIES.values())
DEFAULT_CHUNK_BATCH_SIZE = 500
SHA256_RE = re.compile(r"[0-9a-f]{64}", re.ASCII)
PARSE_STATUSES = frozenset({"parsed", "needs_profile_update"})
ITEM_STATUSES = frozenset({"parsed", "empty_disclosure", "incorporated_by_reference"})

# One manifest entry in, one parsed filing and its segmentation profile out.
type FilingParser = Callable[[FilingSource], tuple[ParsedFiling, dict[str, Any]]]


@dataclass(frozen=True, slots=True)
class DocumentRecord:
    """Persist filing identity only, independently of every acquired source and parse."""

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
    aliases: tuple[str, ...]
    sec: SecMetadata | None
    dart: DartMetadata | None

    def __post_init__(self) -> None:
        """Validate the one common identity contract before entering a transaction."""
        payload = self.values()
        payload["document_id"] = payload.pop("doc_id")
        DocumentReference.model_validate(payload)

    def values(self) -> dict[str, Any]:
        """Serialize common identity and source-specific filing metadata to SQL values."""
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
            "aliases": list(self.aliases),
            "sec": self.sec.model_dump(mode="json") if self.sec is not None else None,
            "dart": self.dart.model_dump(mode="json") if self.dart is not None else None,
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
    structure_id: str
    lexical_text: str | None = None
    table_fragment: TableFragment | None = None
    text_fragment: tuple[int, int] | None = None

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
        # Mirror the ck_chunks_lexical_text_language CHECK exactly (IS NOT NULL, not
        # truthiness), so no record accepted here can die later inside the transaction.
        requires_lexical = lexical_plan(self.language).index_transform is not None
        if requires_lexical != (self.lexical_text is not None):
            raise ValueError(
                f"{self.doc_id} chunk {self.ordinal}: lexical_text is required exactly "
                "for languages with a lexical index transform"
            )
        if self.lexical_text is not None and not self.lexical_text.strip():
            raise ValueError(f"{self.doc_id} chunk {self.ordinal}: lexical_text is blank")

    @property
    def stable_key(self) -> str:
        """Use the structural chunk identity independently of persistence order."""
        return Chunk(
            doc_id=self.doc_id,
            item=self.item,
            kind=cast(ChunkKind, self.kind),
            ordinal=self.ordinal,
            body=self.body,
            context_header=self.context_header,
            citation=self.citation,
            start_char=self.start_char,
            end_char=self.end_char,
            source_sha256=self.source_sha256,
            table_fragment=self.table_fragment,
            text_fragment=self.text_fragment,
        ).stable_key

    def values(self) -> dict[str, Any]:
        """Return SQL values without an embedding payload."""
        return {
            "stable_key": self.stable_key,
            "structure_id": self.structure_id,
            "index_text_sha256": hashlib.sha256(self.index_text.encode("utf-8")).hexdigest(),
            "table_fragment": asdict(self.table_fragment) if self.table_fragment else None,
            "text_fragment": list(self.text_fragment) if self.text_fragment else None,
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
            "lexical_text": self.lexical_text,
        }


@dataclass(frozen=True, slots=True)
class SeedBatch:
    """Preserve a complete source-consistent batch in deterministic row order.

    Construction rejects duplicate or unsorted records, unknown document references,
    divergent source hashes, out-of-bounds spans, and non-dense chunk ordinals.
    """

    documents: tuple[DocumentRecord, ...]
    chunks: tuple[ChunkRecord, ...]
    filings: tuple[ParsedFiling, ...]
    selection_id: str | None = None

    def __post_init__(self) -> None:
        """Reject unordered, disconnected, or source-inconsistent records."""
        doc_ids = [record.doc_id for record in self.documents]
        if sorted(filing.source.document.document_id for filing in self.filings) != sorted(doc_ids):
            raise ValueError("seed batch requires a source parse for every document")
        if len(doc_ids) != len(set(doc_ids)):
            raise ValueError("seed batch contains duplicate document ids")
        if doc_ids != sorted(doc_ids):
            raise ValueError("seed batch documents must be sorted by doc_id")

        documents_by_id = {record.doc_id: record for record in self.documents}
        filings_by_id = {filing.source.document.document_id: filing for filing in self.filings}
        structures = {}
        for doc_id, filing in filings_by_id.items():
            if document_record(filing) != documents_by_id[doc_id]:
                raise ValueError(f"document identity differs from selected filing: {doc_id}")
            structures[doc_id] = structure_values(filing)
        known_docs = set(documents_by_id)
        by_doc: dict[str, list[int]] = {doc_id: [] for doc_id in doc_ids}
        previous_key: tuple[str, int] | None = None
        for record in self.chunks:
            if record.doc_id not in known_docs:
                raise ValueError(f"chunk references an unknown document: {record.doc_id}")
            filing = filings_by_id[record.doc_id]
            if record.structure_id != structures[record.doc_id]["structure_id"]:
                raise ValueError(f"chunk references a different source parse: {record.doc_id}")
            if record.source_sha256 != filing.source_sha256:
                raise ValueError(f"chunk source SHA-256 differs from document: {record.doc_id}")
            if record.end_char > filing.source_length:
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
    """Chunk every registry with the common complete-input token budget."""
    return chunk_filing(filing, ChunkConfig())


def embedding_chunk_config(
    provider: EmbeddingProvider, *, target_tokens: int = 2_048
) -> ChunkConfig:
    """Plan complete inputs using the selected embedding model's actual tokenizer."""
    maximum = min(8_192, provider.max_input_tokens)
    return ChunkConfig(
        target_tokens=min(target_tokens, maximum),
        max_tokens=maximum,
        model=provider.identity.model,
        token_counter=provider.count_input_tokens,
    )


@lru_cache(maxsize=2)
def _parser_identity(registry: str) -> str:
    """Fingerprint the source parser and its structural processing dependencies."""
    names = ["parser.py", "tables.py", "edgar.py" if registry == "sec" else "dart.py"]
    if registry == "sec":
        names.append("xref.py")
    return hashlib.sha256(
        b"".join(Path(__file__).with_name(name).read_bytes() for name in names)
    ).hexdigest()


def structure_values(filing: ParsedFiling) -> dict[str, Any]:
    """Capture source-anchored parsed structures independently of retrieval chunks."""
    document_id = filing.source.document.document_id
    if filing.source_length <= 0:
        raise ValueError(f"{document_id} has no canonical source length")
    _require_sha256(filing.source_sha256, owner=document_id)
    if filing.parse_status not in PARSE_STATUSES:
        raise ValueError(f"{document_id} has an invalid parse status")
    if not isinstance(filing.item_index, list):
        raise ValueError(f"{document_id} item index must be a list")
    for position, entry in enumerate(filing.item_index):
        if not isinstance(entry, dict):
            raise ValueError(f"{document_id} item index {position} is not an object")
        if not isinstance(entry.get("item"), str) or not entry["item"]:
            raise ValueError(f"{document_id} item index {position} has no item")
        if entry.get("status") not in ITEM_STATUSES:
            raise ValueError(f"{document_id} item index {position} has an invalid status")
    try:
        item_index = json.loads(json.dumps(filing.item_index, sort_keys=True))
    except (TypeError, ValueError) as error:
        raise ValueError(f"{document_id} has a non-JSON item index") from error
    payload = {
        "sections": [asdict(section) for section in filing.sections],
        "warnings": filing.warnings,
        "profile_used": filing.profile_used,
        "segment_type": filing.segment_type,
    }
    identity = _parser_identity(filing.source.document.registry)
    source = filing.source
    serialized = json.dumps(
        [
            source.corpus.corpus_id,
            source.artifact.artifact_id,
            source.artifact.sha256,
            filing.source_sha256,
            identity,
            filing.parse_status,
            item_index,
            payload,
        ],
        ensure_ascii=False,
        sort_keys=True,
    )
    return {
        "structure_id": hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
        "corpus_id": source.corpus.corpus_id,
        "artifact_id": source.artifact.artifact_id,
        "artifact_sha256": source.artifact.sha256,
        "parser_identity": identity,
        "source_sha256": filing.source_sha256,
        "source_length": filing.source_length,
        "structure": payload,
        "parse_status": filing.parse_status,
        "item_index": item_index,
    }


def document_record(filing: ParsedFiling) -> DocumentRecord:
    """Derive filing identity exclusively from its typed selected source document."""
    document = filing.source.document
    return DocumentRecord(
        doc_id=document.document_id,
        registry=document.registry,
        language=document.language,
        issuer=document.issuer,
        issuer_id=document.issuer_id,
        fiscal_year=document.fiscal_year,
        form=document.form,
        filing_date=document.filing_date.isoformat(),
        report_period=document.report_period.isoformat(),
        filing_id=document.filing_id,
        source_url=document.source_url,
        aliases=document.aliases,
        sec=document.sec,
        dart=document.dart,
    )


def chunk_records(filing: ParsedFiling, chunks: Sequence[Chunk]) -> tuple[ChunkRecord, ...]:
    """Build chunk records after validating ownership, order, and provenance.

    Input order is preserved and ordinals must be dense.
    """
    document_id = filing.source.document.document_id
    records: list[ChunkRecord] = []
    structure_id = structure_values(filing)["structure_id"]
    language = registry_for(filing.source.document.registry).language
    for expected_ordinal, chunk in enumerate(chunks):
        if chunk.doc_id != document_id:
            raise ValueError(
                f"chunk document mismatch: expected {document_id}, found {chunk.doc_id}"
            )
        if chunk.ordinal != expected_ordinal:
            raise ValueError(f"chunk ordinals must be dense for {document_id}")
        if chunk.kind not in {"text", "table"}:
            raise ValueError(f"unsupported chunk kind: {chunk.kind}")
        if not chunk.body:
            raise ValueError(f"{document_id} chunk {chunk.ordinal} has an empty body")
        if not 0 <= chunk.start_char < chunk.end_char <= filing.source_length:
            raise ValueError(f"{document_id} chunk {chunk.ordinal} has an invalid source span")
        if chunk.source_sha256 != filing.source_sha256:
            raise ValueError(f"{document_id} chunk {chunk.ordinal} has a different source SHA-256")

        records.append(
            ChunkRecord(
                doc_id=chunk.doc_id,
                language=language,
                lexical_text=(
                    transform(chunk.content)
                    if (transform := lexical_plan(language).index_transform) is not None
                    else None
                ),
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
                structure_id=structure_id,
                table_fragment=chunk.table_fragment,
                text_fragment=chunk.text_fragment,
            )
        )
    return tuple(records)


def filing_records(
    filing: ParsedFiling, chunks: Sequence[Chunk]
) -> tuple[DocumentRecord, tuple[ChunkRecord, ...]]:
    """Build one document record and its validated chunk records."""
    document = document_record(filing)
    return document, chunk_records(filing, chunks)


def load_manifest(path: Path, *, selection_id: str) -> tuple[FilingSource, ...]:
    """Resolve exactly one selection from a validated common corpus manifest."""
    return Manifest.read(path).selected_sources(selection_id, path.parent)


def _ordered_manifest_entries(
    entries: Iterable[FilingSource], expected_documents: int | None
) -> list[FilingSource]:
    """Validate and order exact selected filing sources before parsing."""
    ordered = list(entries)
    if expected_documents is not None and len(ordered) != expected_documents:
        raise ValueError(f"expected {expected_documents} selected documents, found {len(ordered)}")
    identities = [entry.document.document_id for entry in ordered]
    if len(set(identities)) != len(identities):
        raise ValueError("selected documents must be unique")
    return sorted(ordered, key=lambda entry: (entry.document.registry, entry.document.document_id))


def parse_seed_filings(
    entries: Iterable[FilingSource],
    *,
    expected_documents: int | None = None,
    parser: FilingParser | None = None,
    on_progress: OperationProgressCallback | None = None,
) -> tuple[ParsedFiling, ...]:
    """Parse copied manifest entries once in deterministic input-adapter order.

    Validate the expected count before invoking the parser. Each entry is parsed by the
    registry it names unless ``parser`` overrides that for every entry.
    """
    ordered = _ordered_manifest_entries(entries, expected_documents)
    filings: list[ParsedFiling] = []
    for position, entry in enumerate(ordered, start=1):
        filing, _profile = (parser or registry_for(entry.document.registry).parse)(entry)
        filings.append(filing)
        if on_progress is not None:
            on_progress(
                OperationProgress(
                    "parse", position, len(ordered), filing.source.document.document_id
                )
            )
    return tuple(filings)


def build_seed_batch_from_filings(
    filings: Iterable[ParsedFiling],
    *,
    chunker: Callable[[ParsedFiling], list[Chunk]] = registry_chunker,
    on_progress: OperationProgressCallback | None = None,
) -> SeedBatch:
    """Chunk parsed filings and return records in deterministic database order."""
    ordered = tuple(filings)
    documents: list[DocumentRecord] = []
    chunks: list[ChunkRecord] = []
    for position, filing in enumerate(ordered, start=1):
        document, filing_chunks = filing_records(filing, chunker(filing))
        documents.append(document)
        chunks.extend(filing_chunks)
        if on_progress is not None:
            on_progress(
                OperationProgress(
                    "chunk", position, len(ordered), filing.source.document.document_id
                )
            )

    documents.sort(key=lambda record: record.doc_id)
    chunks.sort(key=lambda record: (record.doc_id, record.ordinal))
    return SeedBatch(tuple(documents), tuple(chunks), tuple(ordered))


def build_seed_batch(
    entries: Iterable[FilingSource],
    *,
    expected_documents: int | None = None,
    parser: FilingParser | None = None,
    chunker: Callable[[ParsedFiling], list[Chunk]] = registry_chunker,
    on_progress: OperationProgressCallback | None = None,
) -> SeedBatch:
    """Parse and chunk manifest entries into a deterministic seed batch.

    Each entry is parsed by the registry it names unless ``parser`` overrides that.
    """
    ordered = _ordered_manifest_entries(entries, expected_documents)
    documents: list[DocumentRecord] = []
    chunks: list[ChunkRecord] = []
    filings: list[ParsedFiling] = []
    if on_progress is not None:
        on_progress(OperationProgress("prepare", 0, len(ordered), "Parsing selected filings"))
    for position, entry in enumerate(ordered, start=1):
        filing, _profile = (parser or registry_for(entry.document.registry).parse)(entry)
        filings.append(filing)
        document, filing_chunks = filing_records(filing, chunker(filing))
        documents.append(document)
        chunks.extend(filing_chunks)
        if on_progress is not None:
            on_progress(
                OperationProgress(
                    "prepare", position, len(ordered), filing.source.document.document_id
                )
            )

    documents.sort(key=lambda record: record.doc_id)
    chunks.sort(key=lambda record: (record.doc_id, record.ordinal))
    return SeedBatch(tuple(documents), tuple(chunks), tuple(filings))


def prepare_seed_batch(
    manifest_path: Path | None = None,
    *,
    selection_id: str,
    embedding_provider: EmbeddingProvider | None = None,
    manifest_name: str = DEFAULT_MANIFEST_NAME,
    expected_documents: int | None = None,
    parser: FilingParser | None = None,
    chunker: Callable[[ParsedFiling], list[Chunk]] = registry_chunker,
    on_progress: OperationProgressCallback | None = None,
) -> SeedBatch:
    """Prepare and validate one complete corpus before any transaction opens.

    Use the named manifest under the configured corpus directory unless an explicit
    path is supplied. ``parser`` and ``chunker`` reach ``build_seed_batch`` unchanged,
    so a caller measuring a different chunk target does not lose registry dispatch.
    """
    path = manifest_path or get_settings().corpus_dir / manifest_name
    if embedding_provider is not None:
        if chunker is not registry_chunker:
            raise ValueError("choose either an embedding provider or an explicit chunker")
        config = embedding_chunk_config(embedding_provider)

        def configured_chunker(filing: ParsedFiling) -> list[Chunk]:
            """Use the model budget resolved once for this processing selection."""
            return chunk_filing(filing, config)

        chunker = configured_chunker
    return replace(
        build_seed_batch(
            load_manifest(path, selection_id=selection_id),
            expected_documents=expected_documents,
            parser=parser,
            chunker=chunker,
            on_progress=on_progress,
        ),
        selection_id=selection_id,
    )


class ManifestError(Exception):
    """One typed manifest failure with a stable machine-readable code.

    Owned by ingestion so every entrypoint reports the same code for the same broken
    manifest; a new failure mode added here reaches the CLI and the API together.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def load_seed_batch(
    manifest_path: Path,
    *,
    selection_id: str,
    embedding_provider: EmbeddingProvider | None = None,
    expected_documents: int | None = None,
    on_progress: OperationProgressCallback | None = None,
) -> SeedBatch:
    """Prepare one manifest, mapping every expected failure to a ``ManifestError``.

    Parameters
    ----------
    manifest_path : Path
        Explicit manifest file location.
    expected_documents : int | None
        Required document count, or ``None`` to accept any nonempty corpus.

    Returns
    -------
    SeedBatch
        Validated corpus batch ready to persist.

    Raises
    ------
    ManifestError
        With one of the stable codes ``manifest_not_found``, ``invalid_manifest_json``,
        ``invalid_manifest_encoding``, ``corpus_file_not_found``, ``invalid_manifest``.
    """
    if not manifest_path.is_file():
        raise ManifestError(
            "manifest_not_found",
            f"Manifest file was not found: {manifest_path}",
        )
    try:
        return prepare_seed_batch(
            manifest_path,
            selection_id=selection_id,
            embedding_provider=embedding_provider,
            expected_documents=expected_documents,
            on_progress=on_progress,
        )
    except json.JSONDecodeError as error:
        raise ManifestError(
            "invalid_manifest_json",
            f"Manifest is not valid JSON at line {error.lineno} column {error.colno}.",
        ) from error
    except UnicodeDecodeError as error:
        raise ManifestError(
            "invalid_manifest_encoding",
            "Manifest must be UTF-8 text.",
        ) from error
    except FileNotFoundError as error:
        raise ManifestError(
            "corpus_file_not_found",
            f"Corpus file was not found: {error.filename}",
        ) from error
    except ValueError as error:
        raise ManifestError("invalid_manifest", str(error)) from error


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

    chunk_keys: dict[str, list[str]] = {record.doc_id: [] for record in batch.documents}
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
    from app.retrieval.bm25 import backfill_term_stats

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
