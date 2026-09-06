# M3.3 튜토리얼 4 — 어제의 0.79와 오늘의 0.82를 비교해도 되는가

튜토리얼 3(M3.2)은 한 번의 평가 실행을 한 벌의 숫자로 바꾸는 채점기를 남겼다. 같은 구간, 같은 히트가 들어오면 바이트 단위로 같은 점수가 나온다. 그 계층이 하지 못하는 일은 기억이다. 지난 실행의 기록도, 그 숫자가 측정된 조건의 기록도 남기지 않으므로, 튜닝할 때마다 던지는 질문 — 오늘이 어제보다 나은가 — 에는 아직 정직한 답이 없다.

어제 재현율이 0.79였고 오늘 0.82라고 하자. 개선인가. **알 수 없다.** 그 사이에 임베딩 공급자가 바뀌었을 수도, 청킹 목표가 바뀌었을 수도, 검색 깊이가 5에서 10으로 바뀌었을 수도 있다. 조건 하나가 숫자를 얼마나 움직이는지는 커밋된 평가 아티팩트가 보여준다. 같은 lexical BM25 검색이 1,200자 청킹에서는 재현율 0.5208을, 500자 청킹에서는 0.4583을 기록한다. 이 0.0625 차이는 순전히 측정 조건의 차이다 — 이 경계를 넘어 비교하면 청킹 변경이 검색 개선으로 보고된다.

비교 규칙이 없으면 이 실패는 조용히 누적된다. 파라미터를 하나씩 조정할 때마다 "지난번보다 낫다"는 기록만 남고, 지난번이 실제로 무엇을 측정했는지는 아무도 재구성할 수 없다. 그런 비교 위에 세운 게이트는 회귀를 잡는 것이 아니라 잡음을 공인한다.

그래서 이 튜토리얼은 점수에 기억과 비교 규칙을 붙인다. 불변조건은 하나다. **두 점수는 스위트가 같고 정규화를 거친 설정이 동일할 때만 — 다시 말해 정규 JSON 문자열이 바이트 단위로 일치할 때만 — 비교한다.** 그 밖의 모든 경우는 더 느슨한 비교가 아니라 비교 없음이며, 정확히 그렇게 보고해야 한다.

**선행 조건:** 튜토리얼 3의 `uv run pytest tests/evals/test_02_scoring.py -q`가 통과해야 한다.

### 구성이 완전히 같을 때만 비교한다

그래서 `EvalResult`는 지표와 함께 **정규화된 설정 전체**를 저장한다. 청킹, 검색 방식, 공급자, 차원, 검색 깊이 — 하나라도 다르면 다른 실험이다.

> **개념 — 설정 지문이 비교의 열쇠다**
>
> 회귀 판정은 하나의 시스템을 두 번 측정했다는 주장이므로, 뺄셈보다 먼저 두 실행이 같은 것을 측정했다는 사실부터 성립시켜야 한다. 이 계층은 그것을 구조로 성립시킨다. 측정에 영향을 주는 모든 축을 하나의 설정 객체로 정규화해 지표 옆에 저장하고, 기준선 조회는 스위트 이름과 그 정규화된 설정의 일치만 본다. 정규형의 동등이 곧 "같은 실험"의 정의다. 유사도 판정도, 부분 인정도, "랭커만 다르니 충분히 가깝다"도 없다.
>
> 이 지문은 양방향으로 작동한다. 설정이 일치하는 두 실행은 몇 주가 떨어져 있어도 비교할 수 있다. 숫자를 결정하는 조건이 전부 고정되어 있기 때문이다. 반대로 필드 하나가 다른 두 실행은 남남이다. 그 차이에는 설정 변경의 효과가 다른 모든 것과 뒤엉켜 있고, 사후의 어떤 산술로도 둘을 다시 분리할 수 없다.

`latest_comparable_baseline()`은 설정이 **정확히** 일치하는 가장 최근 결과만 가져오고, 일치하는 결과가 없으면 비교 대상이 없다고 보고한다. 설정이 비슷한 결과를 대신 사용하지 않는다.

> **개념 — 비교 불가는 조용한 통과가 아니다**
>
> 게이트의 정직한 결과는 셋이다. 통과, 회귀, 그리고 비교 대상 없음. 셋째를 첫째로 뭉개는 것이 이 계층이 저지를 수 있는 가장 위험한 실패다. 이 실패는 정확히 측정 조건이 바뀐 순간에 발동한다 — 비교가 가장 성립하지 않는 순간에 게이트가 조용히 초록불을 켠다. 그러면 설정 변경은 언제나 자기 영향을 세탁한다. 새 설정의 첫 실행은 진짜 기준선을 찾지 못한 채 통과 처리되고, 이후의 모든 실행은 옛 세계가 만든 숫자와 비교된다.
>
> 아무것도 돌려주지 않고 호출자가 "기준선 없음"을 말하게 만들면 셋째 상태가 눈에 보인다. 새 설정의 첫 실행은 기준선을 세우는 실행이지 판정받는 실행이 아니고, 판정받았다고 주장해서도 안 된다.

조용한 대체 비교가 얼마나 큰 오류를 만드는지는 커밋된 아티팩트가 보여준다. 커밋된 평가 실행의 lexical BM25 실험군 둘은 청킹 목표(그리고 거기서 파생된 실험군 이름)만 다른데, 재현율은 0.5208 대 0.4583이다:

```bash
python3 -c "import json; a=json.load(open('data/eval_runs/20260824T203336Z-structure-1200-lexical-bm25.json')); b=json.load(open('data/eval_runs/20260824T203336Z-structure-500-lexical-bm25.json')); print('recall  :', a['metrics']['recall_at_k'], 'vs', b['metrics']['recall_at_k']); print('config ==', a['config'] == b['config']); print('chunking:', a['config']['chunking']['target_text_chars'], 'vs', b['config']['chunking']['target_text_chars'])"
```

설정을 무시하는 조회라면 500자 실험군의 행을 1,200자 실행의 기준선으로 건네고, 검색 파라미터는 하나도 바뀌지 않았는데 재현율 +0.0625 "개선"을 보고했을 것이다. 대신 게이트는 `None`을 돌려주고, 튜토리얼 7의 러너는 그것을 고유한 결과로 기록한다 — 비교는 건너뛰고, 기준선은 세워진다.

`serialize_config()`가 정규화된 JSON을 만드는 이유도 여기에 있다. 키를 정렬해야 같은 설정이 항상 같은 문자열로 기록되어 저장된 설정과 산출물을 실행 사이에 그대로 비교할 수 있다. JSON으로 표현할 수 없는 값과 무한대, NaN도 거부한다. 저장된 뒤에는 어떤 비교도 성립하지 않는 값들이기 때문이다. 두 선택 모두 4절에서 해부한다.

### 방향과 허용 오차를 명시한다

회귀 판정(regression gating)을 하려면 각 지표에서 어느 방향이 개선인지 정의해야 한다. Recall@k, Hit Rate@k, MRR은 모두 클수록 좋은 값이므로 비교식이 하나로 통일된다.

```text
delta = current - baseline
regressed = delta < -tolerance
```

> **개념 — 방향을 선언하지 않은 지표는 게이팅할 수 없다**
>
> current 빼기 baseline이라는 뺄셈은 어느 부호가 좋은 것인지 누군가 선언한 뒤에야 판정이 된다. 재현율, 적중률, MRR은 클수록 좋으므로 하락이 허용 오차를 넘으면 회귀라는 규칙 하나로 셋을 전부 덮는다. 지연 시간은 부호가 반대다. 작을수록 좋은 값에 같은 규칙을 그대로 적용하면 느려질 때마다 칭찬하고 빨라질 때마다 회귀로 판정한다.
>
> 비교기가 두 매핑이 공유하는 키가 아니라 이름 세 개의 명시적 허용 목록을 도는 이유가 이것이다. 커밋된 실행의 지표 매핑에는 품질 옆에 지연 시간이 그대로 실려 있다. 1,200자 lexical BM25 실험군은 재현율 0.5208 옆에 p95 지연 시간 55.36ms를 기록하고, 같은 청킹에서 가장 느린 실험군은 238.23ms를 기록한다. 공유 키 전부를 클수록 좋다고 가정하는 게이트라면 55.36에서 238.23으로의 도약을 +182.87 개선으로 읽는다. 선언되지 않은 지표를 건너뛰는 것은 엉성한 입력에 관대해서가 아니라, 선언된 적 없는 방향을 추측하기를 거부하는 것이다.

`tolerance`는 실제로 발생했지만 받아들일 수 있는 하락을 회귀로 판정하지 않기 위한 값이다. 기본값은 0.0으로 어떤 하락도 허용하지 않는다. 이 엄격함이 감당 가능한 이유는 채점 경로 전체가 튜토리얼 3의 불변조건대로 결정적이기 때문이다. 같은 조건이면 같은 숫자가 나오므로, 허용 오차 0이 오판할 측정 잡음 자체가 없다. 허용 오차가 실제로 일을 하게 되는 것은 진짜 잡음 있는 축이 설정에 들어오는 날이고, 그때도 지표별로, 의도를 갖고 올린다 — 일괄 완충값이 아니다.

음수 허용 오차는 `__post_init__`이 거부한다. 허용 오차가 음수라면 점수가 올라도 회귀로 판정하라는 뜻이 되어 게이팅의 정의와 맞지 않는다.

### 영속화는 commit하지 않고 flush한다

**`EvalResult` 저장은 호출자의 트랜잭션 안에서 flush만 수행하고 커밋은 호출자가 한다.** M1.4의 `persist_seed_batch`와 같은 규칙이다.

평가 결과를 러너의 다른 작업과 같은 트랜잭션으로 묶어야 하는 경우가 있다. 이 함수가 내부에서 커밋하면 호출자는 그 경계를 정할 수 없고, 뒤이은 작업이 실패해도 평가 결과만 남는다.

숨은 커밋이 부르는 실패는 반쯤 기록된 실행이다. 결과 행은 커밋됐는데 러너의 다음 단계가 실패하면, 데이터베이스에는 실행이 끝내 완료되지 못한 기준선이 남고 다음 실행은 그것과 태연히 비교한다. flush만 하면 행은 아직 열려 있는 트랜잭션 안에서 ID를 받고, 롤백하면 그 실행이 쓴 다른 모든 것과 함께 사라진다. 전부-아니면-무(無)의 결정권이 호출자 한 곳에 모인다.

### 무엇을 작성하고 어디를 직접 구현할까

먼저 `app/db/models.py`에 결과 테이블을 추가하고, `app/evals/regression.py`를 다섯 단계로 작성한다. 앞의 세 단계는 순수 계산이고, 뒤의 두 단계가 데이터베이스에 접근한다.

| 구간 | 학습 행동 | 여기서 얻어야 하는 것 |
|---|---|---|
| `EvalResult` 테이블 | **구조 작성** | 기준선이 파일이 아니라 행으로 남는 이유 |
| 지표 이름과 방향 | **설정 스키마 정의** | 방향을 아는 지표만 게이팅한다는 것 |
| `RegressionTolerances` | 불변조건을 **직접 구현** | 음수 허용 오차가 무의미한 이유 |
| `compare_against_baseline` | 비교 규칙을 **직접 구현** | 경계값이 통과인지 실패인지 |
| 설정 정규화와 검증 | **경계 변환 검토** | 같은 실험이 같은 문자열이 되는 조건 |
| 영속화와 기준선 조회 | **구조 작성 후 호출 순서 검토** | flush와 commit의 경계 |

### 1. 방향을 아는 지표만 게이팅한다

#### `app/db/models.py` 확장 — `EvalResult` 테이블

기준선을 파일이 아니라 데이터베이스 행으로 남기려면 테이블이 먼저 필요하다. M1.4의 테이블들과 같은 파일에, 같은 규칙으로 추가한다. 어느 튜토리얼도 이 테이블을 아직 만들지 않았다 — 여기서 처음 작성한다.

행이냐 파일이냐는 조회 가능성의 결정이다. 이 모듈이 마지막에 만드는 조회 — 스위트와 정규화된 설정이 모두 일치하는 가장 최근 행 — 는 인덱스를 타는 SQL 쿼리 하나다. PostgreSQL이 `WHERE` 절에서 JSONB 동등 비교를 해 주기 때문이다. 기준선을 파일 디렉터리로 관리하면 설정을 파일 이름에 인코딩하거나 조회할 때마다 모든 파일을 열어 파싱해야 하고, "가장 최근"은 어떤 제약도 지켜주지 않는 파일시스템 타임스탬프에 얹히게 된다. 그렇다고 파일이 사라지는 것은 아니다. 역할이 바뀔 뿐이다. `raw_artifact_path`가 모든 행에서 `data/eval_runs/` 아래의 사례별 전체 JSON을 가리키므로, 행은 조회 가능한 요약이고 파일은 감사 가능한 증거다. 어디에 무엇이 사는지도 봐 두자. JSON 아티팩트는 저장소에 커밋되지만 `eval_results` 행은 로컬 PostgreSQL에만 존재한다. 커밋된 실행들은 스위트 이름 `m3-retrieval-v1`을 기록하고 있고, 행을 다시 만드는 방법은 평가를 다시 돌리는 것이다.

**학습 행동 — 구조 작성:** 세 개의 `CheckConstraint`가 각각 어떤 잘못된 행을 막는지 확인하며 작성한다.

<!-- src: app/db/models.py::EvalResult -->
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
```

**코드에서 꼭 볼 것**

- `config`와 `metrics`는 `JSONB`이고, 제약이 `jsonb_typeof(...) = 'object'`를 강제한다. 컬럼 타입만으로는 어떤 JSON 값이든 — 배열도, 문자열도, 숫자 하나도 — 들어갈 수 있다. 배열로 저장된 설정은 어떤 정규화된 객체와도 같아질 수 없으므로 이후의 모든 조회가 불평 한마디 없이 기준선 없음을 돌려주게 된다. 제약이 그 조용한 영원히-불일치 행을 저장 시점의 요란한 오류로 바꾼다.
- `suite`와 `raw_artifact_path`는 공백뿐인 값을 제약으로 거부한다. 빈 스위트는 아무것도 일치할 수 없는 조회 키이고, 아티팩트 경로 없는 결과는 증거를 버린 주장이다 — 집계 숫자만 남고 그것을 대조할 사례별 기록이 없다.
- `created_at`은 `server_default=func.now()`다. 시각을 애플리케이션이 아니라 데이터베이스가 찍으므로, 여러 프로세스가 저장해도 기준선 정렬이 한 시계를 따른다. 스위트와 `created_at`에 걸린 인덱스는 정확히 이 모듈이 마지막에 만드는 쿼리 — 한 스위트 안에서 가장 최근 것부터 — 를 위한 것이다.
- 이 테이블은 측정값과 측정 조건만 저장하고 통과/실패 판정은 저장하지 않는다. 판정은 비교 시점에 다시 계산하므로 허용 오차 정책이 내일 바뀌어도 과거를 다시 쓸 필요가 없다. 판정을 저장하면 기록 시점에 우연히 유효했던 정책이 행에 얼어붙어, 이후의 모든 정책 아래에서 거짓을 보고한다.

#### `app/evals/regression.py` 생성 — 모듈 헤더

**학습 행동 — 구조 작성:** import 목록의 `EvalResult`를 확인한다. 방금 정의한 테이블을 이 모듈이 처음 사용한다.

```python
"""Typed regression comparison and PostgreSQL evaluation-result persistence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
import json
import math
from pathlib import Path
from typing import Any, Final, Literal, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import EvalResult
```

#### `app/evals/regression.py` 확장 — 지표 이름과 방향

**학습 행동 — 설정 스키마 정의:** 목록에 지표 세 개만 있는 이유를 확인하며 작성한다.

<!-- src: app/evals/regression.py::MetricName,HIGHER_IS_BETTER_METRICS -->
```python
type MetricName = Literal["recall_at_k", "hit_rate_at_k", "mrr"]

HIGHER_IS_BETTER_METRICS: Final[tuple[MetricName, ...]] = (
    "recall_at_k",
    "hit_rate_at_k",
    "mrr",
)
```

**코드에서 꼭 볼 것**

- 상수 이름이 `HIGHER_IS_BETTER_METRICS`다. 방향이 이름에 들어 있으므로, 지연 시간처럼 작을수록 좋은 지표를 추가하려 할 때 이름과 값이 곧바로 충돌한다.
- **지연 시간은 이 목록에 없다. 방향이 반대인 지표를 같은 비교 함수에 넣으면 값이 줄어든 개선을 회귀로 판정하기 때문이다.** 지연 시간 예산은 M3.4가 따로 다룬다.
- 이 세 이름은 튜토리얼 3의 채점기가 내는 세 가지 비율 그대로이고, `MetricName`이 이를 `Literal`로 좁힌다. 지표 이름의 오타는 조용히 게이팅에서 빠지는 지표가 아니라 호출부의 타입 오류가 된다.

### 2. 음수 허용 오차는 의미가 없다

#### `app/evals/regression.py` 확장 — 허용 오차와 비교 레코드

**학습 행동 — 불변조건 구현:** `__post_init__`을 직접 구현하면서 두 검사를 따로 두는 이유를 확인한다.

<!-- src: app/evals/regression.py::RegressionTolerances,BaselineComparison -->
```python
@dataclass(frozen=True, slots=True)
class RegressionTolerances:
    """Maximum accepted absolute drop for each higher-is-better metric."""

    recall_at_k: float = 0.0
    hit_rate_at_k: float = 0.0
    mrr: float = 0.0

    def __post_init__(self) -> None:
        """Reject non-finite or negative tolerance values at construction."""
        for metric in HIGHER_IS_BETTER_METRICS:
            value = getattr(self, metric)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{metric} tolerance must be a finite nonnegative number")
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{metric} tolerance must be a finite nonnegative number")

    def for_metric(self, metric: MetricName) -> float:
        """Return the configured tolerance for one supported metric."""
        return float(getattr(self, metric))


@dataclass(frozen=True, slots=True)
class MetricComparison:
    """One current metric compared with its higher-is-better baseline."""

    metric: MetricName
    baseline: float
    current: float
    delta: float
    tolerance: float
    regressed: bool


@dataclass(frozen=True, slots=True)
class BaselineComparison:
    """Deterministically ordered comparisons for all regression-gated metrics."""

    metrics: tuple[MetricComparison, ...]

    @property
    def regressed_metrics(self) -> tuple[MetricName, ...]:
        """Return metric names whose drop exceeds the configured tolerance."""
        return tuple(result.metric for result in self.metrics if result.regressed)

    @property
    def passed(self) -> bool:
        """Return whether every metric stayed within its allowed drop."""
        return not self.regressed_metrics
```

**코드에서 꼭 볼 것**

- `isinstance(value, bool)`을 먼저 거부한다. `True`는 `int`의 하위 타입이므로, 이 검사가 없으면 `tolerance=True`가 `1.0`으로 해석되어 재현율이 1.0 떨어져도 회귀로 판정되지 않는다.
- `value < 0`을 거부한다. 허용 오차가 음수면 점수가 오른 경우까지 회귀로 판정하게 된다.
- `MetricComparison`은 `baseline`, `current`, `delta`, `tolerance`를 모두 저장한다. `regressed` 불리언만 남기면 그 판정의 근거를 나중에 확인할 수 없다.
- `BaselineComparison.passed`는 `regressed_metrics`에서 파생된다. 두 값을 따로 저장하지 않으므로 서로 어긋날 수 없다.

### 3. 경계값은 통과다

#### `app/evals/regression.py` 확장 — 기준선 비교

**학습 행동 — 비교 규칙 구현:** `regressed`를 계산하는 한 줄을 직접 작성하고, 그 줄에 `math.isclose`가 필요한 이유를 설명할 수 있어야 한다.

<!-- src: app/evals/regression.py::_metric_value,compare_against_baseline -->
```python
def _metric_value(metrics: Mapping[str, float], metric: MetricName, owner: str) -> float:
    try:
        value = metrics[metric]
    except KeyError as exc:
        raise ValueError(f"{owner} metrics are missing {metric}") from exc
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{owner} {metric} must be a finite number between 0 and 1")
    numeric = float(value)
    if not math.isfinite(numeric) or not 0.0 <= numeric <= 1.0:
        raise ValueError(f"{owner} {metric} must be a finite number between 0 and 1")
    return numeric


def compare_against_baseline(
    baseline: Mapping[str, float],
    current: Mapping[str, float],
    *,
    tolerances: RegressionTolerances | Mapping[str, float] | None = None,
) -> BaselineComparison:
    """Compare current values with an explicit higher-is-better metric baseline.

    A drop exactly equal to its tolerance passes. Extra metrics are ignored so
    lower-is-better values such as latency are never interpreted implicitly.
    """
    if not isinstance(baseline, Mapping) or not isinstance(current, Mapping):
        raise ValueError("baseline and current metrics must be mappings")
    if tolerances is None:
        limits = RegressionTolerances()
    elif isinstance(tolerances, RegressionTolerances):
        limits = tolerances
    else:
        if not isinstance(tolerances, Mapping) or not all(
            isinstance(metric, str) for metric in tolerances
        ):
            raise ValueError("tolerances must map supported metric names to numbers")
        unknown = set(tolerances) - set(HIGHER_IS_BETTER_METRICS)
        if unknown:
            names = ", ".join(sorted(unknown))
            raise ValueError(f"unsupported metric tolerances: {names}")
        limits = RegressionTolerances(**tolerances)
    comparisons: list[MetricComparison] = []
    for metric in HIGHER_IS_BETTER_METRICS:
        baseline_value = _metric_value(baseline, metric, "baseline")
        current_value = _metric_value(current, metric, "current")
        tolerance = limits.for_metric(metric)
        delta = current_value - baseline_value
        boundary = -tolerance
        regressed = delta < boundary and not math.isclose(
            delta,
            boundary,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
        comparisons.append(
            MetricComparison(
                metric=metric,
                baseline=baseline_value,
                current=current_value,
                delta=delta,
                tolerance=tolerance,
                regressed=regressed,
            )
        )
    return BaselineComparison(metrics=tuple(comparisons))
```

**코드에서 꼭 볼 것**

- 판정식은 `delta < boundary and not math.isclose(...)`다. 부동소수 뺄셈은 `-0.30000000000000004`처럼 `-tolerance`와 미세하게 다른 값을 낼 수 있다. **`isclose`가 없으면 허용 오차와 정확히 같은 크기의 하락이 실행에 따라 통과하기도 하고 실패하기도 한다.**
- 목록에 없는 지표는 비교하지 않고 넘어간다. 호출자가 지연 시간을 섞어 넣어도 방향을 모르는 값을 임의로 해석하지 않는다.
- `_metric_value`는 값이 0에서 1 사이인지 확인한다. 세 지표 모두 비율이므로 1.2 같은 값은 좋은 결과가 아니라 계산 오류다.
- 허용 오차를 매핑으로 받을 때 모르는 키가 있으면 거부한다. `{"recal_at_k": 0.01}` 같은 오타를 통과시키면 실제로는 허용 오차 0으로 게이팅되는데 사용자는 0.01로 설정했다고 판단하게 된다.

집중 테스트가 정확히 이 경계를 측정된 값으로 고정한다. 기준선 재현율 0.8, 현재 0.79, 허용 오차 0.01 — 허용 오차와 정확히 같은 크기의 하락이다. 파이썬이 거기서 실제로 수행하는 뺄셈을 돌려 보자:

```bash
python3 -c "print(repr(0.79 - 0.8))"
```

결과는 `-0.010000000000000009`다. 0.79도 0.8도 정확한 이진 표현이 없어서 경계 `-0.01`보다 대략 9e-18만큼 아래다. `delta < boundary`만 있으면 이 허용된 경계 하락이 회귀로 판정되고, 어떤 경계 사례가 통과하는지는 어느 십진 소수가 어느 쪽으로 반올림되는지에 달리게 된다. `abs_tol=1e-12`는 그 표현 오차를 흡수하면서도 이 스위트의 순위 기반 비율이 만들 수 있는 어떤 실제 하락보다 훨씬 작고, `rel_tol=0.0`은 엡실론을 절대값으로 고정한다. 이 지표들은 0에서 1 사이의 고정 눈금 위에 살고, 상대 엡실론은 허용 오차가 가장 작아지는 곳에서 정확히 0으로 줄어들기 때문이다. 비교 전에 양쪽 매핑을 반올림해도 이 경계는 안정되지만, 그러면 모든 반올림 눈금 근처에서 실제로 다른 값들이 하나로 합쳐진다. 경계에만 붙는 한쪽 엡실론은 경계 자체 말고는 아무것도 건드리지 않는다.

### 4. 같은 실험이 같은 문자열이 되게 한다

#### `app/evals/regression.py` 확장 — 설정 정규화와 값 검증

**학습 행동 — 경계 변환 검토:** `sort_keys=True`와 `allow_nan=False`가 각각 어떤 입력을 막는지 확인하며 작성한다.

<!-- src: app/evals/regression.py::_validate_config_keys,_artifact_path -->
```python
def _validate_config_keys(value: object) -> None:
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise ValueError("config keys must be strings")
        for child in value.values():
            _validate_config_keys(child)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for child in value:
            _validate_config_keys(child)


def serialize_config(config: Mapping[str, Any]) -> str:
    """Serialize a JSON-object config canonically for stable comparability."""
    if not isinstance(config, Mapping):
        raise ValueError("config must be a JSON object")
    try:
        _validate_config_keys(config)
        return json.dumps(
            dict(config),
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (RecursionError, TypeError, ValueError) as exc:
        raise ValueError("config must contain only finite JSON values") from exc


def _canonical_config(config: Mapping[str, Any]) -> dict[str, Any]:
    value = json.loads(serialize_config(config))
    return cast(dict[str, Any], value)


def _validated_metrics(metrics: Mapping[str, float]) -> dict[str, float]:
    if not isinstance(metrics, Mapping) or not metrics:
        raise ValueError("metrics must be a nonempty JSON object")
    validated: dict[str, float] = {}
    for name, value in metrics.items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError("metric names must be nonblank strings")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"metric {name} must be a finite number")
        numeric = float(value)
        if not math.isfinite(numeric):
            raise ValueError(f"metric {name} must be a finite number")
        validated[name] = numeric
    return validated


def _validated_suite(suite: str) -> str:
    if not isinstance(suite, str) or not suite.strip():
        raise ValueError("suite must be a nonblank string")
    if len(suite) > 128:
        raise ValueError("suite must be at most 128 characters")
    return suite


def _artifact_path(raw_artifact_path: str | Path) -> str:
    if not isinstance(raw_artifact_path, (str, Path)):
        raise ValueError("raw_artifact_path must be a string or Path")
    path = str(raw_artifact_path)
    if not path.strip():
        raise ValueError("raw_artifact_path must be nonblank")
    return path
```

**코드에서 꼭 볼 것**

- **`sort_keys=True`는 같은 설정을 항상 같은 문자열로 만들어 기록된 설정 텍스트와 산출물을 결정적으로 유지한다.** `latest_comparable_baseline`의 JSONB 동등 비교는 키 순서를 무시하므로 조회 자체는 이 정렬 없이도 성립하지만, 기록이 실행마다 달라지면 산출물 diff가 깨진다.
- `allow_nan=False`는 `NaN`과 무한대를 거부한다. JSON 표준에 없는 값이며, 저장되면 이후 어떤 비교도 성립하지 않는다.
- `_validate_config_keys`는 중첩 구조를 재귀로 검사한다. 최상위 키만 검사하면 중첩 딕셔너리의 정수 키가 통과하고, 직렬화 시점에 오류가 난다.
- `_canonical_config`는 직렬화한 결과를 다시 파싱한다. 저장되는 값이 정규화를 거친 값과 같다는 것을 이 왕복이 보장한다.

> **개념 — 하나의 정규 텍스트, 두 부류의 소비자**
>
> 정렬되고 최소화된 직렬화는 요구가 서로 다른 두 소비자를 동시에 섬긴다. 데이터베이스는 덜 까다로운 쪽이다. PostgreSQL은 JSONB를 정규화된 내부 형식으로 저장하고 그 객체 동등 비교는 키 순서를 무시하므로, 기준선 조회는 키 정렬이 없어도 일치한다. 정렬이 필요한 소비자는 데이터베이스 바깥에 산다. 아티팩트에 기록되는 설정 텍스트, 그리고 사람이나 스크립트가 두 아티팩트 사이에서 뜨는 모든 diff다. 정렬하지 않으면 같은 실험이 딕셔너리 생성 순서에 따라 실행마다 다르게 직렬화될 수 있고, 그때 diff는 직렬화의 우연을 설정 변경처럼 보여준다.
>
> 한 번 정규화한다는 원칙이 왕복도 설명한다. 직렬화하고, 다시 파싱해서, 파싱된 값을 저장한다. 데이터베이스에 도달하는 것이 정규형이라는 보장이 생긴다 — 호출자의 원본 객체 안에 어떤 잔재가 살아남았든 상관없이.

설정 전체를 저장하고 해시를 저장하지 않는 이유는 무엇인가. 정규 문자열의 다이제스트는 더 값싼 동등 키가 되지만, 진단 가능성 때문에 기각된다. 실행이 기준선을 찾지 못했을 때 첫 질문은 *지난 실행과 어느 필드가 다른가*이고, 행에 JSON 객체가 통째로 있으면 diff 한 번이 그 질문에 답하지만 해시는 "무언가 다르다"밖에 말하지 못한다. 스키마 버전 정수는 정반대 극단이다 — 올리기는 아주 싸지만, 비교되는 설정 안에 직접 들어 있지 않는 한 아무것도 가르지 못하고, 무엇이 바뀌었는지도 말하지 않는다.

정직하게 들고 가야 할 날카로운 모서리가 하나 있다. 지문은 설정이 기록하는 범위 안에서만 기준선을 가른다. 커밋된 실험 설정은 청킹, 검색, 임베딩, 측정 축을 고정하지만 — 튜토리얼 3의 판정 규칙이나 그 임계값에 대해서는 아무것도 기록하지 않는다. 그 채점 규칙이 언젠가 바뀐다면, 옛 규칙과 새 규칙으로 채점된 실행들이 여전히 바이트 단위로 일치해 검색만 움직인 것처럼 비교될 것이다. 게이트는 설정이 완전한 만큼만 정직하다. 기록되지 않은 것은 가르지 못한다.

### 5. flush는 하되 commit은 하지 않는다

#### `app/evals/regression.py` 완성 — 영속화와 기준선 조회

**학습 행동 — 구조 작성 후 호출 순서 검토:** 이 함수가 `flush`만 하고 `commit`을 하지 않는 이유를 설명할 수 있어야 한다.

<!-- src: app/evals/regression.py::persist_eval_result,latest_comparable_baseline -->
```python
async def persist_eval_result(
    session: AsyncSession,
    *,
    suite: str,
    config: Mapping[str, Any],
    metrics: Mapping[str, float],
    raw_artifact_path: str | Path,
    created_at: datetime | None = None,
) -> EvalResult:
    """Flush one validated result without committing the caller's transaction."""
    values: dict[str, Any] = {
        "suite": _validated_suite(suite),
        "config": _canonical_config(config),
        "metrics": _validated_metrics(metrics),
        "raw_artifact_path": _artifact_path(raw_artifact_path),
    }
    if created_at is not None:
        if not isinstance(created_at, datetime):
            raise ValueError("created_at must be a timezone-aware datetime")
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        values["created_at"] = created_at

    result = EvalResult(**values)
    session.add(result)
    await session.flush()
    return result


async def latest_comparable_baseline(
    session: AsyncSession,
    *,
    suite: str,
    config: Mapping[str, Any],
) -> EvalResult | None:
    """Return the newest row with the same suite and canonical JSON config."""
    statement = (
        select(EvalResult)
        .where(
            EvalResult.suite == _validated_suite(suite),
            EvalResult.config == _canonical_config(config),
        )
        .order_by(EvalResult.created_at.desc(), EvalResult.id.desc())
        .limit(1)
    )
    return await session.scalar(statement)
```

**코드에서 꼭 볼 것**

- 호출하는 것은 `await session.flush()`이고 `commit()`이 아니다. 행이 데이터베이스로 전송되어 ID를 받지만 트랜잭션은 열린 상태로 남는다. 커밋 시점은 호출자가 정하며, M1.4의 `persist_seed_batch`와 같은 규칙이다.
- `created_at`은 시간대 정보가 있는 값만 받는다. 시간대가 없는 값이 섞이면 기준선 정렬이 실행 환경의 로컬 시간대에 따라 달라진다.
- 조회는 `created_at.desc(), EvalResult.id.desc()` 두 키로 정렬한다. 같은 시각에 두 행이 저장되어도 순서가 하나로 정해진다.
- `config`는 `_canonical_config`로 정규화한 뒤 비교한다. 저장할 때와 조회할 때 같은 정규화를 거쳐야 문자열이 일치한다.

> **개념 — 기준선은 왜 가장 최근의 비교 가능한 행이어야만 하는가**
>
> 비교 가능한 행이 여럿 쌓이면 무엇과 비교할지는 정책이 되는데, 여기서는 그 정책을 일부러 설정 불가능하게 만들었다. 가장 최근 것, 끝. 더 느슨한 규칙은 기준선 쇼핑을 부른다. 나쁜 변경 뒤에 역대 가장 약한 실행과 비교하면 하락이 사라지고, 역대 최고 실행과 비교하면 없던 위기가 만들어진다. 기준선을 가장 최근의 비교 가능한 행에 고정하면 모든 실행이 자기 직전의 세계와 비교되고, 그것이 가장 최근 변경 하나를 분리해 내는 유일한 비교다.
>
> 정직한 대가도 있다. 직전 실행에 닻을 내린 게이트는 계단은 감지하지만 표류는 감지하지 못한다. 허용 오차가 0이 아니라면 여러 실행에 나눠 담긴 느린 미끄러짐이 매번의 비교를 통과할 수 있다. 그 트레이드오프를 여기서는 받아들인다. 고정 닻에 대한 장기 표류 감시는 더 나은 기본값이 아니라 다른 도구다.

집중 스위트의 라이브 PostgreSQL 테스트가 세 행으로 선택 규칙을 고정한다. 한 스위트 안에 12:00의 hybrid 설정 행(MRR 0.6), 12:02의 vector 설정 행(MRR 0.7), 12:01의 두 번째 hybrid 설정 행(MRR 0.61)을 넣는다. hybrid 설정으로 조회하면 반드시 12:01 행이 나와야 한다. 12:02 행은 더 최근이지만 다른 실험을 측정했고, 12:00 행은 비교 가능하지만 더는 최근이 아니다. 두 오답 각각이 누락된 필터 하나, 누락된 정렬 하나 거리에 있다.

행 하나의 생애는 튜토리얼 7에서 완전히 배선된다. 러너가 평가를 측정하고 사례별 원시 아티팩트를 `data/eval_runs/` 아래에 기록한다. 한 트랜잭션 안에서 `latest_comparable_baseline`에게 직전의 비교 가능한 행을 묻고, 비교를 계산한 다음에야 새 결과를 `persist_eval_result`에 넘긴다 — 조회가 삽입보다 먼저 실행되므로 실행이 자기 자신과 비교되는 일은 없다. 호출자의 커밋이 행을 확정하고, 그 순간부터 이 행은 같은 설정의 다음 실행이 찾게 될 기준선이다.


### 집중 테스트와 테스트가 지키는 계약

```bash
uv run pytest tests/evals/test_03_regression.py -q
```

핀 고정 리비전 기준으로 열아홉 개의 테스트다. 비교 규칙과 가드는 어디서든 실행되고, 마지막 하나는 라이브 PostgreSQL로 영속화를 증명하되 루프백 데이터베이스에 닿을 수 없으면 이유를 남기고 스스로 건너뛴다.

| 테스트가 깨뜨리는 값 | 지키는 계약 |
|---|---|
| 허용 오차와 정확히 같은 하락 | 경계값 판정이 실행마다 흔들리지 않는다. |
| 음수 또는 불리언 허용 오차 | 게이팅이 무의미해지는 설정을 막는다. |
| 키 순서만 다른 같은 설정 | 같은 실험이 같은 기준선을 찾는다. |
| `NaN` 또는 무한대가 든 설정 | 나중에 비교 불가능한 값이 저장되지 않는다. |
| 목록에 없는 지표 이름 | 방향을 모르는 값을 임의로 해석하지 않는다. |
| naive `datetime` | 기준선 정렬이 실행 환경에 의존하지 않는다. |

### 여기까지 왔을 때 설명할 수 있어야 하는 것

다음 질문의 답은 앞에서 **굵게 표시한 핵심 문장**에 있다. 각 답을 해당 함수와 연결해 설명해 본다.

- **지표만 저장하고 설정을 저장하지 않으면 무엇이 불가능해지는가?**
  - **답:** 두 숫자가 같은 실험을 측정했는지 알 수 없어, 그 차이를 개선이나 회귀라고 정직하게 판정할 수 없다.
- **허용 오차와 정확히 같은 하락에 `math.isclose`가 필요한 이유는 무엇인가?**
  - **답:** 부동소수점 뺄셈은 계산된 차이를 경계보다 아주 조금 작게 만들 수 있다. `math.isclose`는 허용된 경계 하락이 실행마다 불규칙하게 실패하지 않게 한다.
- **지연 시간을 이 비교 함수에 넣으면 안 되는 이유는 무엇인가?**
  - **답:** 현재 비교기는 지연 시간 판정을 뒤집지 않는다. 지표 매핑의 지연 시간은 무시하고 지연 시간 허용 오차는 거부한다. 이 비교기가 클수록 좋은 세 가지 검색 지표에만 방향을 정의했기 때문에 지연 시간을 제외한다.
- **`sort_keys=True`가 없으면 기준선 조회가 어떻게 실패하는가?**
  - **답:** 그 이유로 실패하지 않는다. PostgreSQL JSONB 동등 비교는 객체 키 순서를 무시한다. 키 정렬은 직렬화된 설정 문자열과 산출물을 결정적으로 만들지만 데이터베이스 동등 비교에는 필요하지 않다.
- **`flush`와 `commit`의 차이가 여기서 왜 중요한가?**
  - **답:** `flush`는 행을 데이터베이스에 보내 ID를 받으면서 트랜잭션을 열어 두지만, `commit`은 호출자에게 있어야 할 트랜잭션 소유권을 내부 함수가 가져간다.

---

[← 이전: 채점](03-scoring.md) · [모듈 개요](../03-build.md) · [다음: 어블레이션 →](05-ablation.md)
