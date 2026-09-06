# M3.4 튜토리얼 5 — 미뤄둔 질문을 실험으로 세운다

튜토리얼 4는 의도된 거부로 끝났다. 회귀 판정은 스위트와 정규화된 설정이 정확히 같은 최신 기준선하고만 비교하므로, "이 설정이 시간이 지나며 나빠졌다"고는 말할 수 있어도 "이 설정이 저 설정보다 낫다"고는 결코 말하지 못한다. 그런데 M2가 미뤄 둔 질문 — 어느 청크 크기, 어느 검색 경로, 어느 lexical 랭커 — 이 정확히 그 금지된 설정 간 비교다. 이 문서는 튜토리얼 4의 규칙을 깨지 않고 그 질문에 답할 수 있게 하는 계층을 만든다. `app/evals/ablation.py`는 설정 조합 하나하나를 출처가 기록된 이름 있는 실험군으로 만들고, 비교는 한 실행 안에서 나란히 측정된 실험군 사이에서만 일어난다. 여기서는 정의 계층만 작성하며, 실제 숫자는 실행 계층을 만드는 튜토리얼 7에서 나온다.

이 계층을 생략해도 비교는 어차피 일어난다. 손으로, 그리고 정해진 방식으로 망가진다. 무엇이 걸려 있는지는 커밋된 증거가 그대로 보여준다. `data/eval_runs/`에는 재현율이 0.458333인 아티팩트와 0.520833인 아티팩트가 있는데, 앞의 것이 500자 코퍼스를 재고 뒤의 것이 1,200자 코퍼스를 쟀다는 사실을 지금도 알 수 있는 근거는 파일 이름에 든 실험군 이름과 파일 안의 config 블록뿐이다. 그 둘을 지우면 두 숫자는 터미널이 스크롤되는 순간 쓸모를 잃는다. 자기 설정을 말하지 못하는 측정은 증거가 아니라 소수점 달린 소문이다.

그래서 이 문서가 강제하는 불변조건은 하나다. **실험의 모든 축은 실험군 이름, 아티팩트 파일 이름, 아티팩트 안의 config 블록 세 곳에 나타난다. 자기 설정을 말하지 못하는 실험군은 디스크에 기록되지 않는다.**

> **개념 — 어블레이션**
>
> 이 말은 어블레이션 연구에서 왔다. 동작하는 시스템에서 구성 요소 정확히 하나만 빼거나 바꾸고 다시 측정해, 그 차이를 그 구성 요소의 몫으로 돌리는 방법이다. 머신러닝은 이 방법을 신경과학의 병변 실험에서 빌려 왔고, 방법의 힘은 전부 "정확히 하나"에 있다. 두 측정이 의도된 한 가지에서만 다르면 원인이 숨을 곳이 없다.
>
> 이 규율은 실행만큼 읽기도 구속한다. 조합 전체를 한 번에 도는 것은 괜찮다. 안 되는 것은 축이 둘 이상 다른 두 결과를 비교하는 일이다. 500자 lexical 실험군을 1,200자 hybrid 실험군과 견주면 청크 크기에 대해서도 전략에 대해서도 아무것도 알 수 없다. 둘을 아무리 정확하게 측정했어도 그렇다.

행렬은 결정을 미룰 때 기록해 둔 두 축에서 출발한다.

```text
chunk target: 500, 1200          ← the value M1.3 called an experimental arm, not a conclusion
retrieval:    lexical, vector, hybrid   ← the three paths built in M2
```

500도 1,200도 측정으로 고른 값이 아니고, 이 저장소 어디에도 그 근거가 없다. 그게 핵심이다. 1,200은 M1.3의 기본값 `DEFAULT_TARGET_TEXT_CHARS`로, 그 주석 스스로 결론이 아니라고 못 박아 둔 값이다. 500은 고정 길이 분할 관행이 습관처럼 잡는 크기다. 둘 다 옳다고 알려져서가 아니라 측정하기 위해 고른 값이다.

위 그림은 처음 그린 계획이고, 이제 행렬의 전부가 아니다. M2.9가 조용히 세 번째 축을 추가했다. lexical 질의를 실제로 실행하는 전략은 이제 랭커별로 하나씩(`ts_rank_cd`, `bm25`) 존재하고, lexical 질의를 아예 실행하지 않는 `vector`는 교차하지 않는다. vector 실험군에 랭커 라벨을 붙이면 실행된 적 없는 코드를 설명하는 셈이기 때문이다. 결과는 구조적 구멍이 하나 있는 세 축 완전 교차다. 청크 목표마다 lexical 둘, hybrid 둘, vector 하나. 여섯이 아니라 열 개의 실험군이다. 커밋된 실행이 그 개수를 증명한다.

```bash
ls data/eval_runs/20260824T203336Z-*.json | grep -v budgets | wc -l
```

이 명령은 10을 출력한다. 2026-08-24 실행의 실험군당 원시 아티팩트 하나씩이다. 따라서 "한 번에 축 하나"는 실행을 계획하는 규칙이 아니라 결과를 읽는 규칙이다. 열 행을 나란히 놓으면 hybrid가 구성 경로들을 정말 이기는지, lexical 경로를 어느 랭커가 끌고 가는지, 어느 청크 크기가 유리한지를 확인할 수 있고, 그 판단 하나하나는 해당 축 하나만 다른 두 행에서 읽는다.

교과서적으로 더 싼 설계는 one-factor-at-a-time이다. 기준 실험군 하나를 고정하고 축마다 한 번씩만 바꾸면 열 번이 아니라 다섯 번으로 끝난다. 이 설계를 쓰지 않는 이유는 축들이 상호작용하지 않는다고 가정하기 때문이다. 랭커를 한 청크 크기에서만 재고 다른 크기로 조용히 일반화하게 된다. 결정론적 임베딩 공급자로는 추가 실험군의 비용이 몇 초 수준이라, 완전 교차로 모든 한 축 비교를 다른 축의 두 값 모두에서 확인할 수 있다.

**정답 식별자가 좌표 기반이므로 청크 크기를 바꿔도 같은 정답 파일로 비교할 수 있다.** M3.1에서 그 조건을 만들어 두었다.

**선행 조건:** 튜토리얼 4의 `uv run pytest tests/evals/test_03_regression.py -q`가 통과해야 한다.

**검증 시점:** 이 문서에서는 `ablation.py` 작성만 마친다. 이 파일이 가져오는 `RetrievalEvaluation`, `write_evaluation_artifact`, `evaluate_retriever`는 튜토리얼 6과 7에서 완성되므로 `tests/evals/test_04_ablation.py`는 튜토리얼 7을 마친 뒤 실행한다.

### 무엇을 작성하고 어디를 직접 구현할까

M3.4는 파일 세 개를 만든다. 이 문서에서는 그중 `app/evals/ablation.py` 하나를 작성한다. 실험군을 정의하고 결과를 파일로 남기는 계층이며, 실제 평가 실행은 다음 두 문서에서 다룬다.

| 구간 | 학습 행동 | 여기서 얻어야 하는 것 |
|---|---|---|
| 전략 어휘와 정렬 순서 | **설정 스키마 정의** | 실험군 순서가 고정돼야 하는 이유 |
| `ExperimentConfig` | 불변조건을 **직접 구현** | 모순된 실험 설정을 만들 수 없게 하는 법 |
| `to_dict()` | **필드 매핑 작성** | 기준선 비교가 무엇을 보고 같다고 판단하는가 |
| `AblationOutcome`·`AblationReport` | **레코드 선언 작성** | 결과와 함께 남는 경로와 비교 표의 형태 |
| `experiment_matrix` | 조합 생성을 **직접 구현** | 교차하는 세 축에 안정적인 순서를 부여하는 법 |
| `run_ablation` | 실행 순서를 **직접 구현** | 실험군과 결과가 어긋나지 않게 하는 가드 |

### 1. 전략 어휘와 정렬 순서

#### `app/evals/ablation.py` 생성 — 모듈 헤더

**학습 행동 — 구조 작성:** import 목록의 `retrieval_eval`을 확인한다. 이 파일은 평가를 직접 수행하지 않고 평가 함수를 호출하기만 한다.

```python
"""Configurable M3 retrieval ablations with stable raw artifact paths."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import re
from typing import Literal

from app.config import LexicalRanker
from app.evals.retrieval_eval import RetrievalEvaluation, write_evaluation_artifact
```

import 방향이 곧 계층 약속이다. 이 파일은 튜토리얼 6이 정의하는 레코드 형태인 `RetrievalEvaluation`과 튜토리얼 7이 완성하는 기록 함수 `write_evaluation_artifact`에 의존할 뿐, 평가가 어떻게 실행되는지에는 의존하지 않는다. 그래서 파일 전체를 지금 다 쓰고 검증만 튜토리얼 7 뒤로 미룰 수 있다.

#### `app/evals/ablation.py` 확장 — 전략 어휘와 이름 규칙

**학습 행동 — 설정 스키마 정의:** `STRATEGY_ORDER`를 집합이 아니라 딕셔너리로 두는 이유를 확인하며 작성한다.

<!-- src: app/evals/ablation.py::RetrievalStrategy,EXPERIMENT_NAME -->
```python
type RetrievalStrategy = Literal["lexical", "vector", "hybrid"]
type ExperimentEvaluator = Callable[["ExperimentConfig"], Awaitable[RetrievalEvaluation]]

STRATEGY_ORDER = {"lexical": 0, "vector": 1, "hybrid": 2}
RANKER_ORDER = {"ts_rank_cd": 0, "bm25": 1}
RANKER_SLUG = {"ts_rank_cd": "ts-rank-cd", "bm25": "bm25"}
DEFAULT_LEXICAL_RANKERS: tuple[LexicalRanker, ...] = ("ts_rank_cd", "bm25")
EXPERIMENT_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
```

**코드에서 꼭 볼 것**

- **`STRATEGY_ORDER`는 전략 이름을 정수에 매핑하므로 유효성 검사와 정렬 키를 하나의 자료구조가 함께 제공한다.** 알파벳순이면 hybrid, lexical, vector 순이 되는데 이는 거꾸로다. lexical과 vector가 구성 경로이고 hybrid가 그 둘을 소비하는 경로이므로, 비교 표는 파이프라인 순서로 읽혀야 한다.
- `type` 문은 Python 3.12의 별칭 문법(PEP 695)이다. `RetrievalStrategy`를 우변이 지연 평가되는 이름 있는 별칭으로 선언하므로, 별칭은 파일 더 아래에서 정의되는 이름을 참조할 수 있다. (여기 평가기 별칭은 클래스 이름을 따옴표 문자열로 쓰므로, 그 지연 평가가 없어도 전방 참조로 해석된다.)
- `EXPERIMENT_NAME`은 kebab-case만 허용한다. 실험 이름이 아티팩트 파일 이름의 일부가 되므로 공백이나 슬래시가 들어가면 경로가 깨진다.

닫힌 어휘의 교과서적 자리인 `enum.Enum`을 쓰지 않는 이유가 있다. 이 값들은 설정 딕셔너리, JSON 아티팩트, 테스트 픽스처로 순수 문자열인 채 건너가야 하는데, enum 멤버는 순수 문자열이 아니다. 경계마다 `.value` 변환이나 str 서브클래스 우회가 필요해지고, 실험군 이름을 만드는 f-string은 변환을 한 번 잊는 순간 값 대신 멤버의 경로 표기를 파일 이름에 박아 넣는다. `Literal`과 작은 딕셔너리 두 개는 어휘를 데이터로 유지한다. 타입 검사기, 파일 이름, 아티팩트에서 같은 바이트다.

#### `app/evals/ablation.py` 확장 — 실험군 이름과 정렬 키

**학습 행동 — 직접 구현:** 두 함수를 작성하면서 `sort_key` 튜플의 네 요소가 각각 무엇을 고정하는지 확인한다.

<!-- src: app/evals/ablation.py::experiment_name,sort_key -->
```python
def experiment_name(
    target_text_chars: int,
    strategy: RetrievalStrategy,
    lexical_ranker: LexicalRanker | None,
) -> str:
    """Return the arm name, which must survive being used as a filename."""
    stem = f"structure-{target_text_chars}-{strategy}"
    return stem if lexical_ranker is None else f"{stem}-{RANKER_SLUG[lexical_ranker]}"


def sort_key(config: ExperimentConfig) -> tuple[int, int, int, str]:
    """Order arms by corpus, then retrieval path, then lexical ranker."""
    return (
        config.target_text_chars,
        STRATEGY_ORDER[config.strategy],
        -1 if config.lexical_ranker is None else RANKER_ORDER[config.lexical_ranker],
        config.name,
    )
```

**코드에서 꼭 볼 것**

- `experiment_name`은 `RANKER_SLUG`를 거쳐 이름을 만든다. `ts_rank_cd`의 밑줄을 파일 이름에 그대로 두면 `EXPERIMENT_NAME`의 kebab-case 검증에 걸리므로, 슬러그 표가 `ts-rank-cd`로 바꿔 붙인다.
- `sort_key` 튜플은 청크 크기, 전략 순서, 랭커 순서, 이름 순이다. 랭커가 없는 vector 실험군은 `-1`을 받는다. 이 치환은 해당 자리를 정수로 유지해 어떤 실험군 조합에서도 순서 비교가 정의되게 하고, "모든 실제 랭커보다 앞"으로 읽힌다. 마지막 요소 `name`은 앞의 세 값이 같을 때의 최종 동점 처리다.

### 2. 모순된 실험 설정을 만들 수 없게 한다

#### `app/evals/ablation.py` 확장 — 실험군 설정

**학습 행동 — 불변조건 구현:** `__post_init__`의 가드 체인을 직접 구현하고 — 검사 하나가 모순된 실험군 한 부류씩을 거부한다 — `to_dict()`를 중첩 구조로 만드는 이유를 확인한다.

<!-- src: app/evals/ablation.py::ExperimentConfig -->
```python
@dataclass(frozen=True, slots=True)
class ExperimentConfig:
    """One explicit chunking and retrieval experiment arm."""

    name: str
    target_text_chars: int
    strategy: RetrievalStrategy
    embedding_provider: str
    dimensions: int
    lexical_ranker: LexicalRanker | None = None
    k: int = 5
    candidate_k: int = 20
    rrf_k: int = 60

    def __post_init__(self) -> None:
        if EXPERIMENT_NAME.fullmatch(self.name) is None:
            raise ValueError("experiment name must be lowercase kebab-case")
        if self.target_text_chars <= 0 or self.dimensions <= 0:
            raise ValueError("chunk target and embedding dimensions must be positive")
        if self.strategy not in STRATEGY_ORDER:
            raise ValueError(f"unsupported retrieval strategy: {self.strategy}")
        if not self.embedding_provider.strip():
            raise ValueError("embedding_provider must be nonblank")
        if self.k <= 0 or self.candidate_k < self.k or self.rrf_k <= 0:
            raise ValueError("k, candidate_k, and rrf_k are inconsistent")
        if self.strategy == "vector":
            if self.lexical_ranker is not None:
                raise ValueError("vector retrieval must not name a lexical ranker")
        elif self.lexical_ranker not in RANKER_ORDER:
            raise ValueError(f"{self.strategy} retrieval requires an explicit lexical ranker")

    def to_dict(self) -> dict[str, object]:
        """Return stable nested config provenance for artifacts and baselines."""
        return {
            "name": self.name,
            "chunking": {
                "strategy": "structure-aware",
                "target_text_chars": self.target_text_chars,
                "golden_identity": "source-sha256-and-half-open-span",
            },
            "retrieval": {
                "strategy": self.strategy,
                "lexical_ranker": self.lexical_ranker,
                "k": self.k,
                "candidate_k": self.candidate_k,
                "rrf_k": self.rrf_k,
            },
            "embedding": {
                "provider": self.embedding_provider,
                "dimensions": self.dimensions,
            },
            "measurement": {
                "environment": "isolated-temporary-postgresql",
                "paid_api_calls": self.embedding_provider != "deterministic",
                "populated_corpus_embeddings_modified": False,
            },
        }
```

**코드에서 꼭 볼 것**

- `candidate_k < self.k`를 거부한다. 후보를 최종 k보다 적게 뽑으면 융합 뒤에 자를 대상이 없다. M2.5에서 같은 조건을 거부한 것과 짝을 이룬다.
- `to_dict()`는 평평한 딕셔너리가 아니라 **중첩 구조**를 만든다. `chunking`, `retrieval`, `embedding`, `measurement`으로 묶으면 나중에 축을 추가해도 기존 키의 위치가 바뀌지 않는다. 커밋된 아티팩트가 정확히 그 흡수 과정을 보여준다. 랭커 축은 자기 그룹 안의 새 키 하나로 도착했다.
- **`measurement` 블록은 `paid_api_calls`와 `populated_corpus_embeddings_modified`를 결과와 함께 저장한다.** 이 값이 없으면 나중에 결과를 읽는 사람이 그 실행에 비용이 발생했는지, 실제 코퍼스를 변경했는지 확인할 수 없다.
- `golden_identity`에는 `"source-sha256-and-half-open-span"`이 들어 있다. 정답 식별 방식이 바뀌면 설정 문자열이 달라지므로 기준선 비교가 자동으로 끊긴다.

> **개념 — 설정은 실험의 정체성이다**
>
> 튜토리얼 4는 "이 두 실행을 비교해도 되는가"를 기계적 규칙 하나로 줄였다. 스위트가 같고 정규화된 설정이 바이트 단위로 같을 것. 그 규칙이 이 dataclass의 진짜 역할을 정한다. 이것은 매개변수 주머니가 아니라 실험의 정체성이고, 직렬화된 설정은 몇 달 뒤 기준선 선택이 "같은 실험"을 고를 때 참조하는 유일한 근거다.
>
> 위험한 실패는 동작을 바꾸는데 기록에는 빠져 있는 축이다. 그 축만 다른 두 실행이 동일한 설정을 갖게 되고, 회귀 게이트는 둘을 매칭해 측정 조건의 변화를 품질 변화로 보고한다. 서두의 불변조건이 세 곳 출현을 요구하는 이유가 이것이다. 이름은 디렉터리를 훑는 사람에게, 파일 이름은 아티팩트 목록에서, config 블록은 기계에게 축을 보이게 한다. 셋 다 하나의 dataclass에서 생성되므로 서로 어긋날 수 없다.
>
> 정직한 경계도 있다. 설정은 이 계층이 아는 축만 기록한다. 히트가 정답으로 인정되는지를 정하는 규칙은 채점 계층에 살고 이 딕셔너리 어디에도 나타나지 않으므로, 그 규칙이 바뀌면 옛 실행과 새 실행이 비교 불가능한데도 비교 가능해 보이게 된다. 지문을 신뢰한다는 것은 그 경계가 정확히 어디를 지나는지 아는 일까지 포함한다.

> **개념 — 자기 폭발 반경을 기록하는 측정**
>
> 청크 목표 500인 실험군은 실제로 500자로 청킹된 코퍼스가 있어야 측정할 수 있다. 그래서 튜토리얼 7이 만드는 러너는 청크 목표마다 한 번씩 코퍼스를 다시 청킹하고 다시 인덱싱하며, 그 목표의 실험군들이 그것을 공유한다. 이 재구축을 운영 테이블에 대고 하면 시딩과 백필이 이미 비용을 치르고 만든 청크와 임베딩을 덮어쓴다. 그래서 러너는 연결이 닫히면 사라지는 임시 테이블 안에 각 코퍼스를 만들고, 이 블록의 environment 문자열은 그 격리를 선언하는 아티팩트의 상시 문구다. 커밋된 결과 하나하나가 "공유 상태가 이 숫자를 만들지도, 다치지도 않았다"는 주장을 지니고 다닌다.
>
> 나머지 두 필드는 옛 아티팩트를 읽는 사람이 사후에 재구성할 수 없는 두 질문에 답한다. 이 실행에 돈이 들었는가, 채워진 코퍼스를 수정했는가. 유료 플래그가 보수적으로 계산된다는 점은 알아 두어야 한다. 결정론적 공급자가 아니면 전부 유료로 표시되므로, 외부 API를 전혀 부르지 않는 로컬 sentence-transformers 실행도 true로 기록된다. 비용을 과장하는 조심이 비용을 숨기는 낙관보다 안전하지만, 알고 있어야 할 단순화다.

### 3. 결과를 나란히 놓는 형태

#### `app/evals/ablation.py` 확장 — 결과 레코드

**학습 행동 — 레코드 선언 작성:** `AblationOutcome`이 평가 결과와 함께 어떤 값을 저장하는지 확인한다.

<!-- src: app/evals/ablation.py::AblationOutcome,AblationReport -->
```python
@dataclass(frozen=True, slots=True)
class AblationOutcome:
    """One evaluated arm and its committed raw artifact path."""

    config: ExperimentConfig
    evaluation: RetrievalEvaluation
    artifact_path: Path


@dataclass(frozen=True, slots=True)
class AblationReport:
    """Deterministically ordered experiment outcomes."""

    outcomes: tuple[AblationOutcome, ...]

    def comparison_markdown(self) -> str:
        """Render a compact comparison table backed by raw artifacts."""
        lines = [
            "| Config | Chunk target | Retrieval | Lexical ranker | Recall@k | Hit rate@k "
            "| MRR | P95 ms | Raw |",
            "|---|---:|---|---|---:|---:|---:|---:|---|",
        ]
        for outcome in self.outcomes:
            score = outcome.evaluation.score
            lines.append(
                "| "
                f"{outcome.config.name} | {outcome.config.target_text_chars} | "
                f"{outcome.config.strategy} | {outcome.config.lexical_ranker or '-'} | "
                f"{score.recall_at_k:.6f} | "
                f"{score.hit_rate_at_k:.6f} | {score.mrr:.6f} | "
                f"{outcome.evaluation.latency.p95_ms:.3f} | "
                f"[{outcome.artifact_path.name}]({outcome.artifact_path.as_posix()}) |"
            )
        return "\n".join(lines)
```

**코드에서 꼭 볼 것**

- `AblationOutcome`은 `artifact_path`를 함께 저장한다. 비교 표의 한 행에서 그 실행의 원시 증거 파일로 바로 이동할 수 있다. "집계만 남기지 않는다"는 원칙이 자료구조에 새겨진 형태다.
- `comparison_markdown()`은 `:.6f`로 소수점 여섯 자리를 고정한다. 두 실험군의 차이가 0.001 수준일 때 반올림 때문에 같은 값으로 보이는 것을 막는다. 다만 이 폭의 의미는 정직하게 읽어야 한다. 이것은 렌더링 보장이지 분해능이 아니다. 골든 스위트는 정답 span을 한두 개씩 가진 양성 사례 24개를 채점하므로, 매크로 평균 재현율은 0.5/24 ≈ 0.0208보다 가는 눈금으로 움직일 수 없다. 소수점 둘째 자리 뒤의 숫자들은 텍스트 diff를 안정시킬 뿐 신호를 담지 않는다.
- 지연 시간 `p95_ms`를 품질 지표와 같은 표에 두므로 재현율만으로 실험군이 이길 수 없다. 이 백분위수를 어떻게 계산하는지, 왜 평균이 아니라 꼬리를 보고하는지는 튜토리얼 6의 주제다. 이 표에는 그 예고만 있으면 된다.

이 형태는 의도적으로 심심하다. 메모리에는 고정된 dataclass, 디스크에는 JSON 파일, 출력은 마크다운 표 하나. 업계의 대안은 MLflow나 Weights & Biases 같은 실험 트래커이고, 반사적으로가 아니라 이유를 들어 기각한다. 트래커는 여러 장비와 팀에 걸친 수백 번의 실행에서 제값을 하는데, 그 대가로 증거를 저장소 밖의 서비스로 옮긴다. 이 열 개의 실험군은 그것을 만든 코드와 같은 git 이력 안에서 리뷰되고, diff로 검토되고, 몇 년 뒤에도 텍스트 편집기로 읽혀야 한다. 표는 언제든 결과 레코드에서 재생성되고, 아티팩트가 기록의 원본으로 남는다.

### 4. 축이 둘일 때 순서를 정한다

원래 설계가 축 둘이었고 절 이름도 그대로다. 핀으로 고정된 코드는 셋을 교차하며, 랭커 축은 lexical 질의를 실제로 실행하는 전략들을 세분한다. 이 절이 실제로 정하는 것은 커진 행렬을 읽을 수 있게 유지하는 순서, 그리고 교차를 정직하게 유지하는 가드다.

#### `app/evals/ablation.py` 확장 — 실험 행렬과 아티팩트 이름

**학습 행동 — 조합 생성 구현:** 중첩 루프와 `vector`의 구조적 구멍을 직접 작성하고, 각 거부 가드를 선택한 이유를 설명할 수 있어야 한다.

<!-- src: app/evals/ablation.py::experiment_matrix,artifact_filename -->
```python
def experiment_matrix(
    *,
    target_text_chars: Sequence[int] = (500, 1200),
    strategies: Sequence[RetrievalStrategy] = ("lexical", "vector", "hybrid"),
    lexical_rankers: Sequence[LexicalRanker] = DEFAULT_LEXICAL_RANKERS,
    embedding_provider: str = "deterministic",
    dimensions: int = 384,
    k: int = 5,
    candidate_k: int = 20,
    rrf_k: int = 60,
) -> tuple[ExperimentConfig, ...]:
    """Build the sorted M3 chunking-by-retrieval-by-ranker comparison matrix.

    The ranker axis crosses only the strategies that actually run a lexical query.
    Crossing it with ``vector`` as well would evaluate the same retrieval path once
    per ranker and write two artifacts that differ only in a label they did not
    use, so ``vector`` contributes exactly one arm per chunk target.
    """
    if not target_text_chars or not strategies:
        raise ValueError("experiment matrix axes must not be empty")
    if len(set(target_text_chars)) != len(target_text_chars):
        raise ValueError("chunk targets must be unique")
    if len(set(strategies)) != len(strategies):
        raise ValueError("retrieval strategies must be unique")
    lexical_strategies = [strategy for strategy in strategies if strategy != "vector"]
    if lexical_strategies:
        if not lexical_rankers:
            raise ValueError(f"{lexical_strategies[0]} retrieval requires a lexical ranker")
        if len(set(lexical_rankers)) != len(lexical_rankers):
            raise ValueError("lexical rankers must be unique")

    configs = []
    for target in target_text_chars:
        for strategy in strategies:
            rankers: tuple[LexicalRanker | None, ...] = (
                (None,) if strategy == "vector" else tuple(lexical_rankers)
            )
            for ranker in rankers:
                configs.append(
                    ExperimentConfig(
                        name=experiment_name(target, strategy, ranker),
                        target_text_chars=target,
                        strategy=strategy,
                        embedding_provider=embedding_provider,
                        dimensions=dimensions,
                        lexical_ranker=ranker,
                        k=k,
                        candidate_k=candidate_k,
                        rrf_k=rrf_k,
                    )
                )
    return tuple(sorted(configs, key=sort_key))


def artifact_filename(recorded_at: datetime, config: ExperimentConfig) -> str:
    """Return a UTC timestamped stable artifact filename."""
    if recorded_at.tzinfo is None or recorded_at.utcoffset() is None:
        raise ValueError("recorded_at must be timezone-aware")
    timestamp = recorded_at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{config.name}.json"
```

**코드에서 꼭 볼 것**

- 마지막의 `sorted(configs, key=sort_key)`는 1절의 네 요소 정렬 키를 재사용한다. **청크 크기가 앞에 오므로 하나의 청킹 코퍼스를 공유하는 실험군들이 인접한다.** 러너는 그룹마다 코퍼스를 한 번만 만들면 되고, 비교하려는 축은 표에서 자기 옆에 있어야 보인다.
- 축의 중복 값을 거부한다. `target_text_chars=(500, 500)`이면 같은 실험이 두 번 실행되고 두 결과가 같은 아티팩트 파일에 기록된다.
- `artifact_filename`은 시간대 정보가 있는 값만 받고 UTC로 변환한다. 실행한 사람의 시간대에 따라 파일 이름이 달라지면 이름순 정렬이 시간 순서를 나타내지 못한다.
- 파일 이름이 `{timestamp}-{name}.json` 형식이므로 사전순 정렬이 곧 시간순 정렬이다.
- 기본 축이 만드는 열 실험군의 순서는 `tests/evals/test_04_ablation.py`에 튜플 하나하나까지 고정되어 있다. 행렬은 편의가 아니라 계약이다.

> **개념 — 평가 아티팩트의 일생**
>
> 탄생. 튜토리얼 7이 완성하는 명령이 이 파일의 실행 함수를 부르고, 실행 함수가 실험군마다 JSON 하나를 아티팩트 디렉터리에 쓴다. 이 저장소에서는 data/eval_runs다. 타임스탬프를 실행당 한 번만 읽으므로 한 실행의 파일들은 UTC 접두사 하나를 공유한다. 실행은 접두사 하나로 묶인 파일 가족이다.
>
> 상태. 커밋된 아티팩트는 증거이고, 증거에는 덧붙이기만 한다. 새 실행은 옛 파일을 절대 건드리지 않고 새 접두사를 받으므로, 디렉터리는 교체 대신 세대를 쌓는다. 이미 두 세대가 있다. 2026-08-12 실행은 랭커 축이 생기기 전의 실험군 파일 여섯 개를 갖고 있고(그 config 블록에는 랭커 키 자체가 없다), 완화 전 lexical 검색이 재현율 0.000000을 기록했다는 발견을 보존한다. 2026-08-24 실행은 현재 행렬의 실험군 파일 열 개를 갖는다.
>
> 읽기. 모듈의 발견 문서가 첫 세대를 읽고 출하된 평가 보고서가 둘째 세대를 읽는다. 두 비교 표의 모든 행이 자기가 요약한 원시 아티팩트로 링크되고, 이후 모듈들은 원시 파일 대신 그 보고서를 인용한다.
>
> 수명의 끝. 아티팩트를 지우는 것은 없다. 코퍼스 변경이나 축의 재정의는 이후 실행의 설정을 바꾸고, 그러면 튜토리얼 4 쪽에서 기준선 비교가 끊긴다. 옛 파일은 더는 존재하지 않는 시스템의 정직한 기록으로 남는다.

### 5. 실험군과 결과가 어긋나지 않게 한다

#### `app/evals/ablation.py` 완성 — 어블레이션 실행

**학습 행동 — 실행 순서 구현:** 가드 세 개를 직접 구현한다. 그중 하나는 입력이 아니라 평가기의 출력을 검사한다.

<!-- src: app/evals/ablation.py::run_ablation -->
```python
async def run_ablation(
    configs: Sequence[ExperimentConfig],
    evaluator: ExperimentEvaluator,
    *,
    artifact_dir: str | Path,
    recorded_at: datetime,
) -> AblationReport:
    """Evaluate sorted unique arms and write one raw artifact per arm."""
    if not configs:
        raise ValueError("ablation configs must not be empty")
    names = [config.name for config in configs]
    if len(names) != len(set(names)):
        raise ValueError("ablation config names must be unique")
    ordered = sorted(configs, key=sort_key)
    directory = Path(artifact_dir)
    outcomes: list[AblationOutcome] = []
    for config in ordered:
        evaluation = await evaluator(config)
        if evaluation.config != config.to_dict():
            raise ValueError(f"evaluation config does not match arm {config.name}")
        path = directory / artifact_filename(recorded_at, config)
        write_evaluation_artifact(path, evaluation)
        outcomes.append(
            AblationOutcome(
                config=config,
                evaluation=evaluation,
                artifact_path=path,
            )
        )
    return AblationReport(outcomes=tuple(outcomes))
```

**코드에서 꼭 볼 것**

- `if evaluation.config != config.to_dict()`가 그 다른 종류의 가드다. 평가기가 돌려준 결과가 **정말 이 실험군의 것인지** 확인한다. 이 검사가 없으면 평가기 버그가 500자 결과를 1200자 실험군의 아티팩트에 저장하고, 그 파일을 읽는 사람은 영원히 알아챌 수 없다. 서두의 불변조건이 집행되는 순간이기도 하다. 이름, 파일 이름, 기록되는 설정이 바로 여기, 쓰는 시점에 같은 dataclass에서 나오므로 세 곳의 출현이 어긋날 수 없다.
- 이 함수에서도 `sorted`를 다시 호출한다. `experiment_matrix`가 이미 정렬하지만 호출자가 직접 만든 목록을 넘길 수 있으므로, 아티팩트 순서가 입력 순서에 의존하지 않게 한다.
- 이름 중복을 거부한다. 이름이 같으면 두 번째 아티팩트가 첫 번째를 덮어쓴다.
- 평가기를 **주입받는다.** 그래서 테스트가 데이터베이스와 임베딩 공급자 없이 이 계층의 실행 순서와 가드를 검증할 수 있다.

### 튜토리얼 7 이후 검증할 계약

아래 계약을 검사하는 집중 테스트는 `retrieval_eval.py`의 레코드와 실행 함수가 모두 준비된 튜토리얼 7 뒤에 실행한다. 지금은 `ablation.py` 작성만 완료한다.

| 테스트가 깨뜨리는 값 | 지키는 계약 |
|---|---|
| `candidate_k`가 `k`보다 작은 설정 | 융합이 자를 것이 없는 실험군이 만들어지지 않는다. |
| 중복된 청크 목표 또는 전략 | 같은 실험이 두 번 돌며 아티팩트를 덮어쓰지 않는다. |
| naive `datetime` | 아티팩트 이름이 실행 환경의 시간대에 의존하지 않는다. |
| 실험군과 다른 설정을 돌려준 평가기 | 결과가 엉뚱한 실험군 파일에 저장되지 않는다. |
| 순서만 다른 같은 실험군 목록 | 아티팩트 순서가 입력 순서에 의존하지 않는다. |

### 여기까지 왔을 때 설명할 수 있어야 하는 것

다음 질문의 답은 앞에서 **굵게 표시한 핵심 문장**에 있다. 각 답을 해당 코드와 연결해 설명해 본다.

- **어블레이션에서 한 번에 축 하나만 바꾸는 이유는 무엇인가?**
  - **답:** 두 축을 함께 바꾸면 결과 차이의 원인을 어느 축에도 돌릴 수 없기 때문이다.
- **`STRATEGY_ORDER`가 집합이 아니라 딕셔너리인 이유는 무엇인가?**
  - **답:** 딕셔너리는 유효한 전략인지 검사하는 동시에 안정적인 파이프라인 순서 번호를 제공하지만, 집합에는 결정적인 순서가 없다.
- **`measurement` 블록이 `to_dict()`에서 결과와 함께 저장돼야 하는 이유는 무엇인가?**
  - **답:** 유료 호출 여부와 실제 코퍼스 수정 여부를 보존해, 나중에 결과를 읽는 사람이 그 숫자가 나온 조건과 비용을 알 수 있게 한다.
- **정렬 키에서 청크 크기가 전략보다 앞에 오는 이유는 무엇인가?**
  - **답:** 같은 청킹 코퍼스를 공유하는 전략들을 묶어 행렬 순서를 안정시키고, 그 그룹의 코퍼스를 한 번만 만들 수 있게 한다.
- **평가기가 돌려준 설정을 다시 확인하지 않으면 어떤 오류가 영원히 감춰지는가?**
  - **답:** 한 실험군의 결과가 다른 실험군의 이름으로 저장되어, 지표가 잘못된 설정에 영구적으로 귀속되는 오류가 감춰진다.

---

[← 이전: 회귀 비교](04-regression.md) · [모듈 개요](../03-build.md) · [다음: 평가 레코드 →](06-evaluation-records.md)
