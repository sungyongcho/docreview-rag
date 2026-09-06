# M3.2 튜토리얼 3 — "맞았다"를 어떻게 판정할 것인가

튜토리얼 2는 검증된 정답 구간을 남겼다. 골든 로더는 원문 스냅샷과 바이트 단위로 대조해 검증한 좌표를 넘겨주고, 검색 계층은 저마다의 좌표를 가진 점수화된 청크를 넘겨준다. 아직 어느 계층도 답하지 않은 질문이 남아 있다. 청크가 정답을 *찾았다*고 인정되는 조건은 무엇인가 — 두 좌표 구간이 정확히 일치하는 경우는 거의 없는데 말이다.

커밋된 평가 아티팩트의 실제 사례를 보자. 사례 `m3c-24`의 골든 구간 하나는 `[517875, 517933)`의 58자이고, 1위로 검색된 청크는 `[516437, 518187)`를 덮는 1,750자로 그 정답을 완전히 포함한다. 이것은 적중인가. 정답의 끝 몇 글자만 스치는 청크는 어떤가. 고정된 규칙이 없으면 모든 평가 표가 "충분히 가깝다"를 두고 벌이는 논쟁이 되고, 규칙이 틀려 있으면 이 계층을 상속하는 뒤 계층의 모든 숫자 — 회귀 비교, 어블레이션 — 가 조용히 왜곡된다.

그래서 이 튜토리얼은 규칙을 순수 함수로 한 번만 정의한다. 불변조건은 하나다. 같은 골든 구간, 같은 히트, 같은 `k`가 들어오면 어느 실행에서든 바이트 단위로 동일한 점수가 나와야 한다. 계산 어디에도 데이터베이스, 시각, 무작위성이 없어야 한다.

**선행 조건:** 튜토리얼 2의 `uv run pytest tests/evals/test_02_loader.py -q`가 통과해야 한다.

### IoU로 겹침을 정량화한다

**IoU(Intersection over Union)** — 교집합을 합집합으로 나눈 값 — 를 쓴다. 객체 검출에서 쓰는 것과 같은 지표다.

```
IoU = overlapping length / (answer length + chunk length - overlapping length)
```

> **개념 — 분모가 합집합인 이유**
>
> IoU는 두 영역의 일치도를 재는 일반적인 척도로 컴퓨터 비전 평가에서 빌려 왔고, 여기서는 두 영역이 모두 반열린 문자 구간이다. 분모가 합집합 — 두 구간 중 하나라도 덮는 모든 문자 — 이므로, 값은 양쪽이 건드린 전체 텍스트 중 두 구간이 합의한 부분의 비율로 읽힌다. 이 분모 선택이 벌점을 대칭으로 만든다. 너무 좁은 구간은 교집합을 잃고, 너무 넓게 뻗은 구간은 합집합을 부풀려서, 어느 쪽 오차든 비율을 끌어내린다. 공식 어디에도 골든 쪽이나 히트 쪽을 우대하는 항이 없다. 두 구간을 맞바꿔도 값은 동일하다.
>
> 같은 대칭을 문자 좌표 구간에 적용하면 미리 알아 둘 결과가 하나 생긴다. 정답을 완전히 포함한 청크라도 청크가 정답보다 훨씬 크면 합집합이 부풀어 점수가 낮게 나온다. 완전 포함일 때 공식은 정답 길이 나누기 청크 길이로 줄어들므로, 임계값 0.05는 정답의 20배 크기까지의 포함 청크만 인정한다.

임계값은 `IoU >= 0.05`이고, 왜 이렇게 낮아야 하는지는 커밋된 평가 아티팩트가 보여준다. `data/eval_runs/20260824T203336Z-structure-1200-lexical-bm25.json` — 튜토리얼 7의 평가 실행이 격리된 임시 PostgreSQL에 대해 기록하고, 이후 튜토리얼과 회귀 기준선이 읽는 원시 증거로 저장소에 커밋한 파일 — 에서 골든 정답 구간의 너비 중앙값은 453자(최소 58자)인데, 검색된 텍스트 청크의 너비 중앙값은 1,549자다. 크기 불일치는 예외가 아니라 정상 상태다.

사례 `m3c-24`가 그 결과를 구체적으로 보여준다. 1위 청크는 `[516437, 518187)`의 1,750자로, 111자짜리와 58자짜리 골든 정답 둘을 모두 완전히 포함한다. 111자 구간은 111/1750 = 0.0634로 통과하고, 58자 구간은 58/1750 = 0.0331로 탈락한다. **같은 청크에 두 정답이 온전히 들어 있는데도 이 사례의 재현율은 0.5로 기록됐다. 정답의 길이만으로 점수가 반토막 난 것이다.**

```bash
python3 -c "import json; c=[x for x in json.load(open('data/eval_runs/20260824T203336Z-structure-1200-lexical-bm25.json'))['cases'] if x['golden']['id']=='m3c-24'][0]; h=c['hits'][0]; print('hit width :', h['end_char']-h['start_char']); print('gold widths:', [a['end_char']-a['start_char'] for a in c['golden']['answers']]); print('case score :', c['score'])"
```

테이블 청크는 불일치를 더 벌린다. 사례 `m3c-28`의 5위 히트는 너비 12,860자의 테이블 청크인데, 이 너비에서는 내용을 따지기 전에 임계값의 결론이 이미 정해져 있다. 이 사례의 639자짜리 골든 구간이 이 청크 안에 통째로 들어 있었다고 해도 IoU는 639/12860 = 0.0497이다. 완전 포함인데도 여전히 임계값 아래다. 커밋된 아티팩트에서 이 사례는 실제로 0점인데, 골든 구간 둘 다 filing의 다른 좌표에 있기 때문이다. **그리고 0.05는 경험적으로 튜닝된 값이 아니다.** 이 저장소의 어떤 측정도 이 값을 도출하지 않는다. 완전 포함 텍스트 청크 대부분을 인정하려고 낮게 잡은 문턱일 뿐이며, 그 날카로운 모서리는 위 두 사례 같은 측정에서 드러난다.

그리고 **맞닿기만 한 구간은 겹치지 않은 것으로 센다.** `[100, 200)`과 `[200, 300)`은 반열린 구간이라 공유하는 문자가 하나도 없고, `overlap == 0`이면 0.0을 돌려준다.

### 해시부터 확인하는 이유

`span_iou`의 첫 줄이 좌표 계산보다 먼저 `doc_id`와 `source_sha256`을 비교한다.

문서가 다르면 좌표가 겹쳐도 무관한 결과라는 점은 분명하다. 판단이 필요한 쪽은 해시다.

`doc_id`는 같은데 해시가 다르면 그 청크는 다른 스냅샷에서 만들어진 것이다. filing을 다시 내려받아 바이트가 달라졌고 이전 스냅샷의 청크가 데이터베이스에 남아 있는 상태다. 이때 좌표 숫자는 겹칠 수 있지만 그 좌표가 가리키는 텍스트는 서로 다르다.

**해시를 비교하지 않으면 다른 스냅샷의 청크가 적중으로 집계되어 평가 점수가 실제보다 높게 나온다.** 그래서 해시가 다르면 겹침을 계산하지 않고 0.0을 반환한다.

### 세 지표가 각각 다른 질문에 답한다

| 지표 | 질문 |
|---|---|
| **Recall@k** | 정답 구간 중 몇 개를 찾았나 |
| **Hit Rate@k** | 관련 결과가 **하나라도** 있었나 |
| **MRR** | 첫 관련 결과가 몇 위였나 |

**재현율은 검색 결과가 아니라 고유한 정답 구간을 센다.** 같은 정답을 덮는 청크를 세 개 검색했다고 재현율이 세 배가 되면, 청크를 잘게 자를수록 점수가 오르는 결과가 된다.

> **개념 — 매크로 평균과 마이크로 평균**
>
> 스위트를 평균하는 방법은 두 가지가 있고 둘 다 근거가 있다. 매크로 평균은 사례마다 점수를 먼저 내고 그 점수들을 평균하므로 질문마다 무게가 같다. 마이크로 평균은 모든 정답 구간을 한 통에 모아 찾은 구간 수를 전체 구간 수로 나누므로 구간마다 무게가 같고, 그만큼 정답 구간이 많은 질문이 비례해서 무거워진다.
>
> 어느 쪽이 틀린 것이 아니라 답하는 질문이 다르다. 매크로는 보통의 질문이 어떤 성적을 받는지를 묻고, 마이크로는 필요한 증거 전체 중 얼마를 찾았는지를 묻는다. 이 스위트는 정답 구간이 몇 개든 사례를 하나의 질문으로 취급하므로 매크로 평균을 쓴다.

매크로 선택은 지표의 눈금도 결정하는데, 그 눈금은 출력되는 자릿수보다 훨씬 굵다. 커밋된 스위트에서 채점 대상 사례는 24개이며 — 14개는 정답 구간이 하나, 10개는 둘 — 구간 하나가 찾음과 놓침 사이를 오가면 스위트 재현율은 최소 0.5/24 ≈ 0.0208만큼 움직인다. 어블레이션 표는 소수 여섯 자리로 출력되지만, 이 스위트 크기에서 0.02 아래의 차이는 잡음이다. 사례 하나 안의 구간 하나 차이일 뿐이다.

### 이 계층에 I/O가 없는 이유

`scoring.py`에는 데이터베이스 접근도, 공급자 호출도, 현재 시각 조회도, 파일 읽기도 없다. 이 파일은 순수 함수로만 구성된다.

이는 의도적인 제약이고, 반례를 들면 구체적으로 보인다. 채점기가 전달받은 히트의 좌표를 믿는 대신 데이터베이스에서 청크 텍스트를 다시 읽는다고 가정하자. 두 실행 사이에 점수가 움직였다면 그 원인은 검색기의 순위가 달라진 것일 수도 있고, 같은 id 뒤의 행이 재시드로 바뀐 것일 수도 있다. 원인은 둘인데 숫자는 하나라서 점수만 보고는 판별할 수 없다. 채점기가 골든 구간, 히트, `k`의 순수 함수인 지금은 점수가 바뀔 수 있는 원인이 입력의 변화 딱 하나다.

**측정 도구는 측정 대상보다 단순하고 결정론적이어야 한다.**

### 무엇을 작성하고 어디를 직접 구현할까

`app/evals/scoring.py`를 네 단계로 작성한다. 파일 전체가 순수 함수이므로 데이터베이스 없이 모든 경로를 테스트할 수 있다.

| 구간 | 학습 행동 | 여기서 얻어야 하는 것 |
|---|---|---|
| `CaseScore`와 `SuiteScore` | **레코드 선언 작성** | 점수와 함께 남겨야 할 근거 |
| `span_iou` | 겹침 계산을 **직접 구현** | 해시 관문과 반열린 구간의 의미 |
| `score_case` | 재현율 규칙을 **직접 구현** | 중복이 점수를 부풀리지 못하게 하는 방법 |
| 집계 함수들 | 매크로 평균을 **직접 구현** | 사례마다 같은 무게를 주는 조건 |

### 1. 모듈 헤더와 임계값

#### `app/evals/scoring.py` 생성 — 모듈 헤더

**학습 행동 — 구조 작성:** import가 M3의 `GoldenSpan`과 M2의 `ChunkHit` 두 개뿐이라는 점을 확인한다.

```python
"""Deterministic span-overlap scoring for retrieval evaluation."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from app.evals.types import GoldenSpan
from app.retrieval.types import ChunkHit

IOU_THRESHOLD: Final[float] = 0.05
```

**코드에서 꼭 볼 것**

- `IOU_THRESHOLD`는 `Final`로 선언한 모듈 상수라서 규칙이 최소한 눈에 보이고 검색된다. 다만 그것으로 얻지 못하는 것도 정직하게 알아야 한다. 이 임계값은 실행이 지니는 실험 config 어디에도 기록되지 않고, 회귀 기준선 매칭은 스위트와 config만 보고 실행을 짝짓는다. 이 상수를 바꿔도 옛 실행과 새 실행은 여전히 비교 가능한 것으로 짝지어진다 — 측정 도구가 그 사이에 달라졌으니 거짓된 비교인데도 말이다. 이것은 현재 코드의 알려진 날카로운 모서리이고, 실행 간 비교를 신뢰하기 전에 알아 둘 가치가 있다.
- import는 정답 타입과 검색 결과 타입 두 개뿐이다. 이 파일이 하는 일은 그 둘을 비교하는 것뿐이다.

`ChunkHit`은 이 파일이 정의를 한 번도 보여주지 않은 채 소비하는 타입이므로 여기서 짚는다. 검색 계층의 검증된 결과 모델 — `app/retrieval/types.py`의 pydantic 클래스 — 로, 보고에 쓰이는 인용 텍스트와 본문과 점수를 함께 실어 나른다. 채점은 그중 아무것도 읽지 않는다. 정확히 네 개의 식별 필드 — `doc_id`, `source_sha256`, `start_char`, `end_char` — 와 히트 리스트의 순서만 사용하고, `GoldenSpan`도 같은 네 필드를 가진다. 판정이 의존하는 것은 전부 좌표와 출처이지 텍스트가 아니다.

### 2. 점수와 함께 남기는 근거

#### `app/evals/scoring.py` 확장 — 결과 레코드

**학습 행동 — 레코드 선언 작성:** `CaseScore`가 지표 세 개 외에 어떤 값을 더 저장하는지 확인한다.

<!-- src: app/evals/scoring.py::CaseScore,SuiteScore -->
```python
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
```

**코드에서 꼭 볼 것**

- `gold_span_count`와 `matched_gold_count`를 재현율과 **함께** 저장한다. 재현율 0.5라는 값만으로는 정답 두 개 중 하나를 찾은 것인지 열 개 중 다섯 개를 찾은 것인지 구분할 수 없다.
- `first_relevant_rank`의 타입은 `int | None`이다. 관련 결과가 없는 경우는 순위가 0이 아니라 존재하지 않는 것이므로, 0으로 저장하면 1위로 찾은 경우와 값이 뒤섞인다.
- `SuiteScore`는 `cases` 튜플을 그대로 보관한다. 집계 점수만 남기면 어떤 질문이 점수를 떨어뜨렸는지 확인할 수 없다.

> **개념 — 저쪽은 pydantic, 이쪽은 dataclass인 이유**
>
> 검색 타입들이 pydantic 모델인 이유는 신뢰 경계에 서 있기 때문이다. 데이터베이스에서 온 행과 아티팩트에서 온 JSON은 외부 입력이고, 나머지 코드가 의존하기 전에 모든 필드를 검증해야 한다. 검증은 생성할 때마다 비용이 들지만, 경계에서는 치를 만한 값이다.
>
> 점수 레코드에는 그런 경계가 없다. 이 모듈이 프로세스 안에서, 들어올 때 이미 검증된 값들로 만들어 낸다. frozen에 slots를 더한 dataclass는 실제로 필요한 것 — 불변성, 적은 메모리, 값 동등성 — 을 주면서 신뢰된 값을 다시 검증하지 않는다. 여기서 더 무거운 도구를 집으면 얻는 것이 없다.

### 3. 겹침 계산과 해시 관문

#### `app/evals/scoring.py` 확장 — IoU 계산

**학습 행동 — 겹침 계산 구현:** 첫 두 줄의 가드를 먼저 작성하고, 그다음 교집합과 합집합 계산을 직접 구현한다.

<!-- src: app/evals/scoring.py::_validate_k,span_iou -->
```python
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
```

**코드에서 꼭 볼 것**

- 해시 비교가 **좌표 산술보다 먼저** 실행된다. 다른 스냅샷의 청크는 좌표를 계산할 필요 없이 무관한 결과다.
- `max(0, min(ends) - max(starts))`는 음수 겹침을 0으로 만든다. 두 구간이 떨어져 있으면 이 뺄셈이 음수가 되고, 그 값을 그대로 쓰면 합집합 계산이 틀어진다.
- `overlap == 0`을 조기 반환으로 따로 처리한다. 이 분기가 없어도 0을 합집합으로 나눠 같은 값이 나오지만, 맞닿기만 한 구간을 겹치지 않은 것으로 본다는 판단을 코드에 남긴다.
- `_validate_k`는 `isinstance(k, bool)`을 먼저 거부한다. `True`는 `int`의 하위 타입이므로, 이 검사가 없으면 `k=True`가 `k=1`로 실행된다.

### 4. 중복이 점수를 부풀리지 못하게 한다

#### `app/evals/scoring.py` 확장 — 사례 채점

**학습 행동 — 재현율 규칙 구현:** `matched_gold`를 집합으로 모으는 이유를 설명할 수 있어야 한다. 무엇을 세는지가 이 함수의 핵심이다.

<!-- src: app/evals/scoring.py::_is_relevant,score_case -->
```python
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
```

**코드에서 꼭 볼 것**

- `matched_gold`는 **정답 인덱스의 집합**이다. 검색 결과가 아니라 정답을 세므로, 같은 정답을 덮는 청크가 세 개여도 재현율은 한 번만 오른다.
- 반대 방향은 허용한다. 넓은 청크 하나가 서로 다른 정답 두 개를 각각 임계값 이상으로 덮으면 둘 다 집계한다. 이 경우는 정답 두 개를 실제로 찾은 것이다.
- `golden_spans`가 비어 있으면 거부한다. absent 사례가 이 함수에 들어오면 재현율의 분모가 0이 되어 계산이 실패하거나, 0으로 집계되어 검색 실패와 같은 값이 된다. M3.1에서 분리한 두 종류의 케이스가 이 가드로 유지된다.
- `first_relevant_rank`는 `enumerate(top_hits, start=1)`로 1부터 센다. MRR의 정의가 1부터 시작하는 순위를 사용하기 때문이다.

### 5. 사례마다 같은 무게를 준다

#### `app/evals/scoring.py` 완성 — 집계

**학습 행동 — 매크로 평균 구현:** 집계 함수 네 개가 모두 `_validated_scores`를 먼저 호출하는 이유를 확인한다.

<!-- src: app/evals/scoring.py::_validated_scores,score_suite -->
```python
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

**코드에서 꼭 볼 것**

- `_validated_scores`는 사례를 `case_id`로 정렬한다. 입력 순서가 달라도 `SuiteScore.cases`의 순서가 같으므로 두 실행의 결과를 그대로 비교할 수 있다.
- 모든 사례의 `k`가 같은지 확인한다. 상위 5개로 채점한 사례와 상위 10개로 채점한 사례를 한 평균에 넣으면 그 값은 어느 조건의 지표도 아니게 된다.
- 네 집계가 모두 `sum(...) / len(scores)` 형태다. 사례 수로 나누므로 정답 구간이 많은 질문이 평균을 끌지 않는다. 매크로 평균이 코드로 표현된 지점이다.
- `mean_reciprocal_rank`는 `mrr`을 그대로 호출한다. 축약형과 전체 이름을 모두 공개해 호출부가 읽기 쉬운 이름을 쓰게 한다.

### 집중 테스트와 테스트가 지키는 계약

```bash
uv run pytest tests/evals/test_02_scoring.py -q
```

| 테스트가 깨뜨리는 값 | 지키는 계약 |
|---|---|
| 좌표는 같고 해시가 다른 hit | 다른 스냅샷의 청크가 점수를 부풀리지 않는다. |
| 맞닿기만 한 두 구간 | 반열린 경계에서 겹침이 0이다. |
| 같은 정답을 덮는 청크 여러 개 | 재현율이 중복으로 오르지 않는다. |
| `k=True` | 불리언이 정수 k로 통과하지 않는다. |
| 서로 다른 k가 섞인 사례들 | 의미 없는 평균이 만들어지지 않는다. |
| 입력 순서만 다른 같은 사례들 | 집계 결과가 실행 사이에 흔들리지 않는다. |

그 스위트의 경계 하나는 단언이 아니라 측정으로 박혀 있다. 골든 구간 `[100, 200)`에 대해 테스트는 `[190, 300)` 히트를 넣는다 — 겹침 10, 합집합 200, IoU는 정확히 10/200 = 0.05 — 그리고 이 히트가 통과할 것을 요구해서 비교가 포함형 `>=`임을 못 박는다. 히트를 다섯 글자 밀어 `[195, 300)`으로 만들면 반드시 탈락해야 한다. 구현이 언젠가 엄격 부등호로 미끄러지면 이 테스트가 잡아낸다.

### 여기까지 왔을 때 설명할 수 있어야 하는 것

다음 질문의 답은 앞에서 **굵게 표시한 핵심 문장**에 있다. 각 답을 해당 함수와 연결해 설명해 본다.

- **IoU 임계값이 0.05로 낮은 이유는 무엇인가?**
  - **답:** 완전 포함일 때 IoU는 정답 길이 나누기 청크 길이로 줄어드는데, 측정된 청크는 정답보다 몇 배씩 넓은 것이 보통이라 완전히 포함한 청크도 0.05 아래로 떨어질 수 있다. 낮은 문턱은 포함 관계 대부분을 인정하기 위한 것이고, 경험적으로 튜닝된 값이 아니다.
- **좌표 계산보다 해시 비교가 먼저인 이유는 무엇인가?**
  - **답:** 서로 다른 원문 스냅샷의 같은 좌표는 다른 텍스트를 가리킬 수 있으므로, 좌표 중첩이 관련성을 부풀리기 전에 낡은 증거를 거부해야 한다.
- **재현율이 검색 결과가 아니라 정답을 세는 이유는 무엇인가?**
  - **답:** 재현율은 필요한 증거를 얼마나 찾았는지 측정한다. 검색 히트를 세면 같은 정답을 덮는 여러 청크가 점수를 반복해서 올릴 수 있다.
- **매크로 평균과 마이크로 평균 중 매크로를 고른 이유는 무엇인가?**
  - **답:** 매크로 평균은 각 질문에 같은 가중치를 준다. 마이크로 평균은 정답 구간이 많은 질문이 전체 점수를 지배하게 한다.
- **채점 계층에 I/O가 하나라도 있으면 무엇을 판단할 수 없게 되는가?**
  - **답:** 점수가 바뀌었을 때 검색이 달라진 것인지 채점 과정의 외부 상태가 달라진 것인지 판단할 수 없다.

---

[← 이전: 골든 로더](02-golden-loader.md) · [모듈 개요](../03-build.md) · [다음: 회귀 비교 →](04-regression.md)
