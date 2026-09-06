# M3.1 튜토리얼 1 — 정답을 무엇으로 표현할 것인가

평가 데이터셋은 질문마다 정답 근거가 어디인지 기록한 파일이다. 이 문서에서 결정할 것은 그 근거를 어떤 형식으로 적을지다.

가장 간단한 형식은 청크 ID다. `chunk_id: 4821` 한 줄로 정답을 지정할 수 있다.

그러나 이 형식은 M3가 하려는 실험 자체를 막는다.

M1은 불변 코퍼스를 남겼다 — 네 티커의 filing 20건이 `data/corpus/` 아래에 커밋되어 있다. M2는 질의에 그럴듯한 청크를 돌려주는 검색 스택을 남겼다. 어느 쪽도 남기지 않은 것은 그 청크가 맞는 청크인지 말할 방법이다. 이 문서에서 측정 도구 제작을 시작하는데, 가장 위험한 지점부터 시작한다. 정답지 자체의 타입 계약이다.

이 위험은 정확히 짚을 가치가 있다. 망가진 정답지는 망가져 보이지 않기 때문이다. 검색 버그는 잘못된 청크를 반환하고 평가가 그것을 잡는다. 오염된 골든 케이스 — 뒤바뀐 오프셋, 오타 난 필드, 낡은 해시 — 는 그대로 채점에 쓰이고, 다운스트림의 모든 지표가 그 오류를 물려받는 동안 테스트는 전부 초록으로 남는다. 정답지 위에는 정답지를 검사할 장치가 없다. 그래서 이 파일이 세우는 불변조건은 의도적으로 절대적이다. **골든 케이스는 큐레이터가 커밋한 그대로 로드되거나, 어느 필드가 문제인지 이름을 대며 로드를 거부한다. 조금 다른 값으로 조용히 로드되는 세 번째 경로는 없다.**

**선행 조건:** M2가 끝나 `uv run pytest tests/retrieval -q`가 통과해야 한다.

### 골든셋 — 채점에는 정답지가 먼저 필요하다

M2를 끝낸 시점의 검색은 동작한다. 그러나 "동작한다"와 "잘 찾는다"는 서로 다른 주장이고, 뒤쪽 주장에는 근거가 필요하다. 질의 하나를 넣어 보고 그럴듯한 청크가 나오는 것을 확인하는 방식은 측정이 아니라 감상이다.

그래서 평가에는 **골든셋(golden set)**이 필요하다. "이 질문의 정답 근거는 원문의 여기다"를 미리 확정해 둔 기록의 모음이며, 시스템이 무엇을 반환하든 이 기록과 대조해서 점수를 계산한다. 정답지가 먼저 있어야 채점이 가능하고, 채점이 가능해야 "바꿨더니 좋아졌다"가 일화가 아니라 숫자가 된다.

이 저장소에는 그 정답지가 이미 `data/golden/retrieval.json`으로 들어와 있다. M1에서 시드한 네 티커의 10-K 코퍼스 위에 28개 케이스 — 정답 구간이 있는 positive 24개와 "문서에 없음"이 정답인 absent 4개 — 가 담겨 있다. **M3에서 작성하는 것은 이 파일이 아니라, 이 파일을 읽고 검증하고 채점하는 기계장치다.**

출처를 분명히 하자. 골든셋의 정석은 도메인 전문가가 손으로 작성하는 것이다. 이 저장소에서는 참조 구현을 만든 코딩 에이전트가 코퍼스를 읽으며 질문과 근거 구간을 선별해 작성했고, 해시·경계·유일성 같은 구조 검증은 기계로 마쳤다. 그러나 내용이 옳은지는 아직 사람이 판정한 적이 없다. 그래서 모든 케이스에 `curation_status`, `approval_status`, `human_verified` 세 상태 필드가 박혀 있고 검토 전 값이 리터럴로 고정되어 있다 — 검토되지 않은 데이터가 검토된 것처럼 보이는 것을 타입이 막는다. 승인을 기다리는 상대는 이 저장소의 작성자이며, 케이스별 검토 절차는 `data/golden/REVIEW.md`에 있다.

수명주기로 펼쳐 보면 이 정답지는 이미 두 상태를 지나 세 번째 상태에 서 있다. **생성:** LLM 코딩 에이전트가 불변 filing 20건을 읽고 근거 구간과 함께 케이스 28개를 작성했다. **기계 검증 완료:** 모든 구간의 해시가 커밋된 파일 바이트와 일치하고, 모든 구간이 경계 안에 있으며 비어 있지 않고, id·질문·구간 정체성이 고유하며, 커밋된 구간 중 2,500자 상한을 넘는 것이 없다 — 가장 긴 구간이 2,280자다. **검토 대기:** 28개 케이스 전부가 같은 상태 트리플 — `agent-curated`, `pending-author-approval`, `human_verified: false` — 을 달고 있고, 이 상태에서 케이스를 꺼내는 것은 코드가 아니라 검토 큐를 따라가는 작성자다. 케이스마다 참조 답변에 필요한 모든 사실이 인용된 구간 안에 있는지 확인하고, absent 케이스라면 그 사실이 단지 찾기 어려운 게 아니라 코퍼스에 정말로 없는지 확인한다. 승인 상태를 바꿀 수 있는 것은 작성자뿐이며, 새 후보를 이 파일로 승격하는 기계장치는 M3.5의 주제다.

이 스위트의 형태 자체가 테스트 계약으로 동결되어 있어서, 아무도 보지 않는 사이에 파일이 조용히 달라질 수 없다. `tests/evals/golden.py`가 커밋된 파일이 만족해야 하는 개수들을 기록하고, 다음 문서의 로더 테스트(`tests/evals/test_02_loader.py`)가 그 전부를 단언한다 — `retrieval.json`을 고치면 같은 검토된 커밋에서 상수를 함께 바꾸기 전까지 스위트가 실패한다.

<!-- src: tests/evals/golden.py::CASE_COUNT,POSITIVE_TICKER_COUNTS -->
```python
CASE_COUNT = 28
POSITIVE_CASE_COUNT = 24
ABSENT_CASE_COUNT = 4
POSITIVE_DOCUMENT_COUNT = 20
DEMO_HERO_COUNT = 8
MAX_ANSWER_SPAN_CHARS = 2_500

CATEGORY_COUNTS = {
    "simple_lookup": 13,
    "exact_number": 5,
    "multi_hop": 6,
    "absent": 4,
}

FACET_COUNTS = {
    "factual": 6,
    "comparison": 6,
    "risk": 6,
    "policy": 5,
    "numeric": 5,
}

POSITIVE_TICKER_COUNTS = {"AMD": 6, "INTC": 6, "MU": 6, "NVDA": 6}
```

이 숫자들은 장식이 아니다. 티커당 positive 6개에 filing 20건이 전부 인용된다는 것은 코퍼스에 놀고 있는 filing이 없다는 뜻이고, 카테고리·패싯 개수가 고정되어 있다는 것은 나중에 난이도·근거 유형별로 지표를 쪼갤 때 비어 있는 그룹이 생기지 않는다는 뜻이다. `demo-hero` 태그 8개 — 티커당 2개 — 까지 고정되어 있어서, 스위트의 형태를 바꾸는 어떤 편집도 눈에 띄지 않고 지나갈 수 없다.

사용 방향도 못박아 두자. **움직이는 쪽은 검색이고 골든셋은 동결이다.** M2의 설정 — 청크 크기, 융합 가중치, 임베딩 — 을 바꾸면 같은 정답지로 다시 채점해서 지표의 변화로 판단한다. 반대 방향, 즉 점수를 올리기 위해 정답지를 고치는 일은 측정 자체를 무효로 만든다.

### 청크 ID로 정답을 적으면 실험을 못 한다

M3가 측정할 항목 중 하나가 청크 크기다. `target_text_chars`를 1,200에서 800으로 바꿨을 때 검색 품질이 오르는지 확인해야 한다.

청크 크기를 바꾸면 문서가 전부 다시 나뉘고 청크 ID도 전부 새로 부여된다. 정답 파일의 `chunk_id: 4821`은 그 시점부터 존재하지 않는 행을 가리키거나 다른 텍스트를 가리킨다.

정답 데이터를 다시 만들지 않으면 두 설정을 비교할 수 없다. 이 스위트 기준으로 재작성은 정답 구간 34개를 손으로 다시 잡고 전부 다시 검토한다는 뜻이다 — 다시 잡은 정답은 새로운 주장이기 때문이다. 이만한 수고 앞에서 실제로는 실험을 하지 않는 쪽이 선택된다.

**측정 도구가 측정 대상의 산출물에 의존하면, 대상을 바꾸는 순간 도구가 무효가 된다.** 청크 ID로 적은 정답 파일이 정확히 이 상태이고, 그래서 청크 설정을 바꾸는 실험이 불가능해진다.

### 그래서 원문 좌표로 적는다

M1.3에서 인용을 청크 ID가 아니라 원문 좌표로 설계한 이유가 이 지점에서 드러난다. 정답도 같은 좌표계로 적는다.

```text
(doc_id, source_sha256, start_char, end_char)
```

**청크를 어떻게 나누든 원문에서의 위치는 변하지 않는다.** 그래서 청크 크기를 바꿔 가며 같은 정답 파일로 결과를 비교할 수 있다.

`source_sha256`을 함께 적는 이유는 좌표가 특정 파일 스냅샷 안에서만 의미를 갖기 때문이다. filing을 다시 내려받아 바이트가 달라지면 해시가 일치하지 않고, 로더가 그 정답 파일을 거부한다. **해시가 없으면 좌표가 다른 내용을 가리키는 상태로 평가가 끝까지 실행되고, 오류 없이 잘못된 점수가 남는다.**

> **개념 — 반열린 구간과 디코딩된 원문 오프셋**
>
> `start_char`는 포함되고 `end_char`는 제외된다. 이 관례는 구간 산술에서 off-by-one 오류를 없애는 형식이다. 길이가 보정항 없이 정확히 `end_char - start_char`이고, 인접한 두 구간은 겹침도 틈도 없이 이어 붙으며, 이 쌍은 파이썬 슬라이싱 관례와 같아서 기록된 쌍으로 디코딩된 원문을 자르면 근거가 글자 그대로 나온다. 닫힌 구간은 이 지점마다 ±1 판단을 되살리고, 그 판단 하나하나가 조용히 틀릴 수 있는 자리다.
>
> 오프셋이 무엇을 가리키는지도 마찬가지로 의도된 선택이다. UTF-8로 디코딩된 원본 filing이지, 청크 ID도 정제된 텍스트도 아니다. 청크 ID는 재청킹에서 죽는다 — 이 문서 전체의 논지다. 정제된 텍스트도 그에 못지않게 취약하다. 정제 규칙이 개선될 때마다 좌표가 밀리므로, 개선 하나하나가 정답지를 좌초시킨다. 원본 스냅샷은 파이프라인에서 절대 변하지 않는 유일한 계층이고, 해시는 그것이 변하지 않았음을 보증하기 위해 존재한다.

이것은 지금 당장 커밋된 데이터로 확인할 수 있다. `m3c-28` 케이스는 NVIDIA의 2024 회계연도 매출과 순이익을 묻고, 첫 정답 구간은 원본 NVDA filing의 639자를 지목한다. 저장소 루트에서 이 주장을 재생해 보자.

```bash
python3 -c "
import hashlib, json
case = [c for c in json.load(open('data/golden/retrieval.json')) if c['id'] == 'm3c-28'][0]
span = case['answers'][0]
raw = open('data/corpus/NVDA/2024-02-21_0001045810-24-000029.html', 'rb').read()
print('sha256 match:', hashlib.sha256(raw).hexdigest() == span['source_sha256'])
print('span length :', span['end_char'] - span['start_char'])
print('span head   :', raw.decode('utf-8')[span['start_char']:span['end_char']][:60])
"
```

```text
sha256 match: True
span length : 639
span head   : Revenue</span></td><td style="background-color:#f1f2f2;borde
```

이 출력에서 정직하게 짚을 것이 둘 있다. 구간 머리가 원시 테이블 마크업인 것은 — 매출 수치 60,922는 구간 안쪽의 `<td>` 셀들 속에 있다 — 좌표가 불변 원본 HTML에 정박하기 때문이다. 검토 시점에 근거를 읽기 좋게 만드는 것은 렌더러의 일이지 좌표의 일이 아니다. 그리고 질문이 두 가지 사실을 요구하므로 케이스는 구간 두 개를 담는다 — 순이익은 649자짜리 두 번째 구간에 있다. 늘려 잡은 구간 하나가 아니라 촘촘한 구간의 튜플이, 여러 사실을 묻는 정답이 정밀함을 유지하는 방식이다.

### 정답이 "없음"인 경우도 데이터에 넣는다

케이스가 두 종류다.

- **positive** — 구간이 하나 이상 있다
- **absent** — 구간이 없다. 이 문서에 그 정보가 **없는 게 맞다**

`absent` 케이스가 필요한 이유는 RAG의 흔한 실패가 문서에 없는 내용을 만들어 내는 것이기 때문이다. NVDA 10-K에 없는 내용을 물었을 때 시스템이 무언가를 찾아 답하면, 사용자는 그 답에 근거가 없다는 사실을 알 수 없다.

커밋된 absent 케이스 네 개는 남은 자투리가 아니라 설계된 질문이다. AMD의 분기 배당금 선언액, Intel의 상용 양자컴퓨팅 구독 서비스, Micron의 랜섬웨어 지불액, NVIDIA 이사회가 승인한 비밀번호 교체 주기를 묻는다 — 하나같이 10-K가 공시할 법하게 들리지만 코퍼스는 실제로 공시하지 않는 내용이다. 큐레이션 에이전트의 전체 코퍼스 정찰에서 네 질문 모두 답이 나오지 않았고, 그래도 검토 큐는 작성자가 각 부재를 독립적으로 확인하도록 요구한다. "에이전트가 못 찾았다"와 "없다"는 다른 주장이기 때문이다.

**`absent` 케이스를 재현율 0인 검색 실패로 집계하면 안 된다.** 이 케이스가 묻는 것은 정답 구간을 찾았는지가 아니라 없다고 답할 수 있는지이므로, 검색 지표가 아니라 라벨 평가로 다뤄야 한다. M3.2의 점수 계산이 두 집계를 분리한다.

> 이 골든 데이터의 출처는 산문이 아니라 데이터다. 현재 상태는 **에이전트 선별, 작성자 승인 대기, 사람 미검증**이다. 평가 결과를 읽을 때 이 한계를 같이 봐야 한다.

### 무엇을 작성하고 어디를 직접 구현할까

이 문서는 `app/evals/types.py` 한 파일을 세 단계로 작성한다. 파일을 읽어 들이는 로더는 다음 문서에서 만든다.

| 구간 | 학습 행동 | 여기서 얻어야 하는 것 |
|---|---|---|
| 모듈 헤더와 값 어휘 | **설정 스키마 정의** | 평가가 다루는 값의 종류가 유한하다는 것 |
| `GoldenSpan` | **모델 선언 작성 후 설계 검토** | 정답이 청크가 아니라 원문에 묶이는 방식 |
| `GoldenCase`의 검증기 | 핵심 검증 로직을 **직접 구현** | positive와 absent가 서로 배타가 되는 조건 |

### 1. 모듈 헤더와 값 어휘

#### `app/evals/types.py` 생성 — 모듈 헤더와 타입 별칭

**학습 행동 — 설정 스키마 정의:** 다섯 개의 별칭을 작성하면서, 각각이 왜 자유 문자열이 아니라 닫힌 목록인지 확인한다.

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
```

**코드에서 꼭 볼 것**

- `GoldenCategory`와 `GoldenFacet`은 `Literal`이다. 새 분류를 추가하려면 코드를 수정해야 하므로, 그 시점에 기존 결과와 비교 가능한지 판단하게 된다. 자유 문자열이었다면 오타로 생긴 `"exact_numebr"` 카테고리가 오류 없이 별도 그룹으로 집계된다.
- `GoldenTag`의 정규식은 kebab-case만 허용한다. 태그는 분석에서 그룹 키로 사용하므로 `"multi hop"`과 `"multi-hop"`이 서로 다른 그룹이 되면 안 된다.
- `SourceSha256`은 M2.1의 같은 이름 별칭과 정확히 같은 정규식이다. 평가와 검색이 같은 형식으로 스냅샷을 가리켜야 좌표가 서로 통한다.

왜 `Literal`이고 `Enum`이 아닌가? 열거형도 닫힌 집합은 준다. 그러나 번역 계층이 하나 끼어든다. JSON 파일에는 `"absent"`가 있는데 코드에는 열거형 멤버가 있어서 직렬화, 비교, 오류 메시지가 전부 그 매핑을 거친다. `Literal`은 파일의 값과 타입의 값을 동일하게 유지한다 — 큐레이터가 적은 그 값을 검증기가 거부할 때 그대로 이름으로 부른다. 이 정도로 작고 안정적인 어휘에서 간접 계층은 사 주는 것이 없다.

### 2. `GoldenSpan` — 청크가 아니라 원문을 가리킨다

| `GoldenSpan` 필드 | 값 또는 제약 | 역할 |
|---|---|---|
| `doc_id` | 비어 있지 않은 filing 식별자 | 답을 포함한 filing을 선택한다. |
| `source_sha256` | 소문자 16진수 64자 | 답을 하나의 불변 원문 스냅샷에 고정한다. |
| `start_char`, `end_char` | 비어 있지 않은 반열린 범위 | 청크 경계에 의존하지 않고 정확한 정답 근거를 찾는다. |

#### `app/evals/types.py` 확장 — `GoldenSpan`

**학습 행동 — 모델 선언 작성 후 설계 검토:** 네 필드는 주어진 대로 작성한다. 검증기가 `>`를 쓰고 `>=`를 쓰지 않는 이유를 설명할 수 있어야 한다.

<!-- src: app/evals/types.py::GoldenSpan -->
```python
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
```

**코드에서 꼭 볼 것**

- 필드가 네 개뿐이다. 질문도, 본문 텍스트도, 청크 정보도 없다. 이 타입이 표현하는 것은 원문의 한 구간뿐이다.
- `end_char <= start_char`를 거부하므로 빈 구간은 정답이 될 수 없다. 길이가 0인 정답은 어떤 검색 결과와도 겹치지 않으므로, 항상 실패하는 케이스가 오류 없이 데이터에 남는다.
- `frozen=True`이므로 채점 도중에 정답이 바뀌지 않는다. 정답이 실행 중에 변경될 수 있으면 계산된 점수가 어느 정답에 대한 값인지 확정할 수 없다.

> **개념 — 정답지 경계의 엄격 타입**
>
> Pydantic의 기본 검증은 의도적으로 관대하다. 평범한 `int` 필드는 문자열 `"10"`을 받고, 파이썬의 bool이 int의 하위 클래스라서 `True`를 1로 받는다. 애플리케이션 코드 안에서라면 이 관용이 무해한 표현 차이를 흡수해 준다. 정답지 경계에서는 같은 관용이 오염 통로가 된다. 오프셋을 문자열로 내보내는 큐레이션 스크립트, 숫자 자리에 끼어든 불리언이 만든 파일이 소리 없이 로드되고, 그 뒤의 모든 실행을 채점한다.
>
> `StrictInt`는 둘 다 거부한다 — 값이 정수로 만들 수 있는 무엇이 아니라 이미 정수여야 한다. `extra="forbid"`는 필드 어휘를 닫아서, 스키마가 선언하지 않은 키 — 오타든 낡은 `chunk_id`든 — 를 조용히 무시되는 동승자가 아니라 오류로 만든다. `frozen=True`는 마지막 창, 즉 로드 이후를 닫는다. 어떤 코드 경로도 채점 도중에 필드를 재할당할 수 없다.
>
> 셋을 관통하는 설계 규칙은 이것이다. 정답지는 그것이 채점하는 시스템보다 오염되기 어려워야 한다. 검색 버그는 나쁜 출력을 내고 평가가 그것을 표시한다. 정답지 버그는 모든 것에 대한 그럴듯한 평가를 내는데, 그것을 표시할 두 번째 정답지는 없다.

### 3. `GoldenCase` — positive와 absent를 서로 배타로 만든다

| `GoldenCase` 필드 | 값 또는 제약 | 역할 |
|---|---|---|
| `id` | `m3c-NN` | 검토된 case에 안정적인 평가 식별자를 부여한다. |
| `question` | 비어 있지 않은 텍스트 | 평가할 검색 질문을 저장한다. |
| `category` | `"simple_lookup"`, `"exact_number"`, `"multi_hop"`, 또는 `"absent"` | 검색 난이도와 부재 동작에 따라 case를 묶는다. |
| `facet` | `"factual"`, `"comparison"`, `"risk"`, `"policy"`, 또는 `"numeric"` | 필요한 근거의 성격을 나타낸다. |
| `tags` | 고유한 kebab-case 값 | 핵심 분류를 바꾸지 않고 더 좁은 분석 레이블을 붙인다. |
| `answers` | `GoldenSpan` 값의 튜플 | 원문에 안정적으로 묶인 정답을 담으며 absent case에서만 비어 있다. |
| `expected_label` | `"SUPPORTED"` 또는 `"NOT_IN_DOCS"` | 코퍼스가 답을 뒷받침해야 하는지 명시한다. |
| `reference_answer` | 비어 있지 않은 텍스트 | 검토된 목표 답변이나 부재 문구를 기록한다. |
| `note` | 비어 있지 않은 텍스트 | case별 검토 문맥을 보존한다. |
| `curation_status` | `"agent-curated"` | 현재 작성 주체의 출처를 명시한다. |
| `approval_status` | `"pending-author-approval"` | 초안 case가 작성자 승인으로 보이는 것을 막는다. |
| `human_verified` | 정확히 `False` | 검토되지 않은 근거가 사람 검증을 마친 것으로 제시되지 않게 한다. |

#### `app/evals/types.py` 완성 — `GoldenCase`

**학습 행동 — 검증 로직 구현:** 필드 선언을 먼저 작성한다. 그다음 검증기 네 개를 직접 구현하면서, 각 검증기가 어떤 형태의 잘못된 정답 파일을 막는지 확인한다.

<!-- src: app/evals/types.py::GoldenCase -->
```python
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

**코드에서 꼭 볼 것**

- `human_verified: Literal[False]` 위에 `mode="before"` 검증기가 하나 더 붙어 있다. 타입 선언만으로는 보이는 것보다 많은 값을 받는다. Pydantic은 숫자 `0`을 실수 형태까지 포함해 이 리터럴로 변환해 `False`로 저장하고, `""` 같은 문자열은 거부한다. 검토 상태를 `0`으로 적은 파일이 큐레이터가 불리언을 의도적으로 적은 파일과 구분되지 않게 로드된다는 뜻이다 — **로드에 성공했다는 사실이 명시적 검토 상태가 기록됐다는 증거가 되지 못한다.** 그래서 검증기는 변환 전에 실행되어 원시 JSON 값을 보고, 정확히 불리언 `false`가 아닌 값을 전부 거부한다.
- `validate_label_and_answers`는 세 필드를 함께 검사한다. `category`, `expected_label`, `answers`는 각각 따로 보면 모두 유효하지만 조합이 모순일 수 있다. absent인데 구간이 있거나, positive인데 `NOT_IN_DOCS`를 기대하는 경우다.
- **필드를 따로 검사하면 이 모순을 잡을 수 없다. absent 케이스에 정답 구간이 하나라도 들어가면 M3.2가 그 구간을 재현율 계산에 넣고, 없다고 답해야 하는 질문이 못 찾은 질문으로 집계된다.** 점수는 나오지만 그 값이 무엇을 측정했는지 확인할 수 없다.
- 정답 구간의 중복도 거부한다. 같은 구간이 두 번 들어가면 재현율의 분모가 실제보다 커진다.

> **개념 — 리터럴로 고정한 출처 필드, fail-closed 스키마**
>
> 세 상태 필드는 각각 정확히 하나의 값만 허용한다. 즉 오늘의 스키마는 승인된 케이스를 표현할 수조차 없다. 승인됐고 사람이 검증했다고 주장하는 파일은 로드되지 않는다 — 어떤 규칙이 거부해서가 아니라, 타입에 그것을 적을 철자가 없어서다. 제약처럼 보이지만 이것이 설계다. "사람이 이것을 검증했다"는 주장은 리터럴 타입을 넓히는 코드 변경으로만 시스템에 들어올 수 있고, 코드 변경은 조용한 데이터 편집과 달리 리뷰되고 diff로 남고 승인 절차를 거친다.
>
> 뻔한 대안 — 승인 상태까지 포함해 전체 어휘를 미리 선언하는 것 — 은 fail-open이다. 스키마가 출하되는 첫날부터 데이터 파일이 일어난 적 없는 승인을 주장할 수 있고, 스키마는 고개를 끄덕인다. fail-closed는 그 기본값을 뒤집는다. 검토 기계장치가 생기기 전까지는 그 부재 자체가 타입으로 강제된다. 이 어휘를 넓히는 승격 경로를 만드는 것이 M3.5의 작업이다.

### 집중 테스트와 테스트가 지키는 계약

```bash
uv run pytest tests/evals/test_01_contract.py -q
```

이 테스트는 지금 존재하지만 아직 통과하지 않는다. 다음 문서의 공개 API 단계에서 심볼이 패키지에 공개되기 전까지는 전부 `not implemented yet`으로 skip되고, 그 지점부터 18개 전부가 초록으로 바뀐다.

| 테스트가 깨뜨리는 값 | 지키는 계약 |
|---|---|
| 알 수 없는 추가 필드 | 정답 파일의 오타가 조용히 무시되지 않는다. |
| 뒤집히거나 빈 구간 | 어떤 검색 결과와도 겹칠 수 없는 정답이 생기지 않는다. |
| 중복된 정답 구간 | 재현율 분모가 부풀려지지 않는다. |
| absent인데 구간이 있는 case | 부재 판정과 검색 실패가 섞이지 않는다. |
| positive인데 `NOT_IN_DOCS` 라벨 | 라벨과 근거가 같은 것을 말한다. |
| `human_verified`가 `True` 또는 `0` | 검토 상태는 커밋된 검토 전 값만 허용하며, 비슷해 보이는 대체 값은 변환 전에 거부된다. |

### 여기까지 왔을 때 설명할 수 있어야 하는 것

다음 질문의 답은 앞에서 **굵게 표시한 핵심 문장**에 있다. 각 답을 해당 타입 또는 검증기와 연결해 설명해 본다.

- **정답을 청크 ID로 적으면 어떤 실험이 불가능해지는가?**
  - **답:** 청크 크기를 바꾸면 모든 ID와 정답 데이터가 무효가 되므로, 같은 골든 세트로 청크 크기를 비교하는 실험을 할 수 없게 된다.
- **`source_sha256`이 정답에 함께 들어가야 하는 이유는 무엇인가?**
  - **답:** 좌표는 정확히 한 원문 스냅샷 안에서만 증거를 식별한다. 해시는 다시 받거나 변경된 파일을 거부해 낡은 정답을 조용히 채점하지 않게 한다.
- **`absent` 케이스를 재현율 0으로 세면 안 되는 이유는 무엇인가?**
  - **답:** 찾을 골든 구간이 없으므로 M3는 검색을 실행하되 점수를 `None`으로 기록하고 검색 지표에서 제외한다. 이렇게 잘못된 재현율 벌점을 막지만, M3가 시스템이 `NOT_IN_DOCS`라고 답하는지를 시험하는 것은 아니다.
- **`human_verified`에 별도 검증기가 필요한 이유는 무엇인가?**
  - **답:** 타입 표기만으로는 숫자 `0`이 `False`로 강제 변환될 수 있다. 검증기는 명시적인 JSON 불리언만 허용해 검토 출처가 잘못 표현되지 않게 한다.
- **세 필드를 함께 보는 모델 검증기가 필드별 검증으로 대체될 수 없는 이유는 무엇인가?**
  - **답:** `category`, `expected_label`, `answers`는 각각 유효해도 함께 보면 정답 구간이 있는 absent 사례처럼 모순일 수 있기 때문이다.
- **스키마가 승인된 케이스를 표현할 수 없는 것이 왜 의도적인가?**
  - **답:** 상태 필드가 단일 리터럴 값으로 고정되어 있어, 승인은 타입을 넓히는 검토된 코드 변경으로만 들어올 수 있다. 아직 아무도 검증하지 않은 주장을 데이터 파일에 맡기는 대신 스키마가 fail-closed로 동작한다.

---

[모듈 개요](../03-build.md) · [다음: 골든 로더 →](02-golden-loader.md)
