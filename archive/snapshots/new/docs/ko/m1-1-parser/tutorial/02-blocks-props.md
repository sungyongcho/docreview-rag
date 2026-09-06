# M1.1 튜토리얼 2 — 재무제표를 부수지 않고 텍스트를 꺼낸다

L3은 HTML 트리를 평평한 블록 목록으로 바꾸고, L4는 블록 하나에서 서식 속성을 뽑는다. 이 장에서 알고리즘다운 알고리즘이 처음 나온다.

L3이 이 모듈에서 가장 미묘한 층이다. 순진하게 짜면 재무제표가 셀 단위로 부서지는데, 그 손상은 M1.2와 M2를 다 지나 최종 인용에서야 드러난다.

**선행 조건:** 튜토리얼 1의 `uv run pytest tests/ingestion/test_01_blocks.py -k ixbrl_numbers_survive -v`와 `-k item_regex -v`가 통과해야 한다.

## 무엇을 작성하고 어디를 직접 구현할까

| 구간 | 학습 행동 | 여기서 얻어야 하는 것 |
|---|---|---|
| L3 `_is_data_table` | 판정 기준을 **직접 구현** | 데이터 표와 레이아웃 표를 가르는 근거 |
| L3 `leaf_blocks` | 순회 알고리즘을 **직접 구현** | 조건 순서 하나가 재무제표를 부수는 지점 |
| L4 `_inline_css` | **구조 작성** | 서식이 요소 자신이 아니라 안쪽 span에 있는 경우 |
| L4 `block_props` | **필드 매핑 작성 후 경계 변환 검토** | 여기서만 딕셔너리가 맞는 이유 |

---

## L3 — 블록화 — 이 장에서 가장 미묘한 곳

HTML은 트리다. 그런데 우리가 할 일은 "이 헤딩부터 다음 헤딩까지"를 한 섹션으로 묶는 것이다. 트리 구조에서 "다음 헤딩까지"를 표현하려면 형제 노드를 따라가다가 부모로 올라갔다가 다시 내려오는 코드를 짜야 한다. 금방 지저분해진다.

그래서 트리를 **순서 있는 평평한 리스트**로 편다. 문서를 위에서 아래로 읽은 순서 그대로 늘어놓으면, 섹션 분할은 그냥 리스트 슬라이싱이 된다.

### 순진하게 짜면 재무제표가 부서진다

"안에 다른 블록이 없는 요소가 리프"라고 정의하는 게 자연스럽다.

```python
# ❌ this alone shatters the financial statements
[el for el in soup.find_all(["div","p","table"]) if el.find(["div","p","table"]) is None]
```

이게 왜 깨지는지는 실제 파일을 보면 안다([F9](../01-findings.md#f9)). 2019년쯤의 구식 파일은 표의 **셀마다 `<div>`를 하나씩 넣는다.** 그러면 `<table>` 안에 `<div>`가 있으니 표는 리프가 아니고, 대신 셀 안의 `<div>` 하나하나가 리프가 된다.

결과는 이렇다. 3년치 매출을 담은 재무제표 하나가 "2024", "26,974", "2023", "26,974"… 같은 조각 수십 개의 문단으로 흩어진다. 표라는 사실도, 어느 숫자가 어느 연도인지도 사라진다.

그럼 반대로 `<table>`을 무조건 통짜로 삼키면 되나? 그것도 안 된다. Intel 문서는 페이지 전체를 표로 감싸는 경우가 있다. 통째로 삼키면 그 안에 있던 섹션 헤딩까지 같이 먹혀서, 문서에 헤딩이 하나도 없는 것처럼 보인다.

### 그래서 표를 두 종류로 가른다

| 표 종류 | 판별 | 처리 |
|---|---|---|
| 데이터 표 | 숫자 셀 밀도 높음 **+ 장문 셀 없음** | 표 자체가 블록 하나. 구조 보존 |
| 레이아웃 표 | 장문 셀(`LAYOUT_CELL_CHARS`(300자)↑) 존재 | 내부 요소가 블록. 그 안에 본문·헤딩이 있다 |

여기서 데이터 표로 판정된 블록은 HTML 원문을 `Block.html`에 그대로 담아둔다. 다음 장 **M1.2가 그 HTML을 받아 마크다운 표로 변환한다.** 지금 표를 조각내면 M1.2가 복원할 방법이 없으므로, 이 판정이 두 모듈에 걸친 계약인 셈이다.

### 조건 순서가 버그를 만든다

`_is_data_table()`을 보면 "장문 셀이 있으면 즉시 탈락"이 숫자 밀도 계산보다 **앞에** 있다. 순서를 바꾸면 어떻게 될까.

Intel의 인포그래픽 표가 문제가 된다. 이 표는 숫자가 많아서 숫자 밀도만 보면 데이터 표로 판정된다. 그런데 실제로는 그 안에 설명 문단과 섹션 헤딩이 같이 들어 있다. 데이터 표로 판정해서 통째로 삼키면 그 헤딩들이 사라진다.

장문 셀 조건을 앞에 두면 이 표는 밀도 계산에 도달하기 전에 탈락한다. **부정 조건을 앞에 두어 조기 탈락시키는 것**이 이런 판별 함수의 기본기다([B05](../04-bugs.md#b05)).

### 구현 — 리프 블록 — 표를 부수지 않고 텍스트를 꺼낸다

#### 대상 파일: `app/ingestion/parser.py`

<!-- src: app/ingestion/parser.py::_is_data_table -->
```python
def _is_data_table(tbl: Tag) -> bool:
    """Use numeric-cell density to distinguish financial data from layout tables."""
    cells = tbl.find_all(["td", "th"])
    if len(cells) < DATA_TABLE_MIN_CELLS:
        return False
    texts = [c.get_text(" ", strip=True) for c in cells]
    if any(len(t) > LAYOUT_CELL_CHARS for t in texts):  # a long prose cell means layout
        return False
    numeric = sum(1 for t in texts if t and len(t) < NUMERIC_CELL_CHARS and re.search(r"\d", t))
    return numeric >= max(DATA_TABLE_MIN_NUMERIC, len(cells) // DATA_TABLE_NUMERIC_DIVISOR)
```

**코드에서 꼭 볼 것**

- 기준은 수치 셀의 밀도 하나다. `<th>`의 존재는 무시하는데, SEC 표는 `<th>`를 거의 쓰지 않기 때문이다.
- 조건 순서가 중요하다. 긴 산문 셀이 하나라도 있으면 밀도 계산에 가기 전에 레이아웃 표로 확정된다.
- 임계값은 고정 개수와 비율의 `max`라서, 작은 표는 절대 개수로, 큰 표는 비율로 판정되고 어느 쪽도 표 크기에 휘둘리지 않는다.

<!-- src: app/ingestion/parser.py::leaf_blocks -->
```python
def leaf_blocks(soup: BeautifulSoup) -> list[Tag]:
    data_ids: set[int] = set()
    for t in soup.find_all("table"):
        if _is_data_table(t) and not any(id(p) in data_ids for p in t.find_parents("table")):
            data_ids.add(id(t))  # keep only the outermost nested table

    out = []
    for el in soup.find_all(["div", "p", "table"]):
        inside_data = any(id(p) in data_ids for p in el.find_parents("table"))
        if el.name == "table":
            if not inside_data and (id(el) in data_ids or el.find(["div", "p", "table"]) is None):
                out.append(el)  # keep a data table or legacy leaf table as one block
        elif not inside_data and el.find(["div", "p", "table"]) is None:
            out.append(el)
    return out
```

코드에 `id(t)`로 집합을 만드는 부분이 있다. `data_ids.add(t)`가 아니라 `data_ids.add(id(t))`인 이유가 있다. BeautifulSoup의 `Tag`는 `__hash__`가 우리가 원하는 동일성 — "메모리상 같은 노드인가" — 과 다르게 동작할 수 있다. 내용이 같은 다른 노드를 같다고 판단해버리면 중첩 표 처리가 어긋난다. `id()`로 객체 정체성을 직접 키로 쓰면 이 위험이 없다.

그리고 조용하지만 중요한 사실 하나. **`find_all`은 문서 순서를 보장한다.** 그래서 위 루프의 `out`은 별도 정렬 없이 이미 문서 순서다.

이게 이후 모든 단계의 전제다. L7의 "이 헤딩부터 다음 헤딩까지"도, L8에서 커서를 단조 증가시키며 제목을 찾는 것도 전부 여기에 기댄다. 나중에 성능 때문에 이 루프를 병렬화하고 싶어지더라도, 순서가 깨지면 그 아래 전부가 조용히 틀리게 된다.

### 확인

CLI는 L14에서 추가하므로, 여기서는 골든 데이터로 블록화 결과를 곧바로 대조한다. 전체 20개 문서의 기대값은 `tests/ingestion/golden.py`의 `BLOCKS`에 있다.

```bash
uv run pytest tests/ingestion/test_01_blocks.py -v
```

**반드시 확인할 것**

| 확인 | 왜 |
|---|---|
| **표블록이 0인 파일이 없다** | 0이면 [F9](../01-findings.md#f9)에 걸린 것 — 표가 셀 단위로 부서졌다 |
| AMD-FY2019·NVDA-FY2020·INTC-FY2019는 블록이 3~5배 많다 | 정상. 구식 파일이라 껍데기 div가 많다 |
| INTC는 문서표 대비 표블록이 적다(492→18) | 정상. 대부분이 레이아웃 표라 안으로 들어간다 |

**틀렸을 때** — 표블록 0 → `_is_data_table`의 장문 셀/숫자 밀도 조건. 블록이 비정상적으로 적음 → `leaf_blocks`가 표를 통째로 삼키고 있다.

**밟은 함정** — [B04](../04-bugs.md#b04) 표 0개 · [B05](../04-bugs.md#b05) 인포그래픽 표 오분류

---

### 여기까지 온 상태

`normalize`, `_is_data_table`, `leaf_blocks` 세 함수로 2MB HTML 덩어리가 문서 순서를 지키는 리프 요소 리스트가 됐다. 재무제표는 통째로 한 블록으로 살아 있고, 레이아웃 표는 안쪽 내용으로 풀렸으며, 원본 좌표는 정규화를 거쳐도 그대로다.

아직 "어느 블록이 Item 1A의 헤딩인가"는 모른다. 그건 L7의 일이다. 그 전에 판별 재료를 준비해야 한다(L4~L5).

### 블록의 끝 좌표는 다음 블록의 시작이다

시작 위치(`source_pos`)는 있는데 끝 위치가 없다. BeautifulSoup의 정규화된 트리에서 닫는 태그의 오프셋을 역산하려 하면 금방 어긋난다.

간단한 우회로가 있다. 블록이 문서 순서대로 늘어서 있으니, **한 블록의 끝은 다음 블록의 시작**이다. 마지막 블록만 파일 길이로 닫으면 된다. 아래 함수가 리스트를 뒤에서부터 훑으며 그 구간을 채운다. L7과 L8이 이 구간을 그대로 `Block`에 실어 보내고, 결국 M1.3의 청크 경계가 된다.

#### 대상 파일: `app/ingestion/parser.py`

<!-- src: app/ingestion/parser.py::block_source_spans -->
```python
def block_source_spans(
    blocks: list[Tag], offsets: list[int] | None, source_end: int | None = None
) -> list[tuple[int | None, int | None]]:
    """Return `[start, end)` source spans for an ordered block list.

    A block ends where the next block starts. The final block ends at
    `source_end` when the caller knows the original HTML length. This avoids
    trying to reconstruct closing-tag offsets from BeautifulSoup's normalized
    tree, while preserving the exact coordinate system of the source file.
    """
    if offsets is None:
        return [(None, None) for _ in blocks]

    starts = [source_pos(block, offsets) for block in blocks]
    spans: list[tuple[int | None, int | None]] = [(None, None)] * len(starts)
    next_start = source_end
    for i in range(len(starts) - 1, -1, -1):
        start = starts[i]
        spans[i] = (start, next_start)
        if start is not None:
            next_start = start
    return spans
```

---

## L4 — 속성 추출 — "이 블록은 굵은 글씨인가"

헤딩을 찾으려면 글씨가 굵은지, 크기가 얼마인지 알아야 한다. 그런데 10-K에는 `<h1>` 같은 시맨틱 태그가 없다([F1](../01-findings.md#f1)). 전부 `<div>`이고 서식은 인라인 CSS로 흩어져 있다.

그래서 이 레이어가 하는 일은 단순하다. 블록 하나를 받아 **뽑을 수 있는 서식 속성을 전부 딕셔너리로 돌려준다.**

### 여기서는 딕셔너리가 맞다

[L1](01-contracts-normalize.md#l1--자료구조가-먼저다)에서는 딕셔너리 대신 dataclass를 쓰라고 했는데 여기선 정반대다. 모순처럼 보이지만 이유가 있다.

이 딕셔너리는 **프로파일 JSON과 키 단위로 비교된다.** 프로파일에 `{"font_weight": 700}`이라고 적혀 있으면, 평가기는 `props["font_weight"]`를 꺼내 비교한다. 즉 **키 이름을 코드가 아니라 데이터가 정한다.**

그래서 나중에 `padding_top` 같은 속성을 지원하고 싶으면 고칠 곳이 한 군데다. 아래 딕셔너리에 한 줄 추가하면 끝이고, [L5](03-rules.md#l5--규칙-평가기--코드와-데이터가-만나는-유일한-지점)의 `matches_rule`은 손댈 필요가 없다. dataclass였다면 필드 선언과 추출 로직 **두 군데**를 고쳐야 하고, 그건 "규칙을 데이터로 다룬다"는 이 설계의 전제를 깬다.

정리하면 경계는 이렇다. **코드가 이름을 아는 것은 dataclass, 데이터가 이름을 정하는 것은 딕셔너리.**

> ⚠ 한 가지 오해는 짚고 가자. "그럼 프로파일 JSON에만 적으면 코드 수정 없이 동작하겠네"는 **아니다.** `block_props`가 그 키를 만들지 않으면 `matches_rule`은 `props.get(key) is None`을 보고 **제약을 조용히 건너뛴다.** 프로파일에 `padding_top`을 적어도 여기서 안 뽑으면 아무 일도 일어나지 않고, 에러도 안 난다. 이 조용함의 대가는 [L5](03-rules.md#l5--규칙-평가기--코드와-데이터가-만나는-유일한-지점)에서 다시 다룬다.

### 정규화는 최대한 아래층에서 끝낸다

CSS에서 굵은 글씨는 `font-weight: bold`로도, `font-weight: 700`으로도 쓴다. 같은 뜻인데 문자열이 다르다.

이걸 여기서 700으로 통일해두면 위층은 숫자 하나만 비교하면 된다. 반대로 위층까지 들고 가면 규칙을 쓰는 사람이 매번 "bold도 처리했나?"를 신경 써야 한다. 이런 표현 차이는 **가능한 한 아래층에서 흡수한다.**

스타일이 요소 자신이 아니라 안쪽 `<span>`에 있는 경우도 흔하다. `_inline_css`가 요소의 스타일과 안쪽 span 2개까지 합쳐서 본다.

### 왈러스 연산자를 쓸 만한 자리

코드에 `(m := re.search(...))`가 나온다. "매치 결과를 변수에 담으면서 동시에 조건으로 쓴다"는 뜻이다. 이게 없으면 앞줄에 따로 대입해야 해서 딕셔너리 리터럴 안에 넣을 수 없다. 남용하면 읽기 어려워지는 문법이지만, 이런 짧은 조건부 표현식은 적절한 자리다.

### 구현 — 시각 속성 — 헤딩처럼 보이게 만드는 것들

#### 대상 파일: `app/ingestion/parser.py`

<!-- src: app/ingestion/parser.py::_inline_css -->
```python
def _inline_css(el: Tag) -> str:
    """Combine inline CSS from this element and its first two nested spans."""
    styles: list[str] = []

    own_style = el.get("style")
    if isinstance(own_style, str):
        styles.append(own_style)

    for span in el.find_all("span", limit=2):
        span_style = span.get("style")
        if isinstance(span_style, str):
            styles.append(span_style)

    return " ".join(styles)
```

**코드에서 꼭 볼 것**

- 요소 자신의 `style`에 최대 두 개의 중첩 `span` 스타일을 합친다. SEC HTML은 굵기를 요소가 아니라 안쪽 span에 두는 일이 흔해서, 요소만 보면 헤딩을 통째로 놓친다.
- `limit=2`가 상한이다. 더 깊이 가면 무관한 자손의 스타일까지 섞여 판정이 흐려지고, 블록마다 트리 깊숙이 내려가는 비용도 붙는다.
- `isinstance(..., str)` 검사가 두 번 나온다. BeautifulSoup 속성은 문자열이라는 보장이 없어서, 이 가드가 없으면 드물게 타입 오류가 난다.

<!-- src: app/ingestion/parser.py::block_props -->
```python
def block_props(el: Tag) -> dict:
    css = _inline_css(el)  # element style plus up to two nested span styles

    def num(pattern: str) -> float:
        m = re.search(pattern, css)
        return float(m.group(1)) if m else 0.0

    mw = re.search(r"font-weight:\s*(\d+|bold)", css)
    weight = mw.group(1) if mw else "400"
    return {
        "font_weight": 700 if weight == "bold" else int(weight),
        "font_size": num(r"font-size:\s*([\d.]+)pt"),
        "margin_top": num(r"margin-top:\s*([\d.]+)pt"),
        "margin_bottom": num(r"margin-bottom:\s*([\d.]+)pt"),
        "text_align": (m.group(1) if (m := re.search(r"text-align:\s*(\w+)", css)) else ""),
        "tag": el.name,
        "in_table": el.find_parent("table") is not None,
    }
```

**코드에서 꼭 볼 것**

- `bold`를 700으로 바꾸는 한 줄이 이 함수의 핵심이다. CSS는 같은 굵기를 `bold`로도 `700`으로도 적는데, 여기서 통일해 두면 위의 모든 레이어가 숫자 하나만 비교하면 된다.
- 스타일이 없을 때의 기본값은 CSS 기본 굵기인 `400`이다. 0으로 두면 모든 블록이 규칙의 최소 임계값 아래로 떨어진다.
- 키 이름은 이 딕셔너리에만 존재한다. 프로파일 JSON이 같은 이름으로 규칙을 적고 `matches_rule`이 그 이름으로 조회하므로, 여기 없는 키는 프로파일이 지정해도 아무 일도 하지 않는다.
- `in_table`은 스타일이 아니라 위치다. 서식 속성과 구조 속성을 한 딕셔너리에 담는 것이 규칙을 단순하게 유지한다.

### 확인

```bash
uv run pytest tests/ingestion/test_02_rules.py -k "bold_keyword or missing_style or inline_css" -v
```

코퍼스 없이 돈다. `bold` → 700 정규화, 스타일이 없으면 400, span 안 스타일 도달을 각각 본다.

## 여기까지 왔을 때 설명할 수 있어야 하는 것

- **데이터 표와 레이아웃 표를 가르지 않으면 재무제표에 무슨 일이 생기는가?**
  - **답:** 데이터 표 안을 순회하면 재무제표가 셀 단위로 쪼개져 행·열 의미를 잃고, 레이아웃 표를 통째로 잡으면 그 안의 본문 헤딩이 사라진다. 둘을 나눠야 재무 표는 M1.2까지 보존하고 레이아웃 내용은 파서가 읽을 수 있다.
- **`leaf_blocks`의 조건 순서를 바꾸면 어떤 손상이 조용히 생기는가?**
  - **답:** 긴 산문 셀을 먼저 거부하지 않고 숫자 밀도가 이기게 두면 인포그래픽·레이아웃 표가 데이터 표로 오인된다. 그 표를 통째로 소비하면서 안쪽 헤딩과 문단이 조용히 사라진다.
- **블록의 끝 좌표를 다음 블록의 시작으로 잡는 근거는 무엇인가?**
  - **답:** 블록은 원문 순서대로 나오지만 BeautifulSoup이 정규화한 트리에서는 닫는 태그의 원래 오프셋을 안정적으로 복원할 수 없다. 다음 시작점을 쓰면 겹치지 않는 결정적 반열린 구간이 되고, 마지막 블록만 원문 길이로 닫으면 된다.
- **L1에서는 딕셔너리를 피하라고 했는데 `block_props`는 왜 딕셔너리인가?**
  - **답:** 여기서는 프로파일 데이터가 키 이름을 정하고 평가기가 키별로 비교한다. 딕셔너리면 새 속성을 추출해도 평가기는 바꿀 필요가 없고, 코드가 고정 필드를 소유할 때는 dataclass가 더 알맞다.
- **프로파일에 키를 적어도 `block_props`가 뽑지 않으면 어떻게 되는가?**
  - **답:** `props.get(key)`가 `None`을 반환해 평가기가 그 제약을 조용히 건너뛴다. 규칙이 아무 효과도 내지 않으므로, 프로파일 키를 허용 목록으로 검증할 필요가 있다.

---

[← 이전: 계약과 정규화](01-contracts-normalize.md) · [모듈 개요](../03-build.md) · [다음: 규칙 평가기 →](03-rules.md)
