# M1.1 버그

> 파싱을 완성하기까지 실제로 밟은 함정들. **증상 → 원인 → 수정 → 이제 무엇이 막나** 4단으로 적었다.
>
> 마지막 칸이 이 문서의 값어치다. 고친 것을 적어두기만 하면 다시 밟는다. 각 항목이 어느 테스트로 고정됐는지가 붙어 있어야 이력이 회귀 방어가 된다.

이 프로젝트에서 가장 오래 걸린 건 파서를 짜는 게 아니라 **틀렸다는 걸 알아채는 것**이었다. 아래 18건 중 절반 이상이 "실행은 성공했는데 결과가 틀린" 종류다 — [F14](01-findings.md#f14)가 왜 필요한지가 여기서 드러난다.

---

## 한눈에

| ID | 증상 | 원인 | **어떻게 발견** | 레이어 |
|---|---|---|---|---|
| [B01](#b01) | Item 16이 "Not applicable"인데 본문 있음 | 표 끝 "Signatures\|Page 125" 흡수 | 내용 검수 | L8 |
| [B02](#b02) | "Form 10-K Summary"가 p10으로 | 2셀 행에서 제목을 값으로 읽음 | 내용 검수 | L8 |
| [B03](#b03) | FY2019·2020 Item 7 실종 | 하위행 참조기호가 상위 상태 오염 | 내용 검수 | L8 |
| [B04](#b04) | 표 0개 (3파일) | 셀마다 `<div>` → 표가 리프 아님 | `--blocks` 표블록 0 | L3 |
| [B05](#b05) | INTC-FY2020 붕괴 | 인포그래픽 표를 데이터 표로 오인 | 섹션 크기 | L3 |
| [B06](#b06) | 재무제표 8p가 Item 9B에 흡수 | 헤딩이 이미지 | 내용 검수 | L8 |
| [B07](#b07) | 7A 끝문단이 1A 서두에 | 페이지 걸침을 고아로 오판 | 경계 대조 | L8 |
| [B08](#b08) | Item 5/10 배정 오류 | 동점 규칙 부재 | 내용 검수 | L8 |
| [B09](#b09) | **커버리지 80%대** | `ix:header` 래퍼 제거 → XBRL 유입 | **커버리지** | L2 |
| [B10](#b10) | 섹션 전원 blocks=2 | 목차 표 제목 셀을 본문 헤딩으로 | 섹션 크기 | L8 |
| [B11](#b11) | "FORM 10-K"→16, "Exhibit"→15 | 느슨한 매칭에 하한이 없음 | 오탐 | L7 |
| [B12](#b12) | `in_table: true`가 "1 이상"으로 | `bool`이 `int`의 서브클래스 | 히트 수 폭증 | L5 |
| [B13](#b13) | 헛계산 19,000회 | 안 쓰는 문맥 조건을 매 블록 평가 | 프로파일링 | L6 |
| [B14](#b14) | 같은 Item 중복 생성 | `custom_title` 부분 일치 | 중복 검증 | L7 |
| [B15](#b15) | "Pages 1 4, 67" 오독 | iXBRL이 숫자 사이 공백 삽입 | 색인표 검수 | L8 |
| [B16](#b16) | 표 안 전환 시 목차 통과 우려 | 밀집도 판정 부재 | 방어적 추가 | L9 |
| [B17](#b17) | `source_pos`가 전부 `None` | `lxml`이 위치를 안 채움 | 위치 대조 | L2 |
| [B18](#b18) | 필드 추가마다 호출부 깨짐 | 4-튜플 반환 | 리팩터링 | L13 |

**발견 경로별 분류** — 어느 지표가 실제로 일을 했는지:

| 발견 경로 | 건수 | 잡은 것 |
|---|---|---|
| 내용 검수 (Item별 본문량·서두 신호어) | 6 | 배정·경계 오류 |
| 섹션 크기 이상 | 2 | 구조 붕괴 |
| **커버리지** | 1 | **다른 셋이 전부 놓친 것** (B09) |
| 그 외 (단위 확인·프로파일링·리팩터링) | 9 | |

---

## L2 — 정규화

### B09

#### 커버리지가 80%대로 떨어졌다

**증상** — Item 개수·순서·중복 검증이 **전부 통과**하는데 커버리지만 80%대였다. 구조는 완벽한데 분모가 부풀어 있었다.

**원인** — `ix:*`를 전부 `unwrap()`한 것. `ix:header`는 iXBRL 규격상 렌더링되지 않는 기계용 영역인데, 그 안의 `xbrli:*`/`xbrldi:*` 자식들은 `ix:` 접두어가 아니라서 래퍼 제거 대상이 아니다. 부모만 벗기니 자식이 살아남아 본문 첫 블록에 뭉쳤다 — MU-FY2024 34,148자, INTC-FY2019 59,005자. ([F10](01-findings.md#f10))

**수정** — `ix:header`만 먼저 `decompose()`하고, 나머지 `ix:*`를 `unwrap()`한다. **순서가 중요하다.**

```python
for tag in soup.find_all("ix:header"):
    tag.decompose()          # Remove non-rendered machine-only regions entirely
for tag in soup.find_all(lambda t: bool(t.name and t.name.startswith("ix:"))):
    tag.unwrap()             # Remove other tags but preserve their text, including numbers
```

**이제 무엇이 막나** — `tests/ingestion/test_01_blocks.py::test_ix_header_is_dropped_not_unwrapped`가 트리에 `ix:header`가 남았는지와 첫 5블록에 `xbrli`/`explicitMember`가 있는지를 본다. 커버리지 상·하한(`test_07_coverage.py`)이 이중으로 감시한다.

> **이 건이 [F14](01-findings.md#f14)를 낳았다.** 지표 하나만 봤으면 영영 못 잡았다.

---

### B17

#### `source_pos`가 전부 `None`이었다

**증상** — 섹션의 위치 필드가 채워지지 않아 "Item 1A를 찾았다"를 원본과 대조할 수 없었다. 개수·크기 같은 간접 지표로만 검증하게 됐다.

**원인** — `lxml` 파서를 쓰고 있었다. 빠르지만 `sourceline`/`sourcepos`를 아예 안 채운다. 그리고 10-K는 최소화돼 있어(2MB 파일이 5줄) 줄 번호 자체가 무의미하다. ([F15](01-findings.md#f15))

**수정** — `html.parser` + `store_line_numbers=True`로 교체. `sourcepos`는 줄 안에서의 위치라 줄 시작 오프셋을 더해야 절대 위치가 된다.

교체 전에 **등가성을 확인했다** — 20개 파일 블록 텍스트가 한 글자도 다르지 않았다. 파서 교체는 트리 구조를 바꿀 수 있어서 이 확인이 필수다. 비용은 +1.6초.

**이제 무엇이 막나** — `tests/ingestion/test_08_items.py::test_sections_carry_their_position`이 모든 섹션의 `block_index`/`source_pos`/`block_range`가 채워졌는지 본다. `tests/ingestion/golden.py`의 `NVDA_FY2024_OFFSETS`가 실제 오프셋 4개를 고정한다.

---

## L3 — 블록화

### B04

#### 표가 0개로 나왔다 (3파일)

**증상** — NVDA-FY2020, AMD-FY2019, INTC-FY2019에서 표블록이 **0개**. 재무제표가 셀 단위 문단으로 흩어져 구조가 통째로 사라졌다.

**원인** — "내부에 블록 없는 요소 = 리프"라는 순진한 정의:

```python
# This alone breaks financial statements
[el for el in soup.find_all(["div","p","table"]) if el.find(["div","p","table"]) is None]
```

구식 파일은 표 셀마다 `<div>`를 넣는다. 그러면 표가 리프가 아니게 되고 셀 하나하나가 문단이 된다. 세 파일 모두 **표의 100%**가 이 형태였다(158/158, 105/105, 492/492). ([F9](01-findings.md#f9))

**수정** — 표를 데이터 표와 레이아웃 표로 가른다. 데이터 표는 통짜 블록으로 삼키고, 레이아웃 표는 내부 요소를 블록으로 낸다. 구식 리프 표(`el.find([...]) is None`)도 통짜다.

**이제 무엇이 막나** — `tests/ingestion/test_01_blocks.py::test_no_document_loses_its_tables`가 20문서 각각에 대해 표블록 > 0을 단언한다. `test_block_counts`가 정확한 개수까지 고정한다.

---

### B05

#### INTC-FY2020이 통째로 붕괴했다

**증상** — 섹션이 잡히긴 하는데 본문이 거의 비었다.

**원인** — [B04](#b04)를 고치면서 "숫자 셀 밀도가 높으면 데이터 표"로만 판별했다. Intel의 인포그래픽 표("Our Capital" 같은 것)는 숫자가 많지만 그 안에 문단과 헤딩이 들어 있다. 통짜로 삼키니 그 안의 헤딩이 전부 사라졌다.

**B04와 B05는 정반대 방향의 실패다.** 한쪽 규칙만으로는 반드시 한쪽이 깨진다.

**수정** — **장문 셀 조건을 숫자 밀도보다 먼저** 둔다. `LAYOUT_CELL_CHARS`(300자)가 넘는 셀이 하나라도 있으면 레이아웃 표다. 부정 조건을 앞에 두어 조기 탈락시키는 게 순서상 맞다.

```python
if any(len(t) > 300 for t in texts):      # Long cells indicate layout tables; check this first
    return False
numeric = sum(1 for t in texts if t and len(t) < 30 and re.search(r"\d", t))
return numeric >= max(4, len(cells) // 4)
```

**이제 무엇이 막나** — `tests/ingestion/test_01_blocks.py::test_block_counts`가 INTC-FY2020의 (2230, 133, 337)을 고정한다. 표를 과하게 삼키면 블록 수가 줄어 즉시 어긋난다.

---

## L5 — 규칙 평가기

### B12

#### `in_table: true`가 "1 이상"으로 해석됐다

**증상** — 헤딩 히트가 수십~수백 개로 폭증했다.

**원인** — 파이썬에서 `bool`은 `int`의 서브클래스다. **`isinstance(True, int)`가 `True`다.** 수치 검사가 불리언 검사보다 앞에 있으면:

- `in_table: True` → "1 이상" → 거의 모두 통과
- `in_table: False` → "0 이상" → **항상 통과**

**수정** — `isinstance(expected, bool)` 검사를 수치 검사보다 **앞에** 둔다.

```python
elif isinstance(expected, bool) or isinstance(actual, bool):
    if actual != expected:
        return False
elif isinstance(expected, int | float):     # Check bool first
    if actual < expected:
        return False
```

**이제 무엇이 막나** — `tests/ingestion/test_02_rules.py::test_bool_is_checked_before_numeric`. `font_weight: True`를 요구했을 때 수치 규약이면 통과(700 ≥ 1)하고 불리언 규약이면 탈락(700 ≠ True)한다는 차이로 순서를 직접 검증한다.

> 이 함정은 파이썬에서 실제로 밟기 쉽다. 규칙 값이 JSON에서 오면 `true`가 자연스럽게 `True`가 되므로 더 그렇다.

---

## L6 — 문맥 신호

### B13

#### 쓰지도 않는 문맥 조건을 매 블록 계산했다

**증상** — 파싱이 느렸다. 기능적 오류는 없었다.

**원인** — 규칙 어휘에 `min_body_after`, `max_repeat`, `next_is_table`, `items` 네 조건을 넣어뒀는데 **실제 프로파일에서 사용률이 0**이었다. 그런데도 `matches_rule`이 매 블록마다 `body_after`를 계산해서 넘기고 있었다. INTC 2,400블록 × 뒤 8블록 = 약 **19,000번의 `get_text()`**가 전부 헛일이었다. ([F13](01-findings.md#f13))

**수정** — 규칙 어휘에서 문맥 조건을 전부 뺐다. 규칙은 순수 스타일뿐이다.

**교훈** — **안 쓰는 것을 어휘에 넣지 않는다.** "나중에 필요할지도"로 넣은 확장점이 비용은 즉시 발생시키고 이득은 영원히 안 준다. 필요해지면 그때 추가한다.

**이제 무엇이 막나** — `tests/ingestion/test_03_segment.py::test_learned_rules_match_golden`이 학습된 규칙의 키가 정확히 `{font_weight, font_size, in_table}` 셋임을 고정한다.

> 관련 — `body_after()`는 지금도 정의만 남아 있고 **호출되지 않는다.** `sec_canonical`·`custom_title`의 학습 함수를 위한 것인데 그 둘이 미구현이다. [02-spec.md](02-spec.md)의 "설계됨 · 미구현" 참조.

---

## L7 — 세그멘테이션 A (헤딩 순회)

### B11

#### "FORM 10-K"가 Item 16, "Exhibit"이 15, "Reserved"가 6으로 잡혔다

**증상** — `sec_canonical` 매칭에서 엉뚱한 오탐이 쏟아졌다.

**원인** — SEC 표준 제목과의 접두 일치에 **길이 하한이 없었다.** 짧은 문자열은 우연히 겹칠 확률이 높다 — "Reserved"는 Item 6의 표준 제목 그 자체이기도 하다.

**수정** — 가드 두 개를 건다.

```python
t = _norm_title(text)
if len(t) < 8:                    # Guard 1: defer when too short
    return None
for item, canon in CANONICAL.items():
    c = _norm_title(canon)
    if t == c:
        return item
    if len(c) >= 14 and (t.startswith(c[:14]) or c.startswith(t[:14])):
        return item               # Guard 2: prefix matches require enough text
```

**교훈** — **느슨한 매칭에는 반드시 하한을 건다.** 길이 하한 `CANON_MIN_CHARS`(8자)과 접두 길이 `CANON_PREFIX_CHARS`(14자) 두 축으로 막는다.

**이제 무엇이 막나** — 직접 고정하는 테스트가 **없다.** `match_canonical`은 `find_item`의 `sec_canonical` 분기에서만 호출되는데 그 타입에 도달하는 판별 함수가 아직 없어서 이 코퍼스에서는 실행되지 않는다. `detect_sec_canonical`을 구현할 때 이 케이스들을 테스트로 먼저 박아야 한다.

---

### B14

#### 같은 Item이 중복 생성됐다

**증상** — `custom_title` 매칭에서 Item 하나가 두 번 나왔다.

**원인** — 제목 부분 일치를 썼다. "Risk Factors"가 "Risk Factors Summary" 같은 하위 소제목까지 잡았다.

**수정** — 정확 일치로 바꿨다. **매핑표가 있다는 건 정답을 안다는 뜻이므로 느슨하게 볼 이유가 없다.**

```python
low = text.strip().lower()
item = next((e["item"] for e in seg["order"] if e["title"].strip().lower() == low), None)
```

**이제 무엇이 막나** — [B11](#b11)과 같은 상태다. `custom_title` 판별이 미구현이라 이 경로가 실행되지 않는다. 다만 중복 자체는 `tests/ingestion/test_03_segment.py::test_no_duplicate_items`가 전 문서에 대해 감시한다.

---

## L8 — 세그멘테이션 B (xref 페이지 조인)

가장 많은 버그가 여기서 나왔다(9건). 알고리즘이 어려워서가 아니라 **문서가 거짓말을 하지는 않지만 애매하게 말하기 때문**이다 — 색인표의 한 칸이 무슨 뜻인지가 맥락에 달렸다.

### B01

#### "Not applicable"인 Item 16에 본문이 생겼다

**증상** — 색인표가 Item 16을 "Not applicable"이라 말하는데 파싱 결과엔 내용이 있었다.

**원인** — 색인표에서 하위 들여쓴 행을 **무조건** 상위 Item에 흡수시켰다. 표 끝의 "Signatures | Page 125"가 마지막 Item(16)에 붙었다.

**수정** — 상태 기계를 명시 변수로 뺀다. 자기 행에 값(페이지 / "Not applicable" / 참조기호)이 있으면 그 Item은 **완결**됐고 아래 행을 흡수하지 않는다.

```python
closed = True                                  # Whether the current Item received a value on its own row
for r in rows:
    if m := ITEM_CELL.match(r[0]):
        ...
        closed = bool(_spans(tail) or EMPTY_CELL.match(tail) or REF_CELL.match(tail))
    elif cur is not None and not closed and len(r) >= 2:
        tail = r[-1]                           # Only an open Item absorbs a continuation row
```

**교훈** — **파서에서 "지금 어떤 문맥인가"는 변수로 드러내는 게 거의 항상 옳다.** 암묵적으로 두면 이런 경계 사례에서 조용히 틀린다.

**이제 무엇이 막나** — `tests/ingestion/test_06_xref.py::test_open_row_absorption_stops_at_a_closed_item`

---

### B02

#### "Form 10-K Summary"가 페이지 10으로 읽혔다

**증상** — Item 16의 페이지 구간이 엉뚱하게 잡혔다.

**원인** — 2셀 행(`번호 | 제목`)에서 마지막 셀을 값으로 읽었다. 제목 "Form 10-K Summary"의 **10**이 페이지 번호로 오독됐다.

**수정** — **값 셀은 3번째 셀뿐이다.** 2셀 행에는 값이 없다.

```python
tail = r[2] if len(r) > 2 else ""       # The value cell is always the third cell
```

**이제 무엇이 막나** — `tests/ingestion/test_06_xref.py::test_value_cell_is_the_third_one`이 모든 엔트리의 페이지가 1~400 범위인지 본다. 제목에서 숫자를 긁으면 벗어난다.

---

### B03

#### FY2019·2020의 Item 7이 통째로 실종됐다

**증상** — MD&A가 결과에 아예 없었다. 문서에는 분명히 있는데.

**원인** — Item 7의 **하위행** "Off balance sheet arrangements | (a)"의 참조기호가 Item 7 **전체**를 `incorporated_by_reference`로 만들었다. 참조로 분류된 Item은 배정 후보에서 제외되므로 본문이 어디에도 안 실렸다.

**수정** — 하위행이 상태를 오염시키지 못하게 하고, **최종 판정은 페이지 구간 유무로** 한다. 구간이 있으면 본문이 실재하는 Item이다.

```python
for e in entries:
    if e.spans:
        e.status = "parsed"          # A page reference means the body exists
    elif e.status == "parsed":
        e.status = "empty_disclosure"
```

**교훈** — 여러 신호가 충돌할 때 **어느 신호가 최종 권한인지**를 정해두어야 한다. 여기서는 "페이지가 있다"가 가장 강한 증거다.

**이제 무엇이 막나** — `tests/ingestion/test_06_xref.py::test_status_is_decided_by_page_spans`가 페이지 구간이 있는데 상태가 `parsed`가 아닌 엔트리를 잡는다. `test_item_7_is_joined_from_many_narrative_sections`가 5년치 Item 7 크기를 고정한다.

---

### B06

#### 재무제표 8페이지가 Item 9B에 흡수됐다

**증상** — FY2022에서 Item 8이 얇고 Item 9B("Other Information")가 비정상적으로 두꺼웠다.

**원인** — Intel의 "Consolidated Financial Statements" 헤딩이 **이미지**라 본문 텍스트에 없다([F8](01-findings.md#f8)). 앵커를 못 찾으니 다음 앵커까지의 구간이 앞 섹션에 통째로 붙었다.

**수정** — 본문의 페이지 번호 푸터로 (블록 → 페이지) 지도를 만들고, 이 섹션 Item의 페이지 구간이 끝나는 지점에서 자른다. 잘려나간 블록들은 **그 페이지를 소유한 Item에게 돌려준다**(FY2022: p72~80 → Item 8).

푸터 지도의 잡음 필터도 실측에서 나왔다:
- 증가폭 1~3만 수용 (표 안 숫자 셀은 순서가 뒤죽박죽)
- 직전 푸터와 5블록 이상 간격 (재무제표 색인의 "76 77 78…" 연속 클러스터 배제)

**이제 무엇이 막나** — `tests/ingestion/test_06_xref.py::test_financial_statements_land_in_item_8`이 연도별 Item 8 표 개수를 고정한다(FY2020~23은 52~65개).

---

### B07

#### Item 7A의 끝문단이 Item 1A 서두에 붙었다

**증상** — [B06](#b06)의 수정이 만든 **역효과**. 경계를 자르니 이번엔 정상적인 페이지 걸침까지 잘렸다.

**원인** — FY2021의 Item 7A(p49) 본문이 p50 초입까지 이어진 뒤 Risk Factors가 시작한다. "페이지 구간이 끝났으니 자른다"를 무조건 적용하면 7A의 마지막 문단이 고아로 분류돼 p50을 소유한 Item(1A)에게 넘어간다.

**수정** — **다음 앵커가 한 페이지 이상 떨어졌을 때만 자른다.** 바로 다음 페이지에서 시작하면 그 사이는 페이지 걸침이지 고아가 아니다.

```python
if clamp is not None and bi < clamp + 1 < end and next_page > hi + 1:
```

그리고 잘라낸 구간이 3블록 미만이면 버린다 — 잔부스러기를 옮겨봐야 노이즈다.

**교훈** — **수정이 만든 새 실패를 반드시 반대 방향으로 확인한다.** B06만 보고 멈췄으면 B07이 남았다.

**이제 무엇이 막나** — `tests/ingestion/test_06_xref.py::test_item_7_is_joined_from_many_narrative_sections`와 커버리지 하한이 함께 감시한다. 잘못 자르면 총량이 유지되므로 커버리지로는 안 잡히고, Item별 크기 골든값으로 잡힌다.

---

### B08

#### Item 5와 10의 배정이 틀렸다

**증상** — 서사 섹션이 엉뚱한 Item에 들어갔다.

**원인** — 한 페이지를 여러 Item이 덮을 때 **동점 규칙이 없었다.**

**수정** — 우선순위를 튜플로 표현한다.

```python
cands.append((-overlap, span[1] - span[0], len(e.item), e))
return min(cands, key=lambda c: c[:3])[3].item if cands else None
```

1. 제목 단어 겹침이 많은 쪽 (`-overlap` — 내림차순이라 부호를 뒤집는다) 2. **덮는 구간 하나**의 폭이 좁은 쪽 (Item의 총 페이지 폭이 아니다) 3. Item 번호가 짧은 쪽 (완전 동점 시 결정성 확보)

실측 근거 셋:

| 사례 | 후보 | 정답 | 결정한 축 |
|---|---|---|---|
| FY2021 "Market for Our Common Stock"@64 | Item 2(64,64 폭0) 대 Item 5(64,65 폭1) | **Item 5** | 겹침 (market/common) |
| FY2019 "Critical Accounting Estimates"@50 | Item 1A(50-60 폭10) 대 Item 7(50,50 폭0) | **Item 7** | 겹침 없음 → 폭 |
| FY2022 "Notes to Consolidated Financial Statements"@81 | Item 8(2) 대 7(1) 대 15(1) | **Item 8** | 겹침 |

**요령** — 마지막 원소로 객체 자체를 넣되 `key=lambda c: c[:3]`으로 비교에서 제외한다. `XrefEntry`끼리 `<` 비교가 안 되므로 넣은 채로 비교하면 터진다.

**이제 무엇이 막나** — `tests/ingestion/test_06_xref.py::test_covering_picks_the_narrowest_span`이 `covering()`의 폭 선택을, Item별 크기 골든값이 배정 결과 전체를 고정한다.

---

### B10

#### 섹션 21개 전원이 blocks=2였다

**증상** — 구조는 완벽했다. Item 개수·순서·중복이 전부 맞았다. **내용만 없었다.**

**원인** — 목차 표의 제목 셀 30개가 전부 "본문 헤딩"으로 잡혔다. 목차는 문서 앞쪽에 몰려 있으니 각 "섹션"이 다음 목차 항목까지 2블록만 갖게 됐다.

**수정** — 목차·색인 표에 속한 블록 집합(`skip`)을 만들어 본문 위치 탐색에서 제외한다.

그리고 이 사고가 **검증 규칙 하나를 낳았다** — 구조 검사만으로는 못 잡으므로, 핵심 Item 중 2개 이상이 본문 없이 비어 있으면 실패로 친다:

```python
thin = sorted(s.item for s in sections
              if s.item in CORE_ITEMS and s.status == "parsed" and len(s.blocks) < 20)
if len(thin) >= 2:
    problems.append(f"looks like a table of contents (core Items without bodies): {thin}")
```

**교훈** — **구조가 완벽한 실패**가 존재한다. 개수·순서·중복은 전부 맞는데 내용이 없다.

**이제 무엇이 막나** — `tests/ingestion/test_04_validate.py::test_validate_catches_a_perfect_structure_with_no_content`가 "23개 섹션 전부 blocks=2"를 만들어 검증이 실제로 잡는지 확인한다. `tests/ingestion/test_08_items.py::test_core_items_have_real_content`가 실문서를 감시한다.

---

### B15

#### "Pages 1 4, 67"이 잘못 읽혔다

**증상** — 페이지 구간이 엉뚱하게 파싱됐다.

**원인** — iXBRL이 숫자 사이에 공백을 넣는다. "Pages 1 4, 67"은 실제로 **14와 67**이다. 그리고 원문 오타도 있었다 — "88 -86".

**수정** — 공백 제거 후 파싱하고, 역순 구간은 정규화한다. "88 -86" → (86, 88).

**교훈** — 실데이터에는 **기계가 만든 노이즈**(iXBRL 공백)와 **사람이 만든 노이즈**(오타)가 둘 다 있다. 둘 다 정상 경로로 흡수해야 한다.

**이제 무엇이 막나** — `tests/ingestion/test_06_xref.py::test_value_cell_is_the_third_one`의 범위 검사(1~400)가 이런 오독을 잡는다.

---

## L9 — 판별 캐스케이드

### B16

#### 표 안까지 허용하면 목차 표가 통과할 수 있다

**증상** — 실제로 터진 적은 **없다.** [F4](01-findings.md#f4)의 "표 밖에서 `OUTSIDE_TABLE_MIN_HITS`(15개) 미만이면 표 안까지 본다" 전환을 넣으면서 예상한 위험이다.

**원인(가설)** — 목차는 Item 후보를 전부 갖고 있고 스타일도 굵다. 표 안을 허용하는 순간 목차 표가 통째로 통과할 수 있다.

**수정** — 밀집도로 목차를 가른다. 목차는 항목 사이에 본문이 없어 문서의 좁은 구간에 몰려 있고, 본문 헤딩은 사이사이에 수만 자가 들어가 전체에 퍼진다.

```python
if len(idx) < 10:
    return False
return idx[-1] - idx[0] < len(blocks) * 0.15    # Treat as TOC when all entries fit within the first 15%
```

**⚠ 이 코퍼스에서는 한 번도 발화하지 않는다.** AMD-FY2019의 Item 후보 21개는 5,220블록에 걸쳐 퍼져 있어 임계(826블록)에 한참 못 미친다.

**그래서 오해가 하나 생겼었다** — "Intel이 `detect_number`에서 탈락하는 건 이 판정 덕분"이라고 적혀 있었으나 **사실이 아니다.** Intel은 후보가 0개라 `len(hits) < 5`에서 끝나고 여기까지 오지도 않는다.

**이제 무엇이 막나** — `tests/ingestion/test_03_segment.py::test_toc_detector_is_a_dormant_guard`가 20문서 전부에서 발화하지 않음을 고정하고(바뀌면 블록화나 임계가 달라진 것), `test_toc_detector_fires_on_a_dense_index`가 합성 목차로 죽은 코드가 아님을 확인한다.

---

## L13 — 오케스트레이션

### B18

#### 필드를 하나 추가할 때마다 호출부가 전부 깨졌다

**증상** — 기능 오류가 아니라 설계 마찰. `(sections, index, profile, problems)` 4-튜플로 반환하다가 `n_chars`를 추가하려니 모든 호출부를 고쳐야 했다.

**수정** — `ParsedFiling` 데이터 클래스로 바꿨다. 필드를 추가해도 기존 코드가 안 깨진다.

**교훈** — **반환값이 3개를 넘으면 데이터 클래스를 쓴다.**

그리고 `n_blocks`/`n_chars`를 결과에 담는 이유가 여기 붙는다 — 커버리지 검증의 분모가 "문서 전체 텍스트"인데 안 담아두면 CLI가 검증할 때마다 문서를 **다시 파싱**한다. 실측 20개 기준 40초 → 18초 차이였다. **측정값은 측정한 곳에서 들고 나오는 게 싸다.**

**이제 무엇이 막나** — `tests/ingestion/test_07_coverage.py::test_n_chars_is_carried_not_recomputed`가 `n_chars`/`n_blocks`가 파싱 시점 측정값과 일치하는지 본다.

---

## 알려진 한계 (버그가 아님)

문서화하고 **수용한** 것들이다. 고칠 수 있지만 비용 대비 이득이 없다고 판단했다.

| 한계 | 규모 | 왜 수용했나 |
|---|---|---|
| INTC FY2021~23의 문서 맨 앞 1~2페이지 유실 | Item 1 본문 50k 중 ~2k | 첫 앵커 이전 구간이다. 이미지 헤딩([F8](01-findings.md#f8))이라 앵커를 못 만든다 |
| 이미지 자체(차트·도식) 제외 | 정성적 | 이미지 감사 결과 인접 텍스트와 표가 수치를 담고 있음을 확인 |
| 커버리지 4~6% 미커버 | 문서당 10~25k자 | 표지·목차·서명·반복 헤더. **SEC 기준으로 어느 Item에도 안 속한다** |
| 신호어 검수 "불일치" 20건 | — | 전수 확인 결과 **전부 오탐**. 예: NVDA Item 1 서두가 "NVIDIA pioneered accelerated computing…"(정상), Item 15 서두가 재무제표 색인(정상) |

### 프로파일 수렴이 2회차가 아니라 3회차다

버그는 아니지만 직관과 다르므로 적어둔다. 같은 코퍼스를 반복해 돌리면:

```
pass1  2019:bootstrap 2020:saved     2021:relearned 2022:saved     2023:relearned
pass2  2019:saved     2020:relearned 2021:saved     2022:relearned 2023:saved
pass3  전부 saved
```

`expected_items`가 연도마다 다르고(Item 1C·9C 신설로 21→23) `default_year`는 **최신**을 가리키므로([F4](01-findings.md#f4)가 요구한다), 항목이 없는 옛 연도는 최신 연도의 기대 개수로 검증받아 반드시 실패한다. 재학습이 성공했을 때만 저장하므로 나쁜 규칙은 남지 않고, 빈 연도를 하나씩 메우며 수렴한다. **자가 복구되지만 멱등적이지는 않다.**

**고정** — `tests/ingestion/test_05_profile.py::test_profiles_converge_but_not_on_the_second_pass`
