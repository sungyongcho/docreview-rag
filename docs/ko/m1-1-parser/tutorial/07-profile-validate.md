# M1.1 튜토리얼 7 — 학습한 것을 남기고 완벽해 보이는 실패를 잡는다

L11은 학습한 규칙을 다음 실행에 넘기고, L12는 그 결과가 실제로 맞는지 검증한다.

L12가 이 모듈에서 가장 과소평가되는 층이다. **구조가 완벽한데도 틀린 파싱**이 있기 때문이다. 목차를 본문 헤딩으로 착각하면 Item 개수도, 순서도, 중복 없음도 전부 통과한다. 그 실패를 무엇으로 잡을지가 여기서 결정된다.

**선행 조건:** 튜토리얼 6의 `uv run pytest tests/ingestion/test_03_segment.py -k "detect or toc_detector" -v`가 통과해야 한다.

## 무엇을 작성하고 어디를 직접 구현할까

| 구간 | 학습 행동 | 여기서 얻어야 하는 것 |
|---|---|---|
| L11 `PROFILES`·`load_profile` | **모델 선언 작성** | 스키마 설계가 코드 복잡도를 정하는 방식 |
| L11 `save_profile` | 저장 조건을 **직접 구현** | 성공한 프로파일만 남기는 이유 |
| L12 `CORE_ITEMS`·`_validate_xref` | **설계 결정 확인** | 무엇을 필수로 볼지 정하는 근거 |
| L12 `validate` | 검증 규칙을 **직접 구현** | 구조가 완벽한 실패를 잡는 신호 |

---

## L11 — 프로파일 입출력 — 스키마가 코드 복잡도를 정한다

학습한 규칙을 회사별 JSON 파일에 저장한다. 스키마는 이렇게 생겼다.

```json
{
  "ticker": "AMD",
  "default_year": "2024",
  "profiles": {
    "2019": { "segmentation": {...}, "validation": {...} },
    "2024": { "segmentation": {...}, "validation": {...} }
  }
}
```

연도마다 **완전한** 프로파일이 들어 있다. 중복이 많아 보인다. 실제로 AMD의 2020~2024 프로파일은 거의 같은 내용이다.

### 중복을 없애려다 복잡해지는 함정

자연스러운 개선안은 `default` 프로파일을 두고 연도별로 차이만 적는 것이다. 중복이 사라지고 파일도 작아진다.

그런데 로드할 때 **병합**을 해야 한다. 그리고 병합에는 정답이 없다.

`rules`가 리스트인데 default에 2개, 연도에 1개가 있으면 어떻게 하나? 이어붙이나, 덮어쓰나? `validation.must_have`는? 리스트 병합 정책을 필드마다 정하고, 문서화하고, 테스트해야 한다.

지금 구조는 그런 게 없다. 로드가 세 줄로 끝난다. 연도 프로파일이 있으면 그걸 쓰고, 없으면 `default_year`의 것을 쓴다. 끝이다.

**스키마 설계가 코드 복잡도를 직접 결정한다.** 데이터의 중복을 없애는 대가로 코드에 정책이 들어오는 거래이고, 여기서는 중복을 택했다.

### 연도 키를 문자열로 통일하는 이유

`data["profiles"]["2024"]`처럼 연도가 문자열 키다. JSON 객체의 키는 문자열만 가능하기 때문이다.

문제는 파이썬에서 `json.dumps({2024: ...})`가 에러를 내지 않고 **조용히 `{"2024": ...}`로 바꾼다**는 점이다. 그래서 int로 저장했는데 로드하면 str이 되고, `profiles[year]`가 `KeyError`를 낸다. 저장 시점엔 멀쩡하다가 다음 실행에서 터지는 종류의 버그다.

처음부터 `str(year)`로 통일하면 이 경로가 막힌다.

### 구현 — 프로파일 저장 — 학습한 것을 다음 실행에 넘긴다

#### 대상 파일: `app/ingestion/parser.py`

<!-- src: app/ingestion/parser.py::PROFILES,load_profile -->
```python
PROFILES = Path("data/profiles")


def load_profile(ticker: str, year: int) -> dict | None:
    """Load the requested year's profile, then the default, or ``None`` to bootstrap.

    Each year is self-contained, so these three lines need no merge policy and
    never have to decide which fields should be combined.
    """
    path = PROFILES / f"{ticker}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    return data["profiles"].get(str(year)) or data["profiles"].get(data["default_year"])
```

**코드에서 꼭 볼 것**

- 폴백이 두 단계다. 요청 연도 → 기본 연도 → `None`. 마지막 `None`이 "학습부터 하라"는 신호다.
- 병합 규칙이 없는 것이 설계다. 연도별 프로파일이 자기완결적이라 어느 필드를 합칠지 결정할 일이 아예 생기지 않는다.
- 파일이 없을 때 예외가 아니라 `None`을 돌려준다. 첫 실행은 오류가 아니라 정상 경로다.

<!-- src: app/ingestion/parser.py::save_profile -->
```python
def save_profile(ticker: str, year: int, profile: dict) -> None:
    """Store one year entry and point ``default_year`` to the latest year.

    Layouts evolve forward, so a new filing is more likely to resemble a recent
    year. Freezing the first bootstrap year breaks measured AMD data because only
    FY2019 places headings inside a table (F4), making the exception the default.
    """
    PROFILES.mkdir(parents=True, exist_ok=True)
    path = PROFILES / f"{ticker}.json"
    data = (
        json.loads(path.read_text())
        if path.exists()
        else {"ticker": ticker, "default_year": str(year), "profiles": {}}
    )
    data["profiles"][str(year)] = profile
    data["default_year"] = max(data["profiles"], key=int)
    # Store years in ascending order for human readability.
    data["profiles"] = dict(sorted(data["profiles"].items(), key=lambda kv: int(kv[0])))
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
```

`data["default_year"] = max(...)` 한 줄에 판단이 하나 들어 있다. **기본값은 항상 가장 최신 연도**다.

처음엔 "처음 학습한 연도를 기본값으로"가 자연스러워 보인다. 그런데 그러면 AMD가 깨진다. AMD는 FY2019만 헤딩이 표 안에 있는데([F4](../01-findings.md#f4)), 코퍼스를 연도순으로 처리하면 FY2019가 첫 학습이 된다. **그 예외가 기본값이 되어버린다.**

최신을 기본값으로 두는 근거는 단순하다. 문서 레이아웃은 앞으로 흘러간다. 새로 들어온 제출물은 5년 전보다 작년 것을 닮았을 확률이 높다.

> **대가도 있다. 수렴이 2회차가 아니라 3회차다.** `expected_items`가 연도마다 다른데, 자기 프로파일이 없는 옛 연도는 최신 연도의 기대 개수로 검증받는다. 당연히 실패하고 재학습을 한 번 거친다. 자가 복구되지만 멱등적이지는 않다. [04-bugs.md](../04-bugs.md#프로파일-수렴이-2회차가-아니라-3회차다)에 자세히 있다.

### 확인

```bash
uv run pytest tests/ingestion/test_05_profile.py -v
```

앞쪽 7개는 코퍼스 없이 돈다. 저장/로드 왕복, 연도 키 문자열화, `default_year` 갱신, 연도별 자기완결성을 각각 본다.

| 확인 | 왜 |
|---|---|
| **연도 전부가 아니라 일부만 항목이 있다** | 앞 연도 프로파일로 검증 통과하면 새로 안 만든다 |
| **INTC는 항목이 1개** | `xref`는 `expected_items`가 없어서 5년 전부 통과 |
| `default_year`가 **최신** 연도 | 첫 연도로 고정되면 AMD가 FY2019 규칙을 기본값으로 갖는다 |

---

## L12 — 검증 — 폴백은 실패를 감지해야 성립한다

이 파서에는 자가 복구 기능이 있다. 저장된 프로파일로 파싱했는데 결과가 이상하면, 그 파일에서 규칙을 다시 학습해서 재시도한다.

그런데 이 구조에는 전제가 하나 있다. **결과가 이상한지 알 수 있어야 한다.** 틀렸는지 모르면 재학습할 기회조차 없다. 점진적 기능 저하(graceful degradation)의 핵심은 폴백 경로가 아니라 **실패 감지**다.

### 구조가 완벽한 실패

L1과 L8에서 두 번 언급한 그 사건을 이제 정면으로 다룬다.

목차를 헤딩으로 잘못 잡으면 검증 지표가 이렇게 나온다.

| 검사 | 결과 |
|---|---|
| Item 개수 | 23개 ✓ |
| Item 순서 | SEC 표준 순서 ✓ |
| 중복 | 없음 ✓ |
| 핵심 Item(1, 1A, 7, 8) | 전부 존재 ✓ |

**전부 통과한다.** 목차에는 Item이 순서대로, 중복 없이, 빠짐없이 있으니까. 구조적으로는 완벽한 파싱 결과다.

다른 건 딱 하나. 각 섹션에 **내용이 없다.** 21개 섹션 전원이 blocks=2였다 ([B10](../04-bugs.md#b10)).

그래서 구조 검사에 하나를 더 붙인다. **핵심 Item인데 블록이 너무 적은 섹션이 2개 이상이면 목차를 잡은 것으로 본다.** Item 1(사업)과 Item 7(MD&A)이 20블록도 안 된다면 정상적인 10-K가 아니다.

이 검사 하나가 없었다면 그 버그는 프로덕션까지 갔을 것이다. **"구조는 맞는데 내용이 없는" 실패를 잡는 검사는 파이프라인마다 하나쯤 필요하다.**

### 문제는 예외가 아니라 리스트로 모은다

`raise`를 쓰면 첫 문제에서 멈춘다. 그러면 "Item 개수가 틀렸다"만 보고 순서도 틀렸다는 걸 다음 실행에서 알게 된다. 디버깅이 왕복 여행이 된다.

리스트로 모으면 로그 한 줄에 전부 나온다. 그리고 호출부가 "문제 있으면 재학습"을 `if problems:` 한 줄로 판단할 수 있다.

### `xref`는 기준이 다르다

`_validate_xref`가 따로 있는 이유가 있다. Intel 문서는 Item이 문서 곳곳에 흩어져 있는 게 **정상**이다([F7](../01-findings.md#f7)). Item 7이 5페이지, 19페이지, 47페이지에 나뉘어 있으니 "순서대로인가"나 "중복인가"를 물어봐야 의미가 없다.

대신 **커버리지**를 본다. 색인표에 있는 모든 Item이 셋 중 하나로 설명되는가 — 본문이 배정됐거나, 공시 없음이거나, 외부 참조이거나. 하나라도 설명이 안 되면 파싱이 뭔가 놓친 것이다.

**같은 시스템이라도 데이터 특성이 다르면 검증 기준도 달라야 한다.** 하나의 검증 로직으로 억지로 통일하면 한쪽은 늘 헛발질한다.

### 구현 — 검증 — 구조가 완벽한 실패를 잡는다

#### 대상 파일: `app/ingestion/parser.py`

<!-- src: app/ingestion/parser.py::CORE_ITEMS,_validate_xref -->
```python
CORE_ITEMS = ("1", "1A", "7", "8")


def _validate_xref(sections: list[Section], index: list[dict], exp: dict) -> list[str]:
    """Validate xref filings with coverage rather than order and uniqueness.

    Items are legitimately scattered across the filing, so order and duplicates
    are not meaningful. Instead, require every indexed Item to be explained by
    assigned body text, an empty disclosure, or incorporation by reference.
    """
    problems: list[str] = []
    explained = {s.item for s in sections if s.item and (s.blocks or s.status != "parsed")}
    if missing := sorted({e["item"] for e in index} - explained):
        problems.append(f"unexplained items: {missing}")
    if miss := sorted(set(exp["must_have"]) - {s.item for s in sections if s.blocks}):
        problems.append(f"missing core items: {miss}")
    thin = sorted(
        s.item for s in sections if s.status == "parsed" and len(s.blocks) < XREF_THIN_BLOCKS
    )
    if index and len(thin) > len(index) * XREF_THIN_RATIO:
        problems.append(f"too many thin sections: {thin}")
    return problems
```

**코드에서 꼭 볼 것**

- xref 문서에는 순서와 중복 검사를 하지 않는다. Item이 문서 곳곳에 흩어져 있는 것이 정상이라 두 검사가 의미를 잃는다.
- 대신 **커버리지**를 본다. 색인에 있는 Item이 본문·빈 공시·참조 셋 중 하나로 설명되는가만 확인한다.
- 얇은 섹션은 개수가 아니라 **비율**로 판정한다. 색인이 크면 얇은 섹션도 비례해서 늘어나므로 고정 개수로는 문서 크기에 휘둘린다.

<!-- src: app/ingestion/parser.py::validate -->
```python
def validate(sections: list[Section], profile: dict, index: list[dict] | None = None) -> list[str]:
    """Return all parse problems; an empty list means validation succeeded.

    Collecting problems instead of raising at the first one exposes every defect.
    The caller can decide whether to relearn with one ``if problems`` check.
    """
    seg, exp = profile["segmentation"], profile["validation"]
    if seg["type"] == "xref":
        return _validate_xref(sections, index or [], exp)
    items = [s.item for s in sections if s.item]
    problems: list[str] = []

    if len(items) != exp["expected_items"]:
        problems.append(f"item count {len(items)} != expected {exp['expected_items']}")

    # Use custom_title array order when present; otherwise use canonical SEC order.
    ranking = [e["item"] for e in seg["order"]] if seg["type"] == "custom_title" else ORDER
    rank = {v: i for i, v in enumerate(ranking)}
    checked = [i for i in items if i in rank]
    if checked != sorted(checked, key=lambda i: rank[i]):
        problems.append("items are out of order")

    if dup := sorted({i for i in items if items.count(i) > 1}):
        problems.append(f"duplicates: {dup}")

    if miss := sorted(set(exp["must_have"]) - set(items)):
        problems.append(f"missing core items: {miss}")

    # Fail even with perfect structure when body content is absent, as with TOC headings.
    thin = sorted(
        s.item
        for s in sections
        if s.item in CORE_ITEMS and s.status == "parsed" and len(s.blocks) < CORE_THIN_BLOCKS
    )
    if len(thin) >= CORE_THIN_COUNT:
        problems.append(f"looks like a contents table (core items with no body): {thin}")

    return problems
```

**코드에서 꼭 볼 것**

- 예외를 던지지 않고 문제를 모아서 돌려준다. 첫 문제에서 멈추면 나머지 결함이 다음 실행까지 숨는다.
- 빈 리스트가 성공이다. 호출자는 `if problems` 한 줄로 재학습 여부를 정한다.
- `custom_title`일 때만 순서 기준을 바꾼다. 그 타입은 회사가 정한 순서가 SEC 표준 순서와 다르기 때문이다.
- 마지막 검사가 이 함수의 존재 이유다. 개수·순서·중복이 전부 통과해도 핵심 Item에 본문이 없으면 목차를 헤딩으로 착각한 것이다. **구조가 완벽한 실패**를 잡는 자리가 여기다.

### 확인

```bash
uv run pytest tests/ingestion/test_04_validate.py -v
```

**일부러 실패시켜 보는 게 핵심이다.** 정상 입력이 통과하는 것만 확인하면 검증이 실제로 일하는지 알 수 없다. `test_validate_catches_a_perfect_structure_with_no_content`가 "23개 섹션 전부 blocks=2"를 만들어 넣는다.

```bash
uv run python -c "
from app.ingestion.parser import validate, Section
secs = [Section(part='I', item=i, canonical_title='', reported_title='') for i in ('1','1A')]
prof = {'segmentation': {'type':'number'}, 'validation': {'expected_items': 23, 'must_have': ['1','1A','7','8']}}
print(validate(secs, prof))
"
```

→ `['item count 2 != expected 23', 'missing core items: ['7', '8']', 'looks like a contents table (core items with no body): ['1', '1A']']`

**밟은 함정** — [B10](../04-bugs.md#b10) 구조가 완벽한 실패

### 여기까지 온 상태

품질 게이트가 완성됐다. 개수·순서·중복·핵심 Item 누락에 더해, **구조는 완벽한데 내용이 없는 실패**까지 잡는다. `xref`는 커버리지라는 다른 기준을 쓴다.

이제 조각이 다 모였다. 남은 건 순서대로 엮는 일이다.

## 여기까지 왔을 때 설명할 수 있어야 하는 것

- **프로파일 스키마 설계가 코드 복잡도를 정한다는 말은 무슨 뜻인가?**
  - **답:** 연도별 항목이 자기완결적이면 직접 조회하고 기본 연도로 폴백하면 끝난다. 기본값과 오버라이드로 중복을 줄이면 필드마다 병합 규칙을 구현·문서화·테스트해야 하므로 복잡성이 데이터에서 코드로 옮겨간다.
- **연도별 프로파일을 병합하지 않고 독립 항목으로 두는 이유는 무엇인가?**
  - **답:** 규칙 목록과 검증 필드에는 모두에게 맞는 병합 방식이 없어 오버라이드를 합치면 애매한 정책이 생긴다. 데이터 중복을 조금 허용하면 각 프로파일이 완전해지고 로딩 결과가 결정적이 된다.
- **성공한 프로파일만 저장하는 이유는 무엇인가?**
  - **답:** 현재 이 규칙을 따르는 것은 재학습 프로파일이다. 실패한 재학습 결과는 저장하지 않으므로 이후 실행이 이미 잘못된 업데이트를 재사용하지 않는다. 부트스트랩 경로는 처음 검증하기 전에 새 프로파일을 쓰므로 예외다.
- **구조가 완벽한데도 실패인 파싱은 어떤 모습인가?**
  - **답:** 목차를 잡으면 모든 Item이 표준 순서로 나오고 중복이나 핵심 Item 누락도 없지만, 각 섹션에는 블록이 몇 개뿐이다. 핵심 Item의 본문 두께 검사가 본문 헤딩을 잡은 것이 아님을 드러낸다.
- **검증 지표를 네 종류로 나눈 이유는 무엇인가?**
  - **답:** 전체 파싱, 커버리지, SEC Item 비교, 소스 위치 검수는 각각 실행 실패, 대량 텍스트 유실, 헤딩 누락·오탐, 잘못된 원문 위치를 잡는다. 어느 한 지표도 네 속성을 모두 보장하지 못한다.

---

[← 이전: 판별과 분류](06-detect-classify.md) · [모듈 개요](../03-build.md) · [다음: 오케스트레이션과 CLI →](08-orchestration-cli.md)
