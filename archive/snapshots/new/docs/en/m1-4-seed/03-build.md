# M1.4 Build — Load It Twice, Get the Same Database

## Everything so far dies with the process

M1.1 through M1.3 completed an in-memory pipeline. HTML cut into Blocks, tables folded into markdown, 9,172 citable chunks assembled. Run it any number of times and the result is the same.

But it is all Python objects. When the process ends they are gone. To search, they have to go into a database.

An `INSERT` statement seems sufficient. It works fine — once. The problem is the **second** time.

## Re-runs are unavoidable

These things will happen.

- a parser bug is fixed → reload
- chunk size changes from 1,200 to 800 → reload
- a new filing arrives → reload

With a plain `INSERT`, the second run doubles the data. Search returns the same paragraph twice.

So delete everything and reload each time? Here the real cost appears. **The embeddings M2 computed go with it.** Embedding 9,172 chunks means real API calls and real money. Recomputing all of that because a parser comment changed makes no sense.

## What this module solves: idempotent persistence

Two goals.

1. **Load the same corpus twice and the database is identical both times.** 2. **When something changes and it is reloaded, only the changed data updates and the remaining embeddings survive.**

The second one especially. If a parser fix changes the text of 30 chunks out of 9,172, only those 30 should lose their embeddings while the other 9,142 keep theirs.

The solution splits three ways.

**First, validate everything before opening a transaction.** SHA-256, source bounds, and ordinal density are checked before a single line of SQL runs. Finding bad data mid transaction means undoing what was already written; not starting is simpler.

**Second, UPSERT rather than INSERT.** PostgreSQL's `INSERT ... ON CONFLICT DO UPDATE` does "update if present, insert if not" atomically. The conflict key for chunks is the `(doc_id, ordinal)` built in M1.3.

**Third, one transaction for the whole thing.** If document 15 of 20 fails while the first 14 are committed, the database holds **a half corpus nobody has validated.** It must all commit or all roll back.

## Starting conditions

M1.3 must pass and produce deterministic chunks for all 20 manifest documents. This layer never reopens source HTML and never rebuilds chunks; it only stores what M1.3 handed over.

L1 builds the models and validated records, L2 the PostgreSQL upserts, L3 the transaction and CLI.

---

## Persistence does not make parsing decisions

```
ParsedFiling + Chunk[]
    │
    ▼
L1  Validated immutable records              no reopening of source HTML
    │
    ▼
L2  PostgreSQL conflict statements           upsert + embedding invalidation
    │
    ▼
L3  One transaction + CLI                    atomic batch, stale cleanup
```

Validation finishes before a transaction opens. Persistence stores the source identity, evidence body, retrieval context, and coordinates already decided by M1.1–M1.3. The table below is the order in which those boundaries become code.

| Layer | Responsibility | Primary tests |
|---|---|---|
| L1 | Models, immutable records, validation, deterministic conversion | `test_01_models.py`, `test_02_records.py` |
| L2 | PostgreSQL conflict statements and embedding invalidation | `test_03_upserts.py` |
| L3 | Atomic batching, stale cleanup, corpus proof, rerun proof | `test_03_upserts.py` through `test_05_postgres.py` |

---

## L1 — Make the corpus trustworthy before writing SQL

### Discard one misconception before starting

L1 is not an exercise in memorizing SQLAlchemy syntax. Neither the ORM classes such as `Document` and `Chunk` nor the dataclasses such as `DocumentRecord` are source code that SQLAlchemy generated for us. We design both, but they own different responsibilities.

This layer has one goal:

**Validate the entire parse in memory, create one `SeedBatch`, and only then allow SQL.**

```text
ParsedFiling + Chunk[]
          │
          ├── rules within one row ──> DocumentRecord + ChunkRecord[]
          │
          └── rules across rows ─────> SeedBatch
                                          │
                                          └── L2 UPSERT → L3 transaction
```

Persisting each filing as soon as it is parsed can leave only the first 14 documents when the 15th fails. It also mixes data failures with connection failures in the same storage loop. Separating `SeedBatch` construction from database writes makes a bad corpus fail before a transaction is even opened.

### What to define, what to implement, and what to inspect

| Section | Learning action | What you should take away |
|---|---|---|
| `app/config.py` | **Define the settings schema** | Settings have one owner. |
| `app/db/models.py` field declarations | **Define mappings, then inspect key constraints** | A Python mapping becomes database constraints. |
| `DocumentRecord` | Define fields and `values()`; **implement** `__post_init__()` | Validation within one document row. |
| `ChunkRecord` | **Implement** `__post_init__()` | Evidence, index text, and source coordinates stay consistent. |
| `SeedBatch` | **Implement** the batch invariants | Provenance invariants that cross rows. |
| Conversion-function field mappings | **Define mappings, then inspect boundary conversions** | M1.3 objects become database inputs. |
| Conversion guards and sorting | **Implement** the core logic | Determinism and a fail-closed boundary. |

Memorizing repeated field names is not the objective. The objective is to explain which invalid states the code can no longer represent.

### 1. Lay down the runtime foundation — define the settings schema

The L1 tests import settings and ORM models during collection, so create `app/config.py` first. Use the definition below to establish the settings schema.

#### Create `app/config.py` — shared settings

**Learning action — define the structure:** do not memorize the field declarations. Verify that every consumer reaches settings through this one file.

```python
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://filing:filing@localhost:5432/filing"
    corpus_dir: Path = Path("data/corpus")
    embedding_provider: Literal["openai", "deterministic"] = "openai"
    embedding_model: str = "text-embedding-3-small"
    embed_dim: Literal[384] = 384
    embedding_batch_size: int = Field(default=128, gt=0, le=2048)
    openai_api_key: SecretStr | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

**Lines you must notice**

- `SettingsConfigDict(env_file=".env", extra="ignore")`: read the environment file without admitting unknown keys into the settings object.
- `@lru_cache`: repeated calls do not construct unrelated settings objects.
- `embed_dim`: the ORM's `Vector(DIM)` and the embedding provider share one dimension.

### 2. The ORM is a database contract, not generated source code

`app/db/models.py` declares **what PostgreSQL is allowed to store**. An ORM removes repeated SQL; it does not decide primary keys, foreign keys, nullability, or uniqueness for us.

Read fields in groups instead of one at a time.

| Model | Field group | Responsibility |
|---|---|---|
| `Document` | `doc_id`, `ticker`, `cik` | Identify the filing and company. |
| `Document` | `fiscal_year`, `form`, dates, accession, URL | Preserve submission metadata. |
| `Document` | `parse_status`, `item_index` | Preserve parser outcomes and statuses. |
| `Document` | `source_length`, `source_sha256` | Bind every citation coordinate to one source snapshot. |
| `Chunk` | `doc_id`, `ordinal` | Define a chunk's logical position inside a document. |
| `Chunk` | `body`, `start_char`, `end_char`, `source_sha256` | Preserve evidence that can be reopened in the source. |
| `Chunk` | `context_header`, `index_text`, `embedding`, `content_tsv` | Keep search representations separate from evidence text. |

```text
Document (PK: doc_id)
    1
    │
    └────< N  Chunk (FK: doc_id, UNIQUE: doc_id + ordinal)
```

#### Create `app/db/models.py` — document and chunk ORM models

**Learning action — define the models, then inspect the design:** create the model declarations, then locate and mark the six decisions listed below.

```python
"""SQLAlchemy models for source-cited filing chunks."""

from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Computed,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, synonym

from app.config import get_settings

DIM = get_settings().embed_dim


class Base(DeclarativeBase):
    """Declarative base for application tables."""


class Document(Base):
    """One immutable SEC filing snapshot and its identifying metadata."""

    __tablename__ = "documents"

    doc_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    ticker: Mapped[str] = mapped_column(String(16), nullable=False)
    cik: Mapped[int] = mapped_column(BigInteger, nullable=False)
    fiscal_year: Mapped[int] = mapped_column(nullable=False)
    form: Mapped[str] = mapped_column(String(16), nullable=False)
    filing_date: Mapped[str] = mapped_column(String(10), nullable=False)
    report_period: Mapped[str] = mapped_column(String(10), nullable=False)
    accession: Mapped[str] = mapped_column(String(32), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    parse_status: Mapped[str] = mapped_column(String(32), nullable=False)
    item_index: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    source_length: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "parse_status IN ('parsed', 'needs_profile_update')",
            name="ck_documents_parse_status",
        ),
        CheckConstraint("source_length > 0", name="ck_documents_source_length_positive"),
        CheckConstraint(
            "source_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_documents_source_sha256_format",
        ),
    )


class Chunk(Base):
    """A source-cited retrieval unit with separate evidence and context text."""

    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    doc_id: Mapped[str] = mapped_column(
        ForeignKey("documents.doc_id", ondelete="CASCADE"), index=True, nullable=False
    )
    item: Mapped[str | None] = mapped_column(String(8), nullable=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    ordinal: Mapped[int] = mapped_column(nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    context_header: Mapped[str] = mapped_column(Text, nullable=False)
    index_text: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = synonym("index_text")
    start_char: Mapped[int] = mapped_column(BigInteger, nullable=False)
    end_char: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    citation: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(DIM), nullable=True)
    content_tsv: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('english', index_text)", persisted=True),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("doc_id", "ordinal", name="uq_doc_ordinal"),
        CheckConstraint("ordinal >= 0", name="ck_chunks_ordinal_nonnegative"),
        CheckConstraint("kind IN ('text', 'table')", name="ck_chunks_kind"),
        CheckConstraint("start_char >= 0", name="ck_chunks_start_nonnegative"),
        CheckConstraint("end_char > start_char", name="ck_chunks_span_order"),
        CheckConstraint(
            "source_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_chunks_source_sha256_format",
        ),
        Index("ix_chunks_tsv", "content_tsv", postgresql_using="gin"),
    )
```

**Six places you must inspect**

| Code | Meaning to read from it |
|---|---|
| `ForeignKey(..., ondelete="CASCADE")` | Deleting a document also deletes chunks derived from it. |
| `UniqueConstraint("doc_id", "ordinal")` | The same logical chunk cannot be stored twice for one document. |
| `end_char > start_char` | The database rejects empty and reversed citation spans. |
| `embedding ... nullable=True` | `NULL` means not computed yet, not corrupt data. |
| `Computed("to_tsvector(...)")` | PostgreSQL rebuilds the search vector when `index_text` changes. |
| `content = synonym("index_text")` | Preserve the M1.3 name without creating a duplicate column. |

No running PostgreSQL instance is needed yet. The test inspects the metadata SQLAlchemy constructed.

```bash
uv run pytest tests/db/test_01_models.py -q
```

Do not continue to business logic if this test fails. A column, constraint, or generated value already disagrees with the contract.

### 3. The real L1 begins here — the pre-SQL record boundary

`DocumentRecord`, `ChunkRecord`, and `SeedBatch` are not SQLAlchemy models. They form an application validation layer built with the standard-library `dataclass`.

One correction matters here: type annotations do not validate runtime values automatically. `frozen=True` prevents field reassignment after construction, and `slots=True` prevents undeclared attributes from being attached. Only conditions we explicitly write in `__post_init__()` enforce domain rules.

#### 3.1 Define the `app/ingestion/seed.py` scaffold

These imports include `case`, `delete`, and `AsyncSession`, which L2 and L3 will use. Later layers append to this same file, so prepare the imports once now. Use this block to establish the module scaffold; the import list itself is not today's learning target.

```python
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
```

#### 3.2 `app/ingestion/seed.py` — validate one document row with `DocumentRecord`

**Learning action — implement the validation:** define the field list and `values()` mapping first. Then implement `__post_init__()` from top to bottom and identify the damaged input stopped by each `raise`.

```python
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
```

**Lines you must notice**

- `missing` checks for empty values, not merely whether attributes exist.
- Parser status and Item status use different allowlists.
- `json.dumps(...)` proves that `item_index` can enter PostgreSQL `JSONB`.
- `values()` contains only values supplied on insert, not values the ORM computes.

#### 3.3 `app/ingestion/seed.py` — validate search text and evidence with `ChunkRecord`

**Learning action — implement the core validation:** the validation is compact and every line connects directly to the M1.3 design. Do not skip `expected_index_text` or the half-open span check.

```python
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
```

**The code you must notice**

```python
expected_index_text = (
    f"{self.context_header}\n\n{self.body}" if self.context_header else self.body
)
```

`body` is source-derived evidence that can be cited. `context_header` is synthetic search context. `index_text` is their search representation. Without this check, the three fields could describe different content while still reaching the database.

#### 3.4 `app/ingestion/seed.py` — catch cross-row errors with `SeedBatch`

**Learning action — implement the batch invariants:** this is the most important code in L1. As you implement each condition, distinguish rules checkable from one `record` alone from rules that require the whole batch.

```python
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
```

`SeedBatch` answers these questions:

- Does every chunk refer to a document that exists?
- Did the document and chunk come from the same SHA-256 source?
- Does every chunk span stay within the document length?
- Is `(doc_id, ordinal)` ordering deterministic?
- Are ordinals dense per document: `0, 1, 2, ...` with no gaps?

The last condition enables L3's stale-chunk cleanup. If a new result has 495 chunks, dense ordinals are what make deleting `ordinal >= 495` safe.

The result type and SHA-256 helper below are short support code. Add them as written.

```python
@dataclass(frozen=True, slots=True)
class SeedResult:
    """Committed row counts for one seed operation."""

    documents: int
    chunks: int


def _require_sha256(value: str, *, owner: str) -> None:
    if SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{owner} must have a lowercase hexadecimal SHA-256")
```

### 4. Convert M1.3 objects into validated records

So far we have defined the shape of safe objects. Now convert `ParsedFiling` and `Chunk` into those objects.

#### 4.1 `app/ingestion/seed.py` — map document fields and inspect boundary conversions

**Learning action — define mappings, then inspect boundaries:** complete the field mappings, then focus on where CIK changes from text to integer and where the JSON round trip occurs.

```python
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
```

`json.loads(json.dumps(..., sort_keys=True))` is not a pass-through. It rejects objects that JSON cannot represent and produces a normalized value detached from the input.

#### 4.2 `app/ingestion/seed.py` — implement chunk provenance guards

**Learning action — implement guards and define constructor mappings:** some rules are checked before constructing `ChunkRecord` so the error can point directly to the offending M1.3 object.

```python
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
```

Nothing here repairs an error and continues. A wrong `doc_id`, empty body, reversed span, or different source hash means that corpus is not eligible for persistence.

#### 4.3 `app/ingestion/seed.py` — sort the corpus and assemble `SeedBatch`

**Learning action — implement sorting and the final return:** define the delegation in `filing_records()` and the field mappings. Then implement `build_seed_batch()` while tracking exactly when it sorts inputs, documents, and chunks.

```python
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
```

Sorting is not presentation polish. It gives repeated runs of the same manifest the same record order and lets `SeedBatch` reject duplicates and reversals with a linear check.

### 5. Read tests as the design specification, not the answer key

Read test names first. Each broken value points back to one boundary you just wrote.

| Value the test breaks | Contract being protected |
|---|---|
| Unknown parser or Item status | Persist only parser outcomes the system understands. |
| A chunk with another `doc_id` | Evidence from different documents never mixes. |
| Ordinals `0, 1, 3` | Chunk order and stale-row cleanup remain safe. |
| Empty `body` or invalid span | Citable evidence actually exists. |
| A different `source_sha256` | Coordinates and the source snapshot have the same version. |
| Stale `index_text` | Indexed text is derived exactly from body and context. |
| Unexpected manifest size | A partial corpus is not mistaken for a complete input. |

```bash
uv run pytest tests/db/test_01_models.py tests/db/test_02_records.py -q
```

After the full test passes, revisit only three failure families.

```bash
uv run pytest tests/db/test_02_records.py \
  -k "broken_provenance or cross_record_provenance or inconsistent_index_text" -q
```

Do not stop at a green test. Explain which invalid database state each exception would allow if removed. Once you can do that, you have learned L1.

### 6. What you should be able to explain now

- **Why are ORM models and `DocumentRecord` separate layers?**
  - **Answer:** ORM models define the database schema and constraints, while `DocumentRecord` validates application data in memory before any database work. This separation lets corpus correctness be tested without a connection and keeps persistence from making parsing decisions.
- **Which validation do `frozen=True` and type annotations not perform?**
  - **Answer:** `frozen=True` prevents reassignment and annotations describe intended types, but neither checks runtime domain values. Empty identifiers, unsupported statuses, invalid spans, malformed hashes, and inconsistent derived text still require explicit validation.
- **Why keep both database `CheckConstraint`s and `__post_init__()` checks?**
  - **Answer:** `__post_init__()` rejects bad data early with application-specific errors before SQL starts. Database constraints remain the final defense for every writer, including code paths that bypass these dataclasses.
- **How do SHA-256 and half-open coordinates form one provenance contract?**
  - **Answer:** SHA-256 pins the exact source snapshot, and `[start_char, end_char)` identifies an unambiguous slice within that snapshot. Either component without the other cannot prove which evidence text the coordinates describe.
- **Why must `SeedBatch` exist before SQL or a transaction?**
  - **Answer:** `SeedBatch` validates cross-record provenance, document membership, deterministic ordering, and dense ordinals before SQL begins. An unexpectedly partial manifest is a separate case: the count guard in `build_seed_batch(expected_documents=...)` rejects it before creating the batch.

If you can answer those five questions, you do not need to memorize the field declarations. L2 now has one job left: turn validated records into PostgreSQL UPSERT statements.

---

## L2 — Build dialect-specific upserts

### Deciding when to throw an embedding away

Now the problem named earlier gets solved in code. Concretely:

1. Seed the corpus. 2. M2 embeds all 9,172 chunks (real API calls, real cost). 3. Fix a parser bug, changing the text of 30 chunks. 4. Re-seed.

Those 30 chunks' existing embeddings are **stale** — vectors computed from text that is no longer what is stored. Leave them and retrieval misbehaves: the vector points at A while the displayed text is B.

The other 9,142 are fine. Their text is unchanged, so their vectors remain valid.

**Clear everything** and it is safe but 9,142 embeddings are recomputed for nothing. **Keep everything** and 30 stay wrong.

So it becomes conditional. **Preserve the embedding when `index_text` is unchanged, set it to NULL when it changed.** M2 then picks out just those 30 with `WHERE embedding IS NULL`.

It is tempting to do this in two steps — query what changed, then update. That opens a race between them.

Putting PostgreSQL's `CASE` expression inside `ON CONFLICT DO UPDATE` makes it **one atomic operation.**

```python
"embedding": case(
    (ChunkModel.index_text == excluded.index_text, ChunkModel.embedding),
    else_=None,
)
```

When the existing row's `index_text` matches the new value, keep the old embedding. Otherwise, set it to NULL. No second query, no race condition.

### What to define, what to implement, and what to inspect

L2 executes no SQL. It appends three functions that **decide the shape of the SQL that will run** to the same `app/ingestion/seed.py`.

| Area | Learning action | What to take away |
|---|---|---|
| `prepare_seed_batch` | **Define the structure** | Corpus assembly finishes outside the transaction |
| `document_upsert_statement`'s `set_` mapping | **Write the field mapping, then inspect the conflict key** | Repetitive declaration versus design judgment |
| `chunk_upsert_statement`'s `embedding` expression | **Implement** the invalidation rule yourself | When expensive derived data is thrown away |

Memorizing the 12 column names in the `set_` dictionary is not the goal. Being able to say **which columns come straight from `excluded` and which single column is conditional** is.

### 1. Finish corpus assembly outside the transaction

`build_seed_batch()` from L1 takes an already-parsed manifest. But callers still have to know where the manifest path comes from. That decision collapses into one function.

There is a reason this function opens L2. **The corpus must be complete before a transaction opens.** A parse error or a manifest count mismatch has to blow up before a database connection is taken.

#### Extend `app/ingestion/seed.py` — from manifest to batch

**Learning action — define the structure:** a two-line function. What matters here is not the code but where it sits.

<!-- src: app/ingestion/seed.py::prepare_seed_batch -->
```python
def prepare_seed_batch(
    manifest_path: Path | None = None, *, expected_documents: int | None = EXPECTED_DOCUMENTS
) -> SeedBatch:
    """Build the complete corpus batch before opening a database transaction."""
    path = manifest_path or get_settings().corpus_dir / "manifest.json"
    return build_seed_batch(load_manifest(path), expected_documents=expected_documents)
```

**What to look for in the code**

- No `AsyncSession` in the signature. This function knows nothing about the database.
- `manifest_path or get_settings()...`: tests pass a path, the CLI defers to settings.
- The return type is `SeedBatch`. Failing L1's batch invariants raises right here.

### 2. Document upsert — repetitive mapping and one design judgment

The document upsert is mostly mechanical. All 12 columns in the `set_` dictionary take the new value straight from `excluded`. A re-seed always overwrites filing metadata with the fresh parse result.

Say that out loud, because it is a policy and not an accident: for a document, the newest parse always wins. If the parser learned to read a filing date it previously missed, the re-seed replaces the old value without asking. That is safe here precisely because nothing downstream has been computed from those columns — no embedding, no evaluation baseline depends on `filing_date`. Compare that with the chunk table, one step from now, where overwriting blindly would throw away something expensive.

Only one thing is worth remembering from this function: **what the conflict key is.**

#### Extend `app/ingestion/seed.py` — document upsert

**Learning action — write the field mapping:** transcribe column names from the `Document` model. Once they are all in, explain why `index_elements` is `doc_id` alone.

<!-- src: app/ingestion/seed.py::document_upsert_statement -->
```python
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
```

**What to look for in the code**

- `if not records: raise ValueError(...)`: building `insert().values([])` from an empty list produces an obscure compile-time error. Reject it at the call boundary instead.
- `insert(Document).values([...])`: 20 documents leave in **one** statement, one round trip.
- `excluded` is the virtual table PostgreSQL exposes per conflicting row. It holds the values being inserted; existing row values are read as `Document.<column>`. That distinction is the axis of all of L2.
- `set_` does not contain `doc_id`. There is no reason to overwrite the conflict key with itself.

### 3. Chunk upsert — one expression carries embedding invalidation

This is the core of L2. Nine columns come straight from `excluded`, exactly like the document upsert. Only the tenth column, `embedding`, is handled differently.

That single exception is the whole reason this project does not use a generic "upsert everything" helper. A generic helper has one policy — replace — and applies it to every column. Here, nine columns want replacement and one wants a conditional decision that depends on comparing an old value against a new one.

You could push that decision out of SQL: fetch the rows, compare in Python, then write. Many codebases do. The section below explains why that shape is worse, and it is worth holding the question in mind while reading the code.

`embedding` is unlike every other column. It is not a value produced by parsing but **derived data that was paid for.** M1.4 never fills this column, yet whether a re-seed **discards it** has to be decided now.

#### Extend `app/ingestion/seed.py` — chunk upsert

**Learning action — implement the invalidation rule:** write the first nine columns in the same shape as the document upsert. Implement the `embedding` entry yourself before comparing against the code below.

<!-- src: app/ingestion/seed.py::chunk_upsert_statement -->
```python
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
```

**What to look for in the code**

- `index_elements=[ChunkModel.doc_id, ChunkModel.ordinal]`: chunk identity is a composite key. It holds only because M1.3 numbered ordinals densely from 0.
- What `case()` compares: the left side `ChunkModel.index_text` is the **value already in the database**, the right side `excluded.index_text` is the **value being written**. Swap them and the expression means nothing.
- Why the condition uses `index_text` and not `body`: the embedding was computed from `index_text`. Even with an identical `body`, a changed `context_header` changes `index_text`, and the vector is invalid.
- `record.values()` carries no `embedding` key. The insert path omits the column entirely, so the database default NULL applies. M1.4's promise not to write embeddings lives here.

### Why the dialect-specific `insert` is imported

The import line is not `from sqlalchemy import insert` but `from sqlalchemy.dialects.postgresql import insert`.

The generic `insert()` has no `on_conflict_do_update()`, because `ON CONFLICT` is PostgreSQL syntax. Other databases use `MERGE` or `INSERT OR REPLACE`.

Portability is given up, and something is gained. **The conflict key is written explicitly in the code.**

```python
index_elements=[ChunkModel.doc_id, ChunkModel.ordinal]
```

Without it you end up with an exception-driven implementation — "INSERT and catch `IntegrityError`, then UPDATE." Then nothing in the code records which constraint provides idempotency, and dropping that index breaks it silently.

**When idempotency depends on a specific database feature, it is better to surface that dependency than hide it.**

### Focused tests and the contracts they protect

```bash
uv run pytest tests/db/test_03_upserts.py -k "document_upsert or chunk_upsert" -q
```

These tests never connect to a database. They compile the statement with the PostgreSQL dialect and inspect **the resulting SQL string.** Each test protects one contract.

| What the test checks | Contract being protected |
|---|---|
| Document SQL targets conflict on `doc_id` | One filing never grows into two rows. |
| Chunk SQL targets conflict on `(doc_id, ordinal)` | Chunk identity is its position inside a document. |
| No `embedding` in the inserted column list | M1.4 writes no vectors. |
| `embedding` preserved when `index_text` matches | Valid embeddings are not burned on recomputation. |
| `embedding` set to NULL when `index_text` differs | A stale vector never points at new text. |

When a test fails, print the compiled statement and find the missing clause. Do not stop at green: explain out loud what retrieval returns if those last two rows are swapped.

### Where you are now

Two statement builders now compile to idempotent upserts, and embedding preservation or invalidation is decided inside a single atomic expression.

A database is still not required. Compiling the statement and checking the string is enough to test it. A real connection appears for the first time in L3's optional exercise.

### UPSERT and the transaction protect different scopes

Both are described as atomic, but they guarantee different scopes.

| Mechanism | Scope protected | Guarantee in this project |
|---|---|---|
| UPSERT | insert-or-update decision for one conflict key | Updates existing chunks without duplicates and invalidates only embeddings that need it. |
| Transaction | the complete seed batch made of multiple SQL statements | Applies every document and chunk or rolls all of them back. |

UPSERT alone updates each row safely but can leave a partial corpus after writing 15 of 20 documents. A transaction around ordinary INSERT statements can roll everything back, but rerunning the same corpus then hits unique-key conflicts. That is why L2's UPSERT and L3's single transaction are both required. It is the same idea as running several upserts inside a TypeScript ORM transaction callback.

---

## L3 — Own one transaction

### Why the transaction has to be exactly one

The corpus is one version as a whole. A state where 15 of 20 documents are the new version and 5 are the old one is **a combination nobody ever validated.** Measuring retrieval quality against it produces numbers that mean nothing.

Chunks are the same. Failing on the third of five batches leaves some document with half its chunks. Search that document and its entire tail is missing.

`async with session.begin()` prevents this. Success commits everything, an exception rolls everything back. No intermediate state exists.

### Old rows survive when chunk counts shrink

Re-chunking can produce **fewer** chunks than before — a parser fix that merges two blocks into one.

Say NVDA-FY2024 had 500 chunks and now has 495. The upsert updates 0 through 494. What about 495 through 499? **They stay.** An upsert does not delete rows that disappeared.

Those five rows are dangerous. They hold text from an older parse while their coordinates point at the current document. If retrieval hits them, it **cites content that does not exist.**

Cleanup is required, and this is where M1.3's dense ordinals pay off.

```sql
DELETE FROM chunks WHERE doc_id = ? AND ordinal >= 495
```

One line does it. No tracking which ordinals used to exist, no full scan. **A single invariant — ordinals run from 0 with no gaps — makes this cleanup trivial.**

### What to define, what to implement, and what to inspect

L3 binds every earlier piece into one executable operation. Only three phases happen inside the transaction.

```text
async with session.begin():
        │
        ├── 1. document UPSERT        x1
        │
        ├── 2. chunk UPSERT           xN   (500 rows per statement)
        │
        └── 3. stale-ordinal DELETE   xN   (1 per document)
        │
    ────┴──── COMMIT all  or  ROLLBACK all
```

| Area | Learning action | What to take away |
|---|---|---|
| `_batches` | **Define the structure** | Where a protocol limit reshapes code |
| Transaction block in `persist_seed_batch` | **Implement** the three-phase order yourself | How far the atomicity boundary reaches |
| Precondition checks in `persist_seed_batch` | **Implement** the rejection rules yourself | How to block a silent partial commit |
| `seed_corpus` and the CLI | **Define the structure, then inspect the entry points** | Library boundary versus execution boundary |
| Later models in `app/db/models.py` | **Write the model declarations** | Why later modules share one registry |
| `app/db/session.py` and `bootstrap.py` | **Write the configuration, then confirm the responsibility** | Bootstrap versus migration |

### 1. Cut batches down to the protocol limit

9,172 chunks cannot travel in a single statement. Start with the helper that cuts them up.

It is worth being clear that this is not a performance tweak. A performance tweak is optional; this one is a hard protocol wall. Build the single-statement version and it does not run slowly — it fails outright, with an error about parameter counts that says nothing about chunks or filings and sends you looking in the wrong place entirely.

Four lines of generator, and they exist because a wire format has a limit.

#### Extend `app/ingestion/seed.py` — chunk batch splitting

**Learning action — define the structure:** one generator. Why it is needed is covered in the section right below.

<!-- src: app/ingestion/seed.py::_batches -->
```python
def _batches(records: Sequence[ChunkRecord], size: int) -> Iterable[Sequence[ChunkRecord]]:
    if size <= 0:
        raise ValueError("chunk batch size must be positive")
    for start in range(0, len(records), size):
        yield records[start : start + size]
```

**What to look for in the code**

- It yields slices. No copy of all 9,172 records is materialized at once.
- The `size <= 0` check exists in two places: here and in `persist_seed_batch`. A generator body does not run until the first `next()`, so failing a bad argument **before the transaction opens** requires the outer check too.

### Why chunks are split into batches and documents are not

Putting 9,172 chunks into one `INSERT ... VALUES (...)` produces a statement with 9,172 value tuples. At 11 columns that is over 100,000 parameters.

It exceeds the PostgreSQL protocol parameter limit (65535), and even below the limit, building and parsing that statement costs a lot of memory.

Cutting at 500 rows keeps each statement at 5,500 parameters. The batching benefit — fewer round trips — is fully retained without hitting the limit.

Documents number only 20, so there is no reason to split them. **Generalizing where it is not needed only adds complexity.**

### 2. The single function that owns the transaction

This is where all of M1.4 converges. Unlike every other function here, this one **has side effects.** Its contract is therefore strict.

- the incoming session must have no open transaction
- success commits the whole batch
- an exception in any statement rolls the whole batch back

Note that `chunk_counts` is computed **outside** the transaction. Knowing how many chunks each document has in this batch is what sets phase 3's `ordinal >= count` boundary. Documents present in the batch with zero chunks must already be seeded by `dict.fromkeys(...)`, so that old rows of a "document whose chunks all disappeared" are removed too.

#### Extend `app/ingestion/seed.py` — single-transaction persistence

**Learning action — implement the transaction boundary:** write the signature and docstring first. Then implement the two precondition checks and the three phases inside `async with session.begin()` yourself.

<!-- src: app/ingestion/seed.py::persist_seed_batch -->
```python
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
```

**What to look for in the code**

- Both precondition checks sit **before** `session.begin()`. A call that will be rejected is rejected before a transaction opens.
- `dict.fromkeys(...)` seeds documents first, then chunks increment. A document left with zero chunks still gets a key, so phase 3 issues `ordinal >= 0` — a full delete.
- DELETE comes **after** the upserts. Reverse the order and the deletion uses pre-update counts, which can remove rows just written.
- The `return` sits **outside** the `async with` block. `SeedResult` is built only after the commit actually completed. Inside the block, a failed commit would be reported as success.
- All three phases use `session.execute()`. No ORM instances are built and handed to `session.add()`. Instantiating and change-tracking 10,000 rows buys nothing here.

### Why `session.in_transaction()` is checked first

The check is the first line of the function. It looks defensive, but it prevents a real hazard.

If a caller passes **a session that already has an open transaction**, `session.begin()` does not create a new transaction — it creates a **savepoint** (a nested transaction). SQLAlchemy does that automatically.

The problem is that rolling back a savepoint **does not undo earlier writes in the outer transaction.** So even when `persist_seed_batch` fails, what the outer scope already wrote can still be committed. The partial commit this design worked so hard to prevent is back.

And it happens quietly. No exception is raised, and the code still reads as one transaction.

So it is rejected outright. This function must own its transaction **completely**, and if it cannot, it does not start.

### 3. Two entry points — library and command line

`persist_seed_batch()` takes an already-built batch. For callers that want to start from a manifest, one thin composition function is added.

The obvious question is why this is a separate function at all rather than a default argument on `persist_seed_batch()`. The answer is that merging them would put manifest reading and transaction ownership in one place, and those two jobs fail for completely different reasons — a missing file versus a lost connection. Keeping them apart is what lets the L1 tests build a corpus with no database anywhere in sight, which is the property this whole module was arranged around.

#### Extend `app/ingestion/seed.py` — library entry point

**Learning action — define the structure:** two lines. The absence of new logic is itself design information.

<!-- src: app/ingestion/seed.py::seed_corpus -->
```python
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
```

What matters is that preparation and persistence remain separate functions. Tests can call `prepare_seed_batch()` alone and validate the corpus with no database.

The command-line entry point wraps the same functions in argument parsing and session lifetime management.

#### Complete `app/ingestion/seed.py` — command-line entry point

**Learning action — define the structure, then inspect the entry point:** transcribe the argument definitions as they are. Work out only the call order inside `_run_cli()`.

<!-- src: app/ingestion/seed.py::_arguments,_run_cli,main -->
```python
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
```

Append the module execution guard at the end of the file. Those two lines are what make `python -m app.ingestion.seed` work.

```python
if __name__ == "__main__":
    main()
```

**What to look for in the code**

- The two imports inside `_run_cli()` are in **the function**, not at module top level. `app.db.session` reads `database_url` from settings and constructs an engine at import time. Hoisting it would make `seed.py` build an engine just to be imported, tying every database-free test in L1 and L2 to database configuration and the async driver.
- `prepare_seed_batch()` runs **before** `bootstrap_schema()`. A broken manifest fails before the schema is touched.
- `async with Session()` opens and closes the session. The transaction inside it is owned by `persist_seed_batch()`. **Connection lifetime and transaction lifetime are different layers.**

### 4. Models and infrastructure later modules share

Outside M1.4, later modules share the same SQLAlchemy registry. One registry is what makes foreign keys resolve and lets `create_all()` build every table. So to match the final `app/db/models.py` exactly, add the remaining shared models below L1's `Chunk` class.

None of these three models is used yet. Do not read them field by field — confirm the responsibilities only.

| Model | Owning module | Responsibility |
|---|---|---|
| `EvalResult` | M3 | Persists one evaluation run as a comparable regression baseline. |
| `Run` | M4 | Persists one workflow result with its status and budget usage. |
| `Trace` | M4 | Persists the individual LLM calls belonging to one `Run`. |

Only `Trace.run_id`'s `ondelete="CASCADE"` and `uq_traces_run_step` are worth a look now. A trace never outlives the run it belongs to, and step numbers cannot repeat within a run.

#### Extend `app/db/models.py` — shared persistence models

**Learning action — write the model declarations:** do not memorize constraint names. Come back here when these tables reappear in later modules.

```python
class EvalResult(Base):
    """One persisted evaluation run used for comparable regression baselines."""

    __tablename__ = "eval_results"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    suite: Mapped[str] = mapped_column(String(128), nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    raw_artifact_path: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("btrim(suite) <> ''", name="ck_eval_results_suite_nonempty"),
        CheckConstraint(
            "jsonb_typeof(config) = 'object'",
            name="ck_eval_results_config_object",
        ),
        CheckConstraint(
            "jsonb_typeof(metrics) = 'object'",
            name="ck_eval_results_metrics_object",
        ),
        CheckConstraint(
            "btrim(raw_artifact_path) <> ''",
            name="ck_eval_results_raw_artifact_path_nonempty",
        ),
        Index("ix_eval_results_suite_created_at", "suite", "created_at"),
    )


class Run(Base):
    """One persisted workflow result, including structured failure outcomes."""

    __tablename__ = "runs"

    run_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    iterations: Mapped[int] = mapped_column(nullable=False)
    total_requests: Mapped[int] = mapped_column(nullable=False)
    total_input_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_output_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_time_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    node_path: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    report: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('ok', 'budget_exceeded', 'schema_rejected', 'error')",
            name="ck_runs_status",
        ),
        CheckConstraint("iterations >= 0", name="ck_runs_iterations_nonnegative"),
        CheckConstraint("total_requests >= 0", name="ck_runs_requests_nonnegative"),
        CheckConstraint("total_input_tokens >= 0", name="ck_runs_input_tokens_nonnegative"),
        CheckConstraint("total_output_tokens >= 0", name="ck_runs_output_tokens_nonnegative"),
        CheckConstraint("total_time_seconds >= 0", name="ck_runs_time_nonnegative"),
        CheckConstraint("btrim(system_prompt) <> ''", name="ck_runs_system_prompt_nonempty"),
        CheckConstraint("jsonb_typeof(node_path) = 'array'", name="ck_runs_node_path_array"),
        CheckConstraint(
            "report IS NULL OR jsonb_typeof(report) = 'object'",
            name="ck_runs_report_object",
        ),
        Index("ix_runs_status_created_at", "status", "created_at"),
    )


class Trace(Base):
    """One raw provider step belonging to a persisted workflow run."""

    __tablename__ = "traces"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.run_id", ondelete="CASCADE"), nullable=False
    )
    step: Mapped[int] = mapped_column(nullable=False)
    node: Mapped[str] = mapped_column(String(32), nullable=False)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    api_url: Mapped[str] = mapped_column(Text, nullable=False)
    input_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    output_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    request_time_ms: Mapped[float] = mapped_column(Float, nullable=False)
    llm_output: Mapped[str] = mapped_column(Text, nullable=False)
    retries: Mapped[int] = mapped_column(nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("run_id", "step", name="uq_traces_run_step"),
        CheckConstraint("step > 0", name="ck_traces_step_positive"),
        CheckConstraint(
            "node IN ('retrieve', 'grade', 'check', 'report')",
            name="ck_traces_node",
        ),
        CheckConstraint("btrim(model_name) <> ''", name="ck_traces_model_name_nonempty"),
        CheckConstraint("btrim(api_url) <> ''", name="ck_traces_api_url_nonempty"),
        CheckConstraint("input_tokens >= 0", name="ck_traces_input_tokens_nonnegative"),
        CheckConstraint("output_tokens >= 0", name="ck_traces_output_tokens_nonnegative"),
        CheckConstraint("request_time_ms >= 0", name="ck_traces_time_nonnegative"),
        CheckConstraint("retries >= 0", name="ck_traces_retries_nonnegative"),
        Index("ix_traces_run_step", "run_id", "step"),
    )
```

Write the canonical `app/db/session.py` so that one module owns the engine and session factory.

#### Create `app/db/session.py` — engine and session factory

**Learning action — write the configuration:** two lines, but what matters is that they run at module level.

```python
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings

engine = create_async_engine(get_settings().database_url, echo=False)
Session = async_sessionmaker(engine, expire_on_commit=False)
```

**What to look for in the code**

- Both lines execute at module top level. Importing this module reads settings and builds an engine immediately. That is exactly why `_run_cli()` defers this import into the function body.
- `expire_on_commit=False`: SQLAlchemy will not re-query attributes accessed after commit. In an async session that implicit re-query cannot happen without awaiting, so it errors.

Write the canonical `app/db/bootstrap.py`. Only `--create-schema` calls this path. It is not a replacement for schema migrations.

`Base.metadata.create_all()` reads current ORM metadata and **bootstraps missing tables for the first time.** When a `chunks` table already exists, adding a new column to the Python model does not diff the existing table into an `ALTER TABLE`, and it tracks no history of column renames or data conversions.

A migration is an explicit change record that moves an existing schema from version A to version B. It leaves new columns, constraint changes, existing-data conversion, and deployment order as reviewable steps. It is the same distinction TypeScript ORMs make between initial schema creation or schema push and versioned migration files. So `create_all()` is fine for a fresh demo database, while schema changes on a production database that already holds data belong in reviewed migrations.

#### Create `app/db/bootstrap.py` — schema bootstrap

**Learning action — define the structure:** confirm only the call order of the two functions.

```python
"""Minimal idempotent PostgreSQL schema bootstrap."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.db.models import Base


async def ensure_vector_extension(connection: AsyncConnection) -> None:
    """Enable pgvector in the current database if it is not already enabled."""
    await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))


async def bootstrap_schema(engine: AsyncEngine) -> None:
    """Enable pgvector before creating missing SQLAlchemy tables and indexes."""
    async with engine.begin() as connection:
        await ensure_vector_extension(connection)
        await connection.run_sync(Base.metadata.create_all)
```

**What to look for in the code**

- Enabling the extension comes **before** `create_all`. Because `chunks.embedding` is a `Vector` column, table creation itself fails without pgvector.
- `CREATE EXTENSION IF NOT EXISTS` and `create_all` are both idempotent. Calling this function twice is safe.

### Focused tests and the contracts they protect

```bash
uv run pytest tests/db/test_03_upserts.py -k "persist_seed_batch" -q
uv run pytest tests/db/test_04_corpus.py -q
```

The first command verifies the transaction contract with a fake session; the second assembles the entire checked-in corpus into a batch. Each test protects one contract.

| What the test checks | Contract being protected |
|---|---|
| Exactly one `begin` and one `commit` | The whole seed is one atomic unit. |
| Full rollback on a mid-batch failure | No partial corpus survives in the database. |
| Chunk statements split by batch size | The protocol parameter limit is never exceeded. |
| `RuntimeError` when handed an open transaction | Savepoint-driven silent partial commits are blocked. |
| `ValueError` when batch size is not positive | A bad argument becomes neither an infinite loop nor an empty batch. |
| 20 documents and every M1.3 chunk in the batch | Nothing is lost between manifest and batch. |

The tests isolate parser profiles in a temporary directory, so verification never modifies the checked-in corpus profile state.

### Where you are now

The persistence pipeline is complete. 20 documents and 9,172 chunks are validated, upserted, and stripped of stale ordinals **inside exactly one transaction.**

Both goals of this chapter are met. Loading the same corpus twice gives the same result, and reloading after a change invalidates only the affected embeddings.

### What you should be able to explain now

- **Why is UPSERT alone insufficient, requiring a separate transaction?**
  - **Answer:** UPSERT makes each conflict-key insert or update idempotent, but it cannot make all document, chunk, and cleanup statements one unit. The transaction prevents a failure from committing only part of the corpus.
- **What exactly breaks if a session with an open transaction is not rejected?**
  - **Answer:** In SQLAlchemy 2.x, another `begin()` raises `InvalidRequestError`; relying on that makes this function's error contract depend on library behavior. If an outer or explicitly nested transaction were allowed instead, this function would no longer own the final commit, so returning success would not prove the batch was committed.
- **Which rows disappear if DELETE is moved ahead of the upserts?**
  - **Answer:** Only stale trailing rows with `ordinal >= count` are deleted; new chunks use ordinals `0` through `count - 1`, so none of them disappear. The current order is retained because upsert-then-cleanup expresses the three persistence phases more clearly.
- **What justifies batching only chunks and not documents?**
  - **Answer:** Roughly 9,172 chunk rows with eleven columns would exceed PostgreSQL's 65,535-parameter protocol limit in one statement, while twenty document rows are far below it. Splitting documents would add machinery without solving a real limit.
- **What does `seed.py` start depending on if `_run_cli()` hoists the `app.db.session` import?**
  - **Answer:** Importing `seed.py` would immediately read database settings, create an engine, and require the async database driver. That would make otherwise database-free L1 and L2 imports and tests depend on database configuration.
- **Why must `create_all()` not be used on a production database?**
  - **Answer:** `create_all()` creates missing tables but does not turn model changes into reviewed `ALTER TABLE` operations, data conversions, or a version history. Existing production schemas require explicit, versioned migrations.

If you can answer those six questions, you understand M1.4's persistence layer.

---

## Optional exercise — check against real PostgreSQL

Every test so far **compiled SQL and checked the string.** That is fast and needs no database, but some things it cannot confirm.

- do transactions really commit
- does an exception really roll everything back
- does the `CASE` expression really preserve and invalidate embeddings

Only a live engine can prove those; syntactically valid does not mean semantically right.

The integration test knocks on the configured database with a short timeout. If it connects, it experiments inside **connection-local temporary tables**. It writes the same batch twice and checks the row count holds, plants a sentinel embedding and confirms it survives identical text, then changes `index_text` and confirms invalidation.

Temporary tables are the trick. They vanish when the connection closes, so **the real application schema is never touched.** That closes off the accident where an integration test wipes development data.

```bash
uv run pytest tests/db/test_05_postgres.py -q
```

When this command passes, the test passes when PostgreSQL is reachable. It may skip only because the configured external database is unavailable. A connected database failure is a real failure, not an acceptable skip.

Temporary tables disappear when the test connection closes. The test never resets the application schema.

---

## Command-line seed

The CLI exposes the same validated batch and transaction path through one command. Operators need a reproducible initial-schema path and a safe rerun path without a second persistence implementation.

For a fresh database:

```bash
uv run python -m app.ingestion.seed --create-schema
```

For an already migrated schema:

```bash
uv run python -m app.ingestion.seed
```

Use `--expected-documents` only when intentionally exercising another manifest. The production corpus default remains 20.

---

## Final verification

```bash
uv run pytest tests/db/test_01_models.py tests/db/test_02_records.py tests/db/test_03_upserts.py tests/db/test_04_corpus.py -q
uv run python scripts/check_doc_code.py docs/en/m1-4-seed/03-build.md docs/ko/m1-4-seed/03-build.md
uv run ruff check --no-fix app/db app/ingestion/seed.py tests/db
```

When all three commands pass with no missing-symbol skip, M1.4 is complete. The optional live test is reported separately as passed or unavailable. Fix the first failing gate before running the next one.

---

## Stage M1 is finished

That is the whole ingestion pipeline. Looking back, it came this way.

```
2 MB of HTML     ──M1.1──▶  51,879 Blocks (with source coordinates)
                              │
                   M1.2 ──▶  data tables → markdown (print layout removed)
                              │
                   M1.3 ──▶  9,172 Chunks (citations that cannot lie)
                              │
                   M1.4 ──▶  PostgreSQL rows (idempotent)
```

**Not once was an LLM used.** Parsing, table conversion, and chunking were all done with measurement and rules. So the same input always yields the same output, and every chunk is verifiable against source coordinates.

Most of a RAG system's quality is decided right here. However refined the retrieval or the prompting, there is no recovering from ingestion that broke the tables and drifted the citations.

## What this module hands to the next one

| What M1.4 produced | Receiver | What happens there |
|---|---|---|
| `chunks.index_text` | **M2** | embedding input |
| `chunks.embedding` (NULL) | **M2** | marks backfill targets |
| `chunks.content_tsv` (GIN) | **M2** | full-text search |
| `chunks.citation` / coordinates | **M4** | report citations |
| `documents` metadata | **M2** | ticker, year, Item filters |
| `eval_results` table | **M3** | stores evaluation results |
| `runs` / `traces` tables | **M4** | workflow run records |

`eval_results`, `runs`, and `traces` are created now because later modules share **the same SQLAlchemy registry**. `Base.metadata.create_all` has to build them all at once for bootstrap to stay in one place.

The next chapter, M2, attaches an embedding provider, builds pgvector cosine search and PostgreSQL full-text search separately, then fuses them with RRF. It starts by **filling the chunks where `embedding IS NULL`.**

<!-- complete-files:start -->
## Reference baseline — the complete canonical files

Create or replace the canonical paths below directly. Do not create `_mine.py` or another learner-copy module. The earlier excerpts explain individual decisions; the blocks in this section are the finished files to compare against once a checkpoint is done. Preserve the shown type annotations and English comments; `pyproject.toml` is the authoritative Ruff policy.

### M1.4 — Complete checkpoint

#### Create or replace `app/db/models.py`

<!-- file: app/db/models.py -->
```python
"""SQLAlchemy models for source-cited filing chunks."""

from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Computed,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, synonym

from app.config import get_settings

DIM = get_settings().embed_dim


class Base(DeclarativeBase):
    """Declarative base for application tables."""


class Document(Base):
    """One immutable SEC filing snapshot and its identifying metadata."""

    __tablename__ = "documents"

    doc_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    ticker: Mapped[str] = mapped_column(String(16), nullable=False)
    cik: Mapped[int] = mapped_column(BigInteger, nullable=False)
    fiscal_year: Mapped[int] = mapped_column(nullable=False)
    form: Mapped[str] = mapped_column(String(16), nullable=False)
    filing_date: Mapped[str] = mapped_column(String(10), nullable=False)
    report_period: Mapped[str] = mapped_column(String(10), nullable=False)
    accession: Mapped[str] = mapped_column(String(32), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    parse_status: Mapped[str] = mapped_column(String(32), nullable=False)
    item_index: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    source_length: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "parse_status IN ('parsed', 'needs_profile_update')",
            name="ck_documents_parse_status",
        ),
        CheckConstraint("source_length > 0", name="ck_documents_source_length_positive"),
        CheckConstraint(
            "source_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_documents_source_sha256_format",
        ),
    )


class Chunk(Base):
    """A source-cited retrieval unit with separate evidence and context text."""

    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    doc_id: Mapped[str] = mapped_column(
        ForeignKey("documents.doc_id", ondelete="CASCADE"), index=True, nullable=False
    )
    item: Mapped[str | None] = mapped_column(String(8), nullable=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    ordinal: Mapped[int] = mapped_column(nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    context_header: Mapped[str] = mapped_column(Text, nullable=False)
    index_text: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = synonym("index_text")
    start_char: Mapped[int] = mapped_column(BigInteger, nullable=False)
    end_char: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    citation: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(DIM), nullable=True)
    content_tsv: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('english', index_text)", persisted=True),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("doc_id", "ordinal", name="uq_doc_ordinal"),
        CheckConstraint("ordinal >= 0", name="ck_chunks_ordinal_nonnegative"),
        CheckConstraint("kind IN ('text', 'table')", name="ck_chunks_kind"),
        CheckConstraint("start_char >= 0", name="ck_chunks_start_nonnegative"),
        CheckConstraint("end_char > start_char", name="ck_chunks_span_order"),
        CheckConstraint(
            "source_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_chunks_source_sha256_format",
        ),
        Index("ix_chunks_tsv", "content_tsv", postgresql_using="gin"),
    )


class ChunkTerm(Base):
    """One lexeme and its frequency inside one chunk."""

    __tablename__ = "chunk_terms"

    chunk_id: Mapped[int] = mapped_column(
        ForeignKey("chunks.id", ondelete="CASCADE"), primary_key=True
    )
    lexeme: Mapped[str] = mapped_column(Text, primary_key=True)
    tf: Mapped[int] = mapped_column(nullable=False)

    __table_args__ = (
        CheckConstraint("tf > 0", name="ck_chunk_terms_tf_positive"),
        Index("ix_chunk_terms_lexeme", "lexeme"),
    )


class ChunkLength(Base):
    """Total indexed lexeme occurrences in one chunk."""

    __tablename__ = "chunk_lengths"

    chunk_id: Mapped[int] = mapped_column(
        ForeignKey("chunks.id", ondelete="CASCADE"), primary_key=True
    )
    dl: Mapped[int] = mapped_column(nullable=False)

    __table_args__ = (CheckConstraint("dl > 0", name="ck_chunk_lengths_positive"),)


class LexemeStat(Base):
    """Number of indexed chunks containing one lexeme."""

    __tablename__ = "lexeme_stats"

    lexeme: Mapped[str] = mapped_column(Text, primary_key=True)
    df: Mapped[int] = mapped_column(nullable=False)

    __table_args__ = (CheckConstraint("df > 0", name="ck_lexeme_stats_df_positive"),)


class EvalResult(Base):
    """One persisted evaluation run used for comparable regression baselines."""

    __tablename__ = "eval_results"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    suite: Mapped[str] = mapped_column(String(128), nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    raw_artifact_path: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("btrim(suite) <> ''", name="ck_eval_results_suite_nonempty"),
        CheckConstraint(
            "jsonb_typeof(config) = 'object'",
            name="ck_eval_results_config_object",
        ),
        CheckConstraint(
            "jsonb_typeof(metrics) = 'object'",
            name="ck_eval_results_metrics_object",
        ),
        CheckConstraint(
            "btrim(raw_artifact_path) <> ''",
            name="ck_eval_results_raw_artifact_path_nonempty",
        ),
        Index("ix_eval_results_suite_created_at", "suite", "created_at"),
    )


class Run(Base):
    """One persisted workflow result, including structured failure outcomes."""

    __tablename__ = "runs"

    run_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    iterations: Mapped[int] = mapped_column(nullable=False)
    total_requests: Mapped[int] = mapped_column(nullable=False)
    total_input_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_output_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_time_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    node_path: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    report: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('ok', 'budget_exceeded', 'schema_rejected', 'error')",
            name="ck_runs_status",
        ),
        CheckConstraint("iterations >= 0", name="ck_runs_iterations_nonnegative"),
        CheckConstraint("total_requests >= 0", name="ck_runs_requests_nonnegative"),
        CheckConstraint("total_input_tokens >= 0", name="ck_runs_input_tokens_nonnegative"),
        CheckConstraint("total_output_tokens >= 0", name="ck_runs_output_tokens_nonnegative"),
        CheckConstraint("total_time_seconds >= 0", name="ck_runs_time_nonnegative"),
        CheckConstraint("btrim(system_prompt) <> ''", name="ck_runs_system_prompt_nonempty"),
        CheckConstraint("jsonb_typeof(node_path) = 'array'", name="ck_runs_node_path_array"),
        CheckConstraint(
            "report IS NULL OR jsonb_typeof(report) = 'object'",
            name="ck_runs_report_object",
        ),
        Index("ix_runs_status_created_at", "status", "created_at"),
    )


class Trace(Base):
    """One raw provider step belonging to a persisted workflow run."""

    __tablename__ = "traces"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.run_id", ondelete="CASCADE"), nullable=False
    )
    step: Mapped[int] = mapped_column(nullable=False)
    node: Mapped[str] = mapped_column(String(32), nullable=False)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    api_url: Mapped[str] = mapped_column(Text, nullable=False)
    input_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    output_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    request_time_ms: Mapped[float] = mapped_column(Float, nullable=False)
    llm_output: Mapped[str] = mapped_column(Text, nullable=False)
    retries: Mapped[int] = mapped_column(nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("run_id", "step", name="uq_traces_run_step"),
        CheckConstraint("step > 0", name="ck_traces_step_positive"),
        CheckConstraint(
            "node IN ('retrieve', 'grade', 'check', 'report')",
            name="ck_traces_node",
        ),
        CheckConstraint("btrim(model_name) <> ''", name="ck_traces_model_name_nonempty"),
        CheckConstraint("btrim(api_url) <> ''", name="ck_traces_api_url_nonempty"),
        CheckConstraint("input_tokens >= 0", name="ck_traces_input_tokens_nonnegative"),
        CheckConstraint("output_tokens >= 0", name="ck_traces_output_tokens_nonnegative"),
        CheckConstraint("request_time_ms >= 0", name="ck_traces_time_nonnegative"),
        CheckConstraint("retries >= 0", name="ck_traces_retries_nonnegative"),
        Index("ix_traces_run_step", "run_id", "step"),
    )
```

#### Create or replace `app/db/session.py`

<!-- file: app/db/session.py -->
```python
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings

engine = create_async_engine(get_settings().database_url, echo=False)
Session = async_sessionmaker(engine, expire_on_commit=False)
```

#### Create or replace `app/db/bootstrap.py`

<!-- file: app/db/bootstrap.py -->
```python
"""Minimal idempotent PostgreSQL schema bootstrap."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.db.models import Base


async def ensure_vector_extension(connection: AsyncConnection) -> None:
    """Enable pgvector in the current database if it is not already enabled."""
    await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))


async def bootstrap_schema(engine: AsyncEngine) -> None:
    """Enable pgvector before creating missing SQLAlchemy tables and indexes."""
    async with engine.begin() as connection:
        await ensure_vector_extension(connection)
        await connection.run_sync(Base.metadata.create_all)
```

#### Create or replace `app/ingestion/seed.py`

<!-- file: app/ingestion/seed.py -->
```python
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
```

Run the checkpoint:

```bash
uv run pytest tests/db -q
```

**Expected:** every selected offline test passes. A declared integration test may skip only when its external service is unavailable.

**Stop:** do not continue if a test fails or skips because a required symbol is missing.

**Debug:** rerun the same pytest target with `-vv --tb=long`, then fix the first failing contract before continuing.

<!-- complete-files:end -->
