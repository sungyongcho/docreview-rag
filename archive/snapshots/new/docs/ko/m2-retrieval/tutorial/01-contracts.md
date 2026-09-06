# M2.1 튜토리얼 1 — 근거와 출처를 함께 보존하는 검색 타입

검색 결과를 문자열만으로 반환하면 출처를 검증할 수 없다.

많은 RAG 예제에서 `retriever.search(q)`는 텍스트 목록을 반환한다. 프롬프트에 바로 넣기는 쉽지만, 각 텍스트의 출처 정보는 남지 않는다.

M1에서 보존한 원문 좌표와 SHA-256이 검색 결과에서 빠지면, M4는 보고서의 인용문을 원문에서 다시 검증할 수 없다.

따라서 검색 결과는 텍스트가 아니라 **근거와 출처 메타데이터를 함께 담은 구조화된 값**이어야 한다. 사람에게 보여줄 인용 정보와 기계가 검증할 좌표를 모두 포함하고, M1.3에서 분리한 다음 세 필드도 유지해야 한다.

- `body` — 원문에서 온 근거
- `context_header` — 우리가 만든 검색 맥락
- `index_text` — 둘을 합친 것, 검색 인덱스에 들어간 텍스트

이 튜토리얼에서는 세 필드의 관계가 어긋난 검색 결과를 타입 생성 단계에서 거부한다.

**선행 조건:** M1.4가 통과해 데이터베이스에 청크가 적재된 상태여야 한다. `uv run pytest tests/db -q`가 통과하는 지점에서 시작한다.

## 무엇을 작성하고 어디를 직접 구현할까

M2.1은 파일 하나를 만든다. `app/retrieval/types.py`를 네 단계로 이어 붙이면 그대로 체크포인트 파일이 된다.

| 구간 | 학습 행동 | 여기서 얻어야 하는 것 |
|---|---|---|
| 모듈 뼈대와 타입 별칭 | **구조 작성** | 제약을 필드마다 반복하지 않고 별칭에 모으는 이유 |
| `ChunkHit` 필드 선언 | **모델 선언 작성 후 설계 검토** | 근거와 검색 텍스트를 한 타입에 함께 두는 이유 |
| `model_validator` — `ChunkHit`의 핵심 검증 | 검증 로직을 **직접 구현** | 타입 생성 시점에 막히는 잘못된 상태 |
| `RetrievalFilters`의 정규화 검증기 | **필드 매핑 작성 후 경계 변환 검토** | 같은 요청이 같은 직렬화를 갖는 조건 |
| `sort_hits`의 정렬 키 | 결정론 규칙을 **직접 구현** | 동점을 무엇으로 끊는가 |

이 단계의 목표는 Pydantic이 자동으로 검사하는 조건과 애플리케이션이 직접 정의해야 하는 조건을 구분하는 것이다.

## 1. 공통 제약을 타입 별칭으로 정의한다

`ChunkHit`을 정의하기 전에 공통 타입 별칭을 만든다. `doc_id`처럼 여러 모델에서 반복되는 제약을 별칭 한 곳에 정의하면 모든 사용처가 같은 규칙을 공유한다.

별칭이 없으면 같은 `Field(min_length=1, max_length=32)`가 `ChunkHit`, `RetrievalFilters`, M3·M4 모델에 각각 반복된다. 이후 데이터베이스 열의 최대 길이를 64자로 변경하면서 일부 정의만 수정하면, 수정하지 않은 모델은 데이터베이스가 허용하는 식별자를 계속 거부한다. 이 불일치는 특정 식별자를 사용하는 요청에서만 나타나므로 원인을 찾기도 어렵다.

**타입 별칭의 목적은 코드를 짧게 만드는 것이 아니라, 같은 제약의 수정 지점을 한 곳으로 제한하는 것이다.**

### `app/retrieval/types.py` 생성 — 모듈 헤더

**학습 행동 — 구조 작성:** import 목록을 암기할 필요는 없다. Pydantic에서 무엇을 가져오는지만 확인한다.

```python
"""Shared value objects and deterministic ordering for retrieval results."""

from collections.abc import Iterable
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, StrictStr
from pydantic.functional_validators import field_validator, model_validator
```

### `app/retrieval/types.py` 확장 — 제약 별칭

**학습 행동 — 공통 제약 정의:** 각 별칭이 어떤 데이터베이스 열의 제약을 옮겨 온 것인지 확인하며 작성한다.

<!-- src: app/retrieval/types.py::ChunkKind,Score -->
```python
ChunkKind = Literal["text", "table"]

ChunkId = Annotated[StrictInt, Field(gt=0)]
DocId = Annotated[StrictStr, Field(min_length=1, max_length=32)]
Ticker = Annotated[StrictStr, Field(min_length=1, max_length=16)]
FiscalYear = Annotated[StrictInt, Field(gt=0)]
Form = Annotated[StrictStr, Field(min_length=1, max_length=16)]
Item = Annotated[StrictStr, Field(min_length=1, max_length=8)]
SourceSha256 = Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]
Score = Annotated[StrictFloat, Field(allow_inf_nan=False)]
```

**코드에서 꼭 볼 것**

- **`Strict*` 타입은 `"3"` 같은 문자열을 정수 `3`으로 자동 변환하지 않는다. `StrictInt`는 이러한 입력을 거부한다.** 데이터베이스 행의 타입이 예상과 다를 때 즉시 실패하므로 잘못된 좌표가 조용히 통과하지 않는다.
- `max_length`는 M1.4 ORM의 `String(32)`, `String(16)`과 같은 숫자다. 같은 제약을 두 계층에 적어 두는 것이 중복이 아니라 **경계마다 fail-closed**로 만드는 방법이다.
- `SourceSha256`의 정규식이 소문자만 허용한다. M1이 저장한 형식과 정확히 같아야 좌표가 같은 스냅샷을 가리킨다.
- `allow_inf_nan=False` — `Score`에 NaN이 섞이면 정렬 결과가 비결정적이 된다.

**ORM 제약은 데이터베이스에 저장되는 값을 보호하고, 검색 타입의 제약은 데이터베이스 밖에서 생성되거나 전달되는 값까지 보호한다.** 같은 규칙을 두 경계에서 검사해야 어느 경로로 들어온 값이든 잘못된 상태를 거부할 수 있다.

## 2. `ChunkHit` — 근거와 검색 텍스트를 한 타입에 묶는다

이 타입은 검색 결과 하나가 반드시 제공해야 할 정보를 정의한다. 필드 모양은 데이터베이스 행과 비슷하지만 단순한 행 복사본은 아니다.

데이터베이스 모델은 각 열의 값이 저장 가능한지를 검사한다. 반면 이 타입은 여러 필드가 함께 있을 때 검색 결과로서 일관되는지를 검사한다. 예를 들어 각 문자열이 개별 열 제약을 통과하더라도 검색 텍스트와 근거 본문이 서로 다르면 모델 검증기가 생성을 거부한다.

검색 결과는 세 가지 질문에 답할 수 있어야 한다. `citation`은 사람이 읽을 출처를 제공한다. `start_char`, `end_char`, `source_sha256`은 기계가 정확한 원문 구간을 다시 찾게 한다. `index_text`는 검색이 실제로 매칭한 텍스트를 보존한다.

### `app/retrieval/types.py` 확장 — `ChunkHit`

**학습 행동 — 모델 선언 작성 + 검증 로직 구현:** 필드 선언은 위 별칭을 보고 작성한다. 그다음 `model_validator`는 보지 말고 직접 구현한 뒤 대조한다.

<!-- src: app/retrieval/types.py::ChunkHit -->
```python
class ChunkHit(BaseModel):
    """One scored database chunk with human and machine citation data."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    chunk_id: ChunkId
    doc_id: DocId
    item: Item | None
    kind: ChunkKind
    citation: Annotated[StrictStr, Field(min_length=1)]
    start_char: Annotated[StrictInt, Field(ge=0)]
    end_char: Annotated[StrictInt, Field(gt=0)]
    source_sha256: SourceSha256
    body: Annotated[StrictStr, Field(min_length=1)]
    context_header: StrictStr
    index_text: Annotated[StrictStr, Field(min_length=1)]
    score: Score

    @model_validator(mode="after")
    def validate_source_and_index_text(self) -> Self:
        """Reject invalid spans and indexed text detached from its evidence."""
        if self.end_char <= self.start_char:
            raise ValueError("end_char must be greater than start_char")

        expected = f"{self.context_header}\n\n{self.body}" if self.context_header else self.body
        if self.index_text != expected:
            raise ValueError("index_text must equal context_header plus body")
        return self
```

| `ChunkHit` 필드 | 값 또는 제약 | 역할 |
|---|---|---|
| `chunk_id` | 양의 데이터베이스 식별자 | 고유한 순위·인용 식별자를 제공한다. |
| `doc_id` | 비어 있지 않은 filing 식별자 | 검색 결과를 하나의 filing에 연결한다. |
| `item` | SEC Item 또는 `None` | 존재하는 경우 섹션 식별자를 보존한다. |
| `kind` | `"text"` 또는 `"table"` | 근거 표현 방식을 나타낸다. |
| `citation` | 비어 있지 않은 텍스트 | 사람이 읽는 출처 레이블을 제공한다. |
| `start_char`, `end_char` | 유효한 반열린 범위 | filing 스냅샷 안에서 근거를 찾게 한다. |
| `source_sha256` | 소문자 16진수 64자 | 좌표를 정확한 원문 버전에 묶는다. |
| `body` | 비어 있지 않은 원문 파생 텍스트 | 사용자에게 보여주는 근거를 전달한다. |
| `context_header` | 비어 있을 수 있는 합성 문맥 | filing·헤딩 문맥을 근거와 분리해 전달한다. |
| `index_text` | 정확히 `context_header + body` | 검색이 실제로 매칭한 텍스트를 보존한다. |
| `score` | 엄격한 유한 float | 한 검색 컴포넌트 안에서 결과 순서를 정한다. |

**코드에서 꼭 볼 것**

- `extra="forbid"`: 정의하지 않은 키를 무시하지 않고 거부한다. 따라서 열 이름의 오타나 예상하지 않은 스키마 변경을 즉시 발견할 수 있다.
- `frozen=True`: 검색 결과를 만든 뒤 점수나 좌표를 바꾸지 못하게 한다.
- `context_header`만 `min_length` 제약이 없다. 문맥이 없는 청크가 정상이기 때문이다. `body`와 `index_text`는 비어 있으면 안 된다.

## `model_validator`가 지키는 것

모델 검증기는 두 가지 불변조건을 검사한다.

**첫째, 반열린 구간이 유효해야 한다.** `end_char > start_char` 조건을 만족하지 않는 검색 결과는 생성하지 않는다. M1.3의 fail-closed 원칙을 검색 결과 경계에서도 유지한다.

**둘째, `index_text`는 정확히 `context_header + body`여야 한다.**

벡터 검색, 어휘 검색, 재순위화는 각각 데이터베이스 행으로 `ChunkHit`을 만들 수 있다. 어느 경로에서든 `body`와 `index_text`를 다르게 전달하면, 검색에 사용한 텍스트와 사용자에게 보여주는 근거가 달라진다.

**타입 생성 시점에 이 관계를 검사하므로, 생성된 `ChunkHit`은 세 필드가 일관된 상태임을 보장한다.**

## 3. `RetrievalFilters` — 요청 조건을 불변으로 고정한다

벡터 검색과 어휘 검색은 같은 요청에 **동일한 필터 조건**을 사용해야 한다. 두 검색 경로의 조건이 다르면 융합 결과는 하나의 요청에 대한 결과가 아니다.

가변 필터 객체를 두 검색 경로가 공유한다고 가정하자. 벡터 검색은 `tickers=("NVDA",)`인 상태에서 실행됐지만, 어휘 검색 전에 호출자가 `"AMD"`를 추가할 수 있다. 그러면 두 검색 결과는 서로 다른 문서 집합을 대상으로 계산된다. RRF는 이 차이를 알지 못한 채 두 순위를 융합한다.

이 과정에서는 예외가 발생하지 않으므로 결과만 보고 필터 불일치를 발견하기 어렵다.

**필터를 불변 객체로 만들면 하나의 요청이 끝날 때까지 모든 검색 경로가 같은 조건을 사용한다.**

### `app/retrieval/types.py` 확장 — `RetrievalFilters`

**학습 행동 — 필드 매핑 작성 + 경계 변환 검토:** 여섯 필드 선언을 먼저 작성한다. 네 개의 정규화 검증기는 각각 무엇을 같은 것으로 만드는지 확인하며 구현한다.

<!-- src: app/retrieval/types.py::RetrievalFilters -->
```python
class RetrievalFilters(BaseModel):
    """Optional exact-match restrictions shared by every retrieval strategy.

    Values within a field are alternatives, while populated fields are combined.
    Empty tuples mean that the corresponding database dimension is unrestricted.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    doc_ids: tuple[DocId, ...] = ()
    tickers: tuple[Ticker, ...] = ()
    fiscal_years: tuple[FiscalYear, ...] = ()
    forms: tuple[Form, ...] = ()
    items: tuple[Item | None, ...] = ()
    kinds: tuple[ChunkKind, ...] = ()

    @field_validator("doc_ids", "tickers", "forms", mode="after")
    @classmethod
    def canonicalize_strings(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        """Remove duplicates and make equivalent string filters serialize equally."""
        return tuple(sorted(set(values)))

    @field_validator("fiscal_years", mode="after")
    @classmethod
    def canonicalize_years(cls, values: tuple[int, ...]) -> tuple[int, ...]:
        """Remove duplicate years and store them in ascending order."""
        return tuple(sorted(set(values)))

    @field_validator("items", mode="after")
    @classmethod
    def canonicalize_items(cls, values: tuple[str | None, ...]) -> tuple[str | None, ...]:
        """Canonicalize Item filters while retaining support for unnumbered sections."""
        return tuple(sorted(set(values), key=lambda item: (item is not None, item or "")))

    @field_validator("kinds", mode="after")
    @classmethod
    def canonicalize_kinds(cls, values: tuple[ChunkKind, ...]) -> tuple[ChunkKind, ...]:
        """Canonicalize kinds in the schema's text-then-table order."""
        order = {"text": 0, "table": 1}
        return tuple(sorted(set(values), key=order.__getitem__))
```

| `RetrievalFilters` 필드 | 제한하는 대상 |
|---|---|
| `doc_ids` | 정확한 filing 식별자 |
| `tickers` | 회사 티커 |
| `fiscal_years` | 회계연도 |
| `forms` | SEC 서식 유형 |
| `items` | 번호가 붙은 Item 또는 `None`인 무번호 섹션 |
| `kinds` | `"text"` 또는 `"table"` 청크 |

**코드에서 꼭 볼 것**

- 네 검증기가 전부 `mode="after"`다. 타입 검사를 통과한 값에만 정규화를 적용한다.
- `canonicalize_items`의 정렬 키가 `(item is not None, item or "")`다. `None`과 문자열을 직접 비교하면 `TypeError`가 발생하므로, 먼저 값의 존재 여부를 비교하여 `None`이 앞에 오도록 정렬한다.
- `canonicalize_kinds`만 알파벳순이 아니라 스키마 순서(`"text"` 다음 `"table"`)를 쓴다. 정규화의 목적은 사전순이 아니라 **같은 요청이 같은 표현을 갖게 하는 것**이다.

## `RetrievalFilters`가 튜플과 정규화를 쓰는 이유

**필터는 `list` 대신 `tuple`을 사용하고 `frozen=True`로 설정하여 요청 실행 중 변경을 막는다.** 따라서 벡터 검색과 어휘 검색이 서로 다른 조건을 사용하는 상태를 만들 수 없다.

**정규화는 중복을 제거하고 정렬하여 의미가 같은 요청을 하나의 표현으로 만든다.** `tickers=("NVDA", "AMD")`와 `("AMD", "NVDA", "AMD")`는 같은 조건이므로 동일하게 직렬화되어야 한다. 그렇지 않으면 캐시와 평가 로그에서 같은 요청이 서로 다른 요청으로 기록된다.

값이 있는 필터 필드들은 AND로 결합한다. 한 필드 안의 여러 값은 서로 대안이며, 빈 튜플은 해당 필드로 결과를 제한하지 않는다는 뜻이다.

## 4. `sort_hits` — 동점을 결정론으로 끊는다

점수가 같은 검색 결과의 순서가 실행마다 달라지면 코드가 바뀌지 않아도 M3 평가값이 달라질 수 있다. 이를 막기 위해 점수 뒤에 **최종적으로 유일해지는 동점 해소 키**를 추가한다.

동점은 충분히 발생할 수 있다. 같은 filing의 인접 청크는 유사도 점수가 같을 수 있고, M2.5에서 상호 순위 합 점수로 변환하면 서로 다른 검색 결과가 정확히 같은 점수를 받기도 한다.

동점 순서를 입력 순서에 맡기면 recall@5가 0.82에서 0.79로 바뀌었을 때 원인이 코드 변경인지 결과 순서의 우연한 변화인지 구분하기 어렵다. 평가값이 검색 시스템의 변화가 아니라 정렬의 비결정성을 측정하게 되는 것이다.

**결정론적 정렬은 같은 입력에 같은 순위를 보장하여 평가값의 차이가 실제 시스템 변경을 반영하게 한다.**

### `app/retrieval/types.py` 완성 — `sort_hits`

**학습 행동 — 결정론 규칙 구현:** 정렬 키 튜플을 직접 만들어 본 뒤 대조한다. 마지막 요소가 왜 `chunk_id`인지 설명할 수 있어야 한다.

<!-- src: app/retrieval/types.py::sort_hits -->
```python
def sort_hits(hits: Iterable[ChunkHit]) -> list[ChunkHit]:
    """Return hits in deterministic relevance order without mutating the input.

    Higher scores sort first. Equal scores use the stable source citation identity,
    followed by the database chunk id as a final unique tie-breaker.
    """
    return sorted(
        hits,
        key=lambda hit: (
            -hit.score,
            hit.doc_id,
            hit.source_sha256,
            hit.start_char,
            hit.end_char,
            hit.chunk_id,
        ),
    )
```

**코드에서 꼭 볼 것**

- `-hit.score`가 첫 요소다. `reverse=True`를 사용하면 점수뿐 아니라 **모든 동점 해소 키도 내림차순**이 되어 의도한 출처 순서가 바뀐다.
- **`chunk_id`는 고유한 기본 키이므로 마지막 동점 해소 키로 사용한다.** 이 요소가 없으면 앞선 키가 모두 같은 결과의 순서가 입력 순서에 의존한다.
- `sorted()`는 새 리스트를 만든다. 호출자가 넘긴 시퀀스를 건드리지 않는다.

여기까지 작성하면 `app/retrieval/types.py`가 완성된다. 네 단계의 코드를 순서대로 이어 붙이면 체크포인트 파일과 같아진다.

## 검색 결과 타입을 엄격하게 검증하는 이유

이 타입의 식별 정보는 **이후 모든 순위·인용·평가 결정의 기반**이 된다.

좌표 또는 `index_text`가 `body`와 일치하지 않으면 답변의 근거를 원문 스냅샷까지 추적할 수 없다. M3의 평가는 검색 결과를 신뢰할 수 없고, M4의 인용은 원문으로 검증할 수 없게 된다.

정리하면 이런 흐름이다.

```
DB row     ──▶  strict ChunkHit       ──▶  deterministic sort_hits
request fields ──▶ immutable RetrievalFilters ──▶ identical constraints in vector/lexical SQL
```

## 5. M2.1 시점의 공개 API

다음 모듈이 아직 없으므로 패키지는 지금 만든 것만 내보낸다.

이 공개 API는 현재 시점에 존재하는 심볼만 포함하는 임시 파일이다. M2.7의 완성본을 미리 사용하면 패키지가 아직 존재하지 않는 `app.retrieval.vector`를 가져오고, 현재 계약과 무관한 `ImportError` 때문에 테스트 수집이 실패한다.

**각 체크포인트의 공개 API는 그 시점에 구현된 모듈만 참조해야 한다.** 그래야 중간 단계도 독립적으로 실행하고 검증할 수 있다.

### `app/retrieval/__init__.py` 생성 — M2.1 임시 공개 API

**학습 행동 — 구조 작성:** M2.7에서 이 파일을 교체한다. 지금은 현재 단계에서 사용할 임시 공개 API만 정의한다.

```python
"""Public retrieval contracts available after M2.1."""

from app.retrieval.types import ChunkHit, ChunkKind, RetrievalFilters, sort_hits

__all__ = ["ChunkHit", "ChunkKind", "RetrievalFilters", "sort_hits"]
```

## 집중 테스트와 테스트가 지키는 계약

```bash
uv run pytest tests/retrieval/test_01_contract.py -q
```

테스트 이름부터 읽는다. 각 실패 사례가 방금 작성한 경계 하나를 가리킨다.

| 테스트가 깨뜨리는 값 | 지키는 계약 |
|---|---|
| ORM 열과 어긋난 필드 집합 | 검색 타입이 실제 데이터베이스 표면을 따라간다. |
| 알 수 없는 추가 키 | 오타나 이름이 바뀐 열이 검증 없이 통과하지 못한다. |
| 문자열로 들어온 정수, NaN 점수 | 강제 변환과 비결정적 정렬을 막는다. |
| `body`가 `index_text`와 어긋남 | 검색된 텍스트와 보여주는 근거가 같다. |
| 순서만 다른 중복 필터 | 같은 요청이 같은 직렬화와 캐시 키를 갖는다. |
| 동점 hit의 입력 순서 | 순위가 실행마다 달라지지 않는다. |
| 누락된 공개 심볼 | 다음 단계가 의존할 공개 API가 실제로 존재한다. |

구현이 완료되면 필수 심볼 누락으로 건너뛰는 항목 없이 모든 계약 테스트가 통과해야 한다.

테스트가 실패하거나 필수 심볼 누락으로 건너뛰면 M2.1 완료로 판단하지 않는다.

가져오기 오류가 발생하면 의존 모듈보다 `__init__.py`를 먼저 작성했는지 확인한다. 검증 오류가 발생하면 값의 강제 변환, 반열린 범위, `index_text`와 `context_header`·`body`의 결합 규칙을 차례로 확인한다.

## 여기까지 왔을 때 설명할 수 있어야 하는 것

다음 질문의 답은 앞에서 **굵게 표시한 핵심 문장**에 있다. 각 답을 해당 모델 또는 검증기와 연결해 설명해 본다.

- **Pydantic 기본 타입 대신 `Strict*`를 쓰는 이유는 무엇인가?**
  - **답:** Pydantic 기본 타입은 `"3"`을 `3`으로 바꾸는 식의 암묵적 강제 변환을 할 수 있다. `Strict*`는 이런 경계 데이터의 변질을 즉시 거부한다.
- **ORM `CheckConstraint`가 이미 있는데 왜 검색 타입에서 다시 검사하는가?**
  - **답:** ORM 제약은 저장된 행을 보호하지만 검색 값은 데이터베이스 쓰기 전이나 밖에서도 생성된다. 검색 타입에서도 검사해야 모든 경계가 잘못된 값을 즉시 차단한다.
- **`frozen=True`가 없으면 융합 결과의 어떤 설명이 불가능해지는가?**
  - **답:** 요청 도중 필터가 바뀌면 벡터 경로와 어휘 경로가 서로 다른 모집단을 검색할 수 있어, 하나의 조건이 어떤 융합 순위를 만들었는지 설명할 수 없다.
- **정규화가 없을 때 평가 로그에서 정확히 무엇이 깨지는가?**
  - **답:** 논리적으로 같은 요청이 순서나 표현이 다른 값으로 기록되어, 동일한 실행이 서로 다른 구성처럼 보이고 결과를 안정적으로 비교할 수 없게 된다.
- **마지막 `chunk_id`를 `sort_hits`의 정렬 키에서 빼면 어떤 증상이 나타나는가?**
  - **답:** 나머지 값이 모두 같은 히트는 입력 순서를 따르므로, 동일한 실행 사이에도 순위와 평가 결과가 달라질 수 있다.

---

[모듈 개요](../03-build.md) · [다음: 임베딩 →](02-embeddings.md)
