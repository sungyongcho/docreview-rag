# M3 구현 — 모든 숫자에 근거를 달기

## M2에서 세 번이나 미룬 결정들

앞 장을 마치며 이렇게 적었다.

- HNSW 인덱스는 **나중에** 재보고 결정한다
- 재순위화는 만들되 **켜지 않는다**
- `rrf_k = 60`은 **실험 대상**이다

전부 "측정하면 알 수 있다"고 미룬 것들이다. 이제 그 측정 장치를 만든다.

문제는 측정 자체가 쉽지 않다는 것이다. "재현율 0.82"라는 숫자를 얻는 건 어렵지 않다. 그 숫자를 **믿을 수 있게** 만드는 게 어렵다.

- 어떤 근거를 정답으로 놓고 잰 건가?
- 어떤 설정으로 돌린 건가?
- 어제 잰 0.79와 오늘의 0.82를 비교해도 되는 건가?

이 셋에 답할 수 없는 점수는 있으나 마나다. 튜닝하다 보면 반드시 "이게 개선인가 노이즈인가"를 판단해야 하는 순간이 오는데, 그때 답을 못 하면 감으로 결정하게 된다.

## 이 장에서 만들 것

| 단계 | 개념 | 정식 파일 | 집중 테스트 |
|---|---|---|---|
| M3.1 | 골든 증거는 변하지 않는 원문 식별자 | `types.py`, `loader.py`, `__init__.py` | `test_01_contract.py`, `test_02_loader.py` |
| M3.2 | 순위 품질은 순수 결정론적 계산 | `scoring.py` | `test_02_scoring.py` |
| M3.3 | 같은 구성끼리만 기준선을 공유 | `regression.py`, 기존 `EvalResult` | `test_03_regression.py` |
| M3.4 | 실험은 원시 증거와 비용을 보존 | `ablation.py`, `retrieval_eval.py`, `__main__.py` | `test_04_ablation.py`, `test_05_runner.py` |
| M3.5 | 셋의 성장은 이어 붙이기가 아니라 게이트를 통과한 큐레이션 | `curation.py`, `breakdown.py` | `test_07_curation.py` |

```text
raw corpus + manifest + golden JSON   →  strict GoldenCase values
GoldenCase spans + ranked ChunkHit    →  deterministic SuiteScore
SuiteScore + canonical config         →  regression comparison  →  EvalResult
experiment matrix                     →  isolated PostgreSQL corpus → raw artifacts + budget evidence
candidate JSON + review decisions     →  gated golden growth + taxonomy breakdown
```

전 계층을 관통하는 원칙이 하나 있다. **원시 원문 해시와 반열린 범위가 계층마다 식별자로 유지된다.** M3는 검색 동작을 측정할 뿐, 결과를 통과시키려고 골든 증거를 고쳐 쓰지 않는다.

## 시작 조건

잠긴 환경을 설치하고 루프백 PostgreSQL을 띄운 뒤 M2 경계를 검증한다.

```bash
uv sync --group dev
docker compose up -d db
uv run pytest tests/retrieval -q
```

M3.1~M3.3의 계약 테스트는 선택적 영속화 검증을 빼면 데이터베이스가 필요 없다. M3.4는 임시 PostgreSQL 테이블을 쓰므로 실험이 실제 코퍼스 벡터를 덮어쓰지 않는다.

`zero`에서 작업하고 `_mine.py`나 대체 테스트 모듈을 만들지 않는다.


---

## 튜토리얼 — 아홉 번에 나눠 만든다

M3는 파일 열 개, 소스 2,210줄을 만든다. 한 번에 앉아서 끝낼 분량이 아니라 아홉 구간으로 나눠 뒀다. 각 문서는 **읽고 구현하는 데 30분 안쪽**을 목표로 한다.

| 문서 | 체크포인트 | 만드는 파일 | 대략 |
|---|---|---|---|
| [1. 골든 타입](tutorial/01-golden-types.md) | M3.1 | `types.py` | 20분 |
| [2. 골든 로더](tutorial/02-golden-loader.md) | M3.1 | `loader.py`, `__init__.py` | 30분 |
| [3. 채점](tutorial/03-scoring.md) | M3.2 | `scoring.py` | 25분 |
| [4. 회귀 비교](tutorial/04-regression.md) | M3.3 | `regression.py` | 30분 |
| [5. 어블레이션](tutorial/05-ablation.md) | M3.4 | `ablation.py` | 25분 |
| [6. 평가 레코드](tutorial/06-evaluation-records.md) | M3.4 | `retrieval_eval.py` (앞부분) | 30분 |
| [7. 평가 실행](tutorial/07-evaluation-run.md) | M3.4 | `retrieval_eval.py` (실행) | 30분 |
| [8. 격리 실행과 CLI](tutorial/08-evaluation-cli.md) | M3.4 | `retrieval_eval.py` (마무리), `__main__.py` | 30분 |
| [9. 골든 큐레이션](tutorial/09-golden-curation.md) | M3.5 | `curation.py`, `breakdown.py` | 30분 |

순서대로 따라간다. 각 구간 끝의 집중 테스트가 통과하지 않으면 다음으로 넘어가지 않는다.

아래 [완성 기준본](#완성-기준본--정식-구현-전체)은 학습을 건너뛰는 지름길이 아니라 **자기 구현을 맞춰 보는 기준**이다.

---

## 숫자가 이상할 때

게이트가 실패하면 실패한 원시 파일부터 보존한다. 그다음 **가장 낮은 계층부터** 올라오며 조사한다.

```
source identity  →  span math  →  comparable config  →  retrieval
```

아래층이 틀렸으면 위층 숫자는 전부 의미가 없으므로, 위에서부터 보면 시간을 낭비한다.

그리고 이 장에서 가장 중요한 규칙 하나. **실험을 통과시키려고 골든 범위를 고치지 않는다.** 정답을 결과에 맞추기 시작하면 이 모든 장치가 무의미해진다. 구체적인 증상은 [버그와 설계 함정](04-bugs.md)을, 최종 명령 순서는 [검증](05-verify.md)을 참고한다.

### 측정 경계 — 검색 평가와 생성 평가는 다르다

이 장의 Recall@k, Hit rate@k, MRR은 모두 **검색 평가**다. 정답을 만드는 데 필요한 원문 범위가 상위 결과에 들어왔는지는 말할 수 있지만, 그 근거를 받은 LLM이 사실에 맞는 답을 썼는지는 말할 수 없다. 검색 재현율이 1.0이어도 모델은 숫자를 잘못 옮기거나, 서로 다른 연도의 값을 섞거나, 근거에 없는 결론을 덧붙일 수 있다.

반대도 구분해야 한다. 최종 답변이 틀렸다고 해서 검색이 반드시 실패한 것은 아니다. 정답 근거가 검색됐는데 생성 단계가 잘못 읽었을 수 있다. 그래서 원인을 찾을 때는 **검색 실패**와 **생성 실패**를 별도 계층으로 측정해야 한다. 현재 M3는 앞쪽만 구현하며, M4도 인용 출처를 검증할 뿐 주장 단위의 사실성을 채점하지는 않는다.

---

## 아홉 구간을 똑같이 어렵게 읽지 않는다

체크포인트는 다섯인데 문서가 아홉인 이유는 M3.4가 크기 때문이다. 성격으로 나누면 이렇다.

| 성격 | 체크포인트 | 학습 행동 |
|---|---|---|
| 계약 선언 | M3.1 | **모델 선언 작성** — 정답을 무엇으로 표현할지 정하는 것이 전부다 |
| 알고리즘 | M3.2 | 지표 계산을 **직접 구현** — 여기에 시간을 쓴다 |
| 판정 규칙 | M3.3 | 비교 가능성 판정을 **직접 구현** |
| 실행과 배치 | M3.4 | **구조 작성 후 호출 순서 검토** |
| 데이터 거버넌스 | M3.5 | 큐레이션 게이트를 **직접 구현** — 분해는 M3.2를 재사용한다 |

M3.1에서 정답을 청크 ID가 아니라 **원문 좌표 범위**로 정의하는 결정이 이 장 전체를 좌우한다. 그 한 줄이 바뀌면 나머지 여덟 문서의 전제가 무너진다.

## 처음 만나는 개념

검색 품질 지표는 이름이 비슷해서 섞이기 쉽다. 각각이 답하는 질문이 다르다.

**골든셋.** 질문과 그 정답 근거를 사람이 미리 정해 둔 목록이다. 여기서 정답은 "청크 12번"이 아니라 **원문의 문자 범위**로 적는다. 청크 크기를 바꾸면 청크 ID는 전부 달라지지만 원문 좌표는 그대로이므로, 청킹 전략을 바꿔 가며 같은 골든셋으로 비교할 수 있다.

**Recall@k.** "정답 근거 중 상위 k개 안에 몇 개가 들어왔나"를 묻는다. 정답이 5개인데 상위 10개 안에 3개가 들어왔으면 0.6이다. **정답을 기준으로 세지 검색 결과를 기준으로 세지 않는다.**

**Hit rate@k.** "상위 k개 안에 정답이 하나라도 있나"를 묻는 이진 값이다. Recall@k보다 무디지만, 사용자가 답을 아예 못 얻는 경우를 직접 센다.

**MRR(Mean Reciprocal Rank).** "첫 정답이 몇 등이었나"를 묻는다. 1등이면 1, 2등이면 1/2, 3등이면 1/3을 주고 질문마다 평균한다. 정답 개수를 세는 대신 **첫 정답까지의 거리**를 본다. 화면에 상위 몇 개만 보여 주는 시스템에서 중요한 지표다.

**어블레이션(ablation).** 설정 하나만 바꿔 가며 돌려서 그 설정이 결과에 얼마나 기여하는지 재는 실험이다. `rrf_k`를 60에서 10으로 바꾸면 재현율이 얼마나 달라지는가 같은 질문에 답한다. 여러 개를 동시에 바꾸면 무엇이 기여했는지 알 수 없으므로 **한 번에 하나만** 바꾼다.

## M3.1 — 정답을 원문 좌표로 고정한다

골든 증거를 청크 ID로 적으면 청크 크기를 바꾸는 순간 골든셋 전체가 무효가 된다. 그래서 정답을 원본 문서의 SHA-256과 반열린 문자 범위로 적는다. M1.3이 인용을 좌표 기반으로 설계한 이유가 여기서 값을 한다. 로더는 그 JSON을 엄격하게 읽어, 범위가 뒤집혔거나 해시가 코퍼스와 다르면 조용히 넘어가지 않고 거부한다.

**문서:** [1. 골든 타입](tutorial/01-golden-types.md), [2. 골든 로더](tutorial/02-golden-loader.md) · **통과 기준:** `uv run pytest tests/evals/test_01_contract.py tests/evals/test_02_loader.py -q`

## M3.2 — 채점을 순수 계산으로 유지한다

채점 계층에는 I/O가 하나도 없다. 골든 범위와 순위 매겨진 히트를 받아 숫자를 돌려줄 뿐이다. 이 제약이 중요한 이유는 단순하다 — 채점이 데이터베이스를 읽으면 점수가 달라졌을 때 검색이 변한 건지 데이터가 변한 건지 구분할 수 없다. 범위 일치는 정확 일치가 아니라 겹침 비율로 판정하고, 사례별 평균(매크로)을 써서 정답이 많은 질문이 결과를 지배하지 않게 한다.

**문서:** [3. 채점](tutorial/03-scoring.md) · **통과 기준:** `uv run pytest tests/evals/test_02_scoring.py -q`

## M3.3 — 회귀 기준선

어제의 0.79와 오늘의 0.82를 비교하려면 두 실행이 **같은 것을 잰 것**이어야 한다. 골든셋이 바뀌었거나, top-k가 달라졌거나, 임베딩 모델이 교체됐으면 두 숫자는 비교 대상이 아니다. 그래서 기준선에 구성 지문을 함께 저장하고, 지문이 다르면 개선도 악화도 선언하지 않는다. 비교 불가를 조용한 통과로 처리하는 것이 이 계층에서 가장 위험한 실수다.

**문서:** [4. 회귀 비교](tutorial/04-regression.md) · **통과 기준:** `uv run pytest tests/evals/test_03_regression.py -q`

## M3.4 — 실험은 원시 증거와 비용을 보존한다

이제 M2에서 미룬 질문들에 답한다. 어블레이션은 설정 하나만 바꿔 가며 돌리고, 각 실행의 원시 산출물과 토큰·비용을 함께 남긴다. 요약 숫자만 남기면 나중에 "이 값이 어떻게 나왔나"에 답할 수 없다. 실행은 임시 PostgreSQL 테이블에서 돌아 실제 코퍼스 벡터를 덮어쓰지 않는다.

**문서:** [5. 어블레이션](tutorial/05-ablation.md) ~ [8. 격리 실행과 CLI](tutorial/08-evaluation-cli.md) · **통과 기준:** `uv run pytest tests/evals/test_04_ablation.py tests/evals/test_05_runner.py tests/evals/test_06_postgres.py -q`

## M3.5 — 셋의 성장은 게이트를 통과한 큐레이션이다

골든 셋은 이제 측정 도구다. 그러니 셋을 키우는 일은 이어 붙이기가 아니라 관리되는 파이프라인이어야 한다. 생성된 후보는 별도의 `m3s` 네임스페이스로 들어오고, 기계 게이트가 로더가 신뢰하는 모든 기계적 증명에 중복 검사와 span 폭 검사를 더해 다시 돌리며, 명시적으로 기록된 사람의 결정만이 승격으로 다음 `m3c` id를 발급하게 한다 — 입장은 인증이 아니므로 승격 뒤에도 저자 승인 대기다. 같은 체크포인트가 집계 재현율 하나를 category별 실패 지도로 바꾸는 분류 체계 분해를 더한다.

**문서:** [9. 골든 큐레이션](tutorial/09-golden-curation.md) · **통과 기준:** `uv run pytest tests/evals/test_07_curation.py -q`

## 여기까지 왔을 때 설명할 수 있어야 하는 것

- **골든 정답을 청크 ID가 아니라 원문 좌표로 적는 이유는 무엇인가?**
  - **답:** 같은 공시를 다시 청킹해도 원문 좌표는 유지되지만 청크 ID는 바뀐다. 따라서 하나의 골든 세트로 여러 청크 크기를 비교할 수 있다.
- **Recall@k와 MRR이 각각 답하는 질문은 어떻게 다른가?**
  - **답:** Recall@k는 상위 k개 안에서 일치한 골든 구간의 비율을 측정한다. MRR은 같은 상위 k개 안의 첫 일치 순위의 역수를 쓰며, 그 안에 일치가 없으면 0이다.
- **채점 계층에 I/O가 하나라도 있으면 무엇을 판단할 수 없게 되는가?**
  - **답:** 점수 변화가 검색 변화 때문인지, 측정 도구 안의 외부 상태 변화나 I/O 실패 때문인지 확실히 판단할 수 없다.
- **구성 지문이 다른 두 점수를 비교하면 어떤 잘못된 결론이 나오는가?**
  - **답:** 서로 다른 실험 조건에서 생긴 차이를 검색 시스템의 개선이나 회귀라고 잘못 결론 내릴 수 있다.
- **어블레이션에서 한 번에 하나만 바꾸는 이유는 무엇인가?**
  - **답:** 다른 축을 모두 고정해야 점수 차이의 원인을 시험한 설정 하나에 돌릴 수 있다.
- **요약 숫자만 남기고 원시 산출물을 버리면 나중에 무엇을 못 하게 되는가?**
  - **답:** 집계를 만든 실제 히트와 증거가 사라져, 결과를 사례별로 감사하거나 실패 원인을 진단할 수 없다.
- **검색 평가가 통과해도 최종 답변이 틀릴 수 있는 이유는 무엇인가?**
  - **답:** M3에는 절대적인 검색 품질 통과 기준이 없다. 지표는 상위 k개 결과가 0.05 IoU 규칙으로 주석 구간과 얼마나 겹치는지를 측정할 뿐 증거의 완전성이나 주장 근거를 증명하지 않으며, 생성 계층은 여전히 증거를 잘못 읽거나 근거 없는 주장을 더할 수 있다.
- **생성된 후보가 `m3c` id를 절대 달지 않는 이유는 무엇인가?**
  - **답:** 골든 네임스페이스는 동결된 정답지라서, id는 명시적 승인 뒤 승격에서만 발급된다. 그보다 이르면 검수되지 않은 주장이 측정에 들어갈 길이 생긴다.

## 이 모듈이 다음 모듈에 넘기는 것

M3까지가 **검색 시스템**이다. 여기서부터 M4는 그 위에 LLM을 얹는다.

| M3가 만든 것 | 받는 곳 | 거기서 하는 일 |
|---|---|---|
| 검증된 설정(청크 크기·검색 전략·k) | **M4, M5** | 프로덕션 기본값의 근거 |
| `EvalResult` 회귀 기준선 | **M7** | CI에서 품질 게이트 |
| 예산 측정값 | **M5, M7** | 지연 예산의 근거 |
| 골든 케이스 28개 | **M4** | 워크플로 평가의 출발점 |
| 원시 산출물 | **M6** | 데모에서 보여줄 증거 |

M3의 진짜 산출물은 코드가 아니라 **"이 설정이 낫다"고 말할 근거**다. 여기까지 오면 파라미터를 감이 아니라 숫자로 정할 수 있다.

다음 장 M4는 이 검색 위에 LLM 워크플로를 세운다. 그런데 LLM이 들어오는 순간 새로운 문제가 생긴다 — **출력이 결정론적이지 않고, 비용이 들고, 틀린 답을 자신 있게 말한다.** M4는 그래서 예산 상한, 스키마 검증, 인용 출처 검사(check 노드)를 워크플로에 못 박는다. M3에서 만든 "모든 숫자에 근거를 단다"는 원칙이 거기서 "모든 인용을 검색된 근거로 되돌릴 수 있게 한다"로 이어진다. 문장 자체의 사실성 평가는 별도 과제로 남는다.

<!-- complete-files:start -->
## 완성 기준본 — 정식 구현 전체

아래 정식 경로를 직접 생성하거나 교체한다. `_mine.py` 또는 별도의 학습자용 복사 모듈을 만들지 않는다. 앞의 발췌 코드는 개별 결정을 설명하고, 이 절의 코드 블록은 체크포인트를 마친 뒤 대조할 완성 파일이다. 표시된 타입 어노테이션과 영어 주석을 유지하며 `pyproject.toml`을 Ruff 정책의 기준으로 사용한다.

### M3.1 — 완성 체크포인트

#### 생성 또는 교체 `app/evals/__init__.py`

<!-- file: app/evals/__init__.py -->
```python
"""Public contracts and loader for the M3 evaluation milestone."""

from app.evals.loader import (
    DEFAULT_GOLDEN_PATH,
    DEFAULT_MANIFEST_PATH,
    GoldenDataError,
    load_golden_cases,
    validate_golden_sources,
)
from app.evals.types import (
    ExpectedLabel,
    GoldenCase,
    GoldenCategory,
    GoldenFacet,
    GoldenSpan,
    GoldenTag,
)

__all__ = [
    "DEFAULT_GOLDEN_PATH",
    "DEFAULT_MANIFEST_PATH",
    "ExpectedLabel",
    "GoldenCase",
    "GoldenCategory",
    "GoldenDataError",
    "GoldenFacet",
    "GoldenSpan",
    "GoldenTag",
    "load_golden_cases",
    "validate_golden_sources",
]
```

#### 생성 또는 교체 `app/evals/types.py`

<!-- file: app/evals/types.py -->
```python
"""Strict, source-stable value objects for retrieval evaluation data."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr
from pydantic.functional_validators import field_validator, model_validator

GoldenCategory = Literal["simple_lookup", "exact_number", "multi_hop", "absent"]
GoldenFacet = Literal["factual", "comparison", "risk", "policy", "numeric"]
ExpectedLabel = Literal["SUPPORTED", "NOT_IN_DOCS"]
GoldenTag = Annotated[StrictStr, Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")]
SourceSha256 = Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]


class GoldenSpan(BaseModel):
    """One half-open answer span in an immutable raw filing snapshot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    doc_id: Annotated[StrictStr, Field(min_length=1, max_length=32)]
    source_sha256: SourceSha256
    start_char: Annotated[StrictInt, Field(ge=0)]
    end_char: Annotated[StrictInt, Field(gt=0)]

    @model_validator(mode="after")
    def validate_half_open_span(self) -> Self:
        """Reject empty or reversed source intervals."""
        if self.end_char <= self.start_char:
            raise ValueError("end_char must be greater than start_char")
        return self


class GoldenCase(BaseModel):
    """One reviewed-question candidate and its retrieval ground truth."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: Annotated[StrictStr, Field(pattern=r"^m3c-[0-9]{2}$")]
    question: Annotated[StrictStr, Field(min_length=1)]
    category: GoldenCategory
    facet: GoldenFacet
    tags: tuple[GoldenTag, ...]
    answers: tuple[GoldenSpan, ...]
    expected_label: ExpectedLabel
    reference_answer: Annotated[StrictStr, Field(min_length=1)]
    note: Annotated[StrictStr, Field(min_length=1)]
    curation_status: Literal["agent-curated"]
    approval_status: Literal["pending-author-approval"]
    human_verified: Literal[False]

    @field_validator("human_verified", mode="before")
    @classmethod
    def require_literal_false(cls, value: object) -> object:
        """Reject false-like values that could imply an ambiguous review status."""
        if value is not False:
            raise ValueError("human_verified must be the JSON boolean false")
        return value

    @field_validator("question", "reference_answer", "note", mode="after")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        """Reject strings that contain only whitespace."""
        if not value.strip():
            raise ValueError("text fields must not be blank")
        return value

    @field_validator("tags", mode="after")
    @classmethod
    def reject_duplicate_tags(cls, tags: tuple[str, ...]) -> tuple[str, ...]:
        """Keep tag membership unambiguous without silently rewriting input."""
        if len(tags) != len(set(tags)):
            raise ValueError("tags must be unique")
        return tags

    @model_validator(mode="after")
    def validate_label_and_answers(self) -> Self:
        """Keep positive and absent-case contracts mutually exclusive."""
        identities = {
            (answer.doc_id, answer.source_sha256, answer.start_char, answer.end_char)
            for answer in self.answers
        }
        if len(identities) != len(self.answers):
            raise ValueError("answer spans must be unique within a case")

        if self.category == "absent":
            if self.answers:
                raise ValueError("absent cases must not contain answer spans")
            if self.expected_label != "NOT_IN_DOCS":
                raise ValueError("absent cases must expect NOT_IN_DOCS")
            if self.reference_answer != "NOT_IN_DOCS":
                raise ValueError("absent cases must use the NOT_IN_DOCS reference answer")
        else:
            if not self.answers:
                raise ValueError("positive cases must contain at least one answer span")
            if self.expected_label != "SUPPORTED":
                raise ValueError("positive cases must expect SUPPORTED")
            if self.reference_answer == "NOT_IN_DOCS":
                raise ValueError("positive cases must include a supported reference answer")
        return self
```

#### 생성 또는 교체 `app/evals/loader.py`

<!-- file: app/evals/loader.py -->
```python
"""Load strict golden cases and bind every positive span to the raw corpus."""

from __future__ import annotations

from collections.abc import Iterable
import hashlib
import json
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup
from pydantic import TypeAdapter, ValidationError

from app.evals.types import GoldenCase

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GOLDEN_PATH = REPO_ROOT / "data" / "golden" / "retrieval.json"
DEFAULT_MANIFEST_PATH = REPO_ROOT / "data" / "corpus" / "manifest.json"
GOLDEN_CASES = TypeAdapter(list[GoldenCase])


class GoldenDataError(ValueError):
    """A golden file or its cited source snapshot violates the M3 contract."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise GoldenDataError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _read_json(path: Path) -> object:
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except GoldenDataError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GoldenDataError(f"cannot read valid UTF-8 JSON from {path}: {exc}") from exc


def _golden_files(path: Path) -> list[Path]:
    if path.is_dir():
        files = sorted(path.glob("*.json"))
        if not files:
            raise GoldenDataError(f"no golden JSON files found in {path}")
        return files
    return [path]


def _validate_unique_cases(cases: Iterable[GoldenCase]) -> None:
    ids: set[str] = set()
    questions: set[str] = set()
    answer_identities: set[tuple[str, str, int, int]] = set()
    for case in cases:
        if case.id in ids:
            raise GoldenDataError(f"duplicate golden case id: {case.id}")
        ids.add(case.id)

        normalized = " ".join(case.question.casefold().split())
        if normalized in questions:
            raise GoldenDataError(f"duplicate normalized question: {case.question}")
        questions.add(normalized)

        for answer in case.answers:
            identity = (
                answer.doc_id,
                answer.source_sha256,
                answer.start_char,
                answer.end_char,
            )
            if identity in answer_identities:
                raise GoldenDataError(f"duplicate answer span identity in {case.id}")
            answer_identities.add(identity)


def _resolve_source_path(file_name: str, manifest_path: Path) -> Path:
    source = Path(file_name)
    if source.is_absolute() and source.is_file():
        return source

    bases = [Path.cwd(), REPO_ROOT, manifest_path.resolve().parent]
    bases.extend(manifest_path.resolve().parents)
    for base in bases:
        candidate = (base / source).resolve()
        if candidate.is_file():
            return candidate
    raise GoldenDataError(f"manifest source file does not exist: {file_name}")


def _manifest_sources(manifest_path: Path) -> dict[str, Path]:
    payload = _read_json(manifest_path)
    if not isinstance(payload, list):
        raise GoldenDataError("corpus manifest root must be a JSON array")

    sources: dict[str, Path] = {}
    for index, entry in enumerate(payload):
        if not isinstance(entry, dict):
            raise GoldenDataError(f"manifest entry {index} must be an object")
        try:
            ticker = entry["ticker"]
            report_date = entry["report_date"]
            file_name = entry["file"]
        except KeyError as exc:
            raise GoldenDataError(f"manifest entry {index} is missing {exc.args[0]}") from exc
        if not all(isinstance(value, str) and value for value in (ticker, report_date, file_name)):
            raise GoldenDataError(f"manifest entry {index} has invalid identity fields")
        if len(report_date) < 4 or not report_date[:4].isdigit():
            raise GoldenDataError(f"manifest entry {index} has an invalid report_date")

        doc_id = f"{ticker}-FY{report_date[:4]}"
        if doc_id in sources:
            raise GoldenDataError(f"duplicate manifest document id: {doc_id}")
        sources[doc_id] = _resolve_source_path(file_name, manifest_path)
    return sources


def validate_golden_sources(
    cases: Iterable[GoldenCase],
    manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
) -> None:
    """Verify each positive span against its exact UTF-8 source and SHA-256."""
    sources = _manifest_sources(Path(manifest_path))
    cache: dict[str, tuple[str, str]] = {}

    for case in cases:
        for answer in case.answers:
            source_path = sources.get(answer.doc_id)
            if source_path is None:
                raise GoldenDataError(f"{case.id} cites unknown corpus document {answer.doc_id}")
            if answer.doc_id not in cache:
                try:
                    source_bytes = source_path.read_bytes()
                    raw_source = source_bytes.decode("utf-8")
                except (OSError, UnicodeDecodeError) as exc:
                    raise GoldenDataError(
                        f"cannot read UTF-8 source for {answer.doc_id}: {exc}"
                    ) from exc
                cache[answer.doc_id] = (
                    raw_source,
                    hashlib.sha256(source_bytes).hexdigest(),
                )

            raw_source, source_sha256 = cache[answer.doc_id]
            if answer.source_sha256 != source_sha256:
                raise GoldenDataError(f"{case.id} source hash does not match {answer.doc_id}")
            if answer.end_char > len(raw_source):
                raise GoldenDataError(
                    f"{case.id} span ends beyond {answer.doc_id}: "
                    f"{answer.end_char} > {len(raw_source)}"
                )
            evidence = BeautifulSoup(
                raw_source[answer.start_char : answer.end_char],
                "html.parser",
            ).get_text(" ", strip=True)
            if not evidence:
                raise GoldenDataError(
                    f"{case.id} span has no visible source evidence in {answer.doc_id}"
                )


def load_golden_cases(
    path: str | Path = DEFAULT_GOLDEN_PATH,
    *,
    manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
) -> list[GoldenCase]:
    """Load one file or a directory of files and validate all source citations."""
    cases: list[GoldenCase] = []
    for golden_path in _golden_files(Path(path)):
        payload = _read_json(golden_path)
        if not isinstance(payload, list):
            raise GoldenDataError(f"golden file root must be a JSON array: {golden_path}")
        try:
            cases.extend(GOLDEN_CASES.validate_python(payload))
        except ValidationError as exc:
            raise GoldenDataError(f"invalid golden cases in {golden_path}: {exc}") from exc

    _validate_unique_cases(cases)
    validate_golden_sources(cases, manifest_path)
    return cases
```

체크포인트를 실행한다.

```bash
uv run pytest tests/evals/test_01_contract.py tests/evals/test_02_loader.py -q
```

**예상 결과:** 선택한 모든 오프라인 테스트가 통과한다. 명시된 통합 테스트는 외부 서비스를 사용할 수 없을 때만 건너뛸 수 있다.

**중단 조건:** 테스트가 실패하거나 필수 정식 심볼이 없어서 건너뛰면 진행하지 않는다.

**디버깅:** 같은 pytest 대상을 `-vv --tb=long`으로 다시 실행하고 첫 번째로 실패한 계약을 고친 뒤 진행한다.

### M3.2 — 완성 체크포인트

#### 생성 또는 교체 `app/evals/scoring.py`

<!-- file: app/evals/scoring.py -->
```python
"""Deterministic span-overlap scoring for retrieval evaluation."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from app.evals.types import GoldenSpan
from app.retrieval.types import ChunkHit

IOU_THRESHOLD: Final[float] = 0.05


@dataclass(frozen=True, slots=True)
class CaseScore:
    """Retrieval metrics and matching provenance for one positive golden case."""

    case_id: str
    k: int
    gold_span_count: int
    matched_gold_count: int
    recall_at_k: float
    hit_at_k: float
    reciprocal_rank: float
    first_relevant_rank: int | None


@dataclass(frozen=True, slots=True)
class SuiteScore:
    """Macro-averaged retrieval metrics plus deterministic per-case results."""

    k: int
    case_count: int
    recall_at_k: float
    hit_rate_at_k: float
    mrr: float
    cases: tuple[CaseScore, ...]


def _validate_k(k: int) -> None:
    if isinstance(k, bool) or not isinstance(k, int) or k <= 0:
        raise ValueError("k must be a positive integer")


def _span_identity(span: GoldenSpan) -> tuple[str, str, int, int]:
    return (
        span.doc_id,
        span.source_sha256,
        span.start_char,
        span.end_char,
    )


def span_iou(golden: GoldenSpan, hit: ChunkHit) -> float:
    """Return half-open span IoU after exact document-snapshot matching.

    Touching boundaries have zero overlap. A stale hit from another source snapshot
    is never relevant even if its document id and numeric offsets happen to match.
    """
    if golden.doc_id != hit.doc_id or golden.source_sha256 != hit.source_sha256:
        return 0.0

    # IoU = overlapping length / (answer length + chunk length - overlapping length)
    overlap = max(
        0,
        min(golden.end_char, hit.end_char) - max(golden.start_char, hit.start_char),
    )
    if overlap == 0:
        return 0.0
    union = (golden.end_char - golden.start_char) + (hit.end_char - hit.start_char) - overlap
    return overlap / union


def _is_relevant(golden: GoldenSpan, hit: ChunkHit) -> bool:
    return span_iou(golden, hit) >= IOU_THRESHOLD


def score_case(
    case_id: str,
    golden_spans: Sequence[GoldenSpan],
    retrieved_hits: Sequence[ChunkHit],
    k: int,
) -> CaseScore:
    """Score the top-k hits for one positive golden case.

    Recall counts unique gold spans covered. Duplicate retrieved hits cannot count
    one gold span twice, while one broad hit may cover multiple distinct gold spans
    when it independently reaches the IoU threshold for each.
    """
    _validate_k(k)
    if not isinstance(case_id, str) or not case_id.strip():
        raise ValueError("case_id must not be blank")
    if not golden_spans:
        raise ValueError("golden_spans must not be empty; exclude absent cases")

    identities = [_span_identity(span) for span in golden_spans]
    if len(identities) != len(set(identities)):
        raise ValueError("golden_spans must be unique")

    top_hits = retrieved_hits[:k]
    matched_gold = {
        index
        for index, golden in enumerate(golden_spans)
        if any(_is_relevant(golden, hit) for hit in top_hits)
    }
    first_relevant_rank = next(
        (
            rank
            for rank, hit in enumerate(top_hits, start=1)
            if any(_is_relevant(golden, hit) for golden in golden_spans)
        ),
        None,
    )
    matched_count = len(matched_gold)
    recall = matched_count / len(golden_spans)
    hit_at_k = float(bool(matched_count))
    reciprocal_rank = 1.0 / first_relevant_rank if first_relevant_rank is not None else 0.0
    return CaseScore(
        case_id=case_id,
        k=k,
        gold_span_count=len(golden_spans),
        matched_gold_count=matched_count,
        recall_at_k=recall,
        hit_at_k=hit_at_k,
        reciprocal_rank=reciprocal_rank,
        first_relevant_rank=first_relevant_rank,
    )


def _validated_scores(case_scores: Sequence[CaseScore]) -> tuple[CaseScore, ...]:
    if not case_scores:
        raise ValueError("case_scores must not be empty")

    ordered = tuple(sorted(case_scores, key=lambda result: result.case_id))
    if len({result.case_id for result in ordered}) != len(ordered):
        raise ValueError("case_ids must be unique")
    if len({result.k for result in ordered}) != 1:
        raise ValueError("all case scores must use the same k")
    return ordered


def recall_at_k(case_scores: Sequence[CaseScore]) -> float:
    """Return macro recall across a nonempty suite of positive cases."""
    scores = _validated_scores(case_scores)
    return sum(result.recall_at_k for result in scores) / len(scores)


def hit_rate_at_k(case_scores: Sequence[CaseScore]) -> float:
    """Return the fraction of positive cases with at least one relevant top-k hit."""
    scores = _validated_scores(case_scores)
    return sum(result.hit_at_k for result in scores) / len(scores)


def mrr(case_scores: Sequence[CaseScore]) -> float:
    """Return mean reciprocal rank of the first relevant top-k hit per case."""
    scores = _validated_scores(case_scores)
    return sum(result.reciprocal_rank for result in scores) / len(scores)


def mean_reciprocal_rank(case_scores: Sequence[CaseScore]) -> float:
    """Return MRR using its unabbreviated public name."""
    return mrr(case_scores)


def score_suite(case_scores: Sequence[CaseScore]) -> SuiteScore:
    """Aggregate one nonempty, single-k suite in deterministic case-id order."""
    scores = _validated_scores(case_scores)
    return SuiteScore(
        k=scores[0].k,
        case_count=len(scores),
        recall_at_k=sum(result.recall_at_k for result in scores) / len(scores),
        hit_rate_at_k=sum(result.hit_at_k for result in scores) / len(scores),
        mrr=sum(result.reciprocal_rank for result in scores) / len(scores),
        cases=scores,
    )
```

체크포인트를 실행한다.

```bash
uv run pytest tests/evals/test_02_scoring.py -q
```

**예상 결과:** 선택한 모든 오프라인 테스트가 통과한다. 명시된 통합 테스트는 외부 서비스를 사용할 수 없을 때만 건너뛸 수 있다.

**중단 조건:** 테스트가 실패하거나 필수 정식 심볼이 없어서 건너뛰면 진행하지 않는다.

**디버깅:** 같은 pytest 대상을 `-vv --tb=long`으로 다시 실행하고 첫 번째로 실패한 계약을 고친 뒤 진행한다.

### M3.3 — 완성 체크포인트

#### 생성 또는 교체 `app/evals/regression.py`

<!-- file: app/evals/regression.py -->
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

type MetricName = Literal["recall_at_k", "hit_rate_at_k", "mrr"]

HIGHER_IS_BETTER_METRICS: Final[tuple[MetricName, ...]] = (
    "recall_at_k",
    "hit_rate_at_k",
    "mrr",
)


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

체크포인트를 실행한다.

```bash
uv run pytest tests/evals/test_03_regression.py -q
```

**예상 결과:** 선택한 모든 오프라인 테스트가 통과한다. 명시된 통합 테스트는 외부 서비스를 사용할 수 없을 때만 건너뛸 수 있다.

**중단 조건:** 테스트가 실패하거나 필수 정식 심볼이 없어서 건너뛰면 진행하지 않는다.

**디버깅:** 같은 pytest 대상을 `-vv --tb=long`으로 다시 실행하고 첫 번째로 실패한 계약을 고친 뒤 진행한다.

### M3.4 — 완성 체크포인트

#### 생성 또는 교체 `app/evals/ablation.py`

<!-- file: app/evals/ablation.py -->
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

type RetrievalStrategy = Literal["lexical", "vector", "hybrid"]
type ExperimentEvaluator = Callable[["ExperimentConfig"], Awaitable[RetrievalEvaluation]]

STRATEGY_ORDER = {"lexical": 0, "vector": 1, "hybrid": 2}
RANKER_ORDER = {"ts_rank_cd": 0, "bm25": 1}
RANKER_SLUG = {"ts_rank_cd": "ts-rank-cd", "bm25": "bm25"}
DEFAULT_LEXICAL_RANKERS: tuple[LexicalRanker, ...] = ("ts_rank_cd", "bm25")
EXPERIMENT_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


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

#### 생성 또는 교체 `app/evals/retrieval_eval.py`

<!-- file: app/evals/retrieval_eval.py -->
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
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession, create_async_engine
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

type RetrievalStrategy = Literal["lexical", "vector", "hybrid"]
type Retriever = Callable[[str, int], Awaitable[Sequence[ChunkHit]]]
type Clock = Callable[[], int]

INDEXING_BUDGET_SECONDS = 300.0
QUERY_BUDGET_COUNT = 200
QUERY_BUDGET_SECONDS = 90.0
RAW_ARTIFACT_SCHEMA_VERSION = 1


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


async def evaluate_retriever(
    cases: Sequence[GoldenCase],
    retriever: Retriever,
    *,
    suite: str,
    config: Mapping[str, Any],
    k: int = 5,
    clock: Clock = time.perf_counter_ns,
    recorded_at: datetime | None = None,
) -> RetrievalEvaluation:
    """Evaluate every case once while scoring only source-bearing positives."""
    if not isinstance(suite, str) or not suite.strip():
        raise ValueError("suite must be nonblank")
    if isinstance(k, bool) or not isinstance(k, int) or k <= 0:
        raise ValueError("k must be a positive integer")
    ordered = tuple(sorted(cases, key=lambda case: case.id))
    if not ordered:
        raise ValueError("golden cases must not be empty")
    if len({case.id for case in ordered}) != len(ordered):
        raise ValueError("golden case ids must be unique")
    provenance = _golden_provenance(ordered)

    results: list[CaseEvaluation] = []
    scores: list[CaseScore] = []
    latencies: list[float] = []
    for case in ordered:
        started = clock()
        hits = tuple(await retriever(case.question, k))
        elapsed_ms = (clock() - started) / 1_000_000
        if elapsed_ms < 0:
            raise ValueError("clock must be monotonic")
        latencies.append(elapsed_ms)
        case_score = score_case(case.id, case.answers, hits, k) if case.answers else None
        if case_score is not None:
            scores.append(case_score)
        results.append(
            CaseEvaluation(
                golden=case,
                latency_ms=elapsed_ms,
                hits=hits,
                score=case_score,
            )
        )

    return RetrievalEvaluation(
        suite=suite,
        recorded_at=recorded_at or datetime.now(UTC),
        config=_canonical_config(config),
        provenance=provenance,
        score=score_suite(scores),
        latency=_latency_summary(latencies),
        cases=tuple(results),
    )


def write_evaluation_artifact(path: str | Path, evaluation: RetrievalEvaluation) -> Path:
    """Write one stable UTF-8 raw artifact and return its path."""
    artifact_path = Path(path)
    if artifact_path.suffix != ".json":
        raise ValueError("evaluation artifact path must end in .json")
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        evaluation.artifact_payload(),
        allow_nan=False,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    artifact_path.write_text(payload + "\n", encoding="utf-8")
    return artifact_path


async def measure_query_budget(
    queries: Sequence[str],
    retriever: Retriever,
    *,
    k: int = 5,
    query_count: int = QUERY_BUDGET_COUNT,
    budget_seconds: float = QUERY_BUDGET_SECONDS,
    clock: Clock = time.perf_counter_ns,
) -> QueryBudgetMeasurement:
    """Repeat nonempty queries sequentially and assess the wall-clock budget."""
    if not queries or any(not isinstance(query, str) or not query.strip() for query in queries):
        raise ValueError("queries must contain nonblank strings")
    if isinstance(query_count, bool) or not isinstance(query_count, int) or query_count <= 0:
        raise ValueError("query_count must be a positive integer")
    if k <= 0:
        raise ValueError("k must be positive")
    if not math.isfinite(budget_seconds) or budget_seconds <= 0:
        raise ValueError("budget_seconds must be finite and positive")

    previous = clock()
    latencies: list[float] = []
    for index in range(query_count):
        await retriever(queries[index % len(queries)], k)
        current = clock()
        elapsed_ms = (current - previous) / 1_000_000
        if elapsed_ms < 0:
            raise ValueError("clock must be monotonic")
        latencies.append(elapsed_ms)
        previous = current

    summary = _latency_summary(latencies)
    total_seconds = summary.total_ms / 1_000
    return QueryBudgetMeasurement(
        query_count=query_count,
        total_seconds=total_seconds,
        budget_seconds=budget_seconds,
        passed=total_seconds <= budget_seconds,
        mean_ms=summary.mean_ms,
        p50_ms=summary.p50_ms,
        p95_ms=summary.p95_ms,
        max_ms=summary.max_ms,
    )


def assess_indexing_budget(
    *,
    target_text_chars: int,
    document_count: int,
    chunk_count: int,
    embedding_provider: str,
    total_seconds: float,
    budget_seconds: float = INDEXING_BUDGET_SECONDS,
) -> IndexingBudgetMeasurement:
    """Validate and assess one measured indexing duration."""
    if target_text_chars <= 0 or document_count <= 0 or chunk_count <= 0:
        raise ValueError("indexing counts and target_text_chars must be positive")
    if not embedding_provider.strip():
        raise ValueError("embedding_provider must be nonblank")
    if not math.isfinite(total_seconds) or total_seconds < 0:
        raise ValueError("total_seconds must be finite and nonnegative")
    if not math.isfinite(budget_seconds) or budget_seconds <= 0:
        raise ValueError("budget_seconds must be finite and positive")
    return IndexingBudgetMeasurement(
        target_text_chars=target_text_chars,
        document_count=document_count,
        chunk_count=chunk_count,
        embedding_provider=embedding_provider,
        total_seconds=total_seconds,
        budget_seconds=budget_seconds,
        passed=total_seconds <= budget_seconds,
    )


def make_retriever(
    session: AsyncSession,
    *,
    strategy: RetrievalStrategy,
    provider: EmbeddingProvider | None,
    lexical_ranker: LexicalRanker | None = None,
    candidate_k: int = 20,
    rrf_k: int = DEFAULT_RRF_K,
    filters: RetrievalFilters | None = None,
) -> Retriever:
    """Bind one explicit retrieval strategy and lexical ranker to a session.

    The ranker is required exactly when the strategy runs a lexical query, so an
    arm can never be measured under a ranker it did not use, and a vector arm can
    never be labelled with one it never touched.
    """
    if strategy not in {"lexical", "vector", "hybrid"}:
        raise ValueError(f"unsupported retrieval strategy: {strategy}")
    if strategy == "vector":
        if lexical_ranker is not None:
            raise ValueError("vector retrieval must not name a lexical ranker")
    elif lexical_ranker not in {"ts_rank_cd", "bm25"}:
        raise ValueError(f"{strategy} retrieval requires an explicit lexical ranker")
    if candidate_k <= 0:
        raise ValueError("candidate_k must be positive")
    if rrf_k <= 0:
        raise ValueError("rrf_k must be positive")
    if strategy in {"vector", "hybrid"} and provider is None:
        raise ValueError(f"{strategy} retrieval requires an embedding provider")

    async def run(query: str, k: int) -> Sequence[ChunkHit]:
        if candidate_k < k:
            raise ValueError("candidate_k must be at least k")
        if strategy == "lexical":
            if lexical_ranker == "bm25":
                return await bm25_search(session, query, k, filters)
            return await lexical_search(session, query, k, filters)
        assert provider is not None
        if strategy == "vector":
            query_vector = await provider.embed_query(query)
            return await vector_search(session, query_vector, k=k, filters=filters)
        result = await retrieve(
            session,
            query,
            provider=provider,
            k=k,
            candidate_k=candidate_k,
            filters=filters,
            rrf_k=rrf_k,
            lexical_ranker=lexical_ranker,
        )
        return result.hits

    return run


async def persist_evaluation(
    session: AsyncSession,
    evaluation: RetrievalEvaluation,
    *,
    raw_artifact_path: str | Path,
    tolerances: RegressionTolerances | Mapping[str, float] | None = None,
) -> PersistedEvaluation:
    """Persist one run and compare it with the latest suite/config baseline."""
    baseline = await latest_comparable_baseline(
        session,
        suite=evaluation.suite,
        config=evaluation.config,
    )
    comparison = (
        compare_against_baseline(
            baseline.metrics,
            evaluation.metric_values(),
            tolerances=tolerances,
        )
        if baseline is not None
        else None
    )
    result = await persist_eval_result(
        session,
        suite=evaluation.suite,
        config=evaluation.config,
        metrics=evaluation.metric_values(),
        raw_artifact_path=raw_artifact_path,
        created_at=evaluation.recorded_at,
    )
    if result.id is None:
        raise RuntimeError("persisted evaluation did not receive an id")
    return PersistedEvaluation(
        result_id=result.id,
        baseline_id=baseline.id if baseline is not None else None,
        comparison=comparison,
    )


def build_chunking_batch(
    target_text_chars: int,
    *,
    settings: Settings | None = None,
) -> SeedBatch:
    """Build one source-stable corpus arm without changing the canonical golden spans."""
    configured = settings or get_settings()
    entries = load_manifest(configured.corpus_dir / "manifest.json")
    chunk_config = ChunkConfig(target_text_chars=target_text_chars)
    return build_seed_batch(
        entries,
        expected_documents=20,
        chunker=lambda filing: chunk_filing(filing, chunk_config),
    )


async def _create_temporary_corpus_tables(connection: AsyncConnection, dimensions: int) -> None:
    extension = await connection.scalar(
        text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
    )
    if extension is None:
        raise RuntimeError("the configured PostgreSQL database does not have pgvector")
    await connection.execute(
        text(
            """
            CREATE TEMP TABLE documents (
                doc_id varchar(32) PRIMARY KEY,
                ticker varchar(16) NOT NULL,
                cik bigint NOT NULL,
                fiscal_year integer NOT NULL,
                form varchar(16) NOT NULL,
                filing_date varchar(10) NOT NULL,
                report_period varchar(10) NOT NULL,
                accession varchar(32) NOT NULL,
                url text NOT NULL,
                parse_status varchar(32) NOT NULL,
                item_index jsonb NOT NULL,
                source_length bigint NOT NULL,
                source_sha256 varchar(64) NOT NULL
            ) ON COMMIT PRESERVE ROWS
            """
        )
    )
    await connection.execute(
        text(
            f"""
            CREATE TEMP TABLE chunks (
                id bigserial PRIMARY KEY,
                doc_id varchar(32) NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
                item varchar(8),
                kind varchar(16) NOT NULL,
                ordinal integer NOT NULL,
                body text NOT NULL,
                context_header text NOT NULL,
                index_text text NOT NULL,
                start_char bigint NOT NULL,
                end_char bigint NOT NULL,
                source_sha256 varchar(64) NOT NULL,
                citation text NOT NULL,
                embedding vector({dimensions}),
                content_tsv tsvector GENERATED ALWAYS AS (
                    to_tsvector('english', index_text)
                ) STORED,
                created_at timestamptz NOT NULL DEFAULT now(),
                UNIQUE (doc_id, ordinal)
            ) ON COMMIT PRESERVE ROWS
            """
        )
    )
    await connection.execute(text("CREATE INDEX ON chunks USING gin (content_tsv)"))
    for statement in (
        """
        CREATE TEMP TABLE chunk_terms (
            chunk_id bigint NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
            lexeme text NOT NULL,
            tf integer NOT NULL,
            PRIMARY KEY (chunk_id, lexeme)
        ) ON COMMIT PRESERVE ROWS
        """,
        """
        CREATE TEMP TABLE chunk_lengths (
            chunk_id bigint PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,
            dl integer NOT NULL
        ) ON COMMIT PRESERVE ROWS
        """,
        """
        CREATE TEMP TABLE lexeme_stats (
            lexeme text PRIMARY KEY,
            df integer NOT NULL
        ) ON COMMIT PRESERVE ROWS
        """,
        "CREATE INDEX ON chunk_terms (lexeme)",
    ):
        await connection.execute(text(statement))
    await connection.commit()


@asynccontextmanager
async def temporary_corpus_session(
    engine: AsyncEngine,
    batch: SeedBatch,
    provider: EmbeddingProvider,
    *,
    target_text_chars: int,
    embedding_provider: str,
    clock: Clock = time.perf_counter_ns,
    started_at_ns: int | None = None,
) -> AsyncIterator[tuple[AsyncSession, IndexingBudgetMeasurement]]:
    """Index one isolated corpus arm and discard it when its connection closes."""
    started = clock() if started_at_ns is None else started_at_ns
    connection = await engine.connect()
    session: AsyncSession | None = None
    try:
        await _create_temporary_corpus_tables(connection, provider.dimensions)
        session = AsyncSession(bind=connection, expire_on_commit=False)
        await persist_seed_batch(session, batch)
        # One rebuild per corpus arm. Every BM25 experiment on this chunking shares
        # it, and the next chunk target gets its own corpus and its own statistics,
        # because df, avgdl, and dl are all properties of a particular chunking.
        await backfill_term_stats(session)
        backfill = await embed_missing_chunks(session, provider)
        if backfill.embedded != len(batch.chunks) or backfill.skipped_stale:
            raise RuntimeError("temporary corpus embedding backfill was incomplete")
        elapsed_seconds = (clock() - started) / 1_000_000_000
        measurement = assess_indexing_budget(
            target_text_chars=target_text_chars,
            document_count=len(batch.documents),
            chunk_count=len(batch.chunks),
            embedding_provider=embedding_provider,
            total_seconds=elapsed_seconds,
        )
        yield session, measurement
    finally:
        if session is not None:
            await session.close()
        await connection.close()


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse the isolated M3 ablation command."""
    parser = argparse.ArgumentParser(
        description="Run isolated source-span retrieval ablations and latency budgets."
    )
    parser.add_argument("--suite", default="m3-retrieval-v1")
    parser.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN_PATH)
    parser.add_argument("--artifact-dir", type=Path, default=Path("data/eval_runs"))
    parser.add_argument("--provider", choices=("deterministic", "openai"), default="deterministic")
    parser.add_argument("--target-text-chars", type=_positive_int, nargs="+", default=[500, 1200])
    parser.add_argument(
        "--strategies",
        choices=("lexical", "vector", "hybrid"),
        nargs="+",
        default=["lexical", "vector", "hybrid"],
    )
    parser.add_argument(
        "--lexical-rankers",
        choices=("ts_rank_cd", "bm25"),
        nargs="+",
        default=["ts_rank_cd", "bm25"],
        help="Lexical rankers to cross with every lexical and hybrid arm.",
    )
    parser.add_argument("-k", type=_positive_int, default=5)
    parser.add_argument("--candidate-k", type=_positive_int, default=20)
    parser.add_argument("--rrf-k", type=_positive_int, default=DEFAULT_RRF_K)
    parser.add_argument("--budget-queries", type=_positive_int, default=QUERY_BUDGET_COUNT)
    parser.add_argument("--persist-results", action="store_true")
    return parser.parse_args(argv)


async def _run_cli(args: argparse.Namespace) -> dict[str, Any]:
    from app.db.bootstrap import bootstrap_schema
    from app.evals.ablation import ExperimentConfig, experiment_matrix, run_ablation

    if args.candidate_k < args.k:
        raise ValueError("candidate_k must be at least k")
    settings = get_settings().model_copy(update={"embedding_provider": args.provider})
    provider = get_embedding_provider(settings)
    cases = load_golden_cases(args.golden)
    recorded_at = datetime.now(UTC)
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    all_outcomes = []
    indexing_measurements: list[IndexingBudgetMeasurement] = []
    query_budget: QueryBudgetMeasurement | None = None
    budget_ranker: LexicalRanker | None = None
    try:
        for target_text_chars in sorted(set(args.target_text_chars)):
            indexing_started_at_ns = time.perf_counter_ns()
            batch = build_chunking_batch(target_text_chars, settings=settings)
            configs = experiment_matrix(
                target_text_chars=(target_text_chars,),
                strategies=tuple(args.strategies),
                lexical_rankers=tuple(dict.fromkeys(args.lexical_rankers)),
                embedding_provider=args.provider,
                dimensions=provider.dimensions,
                k=args.k,
                candidate_k=args.candidate_k,
                rrf_k=args.rrf_k,
            )
            async with temporary_corpus_session(
                engine,
                batch,
                provider,
                target_text_chars=target_text_chars,
                embedding_provider=args.provider,
                started_at_ns=indexing_started_at_ns,
            ) as (session, indexing):
                indexing_measurements.append(indexing)

                async def evaluator(config: ExperimentConfig) -> RetrievalEvaluation:
                    retriever = make_retriever(
                        session,
                        strategy=config.strategy,
                        provider=provider,
                        lexical_ranker=config.lexical_ranker,
                        candidate_k=config.candidate_k,
                        rrf_k=config.rrf_k,
                    )
                    return await evaluate_retriever(
                        cases,
                        retriever,
                        suite=args.suite,
                        config=config.to_dict(),
                        k=config.k,
                        recorded_at=recorded_at,
                    )

                report = await run_ablation(
                    configs,
                    evaluator,
                    artifact_dir=args.artifact_dir,
                    recorded_at=recorded_at,
                )
                all_outcomes.extend(report.outcomes)

                if target_text_chars == max(args.target_text_chars):
                    budget_strategy = (
                        "hybrid" if "hybrid" in args.strategies else args.strategies[-1]
                    )
                    budget_ranker = None if budget_strategy == "vector" else args.lexical_rankers[0]
                    budget_retriever = make_retriever(
                        session,
                        strategy=budget_strategy,
                        provider=provider,
                        lexical_ranker=budget_ranker,
                        candidate_k=args.candidate_k,
                        rrf_k=args.rrf_k,
                    )
                    query_budget = await measure_query_budget(
                        [case.question for case in cases],
                        budget_retriever,
                        k=args.k,
                        query_count=args.budget_queries,
                    )

        if query_budget is None:
            raise RuntimeError("query budget was not measured")

        timestamp = recorded_at.strftime("%Y%m%dT%H%M%SZ")
        budget_path = args.artifact_dir / f"{timestamp}-budgets.json"
        budget_payload = {
            "schema_version": RAW_ARTIFACT_SCHEMA_VERSION,
            "recorded_at": _utc_text(recorded_at),
            "measurement_provenance": {
                "embedding_provider": args.provider,
                "budget_lexical_ranker": budget_ranker,
                "environment": "isolated-temporary-postgresql",
                "paid_api_calls": args.provider != "deterministic",
                "populated_corpus_embeddings_modified": False,
            },
            "indexing": [asdict(measurement) for measurement in indexing_measurements],
            "query_budget": asdict(query_budget),
        }
        budget_path.parent.mkdir(parents=True, exist_ok=True)
        budget_path.write_text(
            json.dumps(budget_payload, allow_nan=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        persisted = []
        if args.persist_results:
            await bootstrap_schema(engine)
            async with AsyncSession(engine, expire_on_commit=False) as session:
                for outcome in all_outcomes:
                    persisted.append(
                        await persist_evaluation(
                            session,
                            outcome.evaluation,
                            raw_artifact_path=outcome.artifact_path,
                        )
                    )
                await session.commit()

        from app.evals.ablation import AblationReport

        combined = AblationReport(outcomes=tuple(all_outcomes))
        return {
            "comparison_table": combined.comparison_markdown(),
            "artifacts": [str(outcome.artifact_path) for outcome in all_outcomes],
            "budget_artifact": str(budget_path),
            "indexing": [asdict(measurement) for measurement in indexing_measurements],
            "query_budget": asdict(query_budget),
            "persisted": [asdict(result) for result in persisted],
        }
    finally:
        await engine.dispose()


def main() -> None:
    """Run the complete isolated M3 evaluation command."""
    result = asyncio.run(_run_cli(arguments()))
    print(result["comparison_table"])
    print(
        json.dumps(
            {key: value for key, value in result.items() if key != "comparison_table"}, indent=2
        )
    )


if __name__ == "__main__":
    main()
```

#### 생성 또는 교체 `app/evals/__main__.py`

<!-- file: app/evals/__main__.py -->
```python
"""Command-line entry point for the complete M3 evaluation matrix."""

from app.evals.retrieval_eval import main

if __name__ == "__main__":
    main()
```

체크포인트를 실행한다.

```bash
uv run pytest tests/evals/test_04_ablation.py tests/evals/test_05_runner.py -q
```

**예상 결과:** 선택한 모든 오프라인 테스트가 통과한다. 명시된 통합 테스트는 외부 서비스를 사용할 수 없을 때만 건너뛸 수 있다.

**중단 조건:** 테스트가 실패하거나 필수 정식 심볼이 없어서 건너뛰면 진행하지 않는다.

**디버깅:** 같은 pytest 대상을 `-vv --tb=long`으로 다시 실행하고 첫 번째로 실패한 계약을 고친 뒤 진행한다.

### M3.5 — 완성 체크포인트

#### 생성 또는 교체 `app/evals/curation.py`

<!-- file: app/evals/curation.py -->
```python
"""Candidate intake, machine validation, review queue, and fail-closed promotion."""

from __future__ import annotations

from collections.abc import Sequence
import json
from pathlib import Path
from typing import Annotated, Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr, TypeAdapter, ValidationError
from pydantic.functional_validators import field_validator

from app.evals.loader import DEFAULT_MANIFEST_PATH, GoldenDataError, validate_golden_sources
from app.evals.types import GoldenCase

# A committed answer span never exceeds this many raw characters. A wider span is
# reconnaissance, not an answer: it inflates IoU denominators and hides whether the
# generator actually located the evidence.
MAX_CANDIDATE_SPAN_CHARS: Final[int] = 2_500

DecisionLabel = Literal["approve", "reject"]
CandidateState = Literal["pending", "approved", "rejected"]


class CurationError(ValueError):
    """A candidate file, review decision, or promotion violates the curation contract."""


class CandidateCase(GoldenCase):
    """One generated golden candidate that has not earned an ``m3c`` id yet.

    A candidate carries the full golden payload plus generator provenance, so every
    golden invariant is inherited and enforced at intake. Only promotion may mint a
    golden id, and a candidate can never claim any status beyond the pinned pending
    literals it inherits.
    """

    id: Annotated[StrictStr, Field(pattern=r"^m3s-[0-9]{2}$")]
    generator: Annotated[StrictStr, Field(min_length=1)]

    @field_validator("generator", mode="after")
    @classmethod
    def reject_blank_generator(cls, value: str) -> str:
        """Keep generator provenance non-empty, single-line, and table-safe."""
        if not value.strip():
            raise ValueError("generator must not be blank")
        if "|" in value or "\n" in value:
            raise ValueError("generator must not contain pipes or newlines")
        return value


class ReviewDecision(BaseModel):
    """One explicit human verdict on one candidate. Absence of a verdict is pending."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: Annotated[StrictStr, Field(pattern=r"^m3s-[0-9]{2}$")]
    decision: DecisionLabel
    reviewer: Annotated[StrictStr, Field(min_length=1)]
    note: Annotated[StrictStr, Field(min_length=1)]

    @field_validator("reviewer", "note", mode="after")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        """Reject strings that contain only whitespace."""
        if not value.strip():
            raise ValueError("text fields must not be blank")
        return value


CANDIDATE_CASES = TypeAdapter(list[CandidateCase])
REVIEW_DECISIONS = TypeAdapter(list[ReviewDecision])


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CurationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _read_json(path: Path) -> object:
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except CurationError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CurationError(f"cannot read valid UTF-8 JSON from {path}: {exc}") from exc


def _candidate_files(path: Path) -> list[Path]:
    if path.is_dir():
        files = sorted(path.glob("*.json"))
        if not files:
            raise CurationError(f"no candidate JSON files found in {path}")
        return files
    return [path]


def _normalized_question(question: str) -> str:
    return " ".join(question.casefold().split())


def _span_identities(case: GoldenCase) -> list[tuple[str, str, int, int]]:
    return [
        (answer.doc_id, answer.source_sha256, answer.start_char, answer.end_char)
        for answer in case.answers
    ]


def _validate_unique_candidates(candidates: Sequence[CandidateCase]) -> None:
    ids: set[str] = set()
    questions: set[str] = set()
    identities: set[tuple[str, str, int, int]] = set()
    for candidate in candidates:
        if candidate.id in ids:
            raise CurationError(f"duplicate candidate id: {candidate.id}")
        ids.add(candidate.id)

        normalized = _normalized_question(candidate.question)
        if normalized in questions:
            raise CurationError(f"duplicate normalized candidate question: {candidate.question}")
        questions.add(normalized)

        for identity in _span_identities(candidate):
            if identity in identities:
                raise CurationError(f"duplicate answer span identity in {candidate.id}")
            identities.add(identity)

        for answer in candidate.answers:
            width = answer.end_char - answer.start_char
            if width > MAX_CANDIDATE_SPAN_CHARS:
                raise CurationError(
                    f"{candidate.id} span is reconnaissance, not an answer: "
                    f"{width} > {MAX_CANDIDATE_SPAN_CHARS} chars"
                )


def _validate_disjoint_from_golden(
    candidates: Sequence[CandidateCase],
    golden_cases: Sequence[GoldenCase],
) -> None:
    golden_questions = {_normalized_question(case.question) for case in golden_cases}
    golden_identities = {identity for case in golden_cases for identity in _span_identities(case)}
    for candidate in candidates:
        if _normalized_question(candidate.question) in golden_questions:
            raise CurationError(
                f"{candidate.id} duplicates a golden question: {candidate.question}"
            )
        for identity in _span_identities(candidate):
            if identity in golden_identities:
                raise CurationError(f"{candidate.id} reuses a golden answer span identity")


def load_candidate_cases(
    path: str | Path,
    *,
    golden_cases: Sequence[GoldenCase],
    manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
) -> list[CandidateCase]:
    """Load one file or a directory of candidate files and run every machine gate.

    Structural validation, uniqueness, disjointness from the committed golden set,
    and raw-source binding all run here, so a candidate that survives intake fails
    later only on human judgment, never on mechanics.
    """
    candidates: list[CandidateCase] = []
    for candidate_path in _candidate_files(Path(path)):
        payload = _read_json(candidate_path)
        if not isinstance(payload, list):
            raise CurationError(f"candidate file root must be a JSON array: {candidate_path}")
        try:
            candidates.extend(CANDIDATE_CASES.validate_python(payload))
        except ValidationError as exc:
            raise CurationError(f"invalid candidate cases in {candidate_path}: {exc}") from exc

    _validate_unique_candidates(candidates)
    _validate_disjoint_from_golden(candidates, golden_cases)
    try:
        validate_golden_sources(candidates, manifest_path)
    except GoldenDataError as exc:
        raise CurationError(str(exc)) from exc
    return candidates


def load_review_decisions(path: str | Path) -> list[ReviewDecision]:
    """Load explicit review decisions. A missing file is an error, never an empty set."""
    decisions_path = Path(path)
    if not decisions_path.is_file():
        raise CurationError(f"decisions file does not exist: {decisions_path}")
    payload = _read_json(decisions_path)
    if not isinstance(payload, list):
        raise CurationError(f"decisions file root must be a JSON array: {decisions_path}")
    try:
        decisions = REVIEW_DECISIONS.validate_python(payload)
    except ValidationError as exc:
        raise CurationError(f"invalid review decisions in {decisions_path}: {exc}") from exc

    seen: set[str] = set()
    for decision in decisions:
        if decision.candidate_id in seen:
            raise CurationError(f"duplicate review decision for {decision.candidate_id}")
        seen.add(decision.candidate_id)
    return decisions


def candidate_states(
    candidates: Sequence[CandidateCase],
    decisions: Sequence[ReviewDecision] = (),
) -> dict[str, CandidateState]:
    """Map every candidate id to pending, approved, or rejected.

    Every decision must name a known candidate, and at most one decision may exist
    per candidate. A candidate without a decision stays pending — silence never
    approves anything.
    """
    known = {candidate.id for candidate in candidates}
    if len(known) != len(candidates):
        raise CurationError("candidate ids must be unique")

    states: dict[str, CandidateState] = {candidate.id: "pending" for candidate in candidates}
    decided: set[str] = set()
    for decision in decisions:
        if decision.candidate_id not in known:
            raise CurationError(f"decision references unknown candidate: {decision.candidate_id}")
        if decision.candidate_id in decided:
            raise CurationError(f"duplicate review decision for {decision.candidate_id}")
        decided.add(decision.candidate_id)
        states[decision.candidate_id] = "approved" if decision.decision == "approve" else "rejected"
    return states


def review_queue_markdown(
    candidates: Sequence[CandidateCase],
    decisions: Sequence[ReviewDecision] = (),
) -> str:
    """Render the deterministic review queue an author walks before any promotion."""
    states = candidate_states(candidates, decisions)
    lines = [
        "| ID | Category | Facet | Positive source | Generator | Decision |",
        "|---|---|---|---|---|---|",
    ]
    for candidate in sorted(candidates, key=lambda case: case.id):
        doc_ids = sorted({answer.doc_id for answer in candidate.answers})
        source = ", ".join(doc_ids) if doc_ids else "none"
        lines.append(
            f"| {candidate.id} | {candidate.category} | {candidate.facet} | "
            f"{source} | {candidate.generator} | {states[candidate.id]} |"
        )
    return "\n".join(lines)


def _next_golden_number(golden_cases: Sequence[GoldenCase]) -> int:
    return max((int(case.id.split("-", 1)[1]) for case in golden_cases), default=0) + 1


def promote_approved(
    candidates: Sequence[CandidateCase],
    decisions: Sequence[ReviewDecision],
    golden_cases: Sequence[GoldenCase],
    *,
    manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
) -> tuple[GoldenCase, ...]:
    """Mint golden cases from explicitly approved candidates only.

    Promotion re-runs every machine gate — uniqueness, disjointness from the
    committed set, and raw-source binding for the approved cases — assigns the next
    free ``m3c`` ids in candidate-id order, and keeps the pinned pending-approval
    provenance: entering the golden pool queues a case for the author, it never
    certifies one.
    """
    _validate_unique_candidates(candidates)
    _validate_disjoint_from_golden(candidates, golden_cases)
    states = candidate_states(candidates, decisions)

    approved = [
        candidate
        for candidate in sorted(candidates, key=lambda case: case.id)
        if states[candidate.id] == "approved"
    ]
    try:
        validate_golden_sources(approved, manifest_path)
    except GoldenDataError as exc:
        raise CurationError(str(exc)) from exc
    number = _next_golden_number(golden_cases)
    promoted: list[GoldenCase] = []
    for candidate in approved:
        if number > 99:
            raise CurationError("golden id namespace m3c-NN is exhausted")
        payload = candidate.model_dump(mode="json", exclude={"generator"})
        payload["id"] = f"m3c-{number:02d}"
        try:
            promoted.append(GoldenCase.model_validate(payload))
        except ValidationError as exc:
            raise CurationError(f"promoted case from {candidate.id} is invalid: {exc}") from exc
        number += 1
    return tuple(promoted)


def write_golden_cases(path: str | Path, cases: Sequence[GoldenCase]) -> Path:
    """Write promoted cases as a golden-shaped JSON array for a reviewed merge."""
    target = Path(path)
    if target.suffix != ".json":
        raise CurationError(f"golden output must be a .json file: {target}")
    payload = [case.model_dump(mode="json") for case in cases]
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return target
```

#### 생성 또는 교체 `app/evals/breakdown.py`

<!-- file: app/evals/breakdown.py -->
```python
"""Taxonomy-grouped retrieval metrics over one scored golden suite."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import get_args

from app.evals.scoring import CaseScore, score_suite
from app.evals.types import GoldenCase, GoldenCategory, GoldenFacet


@dataclass(frozen=True, slots=True)
class GroupScore:
    """Macro-averaged retrieval metrics for one taxonomy group of positive cases."""

    group: str
    k: int
    case_count: int
    recall_at_k: float
    hit_rate_at_k: float
    mrr: float


def _positive_case_index(cases: Sequence[GoldenCase]) -> dict[str, GoldenCase]:
    index: dict[str, GoldenCase] = {}
    for case in cases:
        if case.id in index:
            raise ValueError(f"duplicate golden case id: {case.id}")
        index[case.id] = case
    return index


def _validated_pairs(
    cases: Sequence[GoldenCase],
    scores: Sequence[CaseScore],
) -> list[tuple[GoldenCase, CaseScore]]:
    """Pair every score with its positive case and reject partial or stray scoring.

    A breakdown over a subset would silently misrepresent a group, so every positive
    case must carry exactly one score, an absent case must carry none, and every
    score must point at a known case.
    """
    index = _positive_case_index(cases)
    if not scores:
        raise ValueError("scores must not be empty")
    if len({score.k for score in scores}) != 1:
        raise ValueError("all case scores must use the same k")

    pairs: list[tuple[GoldenCase, CaseScore]] = []
    scored_ids: set[str] = set()
    for score in scores:
        case = index.get(score.case_id)
        if case is None:
            raise ValueError(f"score references unknown golden case: {score.case_id}")
        if case.category == "absent":
            raise ValueError(f"absent case cannot carry a retrieval score: {score.case_id}")
        if score.case_id in scored_ids:
            raise ValueError(f"duplicate case score: {score.case_id}")
        scored_ids.add(score.case_id)
        pairs.append((case, score))

    unscored = [
        case.id for case in cases if case.category != "absent" and case.id not in scored_ids
    ]
    if unscored:
        raise ValueError(f"positive cases missing a score: {', '.join(sorted(unscored))}")
    return pairs


def _grouped(
    pairs: Sequence[tuple[GoldenCase, CaseScore]],
    groups: Sequence[str],
    key: Callable[[GoldenCase], str],
) -> tuple[GroupScore, ...]:
    results: list[GroupScore] = []
    for group in groups:
        members = [score for case, score in pairs if key(case) == group]
        if not members:
            continue
        suite = score_suite(members)
        results.append(
            GroupScore(
                group=group,
                k=suite.k,
                case_count=suite.case_count,
                recall_at_k=suite.recall_at_k,
                hit_rate_at_k=suite.hit_rate_at_k,
                mrr=suite.mrr,
            )
        )
    return tuple(results)


def breakdown_by_category(
    cases: Sequence[GoldenCase],
    scores: Sequence[CaseScore],
) -> tuple[GroupScore, ...]:
    """Group suite metrics by golden category in declaration order."""
    pairs = _validated_pairs(cases, scores)
    return _grouped(pairs, get_args(GoldenCategory), lambda case: case.category)


def breakdown_by_facet(
    cases: Sequence[GoldenCase],
    scores: Sequence[CaseScore],
) -> tuple[GroupScore, ...]:
    """Group suite metrics by golden facet in declaration order."""
    pairs = _validated_pairs(cases, scores)
    return _grouped(pairs, get_args(GoldenFacet), lambda case: case.facet)


def breakdown_markdown(dimension: str, groups: Sequence[GroupScore]) -> str:
    """Render one taxonomy breakdown as a compact comparison table."""
    if not dimension.strip():
        raise ValueError("dimension must not be blank")
    if not groups:
        raise ValueError("groups must not be empty")
    lines = [
        f"| {dimension} | Cases | Recall@k | Hit rate@k | MRR |",
        "|---|---:|---:|---:|---:|",
    ]
    for group in groups:
        lines.append(
            f"| {group.group} | {group.case_count} | {group.recall_at_k:.6f} | "
            f"{group.hit_rate_at_k:.6f} | {group.mrr:.6f} |"
        )
    return "\n".join(lines)
```

체크포인트를 실행한다.

```bash
uv run pytest tests/evals/test_07_curation.py -q
```

**예상 결과:** 선택한 모든 오프라인 테스트가 통과한다. 명시된 통합 테스트는 외부 서비스를 사용할 수 없을 때만 건너뛸 수 있다.

**중단 조건:** 테스트가 실패하거나 필수 정식 심볼이 없어서 건너뛰면 진행하지 않는다.

**디버깅:** 같은 pytest 대상을 `-vv --tb=long`으로 다시 실행하고 첫 번째로 실패한 계약을 고친 뒤 진행한다.

<!-- complete-files:end -->
