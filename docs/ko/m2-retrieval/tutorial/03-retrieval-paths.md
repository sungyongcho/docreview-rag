# M2.3–M2.4 튜토리얼 3 — 두 개의 검색 경로

**선행 조건:** 튜토리얼 2의 `uv run pytest tests/retrieval/test_02_embeddings.py -q`가 통과해야 한다.

## M2.3 — 일부러 느린 정확 검색부터 만든다

이 단계에서 벡터 검색을 구현한다. 대부분의 pgvector 예제는 속도를 위해 HNSW 인덱스부터 만든다.

여기서는 **인덱스를 만들지 않고 전체 행을 훑는 정확 검색(exact search)부터 구현한다.** 그 이유를 먼저 정리한다.

### 근사 인덱스를 나중으로 미루는 이유

벡터 검색은 질문 벡터와 저장된 청크 벡터 사이의 거리를 계산해 가까운 청크를 고르는 작업이다. **벡터 인덱스는 임베딩을 만드는 모델이 아니라, 이미 저장된 벡터 중 가까운 후보를 빨리 찾기 위한 보조 탐색 구조다.**

인덱스가 없으면 PostgreSQL은 필터를 통과한 모든 벡터와 질문 벡터의 거리를 계산한다. 이것이 정확 검색이다. 여기서 "정확"은 검색 결과의 내용이 항상 정답이라는 뜻이 아니다. **현재 거리 함수가 정한 가장 가까운 벡터를 인덱스 때문에 빠뜨리지 않는다는 뜻이다.**

- HNSW는 가까운 벡터끼리 연결한 여러 층의 그래프를 따라가며 후보 범위를 좁힌다. 보통 IVFFlat보다 같은 속도에서 가까운 벡터를 덜 놓치지만, 인덱스를 만드는 시간이 길고 메모리를 더 사용한다.
- IVFFlat은 비슷한 벡터를 여러 그룹으로 나눈 뒤 질문과 가까운 그룹 일부만 확인한다. HNSW보다 인덱스를 빨리 만들고 메모리를 덜 사용하지만, 데이터로 그룹을 먼저 학습해야 하고 검색할 그룹 수를 조절해야 한다.

두 방식 모두 전체 벡터 대신 일부 후보만 확인하므로 빠르지만, 실제로 가장 가까운 벡터를 탐색하지 못할 수 있다. 이것이 근사 최근접 탐색(approximate nearest neighbor)의 "근사"가 뜻하는 바다. 임베딩 자체를 대충 만드는 것은 아니다.

문제는 도입 순서다. 근사 인덱스를 먼저 만들면 검색 품질이 낮게 나왔을 때 다음 세 원인을 구분할 수 없다.

- 임베딩 품질이 낮다
- 청킹 경계가 잘못됐다
- 인덱스가 정답 행을 놓쳤다

**정확 검색으로 먼저 측정한 값이 기준선이 되어야 세 원인을 분리할 수 있다.** 정확 검색의 재현율이 0.82이고 인덱스를 켰을 때 0.79라면, 차이 0.03이 근사 인덱스가 지불한 비용이다. 기준선이 없으면 0.79가 좋은 값인지 판단할 근거 자체가 없다.

M3의 평가도 이 기준선 위에서 실행된다. **최적화는 측정 기준선을 확보한 다음에 시작한다.** 9,172행 전체 스캔은 이 규모에서 충분히 빠르므로 기준선을 만드는 비용도 작다.

### 거리와 유사도를 뒤집어 놓는 지점

pgvector의 `<=>` 연산자는 코사인 거리(cosine distance)를 반환한다. 값이 작을수록 가깝고, 0이 완전히 같은 방향이다.

반면 검색 결과의 `score`는 값이 클수록 좋은 결과로 읽힌다. 두 방향이 코드베이스에 함께 남으면 정렬·융합·평가 코드가 값마다 방향을 기억해야 하고, 한 곳에서 방향을 착각하면 순위가 그대로 뒤집힌다.

**방향 변환은 모듈 경계에서 한 번만 수행한다.** SQL은 거리 오름차순(`distance.asc()`)으로 정렬하고, 공개 타입인 `ChunkHit`을 만들 때 `1 - distance`로 유사도로 바꾼다. 이 모듈 밖으로 나가는 값은 전부 클수록 좋은 값이다.

### 무엇을 작성하고 어디를 직접 구현할까

M2.3은 `app/retrieval/vector.py`를 다섯 단계로 작성한다. 구문(statement) 빌더와 실행기를 분리하므로, 데이터베이스 없이 컴파일된 SQL만으로 질의를 검증할 수 있다.

| 구간 | 학습 행동 | 여기서 얻어야 하는 것 |
|---|---|---|
| 모듈 헤더 | **구조 작성** | 이 파일이 의존하는 계약 |
| `validate_query_vector` | 입력 가드를 **직접 구현** | 질문 쪽에도 별도 검증이 필요한 이유 |
| `_filtered_statement` | 필터 매핑을 **직접 구현** | 두 검색 경로가 맞춰야 하는 필터 의미 |
| `vector_search_statement` | 정렬 결정을 **직접 구현** | 결정론이 실제로 고정되는 지점 |
| `vector_search` | **필드 매핑 작성 후 경계 변환 검토** | 거리가 유사도가 되는 지점 |

### 1. 모듈 헤더

#### `app/retrieval/vector.py` 생성 — 모듈 헤더

**학습 행동 — 구조 작성:** `DIM`을 설정이 아니라 ORM 모델에서 가져온다는 점을 확인한다. 질문 벡터의 차원을 결정하는 것은 설정 값이 아니라 실제 열 정의다.

```python
"""Filtered, deterministic pgvector cosine retrieval."""

from collections.abc import Sequence
import math
from numbers import Real
from typing import Any

from sqlalchemy import Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DIM, Chunk, Document
from app.retrieval.types import ChunkHit, RetrievalFilters
```

### 2. 질문 벡터를 지킨다

M2.2는 공급자가 반환한 벡터를 검증했다. 이 단계에서 검증하는 대상은 반대 방향, 즉 질문 인자로 들어오는 벡터다.

직전 줄에서 임베딩 공급자가 만든 벡터를 넘긴다면 이 검증은 중복으로 보인다.

그러나 이 함수에 도달하는 경로는 공급자만이 아니다. 테스트는 벡터를 직접 만들고, 평가 하네스는 다른 모델 실행이 남긴 캐시 파일에서 읽어 오며, M5의 API는 클라이언트가 보낸 벡터를 그대로 받는다. 이 경로들은 `validate_embeddings`를 거치지 않는다. 그래서 열이 384차원인데 1,536차원 벡터가 도착할 수 있고, 상류의 정규화가 0으로 나눈 결과로 특정 성분에 NaN이 실려 올 수도 있다.

차원이 다른 벡터는 pgvector가 오류로 거부하므로 즉시 발견된다. NaN은 그렇지 않다. NaN과의 비교는 모두 거짓이므로 질의는 오류 없이 실행되고, 결과만 질문과 무관한 행이 된다. **공급자 출력 검증은 공급자를 거친 벡터만 보호하므로, 질문 인자로 들어오는 벡터는 이 함수에서 다시 검증한다.**

#### `app/retrieval/vector.py` 확장 — 질문 벡터 검증

**학습 행동 — 입력 가드 구현:** 구조는 `validate_embeddings`와 같다. 차이가 한 군데 있으므로 그 지점을 찾으며 작성한다.

<!-- src: app/retrieval/vector.py::validate_query_vector -->
```python
def validate_query_vector(values: Sequence[float], *, dimensions: int = DIM) -> list[float]:
    """Return a finite vector whose shape matches the database column."""
    if len(values) != dimensions:
        raise ValueError(f"query vector has dimension {len(values)}, expected {dimensions}")
    vector: list[float] = []
    for component in values:
        if isinstance(component, bool) or not isinstance(component, Real):
            raise ValueError("query vector contains a nonnumeric component")
        number = float(component)
        if not math.isfinite(number):
            raise ValueError("query vector contains a non-finite component")
        vector.append(number)
    return vector
```

**코드에서 꼭 볼 것**

- 시그니처의 `Sequence[float]`은 M2.2에서 정한 정적 계약이고, 함수 안의 `isinstance(component, Real)`은 런타임 검증이다. 두 타입을 같은 자리에 쓰지 않는다.
- 기본값 `dimensions=DIM`은 ORM 열의 너비를 그대로 읽는다. 저장된 벡터와 차원이 다른 질문 벡터로는 거리 계산이 성립하지 않는다.
- `bool` 거부와 `math.isfinite` 검사는 M2.2와 같은 규칙이다. 같은 검사를 두 번 두는 이유는 이 입력이 공급자를 거치지 않기 때문이다.
- NaN 성분이 하나라도 있으면 모든 거리 값이 NaN이 되어 순위가 의미를 잃는다. 질의는 오류 없이 끝나므로 이 상태는 결과를 직접 확인해야 발견된다.

### 3. 두 검색 경로가 공유하는 필터 매핑

필터는 두 검색 경로가 같은 문서 집합을 보는지를 결정한다.

M2.5는 벡터 순위와 어휘 순위를 융합해 하나의 답을 만든다. 이 융합이 성립하려면 두 순위가 같은 모집단에서 뽑혀야 한다. 모집단을 정의하는 것이 필터이므로, 두 경로의 필터가 다르게 동작하면 융합 결과는 순위가 조금 나빠지는 정도가 아니라 서로 다른 두 집합을 섞은 값이 된다.

**아래 매핑은 M2.4의 어휘 검색 필터와 의미가 정확히 일치해야 하는 계약의 절반이다.**

#### `app/retrieval/vector.py` 확장 — 공유 필터 술어

**학습 행동 — 필터 매핑 구현:** 여섯 개 분기를 순서대로 작성한다. `items` 분기만 단순한 `IN` 절로 끝나지 않는다.

<!-- src: app/retrieval/vector.py::_filtered_statement -->
```python
def _filtered_statement(statement: Select[Any], filters: RetrievalFilters) -> Select[Any]:
    """Apply exact-match chunk and document filters with AND semantics."""
    if filters.tickers or filters.fiscal_years or filters.forms:
        statement = statement.join(Document, Document.doc_id == Chunk.doc_id)
    if filters.doc_ids:
        statement = statement.where(Chunk.doc_id.in_(filters.doc_ids))
    if filters.items:
        named_items = tuple(item for item in filters.items if item is not None)
        item_predicates = []
        if None in filters.items:
            item_predicates.append(Chunk.item.is_(None))
        if named_items:
            item_predicates.append(Chunk.item.in_(named_items))
        statement = statement.where(or_(*item_predicates))
    if filters.kinds:
        statement = statement.where(Chunk.kind.in_(filters.kinds))
    if filters.tickers:
        statement = statement.where(Document.ticker.in_(filters.tickers))
    if filters.fiscal_years:
        statement = statement.where(Document.fiscal_year.in_(filters.fiscal_years))
    if filters.forms:
        statement = statement.where(Document.form.in_(filters.forms))
    return statement
```

**코드에서 꼭 볼 것**

- 문서 수준 필터가 있을 때만 조인을 추가한다. 항상 조인하면 청크 조건만 사용하는 질의에도 조인 비용이 붙는다.
- `items`는 하나의 `IN` 절로 표현할 수 없다. **이 필터에서 `None`은 번호가 없는 섹션을 뜻하는데, SQL의 `IN`은 NULL과 매칭되지 않기 때문이다.** 그래서 `or_`가 `IS NULL` 술어와 `IN` 목록을 묶는다.
- 값이 있는 필드마다 `where`가 하나씩 덧붙어 AND 의미가 만들어진다. 빈 튜플은 조건을 추가하지 않는다.
- M2.4는 이 함수를 import하지 않고 별도의 `_filter_predicates`를 구현한다. 두 경로가 공유하는 것은 `RetrievalFilters` 계약이지 코드가 아니다. 한쪽에만 필터 차원을 추가하면 두 경로가 서로 다른 문서 집합을 검색하고, 융합 결과를 설명할 수 없게 된다.

### 4. 결정론이 고정되는 구문

앞의 세 단계는 준비였고, 실제 질의를 만드는 함수는 이 단계에 있다.

이 구문이 하는 일은 다섯 가지다. 코사인 거리 계산, null 임베딩 제외, 필터 적용, 정렬, 개수 제한이다. 이 중 잘못 작성하기 쉬운 판단은 세 가지이고, 세 가지 모두 복잡한 줄이 아니라 한 줄짜리 선택이다.

#### `app/retrieval/vector.py` 확장 — 정확 코사인 구문

**학습 행동 — 정렬 결정 구현:** 구문을 작성한 뒤 여섯 개의 정렬 키를 직접 쓰고, 각 키가 무엇을 고정하는지 설명해 본다.

<!-- src: app/retrieval/vector.py::vector_search_statement -->
```python
def vector_search_statement(
    query_vector: Sequence[float],
    *,
    k: int,
    filters: RetrievalFilters | None = None,
) -> Select[Any]:
    """Build the exact cosine query used by runtime and SQL contract tests."""
    if k <= 0:
        raise ValueError("vector search k must be positive")
    vector = validate_query_vector(query_vector)
    restrictions = filters or RetrievalFilters()
    distance = Chunk.embedding.cosine_distance(vector).label("distance")
    statement = select(Chunk, distance).where(Chunk.embedding.is_not(None))
    statement = _filtered_statement(statement, restrictions)
    return statement.order_by(
        distance.asc(),
        Chunk.doc_id.asc(),
        Chunk.source_sha256.asc(),
        Chunk.start_char.asc(),
        Chunk.end_char.asc(),
        Chunk.id.asc(),
    ).limit(k)
```

**코드에서 꼭 볼 것**

- `Chunk.embedding.is_not(None)`은 아직 백필되지 않은 청크를 결과에서 제외한다. M1.4에서 이 열을 nullable로 정의했기 때문에 이 조건을 쓸 수 있다. 기본값이 영벡터였다면 임베딩되지 않은 청크가 모든 질문에 같은 거리로 섞여 들어온다.
- `distance.asc()`는 유사도가 아니라 거리 기준으로 정렬한다. 클수록 좋은 값으로의 변환은 5단계에서 한 번만 일어난다.
- 거리 뒤에 동점 해소 키 다섯 개(`doc_id`, `source_sha256`, `start_char`, `end_char`, `id`)가 따라온다. 거리가 같은 청크들의 순서를 데이터베이스는 보장하지 않는다. **동점 키가 없으면 같은 코드와 같은 데이터에서도 결과 순서가 실행마다 바뀌고, M3의 평가 점수 변화가 회귀인지 잡음인지 구분할 수 없다.**
- 행이 아니라 `Select`를 반환하므로, 계약 테스트가 이 SQL을 컴파일해 데이터베이스 없이 검사할 수 있다.

### 5. 실행과 경계에서의 변환

이 함수의 줄은 두 종류로 나뉜다.

열한 줄은 데이터베이스 행을 `ChunkHit`으로 옮기는 필드 대입이다. 한 필드도 빠뜨리지 않아야 M2.1의 검증기가 좌표와 텍스트의 관계를 검사할 수 있다.

나머지 한 줄은 `score`다. **코사인 거리가 유사도로 바뀌는 지점이 이 한 줄이고, 이 줄을 지난 뒤에는 어떤 모듈도 값의 방향을 기억할 필요가 없다.**

#### `app/retrieval/vector.py` 완성 — 실행과 유사도 변환

**학습 행동 — 필드 매핑 작성 후 경계 변환 검토:** 열두 개의 필드 대입은 기계적으로 작성한다. 마지막 한 줄만 설계 결정이다.

<!-- src: app/retrieval/vector.py::vector_search -->
```python
async def vector_search(
    session: AsyncSession,
    query_vector: Sequence[float],
    *,
    k: int = 5,
    filters: RetrievalFilters | None = None,
) -> list[ChunkHit]:
    """Return complete chunk evidence ordered by cosine similarity."""
    if k < 0:
        raise ValueError("vector search k must not be negative")
    if k == 0:
        return []

    statement = vector_search_statement(query_vector, k=k, filters=filters)
    rows = (await session.execute(statement)).all()
    return [
        ChunkHit(
            chunk_id=chunk.id,
            doc_id=chunk.doc_id,
            item=chunk.item,
            kind=chunk.kind,
            citation=chunk.citation,
            start_char=chunk.start_char,
            end_char=chunk.end_char,
            source_sha256=chunk.source_sha256,
            body=chunk.body,
            context_header=chunk.context_header,
            index_text=chunk.index_text,
            score=1.0 - float(distance),
        )
        for chunk, distance in rows
    ]
```

**코드에서 꼭 볼 것**

- `score=1.0 - float(distance)`가 이 모듈의 유일한 방향 변환이다.
- `k == 0`이면 구문 빌더를 호출하기 전에 빈 결과를 반환한다. 빌더는 0 이하의 `k`를 거부한다. 두 함수의 계약을 일부러 다르게 둔 것으로, 빌더는 실행 가능한 질의만 만들고 실행기는 빈 요청을 정상 입력으로 처리한다.
- 모든 `ChunkHit` 필드를 행에서 채우므로 `index_text`와 `body`가 함께 도착하고, M2.1의 검증기가 둘의 관계를 검사할 수 있다. 전송량을 줄이려고 열을 덜 선택하면 이 검사가 무력해진다.

여기까지 작성하면 `app/retrieval/vector.py`가 완성된다. 다섯 블록을 순서대로 이어 붙인 것이 그대로 체크포인트 파일이다.

정리하면 이런 경로다.

#### 파일 수정 없음 — 벡터 경로 전체 흐름 읽기

```
query vector → dimension/finiteness validation → cosine-distance query → filtering → similarity conversion → sorted ChunkHit
```

### 집중 테스트와 테스트가 지키는 계약

#### 실행 `tests/retrieval/test_03_vector.py`

```bash
uv run pytest tests/retrieval/test_03_vector.py -q
```

| 테스트가 깨뜨리는 값 | 지키는 계약 |
|---|---|
| 너비가 틀린 질문 벡터 | 질문과 열이 같은 차원을 공유한다. |
| 임베딩이 아직 null인 청크 | 임베딩되지 않은 행이 결과로 나오지 않는다. |
| 컴파일된 SQL 속 인덱스 힌트 | 정확 기준선이 정확하게 유지된다. |
| 거리를 반대 방향으로 정렬 | 가장 가까운 근거가 먼저 온다. |
| `1 - distance`가 아닌 공개 점수 | 모듈 밖은 전부 클수록 좋다. |
| 거리가 동점인 청크의 입력 순서 | 코드 변경 없이 평가 점수가 움직이지 않는다. |

구현이 끝나면 컴파일된 PostgreSQL SQL, null 벡터 제외, 필터, 완전한 결과 매핑, 결정론적 동점 처리, HNSW 미사용 가드를 검증하는 모든 벡터 테스트가 통과해야 한다.

정렬 방향이 반대이거나, 공개 점수가 `1 - distance`가 아니거나, 필터 또는 동점 테스트가 실패하면 M2.3을 완료로 판단하지 않는다.

실패하면 실행 결과보다 컴파일된 SQL을 먼저 확인한다. `<=>`가 거리를 계산하는지, null 임베딩이 제외되는지, 출처 식별 열이 모두 최종 정렬에 참여하는지를 순서대로 본다.

### 여기까지 왔을 때 설명할 수 있어야 하는 것

다음 질문의 답은 앞에서 **굵게 표시한 핵심 문장**에 있다. 각 답을 해당 코드와 연결해 설명해 본다.

- **벡터 인덱스와 임베딩 모델은 각각 어떤 역할을 하는가?**
  - **답:** 임베딩 모델은 텍스트를 의미 공간의 벡터로 바꾸고, 벡터 인덱스는 저장된 벡터 가운데 비교할 후보를 빠르게 찾도록 구성한다.
- **정확 검색, HNSW, IVFFlat은 검색할 후보 범위를 어떻게 다르게 확인하는가?**
  - **답:** 정확 검색은 모든 벡터를 비교하고, HNSW는 그래프를 따라 가까운 후보 일부를 탐색하며, IVFFlat은 질의와 가까운 군집 목록만 확인한다.
- **근사 인덱스는 무엇을 측정 불가능하게 만드는가?**
  - **답:** 정확 검색 기준선이 없으면 근사 인덱스가 실제 이웃을 건너뛰어서 생긴 재현율 손실만 따로 측정할 수 없다.
- **공급자 출력을 이미 검증했는데 질문 벡터에 또 검증이 필요한 이유는 무엇인가?**
  - **답:** 질문 벡터는 테스트, 캐시, 클라이언트처럼 공급자 검증기를 거치지 않는 경로에서도 들어올 수 있으므로 이 경계에서 차원과 유한성을 다시 확인해야 한다.
- **`items` 필터가 하나의 `IN` 절이 될 수 없는 이유는 무엇인가?**
  - **답:** `None`은 번호 없는 섹션을 뜻하지만 SQL의 `IN`은 `NULL`과 일치하지 않는다. 이름 있는 항목 조건과 `IS NULL`을 `OR`로 묶어야 한다.
- **동점 키 다섯 개를 없애면 어떤 실패가 나타나는가?**
  - **답:** 거리가 같은 행의 데이터베이스 순서가 보장되지 않아, 같은 실행 사이에도 순위와 M3 평가 점수가 흔들린다.
- **거리에서 유사도로의 반전을 정확히 한 번만, 어디에서 하는가?**
  - **답:** 호출자마다 방향을 다르게 뒤집는 일을 막기 위해 한 번만 변환한다. `vector_search`가 `score`를 `1 - distance`로 만들 때 수행한다.

## M2.4 — 임베딩이 놓치는 것을 잡는 두 번째 경로

벡터 검색 하나로는 처리하지 못하는 질의가 있다.

사용자가 "Item 7A"를 검색하는 경우가 그렇다. 임베딩 모델에게 "Item 7A"는 짧고 구별점이 적은 토큰이므로, 의미 공간에서 "Item 7", "Item 8"과 거의 같은 위치에 놓인다. 금액 `26,974`나 티커 `MU`도 마찬가지다.

**이런 토큰은 의미가 가까운 문서가 아니라 글자가 정확히 일치하는 문서를 찾아야 하므로, 임베딩이 아니라 어휘 검색(lexical search)이 처리한다.**

### 검색 엔진을 따로 띄우지 않는다

이 지점에서 Elasticsearch나 OpenSearch를 도입하는 구성이 일반적이다. 이 프로젝트는 도입하지 않는다.

**PostgreSQL이 전문 검색(full-text search)을 제공하고, 검색 대상 데이터도 이미 같은 데이터베이스에 있다.** M1.4에서 만든 생성 열 `content_tsv`와 GIN 인덱스가 이 검색을 위한 것이다.

검색 엔진을 따로 두면 같은 데이터를 두 저장소에 동기화해야 한다. **동기화가 필요해지는 순간부터 검색 인덱스가 데이터베이스의 현재 상태와 어긋나는 오류가 생기고, 이 오류는 두 저장소를 비교해야만 확인된다.** 9,172행 규모에서 이 비용을 치를 이유가 없다.

**인프라는 필요해진 다음에 늘린다.** 코퍼스가 수백만 건이 되면 그때 옮기면 되고, 그 시점에 교체되는 것은 `lexical_search` 함수 하나다.

### 사용자 입력을 tsquery로 바꾸는 안전한 방법

전문 검색에서 흔한 오류는 사용자 입력을 tsquery 문법으로 직접 조립하는 것이다. `"NVIDIA & risk"` 같은 문자열을 코드로 만들면, 사용자가 `&`나 `!`, 괄호를 입력하는 순간 그 문자가 문법의 일부로 해석되어 질의가 실패한다.

`websearch_to_tsquery`는 검색창에 입력할 법한 문자열을 그대로 받는다. 따옴표, `or`, `-`가 섞여 있어도 **함수가 내부에서 유효한 tsquery로 변환하므로, 잘못된 입력이 예외가 아니라 빈 결과가 된다.**

그리고 질의 문자열은 항상 **바인드 파라미터**로 전달한다. 문자열 포매팅으로 SQL에 직접 끼워 넣으면 인젝션 경로가 열린다.

### 무엇을 작성하고 어디를 직접 구현할까

M2.4는 `app/retrieval/lexical.py`를 네 단계로 작성한다. 구성은 M2.3과 같다. 구문 빌더와 실행기를 분리해 데이터베이스 없이 SQL을 검증한다.

| 구간 | 학습 행동 | 여기서 얻어야 하는 것 |
|---|---|---|
| 모듈 헤더 | **구조 작성** | 모듈 docstring이 "무엇이 아닌지"를 밝히는 이유 |
| `_filter_predicates` | 필터 매핑을 **직접 구현** | M2.3과 일치해야 하는 부분과 일부러 다른 부분 |
| `lexical_statement` | 안전한 질의 구성을 **직접 구현** | 원시 사용자 텍스트가 문법이 되지 않고 SQL에 닿는 방법 |
| `lexical_search` | **설계 결정 확인** | 이 점수를 벡터 점수와 비교하면 안 되는 이유 |

### 1. 모듈 헤더

#### `app/retrieval/lexical.py` 생성 — 모듈 헤더

**학습 행동 — 구조 작성:** docstring을 자세히 읽는다. 이 구현을 BM25라고 설명하는 것을 막기 위한 문장이 들어 있다.

```python
"""PostgreSQL full-text lexical retrieval.

This is the project's mandatory lexical baseline. It uses PostgreSQL full-text
search with cover-density ranking; ``ts_rank_cd`` is not literal BM25.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Select, Text, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.db.models import Chunk, Document
from app.retrieval.types import ChunkHit, RetrievalFilters

TEXT_SEARCH_CONFIG = "english"

# ``ts_rank_cd`` normalization bitmask (PostgreSQL, "Ranking Search Results").
# Bit 4 divides the rank by the mean harmonic distance between extents, so query
# terms that appear close together outrank the same terms scattered apart; bit 1
# divides by ``1 + log(document length)``, so a long chunk stuffed with one common
# term cannot outrank a short chunk that actually answers. With the default of 0,
# rank degenerates into occurrence counting and, measured on the golden suite,
# recall@5 is exactly zero; 4|1 is the best-scoring native combination.
TS_RANK_NORMALIZATION = 4 | 1
```

**코드에서 꼭 볼 것**

- docstring은 `ts_rank_cd`가 BM25가 **아니라고** 명시한다. 커버 밀도(cover density)와 BM25는 서로 다른 공식이므로, 문서나 README에서 이 구현을 BM25라고 설명하면 사실과 다른 기술이 된다. 실제 BM25는 [튜토리얼 7](07-bm25.md)에서 직접 써 본다. M2.9까지 기다리는 이유는, 그때 갈아 끼워야 이 어댑터 경계가 유지된다는 것을 증명할 수 있기 때문이다.
- `TEXT_SEARCH_CONFIG`는 인라인 리터럴이 아니라 모듈 상수다. 질의 시점에 사용하는 어간 추출 사전이 M1.4에서 `content_tsv`를 생성할 때 사용한 것과 같아야 한다. 두 설정이 다르면 어간이 같은 단어가 오류 없이 매칭되지 않는다.
- `TS_RANK_NORMALIZATION`은 추측이 아니라 측정으로 정한 값이다. PostgreSQL의 정규화 비트마스크 전부를 골든 스위트에 대해 훑었고, 이 주석은 승자가 이기는 이유를 기록한다. 그 측정 이야기가 3절의 본론이다.

### 2. 벡터 검색과 일치해야 하는 필터

이 함수는 M2.3이 정의한 필터 계약의 나머지 절반이고, 이 절반은 코드로 강제되지 않는다.

두 필터 함수는 공유 코드가 아니다. 서로 다른 모듈에 있는 별개의 private 함수이고, 같은 의미를 갖도록 사람이 맞춰 쓴 것이다. 두 함수는 실제로 같은 여섯 차원, 같은 AND 의미, `None`을 무번호 섹션으로 다루는 같은 규칙을 구현한다. 다만 두 구현이 같은지 검사하는 장치는 없다.

중복을 그대로 둔 이유는 두 구문의 형태가 다르기 때문이다. 벡터 경로는 구문을 받아 조건을 덧붙이고, 어휘 경로는 술어 튜플을 반환한다. 하나의 헬퍼로 묶으려면 어느 형태를 만들지 지정하는 플래그가 필요하고, 그 플래그가 다시 분기를 만든다. **대신 한쪽 필터만 수정하면 두 경로가 서로 다른 문서 집합을 검색하게 되고, M2.5의 융합은 이 불일치를 감지하지 못한다.**

그래서 작성한 뒤 두 함수를 나란히 놓고 비교하는 것이 이 단계의 핵심 연습이다.

#### `app/retrieval/lexical.py` 확장 — 필터 술어

**학습 행동 — 필터 매핑 구현:** M2.3과 같은 여섯 차원을 구현한다. 그다음 두 함수를 비교해 차이를 전부 짚어 본다.

<!-- src: app/retrieval/lexical.py::_filter_predicates -->
```python
def _filter_predicates(filters: RetrievalFilters) -> tuple[ColumnElement[bool], ...]:
    """Translate the shared exact-match filters to composable SQL predicates."""
    predicates: list[ColumnElement[bool]] = []
    if filters.doc_ids:
        predicates.append(Chunk.doc_id.in_(filters.doc_ids))
    if filters.tickers:
        predicates.append(Document.ticker.in_(filters.tickers))
    if filters.fiscal_years:
        predicates.append(Document.fiscal_year.in_(filters.fiscal_years))
    if filters.forms:
        predicates.append(Document.form.in_(filters.forms))
    if filters.items:
        named_items = tuple(item for item in filters.items if item is not None)
        item_predicates: list[ColumnElement[bool]] = []
        if named_items:
            item_predicates.append(Chunk.item.in_(named_items))
        if None in filters.items:
            item_predicates.append(Chunk.item.is_(None))
        predicates.append(or_(*item_predicates))
    if filters.kinds:
        predicates.append(Chunk.kind.in_(filters.kinds))
    return tuple(predicates)
```

**코드에서 꼭 볼 것**

- 이 함수는 M2.3의 `_filtered_statement`와 달리 구문을 받아 수정하지 않고 술어 튜플을 반환한다. 형태는 다르고 의미는 같아야 한다.
- 조건부 조인이 없다. `lexical_statement`가 `Document`를 항상 조인하므로 이 함수가 판단할 것이 없다.
- `items` 분기는 같은 `or_`를 만든다. `IN` 목록과 `IS NULL` 술어를 묶되 두 술어를 덧붙이는 순서가 벡터 경로와 반대다. `or_` 안의 순서는 결과 집합을 바꾸지 않지만, 두 구현이 사람 손으로 유지되는 사본이라는 사실을 보여준다.
- **두 함수는 중복 구현이고, 둘의 일치를 강제하는 장치가 없다.** 한쪽에 필터 차원을 추가하고 다른 쪽을 잊으면 벡터 검색과 어휘 검색이 서로 다른 문서 집합을 검색한다.

### 3. 사용자 텍스트가 문법이 되지 않게 질의를 만든다

이 함수에는 실패가 셋 산다. 둘은 누구나 결국 배우게 되는 위험이고, 셋째는 평가 스위트가 측정하기 전까지 보이지 않았다.

첫째는 SQL 인젝션이다. 사용자 텍스트를 SQL 문자열에 포매팅하지 않고 값으로 넘기면 SQLAlchemy가 파라미터로 바인딩한다.

둘째는 전문 검색에만 있는 위험이다. 파라미터 바인딩이 완전해도 `to_tsquery`는 전달받은 인자를 tsquery 문법으로 파싱한다. `risk & (a|b`가 담긴 바인드 파라미터는 인젝션이 아니라 문법 오류이고, PostgreSQL은 예외를 발생시킨다. 이때 괄호를 하나 잘못 입력한 사용자는 검색 결과 대신 서버 오류를 받는다.

**`websearch_to_tsquery`는 인자를 tsquery 문법이 아니라 검색어 문자열로 파싱하므로 두 번째 위험을 막는다.** 두 위험은 원인이 다르고, 막는 수단도 파라미터 바인딩과 함수 선택으로 각각 다르다.

셋째 실패는 그 함수 호출이 **만들어 내는 것**에 있다. `websearch_to_tsquery`는 모든 내용 어휘소를 `&`로 잇는다. 골든 질문 "What was the total revenue reported for fiscal 2024?"는 AND로 묶인 어간 다섯 개가 되고, 다섯 개를 전부 가진 청크만 매칭된다. 이 코퍼스에서 그런 청크는 하나도 없다. 첫 M3 실행은 **평가 케이스 28개 전부에서 히트 0개**, recall@5 정확히 0.000을 기록했고, 어디서도 예외가 나지 않았다. 빈 결과 집합은 에러가 아니기 때문이다. 검색 경로는 인젝션에 안전하고 문법에 안전하면서 동시에 완전히 무용할 수 있다.

그래서 이 구문은 파싱된 질의를 쓰기 전에 완화한다. tsquery의 텍스트 표현은 어휘소마다 따옴표로 감싸고 그 안에 `&`가 들어갈 수 없으므로, `&`를 `|`로 바꿔 `to_tsquery`로 다시 파싱하면 논리곱이 논리합이 되면서 인용 구문(`<->`)은 그대로 남는다.

매칭을 완화하고 나면 같은 문제의 다음 층이 드러난다. 드디어 후보가 흐르는데도 `ts_rank_cd`의 기본 정규화는 사실상 등장 횟수 세기로 순위를 매기고, `AMD`나 `fiscal`처럼 어디에나 있는 단어를 잔뜩 가진 청크가 정답 청크를 이긴다. 후보가 **있는데도** 측정 recall은 0.000에 머물렀다. 정규화 비트마스크 전부를 골든 스위트에 대해 훑은 결과가 `4 | 1`이다. 질의 단어들이 가까이 함께 나오는 청크를 올리고 한 단어로 채운 긴 청크를 깎는 조합이고, recall@5를 0.271로 끌어올렸다. 같은 코퍼스에서 BM25의 0.521 옆에 놓인 그 숫자가 정확히 M3가 존재하는 이유인 정직한 비교다.

#### `app/retrieval/lexical.py` 확장 — 안전한 FTS 구문

**학습 행동 — 안전한 질의 구성 구현:** 가드 두 개를 먼저 작성하고, 다음으로 파싱-완화 한 쌍과 정규화된 `score` 표현식, 마지막으로 열두 개의 선택 열을 작성한다.

<!-- src: app/retrieval/lexical.py::lexical_statement -->
```python
def lexical_statement(
    query: str,
    k: int,
    filters: RetrievalFilters | None = None,
) -> Select[Any]:
    """Build a safe PostgreSQL FTS statement ranked by cover density.

    ``websearch_to_tsquery`` accepts raw user text without exposing ``to_tsquery``
    syntax errors, and SQLAlchemy binds ``query`` as a value instead of interpolating
    it. But its output joins every content lexeme with ``&``: a natural-language
    question like "What was the total revenue reported for fiscal 2024?" becomes
    five AND-ed stems, and only a chunk containing all five matches. On this corpus
    that describes almost no chunk, and the baseline silently returns nothing.

    The statement therefore relaxes the parsed query before using it. The tsquery's
    text form quotes each lexeme and can never contain ``&`` inside one, so
    rewriting ``&`` to ``|`` and reparsing with ``to_tsquery`` turns the conjunction
    into a disjunction while leaving quoted phrases (``<->``) intact. Matching any
    query term is enough to become a candidate, and ``TS_RANK_NORMALIZATION`` makes
    the ranking prefer chunks where more of the query co-occurs closely over chunks
    that merely repeat one common term. One semantic is knowingly weakened: an
    explicit ``-term`` exclusion is relaxed along with everything else.

    PostgreSQL FTS is the lexical baseline here; this statement does not implement BM25.
    """
    if not query.strip():
        raise ValueError("query must not be blank")
    if k <= 0:
        raise ValueError("k must be positive")

    active_filters = filters or RetrievalFilters()
    parsed = func.websearch_to_tsquery(TEXT_SEARCH_CONFIG, query)
    tsquery = func.to_tsquery(TEXT_SEARCH_CONFIG, func.replace(cast(parsed, Text), "&", "|"))
    score = func.ts_rank_cd(Chunk.content_tsv, tsquery, TS_RANK_NORMALIZATION).label("score")
    return (
        select(
            Chunk.id.label("chunk_id"),
            Chunk.doc_id,
            Chunk.item,
            Chunk.kind,
            Chunk.citation,
            Chunk.start_char,
            Chunk.end_char,
            Chunk.source_sha256,
            Chunk.body,
            Chunk.context_header,
            Chunk.index_text,
            score,
        )
        .join(Document, Document.doc_id == Chunk.doc_id)
        .where(Chunk.content_tsv.op("@@")(tsquery), *_filter_predicates(active_filters))
        .order_by(
            score.desc(),
            Chunk.doc_id.asc(),
            Chunk.source_sha256.asc(),
            Chunk.start_char.asc(),
            Chunk.end_char.asc(),
            Chunk.id.asc(),
        )
        .limit(k)
    )
```

**코드에서 꼭 볼 것**

- `func.websearch_to_tsquery(TEXT_SEARCH_CONFIG, query)`는 `query`를 함수 인자로 넘기고, SQLAlchemy가 그 값을 파라미터로 바인딩한다. 문자열 포매팅도 연결도 없다는 점이 인젝션 방어의 전부다.
- 완화는 사용자의 텍스트가 아니라 tsquery의 **텍스트 표현**에 일어난다. 원문 질의를 파이썬에서 고치면 토큰화를 한 번 더 하는 셈이고, PostgreSQL의 토크나이저와 어긋날 수 있는 두 번째 토크나이저는 이 모듈이 다른 모든 곳에서 피하는 바로 그 부류의 버그다. 어휘소에는 `&`가 들어갈 수 없으므로 이 치환이 어휘소를 훼손할 수도 없다.
- 인용 구문이 완화를 통과해 살아남는 이유는 `websearch_to_tsquery`가 인용을 `<->` 연산자로 컴파일하고 치환 대상은 `&`뿐이기 때문이다. 의미 하나는 알고 약화시킨다. 명시적 `-term` 배제도 나머지와 함께 완화된다.
- `tsquery` 표현식을 한 번 만들어 `score` 계산과 `@@` 매칭 두 곳에서 사용한다. 따로 두 번 만들면 같은 부분식이 두 개로 컴파일되고, 한쪽만 수정될 여지가 생긴다. 후보와 순위는 같은 완화된 질의에서 나와야 한다. 아니면 청크가 자기가 매칭된 적 없는 질의로 채점될 수 있다.
- `TS_RANK_NORMALIZATION`은 `ts_rank_cd`의 세 번째 인자로 함께 간다. 이게 없으면 수정은 완성돼 보이면서 아무것도 측정하지 못한다. 매칭은 필요조건이었고, 랭킹이 충분조건이었다.
- **`score.desc()`는 내림차순으로 정렬한다. `ts_rank_cd`는 이미 클수록 좋은 값이므로 변환 없이 그대로 정렬하고, 거리를 반환하는 M2.3만 오름차순으로 정렬한다.**
- `score` 뒤의 동점 해소 키 다섯 개는 M2.3과 같고, 사용하는 이유도 같다.
- `Chunk.id.label("chunk_id")`가 열 이름을 필드 이름에 맞추므로 행이 `ChunkHit`으로 그대로 매핑된다. 4단계가 이 이름에 의존한다.

### 4. 실행, 그리고 비교하면 안 되는 점수

#### `app/retrieval/lexical.py` 완성 — 실행

**학습 행동 — 설계 결정 확인:** 이 함수는 두 줄이다. docstring에 M2.5가 의존하는 제약이 들어 있다.

<!-- src: app/retrieval/lexical.py::lexical_search -->
```python
async def lexical_search(
    session: AsyncSession,
    query: str,
    k: int = 5,
    filters: RetrievalFilters | None = None,
) -> list[ChunkHit]:
    """Run the PostgreSQL FTS baseline and return typed, deterministically ordered hits.

    The returned score is the native ``ts_rank_cd`` cover-density score, not BM25
    and not a probability. Fusion must consume its rank instead of comparing this
    value directly with another retrieval strategy's score.
    """
    result = await session.execute(lexical_statement(query, k, filters))
    return [ChunkHit.model_validate(row) for row in result.mappings().all()]
```

**코드에서 꼭 볼 것**

- `ChunkHit.model_validate(row)`를 `result.mappings()` 결과에 바로 적용할 수 있는 이유는 3단계에서 열 이름을 필드 이름과 같게 선택했기 때문이다. M2.3이 `ChunkHit`을 직접 생성한 것은 거리에서 `score`를 계산해야 했기 때문이다.
- 매핑 경로가 달라도 검증은 모든 행에서 실행된다. `index_text`가 `body`와 어긋나는 어휘 hit는 벡터 경로와 같은 이유로 여기서 거부된다.
- docstring의 마지막 문장은 권고가 아니라 제약이다. **`ts_rank_cd` 값에는 고정된 범위가 없고 질의가 다르면 값의 크기를 비교할 근거도 없다. 그래서 두 경로의 점수를 직접 비교하지 않고 순위만 사용하는 M2.5의 융합이 필요하다.**

여기까지 작성하면 `app/retrieval/lexical.py`가 완성된다. 네 블록을 순서대로 이어 붙인 것이 그대로 체크포인트 파일이다.

### 집중 테스트와 테스트가 지키는 계약

#### 실행 `tests/retrieval/test_04_lexical.py`

```bash
uv run pytest tests/retrieval/test_04_lexical.py -q
```

| 테스트가 깨뜨리는 값 | 지키는 계약 |
|---|---|
| tsquery 구두점이 들어간 질의 | 사용자 텍스트가 질의 문법이 되지 않는다. |
| 바인딩 대신 끼워 넣은 질의 | 인젝션 경로가 존재하지 않는다. |
| 벡터 경로와 다르게 동작하는 필터 | 두 검색 경로가 하나의 문서 집합을 본다. |
| 빠진 근거 열 | 모든 어휘 hit가 완전한 출처를 들고 있다. |
| 순위가 동점인 hit의 입력 순서 | 실행 사이에 순서가 결정론적으로 유지된다. |
| 모든 질의 단어를 요구하는 논리곱 | 부분 매칭도 후보가 된다. recall이 소리 없이 0이 될 수 없다. |
| 기본 정규화로 계산한 순위 | 등장 횟수 세기가 가까운 동시 출현을 이길 수 없다. |

구현이 끝나면 파라미터화된 SQL, 두 경로가 일치하는 필터, 완전한 근거 필드, 결정론적 순서를 검증하는 모든 어휘 테스트가 통과해야 한다.

질의 문자열을 SQL에 직접 끼워 넣거나, 필터 동작이 벡터 검색과 다르거나, 이 구현을 BM25라고 설명하면 M2.4를 완료로 판단하지 않는다.

실패하면 컴파일된 PostgreSQL 구문을 확인한다. 질의가 바인딩된 값으로 남아 있는지, `websearch_to_tsquery`가 그 값을 파싱하는지, 완화된 `to_tsquery` 재작성이 매칭과 순위 양쪽에 들어가는지, `Document` 조인이 벡터 검색과 같은 메타데이터 필터를 지원하는지를 순서대로 본다.

### 여기까지 왔을 때 설명할 수 있어야 하는 것

다음 질문의 답은 앞에서 **굵게 표시한 핵심 문장**에 있다. 각 답을 해당 코드와 연결해 설명해 본다.

- **벡터 검색이 잘 처리하지 못하는 질의는 어떤 것이고, 왜 그런가?**
  - **답:** `Item 7A`, `26,974`, `MU`처럼 정확한 토큰이 핵심인 질의다. 임베딩은 짧고 비슷하게 생긴 식별자들을 의미 공간에서 뚜렷하게 구분하지 못할 수 있다.
- **검색 엔진을 따로 띄우면 어떤 새로운 종류의 버그가 생기는가?**
  - **답:** 데이터베이스와 외부 검색 인덱스가 서로 다른 코퍼스 버전을 갖는 동기화 불일치가 생긴다.
- **`websearch_to_tsquery`가 손으로 만든 문법 대신 막아 주는 것은 무엇인가?**
  - **답:** 일반 사용자 문자열과 구두점을 유효한 tsquery로 바꿔, 잘못된 연산자나 괄호 때문에 PostgreSQL 문법 오류가 나는 일을 막는다.
- **이 경로는 내림차순으로 정렬하는데 M2.3은 오름차순인 이유는 무엇인가?**
  - **답:** `ts_rank_cd`는 값이 클수록 좋지만, M2.3의 코사인 거리는 작을수록 가깝기 때문이다.
- **이 점수를 벡터 점수와 직접 비교할 수 없는 이유는 무엇인가?**
  - **답:** 커버 밀도 순위는 고정된 범위가 없고 코사인 유사도와 단위도 다르므로, 두 검색기의 내부 순위만 서로 비교할 수 있다.
- **파싱된 질의를 쓰기 전에 AND에서 OR로 완화하는 이유는 무엇인가?**
  - **답:** `websearch_to_tsquery`는 질문의 모든 내용 어휘소를 가진 청크 하나를 요구하는데, 이 코퍼스에 그런 청크는 없다. 완화 전의 베이스라인은 골든 스위트 전체에서 히트 0개를 기록하면서 아무 예외도 내지 않았다.
- **완화가 사용자 텍스트 대신 tsquery의 텍스트 표현을 고치는 이유는 무엇인가?**
  - **답:** 텍스트 표현은 어휘소마다 따옴표로 감싸고 그 안에 `&`가 들어갈 수 없어 치환이 안전하다. 원문 질문을 고치려면 PostgreSQL과 어긋날 수 있는 두 번째 토크나이저가 필요해진다.
- **완화만으로 안 되고 정규화 비트마스크가 바꾼 것은 무엇인가?**
  - **답:** 후보가 있어도 기본 정규화에서는 순위가 등장 횟수 세기로 퇴화해 흔한 단어를 채운 청크가 이긴다. `4 | 1`이 가까운 동시 출현을 반복보다 위에 올릴 때까지 recall은 0에 머물렀다.

---

[← 이전: 임베딩](02-embeddings.md) · [모듈 개요](../03-build.md) · [다음 →: 융합](04-fusion.md)
