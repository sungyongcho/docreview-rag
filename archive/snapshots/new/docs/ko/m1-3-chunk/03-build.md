# M1.3 구현 — 인용이 거짓말이 되지 않는 청크 만들기

## 지금까지 모은 것

M1.1이 20개 filing에서 Block 51,879개를 뽑았고, M1.2가 그중 표를 마크다운으로 바꿨다. 이제 이걸 검색 단위로 만들 차례다.

그런데 Block은 그대로 쓸 수 없다. 실제 크기를 재보면 이렇다.

```
shortest paragraph   57 chars     ← a sentence fragment; embedding it captures no meaning
longest paragraph   3,773 chars   ← a wall of text; one hit drags in unrelated content
```

둘 다 검색에 부적합하다. 적당한 크기로 묶거나 나눠야 한다.

## 튜토리얼이 가르치는 방법이 여기선 틀리다

RAG 튜토리얼의 표준 답은 **고정 길이 분할**이다. 텍스트를 500자씩 자르고 50자 겹치게 한다. 라이브러리도 다 이걸 제공한다. 대부분의 용도에서 잘 작동한다.

**인용 가능한 증거에는 틀렸다.**

왜 그런지 구체적으로 보자. 500자에서 자르면 그 지점이 어디일지 아무도 모른다. 문장 중간일 수도 있고, 표의 3행과 4행 사이일 수도 있고, Item 7의 마지막 문단과 Item 8의 첫 문단 사이일 수도 있다.

그런 청크가 검색되면 시스템은 이렇게 말한다.

> "NVIDIA는 매출 총 이익률 72.7%를 기록했습니다. (출처: Item 7, 문자 14823-15323)"

그런데 그 범위를 원문에서 열어보면 문장 중간에서 시작해서 표 중간에서 끝난다. 숫자 72.7이 어느 항목의 것인지 그 범위만 봐서는 알 수 없다. **인용이 형식적으로는 존재하지만 실질적으로는 거짓**이다.

M1.1에서 그 좌표를 지키려고 파서까지 느린 걸로 바꿨는데, 여기서 아무 데나 자르면 그 노력이 전부 무의미해진다.

## 청킹 전략 지형

RAG가 처음이라면 "청킹"이 정해진 기법 하나처럼 들릴 수 있다. 실제로는 서로 다른 것을 포기하는 몇 가지 선택지의 집합이고, 그중 하나를 고르는 것이 이 모듈의 일이다.

| 전략 | 자르는 기준 | 얻는 것 | 포기하는 것 |
|---|---|---|---|
| 고정 길이 | N자마다 | 구현이 가장 단순하고 크기가 균일하다 | 문장·표·섹션 경계를 아무 데서나 자른다 |
| 재귀 분할 | 문단, 다음 문장, 다음 단어 순서로 시도 | 문장 중간 절단이 크게 줄어든다 | 문서 고유 구조(Item, 표)는 여전히 모른다 |
| 시맨틱 | 인접 문장 임베딩 유사도가 떨어지는 지점 | 주제가 바뀌는 곳에서 끊는다 | 임베딩 호출 비용이 들고 경계가 실행마다 달라질 수 있다 |
| 구조 인지 | 문서 자체의 구조 표지 | 경계가 원문 구조와 일치해 인용이 검증된다 | 문서 타입별 구조를 아는 코드가 필요하다 |

앞의 셋은 어떤 문서 타입에도 동작하기 때문에 라이브러리 기본값이 됐다. **이 모듈은 넷째를 고른다.** 10-K는 규정으로 구조가 고정된 문서이고, M1.1이 이미 그 구조를 좌표와 함께 추출했다. 즉 넷째 선택지의 비용인 "구조를 아는 코드"는 앞의 두 모듈에서 이미 지불했다.

덧붙이면 넷은 배타적이지 않다. 실무에서는 큰 단위를 구조로 자른 뒤 그 안에서 재귀 분할을 적용하는 조합이 흔하다. 여기서 그렇게 하지 않는 이유는 아래 경계 규칙에서 따라 나온다.

## 그래서 넘지 않을 경계를 먼저 정한다

이 모듈이 푸는 문제는 이렇다. **임베딩에 충분히 크고 검색에 충분히 작은 청크를 만들되, 인용을 거짓으로 만드는 경계는 절대 넘지 않는다.**

넘지 않을 경계는 넷이다.

| 경계 | 넘으면 생기는 일 |
|---|---|
| **Item 경계** | Item 7 청크에 Item 8 텍스트가 섞여 잘못된 섹션을 인용 |
| **표 경계** | 표를 쪼개면 행 단위 좌표가 없어서 인용할 범위 자체가 없다 |
| **내러티브 제목 경계** | "Gross Margin" 절과 "Operating Expenses" 절이 한 청크에 |
| **소스 그룹 경계** | xref Item은 문서 내 여러 구간에 흩어져 있다(M1.1 L8) |

그리고 규칙 하나. **문단은 절대 쪼개지 않는다.** 목표 크기를 넘는 긴 문단은 나누는 대신 그냥 큰 청크가 된다.

이유는 M1.1에 있다. Block이 소스 좌표를 검증할 수 있는 **가장 작은 단위**다. 문단 안쪽에는 좌표가 없으므로, 쪼개는 순간 그 조각의 인용은 검증 불가능해진다. 크기 최적화보다 검증 가능성을 택한 것이다.

## 시작 조건

M1.1과 M1.2의 포커스 테스트가 20파일 코퍼스에서 통과한 상태여야 한다. 비어 있는 `app/ingestion/chunk.py`에서 출발해 L1에서 입력 계약을 먼저 검증하고, 같은 파일에 레이어를 쌓는다.

한 가지 금지 사항이 있다. **여기서 HTML을 다시 열거나 재해석하지 않는다.** M1.3은 M1.1이 만든 좌표와 M1.2가 만든 마크다운을 소비하기만 한다. 여기서 다시 파싱하면 두 레이어가 서로 다른 소스 텍스트를 기술하게 되고, 좌표가 어긋나기 시작한다.

---

## Block에서 검색 단위까지의 경로

```
ParsedFiling.sections
    │
    ▼
L1  Verify source coordinates              M1.1 contract, not new code
    │
    ▼
L2  Chunk schema + _source_span()          fail-closed provenance validation
    │
    ▼
L3  section_units()                        structure-aware grouping
    │
    ▼
L4  _citation() + _context_header()        synthetic retrieval context
    │
    ▼
L5  chunk_filing()                         assembly, source-sort, ordinals
```

`chunk_filing()`만 공개 함수다. 그 전은 전부 내부 메커니즘이다.

| 레이어 | 책임 | 집중 테스트 |
|---|---|---|
| L1 | 정식 소스 식별과 Block 좌표 | `test_02_block_spans.py` |
| L2 | 불변 Chunk 계약과 fail-closed span | `test_01_contract.py` |
| L3 | 구조 인식 텍스트/표 단위 | `test_03_text.py`, `test_04_tables.py` |
| L4 | 격리된 검색 컨텍스트와 인용 | `test_03_text.py -k "context or narrative_heading"` |
| L5 | 조립, 소스 순서, 왕복 검증, 골든 수 | `test_05_roundtrip.py`, `test_06_golden.py` |

---

## L1 — 청커를 만들기 전에 소스 계약을 검증한다

### 왜 청커부터 시작하지 않는가

`source_pos=14823` 같은 문자 오프셋은 그냥 숫자다. 특정 파일 — 정확한 바이트를 UTF-8로 디코딩한, 줄바꿈 변환 없는 — 에 바인딩될 때만 의미를 갖는다. 파서가 소스 디코딩 방식을 조용히 바꾸면 모든 오프셋이 틀려지고, 모든 인용이 잘못된 텍스트를 가리킨다.

M1.1이 이미 이 계약을 제공한다: `read_source()`는 바이트를 직접 디코딩하고, `source_digest()`는 SHA-256을 계산하고, `ParsedFiling`은 `source_length`와 `source_sha256`을 기록한다. 청커는 이 값들에 생성하는 모든 청크를 의존한다. 이 값들이 틀리면 모든 청크가 틀리다.

그러므로 청킹 코드를 한 줄이라도 쓰기 전에 입력을 검증한다.

### 입력 계약

아래는 M1.1 데이터 구조다 — 이 모듈의 새 코드가 아니다. 청커가 무엇을 받을지 이해하기 위해 읽는다.

#### 참고 파일: `app/ingestion/parser.py`

<!-- src: app/ingestion/parser.py::Block,ParsedFiling -->
```python
@dataclass
class Block:
    kind: Literal["heading", "paragraph", "table"]
    text: str
    level: int | None = None  # 1=Item heading, 2=narrative subheading
    html: str | None = None  # raw table input for the M1.2 markdown converter
    source_pos: int | None = None  # start offset in the original HTML
    end_pos: int | None = None  # exclusive end offset in the original HTML
    source_group: int = 0  # contiguous narrative range within one Section
    source_heading: str | None = None  # title of that narrative range


@dataclass
class Section:
    part: str | None  # "I".."IV"
    item: str | None  # "1A"
    canonical_title: str  # SEC canonical title
    reported_title: str  # title used by the filing
    blocks: list[Block] = field(default_factory=list)
    status: ItemStatus = "parsed"
    reference_source: str | None = None
    # Location proves where an Item was found instead of merely claiming it was found.
    block_index: int | None = None  # heading block number
    block_range: tuple[int, int] | None = None  # block range occupied by this section
    source_pos: int | None = None  # character offset in the original HTML


@dataclass
class ParsedFiling:
    """Top-level output contract containing the complete parse of one filing."""

    doc_id: str  # "NVDA-FY2024"
    ticker: str
    cik: str
    form: str
    filing_date: str
    report_period: str
    fiscal_year: int
    accession: str
    source_url: str
    source_length: int = 0  # Unicode code points in the canonical decoded source
    source_sha256: str = ""  # SHA-256 of the exact source bytes
    sections: list[Section] = field(default_factory=list)
    item_index: list[dict] = field(default_factory=list)  # xref-only source index
    parse_status: str = "parsed"  # parsed | needs_profile_update
    warnings: list[str] = field(default_factory=list)
    profile_used: str = "saved"  # bootstrap | saved | relearned
    segment_type: str = ""
    # Validation measurements kept here so the CLI does not parse the filing twice.
    n_blocks: int = 0
    n_chars: int = 0  # total document text length, used as the coverage denominator
```

<!-- src: app/ingestion/parser.py::read_source,source_digest -->
```python
def read_source(path: str | Path) -> str:
    """Decode source bytes as UTF-8 without universal-newline translation."""
    return Path(path).read_bytes().decode("utf-8")


def source_digest(source: str) -> str:
    """Bind character offsets to the exact UTF-8 source snapshot."""
    return hashlib.sha256(source.encode("utf-8")).hexdigest()
```

소스는 바이트에서 직접 UTF-8로 디코딩된다. `source_length`는 디코딩된 문자열의 길이이고, `source_sha256`은 정확한 바이트에 바인딩한다.

### 확인

```bash
uv run pytest tests/chunk/test_02_block_spans.py -q
```

테스트가 통과하면 텍스트와 표 Block이 CRLF 입력을 포함해 같은 스냅샷으로 왕복한다. 좌표가 빠졌거나, 역전됐거나, 겹치거나, 문서 밖이면 아직 청커를 만들지 않는다. `source[block.source_pos:block.end_pos]`를 원본 요소와 먼저 대조한다.

**지금 갖고 있는 것:** 새 코드 0줄, 하지만 검증된 신뢰. 코퍼스의 모든 Block 오프셋이 올바른 파일의 올바른 위치를, 올바른 해시로 바인딩되어 가리킨다. 이것이 나머지 전부의 기반이다.

---

## L2 — Chunk 계약과 fail-closed span

### 청크가 지나갈 먼 길

여기서 만드는 `Chunk` 객체는 앞으로 이런 여정을 거친다.

```
M1.3 creation → M1.4 DB storage → M2 embedding/retrieval → M4 LLM judgment → M4 report citation
```

중간의 어느 지점에서든 누군가 필드를 바꾸면 어떻게 될까. body를 정리하거나, span을 살짝 조정하거나, ordinal을 다시 매기면.

**인용이 조용히 거짓이 된다.** 크래시도 에러도 없다. 그냥 틀린 답이 근거까지 갖춘 모습으로 사용자에게 간다. 이런 버그는 사후에 찾기가 대단히 어렵다.

그래서 `frozen=True`를 건다. 바꾸려고 시도한 **바로 그 지점에서** `FrozenInstanceError`가 난다. 청크를 "수정"하는 유일한 방법은 `dataclasses.replace()`로 새 객체를 만드는 것이고, 그건 명시적이라 코드 리뷰에서 보인다.

### 이상한 span을 만나면 추측하지 말고 거부한다

좌표가 이상한 경우가 실제로 나온다. `source_pos`가 `None`이거나, 끝이 시작보다 작거나, 문서 길이를 넘어가거나.

여기서 "적당히 처리"하고 싶은 유혹이 생긴다. 없으면 0으로 두고, 뒤집혔으면 바로잡고, 넘치면 잘라내고. 프로그램은 계속 돌아간다.

문제는 그 청크들이 **잘못된 텍스트를 인용한다**는 것이다. 그럴듯한 답이 나오고, 근거 좌표도 붙어 있고, 열어보면 엉뚱한 문단이다.

검색 시스템에서 **잘못된 인용은 인용 없음보다 나쁘다.** "결과 없음"을 본 사용자는 다시 물어볼 줄 안다. 자신 있게 틀린 인용을 본 사용자는 그 거짓 증거로 판단을 내린다. 10-K 리뷰라면 투자나 감사 판단이 걸린 일이다.

그래서 이 청커는 **출처가 불확실한 청크를 만드느니 만들기를 거부한다.** 파이프라인이 멈추면 사람이 원인을 보게 되지만, 조용히 넘어가면 아무도 안 본다.

### 무엇을 작성하고 어디를 직접 구현할까

L2는 아직 아무것도 청킹하지 않는다. 청크가 *무엇인지*, 그리고 시스템이 무엇을 만들기를 거부하는지를 한 파일에 세 단계로 정한다.

| 구간 | 학습 행동 | 여기서 얻어야 하는 것 |
|---|---|---|
| 모듈 기반 | **구조 작성** | 이 모듈이 딛고 선 계약 |
| `ChunkConfig`와 `Chunk` | **모델 선언 작성** | 텍스트 필드가 하나가 아니라 둘인 이유 |
| `_source_span` | fail-closed 게이트를 **직접 구현** | 어떤 잘못된 span이 청크가 되지 못하는가 |

### 모듈 생성

`app/ingestion/chunk.py`를 모듈 설명, import, 공개 타입으로 만든다:

#### `app/ingestion/chunk.py` 생성 — 모듈 기반

```python
"""Structure-aware chunking with source-stable citations.

The chunk id is deliberately not the citation. Re-chunking changes ids and would
invalidate a golden set, making chunk-size ablation impossible. Every chunk instead
carries a `[start_char, end_char)` span into the immutable source filing.

The pipeline keeps source text and synthetic context separate:

    body             text derived from the cited source span
    context_header   filing / Item / narrative heading metadata
    content          context_header + body (the text indexed for retrieval)

This separation makes citation round-trip tests possible even though contextual
headers are intentionally repeated across chunks.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import re
from typing import Literal

from app.ingestion.parser import Block, ParsedFiling, Section
from app.ingestion.tables import table_to_markdown

ChunkKind = Literal["text", "table"]
```

### 목표 크기 1,200자는 정답이 아니다

`DEFAULT_TARGET_TEXT_CHARS = 1_200`을 보면 "왜 1,200인가"가 궁금해진다. 솔직한 답은 **아직 모른다**는 것이다.

청크 크기는 RAG에서 정답이 없는 파라미터다. 작으면 정밀하지만 문맥이 부족하고, 크면 문맥은 충분하지만 관련 없는 내용이 섞인다. 도메인마다 다르고, 임베딩 모델마다 다르다.

그래서 이 값은 **결론이 아니라 실험 조건(ablation arm)** 으로 둔다. M3가 여러 값으로 같은 코퍼스를 청킹해서 검색 품질을 비교하고, 이긴 설정을 기록한다.

이게 가능한 이유가 M1.3 설계의 핵심과 맞닿아 있다. **인용이 청크 ID가 아니라 소스 좌표를 쓰기 때문**이다. 청크 크기를 바꾸면 청크 ID는 전부 달라지지만 소스 좌표는 그대로다. 그래서 정답 데이터(골든 셋)를 다시 만들 필요 없이 설정만 바꿔 비교할 수 있다.

만약 인용이 청크 ID였다면 크기를 바꿀 때마다 골든 셋이 무효가 되고, 이 실험 자체가 불가능했을 것이다.

먼저 그 의도를 적은 주석, 그다음 상수와 타입을 작성한다.

#### `app/ingestion/chunk.py` 확장 — 설정과 공개 타입

```python
# Defaults are starting arms, not conclusions. M3 evaluates alternatives and records
# the winning configuration; callers can change the value without changing logic.
```

<!-- src: app/ingestion/chunk.py::DEFAULT_TARGET_TEXT_CHARS,SOURCE_SHA256_RE -->
```python
DEFAULT_TARGET_TEXT_CHARS = 1_200
SOURCE_SHA256_RE = re.compile(r"[0-9a-f]{64}", re.ASCII)
```

<!-- src: app/ingestion/chunk.py::ChunkConfig,Chunk -->
```python
@dataclass(frozen=True, slots=True)
class ChunkConfig:
    """Tunable chunking parameters used by the M3 ablation."""

    target_text_chars: int = DEFAULT_TARGET_TEXT_CHARS

    def __post_init__(self) -> None:
        if self.target_text_chars <= 0:
            raise ValueError("target_text_chars must be positive")


@dataclass(frozen=True, slots=True)
class Chunk:
    """A retrieval unit whose citation survives re-chunking."""

    doc_id: str
    item: str | None
    kind: ChunkKind
    ordinal: int
    body: str
    context_header: str
    citation: str
    start_char: int
    end_char: int
    source_sha256: str = ""

    @property
    def content(self) -> str:
        """Text sent to indexing: repeated context followed by source-derived body."""
        return f"{self.context_header}\n\n{self.body}" if self.context_header else self.body
```

전체 `Chunk` 계약은 뒤의 함수들에서 필드 의미를 추론하는 것보다 필드 지도로 먼저 보는 편이 이해하기 쉽다.

| 필드 | 값 또는 제약 | 역할 |
|---|---|---|
| `doc_id` | filing 식별자 | 청크를 하나의 파싱된 filing에 연결한다. |
| `item` | SEC Item 또는 `None` | 존재하는 경우 섹션 식별자를 보존한다. |
| `kind` | `"text"` 또는 `"table"` | 출처를 보존하는 변환 경로를 선택한다. |
| `ordinal` | 문서 안의 0부터 시작하는 순서 | filing 안에서 각 청크에 결정론적 위치를 부여한다. |
| `body` | 원문에서 파생된 텍스트 | 왕복 테스트가 검증하는 근거를 제공한다. |
| `context_header` | 합성 메타데이터 | 원문에서 왔다고 가장하지 않으면서 검색 문맥을 보탠다. |
| `citation` | 사람이 읽는 출처 레이블 | filing과 섹션을 사람이 식별하게 한다. |
| `start_char`, `end_char` | 반열린 원문 범위 `[start_char, end_char)` | 원문에서 정확한 근거를 기계적으로 다시 열게 한다. |
| `source_sha256` | 소문자 SHA-256 | 범위를 하나의 불변 원문 스냅샷에 묶는다. |
| `content` | 파생 프로퍼티 | 두 필드를 바꾸지 않고 색인용으로 `context_header`와 `body`를 결합한다. |

### `body`와 `context_header`를 굳이 나눈 이유

`Chunk`에 텍스트 필드가 왜 둘인지 궁금할 것이다. 합쳐서 하나로 두면 간단할 텐데.

배경은 이렇다. 검색된 청크는 자기가 뭘 말하는지 밝혀야 한다. "매출총이익률이 72.7%였다"만 있으면 어느 회사, 어느 해, 어느 섹션인지 모른다. 그래서 `NVDA FY2024, Item 7, Liquidity` 같은 레이블을 붙여서 임베딩한다. 검색 품질도 오르고, LLM도 발췌를 이해한다.

문제는 **이 레이블이 원문에 없다**는 것이다. 우리가 만든 합성 텍스트다.

이걸 `body`에 섞으면 어떻게 될까. M1.3의 가장 중요한 테스트가 깨진다. `source[start_char:end_char]`를 잘라서 `body`와 같은지 비교하는 **왕복 테스트**다. body에 원문에 없는 접두사가 붙어 있으니 당연히 불일치한다.

여기서 "테스트가 접두사를 허용하게 고치자"는 유혹이 온다. 그러면 통과는 한다. 대신 **진짜 인용 드리프트를 감지하는 능력을 잃는다.** 좌표가 어긋나서 생긴 불일치와 접두사 때문에 생긴 불일치를 구분할 수 없게 되니까.

그래서 필드를 나눈다. 원칙은 단순하다.

| 필드 | 내용 | 쓰는 곳 |
|---|---|---|
| `body` | **원문에서 온 텍스트만** | 왕복 테스트, 인용 검증 |
| `context_header` | **우리가 만든 메타데이터만** | — |
| `content` | 둘을 합친 것 | 임베딩, 검색 인덱스 |

이러면 왕복 테스트는 `body`를 엄격하게 검증하고, 검색은 `content`를 쓴다. 서로 간섭하지 않는다. **합성한 것과 원본에서 온 것을 데이터 구조에서 분리해두면 검증 가능성이 살아남는다.**

### span 검증기

이 함수가 fail-closed 게이트다. 모든 청크가 이것을 통과해야 한다.

#### 대상 파일: `app/ingestion/chunk.py`

<!-- src: app/ingestion/chunk.py::_source_span -->
```python
def _source_span(blocks: list[Block], source_length: int | None = None) -> tuple[int, int]:
    """Validate and aggregate one ordered, contiguous narrative block group."""
    if not blocks or any(block.source_pos is None or block.end_pos is None for block in blocks):
        raise ValueError("cannot create a chunk without complete source spans")

    groups = {block.source_group for block in blocks}
    if len(groups) != 1:
        raise ValueError("cannot create a chunk across source groups")

    previous_end: int | None = None
    for block in blocks:
        start, end = block.source_pos, block.end_pos
        assert start is not None and end is not None
        if not 0 <= start < end:
            raise ValueError(f"invalid block source span: [{start}, {end})")
        if previous_end is not None and start < previous_end:
            raise ValueError("chunk blocks are out of source order or overlap")
        if source_length is not None and end > source_length:
            raise ValueError(
                f"block source span ends beyond source length: {end} > {source_length}"
            )
        previous_end = end

    start = blocks[0].source_pos
    end = blocks[-1].end_pos
    assert start is not None and end is not None
    return start, end
```

### 각 검사가 잡는 것

검증을 순서대로 따라가보자:

1. **빠진 좌표.** Block에 `source_pos`나 `end_pos`가 없으면 span을 알 수 없다. 일찍 거부하면 `None`이 산술을 통해 `0`이 되는 것을 막는다.

2. **그룹 간 span.** `source_group`은 Section 내의 연속 내러티브 범위를 식별한다. Intel filing에는 여러 비연속 범위를 소유하는 Item이 있다. 두 그룹에 걸치는 청크를 허용하면 그 사이에 있는 다른 Item의 텍스트까지 포함하는 인용이 만들어진다.

3. **역전 또는 제로 너비 span.** `0 <= start < end`는 음수 위치, start-after-end, 빈 span을 잡는다. 어느 것이든 잘못된 텍스트나 아무 텍스트도 슬라이스하지 못하는 인용을 만든다.

4. **순서 오류 또는 겹치는 Block.** Block B가 Block A 끝나기 전에 시작하면 같은 소스 텍스트가 두 청크에 인용된다. 겹침 검사가 이중 계산을 방지한다.

5. **문서 범위 초과.** `end > source_length`이면 인용이 파일 끝을 넘어 가리킨다. 파서의 off-by-one 에러를 잡는다.

함수는 가장 좁은 포함 span을 반환한다: 첫 Block의 시작부터 마지막 Block의 끝까지. Block 사이의 빈 곳(heading이나 다른 요소가 있는 곳)은 허용된다 — 소스 범위의 일부이지만 청크 body의 일부는 아니다.

### 확인

```bash
uv run pytest tests/chunk/test_01_contract.py -q
```

테스트가 통과하면 유효하지 않은 제한과 span이 거부되고 `Chunk`가 불변임이 증명된다. 실패하면 두 개의 작은 Block으로 `_source_span()`을 호출해 group ID와 인접한 start/end 값을 먼저 확인한다.

**지금 갖고 있는 것:** 냉동 스키마와 불확실한 출처의 청크 생성을 거부하는 span 검증기가 있는 import 가능한 모듈. 아직 청크는 없다 — 아무것도 통과하기 전에 게이트를 먼저 만들었다.

---

## L3 — 구조 인식 텍스트와 표 단위

### 무엇을 작성하고 어디를 직접 구현할까

L3은 이 모듈에서 알고리즘이 들어 있는 유일한 섹션이다. 한 파일, 두 단계다.

| 구간 | 학습 행동 | 여기서 얻어야 하는 것 |
|---|---|---|
| `_Unit` | **레코드 선언 작성** | 그룹화 결정이 기억해야 하는 것 |
| `section_units` | 누적기를 **직접 구현** | 어떤 경계가 단단하고 어떤 것이 선호인가 |

### 그룹화 문제

다음 Block들이 순서대로 있는 Section을 생각해보자:

```
heading   "Revenue Recognition"          group=1
paragraph "The Company recognizes..."    group=1  (312 chars)
paragraph "Performance obligations..."   group=1  (487 chars)
paragraph "Contract assets decreased..." group=1  (203 chars)
table     <table>...</table>             group=1
paragraph "The following table..."       group=1  (89 chars)
heading   "Deferred Revenue"             group=2
paragraph "Deferred revenue was..."      group=2  (445 chars)
```

처음 세 문단은 합계 1,002자 — 1,200자 목표 미만이다. 하나의 텍스트 청크가 돼야 한다. 표는 자체 청크여야 한다. 표 뒤의 짧은 문단은 새 텍스트 누적을 시작한다. "Deferred Revenue" heading은 대기 중인 것을 flush하고 내러티브 컨텍스트를 리셋한다. 그 뒤의 문단은 다른 소스 그룹에 속한다.

### `_Unit` 중간체가 나타내는 것

`_Unit`은 공개 `Chunk` 전의 마지막 단계다. body 텍스트, 소스 Block들(span 계산용), 내러티브 heading(컨텍스트용)을 담는다. filing 수준 메타데이터는 담지 않는다 — 그것은 L4에서 온다. 중간체를 가볍게 유지하면 전체 `ParsedFiling`을 구성하지 않고도 `section_units()`를 테스트할 수 있다.

### 왜 긴 문단을 나누면 안 되는지, 구체적으로

앞에서 "문단은 쪼개지 않는다"고 했는데, 3,773자짜리 문단을 보면 마음이 흔들린다. 1,200자씩 세 조각으로 나누면 깔끔할 텐데. 모든 문자 단위 분할기가 그렇게 한다.

무엇이 문제인지 구체적으로 보자.

문단을 1,200자 지점에서 나누면 그 조각의 소스 좌표가 필요하다. 그런데 파서는 **Block 경계의 좌표만** 준다. Block 안쪽 임의 지점의 좌표는 없다.

계산하면 되지 않을까? Block의 span이 `[14823, 18596)`이니 텍스트 1,200번째 문자는 대략 `14823 + 1200 = 16023`쯤일 것이다.

**"대략"이 문제다.** 원본 HTML에는 추출된 텍스트에 없는 것들이 잔뜩 있다. 태그, HTML 엔티티, 공백, 속성. 텍스트 1,200번째 문자가 실제 HTML에서는 3,000번째일 수도 있고 1,500번째일 수도 있다.

최악의 경우 보간한 좌표가 **HTML 태그 한가운데** 떨어진다. 그 인용을 열어보면 이런 게 나온다.

```
"...cited evidence: <td class=\"num\" colspan=\"2\" style=\"padding-l"
```

사용자에게 보여줄 수 있는 인용이 아니다.

**그래서 Block은 절대 나누지 않는다. 긴 문단은 그냥 큰 청크가 된다.** `target_text_chars`는 "가능하면 이 정도로 묶어라"는 선호이지, 넘으면 잘라야 하는 하드 리미트가 아니다.

크기 균일성을 포기하고 검증 가능성을 얻는 거래다. RAG에서 이런 거래를 어디서 할지 정하는 게 설계의 대부분이다.

### 코드

`_source_span()` 다음에 이 구분선을 추가하고, 바로 아래에 `_Unit` 타입과 `section_units()`를 작성한다:

#### `app/ingestion/chunk.py` 확장 — 텍스트 청크 조립

```python
# ── L2. Text chunks ──────────────────────────────────────────────────────────
```

<!-- src: app/ingestion/chunk.py::_Unit,section_units -->
```python
@dataclass(frozen=True, slots=True)
class _Unit:
    kind: ChunkKind
    body: str
    blocks: list[Block]
    narrative_heading: str | None


def section_units(section: Section, config: ChunkConfig) -> list[_Unit]:
    """Build source-ordered units without crossing a table or narrative heading.

    Paragraphs are never split internally: source block boundaries are the stable
    units. A single long paragraph may therefore exceed the target. The target is a
    grouping preference, not a destructive hard limit.
    """
    units: list[_Unit] = []
    pending: list[Block] = []
    pending_chars = 0
    narrative_heading: str | None = None
    active_group: int | None = None

    def flush() -> None:
        nonlocal pending, pending_chars
        if pending:
            units.append(
                _Unit(
                    kind="text",
                    body="\n\n".join(block.text for block in pending),
                    blocks=pending,
                    narrative_heading=narrative_heading,
                )
            )
        pending = []
        pending_chars = 0

    for block in section.blocks:
        if active_group != block.source_group:
            flush()
            active_group = block.source_group
            narrative_heading = block.source_heading
        if block.kind == "heading":
            flush()
            narrative_heading = block.text
            continue
        if block.kind == "table":
            flush()
            markdown = table_to_markdown(block.html)
            if markdown:
                units.append(_Unit("table", markdown, [block], narrative_heading))
            continue
        if not block.text.strip():
            continue

        separator = 2 if pending else 0
        if pending and pending_chars + separator + len(block.text) > config.target_text_chars:
            flush()
        pending.append(block)
        pending_chars += (2 if len(pending) > 1 else 0) + len(block.text)
    flush()
    return units
```

### 누적기가 작동하는 방식

함수는 문단 Block의 `pending` 버퍼를 유지한다. 각 Block 종류에 대한 제어 흐름을 따라가보자:

1. **소스 그룹 변경.** 대기 텍스트를 flush한다. 활성 그룹과 내러티브 heading을 갱신한다. 이것이 비연속 범위에 걸치는 청크를 방지한다 — 첫 구현에서 12개의 거짓 인용을 만들었던 바로 그 문제다.

2. **Heading.** 대기 텍스트를 flush한다. 내러티브 heading을 갱신한다. heading 자체는 청크가 되지 않는다 — L4를 통해 `context_header`로 간다. heading 텍스트를 body에 포함하면 인용된 소스 증거의 일부가 아닌 내용이 추가된다.

3. **표.** 대기 텍스트를 flush한다. M1.2를 통해 HTML을 markdown으로 변환한다. 결과가 비어있지 않으면 단일 Block 표 unit을 만든다. 비어있으면(레이아웃 전용 표) 버린다. 표는 근본적으로 다른 구조이므로 인접 문단과 절대 그룹화하지 않는다.

4. **빈 문단.** 건너뛴다. 빈 Block은 증거를 담지 않는다.

5. **내용 있는 문단.** 이 문단을 추가하면 목표를 초과하는지 확인한다. 그렇다면 먼저 flush하고 새 누적을 시작한다. `separator = 2`는 body에서 문단을 연결하는 `\n\n`을 고려한다.

6. **Section 끝.** 루프 뒤의 마지막 `flush()`가 마지막 문단 그룹이 유실되지 않게 보장한다.

### 왜 공백이 아니라 `\n\n`으로 연결하는가

문단은 의미적으로 구별된다. 공백으로 연결하면 "...15% 감소했다."와 "회사는..."이 하나의 문장으로 합쳐진다. 이중 줄바꿈은 body 텍스트에서 문단 정체성을 보존하고, 임베딩 모델의 토큰 경계에도 도움이 된다.

### 확인

공개 `chunk_filing()` 조립기가 아직 없으므로 이 레이어를 직접 확인한다:

```bash
uv run python -c "from app.ingestion.chunk import ChunkConfig, section_units; from app.ingestion.parser import Block, Section; s = Section('II', '7', 'MD&A', 'MD&A', [Block('paragraph', 'first', source_pos=10, end_pos=20), Block('paragraph', 'second', source_pos=20, end_pos=30)]); u = section_units(s, ChunkConfig()); assert [x.body for x in u] == ['first\\n\\nsecond']"
```

조용히 끝나면 인접 문단이 순서대로 그룹화된 것이다. 경계 케이스가 실패하면 각 unit의 kind, 소스 그룹, span을 출력하고 첫 전환에서 빠진 `flush()`를 찾는다.

**지금 갖고 있는 것:** 모든 경계를 존중하는 구조 인식 그룹화 — Item, 표, heading, 소스 그룹. 문단은 절대 나뉘지 않는다. 표는 절대 산문과 합쳐지지 않는다. 누적기는 모든 전환 지점에서 flush한다.

---

## L4 — 검색 컨텍스트와 인용 레이블

### 맥락 없는 청크는 쓸모가 반쯤 없다

검색 결과로 이런 청크가 나왔다고 하자.

```text
"Net revenue increased 122% compared to the prior year, driven by Data Center revenue growth of 217%."
```

인상적인 숫자다. 그런데 **어느 회사의, 어느 해 이야기인가?** 20개 filing이 섞인 인덱스에서 이 문장만으로는 알 수 없다. LLM에게 이걸 근거로 주면 회사를 헷갈리거나 연도를 잘못 말하기 딱 좋다.

그래서 맥락을 붙인다.

```text
"NVDA FY2024 · Item 7 · Management's Discussion · Liquidity

Net revenue increased 122%..."
```

이제 청크가 스스로를 설명한다. 검색 품질도 오른다 — "NVIDIA 2024 매출"로 검색하면 본문에 "NVIDIA"나 "2024"가 없어도 헤더가 걸린다.

이 문자열은 원문에 없다. filing 메타데이터와 섹션 제목으로 우리가 조립한 것이고, 그래서 앞에서 말한 대로 `body`가 아니라 `context_header`에 들어간다.

### 무엇을 작성하고 어디를 직접 구현할까

L4는 새 데이터를 만들지 않는다. filing이 이미 아는 것에서 레이블 둘을 파생한다.

| 구간 | 학습 행동 | 여기서 얻어야 하는 것 |
|---|---|---|
| `_citation` | **필드 매핑 작성** | 사람이 읽는 단 하나의 레이블 |
| `_context_header` | 조합을 **직접 구현** | 중복 제거 검사가 존재하는 이유 |

### `citation`과 `context_header`가 따로 있는 이유

둘 다 합성 텍스트인데 왜 필드가 둘일까. 용도가 다르다.

| 필드 | 예시 | 용도 |
|---|---|---|
| `citation` | `NVDA FY2024 · Item 7` | **사람에게 보여주는** 안정적 레이블 |
| `context_header` | `NVDA FY2024 · Item 7 · Management's Discussion · Liquidity` | **검색 인덱스에 넣는** 풍부한 맥락 |

`citation`은 최종 보고서에 그대로 인쇄된다. 짧고 안정적이어야 한다. 내러티브 소제목까지 들어가면 같은 Item의 인용이 청크마다 달라 보여서 오히려 헷갈린다.

`context_header`는 검색용이라 길수록 유리하다. 소제목까지 들어가면 "NVIDIA 유동성"으로 검색했을 때 걸린다.

**표시용과 처리용을 같은 필드로 쓰면 둘 중 하나는 항상 어색해진다.**

### 코드

`_source_span()` 다음, 이전 단계에서 추가한 L2 구분선 바로 앞에 다음 두 함수를 삽입한다:

#### 대상 파일: `app/ingestion/chunk.py`

<!-- src: app/ingestion/chunk.py::_citation,_context_header -->
```python
def _citation(filing: ParsedFiling, section: Section) -> str:
    item = f"Item {section.item}" if section.item else "Unnumbered section"
    return f"{filing.ticker} FY{filing.fiscal_year} · {item}"


def _context_header(
    filing: ParsedFiling, section: Section, narrative_heading: str | None = None
) -> str:
    """Build context that remains useful when a chunk is retrieved in isolation."""
    parts = [_citation(filing, section)]
    title = section.canonical_title or section.reported_title
    if title:
        parts.append(title)
    if narrative_heading and narrative_heading != title:
        parts.append(narrative_heading)
    return " · ".join(parts)
```

### 왜 중복 제거 검사가 있는가

`narrative_heading != title` 조건은 `"NVDA FY2024 · Item 7 · Management's Discussion · Management's Discussion"` 같은 출력을 방지한다. 섹션의 정식 제목과 현재 내러티브 heading이 같은 문자열일 때 발생한다 — 하위 섹션이 없는 Item에서 흔하다. 검사 없이는 반복된 제목이 토큰을 낭비하고 깨져 보인다.

### 확인

```bash
uv run python -c "from app.ingestion.chunk import _context_header; from app.ingestion.parser import ParsedFiling, Section; f = ParsedFiling('NVDA-FY2024', 'NVDA', '1045810', '10-K', '2024-02-21', '2024-01-28', 2024, 'x', 'https://example.test'); s = Section('II', '7', 'Management Discussion', 'Management Discussion'); assert _context_header(f, s, 'Liquidity').endswith('Liquidity')"
```

조용히 끝나면 내러티브 제목이 컨텍스트에 나타나고 자기 자신과 중복 제거되지 않은 것이다. 의심스러운 실제 경계는 두 인접 범위의 `source_group`, `source_heading`, `reported_title`, 결과 header를 비교한다.

**지금 갖고 있는 것:** 모든 청크가 사람이 읽을 수 있는 인용과 기계가 사용하는 컨텍스트 header를 갖게 된다. 합성 텍스트는 자체 필드에 갇힌다 — `body`는 순수한 소스 증거로 남는다.

---

## L5 — 조립, 소스 정렬, 번호 재부여

### 무엇을 작성하고 어디를 직접 구현할까

L5는 이 모듈의 유일한 공개 함수를 쓴다. 앞의 전부가 준비였다.

| 구간 | 학습 행동 | 여기서 얻어야 하는 것 |
|---|---|---|
| `chunk_filing`의 가드 | 코퍼스 수준 가드를 **직접 구현** | 해시 없는 filing을 청킹할 수 없는 이유 |
| 중첩된 `append` | **필드 매핑 작성** | 앞의 모든 조각이 마침내 만나는 지점 |
| 정렬과 번호 재부여 | 순서 불변조건을 **직접 구현** | ordinal을 처음이 아니라 마지막에 매기는 이유 |

### 최종 연결

이 함수에서 지금까지 만든 모든 계약이 합쳐진다. filing의 소스 식별을 검증하고, section을 순회하고, unit을 만들고, span을 계산하고, 최종 청크 목록을 생성한다.

### Intel 문서에서만 터지는 순서 문제

일반적인 heading 기반 문서는 문제가 없다. 파서가 위에서 아래로 훑으며 만들었으니 section 리스트가 이미 소스 순서다.

**xref 문서는 다르다.** M1.1 L8을 떠올려보자. `segment_by_xref`는 색인표를 순회하며 Section을 만든다. 그래서 결과가 **SEC Item 번호 순서**로 나온다. Item 1, 1A, 2, 3… 문서 안에서 그 내용이 실제로 어디 있는지와 무관하게.

그리고 Intel의 Item 7은 문서의 5, 19-44, 47-51페이지에 흩어져 있다.

이 상태로 도착 순서대로 ordinal을 매기면 어떻게 될까. Item 1 청크가 0~15번, Item 2 청크가 16~30번을 받는다. 그런데 Item 2의 내용이 문서에서는 Item 1보다 앞에 있을 수 있다.

ordinal 순서로 청크를 훑는 사람은 **문서를 앞뒤로 뛰어다니는 내용**을 보게 된다. "이전 청크"나 "다음 청크"를 가져오는 기능을 만들면 엉뚱한 게 나온다.

**해법은 간단하다. 다 만든 뒤 소스 위치로 정렬하고, 그다음에 ordinal을 매긴다.** `(start_char, end_char)`로 안정 정렬하면 문서 순서가 복원된다. 그러면 ordinal `0..n-1`이 "어느 Item에 속하나"가 아니라 "문서에서 몇 번째로 나오나"를 뜻하게 된다.

### frozen 객체의 번호를 바꾸는 법

정렬은 청크를 다 만든 뒤에 한다. 그런데 각 청크는 만들어질 때 이미 임시 ordinal을 받아뒀다. 정렬 후 다시 매겨야 한다.

`chunk.ordinal = i`는 안 된다. L2에서 `frozen=True`를 걸었으니 `FrozenInstanceError`가 난다.

`dataclasses.replace(chunk, ordinal=i)`를 쓴다. ordinal만 바뀌고 나머지는 복사된 새 객체가 나온다.

번거로워 보이지만 이게 frozen의 값어치다. **파이프라인 전체에서 청크의 ordinal이 바뀌는 지점이 여기 한 군데뿐임이 코드로 보장된다.** 다른 어디선가 몰래 바꿨다면 그 자리에서 예외가 났을 것이다.

### 코드

`section_units()` 다음에 이 구분선을 추가하고, 아래에 `chunk_filing()`을 놓는다:

#### `app/ingestion/chunk.py` 확장 — filing 청킹 진입점

```python
# ── L3/L4/L5. Tables, context, and source spans ──────────────────────────────
```

<!-- src: app/ingestion/chunk.py::chunk_filing -->
```python
def chunk_filing(filing: ParsedFiling, config: ChunkConfig | None = None) -> list[Chunk]:
    """Convert a parsed filing into ordered text/table chunks with source spans."""
    if filing.source_length <= 0:
        raise ValueError(f"{filing.doc_id} has no canonical source length")
    if SOURCE_SHA256_RE.fullmatch(filing.source_sha256) is None:
        raise ValueError(f"{filing.doc_id} has no canonical source SHA-256")
    cfg = config or ChunkConfig()
    chunks: list[Chunk] = []

    def append(
        section: Section,
        kind: ChunkKind,
        body: str,
        blocks: list[Block],
        narrative_heading: str | None = None,
    ) -> None:
        start, end = _source_span(blocks, filing.source_length)
        chunks.append(
            Chunk(
                doc_id=filing.doc_id,
                item=section.item,
                kind=kind,
                ordinal=len(chunks),
                body=body,
                context_header=_context_header(filing, section, narrative_heading),
                citation=_citation(filing, section),
                start_char=start,
                end_char=end,
                source_sha256=filing.source_sha256,
            )
        )

    for section in filing.sections:
        for unit in section_units(section, cfg):
            append(
                section,
                unit.kind,
                unit.body,
                unit.blocks,
                unit.narrative_heading,
            )

    # Heading-based sections already arrive in source order. Xref sections arrive
    # in SEC Item order instead, and one Item can own multiple narrative ranges.
    # A stable span sort restores document order before ordinals are materialized.
    chunks.sort(key=lambda chunk: (chunk.start_char, chunk.end_char))
    return [replace(chunk, ordinal=ordinal) for ordinal, chunk in enumerate(chunks)]
```

### 함수를 따라가기

1. **filing 식별 검증.** `source_length`가 양수가 아니거나 `source_sha256`이 유효한 64자 hex 문자열이 아니면 전체 filing을 거부한다. 식별 없는 filing은 검증 가능한 인용을 만들 수 없다.

2. **내부 `append()` 정의.** 이 클로저는 filing과 증가하는 `chunks` 리스트를 캡처한다. 각 호출은 span을 검증하고(`_source_span`), context header를 만들고 (`_context_header`), frozen `Chunk`를 생성한다. 임시 ordinal은 `len(chunks)` — section이 소스 순서로 도착할 때만 맞다.

3. **section과 unit 순회.** 각 section에 대해 `section_units()`가 L3의 구조 인식 그룹화를 생성한다. 각 unit이 `append()`를 통해 청크가 된다.

4. **소스 위치로 정렬.** `(start_char, end_char)`에 의한 안정 정렬이 xref filing의 ordinal 부여를 수정한다. Heading 기반 filing에서는 정렬이 무연산이다 — 이미 순서대로 도착한다.

5. **ordinal 재부여.** `replace()`를 사용한 리스트 컴프리헨션이 소스 순서의 밀집 ordinal `0..n-1`로 최종 청크 목록을 생성한다.

### 확인

이 코드를 붙이면 `chunk_filing()`이 처음 존재한다. L3과 L4에서 지연된 동작을 실행한 뒤 왕복과 골든 게이트로 진행한다:

```bash
uv run pytest tests/chunk/test_03_text.py tests/chunk/test_04_tables.py -q
uv run pytest tests/chunk/test_03_text.py -k "context or narrative_heading" -q
uv run pytest tests/chunk/test_05_roundtrip.py tests/chunk/test_06_golden.py -q
```

세 명령이 모두 통과하면:
- 긴 문단과 표가 통째로 남는다 (내부 분할 없음)
- 합성 컨텍스트가 소스 파생 body에서 격리된다
- 모든 body Block이 정확히 한 번 소비된다 (빈 곳 없음, 중복 없음)
- 청크 span이 겹치지 않는다
- 골든 수가 코퍼스 기준선과 일치한다

실패 시 골든 값을 바꾸지 않는다. 소스 순서에서 첫 빈 곳, 겹침, 또는 반복된 Block을 찾는다.

### 여기까지 온 상태

20개 filing에서 **9,172개 청크**가 나온다. 텍스트 8,083개, 표 1,089개.

이 숫자가 이 프로젝트의 기준선이다. 앞으로 파서를 고치거나 청킹 파라미터를 바꾸면 이 값이 변하고, 골든 테스트가 그걸 알려준다.

모든 청크가 검증된 소스 span과 인용, 검색 컨텍스트를 갖고 있다. `body`에는 원문에서 온 텍스트만 있고, ordinal은 section이 어떤 순서로 도착했든 문서 순서를 반영한다.

### 여기까지 왔을 때 설명할 수 있어야 하는 것

- **청크 id가 인용이 될 수 없는 이유는 무엇인가?**
  - **답:** 청크 id는 크기나 묶는 방식이 바뀌면 달라지고 원문의 정확한 구간을 가리키지도 않는다. 문서 식별자·원문 해시·반열린 문자 구간은 청킹 실험이 달라져도 검증할 수 있다.
- **`body`와 `context_header`를 합치면 어떤 테스트가 불가능해지는가?**
  - **답:** 합성 헤더는 원문에 없으므로 원문에서 자른 구간과 source-derived `body`를 정확히 비교하는 왕복 테스트가 불가능해진다. 비교를 느슨하게 만들면 실제 좌표 드리프트도 놓치게 된다.
- **`_source_span`이 추측 대신 거부를 택했을 때 무엇을 지키는가?**
  - **답:** 좌표가 없거나 뒤집혔거나 겹치거나 소스 그룹을 넘거나 원문 범위를 벗어난 청크를 막는다. 실패를 즉시 드러내어 그럴듯한 검색 텍스트가 엉뚱한 증거 좌표와 연결되는 일을 방지한다.
- **긴 문단 하나가 목표 크기를 넘겨도 되는 이유는 무엇인가?**
  - **답:** M1.1은 Block 경계에만 좌표를 주며, 추출 텍스트 위치를 HTML 태그 사이의 문자 위치로 정확히 환산할 수 없다. 목표 크기는 묶기 위한 선호값이므로, 나눌 수 없는 긴 문단은 인용 검증 가능성을 위해 통째로 둔다.
- **ordinal을 정렬 전이 아니라 정렬 후에 매기는 이유는 무엇인가?**
  - **답:** xref Section은 원문 순서가 아니라 SEC Item 순서로 들어온다. 모든 청크를 소스 구간으로 먼저 정렬한 뒤 조밀한 ordinal을 매겨야 번호가 문서 순서를 뜻하고 이전·다음 탐색도 결정적이다.

---

## 이 모듈이 다음 모듈에 넘기는 것

M1.3이 M1 단계의 마지막 계산 모듈이다. 여기서 나온 `Chunk` 객체가 앞으로 어떻게 쓰이는지 정리하고 넘어가자.

| M1.3이 만든 것 | 받는 곳 | 거기서 하는 일 |
|---|---|---|
| `Chunk.content` (context+body) | **M1.4 → M2** | 임베딩 대상 텍스트, 전문 검색 인덱스 |
| `Chunk.body` | **M4** | LLM에 주는 근거 원문 |
| `Chunk.start_char` / `end_char` | **M1.4** | `chunks` 테이블의 좌표 열 |
| `Chunk.source_sha256` | **M1.4** | 문서 행과의 신원 일치 검증 |
| `Chunk.citation` | **M4** | 최종 보고서에 인쇄되는 인용 레이블 |
| `Chunk.ordinal` | **M1.4** | upsert 충돌 키 `(doc_id, ordinal)` |
| 청크 9,172개라는 수 | **M3** | 청크 크기 ablation의 기준선 |

바로 다음 장 M1.4는 이 청크들을 PostgreSQL에 넣는다. 그런데 단순히 INSERT하는 게 아니다. **같은 코퍼스를 두 번 넣어도 데이터베이스가 같아야 하고**, 파서를 고쳐서 다시 넣을 때 **변하지 않은 청크의 임베딩은 살아남아야 한다.** 여기서 만든 `ordinal`과 `source_sha256`이 그걸 가능하게 하는 열쇠다.

---

## 검사 CLI 추가 및 최종 검증

`chunk_filing()`이 준비됐으므로 핵심 모듈이 완성됐다. `app/ingestion/chunk.py` 끝에 이 CLI를 추가한다. 같은 공개 함수를 호출해 사람이 읽을 수 있는 결과를 출력한다.

#### `app/ingestion/chunk.py` 확장 — 검사 CLI

```python
if __name__ == "__main__":  # pragma: no cover - manual inspection helper
    import argparse
    import json
    from pathlib import Path

    from app.ingestion.parser import parse_filing

    parser = argparse.ArgumentParser(description="Inspect structure-aware 10-K chunks.")
    parser.add_argument("--doc", default="NVDA-FY2024", help="doc_id, e.g. NVDA-FY2024")
    parser.add_argument("--kind", choices=("text", "table"))
    parser.add_argument("--limit", type=int, default=3)
    args = parser.parse_args()

    manifest = json.loads(Path("data/corpus/manifest.json").read_text())
    entry = next(
        item for item in manifest if f"{item['ticker']}-FY{item['report_date'][:4]}" == args.doc
    )
    parsed, _ = parse_filing(entry)
    selected = [chunk for chunk in chunk_filing(parsed) if not args.kind or chunk.kind == args.kind]
    for chunk in selected[: args.limit]:
        print(f"\n{'─' * 80}\n#{chunk.ordinal} {chunk.kind} [{chunk.start_char}, {chunk.end_char})")
        print(chunk.content)
```

전체 검증을 실행한다:

```bash
uv run pytest tests/chunk -q
uv run python scripts/check_doc_code.py docs/en/m1-3-chunk/03-build.md docs/ko/m1-3-chunk/03-build.md
uv run ruff check --no-fix app/ingestion/chunk.py tests/chunk
uv run python -m app.ingestion.chunk --doc INTC-FY2022 --kind table --limit 2
```

네 명령이 모두 missing-symbol skip 없이 통과하면 CLI가 소스 순서의 인용 레이블이 붙은 표 청크 두 개를 표시한다. 실패는 명령 순서대로 해결한다. 코퍼스가 없으면 먼저 그 선행 조건을 복원한다; 더 느슨한 폴백이나 소스에서 다시 측정하지 않은 변경된 골든 수로 출처 실패를 숨기지 않는다.

<!-- complete-files:start -->
## 완성 기준본 — 정식 구현 전체

아래 정식 경로를 직접 생성하거나 교체한다. `_mine.py` 또는 별도의 학습자용 복사 모듈을 만들지 않는다. 앞의 발췌 코드는 개별 결정을 설명하고, 이 절의 코드 블록은 체크포인트를 마친 뒤 대조할 완성 파일이다. 표시된 타입 어노테이션과 영어 주석을 유지하며 `pyproject.toml`을 Ruff 정책의 기준으로 사용한다.

### M1.3 — 완성 체크포인트

#### 생성 또는 교체 `app/ingestion/chunk.py`

<!-- file: app/ingestion/chunk.py -->
```python
"""Structure-aware chunking with source-stable citations.

The chunk id is deliberately not the citation. Re-chunking changes ids and would
invalidate a golden set, making chunk-size ablation impossible. Every chunk instead
carries a `[start_char, end_char)` span into the immutable source filing.

The pipeline keeps source text and synthetic context separate:

    body             text derived from the cited source span
    context_header   filing / Item / narrative heading metadata
    content          context_header + body (the text indexed for retrieval)

This separation makes citation round-trip tests possible even though contextual
headers are intentionally repeated across chunks.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import re
from typing import Literal

from app.ingestion.parser import Block, ParsedFiling, Section
from app.ingestion.tables import table_to_markdown

ChunkKind = Literal["text", "table"]

# Defaults are starting arms, not conclusions. M3 evaluates alternatives and records
# the winning configuration; callers can change the value without changing logic.
DEFAULT_TARGET_TEXT_CHARS = 1_200
SOURCE_SHA256_RE = re.compile(r"[0-9a-f]{64}", re.ASCII)


@dataclass(frozen=True, slots=True)
class ChunkConfig:
    """Tunable chunking parameters used by the M3 ablation."""

    target_text_chars: int = DEFAULT_TARGET_TEXT_CHARS

    def __post_init__(self) -> None:
        if self.target_text_chars <= 0:
            raise ValueError("target_text_chars must be positive")


@dataclass(frozen=True, slots=True)
class Chunk:
    """A retrieval unit whose citation survives re-chunking."""

    doc_id: str
    item: str | None
    kind: ChunkKind
    ordinal: int
    body: str
    context_header: str
    citation: str
    start_char: int
    end_char: int
    source_sha256: str = ""

    @property
    def content(self) -> str:
        """Text sent to indexing: repeated context followed by source-derived body."""
        return f"{self.context_header}\n\n{self.body}" if self.context_header else self.body


def _source_span(blocks: list[Block], source_length: int | None = None) -> tuple[int, int]:
    """Validate and aggregate one ordered, contiguous narrative block group."""
    if not blocks or any(block.source_pos is None or block.end_pos is None for block in blocks):
        raise ValueError("cannot create a chunk without complete source spans")

    groups = {block.source_group for block in blocks}
    if len(groups) != 1:
        raise ValueError("cannot create a chunk across source groups")

    previous_end: int | None = None
    for block in blocks:
        start, end = block.source_pos, block.end_pos
        assert start is not None and end is not None
        if not 0 <= start < end:
            raise ValueError(f"invalid block source span: [{start}, {end})")
        if previous_end is not None and start < previous_end:
            raise ValueError("chunk blocks are out of source order or overlap")
        if source_length is not None and end > source_length:
            raise ValueError(
                f"block source span ends beyond source length: {end} > {source_length}"
            )
        previous_end = end

    start = blocks[0].source_pos
    end = blocks[-1].end_pos
    assert start is not None and end is not None
    return start, end


def _citation(filing: ParsedFiling, section: Section) -> str:
    item = f"Item {section.item}" if section.item else "Unnumbered section"
    return f"{filing.ticker} FY{filing.fiscal_year} · {item}"


def _context_header(
    filing: ParsedFiling, section: Section, narrative_heading: str | None = None
) -> str:
    """Build context that remains useful when a chunk is retrieved in isolation."""
    parts = [_citation(filing, section)]
    title = section.canonical_title or section.reported_title
    if title:
        parts.append(title)
    if narrative_heading and narrative_heading != title:
        parts.append(narrative_heading)
    return " · ".join(parts)


# ── L2. Text chunks ──────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class _Unit:
    kind: ChunkKind
    body: str
    blocks: list[Block]
    narrative_heading: str | None


def section_units(section: Section, config: ChunkConfig) -> list[_Unit]:
    """Build source-ordered units without crossing a table or narrative heading.

    Paragraphs are never split internally: source block boundaries are the stable
    units. A single long paragraph may therefore exceed the target. The target is a
    grouping preference, not a destructive hard limit.
    """
    units: list[_Unit] = []
    pending: list[Block] = []
    pending_chars = 0
    narrative_heading: str | None = None
    active_group: int | None = None

    def flush() -> None:
        nonlocal pending, pending_chars
        if pending:
            units.append(
                _Unit(
                    kind="text",
                    body="\n\n".join(block.text for block in pending),
                    blocks=pending,
                    narrative_heading=narrative_heading,
                )
            )
        pending = []
        pending_chars = 0

    for block in section.blocks:
        if active_group != block.source_group:
            flush()
            active_group = block.source_group
            narrative_heading = block.source_heading
        if block.kind == "heading":
            flush()
            narrative_heading = block.text
            continue
        if block.kind == "table":
            flush()
            markdown = table_to_markdown(block.html)
            if markdown:
                units.append(_Unit("table", markdown, [block], narrative_heading))
            continue
        if not block.text.strip():
            continue

        separator = 2 if pending else 0
        if pending and pending_chars + separator + len(block.text) > config.target_text_chars:
            flush()
        pending.append(block)
        pending_chars += (2 if len(pending) > 1 else 0) + len(block.text)
    flush()
    return units


# ── L3/L4/L5. Tables, context, and source spans ──────────────────────────────


def chunk_filing(filing: ParsedFiling, config: ChunkConfig | None = None) -> list[Chunk]:
    """Convert a parsed filing into ordered text/table chunks with source spans."""
    if filing.source_length <= 0:
        raise ValueError(f"{filing.doc_id} has no canonical source length")
    if SOURCE_SHA256_RE.fullmatch(filing.source_sha256) is None:
        raise ValueError(f"{filing.doc_id} has no canonical source SHA-256")
    cfg = config or ChunkConfig()
    chunks: list[Chunk] = []

    def append(
        section: Section,
        kind: ChunkKind,
        body: str,
        blocks: list[Block],
        narrative_heading: str | None = None,
    ) -> None:
        start, end = _source_span(blocks, filing.source_length)
        chunks.append(
            Chunk(
                doc_id=filing.doc_id,
                item=section.item,
                kind=kind,
                ordinal=len(chunks),
                body=body,
                context_header=_context_header(filing, section, narrative_heading),
                citation=_citation(filing, section),
                start_char=start,
                end_char=end,
                source_sha256=filing.source_sha256,
            )
        )

    for section in filing.sections:
        for unit in section_units(section, cfg):
            append(
                section,
                unit.kind,
                unit.body,
                unit.blocks,
                unit.narrative_heading,
            )

    # Heading-based sections already arrive in source order. Xref sections arrive
    # in SEC Item order instead, and one Item can own multiple narrative ranges.
    # A stable span sort restores document order before ordinals are materialized.
    chunks.sort(key=lambda chunk: (chunk.start_char, chunk.end_char))
    return [replace(chunk, ordinal=ordinal) for ordinal, chunk in enumerate(chunks)]


if __name__ == "__main__":  # pragma: no cover - manual inspection helper
    import argparse
    import json
    from pathlib import Path

    from app.ingestion.parser import parse_filing

    parser = argparse.ArgumentParser(description="Inspect structure-aware 10-K chunks.")
    parser.add_argument("--doc", default="NVDA-FY2024", help="doc_id, e.g. NVDA-FY2024")
    parser.add_argument("--kind", choices=("text", "table"))
    parser.add_argument("--limit", type=int, default=3)
    args = parser.parse_args()

    manifest = json.loads(Path("data/corpus/manifest.json").read_text())
    entry = next(
        item for item in manifest if f"{item['ticker']}-FY{item['report_date'][:4]}" == args.doc
    )
    parsed, _ = parse_filing(entry)
    selected = [chunk for chunk in chunk_filing(parsed) if not args.kind or chunk.kind == args.kind]
    for chunk in selected[: args.limit]:
        print(f"\n{'─' * 80}\n#{chunk.ordinal} {chunk.kind} [{chunk.start_char}, {chunk.end_char})")
        print(chunk.content)
```

체크포인트를 실행한다.

```bash
uv run pytest tests/chunk -q
```

**예상 결과:** 선택한 모든 오프라인 테스트가 통과한다. 명시된 통합 테스트는 외부 서비스를 사용할 수 없을 때만 건너뛸 수 있다.

**중단 조건:** 테스트가 실패하거나 필수 정식 심볼이 없어서 건너뛰면 진행하지 않는다.

**디버깅:** 같은 pytest 대상을 `-vv --tb=long`으로 다시 실행하고 첫 번째로 실패한 계약을 고친 뒤 진행한다.

<!-- complete-files:end -->
