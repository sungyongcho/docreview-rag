# M2.7 튜토리얼 5 — 조각들을 하나의 요청으로 묶기

앞의 여섯 단계에서 만든 모듈을 하나의 요청 경로로 조립한다. 이 단계에서 결정할 것은 세 가지다.

**선행 조건:** 튜토리얼 4의 `uv run pytest tests/retrieval/test_06_rerank.py -q`가 통과해야 한다.

## 세션은 호출자가 소유한다

**검색 서비스는 세션을 만들지 않고 호출자에게서 받는다.** M1.4의 `persist_seed_batch`가 트랜잭션이 열려 있지 않은 세션을 요구한 것과 같은 규칙이다.

이 규칙이 필요한 이유는 M5에 있다. FastAPI 요청 하나가 검색을 수행하고 그 결과를 기록까지 한다면, 두 작업이 같은 세션과 같은 트랜잭션 안에서 실행되어야 함께 커밋되거나 함께 롤백된다. 서비스가 내부에서 세션을 새로 만들면 호출자는 이 경계를 제어할 수 없다.

## 원시 점수는 밖으로 내보내지 않는다

`RetrievalResult`는 융합 결과와 함께 **각 구성 검색이 매긴 순위**를 반환한다. 점수는 반환하지 않고, 순위만 `chunk_id`의 나열로 전달한다.

디버깅에는 순위로 충분하다. 특정 청크가 벡터에서 2위, 어휘에서 8위였다는 사실만 알아도 융합 결과를 설명할 수 있다.

**원시 점수를 공개하면 호출자가 그 값으로 임계값이나 평균을 계산하게 되고, M2.5가 제거한 비교 불가능한 점수의 혼합이 서비스 밖에서 다시 만들어진다.** 그래서 점수는 경계 밖으로 내보내지 않는다.

## `R&D` 하나를 위한 정규화

이 규칙은 평가 과정에서 발견한 사례 하나를 처리한다. PostgreSQL 전문 검색은 `R&D`를 `r`과 `d`라는 두 어휘소로 분리한다. 두 토큰 모두 문서 전반에 흔해서 이 질의는 사실상 아무것도 걸러 내지 못한다.

반면 10-K 문서는 같은 개념을 "research and development"로 풀어 쓰는 경우가 훨씬 많다. 질문은 `R&D`로 들어오고 문서에는 풀어 쓴 표현만 있으므로 어휘 검색이 해당 청크를 찾지 못한다.

**정규화는 두 검색 경로가 갈라지기 전에 한 번만 수행한다.** 한쪽 경로에서만 정규화하면 두 목록이 서로 다른 질의에 대한 결과가 되고, 융합 결과를 설명할 수 없다.

> 이런 도메인별 정규화는 한번 시작하면 끝이 없다. 여기에는 측정으로 확인한 사례 하나만 넣었다. 규칙이 늘어난다면 그건 M3의 평가로 효과를 확인한 다음에 할 일이다.

## 무엇을 작성하고 어디를 직접 구현할까

M2.7은 파일 세 개를 작성한다. 서비스 모듈, 명령줄 진입점, 그리고 M2.1의 임시 공개 API를 대체하는 패키지 표면이다.

| 구간 | 학습 행동 | 여기서 얻어야 하는 것 |
|---|---|---|
| `app/retrieval/service.py` 헤더 | **구조 작성** | 나머지 모듈을 전부 import하는 유일한 모듈 |
| `_normalize_query` | 정규화를 **직접 구현** | 경로가 갈라지기 전에 도는 이유 |
| `ComponentRankings`와 `RetrievalResult` | **모델 선언 작성** | 공개해도 되는 출처 정보 |
| `retrieve` | 조합을 **직접 구현** | 세션 하나가 두 어댑터에 안전하게 닿는 방법 |
| `app/retrieval/__main__.py` | **구조 작성 후 진입 계약 검토** | 입력 계약, 출력 형태, 실패 경로 |
| `app/retrieval/__init__.py` | **기존 정의 교체** | M2가 완성한 공개 표면 |

## 1. 나머지를 전부 아는 모듈

### `app/retrieval/service.py` 생성 — 모듈 헤더

**학습 행동 — 구조 작성:** import 목록을 의존 방향 그림으로 읽는다. 다른 검색 모듈이 이 파일로 들어오고, 이 파일을 import하는 검색 모듈은 없다.

```python
"""Production composition for deterministic hybrid retrieval."""

from __future__ import annotations

import re
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DIM
from app.retrieval.embeddings import EmbeddingProvider, get_embedding_provider
from app.retrieval.hybrid import DEFAULT_RRF_K, hybrid_search
from app.retrieval.lexical import lexical_search
from app.retrieval.types import ChunkHit, RetrievalFilters
from app.retrieval.vector import vector_search
```

**코드에서 꼭 볼 것**

- 검색 모듈 여섯 개 중 다섯 개를 이 파일이 import하고, 그중 어느 것도 이 모듈을 import하지 않는다. 의존이 한 방향이므로 각 모듈을 따로 테스트할 수 있다.
- `DIM`을 여기서도 ORM 모델에서 가져온다. 그래서 이 모듈이 I/O를 시작하기 전에 공급자의 차원을 데이터베이스 열과 비교할 수 있다.

## 2. 경로가 갈라지기 전에 한 번 정규화한다

### `app/retrieval/service.py` 확장 — 질의 정규화

**학습 행동 — 정규화 구현:** 패턴과 치환 문자열을 작성한다. `\b` 경계와 `\s*`가 각각 어떤 입력까지 허용하는지 확인한다.

<!-- src: app/retrieval/service.py::RankedChunkId,_normalize_query -->
```python
RankedChunkId = Annotated[int, Field(gt=0)]
RESEARCH_AND_DEVELOPMENT = re.compile(r"\bR\s*&\s*D\b", flags=re.IGNORECASE)


def _normalize_query(query: str) -> str:
    """Expand the common R&D abbreviation for embedding and PostgreSQL FTS parity."""
    return RESEARCH_AND_DEVELOPMENT.sub("research development", query)
```

**코드에서 꼭 볼 것**

- `\s*`가 `&`의 양쪽에 붙어 `R & D`와 `R&D`를 함께 처리하고, `re.IGNORECASE`가 `r&d`까지 포함한다.
- 치환 문자열은 "research and development"가 아니라 "research development"다. 불용어 "and"는 FTS 사전이 어차피 제거하므로 넣어도 매칭이 달라지지 않는다.
- 패턴은 함수 안이 아니라 모듈 수준에서 한 번 컴파일한다. 이 함수는 모든 검색 요청에서 실행된다.

## 3. 공개해도 되는 출처 정보

### `app/retrieval/service.py` 확장 — 결과 모델

**학습 행동 — 모델 선언 작성:** 작은 모델 두 개를 작성한다. 확인할 것은 어떤 필드를 두지 않았는지다.

<!-- src: app/retrieval/service.py::ComponentRankings,RetrievalResult -->
```python
class ComponentRankings(BaseModel):
    """Ranked chunk identities from each retrieval component, without raw scores."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    vector: tuple[RankedChunkId, ...]
    lexical: tuple[RankedChunkId, ...]


class RetrievalResult(BaseModel):
    """Fused evidence plus inspectable rank-only component provenance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    hits: tuple[ChunkHit, ...]
    component_rankings: ComponentRankings
```

**코드에서 꼭 볼 것**

- `ComponentRankings`가 담는 값은 `chunk_id`뿐이다. 튜플 안의 위치가 곧 순위이므로 점수가 들어갈 자리 자체가 없다.
- `hits`는 리스트가 아니라 튜플이다. M2.5가 결정론적으로 정렬해 둔 결과를 호출자가 추가하거나 재정렬할 수 없다.
- `RankedChunkId`는 `gt=0` 제약을 재사용한다. 자리 채우기용 0이 출처 기록에 들어가지 못한다.

## 4. 조합

이 함수는 여든 줄이지만 새로 계산하는 것은 없다. 모듈 여섯 개를 정해진 순서로 호출할 뿐이다.

그래서 이 함수는 관문의 연속으로 읽는다. 먼저 잘못된 인자를 거부하고, 그다음 차원이 어긋난 공급자를 거부하고, 그다음 질의를 한 번 정규화한다. 그 세 관문을 통과한 뒤에야 클로저 두 개를 `hybrid_search`에 넘긴다.

확인할 부분은 클로저다. `hybrid_search`는 M2.5에서 세션과 임베딩 공급자를 모르는 함수로 작성했지만, 실제 검색에는 둘 다 필요하다. **두 값을 클로저에 담아 넘기므로, 데이터베이스를 모르는 융합 함수가 데이터베이스 질의를 실행하는 두 함수를 호출할 수 있다.**

### `app/retrieval/service.py` 완성 — retrieve 진입점

**학습 행동 — 조합 구현:** 검증 블록, 차원 검사, 두 클로저, 융합 호출 순으로 작성한다. 각 단계가 왜 그 위치에 있는지 설명할 수 있어야 한다.

<!-- src: app/retrieval/service.py::retrieve -->
```python
async def retrieve(
    session: AsyncSession,
    query: str,
    *,
    provider: EmbeddingProvider | None = None,
    k: int = 5,
    candidate_k: int | None = None,
    filters: RetrievalFilters | None = None,
    rrf_k: int = DEFAULT_RRF_K,
    reranker: RerankProvider | None = None,
    route_by_language: bool | None = None,
    lexical_ranker: LexicalRanker | None = None,
    bm25_k1: float | None = None,
    bm25_b: float | None = None,
    bm25_idf: BM25Idf | None = None,
) -> RetrievalResult:
    """Run vector then lexical search through one session and fuse their ranks.

    The component adapters close over the same ``AsyncSession``. They are awaited
    sequentially by ``hybrid_search`` because concurrent use of one session is unsafe.
    Component scores stay inside their native lanes; only ranked chunk identities are
    exposed beside the fused hits. An omitted candidate limit expands to
    ``max(20, 4 * k)`` at this production boundary.

    With no reranker the fused list is truncated to ``k`` by fusion itself, which is
    the M2.7 behaviour. Supplying one turns the request into two stages: fusion keeps
    the full candidate list, and the reranker rescores it and returns the top ``k``.
    Retrieval therefore goes wide cheaply first, then narrow expensively.

    Reranked hits carry cross-encoder scores rather than fusion scores. Component
    rankings are unaffected because they record what each retriever proposed, not
    what survived reranking.

    ``route_by_language`` resolves from ``Settings.query_language_routing`` when it is
    omitted. With routing on and a Korean query, the lexical component is skipped and
    ranking is vector-only. The lexical index is built with the ``english`` text-search
    configuration, so that component contributes nothing for Korean anyway; asking it
    anyway costs a database round trip and, worse, gives fusion a component whose
    silence is indistinguishable from a considered "no candidates". A skipped component
    is visible instead: ``ComponentRankings.lexical`` is empty, so the taken route can
    be read off the result rather than inferred from the configuration.
    """
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must not be blank")
    if k <= 0:
        raise ValueError("k must be positive")
    limit = max(20, 4 * k) if candidate_k is None else candidate_k
    if limit < k:
        raise ValueError("candidate_k must be at least k")
    if rrf_k <= 0:
        raise ValueError("rrf_k must be positive")

    settings = get_settings()
    active_lexical_ranker = settings.lexical_ranker if lexical_ranker is None else lexical_ranker
    active_bm25_k1 = settings.bm25_k1 if bm25_k1 is None else bm25_k1
    active_bm25_b = settings.bm25_b if bm25_b is None else bm25_b
    if active_lexical_ranker not in ("ts_rank_cd", "bm25"):
        raise ValueError("lexical_ranker must be 'ts_rank_cd' or 'bm25'")
    if active_bm25_k1 <= 0:
        raise ValueError("bm25_k1 must be positive")
    if not 0 <= active_bm25_b <= 1:
        raise ValueError("bm25_b must be between 0 and 1")
    active_bm25_idf = settings.bm25_idf if bm25_idf is None else bm25_idf
    if active_bm25_idf not in BM25_IDF_VARIANTS:
        raise ValueError("bm25_idf must be 'lucene' or 'robertson'")
    normalized_query = _normalize_query(query)
    active_routing = (
        settings.query_language_routing if route_by_language is None else route_by_language
    )
    skip_lexical = active_routing and detect_query_language(normalized_query) == "ko"

    active_provider = provider or get_embedding_provider()
    if active_provider.dimensions != DIM:
        raise ValueError(
            f"embedding provider dimension {active_provider.dimensions} does not match "
            f"database dimension {DIM}"
        )

    vector_hits: list[ChunkHit] = []
    lexical_hits: list[ChunkHit] = []

    async def vector_component(
        component_query: str,
        component_k: int,
        component_filters: RetrievalFilters,
    ) -> list[ChunkHit]:
        query_vector = await active_provider.embed_query(component_query)
        hits = await vector_search(
            session,
            query_vector,
            k=component_k,
            filters=component_filters,
        )
        vector_hits.extend(hits)
        return hits

    async def lexical_component(
        component_query: str,
        component_k: int,
        component_filters: RetrievalFilters,
    ) -> list[ChunkHit]:
        if skip_lexical:
            return []
        if active_lexical_ranker == "bm25":
            hits = await bm25_search(
                session,
                component_query,
                component_k,
                component_filters,
                k1=active_bm25_k1,
                b=active_bm25_b,
                idf=active_bm25_idf,
            )
        else:
            hits = await lexical_search(
                session,
                component_query,
                component_k,
                component_filters,
            )
        lexical_hits.extend(hits)
        return hits

    fused = await hybrid_search(
        normalized_query,
        limit if reranker is not None else k,
        filters,
        vector_search=vector_component,
        lexical_search=lexical_component,
        candidate_k=limit,
        rrf_k=rrf_k,
    )
    if reranker is not None:
        fused = await rerank_hits(
            normalized_query,
            fused,
            provider=reranker,
            top_k=k,
        )
    return RetrievalResult(
        hits=tuple(fused),
        component_rankings=ComponentRankings(
            vector=tuple(hit.chunk_id for hit in vector_hits),
            lexical=tuple(hit.chunk_id for hit in lexical_hits),
        ),
    )
```

**코드에서 꼭 볼 것**

- 모든 검증이 **I/O보다 먼저** 실행된다. 거부되는 요청은 임베딩 호출도 데이터베이스 질의도 발생시키지 않는다.
- 차원 검사는 공급자의 차원을 `DIM`과 맨 앞에서 비교한다. 이 검사가 없으면 차원이 어긋난 공급자가 pgvector 내부에서 원인을 파악하기 어려운 메시지로 실패한다.
- 두 클로저는 `session`을 인자로 받지 않고 포획한다. 호출자가 소유한 세션 하나가 두 어댑터에 전달되면서도 `hybrid_search`는 데이터베이스 타입을 모르는 상태로 남는다.
- `vector_hits`와 `lexical_hits`는 클로저의 **부수효과**로 채워진다. `hybrid_search`의 시그니처를 바꾸지 않고 구성 요소별 순위를 기록하는 방법이며, 대신 두 리스트는 융합이 두 호출을 모두 await한 뒤에만 읽어야 한다.
- `candidate_k`의 기본값 `max(20, 4 * k)`는 `hybrid_search`가 아니라 이 함수에 있다. 라이브러리 함수는 중립적인 기본값을 유지하고, 조정된 값은 운영 경계인 서비스가 정한다.
- `filters`는 변환 없이 그대로 넘긴다. `RetrievalFilters`가 M2.1에서 이미 정규화를 마쳤기 때문이다.

## 5. 명령줄 인수 경로

여기까지의 계약은 테스트가 검증한다. 이 파일은 사람이 직접 한 번 실행해 확인하기 위한 진입점이다.

두 검증이 확인하는 범위는 다르다. 통과한 테스트 스위트는 각 계약이 격리된 조건에서 성립한다는 것까지 보장한다. 느리거나 비용이 드는 구성 요소는 가짜 구현으로 대체되어 있다. 실제 질의가 실제 코퍼스와 실제 PostgreSQL을 거쳐 사람이 판단할 수 있는 근거를 반환하는지는 테스트가 확인하지 않는다.

인수 명령이 그 확인을 담당한다. 출력을 산문이 아니라 JSON으로 만드는 이유는 실행 결과가 비교하고 보고서에 인용하고 M3에 입력할 수 있는 기록이어야 하기 때문이다.

### `app/retrieval/__main__.py` 생성 — 모듈 헤더

**학습 행동 — 구조 작성:** 검색 모듈 가운데 `app.db.session`을 import해도 되는 첫 모듈이라는 점을 확인한다.

```python
"""Command-line acceptance path for the M2 retrieval service."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence
from dataclasses import asdict
import json
from typing import Literal

from app.config import Settings, get_settings
from app.db.session import Session
from app.retrieval.embeddings import (
    EmbeddingBackfillResult,
    embed_missing_chunks,
    get_embedding_provider,
)
from app.retrieval.service import RetrievalResult, retrieve

ProviderName = Literal["deterministic", "openai"]
```

**코드에서 꼭 볼 것**

- `app.db.session`을 여기서는 모듈 최상단에서 import한다. 같은 import를 함수 안으로 미뤘던 M1.4의 `seed.py`와 다르다. **`__main__.py`는 테스트가 import하지 않고 실행만 되는 파일이므로, import 시점에 엔진을 만들어도 데이터베이스가 필요 없는 테스트에 영향을 주지 않는다.**

## 6. 인자와 출력 형태

### `app/retrieval/__main__.py` 확장 — 인자와 페이로드

**학습 행동 — 구조 작성 후 진입 계약 검토:** 인자 정의는 기계적으로 작성한다. `_payload`는 점수를 공개하지 않는 규칙을 마지막으로 강제하는 함수다.

<!-- src: app/retrieval/__main__.py::arguments,_payload -->
```python
def arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse retrieval acceptance arguments."""
    parser = argparse.ArgumentParser(description="Run exact hybrid retrieval over PostgreSQL.")
    parser.add_argument("--query", required=True, help="Nonempty retrieval query.")
    parser.add_argument("-k", type=int, default=5, help="Number of fused hits to return.")
    parser.add_argument(
        "--candidate-k",
        type=int,
        help="Candidates per component; defaults to max(20, 4 * k).",
    )
    parser.add_argument(
        "--provider",
        choices=("deterministic", "openai", "sbert"),
        help=(
            "Override EMBEDDING_PROVIDER for this command. Stored embeddings are only "
            "comparable with query embeddings from the same provider, so switching "
            "requires re-embedding every chunk with --embed-missing on an empty column."
        ),
    )
    parser.add_argument(
        "--embed-missing",
        action="store_true",
        help="Fill null chunk embeddings before retrieval.",
    )
    parser.add_argument(
        "--rerank",
        action="store_true",
        help="Rescore fused candidates with a local cross-encoder before truncating to k.",
    )
    parser.add_argument(
        "--lexical-ranker",
        choices=("ts_rank_cd", "bm25"),
        help="Override LEXICAL_RANKER for this command.",
    )
    parser.add_argument(
        "--bm25-k1",
        type=float,
        help="Override BM25_K1; must be positive.",
    )
    parser.add_argument(
        "--bm25-b",
        type=float,
        help="Override BM25_B; must be between 0 and 1.",
    )
    parser.add_argument(
        "--bm25-idf",
        choices=("lucene", "robertson"),
        help="Override BM25_IDF; 'robertson' can score common terms negatively.",
    )
    parser.add_argument(
        "--rebuild-bm25-stats",
        action="store_true",
        help="Create missing schema objects and atomically rebuild BM25 term statistics.",
    )
    return parser.parse_args(argv)


def _provider_settings(settings: Settings, provider: ProviderName | None) -> Settings:
    """Return settings with an optional validated command-line provider override."""
    if provider is None:
        return settings
    return settings.model_copy(update={"embedding_provider": provider})


def _payload(
    *,
    query: str,
    provider: str,
    backfill: EmbeddingBackfillResult | None,
    result: RetrievalResult,
    lexical_ranker: LexicalRanker = "ts_rank_cd",
    bm25_k1: float = 1.2,
    bm25_b: float = 0.75,
    bm25_idf: BM25Idf = "lucene",
    bm25_stats: TermStatCounts | None = None,
) -> dict[str, object]:
    """Build stable JSON output while keeping component scores private."""
    return {
        "query": query,
        "provider": provider,
        "lexical_ranker": lexical_ranker,
        "bm25_k1": bm25_k1 if lexical_ranker == "bm25" else None,
        "bm25_b": bm25_b if lexical_ranker == "bm25" else None,
        "bm25_idf": bm25_idf if lexical_ranker == "bm25" else None,
        "bm25_stats": asdict(bm25_stats) if bm25_stats is not None else None,
        "backfill": asdict(backfill) if backfill is not None else None,
        "hits": [hit.model_dump(mode="json") for hit in result.hits],
        "component_rankings": result.component_rankings.model_dump(mode="json"),
    }
```

**코드에서 꼭 볼 것**

- `arguments`는 `argv`를 인자로 받고 `sys.argv`를 직접 읽지 않는다. 그래서 테스트가 이 함수를 직접 호출해 인자 해석을 검증할 수 있다.
- `_provider_settings`는 설정 객체를 변경하지 않고 `model_copy`로 사본을 만든다. 캐시된 `get_settings()` 객체는 프로세스가 끝날 때까지 그대로 유지된다.
- `_payload`는 `component_rankings`만 출력하고 구성 요소 점수는 출력하지 않는다. 점수를 공개하지 않는 규칙이 프로세스 밖으로 나가는 마지막 경계에서도 지켜진다.

## 7. 요청 하나를 실행한다

### `app/retrieval/__main__.py` 완성 — 실행 경로

**학습 행동 — 실행 순서 구현:** `_run`을 직접 작성하고, 백필은 세션 안에서 실행하는데 페이로드 생성은 왜 세션 밖에서 하는지 설명해 본다.

<!-- src: app/retrieval/__main__.py::_run,main -->
```python
async def _run(args: argparse.Namespace) -> dict[str, object]:
    """Run optional embedding backfill and one retrieval request."""
    settings = _provider_settings(get_settings(), args.provider)
    provider = get_embedding_provider(settings)
    lexical_ranker = args.lexical_ranker or settings.lexical_ranker
    bm25_k1 = settings.bm25_k1 if args.bm25_k1 is None else args.bm25_k1
    bm25_b = settings.bm25_b if args.bm25_b is None else args.bm25_b
    bm25_idf = args.bm25_idf or settings.bm25_idf
    if args.rebuild_bm25_stats:
        await bootstrap_schema(engine)
    async with Session() as session:
        backfill = None
        bm25_stats = None
        if args.rebuild_bm25_stats:
            bm25_stats = await backfill_term_stats(session)
        if args.embed_missing:
            backfill = await embed_missing_chunks(session, provider)
        result = await retrieve(
            session,
            args.query,
            provider=provider,
            k=args.k,
            candidate_k=args.candidate_k,
            reranker=CrossEncoderReranker() if args.rerank else None,
            lexical_ranker=lexical_ranker,
            bm25_k1=bm25_k1,
            bm25_b=bm25_b,
            bm25_idf=bm25_idf,
        )
    return _payload(
        query=args.query,
        provider=settings.embedding_provider,
        backfill=backfill,
        result=result,
        lexical_ranker=lexical_ranker,
        bm25_k1=bm25_k1,
        bm25_b=bm25_b,
        bm25_idf=bm25_idf,
        bm25_stats=bm25_stats,
    )


def main() -> None:
    """Run the M2 acceptance command and print machine-readable evidence."""
    print(json.dumps(asyncio.run(_run(arguments())), indent=2, ensure_ascii=False))
```

파일 마지막에 모듈 실행 가드를 덧붙인다. 이 두 줄이 있어야 `python -m app.retrieval`이 동작한다.

```python
if __name__ == "__main__":
    main()
```

**코드에서 꼭 볼 것**

- 세션 하나가 백필과 검색을 모두 감싼다. 호출자가 세션을 소유한다는 결정이 실제로 적용된 모습이다.
- **같은** `provider` 인스턴스를 백필과 `retrieve`에 함께 넘긴다. 문서와 질문이 한 모델로 임베딩된다는 M2.2의 첫 번째 조건이 최상위 진입점에서 지켜진다.
- `_payload`는 `async with` 블록이 닫힌 뒤에 만들어진다. 이 위치는 페이로드의 어떤 필드도 세션에서 지연 로딩되지 않는다는 것을 보여준다.
- `ensure_ascii=False`는 filing 텍스트를 이스케이프하지 않고 그대로 출력한다.

## 8. 완성된 공개 표면

### `app/retrieval/__init__.py` 생성 또는 교체 — M2 공개 API

**학습 행동 — 기존 정의 교체:** M2.1에서 작성한 임시 초기화 파일을 이것으로 바꾼다.

<!-- file: app/retrieval/__init__.py -->
```python
"""Public contracts and production entry points for the retrieval milestone."""

from app.retrieval.bm25 import TermStatCounts, backfill_term_stats, bm25_search
from app.retrieval.cross_encoder import CrossEncoderReranker
from app.retrieval.embeddings import (
    DeterministicEmbeddingProvider,
    EmbeddingBackfillResult,
    EmbeddingProvider,
    OpenAIEmbeddingProvider,
    embed_missing_chunks,
    get_embedding_provider,
)
from app.retrieval.hybrid import DEFAULT_RRF_K, hybrid_search, rrf_fuse
from app.retrieval.lexical import lexical_search
from app.retrieval.rerank import RerankProvider, rerank_hits
from app.retrieval.sbert import SentenceTransformerEmbeddingProvider
from app.retrieval.service import ComponentRankings, RetrievalResult, retrieve
from app.retrieval.types import ChunkHit, ChunkKind, RetrievalFilters, sort_hits
from app.retrieval.vector import vector_search

__all__ = [
    "DEFAULT_RRF_K",
    "ChunkHit",
    "ChunkKind",
    "ComponentRankings",
    "CrossEncoderReranker",
    "DeterministicEmbeddingProvider",
    "EmbeddingBackfillResult",
    "EmbeddingProvider",
    "OpenAIEmbeddingProvider",
    "RerankProvider",
    "RetrievalFilters",
    "RetrievalResult",
    "SentenceTransformerEmbeddingProvider",
    "TermStatCounts",
    "backfill_term_stats",
    "bm25_search",
    "embed_missing_chunks",
    "get_embedding_provider",
    "hybrid_search",
    "lexical_search",
    "rerank_hits",
    "retrieve",
    "rrf_fuse",
    "sort_hits",
    "vector_search",
]
```

이 마지막 교체가 M2.1의 임시 초기화 파일을 없앤다. 이제 패키지가 완성된 검색 표면과 일치한다.

**공개하지 않은 이름**도 함께 확인한다. `_normalize_query`, `_filtered_statement`, `_filter_predicates`, `validate_embeddings`, `rrf_fuse`의 내부 도우미가 여기에 해당한다. 밑줄로 시작하는 이름은 내부 구현이고, 이후 모듈이 의존해도 되는 표면은 이 목록으로 한정된다.

## 집중 테스트와 테스트가 지키는 계약

```bash
uv run pytest tests/retrieval/test_07_service.py -q
```

| 테스트가 깨뜨리는 값 | 지키는 계약 |
|---|---|
| 첫 임베딩 호출 뒤로 옮긴 검증 | 거부되는 요청이 I/O를 수행하지 않는다. |
| `DIM`과 차원이 다른 공급자 | 불일치가 명확한 메시지로 일찍 실패한다. |
| 서비스 안에서 만든 세션 | 호출자가 트랜잭션 제어권을 유지한다. |
| 두 구성 요소에 도달한 서로 다른 질의 | 두 목록이 같은 질문에 답한다. |
| 동시에 호출된 구성 검색 | 하나의 `AsyncSession`을 동시에 쓰지 않는다. |
| 출력에 포함된 구성 요소 점수 | 비교 불가능한 점수를 다시 공개하지 않는다. |

구현이 끝나면 I/O 이전 검증, 단일 세션 소유, 순차 호출 순서, `R&D` 정규화, RRF 조합, 구성 요소 순위, CLI 출력을 검증하는 모든 서비스 테스트가 통과해야 한다.

검증이 I/O 뒤로 밀리거나, 세션이 교체되거나, 호출 순서가 바뀌거나, 두 경로가 서로 다른 질의를 받거나, 원시 구성 요소 점수가 출력에 포함되면 M2.7을 완료로 판단하지 않는다.

실패하면 가장 먼저 실패한 목 단언을 경계로 삼아 확인한다. 검증이 `embed_query` 호출보다 앞서는지, 두 검색이 같은 정규화된 질의와 같은 필터를 받는지, 호출자가 소유한 `AsyncSession`이 교체되거나 닫히지 않는지를 순서대로 본다.

## 여기까지 왔을 때 설명할 수 있어야 하는 것

다음 질문의 답은 앞에서 **굵게 표시한 핵심 문장**에 있다. 각 답을 해당 코드와 연결해 설명해 본다.

- **서비스가 자기 세션을 만들면 M5가 무엇을 잃는가?**
  - **답:** 검색을 호출자가 이미 가진 세션에 참여시킬 수 없으므로, M5가 요청 단위의 트랜잭션과 수명 주기를 통제할 수 없게 된다.
- **순위는 공개하면서 점수는 공개하지 않는 이유는 무엇인가?**
  - **답:** 순위 위치는 검색기 사이에서도 같은 뜻이지만 원시 점수는 그렇지 않다. 점수를 공개하면 잘못된 임계값, 평균, 직접 비교에 쓰일 수 있다.
- **두 경로 중 한쪽만 정규화된 질의를 보면 무엇이 깨지는가?**
  - **답:** 두 구성 목록이 서로 다른 질문에 답하게 되어, 융합 결과와 그 결과가 나온 이유를 올바르게 설명할 수 없다.
- **`hybrid_search`가 모르는 채로 세션 하나가 두 어댑터에 닿는 방법은 무엇인가?**
  - **답:** `retrieve`가 호출자 소유 세션을 캡처한 두 어댑터 클로저를 만든 뒤, 데이터베이스를 모르는 `hybrid_search`에 그 함수들을 넘긴다.
- **`__main__.py`는 `app.db.session`을 모듈 수준에서 import해도 되는데 `seed.py`는 안 되는 이유는 무엇인가?**
  - **답:** 오프라인 테스트도 `app.retrieval.__main__`을 import하므로 테스트가 전혀 import하지 않는다는 설명은 틀리다. `app.db.session`을 import하면 엔진 객체는 만들지만 연결은 열지 않는다. `seed.py`는 더 넓게 재사용되는 라이브러리 경계라 그 설정조차 뒤로 미룬다.

---

[← 이전: 융합](04-fusion.md) · [모듈 개요](../03-build.md) · [다음 →: 라이브 PostgreSQL](06-live-postgres.md)
