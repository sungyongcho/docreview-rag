# M1.4 구현 — 두 번 실행해도 같은 데이터베이스 상태

## 지금까지의 결과물은 프로세스가 종료되면 사라진다

M1.1부터 M1.3까지 인메모리 파이프라인을 완성했다. HTML을 Block으로 분해하고, 표를 마크다운으로 변환하고, 그 결과를 인용 가능한 청크 9,172개로 묶었다. 같은 입력에는 항상 같은 결과가 나온다.

하지만 지금까지 만든 결과는 모두 파이썬 객체다. 프로세스가 종료되면 사라지므로 검색에 사용하려면 데이터베이스에 저장해야 한다.

단순한 `INSERT`문도 첫 실행에서는 동작한다. 문제는 같은 코퍼스를 다시 저장하는 **두 번째 실행**부터 발생한다.

## 재실행은 피할 수 없다

이런 일이 반드시 생긴다.

- 파서 버그를 수정하면 코퍼스를 다시 저장해야 한다.
- 청크 크기를 1,200에서 800으로 바꾸어 실험하면 코퍼스를 다시 저장해야 한다.
- 새 filing이 추가되면 코퍼스를 다시 저장해야 한다.

단순 `INSERT`면 두 번째 실행에서 데이터가 두 배가 된다. 검색하면 같은 문단이 두 번 나온다.

매번 기존 행을 모두 지우고 다시 저장할 수도 있다. 그러나 그렇게 하면 **M2가 계산한 임베딩까지 함께 삭제된다.** 청크 9,172개의 임베딩을 다시 만드는 데는 API 호출 시간과 비용이 든다. 일부 파싱 결과만 바뀌었는데 모든 임베딩을 다시 계산하는 방식은 비효율적이다.

## 이 모듈이 푸는 문제: 멱등 영속화

목표는 두 가지다.

1. **같은 코퍼스를 두 번 저장해도 데이터베이스 상태가 달라지지 않는다.** 2. **입력이 바뀌면 변경된 청크만 갱신하고, 나머지 청크의 임베딩은 보존한다.**

두 번째가 특히 중요하다. 파서를 고쳐서 청크 9,172개 중 30개만 텍스트가 달라졌다면, 그 30개만 임베딩을 무효화하고 나머지 9,142개는 그대로 둬야 한다.

해법은 셋으로 나뉜다.

**첫째, 트랜잭션을 열기 전에 전체 코퍼스를 검증한다.** SHA-256, 소스 범위, 서수 연속성을 SQL 실행 전에 확인한다. 잘못된 입력은 데이터베이스 쓰기를 시작하기 전에 거부한다.

**둘째, INSERT 대신 UPSERT를 사용한다.** PostgreSQL의 `INSERT ... ON CONFLICT DO UPDATE`는 행이 없으면 삽입하고, 충돌하면 갱신하는 결정을 원자적으로 처리한다. 청크의 충돌 키는 M1.3에서 만든 `(doc_id, ordinal)`이다.

**셋째, 전체 시드 작업을 하나의 트랜잭션으로 처리한다.** 20개 중 15번째 문서에서 실패했을 때 앞의 14개만 커밋되면, 데이터베이스에는 전체로 검증되지 않은 부분 코퍼스가 남는다. 따라서 모든 쓰기가 함께 성공하거나 함께 롤백되어야 한다.

## 시작 조건

M1.3 테스트가 통과하고, 20개 매니페스트 문서에서 결정론적 청크를 만들 수 있어야 한다. 이 단계는 기존 파싱·청킹 함수를 호출하지만 해당 규칙을 새로 정의하지 않는다. M1.3이 만든 객체를 검증하여 저장하는 것이 이 레이어의 책임이다.

L1에서 모델과 검증 레코드를, L2에서 PostgreSQL upsert를, L3에서 트랜잭션과 CLI를 만든다.

---

## 영속화는 파싱 결정을 내리지 않는다

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

검증은 트랜잭션이 열리기 전에 끝난다. 영속화는 M1.1–M1.3에서 이미 결정된 소스 아이덴티티, 증거 본문, 검색 컨텍스트, 좌표를 저장한다. 아래 표는 그 경계가 코드로 바뀌는 순서다.

| 레이어 | 책임 | 주요 테스트 |
|---|---|---|
| L1 | 모델, 불변 레코드, 검증, 결정론적 변환 | `test_01_models.py`, `test_02_records.py` |
| L2 | PostgreSQL 충돌 구문과 임베딩 무효화 | `test_03_upserts.py` |
| L3 | 원자적 배치, 오래된 행 정리, 코퍼스 증명, 재실행 증명 | `test_03_upserts.py` ~ `test_05_postgres.py` |

---

## L1 — SQL 실행 전에 코퍼스를 검증한다

### 이번 레이어에서 먼저 버릴 오해

L1은 SQLAlchemy 문법을 외우는 장이 아니다. `Document`, `Chunk` 같은 ORM 클래스도, `DocumentRecord` 같은 데이터클래스도 SQLAlchemy가 자동으로 써준 결과물이 아니다. 둘 다 우리가 설계하지만 맡는 책임이 다르다.

이 레이어의 목표는 다음 한 문장으로 요약된다.

**파싱 결과 전체를 메모리에서 검증해 `SeedBatch`를 만든 뒤에만 SQL을 허용한다.**

```text
ParsedFiling + Chunk[]
          │
          ├── rules within one row ──> DocumentRecord + ChunkRecord[]
          │
          └── rules across rows ─────> SeedBatch
                                          │
                                          └── L2 UPSERT → L3 transaction
```

파일링을 하나 파싱할 때마다 바로 저장하면 15번째 문서에서 실패했을 때 앞의 14개만 남을 수 있다. 또한 데이터 오류와 연결 오류가 같은 저장 루프에서 뒤섞인다. **`SeedBatch` 생성과 데이터베이스 쓰기를 분리하면 전체 코퍼스 검증이 트랜잭션보다 먼저 끝나므로, 잘못된 입력은 데이터베이스를 변경하지 못한다.**

### 무엇을 작성하고 어디를 직접 구현할까

| 구간 | 학습 행동 | 여기서 얻어야 하는 것 |
|---|---|---|
| `app/config.py` | **설정 스키마 작성** | 설정의 소유자가 하나라는 사실 |
| `app/db/models.py` 필드 선언 | **모델 선언 작성 후 핵심 줄 검토** | Python 매핑이 어떤 DB 제약이 되는지 |
| `DocumentRecord` | 필드와 `values()`를 작성하고 `__post_init__()`을 **직접 구현** | 행 하나의 유효성 검사 |
| `ChunkRecord` | `__post_init__()`을 **직접 구현** | 본문·검색 텍스트·출처 좌표의 일관성 |
| `SeedBatch` | 배치 불변조건을 **직접 구현** | 여러 행을 가로지르는 출처 불변조건 |
| 변환 함수의 필드 매핑 | **매핑 작성 후 경계 변환 검토** | M1.3 객체가 DB 입력으로 바뀌는 경로 |
| 변환 함수의 가드와 정렬 | 핵심 로직을 **직접 구현** | 결정론과 fail-closed 경계 |

반복 필드명을 기계적으로 입력하는 것은 목표가 아니다. 코드가 어떤 잘못된 상태를 더는 표현하지 못하게 하는지 설명할 수 있으면 된다.

### 1. 실행 기반을 먼저 준비한다 — 설정 스키마 작성

L1 테스트는 import 단계에서 설정과 ORM 모델을 읽는다. 따라서 먼저 `app/config.py`를 만든다. 아래 정의로 설정 스키마를 작성한다.

#### `app/config.py` 생성 — 공유 설정

**학습 행동 — 구조 작성:** 필드 선언을 외우지 말고, 설정을 읽는 경로가 이 파일 하나로 모인다는 점만 확인한다.

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

**코드에서 꼭 볼 것**

- `SettingsConfigDict(env_file=".env", extra="ignore")`: 환경 파일을 읽되 알 수 없는 키는 설정 객체에 섞지 않는다.
- `@lru_cache`: 호출할 때마다 서로 다른 설정 객체를 만들지 않는다.
- `embed_dim`: ORM의 `Vector(DIM)`과 임베딩 공급자가 같은 차원을 공유한다.

### 2. ORM은 자동 생성물이 아니라 데이터베이스 계약이다

`app/db/models.py`는 PostgreSQL에 **무엇을 저장할 수 있는지** 선언한다. ORM이 줄여주는 것은 반복 SQL이지, 기본 키·외래 키·NULL 허용 여부·고유성 같은 설계 판단이 아니다. **ORM 모델은 데이터베이스의 저장 계약을 표현하고, 뒤에서 만들 검증 레코드는 SQL 실행 전 애플리케이션 계약을 표현한다.**

필드를 하나씩 읽기보다 역할별로 묶어 본다.

| 모델 | 필드 묶음 | 역할 |
|---|---|---|
| `Document` | `doc_id`, `ticker`, `cik` | filing과 회사를 식별한다. |
| `Document` | `fiscal_year`, `form`, 날짜, accession, URL | 제출 메타데이터를 보존한다. |
| `Document` | `parse_status`, `item_index` | 파서가 내린 결과와 상태를 보존한다. |
| `Document` | `source_length`, `source_sha256` | 모든 인용 좌표를 한 원문 스냅샷에 묶는다. |
| `Chunk` | `doc_id`, `ordinal` | 문서 안에서 청크의 논리적 위치를 정한다. |
| `Chunk` | `body`, `start_char`, `end_char`, `source_sha256` | 원문에서 다시 열 수 있는 근거를 보존한다. |
| `Chunk` | `context_header`, `index_text`, `embedding`, `content_tsv` | 검색용 표현을 근거 본문과 분리한다. |

```text
Document (PK: doc_id)
    1
    │
    └────< N  Chunk (FK: doc_id, UNIQUE: doc_id + ordinal)
```

#### `app/db/models.py` 생성 — 문서 및 청크 ORM 모델

**학습 행동 — 모델 선언 작성 + 설계 검토:** 아래 정의로 모델을 작성한 뒤, 여섯 지점을 코드에서 직접 찾아 표시한다.

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

**코드에서 꼭 볼 여섯 지점**

| 코드 | 읽어야 할 의미 |
|---|---|
| `ForeignKey(..., ondelete="CASCADE")` | 문서가 없어지면 그 문서에서 파생된 청크도 함께 없어진다. |
| `UniqueConstraint("doc_id", "ordinal")` | 같은 문서의 같은 논리적 청크를 두 번 저장하지 않는다. |
| `end_char > start_char` | 빈 범위와 뒤집힌 인용 범위를 DB도 거부한다. |
| `embedding ... nullable=True` | `NULL`은 오류가 아니라 아직 계산하지 않은 상태다. |
| `Computed("to_tsvector(...)")` | `index_text`가 바뀌면 PostgreSQL이 검색 벡터를 다시 만든다. |
| `content = synonym("index_text")` | M1.3의 이름을 유지하면서 DB 열을 중복 생성하지 않는다. |

여기까지는 실행 중인 PostgreSQL이 필요 없다. SQLAlchemy가 만든 메타데이터만 검사한다.

```bash
uv run pytest tests/db/test_01_models.py -q
```

이 테스트가 실패하면 비즈니스 로직으로 넘어가지 않는다. 모델의 열·제약·생성 열 중 하나가 이미 계약과 다르다는 뜻이다.

### 3. L1의 핵심 — SQL 실행 전 레코드 경계

`DocumentRecord`, `ChunkRecord`, `SeedBatch`는 SQLAlchemy 모델이 아니다. 표준 라이브러리 `dataclass`로 만든 애플리케이션 검증 계층이다.

**타입 어노테이션은 런타임 값을 검사하지 않으며, `frozen=True`도 생성 이후의 재할당만 막을 뿐 잘못된 초기값을 거부하지 않는다.** `slots=True`는 선언하지 않은 속성의 추가를 막는다. 값의 실제 도메인 검증은 `__post_init__()`에 명시한 조건이 수행한다.

**생성 후 애플리케이션 검증은 잘못된 값을 SQL 실행 전에 구체적인 오류로 거부하고, 데이터베이스 CHECK 제약은 이 검증을 거치지 않은 쓰기까지 차단하는 최종 방어선이다.** 두 검증 계층은 같은 규칙을 서로 다른 경계에서 지킨다.

#### 3.1 `app/ingestion/seed.py`의 뼈대 작성

아래 import에는 L2와 L3에서 쓸 `case`, `delete`, `AsyncSession`도 미리 들어 있다. 뒤의 레이어가 같은 파일에 코드를 이어 붙이므로 지금 한 번만 준비한다. 이 블록으로 모듈의 뼈대를 작성하되, import 목록 자체를 암기할 필요는 없다.

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

#### 3.2 `app/ingestion/seed.py` — `DocumentRecord`로 한 문서 행을 검증한다

**학습 행동 — 검증 로직 구현:** 필드 목록과 `values()` 매핑을 먼저 작성한다. 그런 다음 `__post_init__()`을 위에서 아래로 직접 구현하면서 각 `raise`가 어떤 손상된 입력을 막는지 확인한다.

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

**코드에서 꼭 볼 것**

- `missing`은 필드가 존재하는지가 아니라 값이 비어 있는지를 검사한다.
- parser status와 Item status는 서로 다른 허용 집합을 사용한다.
- `json.dumps(...)`는 `item_index`가 PostgreSQL `JSONB`에 들어갈 수 있는지 미리 확인한다.
- `values()`에는 ORM이 자동 계산할 값이 없다. 입력으로 저장할 값만 명시한다.

#### 3.3 `app/ingestion/seed.py` — `ChunkRecord`로 검색 텍스트와 근거를 검증한다

**학습 행동 — 핵심 검증 구현:** 검증이 짧고 각 줄이 M1.3의 설계와 직접 연결된다. 특히 `expected_index_text`와 반열린 좌표 검사는 생략하지 않는다.

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

**코드에서 꼭 볼 것**

```python
expected_index_text = (
    f"{self.context_header}\n\n{self.body}" if self.context_header else self.body
)
```

`body`는 인용 가능한 원문 근거이고, `context_header`는 우리가 합성한 검색 문맥이다. `index_text`는 둘을 검색용으로 합친 값이다. 이 검사가 없으면 세 필드가 서로 다른 내용을 가리킨 채 DB에 들어갈 수 있다.

#### 3.4 `app/ingestion/seed.py` — `SeedBatch`로 행 사이의 오류를 잡는다

**학습 행동 — 배치 불변조건 구현:** L1에서 가장 중요한 코드다. 조건을 하나씩 구현하면서 `record` 하나만 보고 검사할 수 있는 조건과 전체 배치를 봐야 하는 조건을 구분한다.

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

`SeedBatch`는 다음 질문에 답한다.

- 모든 청크가 실제 문서를 참조하는가?
- 문서와 청크가 같은 SHA-256 원문에서 왔는가?
- 청크 좌표가 문서 길이를 넘지 않는가?
- `(doc_id, ordinal)` 순서가 결정론적인가?
- ordinal이 문서마다 `0, 1, 2, ...`로 빈틈없이 이어지는가?

마지막 조건은 L3의 오래된 청크 삭제를 가능하게 한다. 새 결과가 495개라면 `ordinal >= 495`인 행을 삭제해도 안전하다는 근거가 바로 밀집 서수다.

**SHA-256은 좌표가 속한 원문 스냅샷을 식별하고, 반열린 범위 [start_char, end_char)는 그 스냅샷 안의 정확한 근거 구간을 지정한다.** 둘 중 하나라도 다르면 같은 좌표가 같은 내용을 가리킨다고 보장할 수 없다.

아래 결과 타입과 SHA-256 helper는 짧은 지원 코드다. 이어서 작성한다.

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

### 4. M1.3 객체를 검증 레코드로 바꾼다

지금까지는 안전한 객체의 모양을 정의했다. 이제 `ParsedFiling`과 `Chunk`를 그 모양으로 변환한다.

#### 4.1 `app/ingestion/seed.py` — 문서 필드 매핑과 경계 변환

**학습 행동 — 매핑 작성 + 경계 검토:** 필드 매핑을 완성한 뒤, CIK가 문자열에서 정수로 바뀌는 지점과 JSON 왕복을 확인한다.

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

`json.loads(json.dumps(..., sort_keys=True))`는 단순 전달이 아니다. JSON으로 표현할 수 없는 객체를 여기서 거부하고, 입력과 분리된 정규화된 값을 만든다.

#### 4.2 `app/ingestion/seed.py` — 청크 provenance 가드 구현

**학습 행동 — 가드 구현 + 생성자 매핑 작성:** `ChunkRecord` 생성 전에 같은 규칙을 일부 다시 검사하는 이유는 에러 메시지를 M1.3 객체의 문맥에서 바로 내기 위해서다.

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

이 함수는 잘못된 입력을 임의로 보정하지 않는다. `doc_id` 불일치, 빈 본문, 잘못된 좌표, 원문 해시 불일치 중 하나라도 발견되면 해당 코퍼스 전체를 저장 대상에서 제외한다.

#### 4.3 `app/ingestion/seed.py` — 전체 코퍼스를 정렬해 `SeedBatch`로 조립한다

**학습 행동 — 정렬 로직과 최종 반환 구현:** `filing_records()`의 위임과 필드 매핑을 작성한다. 이어서 `build_seed_batch()`가 입력·문서·청크를 각각 언제 정렬하는지 확인하며 구현한다.

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

정렬은 출력 형태를 정돈하기 위한 장식이 아니다. 같은 매니페스트를 두 번 읽었을 때 동일한 레코드 순서를 만들고, `SeedBatch`가 중복과 역순을 선형 검사로 거부할 수 있게 한다.

### 5. 테스트를 정답지가 아니라 설계 명세로 읽는다

이제 테스트 이름부터 읽는다. 각 실패 사례가 방금 작성한 경계 하나를 가리킨다.

| 테스트가 깨뜨리는 값 | 지키는 계약 |
|---|---|
| 허용되지 않은 파서 또는 Item 상태 | 정의된 파싱 상태만 저장한다. |
| 다른 `doc_id`의 청크 | 문서 사이의 근거가 섞이지 않는다. |
| `0, 1, 3` ordinal | 청크 순서와 오래된 행 정리가 안전하다. |
| 빈 `body`, 잘못된 출처 범위 | 인용할 근거가 실제로 존재한다. |
| 다른 `source_sha256` | 좌표와 원문 스냅샷이 같은 버전이다. |
| 오래된 `index_text` | 검색되는 텍스트가 body와 context에서 정확히 파생된다. |
| 매니페스트 문서 수 불일치 | 일부만 받은 코퍼스를 완전한 입력으로 오해하지 않는다. |

```bash
uv run pytest tests/db/test_01_models.py tests/db/test_02_records.py -q
```

전체 테스트가 통과하면 다음 명령으로 대표 실패 경로 세 개를 다시 확인한다.

```bash
uv run pytest tests/db/test_02_records.py \
  -k "broken_provenance or cross_record_provenance or inconsistent_index_text" -q
```

각 검증을 제거했을 때 어떤 잘못된 데이터가 DB까지 도달하는지도 설명해 본다. 이 인과관계를 설명할 수 있어야 L1의 검증 경계를 이해한 것이다.

### 6. 여기까지 왔을 때 설명할 수 있어야 하는 것

다음 질문의 답은 앞에서 **굵게 표시한 핵심 문장**에 있다. 각 답을 해당 코드와 연결해 설명해 본다.

- **ORM 모델과 `DocumentRecord`가 왜 별도 계층인가?**
  - **답:** ORM 모델은 데이터베이스 스키마와 제약을 정의하고, `DocumentRecord`는 DB 작업 전에 애플리케이션 데이터를 메모리에서 검증한다. 둘을 나누면 연결 없이도 코퍼스 정확성을 테스트하고 영속 계층이 파싱 판단을 하지 않게 할 수 있다.
- **`frozen=True`와 타입 어노테이션이 해주지 않는 검증은 무엇인가?**
  - **답:** `frozen=True`는 재할당을 막고 타입 어노테이션은 의도한 타입을 설명할 뿐, 런타임 도메인 값을 검사하지 않는다. 빈 식별자, 미지원 상태, 잘못된 구간·해시, 일치하지 않는 파생 텍스트는 명시적으로 검증해야 한다.
- **DB `CheckConstraint`와 `__post_init__()` 검증을 왜 둘 다 두는가?**
  - **답:** `__post_init__()`은 SQL 시작 전에 잘못된 데이터를 애플리케이션 맥락의 오류로 빠르게 거부한다. DB 제약은 이 dataclass를 거치지 않는 쓰기 경로까지 막는 최종 방어선이다.
- **SHA-256과 반열린 좌표가 어떻게 하나의 출처 계약을 이루는가?**
  - **답:** SHA-256은 정확한 원문 스냅샷을 고정하고 `[start_char, end_char)`는 그 스냅샷 안의 모호하지 않은 한 구간을 지정한다. 둘 중 하나만으로는 좌표가 어느 증거 텍스트를 가리키는지 증명할 수 없다.
- **왜 SQL이나 트랜잭션보다 `SeedBatch`가 먼저인가?**
  - **답:** `SeedBatch`는 SQL 실행 전에 레코드 간 출처, 문서 소속, 결정적 순서, 조밀한 ordinal을 검증한다. 예상보다 적은 매니페스트는 별도 문제이며, `build_seed_batch(expected_documents=...)`의 개수 가드가 배치를 만들기 전에 거부한다.

이 다섯 질문에 답할 수 있다면 필드 선언을 외우지 않아도 된다. L2부터는 검증된 레코드를 PostgreSQL UPSERT 문으로 바꾸는 일만 남는다.

---

## L2 — PostgreSQL 전용 UPSERT 구문을 만든다

### 임베딩을 언제 버릴지 결정하는 문제

앞에서 정의한 임베딩 무효화 문제를 구체적인 시나리오로 살펴보자.

1. 코퍼스를 시드한다. 2. M2가 9,172개 청크를 모두 임베딩한다. 이 과정에는 실제 API 호출과 비용이 발생한다. 3. 파서 버그를 수정한 결과, 청크 30개의 텍스트가 달라진다. 4. 코퍼스를 재시드한다.

변경된 청크 30개의 기존 임베딩은 이제 **오래된 파생 데이터**다. 벡터는 이전 검색 텍스트로 계산됐지만 사용자에게 표시되는 내용은 새 검색 텍스트이므로, 그대로 두면 검색 대상과 표시 내용이 어긋난다.

나머지 9,142개는 검색 텍스트가 바뀌지 않았으므로 기존 임베딩도 여전히 유효하다.

**모든 임베딩을 삭제하면** 안전하지만 유효한 9,142개까지 불필요하게 다시 계산해야 한다. **모든 임베딩을 보존하면** 변경된 30개가 새 텍스트와 일치하지 않는 상태로 남는다.

따라서 **`index_text`가 같으면 임베딩을 보존하고, 달라졌으면 NULL로 설정한다.** 그러면 M2는 `WHERE embedding IS NULL` 조건으로 변경된 30개만 다시 계산할 수 있다.

기존 값을 먼저 조회해 변경 여부를 판단한 뒤 갱신하는 두 단계 방식도 생각할 수 있다. 그러나 조회와 갱신 사이에 다른 트랜잭션이 값을 바꾸면, 앞서 확인한 상태는 더 이상 유효하지 않다. 이 때문에 경쟁 조건이 발생한다.

PostgreSQL의 `CASE` 표현식을 `ON CONFLICT DO UPDATE` 안에 넣으면 **한 번의 원자적 연산**으로 끝난다.

```python
"embedding": case(
    (ChunkModel.index_text == excluded.index_text, ChunkModel.embedding),
    else_=None,
)
```

기존 행의 `index_text`가 새 값과 일치하면 이전 임베딩을 유지하고, 다르면 NULL로 설정한다. 별도 조회가 필요하지 않으므로 조회와 갱신 사이의 경쟁 조건도 사라진다.

### 무엇을 작성하고 어디를 직접 구현할까

L2는 SQL을 실행하지 않는다. **실행될 SQL의 모양을 결정하는** 세 함수를 같은 `app/ingestion/seed.py`에 이어 붙인다.

| 구간 | 학습 행동 | 여기서 얻어야 하는 것 |
|---|---|---|
| `prepare_seed_batch` | **구조 작성** | 코퍼스 조립이 트랜잭션 밖에서 끝난다는 경계 |
| `document_upsert_statement`의 `set_` 매핑 | **필드 매핑 작성 후 충돌 키 검토** | 반복 선언과 설계 판단의 구분 |
| `chunk_upsert_statement`의 `embedding` 표현식 | 무효화 규칙을 **직접 구현** | 비싼 파생 데이터를 언제 버리는가 |

`set_` 딕셔너리의 열 이름 12개를 외우는 것은 목표가 아니다. **어떤 열이 `excluded`에서 그대로 오고, 어떤 열만 조건부인지** 구분할 수 있으면 된다.

### 1. 코퍼스 조립을 트랜잭션 밖에서 끝낸다

L1이 만든 `build_seed_batch()`는 이미 파싱된 매니페스트를 받는다. 하지만 호출자는 매니페스트 경로를 어디서 얻는지 알아야 한다. 그 결정을 한 함수로 모은다.

이 함수가 L2의 첫 단계에 오는 이유는 명확하다. **파싱 오류나 매니페스트 개수 불일치는 데이터베이스 연결이나 트랜잭션을 시작하기 전에 발견해야 한다.**

#### `app/ingestion/seed.py` 확장 — 매니페스트에서 배치까지

**학습 행동 — 구조 작성:** 두 줄짜리 함수다. 여기서 볼 것은 코드가 아니라 위치다.

<!-- src: app/ingestion/seed.py::prepare_seed_batch -->
```python
def prepare_seed_batch(
    manifest_path: Path | None = None, *, expected_documents: int | None = EXPECTED_DOCUMENTS
) -> SeedBatch:
    """Build the complete corpus batch before opening a database transaction."""
    path = manifest_path or get_settings().corpus_dir / "manifest.json"
    return build_seed_batch(load_manifest(path), expected_documents=expected_documents)
```

**코드에서 꼭 볼 것**

- 인자에 `AsyncSession`이 없다. 이 함수는 데이터베이스를 모른다.
- `manifest_path or get_settings()...`: 테스트는 경로를 넘기고, CLI는 설정에 맡긴다.
- 반환값이 `SeedBatch`다. L1의 배치 불변조건을 통과하지 못하면 여기서 예외가 난다.

### 2. 문서 UPSERT — 반복 매핑과 하나의 설계 판단

문서 UPSERT의 대부분은 필드 매핑이다. `set_` 딕셔너리의 12개 열은 모두 `excluded`의 새 값을 받으므로, 재시드는 filing 메타데이터를 최신 파싱 결과로 갱신한다.

이 동작은 의도적인 정책이다. 문서 메타데이터에는 **가장 최근 파싱 결과를 사용한다.** 예를 들어 파서가 이전에 놓친 `filing_date`를 읽게 되면 재시드는 기존 값을 새 값으로 교체한다. 이 필드들은 임베딩처럼 보존해야 할 비싼 파생 데이터를 직접 포함하지 않는다. 반면 다음 절의 청크 테이블은 검색 텍스트의 변경 여부에 따라 기존 임베딩을 선택적으로 보존해야 한다.

이 함수의 핵심 설계 판단은 **충돌 키가 무엇인가**에 있다.

#### `app/ingestion/seed.py` 확장 — 문서 UPSERT

**학습 행동 — 필드 매핑 작성:** 열 이름은 `Document` 모델을 보고 작성한다. 매핑을 마친 뒤 `index_elements`가 왜 `doc_id` 하나인지 설명해 본다.

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

**코드에서 꼭 볼 것**

- `if not records: raise ValueError(...)`: 빈 리스트로 `insert().values([])`를 만들면 SQLAlchemy가 컴파일 단계에서 알아보기 어려운 오류를 낸다. 호출 지점에서 먼저 막는다.
- `insert(Document).values([...])`: 20개 문서가 **하나의** 구문으로 나간다. 왕복이 한 번이다.
- `excluded`는 PostgreSQL이 충돌한 행마다 노출하는 가상 테이블이다. 지금 삽입하려던 값을 가리키며, 기존 행 값은 `Document.<column>`으로 참조한다. 이 둘의 차이가 L2 전체의 축이다.
- `set_`에 `doc_id`가 없다. 충돌 키를 자기 자신으로 덮어쓸 이유가 없다.

### 3. 청크 UPSERT — 임베딩 무효화를 한 표현식에 담는다

이 함수가 L2의 핵심이다. 아홉 개 열은 문서 UPSERT와 마찬가지로 `excluded`의 값을 받고, 열 번째 열인 `embedding`만 조건부로 처리한다.

이 예외 때문에 모든 열을 일괄 교체하는 범용 UPSERT 헬퍼를 사용할 수 없다. 아홉 개 열에는 새 값을 적용하지만, 임베딩은 기존 검색 텍스트와 새 검색 텍스트를 비교한 결과에 따라 보존하거나 무효화해야 한다.

이 판단을 파이썬으로 옮겨 기존 행을 조회한 뒤 갱신할 수도 있다. 그러나 앞에서 살펴본 것처럼 조회와 갱신 사이에는 경쟁 조건이 생긴다. 따라서 비교와 갱신을 하나의 SQL 표현식으로 묶는다.

`embedding`은 다른 열과 성질이 다르다. 파싱 결과에서 직접 나오는 값이 아니라 **API 비용을 들여 계산한 파생 데이터**다. M1.4는 이 열을 채우지 않지만, 재시드할 때 기존 값을 보존할지 무효화할지는 지금 결정해야 한다.

#### `app/ingestion/seed.py` 확장 — 청크 UPSERT

**학습 행동 — 무효화 규칙 구현:** 앞의 아홉 개 열은 문서 UPSERT와 같은 형태로 작성한다. `embedding` 항목은 먼저 직접 구현한 뒤 아래 코드와 대조한다.

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

**코드에서 꼭 볼 것**

- `index_elements=[ChunkModel.doc_id, ChunkModel.ordinal]`: 청크의 정체성은 복합 키다. M1.3이 서수를 0부터 빈틈없이 매겨줬기 때문에 이 키가 성립한다.
- `case()`의 비교 대상: 왼쪽 `ChunkModel.index_text`는 **데이터베이스에 이미 있는 값**, 오른쪽 `excluded.index_text`는 **지금 넣으려는 값**이다. 방향을 바꾸면 의미가 없어진다.
- 조건이 `index_text`이고 `body`가 아닌 이유: 임베딩은 `index_text`로 계산했다. `body`가 같아도 `context_header`가 바뀌면 `index_text`가 바뀌고, 벡터는 무효가 된다.
- `record.values()`가 `embedding` 키를 포함하지 않는다. 삽입 경로에서는 열이 아예 빠지므로 DB 기본값 NULL이 들어간다. M1.4는 임베딩을 쓰지 않는다는 약속이 여기 있다.

### 왜 방언 전용 `insert`를 import하는가

import 문을 보면 `from sqlalchemy import insert`가 아니라 `from sqlalchemy.dialects.postgresql import insert`다.

범용 `insert()`에는 `on_conflict_do_update()`가 없다. `ON CONFLICT`가 PostgreSQL 문법이기 때문이다. 다른 DB에서는 `MERGE`나 `INSERT OR REPLACE`를 쓴다.

이식성을 포기하는 대신 얻는 게 있다. **충돌 키가 코드에 명시적으로 적힌다.**

```python
index_elements=[ChunkModel.doc_id, ChunkModel.ordinal]
```

충돌 키를 명시하지 않으면 INSERT가 실패할 때 `IntegrityError`를 잡아 UPDATE하는 예외 기반 구현으로 흐르기 쉽다. 그러면 어떤 제약이 멱등성을 보장하는지 코드에서 드러나지 않고, 관련 고유 제약이 바뀌어도 문제를 즉시 발견하기 어렵다.

**멱등성이 특정 DB 기능에 의존한다면, 그 의존을 감추지 말고 드러내는 편이 낫다.**

### 집중 테스트와 테스트가 지키는 계약

```bash
uv run pytest tests/db/test_03_upserts.py -k "document_upsert or chunk_upsert" -q
```

이 테스트들은 데이터베이스에 붙지 않는다. 구문을 PostgreSQL 방언으로 **컴파일해서 나온 SQL 문자열**을 검사한다. 각 테스트가 지키는 계약은 다음과 같다.

| 테스트가 확인하는 것 | 지키는 계약 |
|---|---|
| 문서 SQL의 충돌 대상이 `doc_id` | 같은 filing이 두 행으로 늘어나지 않는다. |
| 청크 SQL의 충돌 대상이 `(doc_id, ordinal)` | 청크 정체성이 문서 안의 위치로 결정된다. |
| 삽입 열 목록에 `embedding`이 없다 | M1.4는 벡터를 쓰지 않는다. |
| `embedding` 보존 — `index_text`가 같을 때 | 유효한 임베딩을 불필요하게 다시 계산하지 않는다. |
| `embedding`을 NULL로 — `index_text`가 다를 때 | 오래된 벡터가 새 텍스트를 가리키지 않는다. |

테스트가 실패하면 컴파일된 구문을 직접 출력해서 어느 절이 빠졌는지 본다. 통과를 확인하는 데서 멈추지 말고, 마지막 두 줄을 뒤집으면 어떤 검색 결과가 나오는지 말로 설명해 본다.

### 여기까지 온 상태

멱등 UPSERT로 컴파일되는 구문 빌더 두 개를 만들었다. 임베딩 보존과 무효화는 하나의 원자적 표현식 안에서 결정된다.

여전히 데이터베이스는 필요 없다. 구문을 **컴파일**해서 문자열을 확인하는 것만으로 테스트가 된다. 실제 연결은 L3의 선택 과제에서 처음 나온다.

### UPSERT와 트랜잭션은 서로 다른 범위를 보호한다

둘 다 원자적이라는 표현을 쓰지만 보장하는 범위가 다르다.

| 장치 | 보호하는 범위 | 이 프로젝트에서 보장하는 것 |
|---|---|---|
| UPSERT | 하나의 충돌 키에 대한 삽입 또는 갱신 결정 | 중복 행 없이 기존 청크를 갱신하고 필요한 임베딩만 무효화 |
| 트랜잭션 | 여러 SQL 문장으로 구성된 전체 시드 배치 | 문서와 청크가 전부 반영되거나 전부 롤백 |

UPSERT만 사용하면 각 행은 안전하게 갱신되지만, 20개 문서 중 15개를 쓴 뒤 실패한 부분 코퍼스가 남을 수 있다. 트랜잭션만 사용하고 일반 INSERT를 쓰면 전체 롤백은 가능하지만 같은 코퍼스를 재실행할 때 고유 키 충돌이 난다. **UPSERT는 하나의 충돌 키를 보호하고, 트랜잭션은 여러 SQL 문장으로 구성된 전체 시드 배치를 보호하므로 둘 다 필요하다.**

---

## L3 — 하나의 트랜잭션을 소유하라

### 트랜잭션이 정확히 하나여야 하는 이유

코퍼스는 전체가 하나의 버전을 이룬다. 20개 중 15개만 새 버전이고 5개는 이전 버전이면, 어느 실행에서도 검증하지 않은 조합이 된다. 이 상태에서 측정한 검색 품질은 재현 가능한 기준으로 사용할 수 없다.

청크도 마찬가지다. 청크 배치 다섯 개 중 세 번째에서 실패하면 일부 문서에는 앞부분의 청크만 저장된다. 해당 문서를 검색할 때 저장되지 않은 뒷부분은 결과에 포함될 수 없다.

`async with session.begin()`은 모든 쓰기를 하나의 트랜잭션으로 묶는다. 블록이 성공하면 전체를 커밋하고, 예외가 발생하면 전체를 롤백하므로 부분 코퍼스가 남지 않는다.

### 청크가 줄어들면 옛 행이 남는다

재청킹 결과가 이전보다 **적을** 수 있다. 파서를 고쳐서 두 블록이 하나로 합쳐지는 경우다.

NVDA-FY2024의 청크가 이전에는 500개였지만 새 결과에서는 495개라고 가정하자. UPSERT는 0~494번을 갱신하지만, 입력에서 사라진 495~499번 행은 삭제하지 않으므로 그대로 남는다.

남은 다섯 행에는 이전 파싱 결과의 텍스트와 좌표가 들어 있다. 이 행이 검색되면 현재 코퍼스에는 존재하지 않는 내용을 인용할 수 있다.

이 오래된 행을 정리할 때 M1.3의 밀집 서수 불변식을 사용한다.

```sql
DELETE FROM chunks WHERE doc_id = ? AND ordinal >= 495
```

이 구문은 이전 서수 목록을 따로 추적하거나 전체 행을 조회하지 않고 오래된 꼬리 행을 삭제한다. **서수가 0부터 빈틈없이 이어진다는 불변식 덕분에 새 청크 수가 곧 안전한 삭제 경계가 된다.**

### 무엇을 작성하고 어디를 직접 구현할까

L3은 지금까지의 조각을 실행 가능한 하나의 연산으로 묶는다. 트랜잭션 안에서 일어나는 일은 세 단계뿐이다.

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

| 구간 | 학습 행동 | 여기서 얻어야 하는 것 |
|---|---|---|
| `_batches` | **구조 작성** | 프로토콜 한도가 코드 형태를 바꾸는 지점 |
| `persist_seed_batch`의 트랜잭션 블록 | 세 단계 순서를 **직접 구현** | 원자성의 경계가 어디까지인가 |
| `persist_seed_batch`의 사전 검사 | 거부 조건을 **직접 구현** | 조용한 부분 커밋을 막는 방법 |
| `seed_corpus`, CLI | **구조 작성 후 진입점 검토** | 라이브러리 경계와 실행 경계의 분리 |
| `app/db/models.py` 이후 모델 | **모델 선언 작성** | 이후 모듈이 같은 레지스트리를 공유하는 이유 |
| `app/db/session.py`, `bootstrap.py` | **설정 작성 후 책임 확인** | 부트스트랩과 마이그레이션의 차이 |

### 1. 배치를 프로토콜 한도 안으로 자른다

청크 9,172개를 하나의 구문에 담으면 PostgreSQL 프로토콜의 파라미터 한도를 넘는다. 먼저 레코드를 안전한 크기로 나누는 헬퍼를 만든다.

이 분할은 선택적인 성능 튜닝이 아니라 프로토콜 한도를 지키기 위한 필수 조건이다. 모든 청크를 단일 구문에 넣으면 실행 속도가 느려지는 정도가 아니라 파라미터 개수 오류로 구문 자체가 실패한다.

따라서 배치 분할 헬퍼는 와이어 프로토콜이 허용하는 범위 안에서 구문을 만들기 위해 존재한다.

#### `app/ingestion/seed.py` 확장 — 청크 배치 분할

**학습 행동 — 구조 작성:** 제너레이터 한 개다. 왜 필요한지는 바로 아래 절에서 다룬다.

<!-- src: app/ingestion/seed.py::_batches -->
```python
def _batches(records: Sequence[ChunkRecord], size: int) -> Iterable[Sequence[ChunkRecord]]:
    if size <= 0:
        raise ValueError("chunk batch size must be positive")
    for start in range(0, len(records), size):
        yield records[start : start + size]
```

**코드에서 꼭 볼 것**

- 슬라이스를 하나씩 내보낸다. 9,172개 레코드의 사본을 한꺼번에 만들지 않는다.
- `size <= 0` 검사가 두 곳에 있다. 여기와 `persist_seed_batch`다. 제너레이터의 본문은 첫 `next()` 전까지 실행되지 않으므로, 호출자가 잘못된 값을 넘겼을 때 **트랜잭션을 열기 전에** 실패시키려면 바깥에도 검사가 필요하다.

### 청크는 나눠 넣고 문서는 한 번에 넣는 이유

청크 9,172개를 하나의 `INSERT ... VALUES (...)`에 넣으면 값 튜플이 9,172개짜리 구문이 만들어진다. 열이 11개니 파라미터가 10만 개다.

PostgreSQL 프로토콜의 파라미터 한도(65535)를 넘고, 넘지 않더라도 그 구문을 만들고 파싱하는 데 메모리를 많이 쓴다.

500행씩 나누면 각 구문은 5,500개 파라미터를 사용한다. 프로토콜 한도보다 충분히 작으면서도 한 행씩 보낼 때보다 데이터베이스 왕복 횟수가 크게 줄어든다.

**청크 9,172개는 프로토콜 한도 때문에 나누지만, 문서 20개는 하나의 구문에 안전하게 들어가므로 나누지 않는다.** 필요하지 않은 배치 분할을 문서 경로까지 일반화하면 복잡성만 늘어난다.

### 2. 트랜잭션을 소유하는 단 하나의 함수

이제 M1.4의 구성 요소를 하나의 저장 연산으로 결합한다. 이 함수는 실제로 데이터베이스를 변경하므로 다음 계약을 엄격하게 지켜야 한다.

- 전달받은 세션에는 열린 트랜잭션이 없어야 한다.
- 성공하면 배치 전체가 커밋된다.
- 어느 구문에서든 예외가 발생하면 배치 전체가 롤백된다.

`chunk_counts`를 트랜잭션 **밖에서** 미리 세는 점에 주의한다. 문서마다 이번 배치의 청크가 몇 개인지 알아야 3단계의 `ordinal >= count` 경계를 정할 수 있다. 배치에는 있는데 청크가 0개인 문서도 `dict.fromkeys(...)`로 미리 채워져 있어야 한다. 그래야 "청크가 전부 사라진 문서"의 옛 행도 지워진다.

#### `app/ingestion/seed.py` 확장 — 단일 트랜잭션 영속화

**학습 행동 — 트랜잭션 경계 구현:** 시그니처와 docstring을 먼저 작성한다. 그다음 사전 검사 두 개와 `async with session.begin()` 안의 세 단계를 직접 구현한다.

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

**코드에서 꼭 볼 것**

- 두 사전 검사가 `session.begin()` **앞에** 있다. 거부할 호출은 트랜잭션을 열기 전에 거부한다.
- `dict.fromkeys(...)`로 문서를 먼저 채우고 청크로 증가시킨다. 청크가 0개가 된 문서도 키를 갖게 되어 3단계에서 `ordinal >= 0`, 즉 전체 삭제가 된다.
- **DELETE를 UPSERT 앞으로 옮겨도 밀집 서수 불변식 때문에 ordinal >= count인 오래된 꼬리 행만 삭제되고, 0부터 count - 1까지인 새 청크는 사라지지 않는다.** 현재 순서는 원하는 행을 먼저 UPSERT한 뒤 남은 꼬리를 정리하는 세 단계 흐름을 명확하게 보여주기 위해 유지한다.
- `return`이 `async with` 블록 **밖**이다. `SeedResult`는 커밋이 실제로 끝난 뒤에만 만들어진다. 블록 안이었다면 커밋 실패를 성공으로 보고했을 것이다.
- 세 단계 전부 `session.execute()`다. ORM 객체를 만들어 `session.add()`하지 않는다. 1만 행에 대해 인스턴스를 만들고 변경 추적을 붙일 이유가 없다.

### `session.in_transaction()`을 먼저 확인하는 이유

함수 첫 줄의 검사는 트랜잭션 소유권을 명시적으로 보장한다.

SQLAlchemy 2.x에서 이미 트랜잭션이 열린 세션에 `session.begin()`을 다시 호출하면 자동으로 중첩 트랜잭션을 만들지 않고 InvalidRequestError를 발생시킨다. 세이브포인트가 필요할 때는 begin_nested를 명시적으로 호출해야 한다.

따라서 사전 검사가 없더라도 SQLAlchemy가 중첩 호출을 거부하지만, 오류 형식과 트랜잭션 계약이 SQLAlchemy 내부 동작에 의존하게 된다. 반대로 begin_nested로 열린 트랜잭션을 허용하면 함수가 종료되어도 최종 커밋 여부는 바깥 트랜잭션 소유자에게 남는다. 이 경우 결과 객체를 반환했다는 사실만으로 배치가 커밋됐다고 말할 수 없다.

**열린 트랜잭션을 사전에 거부하면 `persist_seed_batch`가 커밋과 롤백을 직접 소유한다는 계약과 반환값의 의미가 유지된다.** 이 조건을 만족하지 못하면 SQL을 실행하기 전에 명확한 오류로 실패한다.

### 3. 두 개의 진입점 — 라이브러리와 명령줄

`persist_seed_batch()`는 이미 만들어진 배치를 받는다. 매니페스트 경로에서 시작하는 호출자를 위해 준비와 영속화를 연결하는 함수 하나를 추가한다.

매니페스트 경로를 `persist_seed_batch()`에 직접 넣지 않는 이유는 준비와 영속화의 실패 원인이 다르기 때문이다. 매니페스트 읽기는 파일 오류로 실패하고, 영속화는 연결이나 SQL 오류로 실패한다. 두 책임을 분리하면 L1 테스트는 데이터베이스 없이 코퍼스를 검증하고, L3 테스트는 이미 검증된 배치만으로 트랜잭션 계약을 확인할 수 있다.

#### `app/ingestion/seed.py` 확장 — 라이브러리 진입점

**학습 행동 — 구조 작성:** 두 줄이다. 새 로직이 없다는 점 자체가 설계 정보다.

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

준비와 영속화가 여전히 별개 함수로 남아 있다는 점이 중요하다. 테스트는 `prepare_seed_batch()`만 불러 데이터베이스 없이 코퍼스를 검증할 수 있다.

명령줄 진입점은 같은 함수들을 인자 파싱과 세션 수명 관리로 감싼다.

#### `app/ingestion/seed.py` 완성 — 명령줄 진입점

**학습 행동 — 구조 작성 후 진입점 검토:** 인자 정의를 작성하고 `_run_cli()`의 호출 순서가 준비, 스키마 생성, 영속화 순서인지 확인한다.

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

파일 마지막에 모듈 실행 가드를 덧붙인다. 이 두 줄이 있어야 `python -m app.ingestion.seed`가 동작한다.

```python
if __name__ == "__main__":
    main()
```

**코드에서 꼭 볼 것**

- **`_run_cli()`가 `app.db.session`을 함수 안에서 import하면, 이 모듈이 `database_url`을 읽고 엔진을 만드는 시점도 CLI 실행 때까지 미뤄진다.** 따라서 `seed.py`의 일반 import와 L1·L2 테스트가 DB 설정 및 async 드라이버에 의존하지 않는다.
- `prepare_seed_batch()`가 `bootstrap_schema()`보다 **먼저** 실행된다. 매니페스트가 깨졌으면 스키마를 건드리기 전에 실패한다.
- 세션은 `async with Session()`이 열고 닫는다. 트랜잭션은 그 안에서 `persist_seed_batch()`가 소유한다. **연결 수명과 트랜잭션 수명은 다른 층이다.**

### 4. 이후 모듈이 공유할 모델과 인프라

M1.4 이후의 모듈도 같은 SQLAlchemy 레지스트리를 사용한다. 레지스트리가 하나여야 모델 사이의 외래 키가 연결되고 `create_all()`이 모든 테이블을 함께 만들 수 있다. 따라서 최종 `app/db/models.py`의 L1 `Chunk` 클래스 아래에 이후 모듈에서 사용할 공유 모델을 추가한다.

지금은 이 세 모델을 사용하지 않는다. 필드를 하나씩 읽지 말고 책임만 확인한다.

| 모델 | 소유 모듈 | 책임 |
|---|---|---|
| `EvalResult` | M3 | 평가 실행 한 건을 비교 가능한 회귀 기준선으로 남긴다. |
| `Run` | M4 | 워크플로 결과 한 건을 상태와 예산 사용량과 함께 남긴다. |
| `Trace` | M4 | `Run` 하나에 속한 개별 LLM 호출 기록을 남긴다. |

지금은 `Trace.run_id`의 `ondelete="CASCADE"`와 `uq_traces_run_step`만 확인한다. 추적 기록은 자신이 속한 실행보다 오래 남지 않고, 한 실행 안에서 스텝 번호가 중복될 수 없다.

#### `app/db/models.py` 확장 — 공유 영속 모델

**학습 행동 — 모델 선언 작성:** 제약 이름을 외우지 않는다. 이후 모듈에서 이 모델을 구현할 때 각 제약의 책임을 다시 확인한다.

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

정식 `app/db/session.py`를 작성하여 하나의 모듈이 엔진과 세션 팩토리를 소유하게 한다.

#### `app/db/session.py` 생성 — 엔진과 세션 팩토리

**학습 행동 — 설정 작성:** 두 줄이지만 모듈 수준에서 실행된다는 점이 중요하다.

```python
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings

engine = create_async_engine(get_settings().database_url, echo=False)
Session = async_sessionmaker(engine, expire_on_commit=False)
```

**코드에서 꼭 볼 것**

- 두 줄 다 모듈 최상단에서 실행된다. 이 모듈을 import하는 순간 설정을 읽고 엔진을 만든다. `_run_cli()`가 이 import를 함수 안으로 미룬 이유가 이것이다.
- `expire_on_commit=False`: 커밋 후 객체 속성에 접근할 때 SQLAlchemy가 다시 조회하지 않는다. async 세션에서는 그 암묵적 재조회가 대기 없이 일어날 수 없어 오류가 된다.

정식 `app/db/bootstrap.py`를 작성한다. `--create-schema`만 이 경로를 호출한다. 스키마 마이그레이션의 대체가 아니다.

**`Base.metadata.create_all()`은 현재 ORM 메타데이터를 기준으로 없는 테이블을 만드는 부트스트랩일 뿐, 기존 운영 스키마를 변경하는 마이그레이션이 아니다.** 이미 `chunks` 테이블이 존재할 때 Python 모델에 새 열을 추가해도 `ALTER TABLE`을 생성하지 않으며, 열 이름 변경이나 데이터 변환 이력도 관리하지 않는다.

마이그레이션은 기존 스키마를 한 버전에서 다음 버전으로 옮기는 명시적인 변경 기록이다. 새 열 추가, 제약 변경, 기존 데이터 변환, 배포 순서를 검토 가능한 단계로 남긴다. 따라서 새 데모 DB에는 `create_all()`을 사용할 수 있지만, 데이터가 있는 운영 DB의 스키마 변경은 검토된 마이그레이션으로 처리해야 한다.

#### `app/db/bootstrap.py` 생성 — 스키마 부트스트랩

**학습 행동 — 구조 작성:** 두 함수의 호출 순서만 확인한다.

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

**코드에서 꼭 볼 것**

- 확장 활성화가 `create_all` **앞**이다. `chunks.embedding`이 `Vector` 타입이므로 pgvector가 없으면 테이블 생성 자체가 실패한다.
- `CREATE EXTENSION IF NOT EXISTS`와 `create_all`은 둘 다 멱등이다. 이 함수를 두 번 불러도 안전하다.

### 집중 테스트와 테스트가 지키는 계약

```bash
uv run pytest tests/db/test_03_upserts.py -k "persist_seed_batch" -q
uv run pytest tests/db/test_04_corpus.py -q
```

첫 명령은 가짜 세션으로 트랜잭션 계약을 검증하고, 두 번째는 체크인된 코퍼스 전체를 배치로 조립한다. 각 테스트가 지키는 계약은 다음과 같다.

| 테스트가 확인하는 것 | 지키는 계약 |
|---|---|
| `begin`과 `commit`이 정확히 한 번 | 시드 전체가 하나의 원자 단위다. |
| 중간 실패 시 전체 롤백 | 부분 코퍼스가 데이터베이스에 남지 않는다. |
| 청크 구문이 배치 크기로 나뉜다 | 프로토콜 파라미터 한도를 넘지 않는다. |
| 열린 트랜잭션을 넘기면 `RuntimeError` | 트랜잭션 소유권과 커밋 완료를 뜻하는 반환 계약을 지킨다. |
| 배치 크기가 0 이하면 `ValueError` | 잘못된 인자가 무한 루프나 빈 배치가 되지 않는다. |
| 배치에 문서 20개와 M1.3 청크 전부 | 매니페스트에서 배치까지 손실이 없다. |

테스트가 임시 디렉터리에서 파서 프로파일을 격리하므로, 검증이 체크인된 코퍼스 프로파일 상태를 수정하지 않는다.

### 여기까지 온 상태

영속화 파이프라인이 완성됐다. 문서 20개와 청크 9,172개는 트랜잭션을 열기 전에 검증된다. 이후 **정확히 하나의 트랜잭션** 안에서 UPSERT되고, 오래된 서수까지 정리된다.

이 장의 두 목표가 달성됐다. 같은 코퍼스를 두 번 저장해도 결과가 같고, 입력이 바뀌면 영향받은 임베딩만 무효화된다.

### 여기까지 왔을 때 설명할 수 있어야 하는 것

다음 질문의 답도 앞에서 **굵게 표시한 핵심 문장**에 있다. 질문마다 보호하려는 계약을 함께 설명해 본다.

- **왜 UPSERT만으로는 부족하고 트랜잭션이 따로 필요한가?**
  - **답:** UPSERT는 충돌 키 하나의 삽입·갱신을 멱등적으로 만들지만, 여러 문서·청크·정리 구문 전체를 한 단위로 묶지는 못한다. 트랜잭션이 있어야 중간 실패 시 코퍼스 일부만 커밋되는 일을 막는다.
- **열린 트랜잭션을 가진 세션을 거부하지 않으면 정확히 무엇이 깨지는가?**
  - **답:** SQLAlchemy 2.x에서 `begin()`을 다시 호출하면 `InvalidRequestError`가 나므로, 사전 검사가 없으면 함수의 오류 계약이 라이브러리 동작에 의존한다. 바깥 트랜잭션이나 명시적 중첩 트랜잭션을 허용하면 최종 커밋을 이 함수가 소유하지 못해 성공 반환만으로 배치 커밋을 보장할 수도 없다.
- **DELETE를 UPSERT 앞으로 옮기면 어떤 행이 사라지며, 새 청크는 왜 사라지지 않는가?**
  - **답:** 새 조밀 청크 개수 이상인 `ordinal >= count`의 오래된 꼬리 행만 삭제된다. 새 청크의 ordinal은 `0`부터 `count - 1`까지라 사라지지 않으며, 현재 순서는 UPSERT 후 정리라는 세 단계를 더 분명히 보여주기 위해 유지한다.
- **청크만 배치로 나누고 문서는 나누지 않는 근거는 무엇인가?**
  - **답:** 약 9,172개 청크에 열 11개를 한 문장으로 보내면 PostgreSQL의 65,535개 파라미터 프로토콜 한도를 넘지만, 문서는 20개뿐이라 훨씬 아래다. 문서까지 나누면 실제 한도를 해결하지 않으면서 복잡성만 늘어난다.
- **`seed.py`는 `_run_cli()`가 `app.db.session` import를 최상단으로 올리면 무엇에 의존하게 되는가?**
  - **답:** `seed.py`를 import하는 순간 DB 설정을 읽고 엔진을 만들며 비동기 DB 드라이버까지 요구하게 된다. 그러면 원래 DB 없이 가능한 L1·L2의 import와 테스트도 데이터베이스 설정에 의존한다.
- **`create_all()`을 운영 데이터베이스에 쓰면 안 되는 이유는 무엇인가?**
  - **답:** `create_all()`은 없는 표를 만들 뿐 모델 변경을 검토 가능한 `ALTER TABLE`, 데이터 변환, 버전 이력으로 바꾸지 않는다. 기존 운영 스키마는 명시적인 버전 마이그레이션으로 변경해야 한다.

이 여섯 질문에 답할 수 있다면 M1.4의 영속 계층을 이해한 것이다.

---

## 선택 과제 — 실제 PostgreSQL로 확인하기

지금까지의 테스트는 SQL을 **컴파일하여 문자열을 확인**했다. 빠르고 데이터베이스가 필요 없지만, 다음 동작까지 증명하지는 못한다.

- 트랜잭션이 실제로 커밋되는가?
- 예외가 발생하면 전체 배치가 롤백되는가?
- `CASE` 표현식이 조건에 따라 임베딩을 보존하거나 무효화하는가?

이 동작은 실행 중인 PostgreSQL에서만 확인할 수 있다. 구문이 문법적으로 올바르다는 사실만으로 실행 결과의 의미까지 보장되지는 않는다.

통합 테스트는 짧은 타임아웃으로 설정된 데이터베이스에 연결한다. 연결에 성공하면 해당 연결에서만 보이는 임시 테이블을 만든다. 같은 배치를 두 번 저장해 행 수가 유지되는지 확인하고, 센티넬 임베딩을 넣어 `index_text`가 같을 때는 보존되고 달라질 때는 무효화되는지 검증한다.

임시 테이블은 연결이 닫히면 자동으로 사라지므로 **실제 애플리케이션 스키마와 개발 데이터를 변경하지 않는다.**

```bash
uv run pytest tests/db/test_05_postgres.py -q
```

PostgreSQL에 연결할 수 있으면 테스트를 실행하고, 설정된 외부 데이터베이스를 사용할 수 없을 때만 건너뛴다. 연결에 성공한 뒤 발생한 오류는 테스트 실패로 처리한다.

임시 테이블은 테스트 연결이 닫힐 때 사라진다. 테스트는 애플리케이션 스키마를 리셋하지 않는다.

---

## 커맨드라인 시드

CLI는 앞에서 검증한 배치 준비와 트랜잭션 경로를 그대로 호출한다. 별도의 저장 로직을 만들지 않으므로 초기 스키마 생성과 재시드가 같은 영속화 구현을 공유한다.

새 데이터베이스의 경우:

```bash
uv run python -m app.ingestion.seed --create-schema
```

이미 마이그레이션된 스키마의 경우:

```bash
uv run python -m app.ingestion.seed
```

`--expected-documents`는 의도적으로 다른 매니페스트를 실행할 때만 사용한다. 프로덕션 코퍼스 기본값은 20으로 유지된다.

---

## 최종 확인

```bash
uv run pytest tests/db/test_01_models.py tests/db/test_02_records.py tests/db/test_03_upserts.py tests/db/test_04_corpus.py -q
uv run python scripts/check_doc_code.py docs/en/m1-4-seed/03-build.md docs/ko/m1-4-seed/03-build.md
uv run ruff check --no-fix app/db app/ingestion/seed.py tests/db
```

세 명령이 모두 누락 심벌로 인한 건너뛰기 없이 통과하면 M1.4가 완료된다. 선택 통합 테스트는 통과 여부와 데이터베이스 사용 불가로 인한 건너뛰기를 구분해 보고한다. 앞선 검증 명령이 실패하면 해당 문제를 해결한 뒤 다음 명령을 실행한다.

---

## M1 단계가 끝났다

여기까지가 인제스션 파이프라인 전체다. 되짚어보면 이렇게 흘러왔다.

```
2 MB of HTML     ──M1.1──▶  51,879 Blocks (with source coordinates)
                              │
                   M1.2 ──▶  data tables → markdown (print layout removed)
                              │
                   M1.3 ──▶  9,172 Chunks (citations that cannot lie)
                              │
                   M1.4 ──▶  PostgreSQL rows (idempotent)
```

**한 번도 LLM을 쓰지 않았다.** 파싱도, 표 변환도, 청킹도 전부 측정과 규칙으로 했다. 그래서 같은 입력에 항상 같은 출력이 나오고, 모든 청크가 원문 좌표로 검증된다.

RAG 시스템의 품질은 인젝션 결과에 크게 좌우된다. 이 단계에서 표 구조가 손실되거나 인용 좌표가 어긋나면 이후의 검색 또는 프롬프트 단계에서 원래 근거를 복원하기 어렵다.

## 다음 모듈로 넘기는 것

| M1.4가 만든 것 | 받는 곳 | 거기서 하는 일 |
|---|---|---|
| `chunks.index_text` | **M2** | 임베딩 입력 |
| `chunks.embedding` (NULL) | **M2** | 백필 대상 표시 |
| `chunks.content_tsv` (GIN) | **M2** | 전문 검색 |
| `chunks.citation` / 좌표 | **M4** | 보고서 인용 |
| `documents` 메타데이터 | **M2** | ticker·연도·Item 필터 |
| `eval_results` 테이블 | **M3** | 평가 결과 저장 |
| `runs` / `traces` 테이블 | **M4** | 워크플로 실행 기록 |

`eval_results`, `runs`, `traces`를 지금 만들어둔 건, 이후 모듈들이 **같은 SQLAlchemy 레지스트리**를 공유해야 하기 때문이다. `Base.metadata.create_all`이 한 번에 다 만들어야 부트스트랩이 한 곳으로 유지된다.

다음 장 M2는 임베딩 공급자를 붙이고, pgvector 코사인 검색과 PostgreSQL 전문 검색을 각각 만든 뒤 RRF로 합친다. **`embedding IS NULL`인 청크를 채우는 것**부터 시작한다.

<!-- complete-files:start -->
## 완성 기준본 — 정식 구현 전체

아래 정식 경로를 직접 생성하거나 교체한다. `_mine.py` 또는 별도의 학습자용 복사 모듈을 만들지 않는다. 앞의 발췌 코드는 개별 결정을 설명하고, 이 절의 코드 블록은 체크포인트를 마친 뒤 대조할 완성 파일이다. 표시된 타입 어노테이션과 영어 주석을 유지하며 `pyproject.toml`을 Ruff 정책의 기준으로 사용한다.

### M1.4 — 완성 체크포인트

#### 생성 또는 교체 `app/db/models.py`

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

#### 생성 또는 교체 `app/db/session.py`

<!-- file: app/db/session.py -->
```python
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings

engine = create_async_engine(get_settings().database_url, echo=False)
Session = async_sessionmaker(engine, expire_on_commit=False)
```

#### 생성 또는 교체 `app/db/bootstrap.py`

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

#### 생성 또는 교체 `app/ingestion/seed.py`

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

체크포인트를 실행한다.

```bash
uv run pytest tests/db -q
```

**예상 결과:** 선택한 모든 오프라인 테스트가 통과한다. 명시된 통합 테스트는 외부 서비스를 사용할 수 없을 때만 건너뛸 수 있다.

**중단 조건:** 테스트가 실패하거나 필수 정식 심볼이 없어서 건너뛰면 진행하지 않는다.

**디버깅:** 같은 pytest 대상을 `-vv --tb=long`으로 다시 실행하고 첫 번째로 실패한 계약을 고친 뒤 진행한다.

<!-- complete-files:end -->
