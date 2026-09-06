# M2.5–M2.6 튜토리얼 4 — 순위 융합과 선택적 재순위화

**선행 조건:** 튜토리얼 3의 `uv run pytest tests/retrieval/test_04_lexical.py -q`가 통과해야 한다. 두 검색 경로가 모두 있어야 순위를 합칠 수 있다.

## M2.5 — 점수를 섞지 말고 순위를 섞는다

두 검색 경로가 각각 순위 목록을 반환했다. 이제 두 목록을 하나의 순위로 합쳐야 한다. 가장 먼저 떠오르는 방법은 두 점수의 가중 평균이다.

#### 파일 수정 없음 — 가중 점수 합이 왜 틀렸는지 읽기

```python
final = 0.7 * vector_score + 0.3 * lexical_score   # ❌
```

이 방법이 왜 성립하지 않는지가 이 단계의 핵심이다.

### 두 점수는 애초에 같은 단위가 아니다

| | 벡터 점수 | 어휘 점수 |
|---|---|---|
| 정체 | `1 - cosine distance` | `ts_rank_cd` 커버 밀도 |
| 범위 | 대략 0–1 | 위로 제한 없음 |
| 의미 | 의미적 유사도 | 질의어가 문서에 얼마나 밀집해 있는가 |
| 분포 | 대개 0.6–0.9에 뭉침 | 질의마다 척도가 다름 |

**두 점수는 단위와 범위가 다르므로 가중 평균의 결과가 무엇을 뜻하는지 정의되지 않는다.** `0.7 * 0.85 + 0.3 * 4.2`는 계산은 되지만 그 값이 나타내는 관련성이 없다.

정규화로 범위를 맞추는 방법도 답이 아니다. min-max 정규화는 **같은 문서의 점수를 그 질의의 결과 집합에 의존하게 만든다.** 관련 없는 문서가 하나 더 매칭됐다는 이유만으로 상위 순위가 뒤집힐 수 있다.

### RRF는 점수를 아예 버린다

Reciprocal Rank Fusion은 점수를 무시하고 **순위만** 쓴다.

#### 파일 수정 없음 — RRF 공식 읽기

```
chunk's final score = Σ  1 / (rrf_k + its rank in each list)
```

벡터가 1위, 어휘가 3위로 꼽은 청크는 `1/(60+1) + 1/(60+3)`을 받는다.

순위는 어느 검색기가 만들었든 같은 의미를 갖는다. 1위는 그 검색기가 가장 관련 있다고 판단한 결과이고, 그 판단의 내부 단위가 코사인 유사도인지 커버 밀도인지는 순위에 남지 않는다. **RRF는 단위가 다른 점수 대신 두 목록에서 동일하게 정의되는 순위만 사용한다.**

결과도 직관과 맞는다. **양쪽 목록에서 모두 상위에 오른 청크가 최종 순위에서 이긴다.** 두 목록에서 각각 3위인 청크가 한쪽에서만 1위인 청크보다 신뢰할 만하다는 판단이 공식에 그대로 반영되어 있다.

`rrf_k`(기본값 60)는 각 목록 상위권의 영향력을 조절하는 상수다. 값이 작을수록 1위와 2위의 기여 차이가 커지고, 클수록 평평해진다. 이 값도 M3의 실험 대상이다.

### 무엇을 작성하고 어디를 직접 구현할까

M2.5는 `app/retrieval/hybrid.py`를 네 단계로 작성한다. 이 파일은 SQLAlchemy를 import하지 않는다. 융합이 두 목록에 대한 순수 계산이기 때문이다.

| 구간 | 학습 행동 | 여기서 얻어야 하는 것 |
|---|---|---|
| 모듈 헤더 | **구조 작성** | 검색 함수가 import가 아니라 타입으로 들어오는 이유 |
| `_FusedHit`과 `_unique_ranked_hits` | 중복 제거를 **직접 구현** | 한 목록이 청크당 순위 하나만 낼 수 있는 이유 |
| `rrf_fuse` | 융합 루프를 **직접 구현** | 순위가 점수를 대체하는 지점 |
| `hybrid_search` | **구조 작성 후 호출 순서 검토** | 두 검색을 순차로 await하는 이유 |

### 1. 모듈 헤더

#### `app/retrieval/hybrid.py` 생성 — 모듈 헤더

**학습 행동 — 구조 작성:** import 목록을 확인한다. 이 파일이 가져오는 어떤 이름도 데이터베이스에 의존하지 않는다.

```python
"""Rank-only reciprocal rank fusion and thin hybrid orchestration."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from app.retrieval.types import ChunkHit, RetrievalFilters, sort_hits

DEFAULT_RRF_K = 60

SearchCallable = Callable[[str, int, RetrievalFilters], Awaitable[list[ChunkHit]]]
```

**코드에서 꼭 볼 것**

- `vector_search`도 `lexical_search`도 import하지 않는다. 대신 `SearchCallable`이 두 함수의 형태만 기술하므로, 융합을 리스트 두 개로 데이터베이스 없이 테스트할 수 있다.
- `DEFAULT_RRF_K = 60`은 공식 안의 리터럴이 아니라 이름을 가진 모듈 상수다. M3가 이 값을 바꿔 가며 실험하므로, 실험 대상 값은 한 곳에서만 바뀌어야 한다.

### 2. 한 목록은 청크당 순위 하나만 낸다

중복 제거는 정리 작업처럼 보이지만 융합 점수를 직접 결정한다.

한 구성 목록에 500번 청크가 두 번 들어 있는 경우를 보자. 순위는 목록 안의 위치로 매겨지므로, 이 청크는 `1/(60+2)`와 `1/(60+7)`을 모두 더해 받는다. 그 결과 다른 검색기가 1위로 꼽은 청크보다 높은 점수를 얻는다.

**한 목록이 같은 청크에 순위를 두 번 부여하면 중복이 기여를 두 번 하므로, 중복 제거는 순위를 매기기 전에 끝나야 한다.** 순서를 지키지 않으면 융합 순위는 오류 없이 잘못된 결과를 낸다.

#### `app/retrieval/hybrid.py` 확장 — 융합 누산기

**학습 행동 — 중복 제거 구현:** `_unique_ranked_hits`를 직접 작성하고, 이 함수가 없을 때 융합 점수가 어떻게 달라지는지 확인한다.

<!-- src: app/retrieval/hybrid.py::_FusedHit,_unique_ranked_hits -->
```python
@dataclass(slots=True)
class _FusedHit:
    hit: ChunkHit
    score: float = 0.0


def _unique_ranked_hits(hits: Sequence[ChunkHit]) -> list[ChunkHit]:
    """Keep the first occurrence of each chunk so one list contributes one rank."""
    seen: set[int] = set()
    unique: list[ChunkHit] = []
    for hit in hits:
        if hit.chunk_id not in seen:
            seen.add(hit.chunk_id)
            unique.append(hit)
    return unique
```

- `_FusedHit`은 이 프로젝트의 다른 레코드와 달리 frozen이 **아니다.** 루프에서 `score`를 누적하는, 함수 안에서만 사는 누산기이기 때문이다.
- 중복 제거가 순위를 매기기 **전에** 실행된다. 순서가 반대이면 중복이 순위 자리를 두 개 차지하고 기여도 두 번 한다.
- 같은 청크가 여러 번 나오면 첫 등장 위치를 사용한다. 구성 검색기가 매긴 순서가 그대로 보존된다.

### 3. 순위가 점수를 대체하는 융합

#### `app/retrieval/hybrid.py` 확장 — 상호 순위 융합

**학습 행동 — 융합 루프 구현:** 누산 로직을 직접 작성한다. 완성한 뒤 들어온 `score`를 한 번도 읽지 않는지 확인한다.

<!-- src: app/retrieval/hybrid.py::rrf_fuse -->
```python
def rrf_fuse(
    vector_hits: Sequence[ChunkHit],
    lexical_hits: Sequence[ChunkHit],
    k: int,
    *,
    rrf_k: int = DEFAULT_RRF_K,
) -> list[ChunkHit]:
    """Fuse ranked lists by reciprocal rank, keyed by database ``chunk_id``.

    Source scores are intentionally ignored because vector similarity and PostgreSQL
    FTS cover-density scores have unrelated scales. Each list contributes
    ``1 / (rrf_k + rank)`` once per chunk, where rank is one-based.
    """
    if k <= 0:
        raise ValueError("k must be positive")
    if rrf_k <= 0:
        raise ValueError("rrf_k must be positive")

    fused: dict[int, _FusedHit] = {}
    for ranking in (vector_hits, lexical_hits):
        for rank, hit in enumerate(_unique_ranked_hits(ranking), start=1):
            contribution = 1.0 / (rrf_k + rank)
            entry = fused.get(hit.chunk_id)
            if entry is None:
                fused[hit.chunk_id] = _FusedHit(hit=hit, score=contribution)
            else:
                entry.score += contribution

    hits = [entry.hit.model_copy(update={"score": entry.score}) for entry in fused.values()]
    return sort_hits(hits)[:k]
```

**코드에서 꼭 볼 것**

- 들어온 `hit.score`를 한 번도 읽지 않고 `enumerate`가 주는 위치만 사용한다. **점수를 섞지 않고 순위만 섞는다는 이 단계의 결론이 이 두 줄에 들어 있다.**
- `start=1`이 순위를 1부터 세게 한다. 0부터 세면 최상위 hit가 `1/rrf_k`를 기여하게 되어 공식이 알려진 정의와 달라진다.
- 누산기의 키는 객체 식별자가 아니라 `chunk_id`다. 같은 청크가 두 경로에서 서로 다른 `ChunkHit` 인스턴스로 도착하기 때문이다.
- `model_copy(update={"score": ...})`는 frozen 모델을 변경하지 않고 점수만 교체한 사본을 만든다. 나머지 근거 필드는 그대로 전달된다.
- `sort_hits`는 모든 기여를 합산한 뒤에 실행된다. M2.1의 동점 해소 키를 그대로 사용하므로 RRF 합이 같아도 순서가 고정된다.
- `[:k]` 절단은 가장 마지막에 실행된다. **더 일찍 자르면 두 번째 목록의 기여로 상위 k에 올라왔을 청크가 융합 전에 사라진다.**

### 4. 테스트할 수 있을 만큼 얇은 오케스트레이션

이 파일의 마지막 함수는 호출 순서만 결정한다.

호출 가능 객체 두 개를 받아 각각 await하고, 두 결과를 `rrf_fuse`에 넘긴다. 세션이 무엇인지, 임베딩 공급자가 무엇인지, 벡터 질의를 어떻게 준비하는지는 이 함수가 알지 못한다. 그 정보는 M2.7의 어댑터가 클로저로 들고 있다.

이 구조 덕분에 융합 로직을 리스트 두 개만으로 테스트할 수 있다. 데이터베이스도, 픽스처도, ORM 목도 필요 없다. 순위가 잘못 나올 때 실패하는 테스트가 인프라가 아니라 계산을 가리킨다.

#### `app/retrieval/hybrid.py` 완성 — 하이브리드 오케스트레이션

**학습 행동 — 구조 작성 후 호출 순서 검토:** 가드는 기계적으로 작성한다. 설계 결정은 두 개의 `await` 줄에 있다.

<!-- src: app/retrieval/hybrid.py::hybrid_search -->
```python
async def hybrid_search(
    query: str,
    k: int,
    filters: RetrievalFilters | None = None,
    *,
    vector_search: SearchCallable,
    lexical_search: SearchCallable,
    candidate_k: int | None = None,
    rrf_k: int = DEFAULT_RRF_K,
) -> list[ChunkHit]:
    """Retrieve two candidate lists and combine them with rank-only RRF.

    Injected callables let the production adapter close over its session, embedder,
    and vector query preparation. Calls are awaited sequentially so both adapters may
    safely share one SQLAlchemy ``AsyncSession``.
    """
    if not query.strip():
        raise ValueError("query must not be blank")
    if k <= 0:
        raise ValueError("k must be positive")
    if rrf_k <= 0:
        raise ValueError("rrf_k must be positive")

    limit = candidate_k if candidate_k is not None else k
    if limit < k:
        raise ValueError("candidate_k must be at least k")
    active_filters = filters or RetrievalFilters()

    vector_hits = await vector_search(query, limit, active_filters)
    lexical_hits = await lexical_search(query, limit, active_filters)
    return rrf_fuse(vector_hits, lexical_hits, k, rrf_k=rrf_k)
```

**코드에서 꼭 볼 것**

- 두 검색을 동시에 실행하지 않고 **차례로** await한다. **`AsyncSession`은 동시 사용을 지원하지 않고, 두 어댑터는 대개 같은 세션을 공유한다.** 이 자리에서 `asyncio.gather`로 두 호출을 묶으면 세션 상태가 깨진다.
- `candidate_k`는 각 경로가 최종 `k`보다 많은 후보를 반환하게 한다. 융합은 목록이 깊을수록 정확해지며, `limit < k`를 거부하는 이유는 후보가 최종 개수보다 적으면 절단이 의미를 잃기 때문이다.
- 같은 `active_filters` 객체를 두 경로에 전달한다. 이 객체는 frozen이므로 어느 어댑터도 값을 바꿀 수 없고, 두 검색이 같은 문서 집합을 대상으로 실행된다.
- 두 검색은 서로를 참조하지 않는다. 그래서 M2.6의 재순위화를 이 함수를 수정하지 않고 뒤에 덧붙일 수 있다.

여기까지 작성하면 `app/retrieval/hybrid.py`가 완성된다. 네 블록을 순서대로 이어 붙인 것이 그대로 체크포인트 파일이다.

정리하면 이런 경로다.

#### 파일 수정 없음 — 융합 경로 전체 흐름 읽기

```
ordered vector hits + ordered lexical hits → per-list deduplication → one-based ranks → RRF contributions → sum by chunk_id → stable top-k ChunkHit list
```

### 집중 테스트와 테스트가 지키는 계약

#### 실행 `tests/retrieval/test_05_hybrid.py`

```bash
uv run pytest tests/retrieval/test_05_hybrid.py -q
```

| 테스트가 깨뜨리는 값 | 지키는 계약 |
|---|---|
| 한 구성 목록 안의 중복 청크 | 한 목록이 청크당 순위 하나만 기여한다. |
| 1부터가 아니라 0부터 세는 순위 | 공식이 알려진 정의와 일치한다. |
| 공식에 들어간 원시 점수 | 비교 불가능한 단위를 비교하지 않는다. |
| 융합 합이 동점인 청크 | 실행 사이에 순서가 결정론적으로 유지된다. |
| 융합보다 먼저 적용된 절단 | 두 번째 목록이 끌어올린 청크가 살아남는다. |
| 동시에 호출된 구성 검색 | 하나의 `AsyncSession`을 동시에 쓰지 않는다. |

구현이 끝나면 중복 처리, 1부터 시작하는 순위, 결정론적 동점 처리, 상위 k 절단, 구성 검색 호출 순서를 검증하는 모든 하이브리드 테스트가 통과해야 한다.

원시 점수가 RRF 공식에 들어가거나 한 구성 목록의 중복이 두 번 기여하면 M2.5를 완료로 판단하지 않는다.

실패하면 점수 대신 순위를 출력해 확인한다. `enumerate(..., start=1)` 이전에 중복을 제거했는지, 누산기의 키가 `chunk_id`인지, 모든 기여를 합산한 뒤에 `sort_hits`를 적용하는지를 순서대로 본다.

### 여기까지 왔을 때 설명할 수 있어야 하는 것

다음 질문의 답은 앞에서 **굵게 표시한 핵심 문장**에 있다. 각 답을 해당 코드와 연결해 설명해 본다.

- **두 점수의 가중 평균이 아무 의미가 없는 이유는 무엇인가?**
  - **답:** 코사인 유사도와 `ts_rank_cd`는 척도와 단위가 달라, 숫자에 가중치를 곱해도 의미상 비교 가능한 값이 되지 않는다.
- **min-max 정규화가 만들어 내는, RRF에는 없는 문제는 무엇인가?**
  - **답:** 같은 문서의 원래 점수가 그대로여도 결과 집합이나 이상치가 달라지면 정규화 점수가 바뀐다. RRF는 순위 위치에만 의존한다.
- **순위를 매긴 뒤에 중복을 제거하면 무엇이 깨지는가?**
  - **답:** 중복 청크가 여러 순위를 차지하고 점수에도 여러 번 기여해, 실수로 반복된 결과가 실제로 강한 청크를 이길 수 있다.
- **`k`로의 절단이 융합보다 앞이 아니라 뒤여야 하는 이유는 무엇인가?**
  - **답:** 두 긴 목록에서 모두 중상위인 후보는 신호를 합치면 최종 상위 k가 될 수 있다. 각 목록을 먼저 자르면 융합 전에 그 후보를 잃는다.
- **두 구성 검색을 동시에 돌리지 않는 이유는 무엇인가?**
  - **답:** 두 어댑터는 보통 같은 `AsyncSession`을 공유하며, 이 세션은 동시 사용에 안전하지 않다.

## M2.6 — 재순위화는 만들되 켜지 않는다

교차 인코더(cross-encoder) 재순위화는 RAG 성능을 올리는 표준 기법이다. 질문과 문서를 **함께** 모델에 넣어 관련성을 매기므로, 각각 임베딩해서 비교하는 것보다 정확하다.

다만 비용이 따른다.

- 후보 수만큼 모델을 호출하니 **느리다**
- 로컬 모델이면 수백 MB 의존성, API면 **비용**
- 무엇보다 **정말 도움이 되는지 아직 모른다**

세 번째 항목이 핵심이다. 교차 인코더가 일반적으로 성능을 올린다는 사실은 **이 코퍼스와 이 질문 유형에서 얼마나 올리는지**를 알려주지 않는다.

그래서 M2에서는 **경계만 정의하고 기본값은 끈 상태로 둔다.** `RerankProvider` 추상 클래스와, 공급자가 없으면 입력을 그대로 통과시키는 함수만 작성한다.

M3에서 실제 공급자를 붙여 어블레이션 실험군으로 비교한다. 그 시점에 재현율이 얼마나 오르고 지연이 얼마나 늘어나는지가 숫자로 나오고, 그 숫자를 보고 켤지 결정한다.

**성능이 좋다고 알려진 기법도 측정 결과 없이 기본으로 켜지 않는다.** M2.3에서 HNSW 인덱스를 미룬 것과 같은 이유다.

### 무엇을 작성하고 어디를 직접 구현할까

M2.6은 `app/retrieval/rerank.py`를 네 단계로 작성한다. 이 모듈에서 가장 작은 파일이고, 공급자가 없을 때 지나가는 경로가 가장 중요하다.

| 구간 | 학습 행동 | 여기서 얻어야 하는 것 |
|---|---|---|
| 모듈 헤더 | **구조 작성** | 모델 라이브러리를 import하지 않는 이유 |
| `RerankProvider` | **설계 결정 확인** | 구현 없는 경계가 사 오는 것 |
| `_scores` | 점수 검증을 **직접 구현** | 재순위기 출력에 임베더와 같은 가드가 필요한 이유 |
| `rerank_hits` | 통과 분기를 **직접 구현** | 켠 상태와 끈 상태가 한 코드 경로를 공유해야 하는 이유 |

### 1. 모듈 헤더

#### `app/retrieval/rerank.py` 생성 — 모듈 헤더

**학습 행동 — 구조 작성:** docstring이 의존성 없는 경계라고 밝히고 있다. import 목록이 그 설명과 일치하는지 확인한다.

```python
"""Optional async reranking behind a dependency-free provider boundary."""

from abc import ABC, abstractmethod
from collections.abc import Sequence
import math
from numbers import Real

from app.retrieval.types import ChunkHit, sort_hits
```

**코드에서 꼭 볼 것**

- 모델 라이브러리도, HTTP 클라이언트도, `torch`도 import하지 않는다. 경계를 선언하는 데는 의존성이 필요 없으므로, 구현 없이 인터페이스만 두는 비용이 사실상 없다.

### 2. 구현이 없는 경계

#### `app/retrieval/rerank.py` 확장 — 공급자 경계

**학습 행동 — 설계 결정 확인:** 추상 메서드 하나다. 그 시그니처가 이미 무엇을 확정하고 있는지 따져 본다.

답은 cross-encoder를 확정하고 있다는 것이고, [튜토리얼 9](09-cross-encoder.md)의 M2.11에서 채워진다. 여기서 비워 두는 것이 그 도착 비용을 선택적 매개변수 하나로 만든다.

<!-- src: app/retrieval/rerank.py::RerankProvider -->
```python
class RerankProvider(ABC):
    """Provider boundary for scoring query/document pairs."""

    @abstractmethod
    async def score(self, query: str, documents: Sequence[str]) -> Sequence[float]:
        """Return one relevance score per document in caller order."""
```

**코드에서 꼭 볼 것**

- `Sequence[float]`은 공급자가 정상적으로 돌려줘야 하는 정적 계약이다. 아래 `_scores`의 `Real` 검사는 실제 반환값을 확인하는 런타임 방어이므로 그대로 남는다.
- **`score`는 문서 하나가 아니라 후보 배치 전체를 받는다.** 문서 단위 시그니처였다면 배치를 지원하는 공급자에게도 후보 수만큼의 순차 왕복을 강제한다.
- docstring의 "in caller order"가 결과를 식별자 없이 사용할 수 있게 하는 계약이다. 공급자는 `chunk_id`를 받지 않으므로 위치가 유일한 대응 수단이다.
- 아직 구현이 없는데도 메서드를 `async`로 선언한다. 지금 동기 메서드로 두면 앞으로 추가될 API 기반 공급자가 이벤트 루프를 막게 된다.

### 3. 재순위기가 돌려준 것을 검증한다

#### `app/retrieval/rerank.py` 확장 — 점수 검증

**학습 행동 — 점수 검증 구현:** 구조는 M2.2의 `validate_embeddings`와 같다. 작성한 뒤 이 함수가 검사하지 않는 것이 무엇인지 확인한다.

<!-- src: app/retrieval/rerank.py::_scores -->
```python
def _scores(values: Sequence[float], *, expected_count: int) -> list[float]:
    """Validate provider scores before replacing immutable hit scores."""
    if len(values) != expected_count:
        raise ValueError(f"reranker returned {len(values)} scores for {expected_count} hits")
    scores: list[float] = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, Real):
            raise ValueError("reranker returned a nonnumeric score")
        score = float(value)
        if not math.isfinite(score):
            raise ValueError("reranker returned a non-finite score")
        scores.append(score)
    return scores
```

**코드에서 꼭 볼 것**

- **점수의 범위를 강제하지 않는다.** 교차 인코더는 크기가 정해지지 않은 로짓을 반환할 수 있고, M2.1의 `Score` 타입도 유한성만 요구한다. 여기서 0–1로 제한하면 정상 동작하는 공급자를 거부하게 된다.
- 개수 검사는 2단계의 위치 계약을 지키는 장치다. 공급자가 점수를 하나 빠뜨리면 그 뒤의 모든 점수가 다른 문서에 붙는다.
- `bool` 거부와 `math.isfinite` 검사는 M2.2와 같은 규칙이다. NaN 점수는 오류를 내는 대신 `sort_hits`의 결과를 실행마다 바꾸기 때문이다.

### 4. 켠 상태와 끈 상태가 지나는 하나의 경로

이 함수에는 재채점을 하지 않는 분기가 있고, 그 분기가 이 파일의 목적이다.

M3는 재순위화가 검색 품질을 올리는지를 측정한다. 이 측정은 파이프라인을 두 번 실행해 비교하는 방식이므로, 두 실행이 공급자 유무 하나에서만 달라야 결과를 해석할 수 있다.

재순위화가 꺼져 있을 때 이 함수를 건너뛰는 구현이 더 짧아 보인다. 그러나 `rerank_hits`는 재채점 외에 정렬과 절단도 수행한다. 함수를 건너뛰면 끈 실행에는 켠 실행이 수행한 `sort_hits` 호출이 빠지고, 두 결과는 점수뿐 아니라 동점 순서에서도 달라진다. 그러면 측정된 차이에 재순위화의 효과와 정렬 차이가 함께 들어간다.

**`provider is None` 분기는 재순위화를 끈 실행이 켠 실행과 같은 정렬·절단 경로를 지나게 하는 대조군이다.**

#### `app/retrieval/rerank.py` 완성 — 선택적 재채점

**학습 행동 — 통과 분기 구현:** 가드와 두 분기를 모두 작성한다. `provider is None` 분기가 M3의 측정을 지키는 쪽이다.

<!-- src: app/retrieval/rerank.py::rerank_hits -->
```python
async def rerank_hits(
    query: str,
    hits: Sequence[ChunkHit],
    *,
    provider: RerankProvider | None = None,
    top_k: int = 5,
) -> list[ChunkHit]:
    """Optionally rescore top candidates and return deterministic top-k hits."""
    if not isinstance(query, str) or not query.strip():
        raise ValueError("rerank query must be nonempty")
    if top_k < 0:
        raise ValueError("rerank top_k must not be negative")
    if top_k == 0 or not hits:
        return []
    if provider is None:
        return sort_hits(hits)[:top_k]

    scores = _scores(
        await provider.score(query, [hit.index_text for hit in hits]),
        expected_count=len(hits),
    )
    rescored = [
        hit.model_copy(update={"score": score}) for hit, score in zip(hits, scores, strict=True)
    ]
    return sort_hits(rescored)[:top_k]
```

**코드에서 꼭 볼 것**

- 두 분기가 모두 `sort_hits(...)[:top_k]`로 끝난다. 껐을 때와 켰을 때가 **같은 코드 경로**를 지나므로 두 결과의 차이는 재순위화의 효과만 담는다. 껐을 때만 다른 함수를 지나면 M3의 비교값에 정렬 차이가 섞인다.
- 공급자에게 넘기는 텍스트는 `index_text`이고 `body`가 아니다. **재순위기는 검색이 실제로 매칭한 텍스트를 채점해야 하며, 근거 본문만 넘기면 문맥 헤더가 빠진 텍스트에 대한 점수가 된다.**
- `model_copy`는 여기서도 frozen 모델의 점수만 교체하고 출처 필드는 그대로 둔다. 재순위화는 순서를 바꾸고 근거는 바꾸지 않는다.
- `strict=True`를 붙인 `zip`은 `_scores`의 개수 검사에 이은 두 번째 가드다. 길이가 어긋난 채로 진행되면 점수가 다른 문서에 붙는다.

여기까지 작성하면 `app/retrieval/rerank.py`가 완성된다. 네 블록을 순서대로 이어 붙인 것이 그대로 체크포인트 파일이다.

정리하면 이런 경로다.

#### 파일 수정 없음 — 선택적 리랭킹 경로 읽기

```
query + candidate index_text  ──▶ RerankProvider present ──▶ validated scores ──▶ reordered top-k
                              └─▶ absent ──────────────────────────────────────▶ top-k unchanged
```

### 집중 테스트와 테스트가 지키는 계약

#### 실행 `tests/retrieval/test_06_rerank.py`

```bash
uv run pytest tests/retrieval/test_06_rerank.py -q
```

| 테스트가 깨뜨리는 값 | 지키는 계약 |
|---|---|
| 비어 있거나 문자열이 아닌 질의 | 재순위기에게 빈 것을 채점시키지 않는다. |
| 후보 수와 다른 점수 개수 | 점수가 올바른 문서에 붙어 있다. |
| NaN 또는 불리언 점수 | 순서가 비결정적으로 변할 수 없다. |
| 공급자에게 보낸 일부 근거 텍스트 | 재순위기가 검색이 매칭한 텍스트를 판정한다. |
| 공급자가 설정되지 않았을 때의 결과 | 끈 경로가 재순위화 이전 기준선과 동일하다. |

구현이 끝나면 입력 검증, 후보당 점수 하나, 유한성, 안정적인 동점 처리, 공급자가 없을 때의 동작을 검증하는 모든 재순위화 테스트가 통과해야 한다.

공급자가 일부만 담긴 텍스트를 받거나, 후보 수와 다른 개수의 점수를 반환하거나, 공급자를 설정하지 않았는데 결과가 달라지면 M2.6을 완료로 판단하지 않는다.

실패하면 공급자가 후보 순서대로 `index_text`를 받는지 확인한다. 수치가 아니거나, 유한하지 않거나, 개수가 어긋난 결과는 갱신된 hit를 만들기 전에 거부해야 한다.

### 여기까지 왔을 때 설명할 수 있어야 하는 것

다음 질문의 답은 앞에서 **굵게 표시한 핵심 문장**에 있다. 각 답을 해당 코드와 연결해 설명해 본다.

- **아무것도 구현하지 않는데 지금 경계를 만드는 이유는 무엇인가?**
  - **답:** 의존성 없는 교체 가능 인터페이스를 고정하면 지금 기본 경로에 모델 라이브러리를 묶지 않아도 된다. 현재 M3 행렬에는 재순위화 실험군이 없지만, 이 인터페이스가 향후 실험을 위한 확장 지점을 남긴다.
- **`score`가 문서 하나가 아니라 배치를 받는 이유는 무엇인가?**
  - **답:** 배치를 지원하는 공급자는 후보 전체를 한 번의 왕복으로 채점할 수 있지만, 문서 하나짜리 시그니처는 N번의 순차 호출을 강제한다.
- **재순위기 점수에 범위를 강제하지 않는 이유는 무엇인가?**
  - **답:** 올바른 재순위기도 크기 제한이 없는 로짓을 반환할 수 있으므로, 계약은 개수가 맞는 유한한 숫자인지만 요구한다.
- **끈 경로를 따로 두면 M3의 어블레이션 비교에 무슨 일이 생기는가?**
  - **답:** 현재 M3 어블레이션에는 재순위화 실험군이 없어 그런 비교가 아직 없다. 향후 재순위화 어블레이션에서 두 실험군이 같은 경로를 공유하지 않으면 별도 끄기 경로 때문에 정렬·절단 방식까지 달라질 수 있어 측정된 효과에 다른 동작이 섞인다.
- **공급자가 `index_text`를 받고 `body`를 받지 않는 이유는 무엇인가?**
  - **답:** 검색이 일치시킨 문맥 포함 텍스트와 같은 대상을 평가해야 한다. `body`만 채점하면 검색과 다른 증거를 평가하게 된다.

---

[← 이전: 검색 경로](03-retrieval-paths.md) · [모듈 개요](../03-build.md) · [다음 →: 서비스](05-service.md)
