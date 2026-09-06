# M1.1 튜토리얼 3 — 회사별 차이를 코드가 아니라 데이터로 다룬다

회사마다 헤딩 서식이 다르다는 문제를, 회사별 분기문이 아니라 **프로파일 JSON + 평가기 하나**로 푼다. L5가 그 평가기다.

L6은 성격이 다르다. 만들었지만 최종 규칙에는 쓰지 않기로 한 층이다. 측정이 가설을 기각한 기록이라 남겨 둔다.

**선행 조건:** 튜토리얼 2의 `uv run pytest tests/ingestion/test_01_blocks.py -v`가 전부 통과해야 한다.

## 무엇을 작성하고 어디를 직접 구현할까

| 구간 | 학습 행동 | 여기서 얻어야 하는 것 |
|---|---|---|
| L5 규약 표 | **설계 결정 확인** | 규칙을 쓰는 사람이 소스를 안 열어도 되게 하는 법 |
| L5 `matches_rule`·`matches_any` | 판정 규칙을 **직접 구현** | `in_table`이 비대칭인 이유 |
| L6 `body_after` | **구조 작성** | 만들었지만 채택하지 않은 층을 남기는 이유 |

---

## L5 — 규칙 평가기 — 코드와 데이터가 만나는 유일한 지점

이 프로젝트에서 "회사마다 다른 서식"은 코드가 아니라 데이터로 표현된다. NVIDIA용 분기문, AMD용 분기문을 짜는 게 아니라, 회사별 프로파일 JSON에 규칙을 적어두고 평가기 하나가 그걸 해석한다.

프로파일의 `rules`는 이렇게 생겼다.

```json
"rules": [
  {"font_weight": 700, "font_size": 10.0, "in_table": false}
]
```

"굵기 700 이상, 크기 10pt 이상, 표 밖에 있는 블록"이라는 뜻이다. 그런데 이 해석이 자명하지 않다. `700`이 "정확히 700"인가 "700 이상"인가? 안 적은 키는 어떻게 되나?

### 규약부터 문장으로 못 박는다

이게 없으면 규칙을 쓰는 사람이 매번 평가기 소스를 열어봐야 한다.

| 규약 | 의미 |
|---|---|
| 지정하지 않은 키 | 제약 없음 |
| 수치 | **이상** (`font_size: 14` = 14pt 미만 탈락) |
| 불리언·문자열 | 일치 |
| `in_table` | `false`=표 밖만, `true`=제약 없음 (**비대칭**) |
| 리스트 전체 | 하나라도 통과하면 헤딩 |

수치를 "이상"으로 정한 이유는 L9에서 다시 나온다. 학습이 "관측한 모든 헤딩을 통과시키는 가장 느슨한 규칙"을 만들기 때문에, 최솟값을 문턱으로 쓰는 게 자연스럽다.

`in_table`의 비대칭은 지금은 이상해 보일 것이다. 코드를 본 뒤에 설명한다.

### 구현

#### 대상 파일: `app/ingestion/parser.py`

<!-- src: app/ingestion/parser.py::matches_rule,matches_any -->
```python
def matches_rule(el: Tag, rule: dict) -> bool:
    props = block_props(el)
    for key, expected in rule.items():
        actual = props.get(key)
        if actual is None:
            continue  # an unknown key adds no constraint
        if key == "in_table":
            if not expected and actual:  # constrain only when False is expected
                return False
        elif isinstance(expected, bool) or isinstance(actual, bool):
            if actual != expected:
                return False
        elif isinstance(expected, int | float):
            if actual < expected:
                return False  # numeric rules are minimum thresholds
        elif actual != expected:
            return False
    return True


def matches_any(el: Tag, rules: list[dict]) -> bool:
    return any(matches_rule(el, r) for r in rules)
```

**코드에서 꼭 볼 것**

- `actual is None` 가드 하나와 그 `continue`가 "지정하지 않은 키는 제약을 더하지 않는다"는 규약의 구현이다. 프로파일이 지정했지만 `block_props`가 추출하지 않는 키도 조용히 건너뛴다.
- `in_table` 분기가 다른 분기보다 앞에 온다. 유일한 비대칭 키라서 일반 비교 규칙에 태울 수 없다.
- 불리언 검사가 수치 검사보다 앞이다. 파이썬에서 `True`는 `int`의 서브클래스라, 순서를 뒤집으면 불리언이 수치 비교로 새어 들어간다.
- `matches_any`는 규칙 목록을 OR로 묶는다. 하나만 통과해도 헤딩이다.

### 파이썬에서 가장 잘 밟는 함정 하나

코드를 보면 `isinstance(expected, bool)` 검사가 수치 검사보다 **앞에** 있다. 순서를 바꾸면 어떻게 될까.

파이썬에서 `bool`은 `int`의 서브클래스다. 즉 **`isinstance(True, int)`가 `True`다.** 그래서 수치 검사가 먼저 오면 `in_table: true`가 "1 이상인가"로, `in_table: false`가 "0 이상인가"로 해석된다. 뒤쪽은 **항상 참**이다.

결과적으로 "표 밖에 있는 블록만"이라는 제약이 통째로 사라지고, 목차의 Item 항목들이 전부 헤딩으로 잡힌다. 실제로 밟았던 버그다([B12](../04-bugs.md#b12)). 규칙이 JSON에서 오면 `true`가 자연스럽게 파이썬 `True`가 되기 때문에 더 걸리기 쉽다.

### `in_table`이 비대칭인 이유

앞에서 미뤄둔 이야기다. 20개 파일 중 **AMD FY2019 하나만** 헤딩이 표 안에 있다([F4](../01-findings.md#f4)).

그러면 `in_table: true`를 "반드시 표 안에 있어야 함"으로 해석하고 싶어진다. 그런데 그렇게 하면 AMD FY2019에서 학습한 규칙이 다른 연도에는 전혀 안 맞는다. AMD FY2020의 헤딩은 표 밖에 있으니까.

그래서 `true`는 "제약 없음"으로 정의했다. 실제로 필요한 제약은 한 방향뿐이다 — "표 안은 목차일 가능성이 높으니 제외"라는 `false` 쪽.

대칭적이지 않아서 보기 싫지만, 실측이 요구하면 따른다. 대신 규약 표에 굵게 적어서 다음 사람이 헷갈리지 않게 한다. **설계의 우아함보다 실측이 우선이고, 그 예외는 문서에 남긴다.**

### 관대함의 대가

`props.get(key)`가 `None`이면 그 키는 건너뛴다. 그래서 프로파일에 `font_wieght`처럼 오타를 내도 프로그램이 죽지 않는다.

관대해서 좋아 보이지만 뒤집어 보면 **오타를 영영 못 잡는다는 뜻**이다. 규칙을 고쳤는데 아무 변화가 없어서 한참 헤매다가, 알고 보니 키 이름이 틀렸더라는 상황이 가능하다.

더 나은 설계는 프로파일을 **저장할 때** 키 허용 목록으로 검증하는 것이다. 규칙을 만드는 곳은 학습 함수 하나뿐이라 거기 한 군데만 막으면 된다. 이 프로젝트는 아직 안 했다 — 알면서 남겨둔 부채다.

### 확인

```bash
uv run pytest tests/ingestion/test_02_rules.py -v
```

코퍼스 없이 0.1초에 끝난다. 규약 5개가 각각 테스트 하나씩이다.

**밟은 함정** — [B12](../04-bugs.md#b12) `bool`이 `int`의 서브클래스

### 여기까지 온 상태

이제 블록 하나와 규칙 리스트를 주면 "이 블록이 헤딩인가"에 답할 수 있다. 중요한 건 이 평가기가 **어느 전략이 그 규칙을 만들었는지 전혀 모른다**는 점이다. 규칙은 그냥 딕셔너리고, 평가기는 그걸 규약대로 해석할 뿐이다.

이 무지가 설계 의도다. 덕분에 새 회사·새 서식을 지원할 때 평가기를 건드릴 일이 없다. 프로파일 JSON만 늘어난다.

남은 질문은 "그 규칙을 누가 만드나"인데, 그건 L9의 학습 함수다. 그 전에 L7에서 규칙을 실제로 써서 문서를 자르는 걸 먼저 본다.

---

## L6 — 문맥 신호 — 만들었지만 결국 안 쓴 것

이 레이어는 결말부터 말하는 게 낫다. **여기서 만드는 신호는 최종 규칙에 하나도 들어가지 않았다.** 그런데도 남겨둔 이유와, 왜 안 쓰게 됐는지가 이 프로젝트에서 배울 게 많은 대목이다.

### 처음 세운 가설

[F2](../01-findings.md#f2)·[F11](../01-findings.md#f11)·[F12](../01-findings.md#f12)가 말하는 문제는 이거다. "RISK FACTORS"라는 똑같은 글자가 한 문서에 여러 번 나온다. 목차에 한 번, 상호 참조 색인에 한 번, 진짜 본문 헤딩으로 한 번. 게다가 **스타일까지 같을 수 있다.**

스타일로 못 가른다면 문맥으로 갈라야 한다. 예를 들어 "헤딩 뒤에는 본문이 길게 이어지지만, 목차 항목 뒤에는 다음 목차 항목이 나온다"는 신호. 실제로 INTC FY2019의 세 "RISK FACTORS"를 재보면 뒤따르는 본문이 각각 1,851자 / 41자 / 90자다. 확실히 갈린다.

### 그런데 실측해보니 필요가 없었다

최종 프로파일 4개 중 문맥 조건을 가진 것이 **하나도 없다**([F13](../01-findings.md#f13)).

```
NVDA / AMD / MU   {font_weight, font_size, in_table}   ← three style keys only
INTC              (no rules at all — xref)
```

`number` 타입에서는 **번호 자체가 워낙 강한 앵커**였기 때문이다. "Item 1A"가 문서에 8번 나와도, 7번은 문장 중간의 상호 참조라 `ITEM_RE`의 `^` 앵커에서 탈락하고, 목차는 표 안이라 `in_table: false`에서 탈락한다. 남는 게 정확히 하나다.

문맥 신호는 그래서 **규칙 어휘가 아니라 학습 시점의 후보 필터**로만 남았다.

> ⚠ 더 솔직히 말하면 **`body_after`는 현재 어디에서도 호출되지 않는다.** `sec_canonical`·`custom_title` 학습 함수를 위한 것인데 그 둘이 미구현이다 ([02-spec.md](../02-spec.md)의 "설계됨 · 미구현"). 정의만 남아 있다.

### 구현 — 본문 시작점 — 측정이 기각한 가설

#### 대상 파일: `app/ingestion/parser.py`

<!-- src: app/ingestion/parser.py::body_after -->
```python
def body_after(blocks: list[Tag], idx: int, span: int = 8) -> int:
    """Measure following body text to filter learning candidates.

    Measured for the three INTC FY2019 "RISK FACTORS" occurrences: 1,851 after
    the heading, 41 after the TOC entry, and 90 after the index entry.
    """
    return sum(
        len(blocks[j].get_text(" ", strip=True))
        for j in range(idx + 1, min(idx + 1 + span, len(blocks)))
    )
```

반면 "이 텍스트가 문서에 몇 번 나오나"라는 신호는 실제로 쓴다. 다만 함수로 빼지 않고 [L8](05-segment-xref.md#l8--세그멘테이션-b--문서가-스스로-들고-있는-답을-읽는다)의 본문 조립에서 직접 쓴다. 페이지마다 반복되는 "Table of Contents" 머리글을 걷어내는 용도인데, 이 문자열이 한 문서에 113번 나온다.

```python
freq = Counter(b.get_text(" ", strip=True) for b in blocks)
```

한 줄이지만 성능 관점에서 중요한 선택이 들어 있다. 블록마다 "이 텍스트가 문서에 몇 번 나오나"를 그때그때 세면 전체가 O(n²)이 된다. 블록이 2,400개면 570만 번 비교다. `Counter`를 한 번 만들어두고 조회만 하면 O(n)이다.

같은 이유로 `texts` 리스트도 미리 만든다. `get_text()`는 트리를 다시 걷는 비싼 호출이라 루프 안에서 반복하면 안 된다.

### 안 쓸 확장점을 미리 넣은 대가

이 레이어에서 가장 값진 교훈은 실패담이다.

초기 설계는 `min_body_after`, `max_repeat`, `next_is_table`, `items` 네 조건을 규칙 어휘에 넣었다. "나중에 필요할 것 같아서"였다. 결과적으로 최종 프로파일에서 사용률은 **0%**였다.

문제는 안 쓴 게 아니라 **비용을 냈다는 것**이다. `matches_rule`이 블록을 평가할 때마다 `body_after`를 계산했고, 그게 약 19,000번의 `get_text()` 호출로 이어졌다 ([B13](../04-bugs.md#b13)). 전부 헛일이었다.

**"나중에 필요할지도"로 넣은 확장점은 비용을 즉시 발생시키고 이득은 영원히 안 줄 수 있다.** 필요해질 때 넣는 편이 대체로 싸다.

**밟은 함정** — [B13](../04-bugs.md#b13) 헛계산 19,000회

## 여기까지 왔을 때 설명할 수 있어야 하는 것

- **규칙을 코드가 아니라 데이터로 두면 무엇이 가능해지는가?**
  - **답:** 회사와 연도별 차이를 평가기 분기 없이 학습해 프로파일로 저장할 수 있다. 하나의 검증된 계약이 모든 프로파일을 해석한다.
- **수치 규칙을 "정확히 일치"가 아니라 "이상"으로 정한 이유는 무엇인가?**
  - **답:** 학습은 관측된 굵기나 크기의 최솟값을 택해 모든 실제 헤딩을 통과시키는 가장 느슨한 문턱을 만든다. 정확히 일치시키면 더 강한 서식을 쓴 정상 헤딩을 거부한다.
- **`in_table`만 비대칭으로 처리하는 이유는 무엇인가?**
  - **답:** `false`는 표 안 목차를 제외해야 하지만, `true`는 위치 제약 없음이어야 AMD FY2019의 표 안 헤딩에서 배운 규칙을 이후 표 밖 연도에도 쓸 수 있다. 측정 결과 이 방향의 제약만 필요했다.
- **규약을 문장으로 먼저 못 박지 않으면 누가 무엇을 해야 하는가?**
  - **답:** 프로파일 작성자마다 평가기 소스를 열어 생략·최솟값·정확 일치·`in_table`의 의미를 역으로 추론해야 한다. 규칙이 제각각 되기 쉬우므로 문장으로 적은 규약도 인터페이스의 일부다.
- **L6을 최종 규칙에서 뺐는데도 문서에 남긴 이유는 무엇인가?**
  - **답:** 문맥 신호가 필요 없었다는 측정 결과와 추측으로 넣은 확장점의 비용을 기록하기 위해서다. 이 근거가 남아 있으면 같은 비싼 미사용 규칙을 다시 도입하는 일을 막을 수 있다.

---

[← 이전: 블록과 속성](02-blocks-props.md) · [모듈 개요](../03-build.md) · [다음: 헤딩 세그멘테이션 →](04-segment-heading.md)
