# M3.4 튜토리얼 6 — 측정 결과를 담을 그릇

`ablation.py`가 실험군을 정의했다. 튜토리얼 5는 어떤 실험을 어떤 순서로 돌리고 비교 표가 어떤 모양인지까지 정했지만, 한 가지 질문은 의도적으로 남겨 두었다. 실행이 끝난 뒤에도 평가된 사례 하나가 어떤 증거를 계속 갖고 있어야 하는가. 이 문서는 실험 한 번이 **무엇을 남기는지** 정하는 것으로 그 질문에 답한다.

실행 로직은 다음 문서에 있고, 여기서 작성하는 것은 레코드 선언과 작은 헬퍼다. 다만 이 선언이 나중에 평가 결과를 읽는 사람이 확인할 수 있는 정보의 범위를 그대로 결정한다. 이 계층이 얇으면 실패는 조용히 온다. 실행은 끝나고 집계값은 표에 실리지만, 몇 달 뒤 어느 질문이 퇴행했는지, 기대한 증거 대신 무엇이 검색됐는지는 아무도 말할 수 없다. 평균을 계산한 순간 증거를 버렸기 때문에, 어떤 사례도 다시 감사할 수 없다.

이 레코드 계층이 세우는 불변조건은 하나다. **아티팩트 안의 모든 집계값은 같은 아티팩트 안의 사례별 레코드에서 다시 계산될 수 있어야 한다.** 재현율, 적중률, MRR, 지연 통계 전부가 추가 입력 없이 저장된 사례들로부터 나와야 한다. 3절에서 이 문장을 커밋된 아티팩트에 대해 실행 가능한 검증으로 바꾼다.

**선행 조건:** 튜토리얼 5의 `app/evals/ablation.py` 작성을 마친 상태여야 한다. 이 문서는 `retrieval_eval.py`의 앞부분만 만들며, 튜토리얼 5의 집중 테스트는 실행 함수까지 완성하는 튜토리얼 7 뒤에 실행한다. 이 문서의 레코드 계층 테스트는 튜토리얼 8에서 함께 돈다.

### 집계 점수만 남기면 재현할 수 없다

각 실험군의 결과가 지표로 집계되기 **전에**, 사례별 검색 결과 전체와 지연 시간을 원시 JSON으로 기록한다.

**집계값만 — 커밋된 structure-1200-lexical-bm25 실험군의 재현율 0.5208만 — 남기면 채점된 24개 질문 중 어느 것이 실패했는지, 그 자리에 대신 무엇이 검색됐는지, 왜 그랬는지를 확인할 수 없다.** 같은 실행을 다시 하면 된다고 볼 수도 있지만, 공급자나 코퍼스, 코드가 바뀐 뒤에는 그 숫자가 재현되지 않고, 옛 실행의 증거는 영영 사라진다.

그래서 측정값을 만든 원시 근거를 측정값과 함께 저장한다. 파일 이름의 UTC 타임스탬프가 실행을 구분하므로 새 측정이 옛 측정을 덮어쓰는 일이 없고, 어느 실행이 최신인지는 디렉터리 목록만으로 읽힌다.

### 28개를 기록하고 24개를 채점한다

`evaluate_retriever()`는 골든 사례 28개를 **전부 돌리고 기록하되** 양성 24개만 채점한다.

M3.1에서 나눈 구분이 여기서 유지된다. `absent` 4개는 검색 재현율로 측정할 대상이 아니다. 검색기가 어떤 span을 돌려줘도 점수를 얻을 수 없는 질문이기 때문이다. 떠오르는 대안 둘은 모두 정보를 잃는다. 0점으로 채점하면 이길 수 없는 질문이 매크로 평균에 섞여 들어간다. 0점 네 개가 섞이면 커밋된 bm25 실험군의 재현율은 0.5208이 아니라 0.4464로 찍히고, 검색기는 애초에 이길 수 없던 질문 때문에 벌점을 받는다. 그렇다고 실행에서 아예 빼면 코퍼스에 답이 없을 때 검색기가 실제로 무엇을 돌려줬는지가 어디에도 남지 않아, 없다고 답할 수 있는지를 분석할 데이터가 사라진다. 그래서 **실행하고 기록하되 점수 집계에서는 제외한다.**

28개를 전부 실행하는 데는 조용한 이유가 하나 더 있다. 시도한 사례마다 지연 표본이 하나씩 나온다. 이 문서에서 만드는 지연 요약은 24개가 아니라 28개 측정을 서술하며, 5절의 백분위 산술이 이 개수에 의존한다.

### 무엇을 작성하고 어디를 직접 구현할까

`app/evals/retrieval_eval.py`의 앞부분을 다섯 단계로 작성한다. 실행 함수는 다음 문서에서 만든다.

| 구간 | 학습 행동 | 여기서 얻어야 하는 것 |
|---|---|---|
| 모듈 헤더와 예산 상수 | **구조 작성** | 이 파일이 M1·M2·M3 전부에 의존한다는 것 |
| 출처·지연·사례 레코드 | **레코드 선언 작성** | 측정과 함께 남겨야 하는 것 |
| `RetrievalEvaluation` | **필드 매핑 작성** | 아티팩트 JSON의 모양 |
| `_latency_summary` | 백분위 계산을 **직접 구현** | 표본이 적을 때 p95가 무엇인가 |
| `_golden_provenance` | 균일성 검사를 **직접 구현** | 검토 상태가 섞이면 안 되는 이유 |

### 1. 모듈 헤더와 예산 상수

#### `app/evals/retrieval_eval.py` 생성 — 모듈 헤더

**학습 행동 — 구조 작성:** import 목록을 확인한다. 이 파일이 지금까지 만든 거의 모든 모듈을 호출한다.

```python
"""Run source-grounded retrieval evaluations and measure M3 latency budgets."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import json
import math
from pathlib import Path
import time
from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import LexicalRanker, Settings, get_settings
from app.evals.loader import DEFAULT_GOLDEN_PATH, load_golden_cases
from app.evals.regression import (
    BaselineComparison,
    RegressionTolerances,
    compare_against_baseline,
    latest_comparable_baseline,
    persist_eval_result,
    serialize_config,
)
from app.evals.scoring import CaseScore, SuiteScore, score_case, score_suite
from app.evals.types import GoldenCase
from app.ingestion.chunk import ChunkConfig, chunk_filing
from app.ingestion.seed import SeedBatch, build_seed_batch, load_manifest, persist_seed_batch
from app.retrieval.bm25 import backfill_term_stats, bm25_search
from app.retrieval.embeddings import (
    EmbeddingProvider,
    embed_missing_chunks,
    get_embedding_provider,
)
from app.retrieval.hybrid import DEFAULT_RRF_K
from app.retrieval.lexical import lexical_search
from app.retrieval.service import retrieve
from app.retrieval.types import ChunkHit, RetrievalFilters
from app.retrieval.vector import vector_search
```

**코드에서 꼭 볼 것**

- M1의 `chunk_filing`과 `persist_seed_batch`, M2의 검색 계층, M3의 로더·채점·회귀가 이 파일에 모인다. 평가 계층은 파이프라인 전체를 다시 조립해 실행한다. 계층별 로컬 테스트가 잘 합쳐지리라 믿는 대신, 실험 하나가 청킹을 바꾸고 그 효과를 끝까지 측정할 수 있는 것은 정확히 이 재조립 덕분이다.
- `NullPool`을 가져온다. 임시 테이블은 연결에 묶여 있으므로, 연결을 재사용하는 풀은 앞 실행의 임시 코퍼스를 다음 실행에 흘려보낸다. 이 성질에 의존하는 격리는 튜토리얼 8에서 만든다.

#### `app/evals/retrieval_eval.py` 확장 — 예산 상수

**학습 행동 — 설정 스키마 정의:** 예산 값 세 개를 설정이 아니라 코드에 두는 이유를 확인한다.

<!-- src: app/evals/retrieval_eval.py::RetrievalStrategy,RAW_ARTIFACT_SCHEMA_VERSION -->
```python
type RetrievalStrategy = Literal["lexical", "vector", "hybrid"]
type Retriever = Callable[[str, int], Awaitable[Sequence[ChunkHit]]]
type Clock = Callable[[], int]

INDEXING_BUDGET_SECONDS = 300.0
QUERY_BUDGET_COUNT = 200
QUERY_BUDGET_SECONDS = 90.0
RAW_ARTIFACT_SCHEMA_VERSION = 1
```

**코드에서 꼭 볼 것**

- 예산을 설정이 아니라 모듈 상수로 둔다. 실행할 때마다 값을 바꿀 수 있으면 한도를 넘길 때마다 한도를 올리게 되고, 초록불이 느려짐을 막는 대신 느려짐을 따라간다. 완화를 코드 변경으로 만들어야 그 결정이 리뷰를 거치고 이력에 남는다.
- `RAW_ARTIFACT_SCHEMA_VERSION`을 아티팩트에 함께 저장한다. 나중에 페이로드 모양을 바꾸고 버전을 올려도, 이전 파일을 읽는 코드가 그 파일의 형식을 판단할 근거를 가진다. 이 버전이 하지 **않는** 일 — 기준선을 가르는 일 — 은 3절에서 다시 짚는 날카로운 모서리다.

### 2. 측정과 함께 남기는 것

#### `app/evals/retrieval_eval.py` 확장 — 출처·지연·사례 레코드

**학습 행동 — 레코드 선언 작성:** `CaseEvaluation.score`의 타입에 `| None`이 붙은 이유를 확인한다.

<!-- src: app/evals/retrieval_eval.py::GoldenProvenance,CaseEvaluation -->
```python
@dataclass(frozen=True, slots=True)
class GoldenProvenance:
    """Review provenance shared by every case in one strict golden suite."""

    total_cases: int
    scored_positive_cases: int
    unscored_absent_cases: int
    curation_status: str
    approval_status: str
    human_verified: bool


@dataclass(frozen=True, slots=True)
class LatencySummary:
    """Measured sequential retrieval latency in milliseconds."""

    query_count: int
    total_ms: float
    mean_ms: float
    p50_ms: float
    p95_ms: float
    max_ms: float


@dataclass(frozen=True, slots=True)
class CaseEvaluation:
    """Raw hits, latency, and optional positive-case retrieval score."""

    golden: GoldenCase
    latency_ms: float
    hits: tuple[ChunkHit, ...]
    score: CaseScore | None
```

**코드에서 꼭 볼 것**

- `GoldenProvenance`는 `total_cases`와 `scored_positive_cases`를 **모두** 저장한다. 28개를 실행하고 24개를 채점했다는 사실이 결과 파일에 남는다.
- `human_verified`가 출처 레코드에 들어 있다. 평가 수치를 인용하는 사람이 이 데이터가 사람 검증을 거치지 않았다는 것을 결과 파일에서 바로 확인한다.
- **`CaseEvaluation.score`의 타입은 `CaseScore | None`이다. absent 사례에는 0점이 아니라 `None`을 저장한다. 0점은 찾지 못했다는 뜻이고 채점 대상이 아니라는 뜻은 아니므로, 0으로 저장하면 두 상태가 같은 값이 된다.** M3.1에서 만든 구분이 여기까지 이어진다.
- `hits`를 튜플로 그대로 저장한다. 재현율뿐 아니라 그 자리에 무엇이 검색됐는지가 함께 남는다.

> **개념 — 레코드는 요약이 아니라 증거다**
>
> 이 계층의 단위는 사례 하나이고, 사례 레코드는 네 가지를 담는다. 물었던 그대로의 질문, 검색기가 돌려준 전부, 시도에 걸린 시간, 그리고 채점이 정의되는 경우에만 붙는 판정. 이 네 가지가 있어야 나중에 읽는 사람이 재실행 없이 그 사례를 다시 심리할 수 있다. 하나라도 빠지면 답할 수 없는 질문의 부류가 생긴다. 히트가 없으면 미스를 진단할 수 없고, 지연 시간이 없으면 느려진 실행의 원인을 어느 사례에 돌릴 수 없으며, 질문을 얼려 두지 않으면 정답 파일이 나중에 움직였는지 판별할 수 없다.
>
> 점수가 선택적인 것은 우연이 아니라 타입의 결정이다. 가져올 것이 없으면 검색 품질은 정의되지 않는다. absent 사례에는 맞는 span 자체가 없으므로 어떤 검색 결과도 그 사례에 대해 옳거나 그를 수 없다. 시스템이 없다고 *말할* 수 있는지는 실재하는 측정이지만, 그것은 여기가 아니라 답변 계층에서 하는 다른 측정이다. 점수를 비워 두는 것은 이 질문이 지표의 정의역 밖이었다는 뜻이고, 0점을 저장하는 것은 측정했는데 실패했다는 뜻이 되어 거짓이 된다.

> **개념 — 정답지 상태가 붙지 않은 숫자는 과대 주장을 부른다**
>
> 이 시스템의 모든 지표는 정답지에 상대적이고, 정답지에는 검토 상태가 있다. 커밋된 골든셋은 에이전트가 큐레이션한 것이다. 기계가 span을 코퍼스 바이트와 대조해 검증했지만, 사람이 승인한 사례는 단 하나도 없고, 파일 스스로 그렇게 말한다. 이 상태 없이 보고서에 옮겨 적힌 재현율 숫자는 조용히 스스로를 승격시킨다. 숫자와 함께 여행하며 아니라고 말해 줄 것이 없으므로, 옮겨 말하는 사이에 기계 검증이 사람 승인으로 바뀐다.
>
> 검토 출처를 아티팩트 옆이 아니라 안에 싣는 이유가 이것이다. 결과 파일 스스로 몇 개를 실행했고 몇 개를 채점했으며 사람 검증을 거친 사례가 없다는 것을 말한다. 숫자를 인용하는 사람이 같은 파일 안에서 단서 조항을 함께 들고 있으므로, 미승인 정답지로 평가한 스위트가 승인된 벤치마크로 오인될 수 없다.

세 상태 필드 뒤에는 수명 주기가 있다. 이 스위트는 M3.5가 게이팅하는 에이전트 큐레이션 흐름이 조립했으므로 커밋된 모든 사례가 `agent-curated`와 `pending-author-approval`을 달고 있다. 그 상태의 근거인 기계 검증은 `data/golden/REVIEW.md`에 기록되어 있고, 사례를 대기 상태에서 꺼내는 것은 오직 저자만이 검토된 변경으로 할 수 있다. 현재 골든 타입은 이 값들을 리터럴로 박아 두어, 의도적인 타입 변경 없이는 승인된 상태를 표현할 수조차 없다. `_golden_provenance`는 스위트의 균일한 상태를 아티팩트로 복사할 뿐, 상태를 전진시키지 않는다.

### 3. 아티팩트 JSON의 모양

#### `app/evals/retrieval_eval.py` 확장 — 평가 결과

**학습 행동 — 필드 매핑 작성:** `metric_values()`가 품질 지표와 지연 시간을 같은 딕셔너리에 담는 이유를 확인한다.

<!-- src: app/evals/retrieval_eval.py::RetrievalEvaluation -->
```python
@dataclass(frozen=True, slots=True)
class RetrievalEvaluation:
    """One complete, artifact-ready retrieval experiment."""

    suite: str
    recorded_at: datetime
    config: dict[str, Any]
    provenance: GoldenProvenance
    score: SuiteScore
    latency: LatencySummary
    cases: tuple[CaseEvaluation, ...]

    def metric_values(self) -> dict[str, float]:
        """Return quality and latency values suitable for ``eval_results``."""
        return {
            "recall_at_k": self.score.recall_at_k,
            "hit_rate_at_k": self.score.hit_rate_at_k,
            "mrr": self.score.mrr,
            "query_count": float(self.latency.query_count),
            "total_latency_ms": self.latency.total_ms,
            "mean_latency_ms": self.latency.mean_ms,
            "p95_latency_ms": self.latency.p95_ms,
        }

    def artifact_payload(self) -> dict[str, Any]:
        """Return the stable raw JSON payload for this measured run."""
        return {
            "schema_version": RAW_ARTIFACT_SCHEMA_VERSION,
            "suite": self.suite,
            "recorded_at": _utc_text(self.recorded_at),
            "config": self.config,
            "golden_provenance": asdict(self.provenance),
            "metrics": {
                "k": self.score.k,
                "scored_case_count": self.score.case_count,
                **self.metric_values(),
            },
            "latency": asdict(self.latency),
            "cases": [
                {
                    "golden": case.golden.model_dump(mode="json"),
                    "latency_ms": case.latency_ms,
                    "hits": [hit.model_dump(mode="json") for hit in case.hits],
                    "score": asdict(case.score) if case.score is not None else None,
                }
                for case in self.cases
            ],
        }
```

**코드에서 꼭 볼 것**

- `metric_values()`는 재현율과 지연 시간을 **한 딕셔너리에** 담는다. 이 값이 `eval_results`에 그대로 저장되므로, 나중에 조회하면 품질과 비용을 함께 볼 수 있다.
- 다만 M3.3의 `compare_against_baseline`은 그중 앞의 세 지표만 게이팅한다. 지연 시간은 저장하되 방향을 정의하지 않은 값으로 자동 판정하지 않는다.
- `artifact_payload()`는 `model_dump(mode="json")`을 사용한다. `datetime`과 튜플이 JSON에 바로 쓸 수 있는 형태로 변환된다.
- 사례마다 `golden`을 다시 저장한다. **정답 파일은 이후에 바뀔 수 있으므로, 이 실행이 무엇을 정답으로 사용했는지는 아티팩트 안에 함께 남아야 확인할 수 있다.**

실행 아티팩트는 바로 이 페이로드에서 나온다. 튜토리얼 7의 `write_evaluation_artifact`가 정확히 이 딕셔너리를 디스크에 직렬화하며, `data/eval_runs/` 아래에 커밋된 실험군 파일들 — 2026-08-12 실행의 6개, 2026-08-24 실행의 10개 — 이 측정 순간에 동결된 이 페이로드다. 각 실행은 그 옆에 예산 파일 하나도 남기는데, 그것은 모양이 다른 별도의 레코드다. 한번 쓴 아티팩트는 아무도 수정하지 않는다. 새 실행은 옛 파일 옆에 새 타임스탬프 파일을 쓰고, 마일스톤 평가 보고서는 비교 표의 모든 행을 근거로서 이 파일들 중 하나로 곧장 연결한다.

> **개념 — 결정론적 직렬화가 아티팩트를 diff 가능하게 만든다**
>
> 아티팩트는 나란히 놓을 때 가장 쓸모 있다. 두 실행 사이에 무엇이 바뀌었는가는 파일을 diff하는 것으로 답할 수 있어야 한다. 그러려면 직렬화가 결정론적이어야 한다. 같은 데이터면 같은 바이트가 나와야 한다. 그래서 튜토리얼 7의 기록 함수는 키를 정렬하고 들여쓰기를 고정해, 딕셔너리의 임의 순서가 변경으로 위장할 수 없게 만들고, 아티팩트마다 함께 찍히는 스키마 버전이 페이로드 모양 자체가 움직인 시점을 기록한다.
>
> 정직한 한계가 하나 있다. 스키마 버전은 아티팩트를 서술하지 실험을 서술하지 않는다. 기준선 비교는 스위트와 바이트 단위로 동일한 config로 기준을 고르는데, 버전 필드는 config 밖에 있다. 버전을 올려도 옛 결과와 새 결과가 갈라지지 않고 비교도 멈추지 않는다. 기준선을 가르는 것은 config 안에 기록된 것뿐이다. 이것이 튜토리얼 4의 계약이고, 여기 있는 버전 숫자는 과신하기 쉽다.

도입부의 불변조건은 이제 커밋된 아티팩트로 검증할 수 있다. 모든 집계값이 같은 파일의 사례별 레코드에서 나온다.

```bash
python3 -c "import json; d=json.load(open('data/eval_runs/20260824T203336Z-structure-1200-lexical-bm25.json')); s=[c['score'] for c in d['cases'] if c['score'] is not None]; print(sum(x['recall_at_k'] for x in s)/len(s) == d['metrics']['recall_at_k'], sum(c['latency_ms'] for c in d['cases']) == d['latency']['total_ms'])"
```

두 비교 모두 `True`를 출력한다. 저장된 재현율은 저장된 사례 재현율 24개의 평균과 정확히 같고, 저장된 총 지연 시간은 저장된 사례별 지연 시간 28개의 합과 정확히 같다.

### 4. 표본이 적을 때의 백분위

#### `app/evals/retrieval_eval.py` 확장 — 예산 측정 레코드

**학습 행동 — 레코드 선언 작성:** `passed`가 계산 결과가 아니라 레코드에 저장되는 값이라는 점을 확인한다.

<!-- src: app/evals/retrieval_eval.py::QueryBudgetMeasurement,PersistedEvaluation -->
```python
@dataclass(frozen=True, slots=True)
class QueryBudgetMeasurement:
    """Wall-clock evidence for the fixed 200-query retrieval budget."""

    query_count: int
    total_seconds: float
    budget_seconds: float
    passed: bool
    mean_ms: float
    p50_ms: float
    p95_ms: float
    max_ms: float


@dataclass(frozen=True, slots=True)
class IndexingBudgetMeasurement:
    """Wall-clock evidence for one isolated corpus indexing configuration."""

    target_text_chars: int
    document_count: int
    chunk_count: int
    embedding_provider: str
    total_seconds: float
    budget_seconds: float
    passed: bool


@dataclass(frozen=True, slots=True)
class PersistedEvaluation:
    """Database identity and optional comparison with the preceding baseline."""

    result_id: int
    baseline_id: int | None
    comparison: BaselineComparison | None
```

**코드에서 꼭 볼 것**

- `budget_seconds`를 결과와 함께 저장하고, `passed`도 함께 저장한다. 떠오르는 대안 — 저장된 총 시간과 지금의 예산으로 판정을 나중에 다시 계산하는 것 — 은 예산이 바뀌는 날 이력을 조용히 다시 쓴다. 둘을 함께 동결해야 그 실행을 어떤 한도로 판정했는지가 파일에 남는다.
- `IndexingBudgetMeasurement`는 `document_count`와 `chunk_count`를 함께 저장한다. 한도를 넘겼을 때 코퍼스가 커진 것인지 코드가 느려진 것인지 구분할 수 있다.
- `PersistedEvaluation.comparison`의 타입에 `| None`이 붙는다. 비교할 기준선이 없는 첫 실행과, 비교했지만 회귀가 없었던 실행이 서로 다른 값으로 남는다. 둘을 한 값으로 뭉개면 맨 처음 실행이 검증된 실행으로 통하게 된다.

### 5. 백분위와 출처 균일성

#### `app/evals/retrieval_eval.py` 확장 — 헬퍼

**학습 행동 — 백분위 계산 구현:** `percentile`을 직접 구현하고, 표본이 28개일 때 p95가 몇 번째 값인지 계산해 본다.

<!-- src: app/evals/retrieval_eval.py::_utc_text,_golden_provenance -->
```python
def _utc_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("recorded_at must be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _canonical_config(config: Mapping[str, Any]) -> dict[str, Any]:
    return json.loads(serialize_config(config))


def _latency_summary(values: Sequence[float]) -> LatencySummary:
    if not values:
        raise ValueError("latency measurements must not be empty")
    if any(not math.isfinite(value) or value < 0 for value in values):
        raise ValueError("latency measurements must be finite and nonnegative")
    ordered = sorted(values)

    def percentile(fraction: float) -> float:
        position = max(0, math.ceil(fraction * len(ordered)) - 1)
        return ordered[position]

    total = sum(values)
    return LatencySummary(
        query_count=len(values),
        total_ms=total,
        mean_ms=total / len(values),
        p50_ms=percentile(0.50),
        p95_ms=percentile(0.95),
        max_ms=ordered[-1],
    )


def _golden_provenance(cases: Sequence[GoldenCase]) -> GoldenProvenance:
    positive_count = sum(bool(case.answers) for case in cases)
    if positive_count == 0:
        raise ValueError("evaluation requires at least one positive golden case")
    curation_statuses = {case.curation_status for case in cases}
    approval_statuses = {case.approval_status for case in cases}
    verification_states = {case.human_verified for case in cases}
    if len(curation_statuses) != 1 or len(approval_statuses) != 1:
        raise ValueError("golden review provenance must be uniform within a suite")
    if verification_states != {False}:
        raise ValueError("M3 golden cases must not claim human verification")
    return GoldenProvenance(
        total_cases=len(cases),
        scored_positive_cases=positive_count,
        unscored_absent_cases=len(cases) - positive_count,
        curation_status=next(iter(curation_statuses)),
        approval_status=next(iter(approval_statuses)),
        human_verified=False,
    )
```

**코드에서 꼭 볼 것**

- `percentile`은 `math.ceil(fraction * n) - 1`로 인덱스를 계산한다. 지연 시간은 absent 사례를 포함해 시도한 28개 전부에서 기록되므로 표본이 28개이고, p95는 `ceil(26.6) - 1 = 26`, 즉 정렬된 27번째 값이다. **보간하지 않고 실제 관측값 하나를 고르므로, 실행되지 않은 지연 시간을 결과로 보고하지 않는다.**
- `max(0, ...)`는 표본이 하나일 때 인덱스가 -1이 되는 것을 막는다.
- **`_golden_provenance`는 검토 상태의 균일성을 강제한다. 한 스위트 안에 승인된 사례와 미승인 사례가 섞이면 결과 파일의 `approval_status` 한 줄이 전체를 대표하지 못한다.** 떠오르는 대안 — 관측된 상태들의 집합을 기록하는 것 — 은 혼합 상태 처리를 이후의 모든 소비자에게 떠넘긴다. 대신 에러를 내는 것은 혼합된 스위트를 표현할 상태가 아니라 문 앞에서 막을 큐레이션 실수로 취급하는 것이다.
- `verification_states != {False}`를 거부한다. M3의 골든 데이터가 사람 검증을 마쳤다고 주장하지 않는다는 조건이 코드로 강제된다.

> **개념 — 평균은 처리량의 숫자이고 p95는 경험의 숫자다**
>
> 평균은 질의 N개의 총 시간을 N으로 나눈 값에 답한다. 예산 산술에 맞는 숫자이고, 실제로 4절의 질의 예산이 정확히 그 용도로 쓴다. 그러나 평균을 경험하는 사람은 없다. 요청 하나하나는 분포의 한 점에 떨어지고, 기억에 남는 것은 느린 꼬리다. 평균만 담은 요약은 아주 느린 소수의 질의가 빠른 다수 속에 숨게 놓아둔다.
>
> 커밋된 bm25 실험군이 실제 데이터에서 그 간극을 보여준다. 평균은 35.6ms인데 p95는 55.4ms, 최댓값은 62.0ms다. 꼬리는 평균보다 대략 절반쯤 더 느리게 돌고, 그것을 드러내는 것은 백분위 줄뿐이다.
>
> 표본이 28개면 결정이 하나 더 남는다. 숫자 28개의 95번째 백분위란 정확히 무엇인가. 흔히 쓰는 보간 정의들은 두 관측값 사이의 값, 즉 아무도 측정하지 않은 지연 시간을 만들어 낸다. 최근접 순위 방식은 대신 정렬된 목록의 한 위치를 고른다. 여기서는 ceil(0.95 × 28) − 1 = 26, 곧 27번째 관측값이고, 실제로 일어난 지연 시간이다. 표본이 적을 때는 매끄러운 추정값보다 실제 관측값만 보고하는 쪽이 더 값지다.

커밋된 아티팩트가 이 산술을 확인해 준다. 표본은 28개이고, 저장된 p95는 정확히 정렬된 27번째 관측값이다.

```bash
python3 -c "import json; d=json.load(open('data/eval_runs/20260824T203336Z-structure-1200-lexical-bm25.json')); lat=sorted(c['latency_ms'] for c in d['cases']); print(len(lat), lat[26], d['latency']['p95_ms'], d['latency']['mean_ms'])"
```

```text
28 55.356528 55.356528 35.56012882142857
```

### 여기까지 왔을 때 설명할 수 있어야 하는 것

다음 질문의 답은 앞에서 **굵게 표시한 핵심 문장**에 있다. 각 답을 해당 레코드와 연결해 설명해 본다.

- **집계 점수만 저장하면 나중에 무엇을 할 수 없는가?**
  - **답:** 회귀가 어느 질문에서 생겼는지 추적하거나, 예상 증거 대신 어떤 히트가 나왔는지 조사할 수 없다.
- **`CaseEvaluation.score`가 0이 아니라 `None`인 이유는 무엇인가?**
  - **답:** absent 사례는 채점하지 않은 것이며, 0은 채점했지만 검색에 실패했다는 잘못된 뜻을 만든다.
- **사례마다 `golden`을 다시 저장하는 것이 중복이 아닌 이유는 무엇인가?**
  - **답:** 외부 정답 파일이 나중에 바뀌어도 이 실행이 실제로 사용한 정답을 산출물 안에 그대로 보존한다.
- **표본이 적을 때 p95가 보간값이 아니라 관측값이어야 하는 이유는 무엇인가?**
  - **답:** 지연 시간은 absent 사례를 포함해 시도한 28개 전부에서 기록되므로 p95는 정렬된 27번째 관측값이다. 최근접 순위를 고르면 실제로 측정된 지연 시간을 보고하고, 보간은 일어난 적 없는 값을 만들어 낸다.
- **검토 상태가 스위트 안에서 균일해야 하는 이유는 무엇인가?**
  - **답:** 산출물에는 스위트 전체를 나타내는 검토 출처 상태가 하나만 있으므로, 승인된 사례와 미승인 사례를 섞으면 그 상태가 거짓이 된다.
- **아티팩트 스키마 버전을 올리는 것이 하지 않는 일은 무엇인가?**
  - **답:** 기준선을 가르지 않는다. 기준선 선택은 스위트와 config만 대조하므로, 옛 실행과 새 실행을 가르는 것은 config 안에 기록된 필드뿐이다.

---

[← 이전: 어블레이션](05-ablation.md) · [모듈 개요](../03-build.md) · [다음: 평가 실행 →](07-evaluation-run.md)
