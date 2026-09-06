# M1.1 튜토리얼 6 — 어느 전략을 쓸지 문서가 정하게 한다

전략이 둘이 되었으니 고르는 코드가 필요하다. L9가 그 판별기다.

L10은 잘라 낸 섹션에 상태를 붙인다. 여기서 중요한 판단이 하나 있다. **짧은 섹션이 전부 버그는 아니다.** "Not applicable" 한 줄짜리 Item은 정상이고, 그것과 진짜 파싱 실패를 구분하지 못하면 L12의 검증이 의미를 잃는다.

**선행 조건:** 튜토리얼 5의 `uv run pytest tests/ingestion/test_06_xref.py -v`가 전부 통과해야 한다. 세그멘테이션 두 경로가 모두 있어야 판별기를 만들 수 있다.

## 무엇을 작성하고 어디를 직접 구현할까

| 구간 | 학습 행동 | 여기서 얻어야 하는 것 |
|---|---|---|
| L9 `_looks_like_toc` | 밀도 판정을 **직접 구현** | 목차와 본문 헤딩을 가르는 신호 |
| L9 `detect_number`·`detect_xref` | 판별과 학습을 **직접 구현** | 판별기가 설정 생성기를 겸하는 설계 |
| L9 `detect_segmentation`·`build_profile` | **호출 순서 검토** | 캐스케이드 순서가 결과를 바꾸는 지점 |
| L10 `classify_sections` | 상태 규칙을 **직접 구현** | 정상적으로 짧은 Item과 파싱 실패의 구분 |

---

## L9 — 판별 캐스케이드 — 이 문서엔 어느 전략이 맞나

전략이 두 개 있으니 고르는 코드가 필요하다. 그런데 여기서 이 프로젝트의 설계 하나가 드러난다. **판별 함수가 판별기이면서 동시에 설정 생성기다.**

보통은 "타입을 판별한다 → 그 타입의 설정을 만든다"를 두 단계로 나눈다. 여기서는 한 함수가 둘 다 한다. 반환값이 곧 답이다.

- `{}` → "내 타입 아님"
- 채워진 dict → "내 타입이고, 설정은 이거다"

이렇게 하면 판별에 쓴 측정값을 설정에 그대로 재활용할 수 있다. 예를 들어 `detect_number`는 헤딩 후보를 모으면서 그 폰트 굵기·크기를 이미 재고 있는데, 그 값이 바로 규칙이 된다. 판별과 학습을 분리하면 같은 측정을 두 번 하게 된다.

### 구현

#### 대상 파일: `app/ingestion/parser.py`

<!-- src: app/ingestion/parser.py::_looks_like_toc -->
```python
def _looks_like_toc(blocks: list[Tag]) -> bool:
    """Detect a TOC by densely clustered Item candidates with little body between them."""
    idx = [
        i
        for i, el in enumerate(blocks)
        if (t := el.get_text(" ", strip=True)) and len(t) < HEADING_MAX_CHARS and ITEM_RE.match(t)
    ]
    if len(idx) < TOC_MIN_ITEMS:
        return False
    return idx[-1] - idx[0] < len(blocks) * TOC_DENSITY
```

목차와 본문 헤딩을 가르는 아이디어가 재미있다. **밀도**를 본다.

목차는 항목 사이에 본문이 없으니 문서의 좁은 구간에 몰려 있다. 반면 본문 헤딩은 사이사이에 수만 자가 들어가서 문서 전체에 고르게 퍼진다. 그래서 "Item 후보들의 첫 위치와 끝 위치 차이가 문서 전체의 15% 미만이면 목차"로 판정한다.

> ⚠ 솔직하게 덧붙이면 **이 함수는 이 코퍼스에서 한 번도 발화하지 않는다.** AMD-FY2019의 Item 후보 21개는 5,220블록에 퍼져 있어 임계(826블록)에 한참 못 미친다. 그리고 흔한 오해 하나 — **"Intel이 이 판정 때문에 탈락한다"는 사실이 아니다.** Intel은 후보가 0개라 `len(hits) < 5`에서 이미 끝나고 여기까지 오지도 않는다([B16](../04-bugs.md#b16)). 코드를 읽고 "아 이래서 Intel이 걸러지는구나"라고 넘겨짚기 쉬운 자리라 명시해둔다.

<!-- src: app/ingestion/parser.py::detect_number -->
```python
def detect_number(blocks: list[Tag]) -> dict:
    """Strategy 1: detect filings with explicit ``Item 1A.`` body headings."""

    def collect(allow_table: bool) -> list[tuple[int, float]]:
        out = []
        for el in blocks:
            t = el.get_text(" ", strip=True)
            if not t or len(t) > HEADING_MAX_CHARS or not ITEM_RE.match(t):
                continue
            if not allow_table and el.find_parent("table") is not None:
                continue
            props = block_props(el)
            if props["font_weight"] < 700:  # unstyled matches are TOC entries or references
                continue
            out.append((props["font_weight"], props["font_size"]))
        return out

    outside, inside = collect(False), collect(True)
    hits, in_table = (outside, False) if len(outside) >= OUTSIDE_TABLE_MIN_HITS else (inside, True)
    # When table-contained headings are required, confirm the table is not a TOC.
    if len(hits) < NUMBER_MIN_HITS or (in_table and _looks_like_toc(blocks)):
        return {}

    # Use the loosest rule covering every observation; a mean or mode drops valid headings.
    return {
        "type": "number",
        "rules": [
            {
                "font_weight": min(w for w, _ in hits),
                "font_size": min(s for _, s in hits),
                "in_table": in_table,
            }
        ],
    }
```

**코드에서 꼭 볼 것**

- `collect`를 두 번 부르는 구조가 핵심이다. 먼저 표 밖에서 찾고, 부족하면 표 안까지 넓힌다. AMD처럼 헤딩이 표 셀 안에 있는 문서를 위한 경로다.
- `font_weight < 700`으로 거르는 이유는 굵지 않은 `Item 1A`가 대개 목차 항목이나 상호 참조이기 때문이다.
- 규칙을 `min`으로 만든다. 평균이나 최빈값을 쓰면 관측한 헤딩 중 일부가 자기 규칙에 걸러진다. **관측을 전부 통과시키는 가장 느슨한 규칙**이 목표다.
- 표 안 경로일 때만 `_looks_like_toc`를 부른다. 표 밖에서 찾았다면 목차일 가능성이 없어 검사가 낭비다.

### 표 안까지 볼지를 스스로 정한다

L5에서 미뤄뒀던 `in_table` 비대칭이 여기서 값을 정한다.

`collect()`를 두 번 호출한다. 한 번은 표 밖만, 한 번은 표 안까지 포함해서. 그리고 표 밖에서 충분히(`OUTSIDE_TABLE_MIN_HITS` 15개 이상) 나오면 표 밖 규칙을 쓰고, 부족하면 표 안까지 허용한다.

덕분에 AMD FY2019 — 유일하게 헤딩이 표 안에 있는 파일 — 이 **사람 개입 없이 자동으로** 다른 규칙을 학습한다. 예외를 코드에 하드코딩하지 않고 측정으로 처리한 사례다.

### `min()`으로 규칙을 뽑는 이유

학습 부분이 짧아서 지나치기 쉬운데, 여기 중요한 판단이 있다.

관측한 헤딩들의 폰트 굵기가 700, 700, 800이었다고 하자. 규칙을 뭐로 정해야 할까? 평균(733)이나 최빈값(700)이 떠오른다. 그런데 평균을 쓰면 **관측한 헤딩 중 일부가 자기 규칙에 탈락한다.** 700짜리가 733 문턱을 못 넘는다.

그래서 `min()`을 쓴다. 수치를 "이상"으로 해석하는 규약(L5)과 짝을 이뤄서, **관측한 것을 전부 통과시키는 가장 느슨한 규칙**이 된다.

이게 이 학습의 목표다. 정확한 분류가 아니라 **재현율 우선.** 놓친 헤딩은 섹션 하나가 통째로 사라지지만, 조금 느슨해서 딸려온 것은 L12 검증이 잡아준다.

#### 대상 파일: `app/ingestion/parser.py`

<!-- src: app/ingestion/parser.py::detect_xref -->
```python
def detect_xref(soup: BeautifulSoup, blocks: list[Tag]) -> dict:
    """Strategy 2: detect a filing that maps Items through a Cross-Reference Index.

    Call this only after strategy 1 fails. A normal 10-K TOC can resemble an index
    with ``Item 1. Business ... 3``, so first confirm that the body lacks Item
    headings. There is no payload because style rules cannot locate absent headings.
    """
    xref_tbl, toc_tbl = find_tables(soup)
    if xref_tbl is None or toc_tbl is None:
        return {}
    if len(parse_xref(xref_tbl)) < XREF_MIN_ENTRIES or len(parse_toc(toc_tbl)) < XREF_MIN_TOC_ROWS:
        return {}
    return {"type": "xref"}
```

**코드에서 꼭 볼 것**

- 반환값에 `rules`가 없다. 없는 헤딩을 스타일로 찾을 수는 없으니 규칙을 만들 대상 자체가 존재하지 않는다.
- 표 두 개를 모두 요구한다. 색인표만으로는 일반 10-K의 목차와 구분되지 않기 때문이다.
- 이 함수는 `detect_number`가 실패한 뒤에만 불린다. 순서를 바꾸면 목차를 가진 정상 10-K가 xref로 오판될 수 있다.

<!-- src: app/ingestion/parser.py::detect_segmentation -->
```python
def detect_segmentation(soup: BeautifulSoup, blocks: list[Tag]) -> dict:
    """Try measured segmentation strategies in order and accept the first match.

    Strategy 1 is cheaper and more common. Running strategy 2 first can mistake a
    normal 10-K TOC such as ``Item 1. Business ... 3`` for a cross-reference index;
    establish the absence of body Item headings first.
    """
    return detect_number(blocks) or detect_xref(soup, blocks) or {"type": "undefined"}
```

한 줄짜리 함수지만 **이 순서 자체가 정책**이다.

`detect_xref`를 앞에 두면 어떻게 될까. 일반 10-K의 목차도 `Item 1. Business … 3` 형태라서 색인표처럼 보인다. NVIDIA 문서가 xref로 판정되고, 본문에 멀쩡히 있는 헤딩을 무시한 채 목차 기반으로 엉뚱하게 잘린다.

그래서 **본문에 헤딩이 없다는 것을 먼저 확인**한 뒤에만 xref를 시도한다. 순서가 곧 "값싸고 흔한 것을 먼저, 예외는 나중에"라는 정책이다.

이런 순서 의존성은 주석을 **함수 안에** 적는 게 좋다. 읽는 사람이 순서를 확인하러 오는 곳이 여기이기 때문이다. 파일 위쪽 주석에 적어두면 아무도 안 읽는다.

<!-- src: app/ingestion/parser.py::build_profile -->
```python
def build_profile(soup: BeautifulSoup, blocks: list[Tag], doc_id: str) -> dict:
    """Measure this filing and build one parsing profile."""
    seg = detect_segmentation(soup, blocks)
    sections, _ = segment(soup, blocks, seg)
    items = [s.item for s in sections if s.item]

    # xref does not store expected_items because each year's index states them directly.
    validation: dict = {"must_have": ["1A", "7", "8"]}
    if seg["type"] not in ("xref", "undefined"):
        validation = {
            "expected_items": len(items),
            "must_have": ["1", "1A", "7", "8"],
        }
    return {
        "segmentation": seg,
        "validation": validation,
        "learned_from": doc_id,
        "learned_by": "bootstrap",
        "learned_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
```

마지막 조각은 `build_profile`이다. 판별한 전략과 검증 기준을 묶어 프로파일로 만든다.

여기 눈에 띄는 비대칭이 하나 있다. **`xref`는 `expected_items`를 저장하지 않는다.**

이유가 깔끔하다. 색인표가 연도마다 Item 개수를 직접 알려주므로 파서가 기억할 이유가 없다. 반면 `number` 타입은 "이 회사는 보통 23개"를 기억해둬야 다음 해에 20개만 잡혔을 때 이상을 감지한다.

이 차이가 실제 효과를 낸다. **INTC 프로파일이 5년치에 한 개뿐**인 이유가 이것이다. 연도마다 다를 값을 저장하지 않으니 프로파일 하나가 모든 연도에 통한다.

### 확인

```bash
uv run pytest tests/ingestion/test_03_segment.py -k "detect or toc_detector" -v
```

**밟은 함정** — [B16](../04-bugs.md#b16) 목차 밀집도 판정

---

## L10 — 상태 분류 — 짧은 섹션이 다 버그는 아니다

파싱 결과를 보면 블록이 1~2개뿐인 섹션이 나온다. 처음엔 파서가 뭔가 놓쳤다고 생각하게 된다.

실제로 원문을 열어보면 이렇게 적혀 있다.

```
Item 4. Mine Safety Disclosures
Not applicable.
```

반도체 회사에 광산 안전 공시가 있을 리 없다. 짧은 게 정상이다. 마찬가지로 Part III(Item 10~14)는 대개 이렇게 처리된다.

```
Item 11. Executive Compensation
The information required by this Item is incorporated herein by reference
to the Company's Proxy Statement...
```

임원 보수는 위임장 자료(Proxy Statement)라는 별도 문서에 있고, 10-K는 그걸 참조만 한다. 이것도 정상이다.

이 둘을 "본문 없음 = 파싱 실패"로 취급하면 L12의 검증이 계속 헛발질한다. 그래서 섹션에 **상태**를 붙인다.

- `empty_disclosure` — 공시할 게 없다고 문서가 밝힘
- `incorporated_by_reference` — 외부 문서로 위임
- `parsed` — 실제 본문 있음

### 추정한 것과 문서가 말해준 것은 다르다

`xref` 타입은 이 추정을 하지 않는다. 색인표가 상태를 **직접 알려주기** 때문이다.

같은 정보라도 이 둘은 다르다. 여기서 하는 건 본문 앞부분을 정규식으로 보고 **추정**하는 것이고, xref는 문서가 표에 명시한 것을 **읽는** 것이다. 후자는 `item_index`에 원본 기록이 남아서 나중에 근거를 댈 수 있다.

RAG 시스템을 만들 때 이 구분을 습관화하는 게 좋다. **어디까지가 문서가 말한 것이고 어디부터가 우리가 추정한 것인지**를 데이터에 남겨두면, 나중에 신뢰도를 따질 때 근거가 된다.

### 구현 — 섹션 분류 — 추정한 것과 문서가 말해준 것

#### 대상 파일: `app/ingestion/parser.py`

<!-- src: app/ingestion/parser.py::EMPTY_RE,REF_RE -->
```python
EMPTY_RE = re.compile(r"^\s*(none|not applicable|n/?a)\.?\s*$", re.I)
REF_RE = re.compile(
    r"(incorporated (herein )?by reference|is set forth in|will be (contained|included) in"
    r"|information (required by|regarding).{0,80}(proxy|incorporated|set forth))",
    re.I,
)
```

**코드에서 꼭 볼 것**

- 두 정규식이 "본문이 비어 있다"의 서로 다른 두 이유를 가른다. 앞은 정상적으로 해당 없음이고, 뒤는 다른 문서로 넘긴 경우다.
- `REF_RE`의 `.{0,80}`에 상한을 둔 이유는 무제한 매칭이 문단 전체를 삼켜 관계없는 문장까지 참조로 판정하기 때문이다.
- 둘 다 `re.I`다. 같은 문구를 문서마다 다른 대소문자로 쓴다.

<!-- src: app/ingestion/parser.py::classify_sections -->
```python
def classify_sections(sections: list[Section]) -> None:
    """Distinguish a valid short disclosure from a broken thin section.

    Short 10-K sections are usually valid:
      "None." / "Not applicable."        → empty_disclosure
      "...incorporated by reference..."  → incorporated_by_reference (for example, proxy)

    An ``xref`` index reports status directly and needs no inference. This function
    applies only to title- and number-based segmentation.
    """
    for s in sections:
        text = " ".join(b.text for b in s.blocks if b.kind == "paragraph")[
            :CLASSIFY_SCAN_CHARS
        ].strip()
        if not text:
            continue
        if EMPTY_RE.match(text):
            s.status = "empty_disclosure"
        elif len(s.blocks) <= REF_MAX_BLOCKS and REF_RE.search(text):
            s.status = "incorporated_by_reference"
```

`len(s.blocks) <= REF_MAX_BLOCKS` 조건이 왜 필요한지 짚고 가자.

"incorporated by reference"라는 표현은 본문이 긴 섹션 안에서도 나올 수 있다. Item 1 사업 설명 중간에 "자세한 내용은 Exhibit 21에 통합 참조된다" 같은 문장이 있는 식이다. 블록 수 제한이 없으면 이 섹션 전체가 `incorporated_by_reference`로 찍힌다.

그러면 **본문이 멀쩡히 있는데 없는 것처럼 보인다.** 검색에서 빠지고, 검증도 통과해버린다. 반대로 분류를 못 하면 어떻게 될까? `parsed`로 남아서 본문이 있는 것으로 취급된다. 실제로 짧으면 L12가 "얇은 섹션"으로 잡아준다.

**오분류가 미분류보다 위험하다**는 게 여기서의 판단이다. 그래서 참조 판정은 블록이 3개 이하일 때만 허용한다.

이제 디스패처다.

<!-- src: app/ingestion/parser.py::segment -->
```python
def segment(
    soup: BeautifulSoup,
    blocks: list[Tag],
    seg: dict,
    offsets: list[int] | None = None,
    source_end: int | None = None,
) -> tuple[list[Section], list[dict]]:
    """Dispatch segmentation by type and return sections plus source index records.

    Source index records are populated only for ``xref`` filings.
    """
    match seg["type"]:
        case "xref":
            return segment_by_xref(soup, blocks, offsets, source_end)
        case "undefined":
            return [], []
        case _:
            sections = segment_by_heading(blocks, seg, offsets, source_end)
            classify_sections(sections)  # distinguish valid short disclosures from bugs
            return sections, []
```

이 짧은 함수가 하는 일이 생각보다 크다. **타입 분기를 여기 하나에 가둔다.**

호출부인 `parse_filing`과 `build_profile`은 `segment()`만 부르면 되고 전략이 뭔지 알 필요가 없다. 나중에 네 번째 전략이 추가돼도 호출부는 그대로다.

`classify_sections`를 여기서 부르는 것도 같은 이유다. 이 함수는 `xref`에는 부르면 안 되는데, 그 조건을 호출부가 알아야 한다면 새 전략을 추가할 때마다 모든 호출부를 확인해야 한다. 디스패처 안에 두면 그 지식이 한 곳에 머문다.

**분기 조건이 여러 곳에 흩어지면 새 케이스를 추가할 때 빠뜨린 곳이 생긴다.** 진입점 하나로 모으는 게 대체로 답이다.

### 확인

```bash
uv run pytest tests/ingestion/test_04_validate.py -k classify -v
```

코퍼스 없이 돈다. "None." / "Not applicable." / 위임장 자료 문장 / 긴 본문 네 경우를 본다.

## 여기까지 왔을 때 설명할 수 있어야 하는 것

- **판별 함수가 판별기이면서 설정 생성기를 겸하는 이유는 무엇인가?**
  - **답:** 판별 과정에서 이미 후보 헤딩의 서식과 위치를 측정하며, 그 측정값이 파서에 필요한 설정이기 때문이다. `{}` 또는 완성된 설정을 반환하면 같은 측정을 두 번 하지 않아도 된다.
- **목차와 본문 헤딩을 밀도로 가르는 근거는 무엇인가?**
  - **답:** 목차 항목은 사이에 본문이 거의 없어 문서의 좁은 구간에 몰리고, 실제 본문 헤딩은 문서 전체에 퍼져 있다. 첫 후보와 마지막 후보가 차지하는 상대 구간이 측정 가능한 밀도 신호가 된다.
- **캐스케이드의 순서를 바꾸면 어떤 문서에서 결과가 달라지는가?**
  - **답:** `detect_xref`를 먼저 실행하면 목차가 있는 일반 헤딩형 10-K를 xref 문서로 오인할 수 있으며, 실측 예는 NVIDIA다. `detect_number`를 먼저 시도해야 본문 Item 헤딩이 없다는 사실을 확인한 뒤 예외 경로로 넘어간다.
- **"Not applicable" 한 줄짜리 Item과 파싱 실패를 무엇으로 구분하는가?**
  - **답:** 짧은 섹션 앞부분의 명시적인 문구가 정규식과 맞으면 `empty_disclosure` 상태를 준다. 그런 근거 없이 예상보다 얇은 섹션은 `parsed`로 남겨 검증이 실패로 잡게 한다.
- **판별에 실패한 문서를 버리지 않고 `undefined`로 남기는 이유는 무엇인가?**
  - **답:** `undefined`는 지원하는 방식이 하나도 맞지 않았다는 사실을 문서가 조용히 사라지는 대신 관찰 가능한 상태로 보존한다. 이 상태는 보고·저장할 수 있고 판별기가 개선되면 다시 처리할 수 있다.

---

[← 이전: xref 세그멘테이션](05-segment-xref.md) · [모듈 개요](../03-build.md) · [다음: 프로파일과 검증 →](07-profile-validate.md)
