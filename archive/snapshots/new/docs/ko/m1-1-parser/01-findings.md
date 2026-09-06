# M1.1 실측

> 이 문서가 **실측의 유일한 원천**이다. 나머지 문서는 전부 `[F9](01-findings.md#f9)`처럼 여기를 링크만 하고 내용을 다시 풀어 쓰지 않는다.
>
> 코퍼스: NVDA · AMD · INTC · MU × 5년 = 20파일 (`data/corpus/manifest.json`)

설계 결정에 "그래 보인다"가 하나도 없다. 아래는 전부 이 코퍼스에서 직접 측정한 사실이고, [02-spec.md](02-spec.md)의 모든 선택이 여기서 나왔다.

**재현 가능성 표기** — 각 항목의 숫자가 지금도 나오는지 표시했다.

| 표기 | 뜻 |
|---|---|
| ✅ | 이 문서를 쓰면서 재측정해 일치 확인 |
| 🔄 | 수치가 갱신됨 (원래 기록과 다름 — 갱신값을 적었다) |
| 📌 | 테스트로 고정됨 (`tests/`에서 회귀 감시 중) |

---

## 한눈에

| # | 사실 | 결정한 것 | 레이어 |
|---|---|---|---|
| [F1](#f1) | 시맨틱 HTML이 없다 | 스타일 규칙으로 헤딩 판별 | [L4·L5](03-build.md) |
| [F2](#f2) | "Item 1A" 텍스트는 여러 번 나온다 | `^` 앵커 + 스타일 결합 | [L7](03-build.md) |
| [F3](#f3) | 회사 안에서 레이아웃이 일관된다 | 회사 단위 프로파일 | [L11](03-build.md) |
| [F4](#f4) | 같은 회사도 연도가 바뀌면 깨진다 | 연도별 프로파일 + 재학습 | [L11·L13](03-build.md) |
| [F5](#f5) | Intel은 본문에 Item 헤딩이 없다 | **전략 자체를 바꾼다** (`xref`) | [L8·L9](03-build.md) |
| [F6](#f6) | SEC가 Cross-Reference Index를 의무화한다 | `xref` 타입의 근거 | [L8](03-build.md) |
| [F7](#f7) | Item 하나 = 서사 섹션 여러 개 | 페이지 구간 겹침으로 배정 | [L8](03-build.md) |
| [F8](#f8) | 일부 헤딩이 이미지다 | 페이지 푸터로 경계 보정 | [L8](03-build.md) |
| [F9](#f9) | 구식 파일은 표 셀마다 `<div>` | 데이터 표 / 레이아웃 표 분리 | [L3](03-build.md) |
| [F10](#f10) | iXBRL은 벗기되 `ix:header`는 지운다 | `unwrap` 대 `decompose` | [L2](03-build.md) |
| [F11](#f11) | 진짜 헤딩은 1회, 가짜는 반복된다 | 본문 조립 시 노이즈 필터 | [L8](03-build.md) |
| [F12](#f12) | 뒤따르는 본문량이 목차와 헤딩을 가른다 | 학습 필터 (**현재 미사용**) | [L6](03-build.md) |
| [F13](#f13) | `number`엔 문맥 신호가 필요 없었다 | 규칙 어휘에서 문맥 조건 제거 | [L5·L6](03-build.md) |
| [F14](#f14) | 검증 지표 하나로는 부족하다 | 지표 4종 병행 | [05-verify.md](05-verify.md) |
| [F15](#f15) | 10-K는 최소화돼 줄 번호가 무의미하다 | 문자 오프셋 앵커 | [L2](03-build.md) |

---

## F1

### 시맨틱 HTML이 없다 ✅📌

4사 전부 `<h1>~<h6>`, `<b>`, `<strong>` 사용 **0회**. 제목은 오직 인라인 CSS로만 표현된다.

```
NVDA-2024: 0    AMD-2023: 0    INTC-2022: 0    MU-2024: 0
```

```html
<div style="font-weight:700;font-size:10pt;margin-top:12pt">Item 1. Business</div>
```

**결정** — "HTML 헤딩 태그 기준으로 자르면 되잖아"는 원천 불가능하다. 헤딩 판별을 `font-weight`·`font-size` 같은 인라인 CSS 측정 위에 세워야 한다. 그래서 [L4](03-build.md)의 `block_props`가 존재하고, 그 출력이 프로파일의 `rules`와 키 단위로 대조된다.

**고정** — `tests/ingestion/test_02_rules.py::test_inline_css_reaches_inner_spans`

---

## F2

### 같은 "Item 1A" 텍스트가 문서에 여러 번 나온다 🔄📌

NVDA-FY2024에서 "Item 1A"를 포함하는 리프 블록이 **8개**다. (원래 기록은 5개 — 블록화 방식이 바뀌며 갱신됐다. 성격은 같다.)

| 블록 | 정체 |
|---|---|
| 42 | 목차 (`Page Part I Item 1. Business 4 Item 1A. Risk Factors 13 …`) |
| 158, 159, 162 | 본문 중간 상호참조 (`…as described in Item 1A…`) |
| **215** | **진짜 헤딩** (`Item 1A. Risk Factors`) |
| 470, 515, 536 | 본문 중간 상호참조 |

**결정** — 단순 텍스트 검색은 목차·상호참조를 헤딩으로 오인한다. 두 조건을 **동시에** 걸어야 정확히 하나가 남는다:

1. 블록 **전체**가 그 텍스트여야 한다 → `ITEM_RE`의 `^` 앵커가 문장 중간 참조를 걸러낸다 2. 스타일 규칙을 만족해야 한다 → 목차는 표 안이라 `in_table: false`에서 탈락한다

**고정** — `tests/ingestion/test_03_segment.py::test_headings_are_found_by_style_plus_number` (NVDA-FY2024에 규칙을 걸면 정확히 23개)

---

## F3

### 회사 안에서는 레이아웃이 일관된다. 회사 간에는 다르다 ✅📌

| 회사 | 헤딩 스타일 | 기간 |
|---|---|---|
| NVDA | 700 / 11pt (FY2024만 10pt) | 5년 |
| AMD | 700 / 10pt | 5년 |
| MU | 700 / 14pt | 5년 |

**결정** — **회사 단위 프로파일이 성립한다.** 문서마다 규칙을 학습하는 게 아니라 회사마다 한 번 학습해 그 회사의 5년치를 지배한다. 비용이 문서 수가 아니라 (회사 × 레이아웃 변경) 수에 비례한다.

**고정** — `tests/ingestion/test_03_segment.py::test_learned_rules_match_golden`

---

## F4

### 같은 회사도 연도가 바뀌면 깨질 수 있다 ✅📌

**AMD FY2019만 헤딩이 표 안에 있다.** 다른 4년은 표 밖이다.

```
AMD-FY2019: 표 밖 굵은 Item 블록  4개  /  표 안까지 포함  21개
AMD-FY2023: 표 밖 굵은 Item 블록 23개  /  표 안까지 포함  23개
```

**결정 두 가지.**

1. **연도별 프로파일** — `profiles: {연도: {...}}`. 각 항목이 자기완결적이라 병합 규칙이 없다. 2. **검증 실패 시 재학습** — 앞 연도 규칙으로 파싱해보고 검증이 깨지면 이 문서로 다시 배운다.

그리고 `in_table`의 **비대칭**도 여기서 나왔다. `true`를 "반드시 표 안"으로 해석하면 표 밖 헤딩이 전부 탈락하므로, `true` = "제약 없음"으로 정의했다. 보기 싫지만 실측이 요구한다.

`default_year`가 **최신** 연도를 가리켜야 하는 이유이기도 하다 — 첫 부트스트랩 연도로 고정하면 AMD는 FY2019(예외)를 기본값으로 갖게 된다.

**고정** — `tests/ingestion/test_02_rules.py::test_in_table_is_asymmetric`, `tests/ingestion/test_05_profile.py::test_default_year_tracks_the_newest`

---

## F5

### Intel은 본문에 Item 헤딩이 아예 없다 🔄📌

INTC-FY2022의 리프 블록 **2,267개 중 `ITEM_RE`에 걸리는 블록이 0개**다. (원래 기록은 "2,416블록 중 1개, 그나마 문서 끝 색인표 안" — 색인표가 데이터 표로 통째로 흡수되면서 셀이 리프가 되지 않아 0이 됐다. 결론은 오히려 강해졌다.)

Intel은 2019년부터 자체 서사 구조로 재구성했다 — "Our Capital", "Other Key Information" 등.

**결정** — **스타일 규칙을 아무리 정교화해도 없는 것은 못 찾는다.** 문맥 조건 튜닝으로 씨름한 것이 헛돈 이유다. **전략 자체를 바꿔야 하는 경우가 존재한다**는 것이 이 프로젝트의 설계 분기점이고, `segmentation.type`이 데이터인 이유다.

> ⚠ 흔한 오해 — "Intel의 색인표를 목차로 걸러내서 `detect_number`가 실패한다"가 아니다. 후보가 **0개**라 `len(hits) < 5`에서 끝나고 `_looks_like_toc`까지 가지도 않는다. 목차 판정은 이 코퍼스에서 한 번도 발화하지 않는 방어 코드다.

**고정** — `tests/ingestion/test_03_segment.py::test_intel_fails_for_lack_of_candidates_not_toc_density`, `::test_toc_detector_is_a_dormant_guard`

---

## F6

### SEC는 재구성의 대가로 Cross-Reference Index를 의무화한다 ✅📌

문서가 "내 어느 페이지가 어느 Item인가"를 **스스로 표로 들고 있다**:

```
Item 1A. | Risk Factors | Pages 53 - 67
Item 7.  | Management's Discussion and Analysis…      ← 값 없음: 아래 하위행이 페이지 보유
         |   Results of operations | Pages 5-6, 19-44, 47-51
Item 11. | Executive Compensation | (b)               ← proxy 참조 각주
Item 4.  | Mine Safety Disclosures | Not applicable   ← 공시 없음
```

게다가 기업 자체 목차(제목 → 시작 페이지)도 표로 있다.

| 문서 | 색인표 엔트리 | 목차 행 |
|---|---|---|
| INTC-FY2019 | 21 | 30 |
| INTC-FY2020 | 21 | 29 |
| INTC-FY2021 | 22 | 26 |
| INTC-FY2022 | 22 | 25 |
| INTC-FY2023 | 23 | 29 |

**결정** — 둘을 **페이지로 조인**하면 LLM 없이 매핑이 완성된다. `xref` 타입의 근거다. 문서 자체의 메타데이터를 쓰는 것이라 추론이 아니라 **사실**이고, 그래서 "이 Item은 Not applicable"이라고 근거를 갖고 답할 수 있다.

**고정** — `tests/ingestion/test_06_xref.py::test_table_row_counts`

---

## F7

### Item 하나 = 서사 섹션 여러 개 ✅📌

INTC FY2022 Item 7 = Pages 5-6, 19-44, 47-51 → 서사 섹션 8개.

**결정** — 앵커 1:1 매핑이 아니라 **페이지 구간 겹침**으로 풀어야 한다. 그리고 같은 Item에 배정된 서사 섹션들을 하나의 `Section`으로 합친다(문서 순서 유지, 중복 없음).

`xref`의 검증에서 **순서·중복 검사가 무의미한 이유**이기도 하다 — Item이 문서 곳곳에 흩어져 있는 게 정상이다.

**고정** — `tests/ingestion/test_06_xref.py::test_item_7_is_joined_from_many_narrative_sections`

---

## F8

### 최근 연도 Intel의 일부 헤딩은 이미지다 ✅📌

FY2020~23의 "Segment Trends and Results", "Auditor's Reports", "Consolidated Financial Statements" 등은 본문 텍스트에 **존재하지 않는다**(목차 표 안에만).

**결정** — 텍스트 매칭으로 경계를 못 긋는 구간이 생긴다. 그러면 다음 앵커가 멀리 밀리고 그 사이 내용이 앞 섹션에 통째로 흡수된다(FY2022: 재무제표 8페이지가 Item 9B로). **페이지 번호 푸터가 유일한 결정적 경계 신호**가 된다.

단서 하나 — 다음 앵커가 **바로 다음 페이지**면 자르지 않는다. 그건 페이지 걸침이지 고아가 아니다. FY2021의 Item 7A(p49) 본문이 p50 초입까지 이어진 뒤 Risk Factors가 시작하는데, 여기를 자르면 7A의 끝문단이 1A 서두에 붙는다.

**고정** — `tests/ingestion/test_06_xref.py::test_financial_statements_land_in_item_8`

---

## F9

### 구식 파일은 표 셀마다 `<div>`를 넣는다 ✅📌

| 문서 | 표 개수 | 내부에 `div`/`p`가 있는 표 |
|---|---|---|
| NVDA-FY2020 | 158 | **158 (전부)** |
| AMD-FY2019 | 105 | **105 (전부)** |
| INTC-FY2019 | 492 | **492 (전부)** |
| NVDA-FY2024 (대조군) | 66 | 18 |

**결정** — "내부 블록 없는 요소만 리프" 규칙으로는 이 표들이 리프가 아니게 되어 셀 단위 문단으로 부서지고 **재무제표 구조가 통째로 사라진다.**

그렇다고 표를 무조건 통짜로 삼키면 반대편이 깨진다 — Intel은 페이지 전체를 레이아웃 표로 감싸서 헤딩이 표 안에 있다. 삼키면 헤딩을 잃는다.

**한쪽 규칙만으로는 반드시 한쪽이 깨진다.** 그래서 표를 두 종류로 가른다:

| 표 종류 | 판별 | 처리 |
|---|---|---|
| 데이터 표 | 숫자 셀 밀도 높음 **+ 장문 셀 없음** | 표 자체가 블록 하나. 구조 보존 |
| 레이아웃 표 | 장문 셀(`LAYOUT_CELL_CHARS`(300자)↑) 존재 | 내부 요소가 블록. 그 안에 본문·헤딩이 있다 |

장문 셀 조건이 **먼저** 와야 한다. 숫자 밀도만 보면 Intel의 인포그래픽 표가 걸린다.

**고정** — `tests/ingestion/test_01_blocks.py::test_no_document_loses_its_tables`

---

## F10

### iXBRL 태그는 벗겨야지 지우면 안 된다 — 단 `ix:header`는 예외 ✅📌

`ix:nonFraction`이 재무 수치를 감싸므로 삭제하면 숫자가 통째로 사라진다:

```
<div>매출 <ix:nonFraction>26,974</ix:nonFraction> 백만</div>

decompose() → <div>매출  백만</div>       ← 숫자 증발
unwrap()    → <div>매출 26,974 백만</div>  ← 정상
```

**그러나 `ix:header`만은 통째로 버려야 한다.** iXBRL 규격상 렌더링되지 않는 기계용 영역이고, 안에 XBRL 컨텍스트 정의가 들어 있다:

| 문서 | `ix:header` 텍스트 | `xbrli:context` | `xbrldi:explicitMember` |
|---|---|---|---|
| MU-FY2024 | **34,148자** | 421 | 640 |
| INTC-FY2019 | **59,005자** | 649 | 1,116 |

`xbrli:*` / `xbrldi:*`는 `ix:` 접두어가 **아니라서** 래퍼 제거 대상이 아니다. 그래서 부모만 벗기면 자식들이 살아남아 본문 첫 블록에 수만 자짜리 쓰레기로 뭉친다.

**순서가 중요하다** — `ix:header`를 먼저 `decompose()`하고 나머지를 `unwrap()`해야 한다.

> 이 버그는 Item 개수·순서·중복 검증을 **전부 통과했다.** 커버리지를 재고 나서야 드러났다. [F14](#f14)가 필요한 이유의 실례다.

**고정** — `tests/ingestion/test_01_blocks.py::test_ix_header_is_dropped_not_unwrapped`, `::test_ixbrl_numbers_survive`

---

## F11

### 진짜 헤딩은 문서에 한 번, 가짜는 반복된다 ✅📌

INTC-FY2022의 반복 텍스트:

```
 113회  'Table of Contents'                            ← 페이지 헤더
  36회  'Notes to Consolidated Financial Statements'
  33회  'MD&A'                                         ← 페이지 헤더
  25회  '■'
  21회  'Other Key Information'
   1회  "Management's Discussion and Analysis"         ← ★진짜 헤딩
```

**결정** — 두 군데에 쓴다.

1. **본문 조립 시 노이즈 제거** — 짧고(`PAGE_HEADER_MAX_CHARS`(60자) 미만) 자주 나오는(`PAGE_HEADER_MIN_REPEATS`(10회) 이상) 텍스트는 걷어낸다. 안 하면 청크가 "Table of Contents"로 오염된다. 2. 제목 기반 타입의 **학습 필터** (→ [F12](#f12)와 같은 용도, 현재 미사용)

**규칙 조건으로는 쓰지 않는다** — [F13](#f13) 참조.

**고정** — `tests/ingestion/test_06_xref.py::test_page_footers_and_repeated_headers_are_stripped`

---

## F12

### 뒤따르는 본문 분량이 목차와 헤딩을 가른다 🔄

원래 기록: INTC-FY2019에서 "RISK FACTORS"가 3회 출현하고 뒤따르는 본문이 진짜 헤딩 1,851자 / 목차 41자 / 색인 90자.

재측정하면 블록 텍스트가 정확히 "risk factors"인 리프는 **1개**(블록 2583, 뒤 8블록 2,155자)뿐이다. 블록화가 바뀌며 나머지 둘이 다른 형태로 흡수됐다. **성격은 유효하지만 원래 수치는 재현되지 않는다.**

**결정** — 이 관찰이 `body_after()`를 낳았다. 다만:

> ⚠ **`body_after`는 현재 어디에서도 호출되지 않는다.** `sec_canonical`·`custom_title`의 **학습** 함수를 위한 것인데 그 둘이 아직 구현되지 않았다([02-spec.md](02-spec.md)의 "설계됨 · 미구현" 참조). 지금은 정의만 있는 상태다.

---

## F13

### 그런데 `number` 타입에는 문맥 신호가 아예 필요 없었다 ✅📌

최종 프로파일 4개 중 문맥 조건을 가진 것이 **0개**다:

```
NVDA / AMD / MU   {font_weight, font_size, in_table}   ← 스타일 3개뿐
INTC              (규칙 자체 없음 — xref)
```

번호가 워낙 강한 앵커라서 `^Item N` + 굵기 + 표 밖만으로 정확히 하나가 남는다([F2](#f2)).

**결정** — **규칙 어휘에서 문맥 조건을 전부 뺐다.** 이전 설계는 `min_body_after`, `max_repeat`, `next_is_table`, `items` 네 조건을 넣었는데 실제 사용률이 0이었다. 그런데도 `matches_rule`이 매 블록마다 `body_after`를 계산했다 — INTC 2,400블록 × 뒤 8블록 = 약 19,000번의 `get_text()`가 전부 헛일이었다.

**규칙 어휘는 실제로 쓰이는 것만 담는다.** 나중에 스타일만으로 안 되는 회사가 나오면 그때 추가한다.

**고정** — `tests/ingestion/test_03_segment.py::test_learned_rules_match_golden`

---

## F14

### 검증 지표 하나로는 부족하다. 넷이 서로 다른 걸 잡는다 ✅📌

| 지표 | 잡는 것 | **못** 잡는 것 |
|---|---|---|
| 커버리지 (섹션합/전체) | 통째로 버려진 텍스트 | **헤딩 누락** — 앞 섹션이 흡수해 총량이 안 변한다 |
| SEC Item 집합 대조 | 헤딩 누락·오탐 | 섹션 내부 경계 미세 오차 |
| 연도 간 크기 일관성 | 특정 해만 튀는 경계 사고 | 모든 해가 같이 틀린 경우 |
| **원본 위치 대조** | 헤딩 위치가 실제로 거기 있나 | 자동화 안 되면 표본만 본다 |

실측 사례가 각각 있다. 커버리지는 `ix:header` 유입([F10](#f10))을 잡았는데 — 그때 Item 개수·순서·중복은 **전부 완벽했다.** 반대로 헤딩을 하나 놓치면 그 내용이 앞 섹션에 흡수돼 커버리지는 그대로다:

```
정상:    [Item 7 본문 30k][Item 7A 본문 3k]   → 커버 96%
7A 놓침: [Item 7 본문 33k          ........]  → 커버 96%   ← 똑같다
```

**커버리지 100%는 목표가 아니다.** 100%면 표지·목차·서명까지 어느 Item에 들어갔다는 뜻인데, SEC 기준으로 그것들은 어느 Item에도 속하지 않는다. 정상 상한이 96~98%다.

그리고 `expected_items`가 파서 **자신의 측정**에서 나오므로 부트스트랩 시 개수 검증은 순환 논리다. **Item 집합 대조는 외부 기준(SEC가 정한 Item 목록)과 맞추므로 순환하지 않는다.**

**고정** — [05-verify.md](05-verify.md)의 지표 4종. `tests/ingestion/test_07_coverage.py`(상한·하한 양쪽), `tests/ingestion/test_08_items.py`

---

## F15

### 10-K는 최소화돼 있어 "줄 번호"가 무의미하다 ✅📌

실측: 2MB 파일이 **5줄**이다.

```
줄 시작 오프셋: [0, 39, 931, 932, 933]
sourceline=5  sourcepos=197,074  →  절대 198,007
raw[198007:198030] = 'Item 1. Business <span style="color:#76b900;'
```

그래서 위치 앵커는 줄이 아니라 **문자 오프셋**이어야 한다.

| 파서 | 20개 총 파싱 | 블록 텍스트 | `sourcepos` |
|---|---|---|---|
| `lxml` | 17.5초 | 기준 | **없음** |
| `html.parser` (`store_line_numbers=True`) | 19.1초 | **20/20 완전 동일** | 전부 채워짐 |

**결정** — +1.6초로 **검증 가능성**을 산다. 위치가 없으면 "Item을 찾았다"를 검증할 방법이 없고 개수·크기 같은 간접 지표로 밀리게 된다.

20개 전부 블록 텍스트가 한 글자도 다르지 않다는 걸 확인하고 바꿨다 — 파서 교체는 트리 구조를 바꿀 수 있어서 **등가성 확인이 필수**다.

**고정** — `tests/ingestion/test_08_items.py::test_sections_carry_their_position`, [최종확인④](05-verify.md)
