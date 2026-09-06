# M1.2 구현 — 재무제표를 검색 가능하게 만들기

## M1.1이 미뤄둔 숙제

M1.1은 데이터 표를 만나면 이렇게 남겨뒀다.

```python
Block(kind="table", text="", html="<table>...</table>")
```

`text`가 비어 있다. HTML은 통째로 보존했지만 **검색할 수 있는 텍스트가 없다.** 지금 상태로는 "NVIDIA의 2024년 매출총이익률은?" 같은 질문에 재무제표가 절대 걸리지 않는다.

10-K에서 표는 부차적인 게 아니다. NVDA-FY2024의 Item 15 하나에만 표가 34개 있고, 매출·이익·세그먼트별 실적 같은 **가장 많이 물어볼 숫자들이 전부 표 안에** 있다. 표를 못 읽으면 이 시스템의 절반이 죽는다.

## 그냥 HTML을 넣으면 안 되나

임베딩 모델에 HTML을 그대로 넣어볼 수도 있다. 실제로 해보면 토큰 예산의 대부분이 `<td>`, `colspan`, `style="padding-left:9pt"` 같은 것에 소모된다. 정작 중요한 숫자는 그 잡음에 파묻힌다.

그래서 "HTML을 마크다운으로 변환하자"가 다음 아이디어다. 그런데 이 프레이밍이 진짜 문제를 가린다.

## SEC 표는 데이터 표가 아니라 인쇄 레이아웃이다

여기가 이 모듈의 출발점이다. 실제 손익계산서를 열어보면 논리적으로는 3열이다 — 항목명, 올해, 작년. 그런데 HTML에는 **12개 열**로 들어 있다.

```
col 0    col 1-2   col 3    col 4-5   col 6    col 7-9   col 10-11  col 12
(empty)  (label)   (empty)  ($)       (value)  (empty)   (value)    (%)
```

왜 이럴까. 이 HTML은 화면이 아니라 **종이에 인쇄될 것**을 전제로 만들어졌다. 스페이서 열이 항목을 들여쓰고, `$` 기호만 담은 열이 통화 표시를 정렬하고, 헤더는 `colspan="12"`로 전체 너비를 점유한다. CSS 없이 표만으로 인쇄 레이아웃을 잡던 시절의 방식이 규제 문서에 그대로 남아 있는 것이다.

이 HTML을 곧이곧대로 마크다운으로 바꾸면 어떻게 될까. 셀의 3분의 2가 빈 12열짜리 표가 나온다. 파이프 문자와 공백이 실제 내용 사이를 벌려놓기 때문에 **원본 HTML보다 더 나쁜** 검색 입력이 된다.

그래서 이 모듈이 실제로 하는 일은 변환이 아니라 **레이아웃 제거**다. 직렬화는 마지막 한 단계일 뿐이고, 그 앞의 다섯 레이어가 인쇄용 장식을 걷어낸다.

## 시작 조건

M1.1 전체 테스트가 통과하고 `data/corpus/manifest.json`이 20개 filing을 가리키는 상태에서 시작한다. 비어 있는 `app/ingestion/tables.py`에서 출발해 L1을 먼저 작성하고 테스트한 뒤, 같은 파일에 L2부터 L7까지 쌓는다. 문서 끝의 생성 구간은 완성본을 대조하는 부록이지 시작점이 아니다.

---

## 표 하나가 지나가는 길

M1.1이 남긴 `Block.html`은 여섯 번의 변환을 거쳐 M1.3이 임베딩하고 저장할 markdown이 된다:

```
Block.html                    raw SEC HTML with 12 physical columns
    │
    ▼
L2  to_grid()                 dense matrix — spans expanded, text at top-left only
    │                          221,730 total cells across the corpus
    ▼
L3  drop_empty()              spacer rows and columns removed
    │                          → 69,241 cells (31.2% of L2)
    ▼
L4  merge_unit_columns()      "$" and "%" folded into their values
    │                          → 66,575 cells (30.0% of L2)
    ▼
L5  split_header()            header rows inferred from shape (no <th> exists)
    │
    ▼
L6  to_markdown()             rectangular markdown with escaped pipes
    │
    ▼
L7  table_to_markdown()       public entry point — compose and fail safely
```

최종 markdown만 M1.3으로 넘어간다. 그 전까지는 전부 내부 과정이다.

아래 표는 책갈피다. 각 행의 테스트는 해당 코드가 파일에 들어간 뒤에 나온다.

| 레이어 | 책임 | 학습 행동 | 집중 테스트 |
|---|---|---|---|
| L1 | 공개 입출력 계약 | **구조 작성** | `-k "degenerate_input"` |
| L2 | span을 반영한 직사각형 격자 | 전개를 **직접 구현** | `-k "grid_is_rectangular or rowspan or colspan"` |
| L3 | 빈 행과 열 제거 | 제거 규칙을 **직접 구현** | `-k "collapse_never_widens"` |
| L4 | 통화·퍼센트 단위 병합 | 병합 방향을 **직접 구현** | `-k "unit_columns"` |
| L5 | 형태 기반 헤더 추론 | 추론을 **직접 구현** | `-k "header"` |
| L6 | 안정적인 Markdown 직렬화 | **필드 매핑 작성 후 이스케이프 검토** | `-k "income_statement or parenthesized_negatives or markdown_rows or cell_pipes"` |
| L7 | 안전하게 실패하는 공개 파이프라인 | **구조 작성 후 호출 순서 검토** | 전체 `test_09_tables.py` |

일곱 레이어 중 실제 알고리즘이 들어 있는 것은 셋뿐이다 — L2, L4, L5. 나머지는 배치이고, 그것을 더 많은 알고리즘이 아니라 배치로 읽는 것이 이 모듈을 똑같이 어려운 문제 일곱 개로 느끼지 않게 해 준다.

---

## L1 — 먼저 문이 열리게 만들기

첫 테스트가 확인하는 것은 화려한 표 변환이 아니다. 공개 함수가 `str | None`을 받고, 쓸 수 없는 입력에는 예외 대신 `""`를 돌려주는가다. 아직 격자 알고리즘이 없으므로 내용이 있는 표에는 의도적으로 `NotImplementedError`를 낸다. 이렇게 하면 미완성 구현이 조용히 빈 결과로 위장하지 않는다.

**왜 격자부터 시작하지 않는가?** 데이터 파이프라인에서 흔한 실수는 내부 변환을 전부 만든 뒤 맨 마지막에 외부 인터페이스를 연결하는 것이다. 그러면 모든 중간 함수가 최종 진입점을 통해서만 테스트되고, 진입점 자체에 문제가 있으면(잘못된 인자 타입, 빠진 null 체크, 빈 입력에서 크래시) 수백 줄을 작성한 뒤에야 알게 된다. 진입점의 계약부터 시작하면 경계가 첫 순간부터 안정된다.

새 정식 파일 `app/ingestion/tables.py`를 만들고 다음 뼈대를 작성한다.

#### `app/ingestion/tables.py` 생성 — 공개 계약 스캐폴드

```python
"""10-K financial tables -> markdown."""

from __future__ import annotations

from bs4 import BeautifulSoup, Tag

Grid = list[list[str]]

# Glyphs that SEC layout tables place in a column of their own. A column holding
# nothing but these is presentation, not data, so it is folded into its value column.
UNIT_MARKERS = frozenset({"$", "%", "€", "¥", "£"})


def table_to_markdown(html: str | None) -> str:
    """Return an empty string for unusable input while later layers are unfinished."""
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if not isinstance(table, Tag) or not table.get_text(" ", strip=True):
        return ""
    raise NotImplementedError("non-empty tables are implemented in L2-L7")
```

이제야 L1 테스트가 모듈을 import하고 실제 공개 함수를 호출할 수 있다.

```bash
uv run pytest tests/ingestion/test_09_tables.py -k "degenerate_input" -q
```

`1 passed`가 나오면 경계가 생긴 것이다. `ModuleNotFoundError`라면 파일 경로를, 잘못된 입력에서 예외가 난다면 세 조기 반환의 순서를 먼저 확인한다. 코퍼스 측정 도구는 렌더러를 모두 완성한 뒤 만든다.

**지금 갖고 있는 것:** `None`, 빈 문자열, 내용 없는 표를 크래시 없이 처리하고, 실제 표는 파이프라인을 만들 때까지 정직하게 거부하는 함수. 테스트 1개 통과, 32개 스킵. 대시보드가 가동됐다.

---

## L2 — 병합 구간을 밀집 격자로 전개

### 문제

HTML 표는 `colspan`과 `rowspan`으로 하나의 셀이 여러 격자 위치를 시각적으로 점유하게 만든다. SEC filing에서 이것이 주된 레이아웃 메커니즘이다 — 코퍼스 전체 1,200개 표에 57,617회의 `colspan`이 등장한다. 이런 조각을 생각해보자:

```html
<tr>
  <td colspan="3">Revenue</td>
  <td colspan="2">26,974</td>
  <td>$</td>
  <td colspan="3"></td>
  <td colspan="2">26,914</td>
  <td>$</td>
</tr>
```

값 세 개(항목명, 올해, 작년)가 들어있는 한 행인데 HTML은 12개 격자 위치를 부여한다.

### 함정 1 — 텍스트를 복제하면 숫자가 두 번 검색된다

span을 전개할 때 자연스러운 선택은 셀 텍스트를 점유하는 모든 위치에 복사하는 것이다. 셀이 3열에 걸치면 세 곳 다 채우는 게 맞아 보인다.

그런데 SEC 표에서는 **값이 span을 갖는다.** 레이블이 아니라. 위 예시를 다시 보면 숫자 `26,974`가 `colspan="2"`를 달고 있다.

복사하면 어떻게 될까. 격자에 `26,974`가 두 번 들어가고, 마크다운에도 두 번 나오고, 검색 인덱스에도 두 번 들어간다. 사용자가 그 숫자를 검색하면 **같은 위치를 가리키는 결과가 두 건** 나온다. 중복 제거로도 못 잡는다. 진짜 다른 청크니까.

그래서 **왼쪽 위에만 텍스트를 두고 나머지 점유 위치는 빈 문자열로 채운다.** 시각적 점유는 재현하되 내용은 한 번만 존재하게 한다.

### 함정 2 — 행마다 너비가 다르다

1,200개 표 중 80개는 행마다 선언한 너비가 다르다. 헤더는 `colspan`으로 12열을 선언하는데 데이터 행은 10열만 선언하는 식이다. HTML 렌더러는 알아서 채워주지만 우리 격자는 그렇지 않다.

모든 행이 같은 너비라고 가정하고 짜면 나중에 L3의 `drop_empty`에서 열에 접근할 때 `IndexError`가 난다. 그것도 전체의 6%에서만 나는 버그라 처음엔 안 보인다.

해법은 **모든 행에서 도달한 가장 먼 좌표를 기억했다가 마지막에 전부 그 너비로 맞추는 것**이다. 아래 코드의 `filled` 딕셔너리 방식을 쓰면 이게 공짜로 따라온다. 별도의 ragged-table 처리 코드가 필요 없다.

### 코드

이제 임시 진입점 바로 위에 격자 코드를 정의한다.

#### 대상 파일: `app/ingestion/tables.py`

<!-- src: app/ingestion/tables.py::_span,to_grid -->
```python
def _span(cell: Tag, name: str) -> int:
    """`colspan`/`rowspan` as a positive int. Filings do emit junk values."""
    try:
        return max(1, int(str(cell.get(name, 1)).strip() or 1))
    except TypeError, ValueError:
        return 1


# ── L2. Grid ────────────────────────────────────────────────────────────────


def to_grid(table: Tag) -> Grid:
    """Expand a `<table>` into a dense matrix, resolving colspan and rowspan.

    A spanned cell keeps its text in the top-left position only; the covered
    positions become empty strings. Replicating the text instead would duplicate
    every number in the corpus, since values are what carry `colspan` here.

    Ragged tables (80 of 1,200) fall out for free: the matrix is sized from
    the furthest cell reached and short rows are padded.
    """
    filled: dict[tuple[int, int], str] = {}
    for r, tr in enumerate(table.find_all("tr")):
        col = 0
        for cell in tr.find_all(["td", "th"]):
            while (r, col) in filled:  # skip positions already taken by a rowspan
                col += 1
            text = cell.get_text(" ", strip=True)
            cspan, rspan = _span(cell, "colspan"), _span(cell, "rowspan")
            for dr in range(rspan):
                for dc in range(cspan):
                    filled[(r + dr, col + dc)] = text if dr == 0 and dc == 0 else ""
            col += cspan
    if not filled:
        return []
    height = max(r for r, _ in filled) + 1
    width = max(c for _, c in filled) + 1
    return [[filled.get((r, c), "") for c in range(width)] for r in range(height)]
```

### 알고리즘이 작동하는 방식, 단계별로

`filled` 딕셔너리는 `(row, column)` 좌표를 셀 텍스트에 대응시킨다. 각 `<tr>`과 그 안의 `<td>/<th>`를 순회한다:

1. **점유된 위치를 건너뛴다.** `while (r, col) in filled` 반복문은 이전 행의 `rowspan`이 이미 차지한 위치를 지나 `col`을 전진시킨다. 이것 없이는 2행짜리 `rowspan`이 아래 셀을 덮어쓴다.

2. **왼쪽 위에만 텍스트를 놓는다.** 중첩된 `for dr / for dc` 루프가 span이 점유하는 모든 위치를 채운다. `text if dr == 0 and dc == 0 else ""` 조건이 셀 텍스트가 한 번만 나타나게 보장한다.

3. **span을 지나서 전진한다.** 채운 뒤 `col += cspan`이 이 행의 열 커서를 다음 빈 위치로 옮긴다.

4. **직사각형 격자를 만든다.** 모든 행을 처리한 뒤 `filled`의 최대 좌표에서 `height`와 `width`를 결정한다. 최종 리스트 컴프리헨션에서 `filled.get((r, c), "")`가 빈 위치까지 채운 밀집 행렬을 만든다.

### 왜 2차원 리스트가 아니라 딕셔너리인가

격자를 만드는 코드니 `[[""] * width for _ in range(height)]`로 미리 할당하는 게 자연스러워 보인다. 그런데 그러려면 **시작할 때 최종 차원을 알아야 한다.**

앞의 함정 2 때문에 그걸 모른다. 행마다 선언 너비가 다르니 최대 너비를 구하려면 전체를 한 번 훑는 사전 순회가 필요하다. 코드가 두 배가 된다.

딕셔너리는 이 문제가 없다. 좌표를 키로 쓰니 크기를 미리 정할 필요가 없고, 삽입과 "이 자리 이미 찼나" 확인을 같은 자료구조로 처리한다. 차원은 마지막에 `max(...)`로 자연스럽게 나온다.

**미리 크기를 알 수 없는 희소한 좌표 공간을 채울 때는 딕셔너리로 모으고 마지막에 밀집 구조로 바꾸는 패턴**이 대체로 깔끔하다.

### 실행

```bash
uv run pytest tests/ingestion/test_09_tables.py -k "grid_is_rectangular or rowspan or colspan" -q
```

모든 선택 테스트가 통과하면 ragged HTML도 직사각형이 됐고 span 텍스트도 한 번만 남은 것이다. 실패하면 가장 작은 표의 `(row, column)` 점유 지도를 보고, `rowspan`이 먼저 차지한 좌표를 건너뛰는 반복문부터 확인한다.

**지금 갖고 있는 것:** 테스트 4개 통과. 코퍼스의 모든 표가 각 값이 정확히 한 번만 나타나는 밀집 직사각형 행렬이 됐다.

---

## L3 — 빈 행·열 제거

### 문제를 눈으로 보기

L2 이후 NVDA-FY2024 손익계산서 격자는 이렇다 (단순화):

```
col:  0    1    2    3         4       5    6    7    8         9       10   11
r0:  [ ]  [ ]  [ ]  [ ]      [ ]     [ ]  [ ]  [ ]  [ ]      [ ]     [ ]  [ ]    ← pure spacer
r1:  [ ]  [ ]  [ ]  [Year Ended...]  [ ]  [ ]  [ ]  [ ]      [ ]     [ ]  [ ]
r2:  [ ]  [ ]  [ ]  [Jan 28, 2024]   [ ]  [ ]  [ ]  [ ]      [Jan 29, 2023]  [ ]
r3:  [Revenue ][ ]  [ ]  [100.0]     [ ]  [%]  [ ]  [ ]      [100.0] [ ]  [%]
```

열 0, 1, 2, 6, 7, 10은 모든 행에서 비어있다. 행 0은 모든 열에서 비어있다. filing이 `colspan`으로 텍스트를 시각적으로 배치하려고 만든 빈 구조물이다.

L3 이후:

```
col:  0          1              2    3              4
r1:  [ ]        [Year Ended..] [ ]  [ ]            [ ]
r2:  [ ]        [Jan 28, 2024] [ ]  [Jan 29, 2023] [ ]
r3:  [Revenue]  [100.0]        [%]  [100.0]        [%]
```

스페이서 행이 사라졌다. 빈 열 6개가 사라졌다. 격자가 12열에서 5열로 줄었고, 데이터가 이제 레이블 바로 옆에 있다.

### 왜 완전히 빈 축만 지우는가

한 셀이라도 내용이 있는 열은 증거일 수 있다. 행 3에 `%`가 있고 행 1-2에서는 빈 열도 어딘가에 내용이 있으므로 살아남는다. 부분적으로 빈 축을 지우면 데이터가 조용히 사라진다. **규칙: 격자 전체에서 모든 셀이 비어있는 축만 제거한다.**

### 코드

`to_grid()` 다음에 L3 구분선과 함수를 차례로 추가한다.

#### `app/ingestion/tables.py` 확장 — 빈 축 제거

```python
# ── L3. Collapse ────────────────────────────────────────────────────────────
```

<!-- src: app/ingestion/tables.py::drop_empty -->
```python
def drop_empty(grid: Grid) -> Grid:
    """Drop rows and columns that hold no text anywhere.

    This is the step that does the real work: spacer rows, spacer columns and the
    indentation columns used for line-item nesting all disappear. Measured on this
    corpus the column count falls from p50=12 / max=66 to p50=5 / max=25, and 26
    tables turn out to be pure layout with no content at all.
    """
    rows = [r for r in grid if any(c.strip() for c in r)]
    if not rows:
        return []
    keep = [j for j in range(len(rows[0])) if any(r[j].strip() for r in rows)]
    return [[r[j] for j in keep] for r in rows]
```

**왜 `.strip()`인가?** 일부 셀에는 공백 문자(`&nbsp;`, 탭)가 있어서 비어 보이지만 빈 문자열은 아니다. `.strip()` 없이는 `"  "`만 들어있는 셀이 열을 살려놓고, 사라져야 할 열이 남아서 골든 셀 수와 맞지 않게 된다.

**왜 예외 대신 `[]`를 반환하는가?** 코퍼스에서 빈 축을 모두 제거한 뒤 내용이 전혀 없는 표가 26개 있다 — 순수 레이아웃 스페이서다. 빈 격자를 반환하면 호출자가 결정할 수 있고 (L7 진입점은 `""`를 반환한다), 예외를 던지면 호출자가 매번 잡아야 한다.

### 확인

아직 다음 레이어의 `merge_unit_columns()`가 없으므로 결합 테스트를 성급히 실행하지 않는다. 대신 작은 격자로 이번 함수만 바로 확인한다.

```bash
uv run python -c "from app.ingestion.tables import drop_empty; assert drop_empty([['', '', ''], ['Revenue', '', '1']]) == [['Revenue', '1']]"
```

이 명령이 조용히 끝나면 빈 축만 사라졌다. 값이 없어졌다면 `keep`과 원래 열을 나란히 놓고 어느 인덱스가 빠졌는지 본다.

**지금 갖고 있는 것:** 여전히 테스트 4개 통과 (L3만으로는 새 테스트가 켜지지 않는다 — 축약 테스트는 L4가 필요하다). 하지만 함수는 수동 점검 가능하다.

---

## L4 — 단위 전용 열 병합

### 문제

L3 이후에도 `$`나 `%`를 표시하기 위해서만 존재하는 열이 남는다. 코퍼스에서 빈 축을 제거한 뒤 279개의 이런 열이 살아남는다. 독립적 의미가 없다 — `$`는 값이 아니라 옆 숫자에 붙는 표현 장식이다. 별도 열로 두면 markdown에 `| $ | 26,974 |`가 나오고, `| $ 26,974 |` 대신 고립된 기호에 검색 토큰이 낭비된다.

### 설계 선택: 방향은 읽는 순서를 따른다

통화 기호는 값 **앞에** 읽힌다: `$ 26,974`. 퍼센트 기호는 값 **뒤에** 읽힌다: `72.7 %`. 따라서 `$`는 오른쪽 열과 합치고 (`target = j + 1`), `%`는 왼쪽 열과 합친다 (`target = j - 1`). 방향을 거꾸로 하면 `26,974 $`나 `% 72.7`이 되어 의미가 깨진다.

### 단위 열을 식별하는 법

열 안의 **비어있지 않은 모든 셀**이 `UNIT_MARKERS` (`$`, `%`, `€`, `¥`, `£`)에 속할 때만 단위 열이다. 셀 하나라도 다른 내용(숫자, 레이블, 공백만)을 담고 있으면 단위 열이 아니다. 이 보수적 규칙은 헤더에 우연히 `$`가 있고 아래에 실제 데이터가 있는 열을 합치는 것을 막는다.

### 코드

먼저 L4 구분선을 작성하고 그 아래에 함수를 정의한다.

#### `app/ingestion/tables.py` 확장 — 단위 열 병합

```python
# ── L4. Units ───────────────────────────────────────────────────────────────
```

<!-- src: app/ingestion/tables.py::merge_unit_columns -->
```python
def merge_unit_columns(grid: Grid) -> Grid:
    """Fold columns holding only a currency or percent glyph into their value.

    Direction follows how the glyph reads: `$` precedes its number, `%` follows it.
    Without this the corpus leaves 279 columns of bare symbols after collapsing.
    """
    if not grid:
        return grid
    width = len(grid[0])
    cols = [[row[j] for row in grid] for j in range(width)]

    dropped: set[int] = set()
    for j in range(width):
        values = [c.strip() for c in cols[j] if c.strip()]
        if not values or not all(v in UNIT_MARKERS for v in values):
            continue
        trailing = all(v == "%" for v in values)
        target = j - 1 if trailing else j + 1
        if not 0 <= target < width or target in dropped:
            continue
        for i, glyph in enumerate(cols[j]):
            if not glyph.strip():
                continue
            value = cols[target][i]
            cols[target][i] = f"{value} {glyph}".strip() if trailing else f"{glyph} {value}".strip()
        dropped.add(j)

    keep = [j for j in range(width) if j not in dropped]
    return [[cols[j][i] for j in keep] for i in range(len(grid))]
```

### 알고리즘을 따라가기

1. **격자를 열 단위로 전치한다.** `cols[j]`는 열 `j`의 모든 값 리스트다. 이 전치 덕에 중첩된 행/열 루프 없이 각 열을 독립적으로 조사할 수 있다.

2. **단위 열을 식별한다.** 비어있지 않은 셀을 모은다. 전부 unit marker이면 단위 열이다.

3. **방향을 결정한다.** 모든 marker가 `%`이면 후행(왼쪽으로 합침). 나머지 unit marker는 전부 선행(오른쪽으로 합침). `$`와 `€`는 값 앞에, `%`는 값 뒤에 오는 일반적 경우를 처리한다.

4. **경계를 검사한다.** 대상 열이 범위 밖이거나 이미 drop됐으면(다른 단위 열이 먼저 합쳐졌으면) 건너뛴다. `target in dropped` 없이는 인접한 두 단위 열이 체이닝돼서 두 번째가 이미 사라진 첫 번째에 합치려 한다.

5. **셀 단위로 합친다.** 각 행에서 glyph를 대상 셀의 값 앞이나 뒤에 붙인다. `.strip()`은 대상 셀이 비어있는 경우를 처리한다 — `f"$ {value}".strip()`은 `"$"`를 만들고 `"$ "`를 만들지 않는다.

6. **합친 열을 제거한다.** 최종 리스트 컴프리헨션이 drop된 열 없이 격자를 다시 만든다. `cols[j][i]` (열 우선)를 읽고 행 우선으로 다시 전치한다.

### 실행

```bash
uv run pytest tests/ingestion/test_09_tables.py -k "collapse_never_widens or unit_columns" -q
```

선택 테스트가 통과하면 축약 결과는 넓어지지 않고 `$`와 `%`도 읽는 순서를 지킨다. 실패한 첫 열의 `values`, `trailing`, `target`을 출력하면 잘못 고른 이웃을 바로 찾을 수 있다.

**지금 갖고 있는 것:** 테스트 6개 통과. 격자가 221,730셀에서 66,575셀로 줄었다 (원본의 30.0%). HTML 표에 들어있던 것의 70%가 데이터가 아니라 레이아웃이었다.

---

## L5 — 헤더 형태 추론

### 설계를 통째로 바꾼 측정 결과 하나

마크다운 표에는 헤더 행이 필요하다. HTML에서 헤더는 `<th>` 태그니까 그걸 찾으면 되겠다 — 라고 생각하고 코퍼스를 재봤다.

**`<th>`가 하나도 없다.** 적은 게 아니라 1,200개 표 전체에서 정확히 0개다.

앞에서 말했듯 이 HTML은 인쇄 레이아웃이다. 시각적으로 굵게 만들면 헤더처럼 보이니 시맨틱 태그를 쓸 이유가 없었던 것이다. M1.1에서 `<h1>`이 없었던 것과 같은 이야기다.

이 사실 하나가 L5 전체를 결정한다. `<th>` 기반 접근은 여기서 영원히 0개를 반환한다. 그래서 아예 다른 신호를 찾아야 한다.

이건 중요한 전제라 테스트로 못 박아뒀다. `test_header_is_inferred_from_shape_not_from_th`가 모든 문서에서 `soup.find("th") is None`을 검증한다. **설계의 전제가 되는 측정값은 테스트로 고정해두는 게 좋다.** 나중에 `<th>`가 있는 문서가 코퍼스에 들어오면 그 테스트가 먼저 알려준다.

### 형태 기반 추론

시맨틱 태그 없이 남은 유일한 신호는 **데이터의 형태**다. SEC 재무 표에서 일관된 패턴이 나타난다:

- **헤더 행**은 값 열에 레이블을 달지만("Year Ended", "Jan 28, 2024") 첫 번째 열(항목명 열)은 비워둔다. 헤더가 설명하는 것은 **값**이지 **항목명**이 아니기 때문이다.
- **데이터 행**은 항상 첫 열에 항목명으로 시작한다 ("Revenue", "Cost of revenue").

이것이 깔끔한 규칙을 준다: **열 0이 비어있고 다른 열에 텍스트가 있는 선두 행을 모은다.** 열 0이 비어있지 않은 첫 행에서 멈춘다 — 그것이 첫 데이터 행이다.

### 여러 행 헤더는?

많은 SEC 표에는 2행, 때로는 3행 헤더가 있다. "Year Ended"가 행 1에서 전체 너비에 걸치고, "Jan 28, 2024"와 "Jan 29, 2023"이 행 2의 해당 값 열 아래에 나타난다. 두 행 모두 첫 열이 비어있고 값 열에 텍스트가 있으므로 형태 규칙이 자연스럽게 두 행을 모두 수집한다. L6에서 이것을 열별로 합쳐 `"Year Ended Jan 28, 2024"`라는 하나의 헤더 셀로 만든다 — 숫자가 어느 기간에 속하는지가 chunk 텍스트에 남는다.

### 아무것도 매치되지 않을 때

첫 행의 열 0에 이미 내용이 있거나, 열 0 밖에 내용이 있는 행이 없으면 규칙이 아무것도 찾지 못한다. 이 경우 `split_header`는 `([], grid)` — 빈 헤더와 격자 전체를 body로 — 반환한다. **헤더를 만들어내지 않는다.** 호출자(L6)가 첫 body 행을 markdown 헤더 위치로 승격시키는 폴백을 처리한다. 이렇게 하면 표가 유효한 markdown으로 남는다.

### 코드

L5 구분선 다음에 헤더 함수를 정의한다.

#### `app/ingestion/tables.py` 확장 — 헤더 분리

```python
# ── L5. Header ──────────────────────────────────────────────────────────────
```

<!-- src: app/ingestion/tables.py::split_header -->
```python
def split_header(grid: Grid) -> tuple[Grid, Grid]:
    """Split leading header rows from the body.

    There is no `<th>` in this corpus, so the header has to be inferred from shape:
    a header row labels the value columns and leaves the label column blank, while
    every data row starts with its line-item name. Leading rows matching that shape
    are the header.

    Returns `([], grid)` when nothing matches, so the caller decides the fallback.
    """
    n = 0
    for row in grid:
        if row[0].strip() or not any(c.strip() for c in row[1:]):
            break
        n += 1
    if n == 0 or n == len(grid):
        return [], grid
    return grid[:n], grid[n:]
```

### 엣지 케이스: `n == len(grid)`

격자의 모든 행에서 첫 열이 비어있으면 루프가 전체 격자를 헤더로 소비하고 body는 없게 된다. 기술적으로 맞는 markdown이 나오지만 쓸모가 없다 — 헤더와 구분선만 있고 데이터 행이 없다. `n == len(grid)` 검사는 대신 전부를 body로 반환해서 이것을 방지한다.

### 실행

```bash
uv run pytest tests/ingestion/test_09_tables.py -k "header" -q
```

선택 테스트는 헤더가 있을 때와 없을 때를 모두 확인한다. 본문까지 헤더로 먹었다면 추론이 멈춰야 했던 첫 행의 첫 열과 값 셀을 확인한다.

**지금 갖고 있는 것:** 테스트 8개 통과. 격자가 헤더와 body로 분리됐고, 여러 행 헤더도 합칠 준비가 됐다.

---

## L6 — 마크다운 직렬화

### 이 레이어가 하는 것과 하지 않는 것

L6는 논리 격자를 markdown 문법으로 번역한다. 값을 바꾸거나 행을 제거하거나 열을 재배열하지 않는다. 구조적 작업은 전부 L2~L5에서 끝났다. 이 레이어는 의도적으로 얇다.

두 가지에 주의해야 한다:

1. **여러 행 헤더를 합쳐야 한다.** 행 1에 "Year Ended"가 있고 행 2에 "Jan 28, 2024"가 있는 2행 헤더는 하나의 헤더 셀 `"Year Ended Jan 28, 2024"`가 돼야 한다. 열별로 처리한다 — 해당 열 위치에서 각 헤더 행의 비어있지 않은 값을 합친다.

2. **셀 안의 파이프를 이스케이프해야 한다.** `|` 문자는 markdown 열 구분자다. `a|b`가 들어있는 셀이 `| a|b |`를 만들면 렌더러는 하나가 아니라 세 열로 해석한다. `a\|b`로 이스케이프하면 셀 경계가 보존된다.

### 코드

아래 두 함수를 `split_header()` 다음에 L6 구분선과 함께 추가한다.

#### `app/ingestion/tables.py` 확장 — Markdown 직렬화

```python
# ── L6. Serialize ───────────────────────────────────────────────────────────
```

<!-- src: app/ingestion/tables.py::_cell,to_markdown -->
```python
def _cell(text: str) -> str:
    """Make a cell safe for a markdown table row."""
    return " ".join(text.replace("|", "\\|").split())


def to_markdown(grid: Grid) -> str:
    """Serialize a collapsed grid as a markdown table.

    Multi-row headers ("Year Ended" over "Jan 28, 2024") are joined per column, so
    the period a number belongs to survives into the chunk text.
    """
    if not grid:
        return ""
    header, body = split_header(grid)
    if header:
        head = [" ".join(row[j] for row in header if row[j].strip()) for j in range(len(grid[0]))]
    else:  # no header shape: promote the first row so the table stays valid markdown
        head, body = body[0], body[1:]

    lines = [
        "| " + " | ".join(_cell(c) for c in head) + " |",
        "| " + " | ".join("---" for _ in head) + " |",
    ]
    lines += ["| " + " | ".join(_cell(c) for c in row) + " |" for row in body]
    return "\n".join(lines)
```

### 왜 `_cell`이 내부 공백도 정리하는가

`" ".join(text.split())` 호출은 내부 공백을 정규화한다. SEC 표 셀에는 iXBRL 렌더링에서 남은 `\n`이나 여러 공백이 들어있기도 하다. 여기서 정규화하면 markdown 행이 균일해지고, 여러 줄 셀 내용이 표 구조를 깨는 것을 막는다.

### 폴백: 헤더를 찾지 못한 경우

`split_header`가 `([], grid)`를 반환하면 직렬화기가 첫 body 행을 헤더 위치로 승격시킨다: `head, body = body[0], body[1:]`. 실용적 선택이다 — markdown 표는 헤더 행 다음에 구분 행이 필수다. 헤더 없이는 표가 렌더링되지 않는다. 첫 행을 승격시키면 데이터 행 하나를 잃지만 출력이 유효한 상태로 남는다.

### 확인

공개 진입점은 아직 임시 함수이므로 직렬화기를 직접 확인한다.

```bash
uv run python -c "from app.ingestion.tables import to_markdown; md = to_markdown([['', '2024'], ['Revenue', 'a|b']]); assert '| Revenue | a\\|b |' in md"
```

명령이 조용히 끝나면 행 너비와 셀 경계가 보존됐다. 다르면 문자열 결합보다 먼저 추론된 `head`와 첫 본문 행을 확인한다.

**지금 갖고 있는 것:** 여전히 테스트 8개 통과 (직렬화 테스트는 전부 `table_to_markdown`을 거치는데 아직 L1 스텁이다). 하지만 직렬화기는 준비됐다.

---

## L7 — 안전하게 실패하는 진입점

### 파이프라인 연결

마지막으로 L1의 임시 `table_to_markdown()`을 실제 구현으로 교체한다. 이 함수는 HTML을 파싱하고 다섯 변환 — `to_grid()`, `drop_empty()`, `merge_unit_columns()`, `to_markdown()` — 을 한 줄로 연결한다.

호출자(M1.3의 chunker)는 이 진입점만 알면 된다. `Block.html`을 넘기면 markdown 문자열을, 내용이 없으면 빈 문자열을 받는다.

### 괄호 음수 결정

SEC filing은 음수를 괄호로 표현한다: `(1,234)`는 마이너스 1,234다. ingestion 시 `-1234`로 변환하면 숫자 검색이 쉬워질 것 같다.

**이 모듈은 그렇게 하지 않는다.** 세 가지 이유:

1. **인용은 원문과 일치해야 한다.** 검색 시스템이 사용자에게 "매출은 (1,234)"라고 보여주며 filing을 인용할 때, filing에 실제로 `(1,234)`가 적혀있어야 한다. `-1234`로 변환하면 인용 계약이 깨진다.

2. **ingestion 시점의 정규화는 되돌릴 수 없다.** `-1234`를 데이터베이스에 쓰면 `(1,234)`를 복원할 수 없다. 쿼리 시점의 정규화(검색 시 `(1,234)`를 확장)는 되돌릴 수 있다.

3. **위험을 안전한 쪽에 집중한다.** 이 결정이 잘못된 것으로 드러나면 쿼리 레이어를 고치면 된다. ingestion 쪽의 실수는 모든 문서를 다시 처리해야 한다.

### 코드

#### `app/ingestion/tables.py` 확장 — 공개 진입점

```python
# ── L7. Entry point ─────────────────────────────────────────────────────────
```

<!-- src: app/ingestion/tables.py::table_to_markdown -->
```python
def table_to_markdown(html: str | None) -> str:
    """`Block(kind="table").html` -> markdown. Empty string when there is no content.

    Numbers are passed through verbatim: `(1,234)` stays parenthesized rather than
    becoming `-1234`. The citation has to match what a reader sees in the filing,
    and normalizing here would be irreversible; query-side normalization is not.
    """
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if not isinstance(table, Tag):
        return ""
    grid = drop_empty(to_grid(table))
    if not grid:
        return ""
    return to_markdown(merge_unit_columns(grid))
```

### 왜 `drop_empty`가 `merge_unit_columns`보다 먼저인가

순서가 중요하다. `drop_empty`는 완전히 빈 열을 제거한다. `merge_unit_columns`는 단위 열을 이웃에 합친다. 순서를 뒤집으면 `merge_unit_columns`가 아직 빈 스페이서 열로 어지러운 격자에서 `$` 열을 찾으려 하고, 이웃 감지(`target = j + 1`)가 값 열 대신 스페이서를 가리킬 수 있다.

### 실행

```bash
uv run pytest tests/ingestion/test_09_tables.py -q
```

**테스트 25개가 한꺼번에 켜지는 순간이다.** 진입점이 모든 변환을 연결하고, `table_to_markdown`을 기다리던 모든 코퍼스 수준 테스트가 실행된다.

전체 파일이 통과하고 필수 심벌 누락 skip이 없어야 한다. 실패 하나만 `-vv`로 다시 실행해 `Grid`가 처음 달라지는 도우미를 찾는다. 이 게이트가 녹색이 되기 전에는 M1.3으로 넘어가지 않는다.

### 결과의 모습

12열 HTML로 도착했고 63.6%가 빈 셀이었던 NVDA-FY2024 비율 손익계산서가 이제 이렇다:

```
|  | Year Ended Jan 28, 2024 | Jan 29, 2023 |
| --- | --- | --- |
| Revenue | 100.0 % | 100.0 % |
| Cost of revenue | 27.3 | 43.1 |
| Gross profit | 72.7 | 56.9 |
| Operating expenses |  |  |
| Research and development | 14.2 | 27.2 |
| Total operating expenses | 18.6 | 41.3 |
| Operating income | 54.1 | 15.6 |
| Interest expense | (0.4) | (1.0) |
| Net income | 48.9 % | 16.2 % |
```

3열. 스페이서 없음. 헤더 합쳐짐. 괄호 음수 보존. 검색 가능하고, 임베딩 가능하고, 원문에 충실하다.

`Year Ended Jan 28, 2024`가 한 셀에 합쳐진 게 특히 중요하다. 이제 이 표에서 `Gross profit`을 검색하면 그 숫자가 **어느 회계연도의 것인지**가 같은 청크 안에 있다. 헤더를 버렸다면 "72.7"이라는 숫자만 남고, 어느 해 것인지 모르는 답이 나왔을 것이다.

### 여기까지 왔을 때 설명할 수 있어야 하는 것

- **span된 텍스트를 덮인 셀마다 복제하면 왜 검색이 망가지는가?**
  - **답:** SEC 표에서는 값 자체에 `colspan`이 자주 붙는다. 표 하나가 청크 하나가 되므로 텍스트를 복제해도 별도 검색 결과가 생기지는 않지만, `index_text` 안에서 같은 사실이 반복되어 해당 토큰의 비중이 커지고 어휘·임베딩 순위가 왜곡될 수 있다. 값은 왼쪽 위 좌표에만 둔다.
- **2차원 리스트 대신 좌표를 키로 쓰는 딕셔너리를 쓰는 이유는 무엇인가?**
  - **답:** rowspan과 들쭉날쭉한 행 때문에 모든 셀을 놓기 전에는 최종 너비와 높이를 알 수 없다. 좌표 딕셔너리는 한 번의 순회로 점유 여부와 확장을 함께 처리하고, 마지막에 패딩된 조밀한 그리드로 바꿀 수 있다.
- **완전히 비었을 때만 제거하는 축은 무엇이고, 그게 무엇을 지키는가?**
  - **답:** 행과 열 모두 그 축의 모든 셀이 비었을 때만 제거한다. 값이나 단위 기호가 하나라도 있는 축을 남겨 두어 증거가 조용히 삭제되는 일을 막는다.
- **단위 열이 반대 방향이 아니라 읽는 순서로 병합되는 이유는 무엇인가?**
  - **답:** 통화 기호는 값 앞에 오므로 오른쪽으로, 퍼센트 기호는 값 뒤에 오므로 왼쪽으로 합친다. 방향을 바꾸면 `26,974 $`나 `% 72.7`처럼 데이터의 읽는 의미가 달라진다.
- **측정이 헤더 설계에서 무엇을 바꿔 놓았는가?**
  - **답:** 코퍼스에 `<th>`가 하나도 없어 시맨틱 태그 기반 판별은 영원히 실패한다는 사실이 확인됐다. 그래서 첫 열은 비고 값 열은 채워진 선두 행이라는 형태로 헤더를 추론한다.
- **`drop_empty`가 `merge_unit_columns`보다 먼저 돌아야 하는 이유는 무엇인가?**
  - **답:** 단위 병합은 바로 옆 열을 대상으로 삼는다. 빈 스페이서 열을 먼저 지워야 그 이웃이 레이아웃용 공백이 아니라 실제 숫자 열이 된다.

---

## 이 모듈이 다음 모듈에 넘기는 것

M1.2는 다른 모듈과 거의 엮이지 않는다. **HTML 문자열을 받아 마크다운 문자열을 돌려주는 순수 함수** 하나가 전부다.

이게 의도된 설계다. 모듈 docstring에도 적혀 있듯, 이 코드는 `Block`을 건드리지 않는다. M1.1 파서는 표 블록을 `Block("table", "", html=...)`로 남겨두기만 하고, **M1.3 청커가 텍스트가 필요해지는 시점에** `table_to_markdown`을 호출한다.

이렇게 분리하면 두 가지 이득이 있다.

- **표 렌더링이 파서의 커버리지 지표를 흔들 수 없다.** 파서 검증과 표 변환이 독립적으로 실패한다.
- **파서가 마크다운을 모른다.** 나중에 표를 JSON이나 다른 형식으로 내보내고 싶어져도 파서는 그대로다.

다음 장 M1.3은 M1.1의 블록 리스트와 이 함수를 함께 써서, 인용 가능한 청크를 만든다. 텍스트 블록은 문단 단위로 묶고, 표 블록은 여기서 만든 마크다운을 통째로 하나의 청크로 만든다. **표를 쪼개면 인용이 거짓이 되기 때문**인데, 그 이야기는 다음 장에서 한다.

---

## 구현 파일을 완성하는 두 가지 도구

핵심 파이프라인은 끝났지만 완성 파일에는 설계 의도를 기록한 모듈 설명과 사람이 결과를 읽을 CLI도 있다. 먼저 `app/ingestion/tables.py` 맨 위의 짧은 한 줄 docstring을 다음 설명으로 교체한다.

#### `app/ingestion/tables.py` 수정 — 모듈 설명

```python
"""10-K financial tables -> markdown.

**The problem is not serialization, it is layout.** SEC filings render tables for
print, not for data: across this corpus's 1,200 table blocks, the median table has
63.6% empty raw cells, `<th>` never appears, and `colspan` is used 57,617 times
purely to position text. A three-column income statement ships as twelve physical
columns of label / value / unit / spacer.

Converting that HTML straight to markdown produces a wide, mostly-empty grid that is
worse for retrieval than the raw text. So the pipeline collapses layout first and
serializes last:

    L2 to_grid              colspan/rowspan -> dense matrix
    L3 drop_empty           remove all-empty rows and columns   (12 -> 5 cols, p50)
    L4 merge_unit_columns   fold '$'/'%'-only columns into their value
    L5 split_header         infer header rows (there is no <th> to read)
    L6 to_markdown          serialize

This module is a pure function over HTML. It does not touch `Block`: the parser
leaves table blocks as `Block("table", "", html=...)` and the chunker (M1.3) calls
`table_to_markdown` when it needs text. Keeping it out of the parser means table
rendering cannot shift the coverage metric, and the parser stays unaware of markdown.

For education/practice purposes, this is implemented directly with BeautifulSoup
instead of a converter library, to keep the collapse rules inspectable.
"""

```

그다음 `app/ingestion/tables.py` 끝에 눈으로 결과를 볼 CLI를 작성한다.

#### `app/ingestion/tables.py` 확장 — 검사 CLI

```python
if __name__ == "__main__":  # pragma: no cover - eyeball helper
    import argparse
    import json
    from pathlib import Path

    from app.ingestion.parser import leaf_blocks, normalize, read_source

    ap = argparse.ArgumentParser(description="Render 10-K tables as markdown.")
    ap.add_argument("--doc", default="NVDA-FY2024", help="doc_id, e.g. NVDA-FY2024")
    ap.add_argument("--contains", default="Gross profit", help="pick tables containing this text")
    ap.add_argument("--limit", type=int, default=2)
    a = ap.parse_args()

    manifest = json.loads(Path("data/corpus/manifest.json").read_text())
    entry = next(e for e in manifest if f"{e['ticker']}-FY{e['report_date'][:4]}" == a.doc)
    soup = normalize(read_source(entry["file"]))
    shown = 0
    for el in leaf_blocks(soup):
        if el.name != "table" or a.contains not in el.get_text(" ", strip=True):
            continue
        print(f"\n{'─' * 70}\n{a.doc}\n{'─' * 70}")
        print(table_to_markdown(str(el)))
        shown += 1
        if shown >= a.limit:
            break
    if not shown:
        print(f"no table in {a.doc} contains {a.contains!r}")
```

마지막으로 정식 경로 `scripts/measure_tables.py`에 측정 도구를 작성한다. 이 도구는 구현을 생성하지 않고 현재 코퍼스의 골든 측정값을 다시 계산한다.

#### `scripts/measure_tables.py` 생성 — 코퍼스 측정 도구

```python
#!/usr/bin/env python3
"""Regenerate the M1.2 corpus measurements and per-document golden tuples."""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import re
from statistics import median

from bs4 import Tag

from app.ingestion.parser import leaf_blocks, normalize, read_source
from app.ingestion.tables import drop_empty, merge_unit_columns, table_to_markdown, to_grid

REPO = Path(__file__).resolve().parent.parent
PAREN_NUMBER = re.compile(r"^\(\s*[\d,.]+\s*\)$")


def _span(cell: Tag, name: str) -> int:
    try:
        return max(1, int(str(cell.get(name, 1)).strip() or 1))
    except TypeError, ValueError:
        return 1


def _percentile(values: list[int], fraction: float) -> int:
    """Return a deterministic nearest-rank percentile for a non-empty list."""
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round((len(ordered) - 1) * fraction)))
    return ordered[index]


def _expanded_row_widths(table: Tag) -> list[int]:
    """Return declared row widths after colspan but before rectangular padding."""
    return [
        sum(_span(cell, "colspan") for cell in row.find_all(["td", "th"]))
        for row in table.find_all("tr")
    ]


def measure() -> tuple[dict[str, tuple[int, int, int, int]], dict[str, object]]:
    """Measure the fixed corpus without writing profiles or derived artifacts."""
    manifest = json.loads((REPO / "data/corpus/manifest.json").read_text())
    golden: dict[str, tuple[int, int, int, int]] = {}
    empty_ratios: list[float] = []
    before_widths: list[int] = []
    dropped_widths: list[int] = []
    after_widths: list[int] = []
    totals: Counter[str] = Counter()

    for entry in sorted(manifest, key=lambda item: (item["ticker"], item["report_date"])):
        doc_id = f"{entry['ticker']}-FY{entry['report_date'][:4]}"
        raw = read_source(REPO / entry["file"])
        tables = [block for block in leaf_blocks(normalize(raw)) if block.name == "table"]
        empty_outputs = expanded_cells = dropped_cells = collapsed_cells = 0

        for table in tables:
            row_widths = _expanded_row_widths(table)
            if row_widths and len(set(row_widths)) > 1:
                totals["ragged_tables"] += 1

            cells = table.find_all(["td", "th"])
            if cells:
                empty_ratios.append(
                    sum(not cell.get_text(" ", strip=True) for cell in cells) / len(cells)
                )
            for cell in cells:
                colspan = _span(cell, "colspan")
                rowspan = _span(cell, "rowspan")
                if colspan > 1:
                    totals["colspan_occurrences"] += 1
                    totals["colspan_covered_cells"] += colspan
                if rowspan > 1:
                    totals["rowspan_occurrences"] += 1
                if PAREN_NUMBER.fullmatch(cell.get_text(" ", strip=True)):
                    totals["parenthesized_number_cells"] += 1

            grid = to_grid(table)
            dropped = drop_empty(grid)
            collapsed = merge_unit_columns(dropped)
            expanded_cells += sum(len(row) for row in grid)
            dropped_cells += sum(len(row) for row in dropped)
            collapsed_cells += sum(len(row) for row in collapsed)
            if grid:
                before_widths.append(len(grid[0]))
            if dropped:
                dropped_widths.append(len(dropped[0]))
            if collapsed:
                after_widths.append(len(collapsed[0]))
            if not table_to_markdown(str(table)):
                empty_outputs += 1

        golden[doc_id] = (len(tables), empty_outputs, expanded_cells, collapsed_cells)
        totals["tables"] += len(tables)
        totals["empty_outputs"] += empty_outputs
        totals["expanded_cells"] += expanded_cells
        totals["dropped_cells"] += dropped_cells
        totals["collapsed_cells"] += collapsed_cells

    summary: dict[str, object] = dict(totals)
    summary["median_raw_cell_empty_ratio"] = round(median(empty_ratios), 3)
    summary["expanded_widths"] = {
        "p50": _percentile(before_widths, 0.50),
        "p90": _percentile(before_widths, 0.90),
        "max": max(before_widths),
    }
    summary["empty_axes_removed_widths"] = {
        "p50": _percentile(dropped_widths, 0.50),
        "p90": _percentile(dropped_widths, 0.90),
        "max": max(dropped_widths),
    }
    summary["collapsed_widths"] = {
        "p50": _percentile(after_widths, 0.50),
        "p90": _percentile(after_widths, 0.90),
        "max": max(after_widths),
    }
    return golden, summary


if __name__ == "__main__":
    measured_golden, measured_summary = measure()
    print("TABLES = {")
    for measured_doc_id, values in measured_golden.items():
        print(f"    {measured_doc_id!r}: {values},")
    print("}")
    print("\nSUMMARY =")
    print(json.dumps(measured_summary, indent=2, sort_keys=True))
```



```bash
uv run python scripts/check_doc_code.py docs/en/m1-2-tables/03-build.md docs/ko/m1-2-tables/03-build.md
uv run ruff check --no-fix app/ingestion/tables.py tests/ingestion/test_09_tables.py scripts/measure_tables.py
uv run pytest tests/ingestion/test_09_tables.py -q
uv run python -m app.ingestion.tables --doc NVDA-FY2024
```

네 명령이 모두 통과하면 CLI에 요청한 filing의 읽을 수 있는 표 Markdown이 나타난다. 하나가 실패하면 다음 명령으로 넘어가지 말고 첫 실패부터 해결한다. 코퍼스가 없다면 구현을 건너뛸 이유가 아니라 M0 선행 조건이 빠진 것이므로 먼저 코퍼스를 준비한다. 끝의 생성 구간은 직접 고치는 대상이 아니다.

<!-- complete-files:start -->
## 완성 기준본 — 정식 구현 전체

아래 정식 경로를 직접 생성하거나 교체한다. `_mine.py` 또는 별도의 학습자용 복사 모듈을 만들지 않는다. 앞의 발췌 코드는 개별 결정을 설명하고, 이 절의 코드 블록은 체크포인트를 마친 뒤 대조할 완성 파일이다. 표시된 타입 어노테이션과 영어 주석을 유지하며 `pyproject.toml`을 Ruff 정책의 기준으로 사용한다.

### M1.2 — 완성 체크포인트

#### 생성 또는 교체 `app/ingestion/tables.py`

<!-- file: app/ingestion/tables.py -->
```python
"""10-K financial tables -> markdown.

**The problem is not serialization, it is layout.** SEC filings render tables for
print, not for data: across this corpus's 1,200 table blocks, the median table has
63.6% empty raw cells, `<th>` never appears, and `colspan` is used 57,617 times
purely to position text. A three-column income statement ships as twelve physical
columns of label / value / unit / spacer.

Converting that HTML straight to markdown produces a wide, mostly-empty grid that is
worse for retrieval than the raw text. So the pipeline collapses layout first and
serializes last:

    L2 to_grid              colspan/rowspan -> dense matrix
    L3 drop_empty           remove all-empty rows and columns   (12 -> 5 cols, p50)
    L4 merge_unit_columns   fold '$'/'%'-only columns into their value
    L5 split_header         infer header rows (there is no <th> to read)
    L6 to_markdown          serialize

This module is a pure function over HTML. It does not touch `Block`: the parser
leaves table blocks as `Block("table", "", html=...)` and the chunker (M1.3) calls
`table_to_markdown` when it needs text. Keeping it out of the parser means table
rendering cannot shift the coverage metric, and the parser stays unaware of markdown.

For education/practice purposes, this is implemented directly with BeautifulSoup
instead of a converter library, to keep the collapse rules inspectable.
"""

from __future__ import annotations

from bs4 import BeautifulSoup, Tag

Grid = list[list[str]]

# Glyphs that SEC layout tables place in a column of their own. A column holding
# nothing but these is presentation, not data, so it is folded into its value column.
UNIT_MARKERS = frozenset({"$", "%", "€", "¥", "£"})


def _span(cell: Tag, name: str) -> int:
    """`colspan`/`rowspan` as a positive int. Filings do emit junk values."""
    try:
        return max(1, int(str(cell.get(name, 1)).strip() or 1))
    except TypeError, ValueError:
        return 1


# ── L2. Grid ────────────────────────────────────────────────────────────────


def to_grid(table: Tag) -> Grid:
    """Expand a `<table>` into a dense matrix, resolving colspan and rowspan.

    A spanned cell keeps its text in the top-left position only; the covered
    positions become empty strings. Replicating the text instead would duplicate
    every number in the corpus, since values are what carry `colspan` here.

    Ragged tables (80 of 1,200) fall out for free: the matrix is sized from
    the furthest cell reached and short rows are padded.
    """
    filled: dict[tuple[int, int], str] = {}
    for r, tr in enumerate(table.find_all("tr")):
        col = 0
        for cell in tr.find_all(["td", "th"]):
            while (r, col) in filled:  # skip positions already taken by a rowspan
                col += 1
            text = cell.get_text(" ", strip=True)
            cspan, rspan = _span(cell, "colspan"), _span(cell, "rowspan")
            for dr in range(rspan):
                for dc in range(cspan):
                    filled[(r + dr, col + dc)] = text if dr == 0 and dc == 0 else ""
            col += cspan
    if not filled:
        return []
    height = max(r for r, _ in filled) + 1
    width = max(c for _, c in filled) + 1
    return [[filled.get((r, c), "") for c in range(width)] for r in range(height)]


# ── L3. Collapse ────────────────────────────────────────────────────────────


def drop_empty(grid: Grid) -> Grid:
    """Drop rows and columns that hold no text anywhere.

    This is the step that does the real work: spacer rows, spacer columns and the
    indentation columns used for line-item nesting all disappear. Measured on this
    corpus the column count falls from p50=12 / max=66 to p50=5 / max=25, and 26
    tables turn out to be pure layout with no content at all.
    """
    rows = [r for r in grid if any(c.strip() for c in r)]
    if not rows:
        return []
    keep = [j for j in range(len(rows[0])) if any(r[j].strip() for r in rows)]
    return [[r[j] for j in keep] for r in rows]


# ── L4. Units ───────────────────────────────────────────────────────────────


def merge_unit_columns(grid: Grid) -> Grid:
    """Fold columns holding only a currency or percent glyph into their value.

    Direction follows how the glyph reads: `$` precedes its number, `%` follows it.
    Without this the corpus leaves 279 columns of bare symbols after collapsing.
    """
    if not grid:
        return grid
    width = len(grid[0])
    cols = [[row[j] for row in grid] for j in range(width)]

    dropped: set[int] = set()
    for j in range(width):
        values = [c.strip() for c in cols[j] if c.strip()]
        if not values or not all(v in UNIT_MARKERS for v in values):
            continue
        trailing = all(v == "%" for v in values)
        target = j - 1 if trailing else j + 1
        if not 0 <= target < width or target in dropped:
            continue
        for i, glyph in enumerate(cols[j]):
            if not glyph.strip():
                continue
            value = cols[target][i]
            cols[target][i] = f"{value} {glyph}".strip() if trailing else f"{glyph} {value}".strip()
        dropped.add(j)

    keep = [j for j in range(width) if j not in dropped]
    return [[cols[j][i] for j in keep] for i in range(len(grid))]


# ── L5. Header ──────────────────────────────────────────────────────────────


def split_header(grid: Grid) -> tuple[Grid, Grid]:
    """Split leading header rows from the body.

    There is no `<th>` in this corpus, so the header has to be inferred from shape:
    a header row labels the value columns and leaves the label column blank, while
    every data row starts with its line-item name. Leading rows matching that shape
    are the header.

    Returns `([], grid)` when nothing matches, so the caller decides the fallback.
    """
    n = 0
    for row in grid:
        if row[0].strip() or not any(c.strip() for c in row[1:]):
            break
        n += 1
    if n == 0 or n == len(grid):
        return [], grid
    return grid[:n], grid[n:]


# ── L6. Serialize ───────────────────────────────────────────────────────────


def _cell(text: str) -> str:
    """Make a cell safe for a markdown table row."""
    return " ".join(text.replace("|", "\\|").split())


def to_markdown(grid: Grid) -> str:
    """Serialize a collapsed grid as a markdown table.

    Multi-row headers ("Year Ended" over "Jan 28, 2024") are joined per column, so
    the period a number belongs to survives into the chunk text.
    """
    if not grid:
        return ""
    header, body = split_header(grid)
    if header:
        head = [" ".join(row[j] for row in header if row[j].strip()) for j in range(len(grid[0]))]
    else:  # no header shape: promote the first row so the table stays valid markdown
        head, body = body[0], body[1:]

    lines = [
        "| " + " | ".join(_cell(c) for c in head) + " |",
        "| " + " | ".join("---" for _ in head) + " |",
    ]
    lines += ["| " + " | ".join(_cell(c) for c in row) + " |" for row in body]
    return "\n".join(lines)


# ── L7. Entry point ─────────────────────────────────────────────────────────


def table_to_markdown(html: str | None) -> str:
    """`Block(kind="table").html` -> markdown. Empty string when there is no content.

    Numbers are passed through verbatim: `(1,234)` stays parenthesized rather than
    becoming `-1234`. The citation has to match what a reader sees in the filing,
    and normalizing here would be irreversible; query-side normalization is not.
    """
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if not isinstance(table, Tag):
        return ""
    grid = drop_empty(to_grid(table))
    if not grid:
        return ""
    return to_markdown(merge_unit_columns(grid))


if __name__ == "__main__":  # pragma: no cover - eyeball helper
    import argparse
    import json
    from pathlib import Path

    from app.ingestion.parser import leaf_blocks, normalize, read_source

    ap = argparse.ArgumentParser(description="Render 10-K tables as markdown.")
    ap.add_argument("--doc", default="NVDA-FY2024", help="doc_id, e.g. NVDA-FY2024")
    ap.add_argument("--contains", default="Gross profit", help="pick tables containing this text")
    ap.add_argument("--limit", type=int, default=2)
    a = ap.parse_args()

    manifest = json.loads(Path("data/corpus/manifest.json").read_text())
    entry = next(e for e in manifest if f"{e['ticker']}-FY{e['report_date'][:4]}" == a.doc)
    soup = normalize(read_source(entry["file"]))
    shown = 0
    for el in leaf_blocks(soup):
        if el.name != "table" or a.contains not in el.get_text(" ", strip=True):
            continue
        print(f"\n{'─' * 70}\n{a.doc}\n{'─' * 70}")
        print(table_to_markdown(str(el)))
        shown += 1
        if shown >= a.limit:
            break
    if not shown:
        print(f"no table in {a.doc} contains {a.contains!r}")
```

#### 생성 또는 교체 `scripts/measure_tables.py`

<!-- file: scripts/measure_tables.py -->
```python
#!/usr/bin/env python3
"""Regenerate the M1.2 corpus measurements and per-document golden tuples."""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import re
from statistics import median

from bs4 import Tag

from app.ingestion.parser import leaf_blocks, normalize, read_source
from app.ingestion.tables import drop_empty, merge_unit_columns, table_to_markdown, to_grid

REPO = Path(__file__).resolve().parent.parent
PAREN_NUMBER = re.compile(r"^\(\s*[\d,.]+\s*\)$")


def _span(cell: Tag, name: str) -> int:
    try:
        return max(1, int(str(cell.get(name, 1)).strip() or 1))
    except TypeError, ValueError:
        return 1


def _percentile(values: list[int], fraction: float) -> int:
    """Return a deterministic nearest-rank percentile for a non-empty list."""
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round((len(ordered) - 1) * fraction)))
    return ordered[index]


def _expanded_row_widths(table: Tag) -> list[int]:
    """Return declared row widths after colspan but before rectangular padding."""
    return [
        sum(_span(cell, "colspan") for cell in row.find_all(["td", "th"]))
        for row in table.find_all("tr")
    ]


def measure() -> tuple[dict[str, tuple[int, int, int, int]], dict[str, object]]:
    """Measure the fixed corpus without writing profiles or derived artifacts."""
    manifest = json.loads((REPO / "data/corpus/manifest.json").read_text())
    golden: dict[str, tuple[int, int, int, int]] = {}
    empty_ratios: list[float] = []
    before_widths: list[int] = []
    dropped_widths: list[int] = []
    after_widths: list[int] = []
    totals: Counter[str] = Counter()

    for entry in sorted(manifest, key=lambda item: (item["ticker"], item["report_date"])):
        doc_id = f"{entry['ticker']}-FY{entry['report_date'][:4]}"
        raw = read_source(REPO / entry["file"])
        tables = [block for block in leaf_blocks(normalize(raw)) if block.name == "table"]
        empty_outputs = expanded_cells = dropped_cells = collapsed_cells = 0

        for table in tables:
            row_widths = _expanded_row_widths(table)
            if row_widths and len(set(row_widths)) > 1:
                totals["ragged_tables"] += 1

            cells = table.find_all(["td", "th"])
            if cells:
                empty_ratios.append(
                    sum(not cell.get_text(" ", strip=True) for cell in cells) / len(cells)
                )
            for cell in cells:
                colspan = _span(cell, "colspan")
                rowspan = _span(cell, "rowspan")
                if colspan > 1:
                    totals["colspan_occurrences"] += 1
                    totals["colspan_covered_cells"] += colspan
                if rowspan > 1:
                    totals["rowspan_occurrences"] += 1
                if PAREN_NUMBER.fullmatch(cell.get_text(" ", strip=True)):
                    totals["parenthesized_number_cells"] += 1

            grid = to_grid(table)
            dropped = drop_empty(grid)
            collapsed = merge_unit_columns(dropped)
            expanded_cells += sum(len(row) for row in grid)
            dropped_cells += sum(len(row) for row in dropped)
            collapsed_cells += sum(len(row) for row in collapsed)
            if grid:
                before_widths.append(len(grid[0]))
            if dropped:
                dropped_widths.append(len(dropped[0]))
            if collapsed:
                after_widths.append(len(collapsed[0]))
            if not table_to_markdown(str(table)):
                empty_outputs += 1

        golden[doc_id] = (len(tables), empty_outputs, expanded_cells, collapsed_cells)
        totals["tables"] += len(tables)
        totals["empty_outputs"] += empty_outputs
        totals["expanded_cells"] += expanded_cells
        totals["dropped_cells"] += dropped_cells
        totals["collapsed_cells"] += collapsed_cells

    summary: dict[str, object] = dict(totals)
    summary["median_raw_cell_empty_ratio"] = round(median(empty_ratios), 3)
    summary["expanded_widths"] = {
        "p50": _percentile(before_widths, 0.50),
        "p90": _percentile(before_widths, 0.90),
        "max": max(before_widths),
    }
    summary["empty_axes_removed_widths"] = {
        "p50": _percentile(dropped_widths, 0.50),
        "p90": _percentile(dropped_widths, 0.90),
        "max": max(dropped_widths),
    }
    summary["collapsed_widths"] = {
        "p50": _percentile(after_widths, 0.50),
        "p90": _percentile(after_widths, 0.90),
        "max": max(after_widths),
    }
    return golden, summary


if __name__ == "__main__":
    measured_golden, measured_summary = measure()
    print("TABLES = {")
    for measured_doc_id, values in measured_golden.items():
        print(f"    {measured_doc_id!r}: {values},")
    print("}")
    print("\nSUMMARY =")
    print(json.dumps(measured_summary, indent=2, sort_keys=True))
```

체크포인트를 실행한다.

```bash
uv run pytest tests/ingestion/test_09_tables.py -q
```

**예상 결과:** 선택한 모든 오프라인 테스트가 통과한다. 명시된 통합 테스트는 외부 서비스를 사용할 수 없을 때만 건너뛸 수 있다.

**중단 조건:** 테스트가 실패하거나 필수 정식 심볼이 없어서 건너뛰면 진행하지 않는다.

**디버깅:** 같은 pytest 대상을 `-vv --tb=long`으로 다시 실행하고 첫 번째로 실패한 계약을 고친 뒤 진행한다.

<!-- complete-files:end -->
