# M1.1 튜토리얼 5 — 본문에 Item이 없는 문서는 어떻게 자르나

Intel의 10-K에는 본문에 `Item N`으로 시작하는 블록이 **하나도 없다.** 앞 문서에서 만든 헤딩 워크로는 아무것도 찾지 못한다.

그런데 SEC는 본문 재구성을 허용하는 대신 **Cross-Reference Index**를 의무화한다. 어느 페이지가 어느 Item인지 적은 표다. 문서가 답을 스스로 들고 있는 셈이고, 이 문서는 그 답을 읽어내는 별도 모듈 `app/ingestion/xref.py`를 만든다.

여덟 문서 중 가장 길다. 한 번에 끝내려 하지 말고 절 단위로 끊어 간다.

**선행 조건:** 튜토리얼 4까지의 헤딩 워크가 동작해야 한다. 이 문서는 `parser.py`가 아니라 새 파일 `app/ingestion/xref.py`에서 시작한다.

## 무엇을 작성하고 어디를 직접 구현할까

| 구간 | 학습 행동 | 여기서 얻어야 하는 것 |
|---|---|---|
| `XrefEntry`와 상수 | **모델 선언 작성** | 페이지 조인이 필요한 값의 최소 집합 |
| `find_tables`·`parse_xref` | 표 인식을 **직접 구현** | Cross-Reference Index를 다른 표와 가르는 근거 |
| `parse_toc`·`_in_tables` | **구조 작성** | 목차와 xref 표가 섞이지 않게 하는 법 |
| `locate_sections`·`assign_items` | 페이지 조인을 **직접 구현** | 페이지 번호가 어떻게 문자 좌표가 되는가 |
| `page_map`·`find_missing` | **경계 변환 검토** | 본문 없는 Item을 근거로 남기는 방법 |

---

## L8 — 세그멘테이션 B — 문서가 스스로 들고 있는 답을 읽는다

여기서 Intel 문제를 푼다. 앞에서 봤듯 Intel은 2019년부터 10-K를 자사 서사 구조로 재구성했고, 본문에 Item 헤딩이 **하나도 없다.** L7의 헤딩 순회는 아무리 정교한 규칙을 줘도 여기서 0개를 반환한다. 없는 걸 찾을 수는 없다.

### 규제가 만들어준 탈출구

SEC는 이런 재구성을 허용한다. 대신 조건을 붙인다. **Form 10-K Cross-Reference Index** — "내 문서의 어느 페이지가 어느 Item인가"를 적은 표 — 를 반드시 실어야 한다.

즉 문서가 답을 스스로 들고 있다. 여기에 회사 자체 목차를 겹치면 매핑이 완성된다.

```
Cross-Reference Index : Item 1A → Risk Factors → Pages 53-67
Company TOC           : Risk Factors → Page 53
⇒ body "Risk Factors" section = Item 1A
```

LLM도, 휴리스틱도 필요 없다. 문서에 적힌 사실을 두 번 조인하면 끝이다. 규제 문서를 다룰 때는 이렇게 **규제 자체가 만들어준 구조**를 먼저 찾아보는 게 좋다.

### 왜 1:1 매칭으로 안 되나

단순하게 "제목 하나 = Item 하나"로 풀고 싶지만 안 된다. Item 하나가 여러 서사 섹션에 흩어져 있기 때문이다. 실측으로 INTC FY2022의 Item 7은 Pages 5-6, 19-44, 47-51 세 구간에 걸쳐 있고, 서사 섹션으로는 8개다.

그래서 앵커 1:1이 아니라 **페이지 구간 겹침**으로 푼다. "이 섹션이 시작하는 페이지를 포함하는 Item은 누구인가"를 묻는 방식이다.

### 알고리즘 8단계

```
1. Find two tables       index (5+ `Item N.` rows) + company TOC (10+ title|page rows)
2. Parse the index       Item → (title, page ranges, status)
3. Parse the TOC         narrative title → start page
4. Locate the body       which block does each narrative title start at
5. Assign Items          by page-range overlap
6. Second-pass search    Items absent from the TOC but paged in the index
7. Correct boundaries    ranges whose heading is an image (F8)
8. Merge per Item        narrative sections assigned to one Item become one Section
```

L7의 한 루프에 비하면 복잡하다. 그래서 별도 모듈 `xref.py`로 뺀다. 헤딩 순회와 공유하는 게 블록 리스트뿐이고 알고리즘 성격이 완전히 다르기 때문이다. 이 파일은 parser의 데이터 클래스를 import하지 않으므로 순환 import도 생기지 않는다.

먼저 모듈 설명과 import를 작성한다.

#### `app/ingestion/xref.py` 생성 — 모듈 기반

```python
"""`xref` 타입 10-K 처리 — 문서가 스스로 들고 있는 매핑표를 읽는다.

**문제.** 모든 기업이 본문을 "Item 1.", "Item 1A." 로 나누지는 않는다. Intel은 2019년부터
자사 서사 구조("Fundamentals of Our Business" / "Our Capital" / "Other Key Information" …)로
10-K를 재구성했다. 본문에 Item 헤딩이 **하나도 없다** (실측: INTC FY2022 리프 블록
2,267개 중 `Item N` 으로 시작하는 블록 0개 — 색인표는 데이터 표로 통째로 흡수된다).

폰트·스타일 규칙을 아무리 정교하게 만들어도 없는 것을 찾을 수는 없다.

**해법.** SEC는 이런 재구성을 허용하되 **Form 10-K Cross-Reference Index** 를 의무화한다.
즉 문서가 "내 어느 부분이 어느 Item인가"를 스스로 표로 들고 있다. 여기에 기업 자체 목차를
합치면 LLM 없이 매핑이 완성된다:

    Cross-Reference Index : Item 1A → Risk Factors → Pages 53-67
    기업 목차             : Risk Factors → Page 53
    ⇒ 본문 "Risk Factors" 섹션 = Item 1A

Item 하나가 여러 서사 섹션에 걸치는 것도 표가 알려준다 (실측 INTC FY2022:
Item 7 = Pages 5-6, 19-44, 47-51 → 서사 섹션 8개). 그래서 앵커 1:1이 아니라
**페이지 구간 겹침**으로 푼다.
"""

from dataclasses import dataclass, field
import re

from bs4 import BeautifulSoup, Tag
```

근거는 [F5](../01-findings.md#f5)와 [F6](../01-findings.md#f6)에 있다.

> 여담이지만 이 독스트링은 한 번 고쳤다. 원래 "2,416블록 중 1개"라고 적혀 있었는데, 현재 블록화 기준으로 재측정하니 **2,267블록 중 0개**였다. 색인표가 데이터 표로 흡수되면서 그 셀들이 더 이상 리프가 아니게 됐기 때문이다. 결론이 오히려 강해진 경우라 값을 갱신했다. **문서의 수치는 코드가 바뀌면 같이 재야 한다.**

### 구현

### 8.0 자료구조와 상수

#### 대상 파일: `app/ingestion/xref.py`

<!-- src: app/ingestion/xref.py::ITEM_CELL,EMPTY_CELL,REF_CELL,REF_NOTE,PAGE_NUM,STOPWORDS -->
```python
ITEM_CELL = re.compile(r"^item\s+(1[0-6]|[1-9])([A-C])?\s*\.?$", re.I)
EMPTY_CELL = re.compile(r"^\s*(not applicable|none|n/?a|\[?reserved\]?)\.?\s*$", re.I)
REF_CELL = re.compile(r"^\s*\(([a-z])\)\s*$", re.I)
REF_NOTE = re.compile(r"^\(([a-z])\)\s*(.+)$", re.S)
PAGE_NUM = re.compile(r"\d[\d\s]*")
STOPWORDS = {"and", "of", "the", "for", "to", "in", "our", "about", "on", "a", "with"}
```

정규식 상수 다음에는 다섯 Intel filing에서 측정한 xref 임계값을 정의한다.

<!-- src: app/ingestion/xref.py::XREF_TABLE_MIN_ITEM_ROWS,FOOTER_MIN_GAP -->
```python
XREF_TABLE_MIN_ITEM_ROWS = 5  # minimum `Item N.` cells required for an index
TOC_HEADER_SCAN_ROWS = 3  # leading rows scanned for the "Page" header
TOC_TABLE_MIN_ROWS = 10  # minimum `title | page` rows required for a TOC
REF_NOTE_MIN_CHARS = 8  # shorter "(a) Incorporated by ..." text is not a note

# Body connection
TOC_TITLE_MAX_CHARS = 120  # longer blocks are paragraphs, not titles
MISSING_TITLE_MIN_CHARS = 8  # second pass: short titles match accidentally

# Page-footer map (F8)
FOOTER_MAX_STEP = 3  # page increment; rejects unordered numeric table cells
FOOTER_MIN_GAP = 5  # gap from prior footer; rejects financial-index number clusters
```

**코드에서 꼭 볼 것**

- 아홉 상수가 전부 코퍼스 실측값이다. 값 옆의 주석이 근거이고, 바꾸려면 다시 재야 한다.
- `FOOTER_MAX_STEP`과 `FOOTER_MIN_GAP`은 한 쌍이다. 앞은 "페이지 번호는 1~3씩 증가한다"를, 뒤는 "푸터 사이에는 최소 다섯 블록이 있다"를 강제한다. 하나만으로는 재무 색인의 숫자 뭉치를 걸러 내지 못한다.
- `TOC_TITLE_MAX_CHARS`가 상한을 두는 이유는 그보다 긴 블록이 제목이 아니라 문단이기 때문이다. 이 상한이 없으면 본문 문단이 제목 후보로 올라온다.


#### 대상 파일: `app/ingestion/xref.py`

<!-- src: app/ingestion/xref.py::XrefEntry -->
```python
@dataclass
class XrefEntry:
    """Represent one Cross-Reference Index row locating one SEC Item."""

    item: str
    reported_title: str
    spans: list[tuple[int, int]] = field(default_factory=list)  # page ranges
    status: str = "parsed"  # parsed | empty_disclosure | incorporated_by_reference
    reference_source: str | None = None

    def covering(self, page: int) -> tuple[int, int] | None:
        """Return the narrowest range that covers this page."""
        hits = [(s, e) for s, e in self.spans if s <= page <= e]
        return min(hits, key=lambda t: t[1] - t[0]) if hits else None
```

`covering()`은 자유 함수로 빼도 동작한다. 그런데 이건 **"이 구간들에 대해 묻는 질문"** 이므로 데이터와 같이 있는 게 자연스럽다.

효과는 나중에 5단계에서 드러난다. `entry.covering(page)` 한 줄로 "이 Item이 그 페이지를 담당하나"가 읽히고, 배정 규칙 전체가 짧아진다. 자료구조에 붙일 메서드를 고를 때는 "이게 그 데이터에 대한 질문인가"를 기준으로 보면 대체로 맞다.

### 8.1 표 찾기

#### 대상 파일: `app/ingestion/xref.py`

<!-- src: app/ingestion/xref.py::_rows -->
```python
def _rows(tbl: Tag) -> list[list[str]]:
    out = []
    for tr in tbl.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
        cells = [c for c in cells if c]
        if cells:
            out.append(cells)
    return out
```

**코드에서 꼭 볼 것**

- 빈 셀을 먼저 버리고 빈 행도 버린다. SEC 표에는 정렬용 빈 셀이 많아서, 이 정리를 하지 않으면 아래의 모든 판정이 빈칸 개수에 휘둘린다.
- `td`와 `th`를 함께 모은다. SEC 표는 헤더 셀도 `td`로 쓰는 경우가 많아 둘을 구분하면 행 길이가 어긋난다.
- 반환 형태가 문자열의 2차원 리스트다. 이후 `find_tables`, `parse_xref`, `parse_toc`가 전부 이 한 가지 형태만 보면 된다.

<!-- src: app/ingestion/xref.py::_spans -->
```python
def _spans(text: str) -> list[tuple[int, int]]:
    """ "Pages 53 - 67 , 70" → [(53,67),(70,70)].

    iXBRL rendering can insert spaces inside numbers ("1 4" = 14), so remove
    spaces before parsing them.
    """
    out: list[tuple[int, int]] = []
    for part in re.split(r"[,;]", text or ""):
        ns = [int(m.group().replace(" ", "")) for m in PAGE_NUM.finditer(part)]
        if not ns:
            continue
        if len(ns) >= 2 and "-" in part:
            lo, hi = ns[0], ns[-1]
            out.append((lo, hi) if lo <= hi else (hi, lo))  # tolerate typos such as "88 -86"
        else:
            out.extend((n, n) for n in ns)
    return out
```

이 짧은 함수가 실데이터의 지저분함을 두 가지나 흡수한다.

첫째, **iXBRL이 숫자 중간에 공백을 넣는다.** "Pages 1 4, 67"은 1과 4와 67이 아니라 14와 67이다. 렌더링 과정에서 생긴 것이라 원문에는 정말 저렇게 적혀 있다.

둘째, **원문에 오타가 있다.** "88 -86"처럼 시작이 끝보다 큰 구간이 실제로 나온다. 사람이 쓴 문서라 어쩔 수 없다.

둘 다 예외로 던지지 않고 정상 경로에서 조용히 처리한다([B15](../04-bugs.md#b15)). **실데이터를 다루는 파서는 "이상적인 입력"과 "에러" 사이에 넓은 회색지대가 있고, 그 회색지대를 정상 경로로 흡수하는 게 대부분의 일이다.**

<!-- src: app/ingestion/xref.py::find_tables -->
```python
def find_tables(soup: BeautifulSoup) -> tuple[Tag | None, Tag | None]:
    """Find the cross-reference index and company table of contents.

    ``xref`` is a table with at least five ``Item N.`` cells. ``toc`` has a
    "Page" header and at least ten ``title | page`` rows.

    A normal 10-K table of contents can also look like
    ``Item 1. Business ... 3``. Call this only after confirming that the body
    has no Item headings and the filing is therefore an ``xref`` candidate.
    """
    xref = toc = None
    for tbl in soup.find_all("table"):
        rs = _rows(tbl)
        if not rs:
            continue
        if sum(1 for r in rs if any(ITEM_CELL.match(c) for c in r)) >= XREF_TABLE_MIN_ITEM_ROWS:
            xref = tbl
        elif toc is None and any(r[-1].lower() == "page" for r in rs[:TOC_HEADER_SCAN_ROWS]):
            if (
                sum(1 for r in rs if len(r) >= 2 and r[-1].replace(" ", "").isdigit())
                >= TOC_TABLE_MIN_ROWS
            ):
                toc = tbl
    return xref, toc
```

**코드에서 꼭 볼 것**

- 두 표를 한 번의 순회로 찾는다. 색인표는 `Item N.` 셀 개수로, 목차는 "Page" 헤더와 `title | page` 형태의 행 수로 가른다.
- `elif`가 중요하다. 색인표로 판정된 표는 목차 후보에서 빠진다. 표 하나가 둘 다일 수는 없다.
- `toc is None` 조건이 첫 번째 목차만 취한다. 뒤에 나오는 재무제표 색인이 목차를 덮어쓰는 것을 막는다.
- docstring이 호출 순서를 못 박는다. 본문에 Item 헤딩이 없음을 확인한 뒤에만 부른다 — 일반 10-K의 목차도 `Item 1. Business ... 3`처럼 생겼기 때문이다.

### 8.2 표 해석 — 함정 3개를 코드로

#### 대상 파일: `app/ingestion/xref.py`

<!-- src: app/ingestion/xref.py::parse_xref -->
```python
def parse_xref(tbl: Tag) -> list[XrefEntry]:
    """Convert the Cross-Reference Index into Item locations and statuses.

    Indented rows can follow an Item row, such as "Results of operations" under
    Item 7. Add those pages to the parent Item. The filing states the result, so
    body-text inference is unnecessary:
      "Not applicable"                         → empty_disclosure
      "(a)" + note "Incorporated by ..."       → incorporated_by_reference
    """
    entries: list[XrefEntry] = []
    notes: dict[str, str] = {}  # (a) -> reference explanation
    cur: XrefEntry | None = None
    closed = True  # whether the current Item received a value on its own row
    for r in _rows(tbl):
        if m := ITEM_CELL.match(r[0]):
            cur = XrefEntry(
                item=(m.group(1) + (m.group(2) or "")).upper(),
                reported_title=(r[1] if len(r) > 1 else "").rstrip(":").strip(),
            )
            entries.append(cur)
            # Only the third cell is a value. A two-cell title row has no value yet;
            # treating its title as a value misreads the "10" in "Form 10-K Summary".
            tail = r[2] if len(r) > 2 else ""
            # An Item is closed when its row contains a page, Not applicable, or a note.
            # Only an Item without a value absorbs the indented rows below it. Otherwise,
            # the final "Signatures | Page 125" row attaches to Item 16 and makes a
            # Not-applicable Item appear to have body content.
            closed = bool(_spans(tail) or EMPTY_CELL.match(tail) or REF_CELL.match(tail))
        elif cur is not None and not closed and len(r) >= 2:
            tail = r[-1]
        else:
            # "(a) Incorporated by …"
            if (n := REF_NOTE.match(r[0])) and len(r[0]) > REF_NOTE_MIN_CHARS:
                notes[n.group(1).lower()] = n.group(2).strip()
            continue

        if EMPTY_CELL.match(tail):
            cur.status = "empty_disclosure"
        elif rm := REF_CELL.match(tail):
            cur.status = "incorporated_by_reference"
            cur.reference_source = rm.group(1).lower()
        cur.spans += _spans(tail)

    for e in entries:
        if e.reference_source:
            e.reference_source = notes.get(e.reference_source, e.reference_source)
        # Page ranges make the final decision. Even if one child row contains "(a)"
        # (measured in FY2019 Item 7, "Off balance sheet arrangements (a)"), the
        # Item has real body content when its other rows provide pages.
        if e.spans:
            e.status = "parsed"
        elif e.status == "parsed" or EMPTY_CELL.match(e.reported_title):
            e.status = "empty_disclosure"
    return entries
```

이 함수는 짧지만 실제 문서에서 밟은 함정 세 개가 코드로 굳어 있다. 하나씩 보자.

### 함정 1 — `closed` 변수가 없으면 Signatures가 Item 16이 된다

색인표에는 Item 행 아래에 들여쓴 하위 행이 따라올 수 있다. Item 7 아래에 "Results of operations | 25" 같은 식이다. 이 페이지는 부모 Item 7의 것으로 합쳐야 한다.

문제는 "언제까지 하위 행을 먹어야 하나"다. 표 맨 끝에는 보통 "Signatures | Page 125" 행이 있는데, 이걸 계속 먹으면 직전 Item — 대개 Item 16 — 에 붙는다. Item 16이 "Not applicable"인데도 본문이 있는 것처럼 보이게 된다 ([B01](../04-bugs.md#b01)).

`closed` 변수가 이 경계를 명시한다. Item 행 자체가 이미 값(페이지·Not applicable· 참조기호)을 가졌으면 닫힌 것으로 보고, 하위 행을 먹지 않는다. 값이 없는 Item만 아래 행을 흡수한다.

**파서에서 "지금 어떤 문맥인가"는 변수로 드러내는 게 거의 항상 옳다.** 암묵적으로 두면 이런 경계 버그가 조용히 들어온다.

### 함정 2 — 두 칸짜리 행의 제목을 값으로 읽으면 안 된다

`tail = r[2] if len(r) > 2 else ""` 부분이다. 값은 **세 번째 칸에만** 있다.

두 칸짜리 행은 제목만 있고 값이 아직 없는 상태다. 그런데 두 번째 칸을 값으로 읽으면 "Form 10-K Summary"라는 제목에서 `PAGE_NUM` 정규식이 **"10"을 페이지 번호로 뽑아낸다.** Item 16이 10페이지에 있다고 잘못 기록된다.

### 함정 3 — 신호가 충돌하면 최종 권한을 정한다

FY2019 Item 7 아래에 "Off balance sheet arrangements (a)"라는 하위 행이 있다. `(a)`는 "외부 문서 참조" 기호다. 이걸 그대로 반영하면 Item 7 전체가 `incorporated_by_reference`가 되고, **본문이 있는데도 통째로 실종된다** ([B03](../04-bugs.md#b03)). Item 7은 MD&A라 10-K에서 가장 중요한 섹션 중 하나다.

마지막 루프의 `if e.spans: e.status = "parsed"`가 이 충돌의 결론이다. **페이지가 하나라도 있으면 본문이 실재한다.** 하위 행 하나의 참조기호보다 페이지 구간의 존재가 강한 증거다.

여러 신호가 충돌할 수 있는 코드에서는 이렇게 **누가 최종 권한인지를 명시적으로 정해두는 단계**가 필요하다. 안 그러면 입력 순서에 따라 결과가 달라진다.

#### 대상 파일: `app/ingestion/xref.py`

<!-- src: app/ingestion/xref.py::parse_toc -->
```python
def parse_toc(tbl: Tag) -> list[tuple[str, int]]:
    """Return company TOC entries as ``(section title, start page)`` in document order."""
    out = []
    for r in _rows(tbl):
        if len(r) >= 2 and (p := r[-1].replace(" ", "")).isdigit():
            title = r[0].strip()
            if title and not title.lower().startswith("page"):
                out.append((title, int(p)))
    return out
```

**코드에서 꼭 볼 것**

- 마지막 셀이 숫자인 행만 취한다. 페이지 번호가 없는 행은 목차 항목이 아니다.
- `replace(" ", "")`가 있는 이유는 SEC 표에 공백이 낀 숫자가 들어 있기 때문이다. 이 한 번의 정리가 없으면 멀쩡한 항목이 통째로 버려진다.
- "page"로 시작하는 제목을 버린다. 헤더 행이 항목으로 섞여 들어오는 것을 막는 가드다.

### 8.3 본문 연결

#### 대상 파일: `app/ingestion/xref.py`

<!-- src: app/ingestion/xref.py::_norm -->
```python
def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()
```

**코드에서 꼭 볼 것**

- 소문자로 낮추고 영숫자와 공백만 남긴다. 목차 제목과 본문 제목이 구두점과 대소문자만 다른 경우가 많아, 그 차이를 여기서 흡수한다.
- 한 줄짜리지만 `locate_sections`와 `find_missing`이 전부 이 함수를 통과한 문자열로 비교한다. 정규화가 한곳에 모여 있어야 두 비교가 서로 어긋나지 않는다.

<!-- src: app/ingestion/xref.py::_words -->
```python
def _words(s: str) -> set[str]:
    return {w.rstrip("s") for w in _norm(s).split() if w not in STOPWORDS and len(w) > 2}
```

**코드에서 꼭 볼 것**

- 불용어를 빼고 세 글자를 넘는 단어만 남긴 뒤 복수형 `s`를 떼어 집합으로 만든다. 어순과 관사가 달라도 같은 제목으로 보게 하려는 것이다.
- 집합이라 순서를 잃는다. 그게 의도다 — "Notes to the Consolidated..."와 "Notes to Consolidated..."를 같은 것으로 만든다.
- `item_for_page`의 제목 겹침 점수도 이 집합을 쓴다. 정규화 규칙 하나가 두 판정을 동시에 지배한다.

<!-- src: app/ingestion/xref.py::_in_tables -->
```python
def _in_tables(blocks: list[Tag], tables: list[Tag | None]) -> set[int]:
    """Return block indexes inside TOC/index tables so body search can skip them.

    Without this exclusion, title cells in the table of contents become body
    headings. In measured INTC FY2019 data, all thirty sections were incorrectly
    placed in blocks 91-196 inside the TOC table.
    """
    live = [t for t in tables if t is not None]
    if not live:
        return set()
    return {i for i, el in enumerate(blocks) if any(el is t or t in el.parents for t in live)}
```

`_in_tables`는 사소해 보이지만 없으면 전체가 무너진다.

이제부터 "이 서사 제목이 본문 어느 블록에서 시작하나"를 찾을 텐데, 그 제목은 목차 표 안에도 똑같이 있다. 문서 위에서부터 찾으면 **항상 목차가 먼저 걸린다.**

INTC FY2019에서 이걸 빼먹고 돌린 결과가 [B10](../04-bugs.md#b10)이다. 30개 섹션이 전부 목차 표 안(블록 91~196)에 배치됐고, 각 섹션의 블록 수가 2개씩이었다. 그런데 겉보기 지표는 멀쩡했다 — Item 개수도 맞고, 순서도 맞고, 중복도 없었다. **L1에서 말한 "구조가 완벽한 실패"가 바로 이것**이고, L12의 검증이 이걸 잡으려고 존재한다.

<!-- src: app/ingestion/xref.py::locate_sections -->
```python
def locate_sections(
    blocks: list[Tag], toc: list[tuple[str, int]], skip: set[int]
) -> list[tuple[str, int, int]]:
    """Locate the body block where each TOC title begins.

    A title also appears in the TOC and page headers. Preserve document order and
    consume each match once from left to right. Return
    ``[(title, start_page, block_index), ...]``.
    """
    texts = [_norm(b.get_text(" ", strip=True)) for b in blocks]
    wordsets = [_words(t) if len(t) < TOC_TITLE_MAX_CHARS else set() for t in texts]
    found, cursor = [], 0
    for title, page in toc:
        want = _norm(title)
        ww = _words(title)
        hit = next(
            (
                j
                for j in range(cursor, len(blocks))
                if j not in skip and texts[j] == want and len(texts[j]) < TOC_TITLE_MAX_CHARS
            ),
            None,
        )
        if hit is None and ww:
            # Fall back to word-set equality for article/case differences between
            # TOC and body titles (FY2020: "Notes to the Consolidated..." versus
            # "Notes to Consolidated...").
            hit = next(
                (j for j in range(cursor, len(blocks)) if j not in skip and wordsets[j] == ww),
                None,
            )
        if hit is None:
            continue
        found.append((title, page, hit))
        cursor = hit + 1
    return found
```

**코드에서 꼭 볼 것**

- `cursor`가 이 함수의 핵심이다. 매치를 왼쪽부터 한 번씩만 소비해 문서 순서를 보존한다. 커서가 없으면 페이지마다 반복되는 머리글이 전부 같은 제목으로 잡힌다.
- 정확 일치를 먼저 시도하고 실패했을 때만 단어 집합 비교로 넘어간다. 순서가 반대면 느슨한 비교가 정확한 후보를 가로챈다.
- `skip` 집합이 색인표와 목차 자신의 블록을 제외한다. 이것이 없으면 목차 안의 제목이 본문 시작점으로 잡힌다.
- `wordsets`를 루프 밖에서 미리 만든다. 안에서 계산하면 제목 수 곱하기 블록 수만큼 정규화가 돌아간다.

### 커서를 되돌리지 않는다

`skip`으로 목차 표를 제외해도 문제가 남는다. 같은 제목이 페이지 머리글에도 나오고, 본문 중간의 언급에도 나온다.

해법은 **커서 단조 전진**이다. 목차의 항목 순서와 본문의 등장 순서가 같다는 사실을 이용해, 한 번 찾을 때마다 커서를 그 뒤로 옮기고 다음 제목은 커서 이후에서만 찾는다.

이러면 이미 소비한 위치로 되돌아가지 않으니 중복 매칭이 없고, 덤으로 전체 탐색이 O(n²)에서 벗어난다. **문서 순서라는 제약을 알고리즘에 활용한 사례**다. L3에서 `find_all`의 문서 순서 보장을 강조한 이유가 여기서 나온다.

### 폴백은 딱 한 단계만

정확 일치가 실패하면 단어집합 일치로 한 번 더 시도한다. 목차에는 "Notes to **the** Consolidated…"인데 본문에는 "Notes to Consolidated…"인 관사 차이가 FY2020에 실제로 있어서다.

중요한 건 **여기서 멈춘다**는 점이다. 부분 일치, 편집 거리, 유사도 임계값으로 계속 느슨하게 만들면 언젠가 맞긴 맞는데 왜 맞는지 모르는 코드가 된다. 폴백은 "실제로 관측된 차이"를 흡수하는 선까지만 연다.

### 8.4 Item 배정

#### 대상 파일: `app/ingestion/xref.py`

<!-- src: app/ingestion/xref.py::assign_items -->
```python
def assign_items(located: list[tuple[str, int, int]], entries: list[XrefEntry]) -> dict[int, str]:
    """Assign each narrative section to one SEC Item without duplicating body text.

    Among Items covering the section's **start page**, choose the narrowest
    **individual covering range**, not the smallest total span. For measured INTC
    FY2019, "Critical Accounting Estimates" on page 50 is covered by Item 1A's
    50-60 range and Item 7's 50-50 range; Item 7 correctly wins.

    Title-word overlap outranks range width. For example, FY2021 "Market for Our
    Common Stock" on page 64 overlaps Item 2's 64-64 range and Item 5's 64-65
    range. Width alone picks Properties, while the words ``market`` and ``common``
    identify Item 5. The same rule maps FY2019 "Information about Our Executive
    Officers" to Item 10 instead of Item 1.
    """
    out: dict[int, str] = {}
    for title, page, bi in located:
        if item := item_for_page(page, entries, title):
            out[bi] = item
    return out
```

**코드에서 꼭 볼 것**

- 판정 우선순위가 docstring에 적혀 있고 코드가 정확히 그 순서다. 제목 단어 겹침 → 범위 폭 → Item 번호 길이.
- 폭 비교가 **개별 커버 범위**이지 전체 합이 아니다. Item 1A의 50-60과 Item 7의 50-50이 같은 페이지를 덮을 때 좁은 쪽인 Item 7이 이긴다.
- 단어 겹침이 폭보다 우선인 이유가 예시에 있다. 64페이지에서 폭만 보면 Properties가 이기지만 `market`과 `common`이라는 단어가 Item 5를 가리킨다.

<!-- src: app/ingestion/xref.py::item_for_page -->
```python
def item_for_page(page: int, entries: list[XrefEntry], title: str = "") -> str | None:
    """Return the owning Item using title overlap, range width, then shorter number."""
    cands = []
    for e in entries:
        if e.status != "parsed":
            continue
        if span := e.covering(page):
            overlap = len(_words(title) & _words(e.reported_title)) if title else 0
            cands.append((-overlap, span[1] - span[0], len(e.item), e))
    return min(cands, key=lambda c: c[:3])[3].item if cands else None
```

**코드에서 꼭 볼 것**

- 정렬 키가 `(-overlap, width, number length)` 튜플이다. 세 기준을 한 번의 `min`으로 처리한다.
- `overlap`에 음수를 붙인 것은 `min`으로 최댓값을 고르기 위해서다. 비교 함수를 따로 쓰지 않으려는 관용구다.
- `e.status != "parsed"`를 먼저 걸러 빈 공시나 참조로 끝난 Item이 본문을 가져가지 않게 한다.
- 세 번째 키가 동점을 결정론적으로 깬다. 같은 조건이면 `1`이 `1A`보다 짧으므로 이긴다.

### 한 페이지를 여러 Item이 주장할 때

배정이 단순하지 않은 이유가 있다. 색인표의 페이지 구간은 겹칠 수 있다.

INTC FY2019의 "Critical Accounting Estimates"는 50페이지에서 시작하는데, Item 1A가 50-60을, Item 7이 50-50을 주장한다. 이럴 땐 **구간이 좁은 쪽**이 더 구체적인 주장이므로 Item 7이 맞다.

그런데 구간 폭만으로는 안 되는 경우도 있다. FY2021의 "Market for Our Common Stock"은 64페이지인데, Item 2(Properties)가 64-64, Item 5(Market for Registrant's Common Equity)가 64-65를 주장한다. 폭만 보면 Item 2가 이긴다. 하지만 제목의 `market`, `common`이라는 단어가 Item 5를 가리킨다.

그래서 우선순위가 셋이다. **제목 단어 겹침 많은 순 → 구간 좁은 순 → Item 번호 짧은 순.** 세 사례 모두 [B08](../04-bugs.md#b08)에 실측으로 기록돼 있다.

### 다중 기준 정렬은 튜플로 쓴다

이 우선순위를 `if/elif` 체인으로 쓰면 금방 엉킨다. 대신 튜플을 만들어 `min()`에 넘긴다.

```python
cands.append((-overlap, span[1] - span[0], len(e.item), e))
```

파이썬의 튜플 비교는 왼쪽부터 사전식이라, 튜플의 원소 순서가 곧 우선순위가 된다. 내림차순이 필요한 항목은 부호를 뒤집는다(`-overlap`).

마지막 원소로 객체 자체를 넣되 `key=lambda c: c[:3]`으로 비교에서 제외한 것도 요령이다. 이렇게 하면 "정렬 기준"과 "정렬 결과로 꺼낼 값"을 한 튜플에 담으면서도, 비교 불가능한 객체가 비교에 끼어드는 걸 막는다. `XrefEntry`끼리는 `<` 비교가 안 되므로 슬라이싱 없이 넘기면 `TypeError`가 난다.

### 8.5 경계 보정과 2차 수색

여기까지 오면 대부분의 섹션이 배정된다. 그런데 실제 Intel 문서에는 두 가지 구멍이 남는다.

**구멍 1 — 헤딩이 이미지다.** INTC FY2022부터 "Segment Trends and Results", "Auditor's Reports" 같은 섹션 제목이 **이미지로 렌더링돼 본문 텍스트에 존재하지 않는다.** 제목 매칭으로는 이 경계를 찾을 방법이 없다.

이럴 때 남은 유일한 결정적 신호가 **페이지 번호 푸터**다. 본문 사이에 "71" 같은 숫자만 있는 블록이 페이지 경계를 알려준다. `page_map()`이 그 지도를 만든다.

문제는 숫자만 있는 블록이 페이지 푸터만은 아니라는 것이다. 재무제표 색인의 "76 77 78…" 같은 숫자 뭉치도 걸린다(FY2022 블록 1378~1384). 그래서 두 가지 필터를 건다 — **증가폭이 1~3 이내**(순서 없는 표 셀 거부)이고, **직전 푸터에서 5블록 이상 떨어져 있을 것**(숫자 뭉치 거부).

**구멍 2 — 목차에 없는 Item이 있다.** INTC FY2022의 Item 3(Legal Proceedings)은 재무제표 주석 안에 들어 있어서 회사 목차에 없다. 하지만 색인표에는 페이지가 적혀 있고, 본문 블록 2100에 "Legal Proceedings" 헤딩이 실제로 존재한다.

`find_missing()`이 이 경우를 2차로 훑는다. 색인표에는 있는데 아직 배정 안 된 Item의 제목을 본문에서 직접 찾는다. 여기서도 `MISSING_TITLE_MIN_CHARS`(8자) 하한을 걸어 짧은 제목의 우연한 일치를 막는다 — L7의 `match_canonical`과 같은 방어다.

#### 대상 파일: `app/ingestion/xref.py`

<!-- src: app/ingestion/xref.py::page_map -->
```python
def page_map(blocks: list[Tag]) -> list[tuple[int, int]]:
    """Build a ``(block_index, page)`` map from body page-number footer blocks.

    Title matching cannot define boundaries when a filing renders section headings
    as images. In measured INTC FY2022+ data, headings such as "Segment Trends and
    Results" and "Auditor's Reports" do not exist in body text. Page footers are
    then the only deterministic boundary signal.

    Measured noise filters accept only increments of one to three, rejecting
    unordered numeric table cells, and require five blocks since the prior footer.
    The gap prevents the FY2022 financial-index cluster "76 77 78..." at blocks
    1378-1384 from being mistaken for page footers.
    """
    marks = []
    # Initialize last_blk far enough back that the first footer passes the gap condition.
    cur, last_blk = 0, -FOOTER_MIN_GAP
    for i, b in enumerate(blocks):
        t = b.get_text(" ", strip=True)
        if not re.fullmatch(r"\d{1,3}", t):
            continue
        n = int(t)
        if cur < n <= cur + FOOTER_MAX_STEP and i - last_blk >= FOOTER_MIN_GAP:
            marks.append((i, n))
            cur, last_blk = n, i
    return marks
```

**코드에서 꼭 볼 것**

- 제목 매칭이 통하지 않는 문서를 위한 마지막 경로다. INTC FY2022부터는 섹션 제목이 이미지라 본문 텍스트에 아예 없다.
- 조건이 둘이다. 증가폭이 1에서 3 사이일 것, 직전 푸터에서 다섯 블록 이상 떨어져 있을 것. 앞은 순서 없는 숫자 셀을, 뒤는 재무 색인의 연속된 숫자 뭉치를 거른다.
- `last_blk`를 음수로 시작한다. 문서의 첫 푸터가 간격 조건에 걸리지 않게 하는 초기화다.
- `fullmatch`라서 숫자만 있는 블록만 후보다. "Page 12" 같은 형태는 여기서 탈락한다.

<!-- src: app/ingestion/xref.py::find_missing -->
```python
def find_missing(
    blocks: list[Tag], entries: list[XrefEntry], assigned: set[str], skip: set[int]
) -> list[tuple[str, int, int]]:
    """Find Items omitted from the TOC whose titles still appear in the body.

    In measured INTC FY2022 data, Item 3 Legal Proceedings is inside the financial
    statement notes and absent from the company TOC, but a "Legal Proceedings"
    heading exists at body block 2100.
    """
    texts = [_norm(b.get_text(" ", strip=True)) for b in blocks]
    out = []
    for e in entries:
        if e.item in assigned or e.status != "parsed" or not e.reported_title:
            continue
        want = _norm(e.reported_title)
        if len(want) < MISSING_TITLE_MIN_CHARS:
            continue
        hit = next(
            (j for j in range(len(blocks)) if j not in skip and texts[j] == want),
            None,
        )
        if hit is not None:
            out.append((e.reported_title, e.spans[0][0] if e.spans else 0, hit))
    return out
```

**코드에서 꼭 볼 것**

- 목차에 없는 Item을 위한 두 번째 통과다. INTC FY2022의 Item 3은 재무제표 주석 안에 있어 회사 목차에 등장하지 않는다.
- `MISSING_TITLE_MIN_CHARS`로 짧은 제목을 배제한다. 두세 글자짜리 제목은 우연히 일치할 확률이 높아서, 여기서 거르지 않으면 엉뚱한 블록이 Item으로 배정된다.
- 여기서는 `cursor` 없이 문서 전체를 본다. 첫 통과에서 못 찾은 항목이라 순서 보존이 의미를 갖지 않는다.
- 이미 배정된 Item과 `skip` 블록은 건너뛴다. 같은 본문이 두 Item에 배정되는 것을 막는 가드다.

### 8.6 조립

#### 대상 파일: `app/ingestion/parser.py`

<!-- src: app/ingestion/parser.py::segment_by_xref -->
```python
def segment_by_xref(
    soup: BeautifulSoup,
    blocks: list[Tag],
    offsets: list[int] | None = None,
    source_end: int | None = None,
) -> tuple[list[Section], list[dict]]:
    """Segment strategy 2 by joining the index and TOC on page ranges.

    A heading walk cannot work because the body has no Item headings. Return the
    assembled sections and the original index records.
    """
    xref_tbl, toc_tbl = find_tables(soup)
    source_spans = block_source_spans(blocks, offsets, source_end)
    entries = parse_xref(xref_tbl)
    toc = parse_toc(toc_tbl)
    item_index = [
        {
            "item": e.item,
            "reported_title": e.reported_title,
            "pages": e.spans,
            "status": e.status,
            "reference_source": e.reference_source,
        }
        for e in entries
    ]

    skip = _in_tables(blocks, [xref_tbl, toc_tbl])  # TOC and index tables are not body text
    freq = Counter(b.get_text(" ", strip=True) for b in blocks)
    located = locate_sections(blocks, toc, skip)
    assigned = assign_items(located, entries)

    # Search the body for Items omitted from the TOC, such as Legal Proceedings in notes.
    for title, page, bi in find_missing(blocks, entries, set(assigned.values()), skip):
        if bi not in assigned:
            located.append((title, page, bi))
            assigned[bi] = next(e.item for e in entries if e.reported_title == title)
    located.sort(key=lambda t: t[2])
    footer_at = {p: i for i, p in page_map(blocks)}  # page -> footer block

    # A narrative section ends before the next section; image headings can shift the boundary.
    spans: list[tuple[str, str, int, int]] = []  # (item, narrative title, start, end)
    for k, (title, page, bi) in enumerate(located):
        end = located[k + 1][2] if k + 1 < len(located) else len(blocks)
        item = assigned.get(bi)
        if item is None:
            continue
        entry = next(e for e in entries if e.item == item)
        hi = (entry.covering(page) or (page, page))[1]  # end page of this section's range
        next_page = located[k + 1][1] if k + 1 < len(located) else 10**9
        clamp = footer_at.get(hi)
        # Clamp only when the next heading starts more than one page later. A heading on
        # the next page indicates spillover rather than an orphan (measured FY2021 Item 7A).
        if clamp is not None and bi < clamp + 1 < end and next_page > hi + 1:
            orphan_lo, orphan_page = clamp + 1, hi + 1
            end = clamp + 1
            # Assign an orphan range to the Item owning that page (FY2022 pages 72-80 -> Item 8).
            if (
                k + 1 < len(located)
                and (owner := item_for_page(orphan_page, entries))
                and located[k + 1][2] - orphan_lo >= ORPHAN_MIN_BLOCKS  # discard fragments
            ):
                spans.append((owner, CANONICAL.get(owner, ""), orphan_lo, located[k + 1][2]))
        spans.append((item, title, bi, end))
    spans.sort(key=lambda s: s[2])

    # Merge narrative sections assigned to one Item in document order without duplicates.
    by_item: dict[str, list[tuple[str, int, int]]] = {}
    for item, title, lo, hi in spans:
        by_item.setdefault(item, []).append((title, lo, hi))

    sections: list[Section] = []
    for e in entries:
        parts = by_item.get(e.item, [])
        sec = Section(
            part=PART_OF.get(e.item),
            item=e.item,
            canonical_title=CANONICAL.get(e.item, ""),
            reported_title=("; ".join(t for t, _, _ in parts) if parts else e.reported_title)[
                :JOINED_TITLE_MAX
            ],
            status=e.status,
            reference_source=e.reference_source,
            block_index=parts[0][1] if parts else None,
            block_range=(min(p[1] for p in parts), max(p[2] for p in parts)) if parts else None,
            source_pos=(source_pos(blocks[parts[0][1]], offsets) if parts and offsets else None),
        )
        for source_group, (_title, lo, hi) in enumerate(parts):
            for j in range(lo, hi):
                if j in skip:
                    continue
                text = blocks[j].get_text(" ", strip=True)
                if not text:
                    continue
                # Page footers such as "71" and repeated page headers are not body text.
                if re.fullmatch(r"\d{1,3}", text) or (
                    len(text) < PAGE_HEADER_MAX_CHARS and freq[text] >= PAGE_HEADER_MIN_REPEATS
                ):
                    continue
                sec.blocks.append(
                    _body_block(
                        blocks[j],
                        text,
                        *source_spans[j],
                        source_group=source_group,
                        source_heading=_title,
                    )
                )
        sections.append(sec)
    return sections, item_index
```

이 조립 함수에서 마지막으로 짚을 두 가지가 있다.

### 잘려나간 블록은 버리지 말고 주인을 찾아준다

이미지 헤딩 때문에 페이지 푸터로 경계를 자르면, 어느 섹션에도 안 속하는 블록 구간이 생긴다. 그냥 버리면 커버리지가 떨어지고 실제 내용이 사라진다.

대신 **그 페이지를 소유한 Item에게 귀속시킨다.** FY2022의 p72~80 구간이 이렇게 Item 8로 들어갔다([B06](../04-bugs.md#b06)). 이미 `item_for_page()`가 있으니 재사용하면 된다.

다만 너무 짧은 조각은 버린다(`ORPHAN_MIN_BLOCKS` 3개). 의미 있는 본문이 아니라 잘린 부스러기일 가능성이 높아서다.

### 버그를 고치면 반대 방향도 확인한다

`next_page > hi + 1` 조건이 눈에 띈다. 이건 [B07](../04-bugs.md#b07)의 산물이다.

경계 보정을 무조건 적용하니 이번엔 반대 문제가 생겼다. 섹션이 페이지를 자연스럽게 넘어가는 정상적인 경우까지 잘라버려서, Item 7A의 마지막 문단이 Item 1A 서두에 붙었다. 다음 헤딩이 **바로 다음 페이지**에서 시작한다면 그건 고아 구간이 아니라 정상적인 페이지 걸침이다.

**수정이 만든 새 실패를 반대 방향에서 확인하는 습관**이 필요하다. "고쳤다"는 대개 "이 방향의 실패를 고쳤다"이지 "모든 방향에서 옳아졌다"가 아니다.

### 확인

`xref.py`의 마지막 함수까지 작성했으면 `app/ingestion/parser.py` 맨 위의 BeautifulSoup import 아래에 다음 import를 추가한다. 이제 두 모듈이 정식 방향으로 연결된다.

#### `app/ingestion/parser.py` 수정 — xref 연결

```python
from app.ingestion.xref import (
    _in_tables,
    assign_items,
    find_missing,
    find_tables,
    item_for_page,
    locate_sections,
    page_map,
    parse_toc,
    parse_xref,
)
```

먼저 표 두 개가 뽑히는지부터:

```bash
uv run pytest tests/ingestion/test_06_xref.py -k "tables_are_found or row_counts" -v
```

```
INTC-FY2019  색인표 21  목차 30
INTC-FY2022  색인표 22  목차 25
```

그 다음 전체:

```bash
uv run pytest tests/ingestion/test_06_xref.py -v
```

**반드시 확인할 것**

| 확인 | 왜 |
|---|---|
| Item 7이 FY2020~23에서 69k~77k | 서사 섹션 여러 개가 합쳐진 결과([F7](../01-findings.md#f7)). 10k대면 조인이 안 된 것 |
| Item 8에 표 52~65개 (FY2020~23) | 재무제표가 제대로 귀속됐나. 적으면 이미지 헤딩 클램프 문제 |
| Item 3이 존재 | 목차엔 없고 주석 안에 있어서 2차 수색으로만 잡힌다 |
| Part III(10~14)가 참조 처리 | 색인표가 `(a)`~`(e)` 각주로 알려준다 |

> ⚠ **FY2019는 두 지표 모두 예외다.** Item 7이 33k(색인표가 그 해엔 "Our Products"를 Item 1에 배정), Item 8 표가 7개(구식 파일이라 표블록 자체가 18개뿐). **버그가 아니다** — `tests/ingestion/golden.py`의 `XREF_ITEM_SHAPE`가 연도별로 따로 고정한다.

**밟은 함정** — [B01](../04-bugs.md#b01) · [B02](../04-bugs.md#b02) · [B03](../04-bugs.md#b03) · [B06](../04-bugs.md#b06) · [B07](../04-bugs.md#b07) · [B08](../04-bugs.md#b08) · [B10](../04-bugs.md#b10) · [B15](../04-bugs.md#b15)

### 여기까지 온 상태

두 세그멘테이션 전략이 모두 완성됐다. `segment_by_heading`이 헤딩이 있는 15개 파일링을, `segment_by_xref`가 Intel 5개를 처리한다. 알고리즘은 전혀 다르지만 **둘 다 같은 `list[Section]`을 내놓는다.** 좌표와 블록 귀속까지 동일한 형태다.

이게 중요하다. 아래 레이어(L10 이후)와 다음 모듈들은 어느 전략이 썼는지 몰라도 된다.

아직 답 안 한 질문이 하나 남았다. **"이 파일에는 어느 전략을 써야 하나?"** L9의 일이다.

## 여기까지 왔을 때 설명할 수 있어야 하는 것

- **본문에 Item 헤딩이 없는 문서에서 답을 어디서 찾는가?**
  - **답:** SEC가 요구한 Cross-Reference Index에는 Item별 페이지가 있고, 회사 목차에는 서사 섹션의 시작 페이지가 있다. 문서가 직접 제공한 두 사실을 페이지 범위로 결합하면 헤딩 워크를 대신할 수 있다.
- **Cross-Reference Index를 다른 표와 구분하는 신호는 무엇인가?**
  - **답:** `Item N`으로 시작하는 셀이 측정된 최소 개수 이상 있는 표를 xref로 보고, 목차는 Page 헤더와 제목-페이지 행으로 따로 판별한다. `elif`는 한 표가 둘로 동시에 채택되는 것도 막는다.
- **목차와 xref 표가 섞이면 어떤 결과가 나오는가?**
  - **답:** 제목 검색이 본문이 아니라 목차 안의 복사본을 잡아 모든 섹션이 그 표 안의 짧은 구간으로 몰린다. Item 개수와 순서는 정상처럼 보여도 본문이 비어 있는 구조적으로 그럴듯한 실패가 된다.
- **페이지 번호가 어떻게 문자 좌표로 바뀌는가?**
  - **답:** xref의 페이지 범위를 목차 제목과 결합하고, 그 제목을 본문 블록에서 찾은 뒤 블록 인덱스를 `source_pos`와 `block_source_spans`에 통과시킨다. 그 결과가 원본 HTML의 절대 문자 오프셋이다.
- **본문이 없는 Item을 버리지 않고 기록하는 이유는 무엇인가?**
  - **답:** 색인이 해당 Item을 명시적으로 해당 없음 또는 외부 문서 참조라고 밝힐 수 있다. Item과 상태를 남겨야 그 진술과 출처를 보존하고, 정상적인 부재를 파서가 놓친 경우와 구분하며 색인 커버리지를 검증할 수 있다.

---

[← 이전: 헤딩 세그멘테이션](04-segment-heading.md) · [모듈 개요](../03-build.md) · [다음: 판별과 분류 →](06-detect-classify.md)
