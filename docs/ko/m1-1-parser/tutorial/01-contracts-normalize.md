# M1.1 튜토리얼 1 — 무엇을 내보낼지부터 못 박는다

파서의 첫 두 층을 만든다. L1은 이 모듈이 무엇을 내보내는지 자료구조로 선언하고, L2는 그 자료구조가 담을 텍스트를 준비한다. 코드는 아직 아무것도 자르지 않는다.

순서가 반대로 느껴질 수 있다. 보통은 파싱부터 하고 정리를 나중에 한다. 여기서는 **출력 계약을 먼저 못 박는다.** 그래야 아래 열두 층이 무엇을 향해 쌓이는지가 고정된다.

**선행 조건:** `uv sync --locked --group dev`가 끝나 있고, `data/corpus/manifest.json`과 20개 filing 스냅샷이 있어야 한다. `app/ingestion/parser.py`는 비어 있는 상태에서 시작한다.

## 무엇을 작성하고 어디를 직접 구현할까

| 구간 | 학습 행동 | 여기서 얻어야 하는 것 |
|---|---|---|
| L1 `Block`·`Section`·`ParsedFiling` | **모델 선언 작성** | 좌표 필드가 없으면 검증이 왜 불가능해지는가 |
| L1 SEC 상수와 정규식 | **설정 스키마 정의** | 임의로 고른 숫자가 하나도 없다는 확인 |
| L2 `normalize` | 제거와 언랩의 경계를 **직접 구현** | iXBRL을 걷어내면서 숫자를 남기는 법 |
| L2 `line_offsets`·`source_pos` | **경계 변환 검토** | 좌표를 정규화 전에 확정해야 하는 이유 |

---

## L1 — 자료구조가 먼저다

먼저 빈 `app/__init__.py`와 `app/ingestion/__init__.py`를 만들고 새 정식 파일 `app/ingestion/parser.py`를 연다. L8에서 `xref.py`가 생기기 전까지는 xref import를 추가하지 않는다. 지금은 파일의 첫 줄부터 다음 import를 작성한다.

#### `app/ingestion/parser.py` 생성 — import와 자료구조 기반

```python
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Literal
import warnings

from bs4 import BeautifulSoup, Tag, XMLParsedAsHTMLWarning
```

파서를 짤 때 가장 흔한 실수는 "일단 파싱부터 하고 정리는 나중에"다. 처음엔 빠른 것 같다. 그런데 한 달쯤 지나면 중간 표현이 딕셔너리로 떠다니면서 `result["blocks"][0]["pos"]` 같은 접근이 코드 곳곳에 박히고, 그 `pos`가 어디서 생긴 값인지 아무도 모르게 된다.

그래서 반대로 간다. **무엇을 내보낼지부터 못 박고 시작한다.** 아래 세 클래스가 이 모듈의 전체 출력 계약이다.

### 좌표가 없으면 검증 자체가 불가능해진다

파서를 다 만들고 나면 이런 순간이 온다. 실행해보니 "23개 Item을 찾았다"고 나온다. Item 순서도 SEC 표준 순서와 맞고, 중복도 없고, 첫 섹션은 5만 자다. 완벽해 보인다.

정말 맞게 찾은 걸까?

출력에 위치가 없으면 확인할 방법이 없다. 개수·크기 같은 간접 지표만 남는다. 그런데 이 지표들은 **목차를 헤딩으로 착각했을 때도 똑같이 완벽하게 나온다.** 목차에는 Item이 순서대로, 중복 없이, 23개 다 있으니까. 실제로 이 프로젝트에서 그 일이 있었다([B10](../04-bugs.md#b10)).

`source_pos`가 있으면 다르다. 원본 HTML을 그 오프셋에서 열어 눈으로 대조하면 끝난다([05-verify.md](../05-verify.md) 최종확인④). 그리고 이 좌표는 앞서 말했듯 M1.3 → M1.4 → M4까지 실려 가서 최종 인용의 근거가 된다.

### 딕셔너리 대신 dataclass를 쓰는 이유

딕셔너리를 쓰면 `sec["itme"]` 같은 오타가 런타임까지 살아남는다. 운이 나쁘면 프로덕션에서 `KeyError`로 터진다. dataclass는 같은 오타가 즉시 `AttributeError`고, 에디터가 필드를 자동완성해주며, `field(default_factory=list)`가 "가변 기본값을 인스턴스끼리 공유하는" 파이썬 고전 함정을 막아준다.

### `Literal`은 런타임에 아무것도 강제하지 않는다

`SegmentType = Literal["number", ...]`이라고 써도 파이썬은 실행 중에 그 값을 검사하지 않는다. 타입체커와 사람을 위한 문서일 뿐이다. 실제 방어는 [L9](06-detect-classify.md#l9--판별-캐스케이드--이-문서엔-어느-전략이-맞나)의 판별 함수가 그 값들만 반환하게 만드는 것으로 한다. "타입은 의도를 적고, 코드가 그 의도를 지킨다"가 파이썬의 방식이다.

> ⚠ 참고로 `SegmentType`은 **선언만 되어 있고 어디에도 어노테이션으로 쓰이지 않는다.** `ParsedFiling.segment_type`은 그냥 `str`이다. `ItemStatus`는 `Section.status`에 실제로 쓰인다.

`int | None` 표기는 Python 3.10부터 표준이라 `typing.Optional`을 가져올 필요가 없다.

### 구현

#### 대상 파일: `app/ingestion/parser.py`

<!-- src: app/ingestion/parser.py::SegmentType,ItemStatus -->
```python
SegmentType = Literal["number", "sec_canonical", "custom_title", "xref", "undefined"]
ItemStatus = Literal["parsed", "empty_disclosure", "incorporated_by_reference"]
```

**코드에서 꼭 볼 것**

- 두 별칭 모두 `Literal`이라 런타임에는 아무것도 검사하지 않는다. 값의 집합을 한 곳에 적어 두는 것이 목적이다.
- `SegmentType`의 다섯 값은 L9 감지 캐스케이드가 반환할 수 있는 전부다. 이 집합 밖의 값이 나오면 L9에 버그가 있다는 뜻이다.
- `ItemStatus`는 본문이 없는 서로 다른 이유를 가른다 — 있거나, 정당하게 해당 없거나, 다른 공시로 미뤘거나. 셋 중 무엇인지는 L10이 정한다.

<!-- src: app/ingestion/parser.py::Block -->
```python
@dataclass
class Block:
    kind: Literal["heading", "paragraph", "table"]
    text: str
    level: int | None = None  # 1=Item heading, 2=narrative subheading
    html: str | None = None  # raw table input for the M1.2 markdown converter
    source_pos: int | None = None  # start offset in the original HTML
    end_pos: int | None = None  # exclusive end offset in the original HTML
    source_group: int = 0  # contiguous narrative range within one Section
    source_heading: str | None = None  # title of that narrative range
```

**코드에서 꼭 볼 것**

- 아홉 필드 중 넷(`source_pos`, `end_pos`, `source_group`, `source_heading`)은 좌표와 출처를 위해 존재한다. 이 넷은 M1.3의 청크 경계와 M4의 인용까지 그대로 타고 간다.
- `html`은 표에만 채워진다. L3이 데이터 표로 판정한 것만 원본 HTML을 유지해 M1.2에 넘긴다.
- `kind`의 값은 정확히 셋이고, 이후 모든 레이어가 분기해야 하는 경우의 수를 여기서 고정한다.

<!-- src: app/ingestion/parser.py::Section -->
```python
@dataclass
class Section:
    part: str | None  # "I".."IV"
    item: str | None  # "1A"
    canonical_title: str  # SEC canonical title
    reported_title: str  # title used by the filing
    blocks: list[Block] = field(default_factory=list)
    status: ItemStatus = "parsed"
    reference_source: str | None = None
    # Location proves where an Item was found instead of merely claiming it was found.
    block_index: int | None = None  # heading block number
    block_range: tuple[int, int] | None = None  # block range occupied by this section
    source_pos: int | None = None  # character offset in the original HTML
```

**코드에서 꼭 볼 것**

- `canonical_title`과 `reported_title`을 분리한 것이 핵심 결정이다. 앞은 SEC의 정식 제목이고, 뒤는 회사가 실제로 인쇄한 제목이다. 합쳐 버리면 Intel이 Item 1A를 뭐라고 불렀는지를 잃는다.
- `block_index`, `block_range`, `source_pos`는 Item을 찾았다는 주장이 아니라 어디서 찾았는지의 증거다. 이게 없으면 L12의 검증은 개수와 순서밖에 볼 수 없다.
- `status`는 `ItemStatus`가 실제로 쓰이는 유일한 자리다.

<!-- src: app/ingestion/parser.py::ParsedFiling -->
```python
@dataclass
class ParsedFiling:
    """Top-level output contract containing the complete parse of one filing."""

    doc_id: str  # "NVDA-FY2024"
    ticker: str
    cik: str
    form: str
    filing_date: str
    report_period: str
    fiscal_year: int
    accession: str
    source_url: str
    source_length: int = 0  # Unicode code points in the canonical decoded source
    source_sha256: str = ""  # SHA-256 of the exact source bytes
    sections: list[Section] = field(default_factory=list)
    item_index: list[dict] = field(default_factory=list)  # xref-only source index
    parse_status: str = "parsed"  # parsed | needs_profile_update
    warnings: list[str] = field(default_factory=list)
    profile_used: str = "saved"  # bootstrap | saved | relearned
    segment_type: str = ""
    # Validation measurements kept here so the CLI does not parse the filing twice.
    n_blocks: int = 0
    n_chars: int = 0  # total document text length, used as the coverage denominator
```

SEC가 정한 상수도 여기 둔다. **바뀌지 않는 것과 바뀌는 것을 파일 첫머리에서 갈라놓는다.**

<!-- src: app/ingestion/parser.py::CANONICAL,ORDER,PART_OF -->
```python
CANONICAL = {
    "1": "Business",
    "1A": "Risk Factors",
    "1B": "Unresolved Staff Comments",
    "1C": "Cybersecurity",
    "2": "Properties",
    "3": "Legal Proceedings",
    "4": "Mine Safety Disclosures",
    "5": "Market for Registrant's Common Equity",
    "6": "Reserved",
    "7": "Management's Discussion and Analysis",
    "7A": "Quantitative and Qualitative Disclosures About Market Risk",
    "8": "Financial Statements and Supplementary Data",
    "9": "Changes in and Disagreements with Accountants",
    "9A": "Controls and Procedures",
    "9B": "Other Information",
    "9C": "Foreign Jurisdictions That Prevent Inspections",
    "10": "Directors, Executive Officers and Corporate Governance",
    "11": "Executive Compensation",
    "12": "Security Ownership",
    "13": "Certain Relationships and Related Transactions",
    "14": "Principal Accountant Fees and Services",
    "15": "Exhibits and Financial Statement Schedules",
    "16": "Form 10-K Summary",
}
ORDER = list(CANONICAL)  # dict preserves insertion order in Python 3.7+
PART_OF = {
    **dict.fromkeys(["1", "1A", "1B", "1C", "2", "3", "4"], "I"),
    **dict.fromkeys(["5", "6", "7", "7A", "8", "9", "9A", "9B", "9C"], "II"),
    **dict.fromkeys(["10", "11", "12", "13", "14"], "III"),
    **dict.fromkeys(["15", "16"], "IV"),
}
```

**코드에서 꼭 볼 것**

- 셋 다 SEC가 고정한 사실이지 코퍼스에서 측정한 값이 아니다. 다시 측정하지 않으며, 규정이 바뀔 때만 바뀐다.
- `ORDER = list(CANONICAL)`은 딕셔너리의 삽입 순서를 재사용한다. L12의 Item 순서 검증이 이 순서를 기준으로 삼는다.
- `PART_OF`는 `dict.fromkeys`로 만들어 Item에서 Part를 바로 찾는다. Part별 Item 목록으로 저장하면 조회할 때마다 뒤집어야 한다.

<!-- src: app/ingestion/parser.py::ITEM_RE -->
```python
ITEM_RE = re.compile(
    r"^\s*item\s+(?P<num>1[0-6]|[1-9])(?P<suffix>[A-C])?\s*[.\-–—:]?\s*(?P<title>.*)$",
    re.I,
)
```

이 정규식에는 함정이 두 개 숨어 있다.

첫째, `1[0-6]|[1-9]`의 **순서**다. 무심코 `[1-9]|1[0-6]`이라고 쓰면 "Item 15"를 만났을 때 `1`만 먹고 멈춘다. Item 15가 Item 1로 둔갑한다. 정규식의 교대(`|`)는 왼쪽부터 시도해서 처음 맞는 걸 취하기 때문에, **긴 패턴을 왼쪽에 둬야 한다.**

둘째, 맨 앞의 `^`다. 이게 없으면 본문 중간의 "as described in Item 1A above" 같은 상호 참조가 전부 헤딩 후보로 잡힌다. 10-K 한 편에 이런 문장이 수십 개씩 있다 ([F2](../01-findings.md#f2)). `^`가 "블록이 이 글자로 시작할 때만"이라는 조건을 건다.

### 튜닝 상수 — 임의로 고른 숫자가 하나도 없다

아래에 나오는 20여 개 상수는 전부 코퍼스 20개 파일을 직접 재서 나온 값이다. 그래서 값 옆에 근거를 주석으로 같이 박아뒀고, 바꾸려면 다시 재야 한다.

한 가지 규칙이 있다. **값이 같아도 뜻이 다르면 따로 선언한다.** `LAYOUT_CELL_CHARS`와 `HEADING_MAX_CHARS`는 둘 다 300이지만 별개 상수다. 앞의 것은 "이만큼 긴 셀이 있으면 레이아웃 표"이고, 뒤의 것은 "이보다 긴 블록은 헤딩일 수 없다"다. 하나로 합쳐두면 나중에 한쪽만 조정해야 할 때 `grep 300`으로 엉뚱한 곳을 고치게 된다.

> 아래 블록은 손으로 옮겨 적은 표가 아니라 소스 그대로다. `scripts/check_doc_code.py`가 대조하므로 문서와 코드의 값이 갈라질 수 없다.

첫 묶음은 L3 블록화에서 데이터 표와 레이아웃 표를 가르는 데 쓰고 ([F9](../01-findings.md#f9)), 나머지는 주석의 레이어 표시를 따라간다. 지금 다 이해할 필요는 없다. 해당 레이어에 도착하면 그때 다시 설명한다.

#### 대상 파일: `app/ingestion/parser.py`

<!-- src: app/ingestion/parser.py::DATA_TABLE_MIN_CELLS,XREF_THIN_RATIO -->
```python
DATA_TABLE_MIN_CELLS = 6  # fewer cells indicate a layout fragment
LAYOUT_CELL_CHARS = 300  # any cell this long makes the table a layout table
# Check length before numeric density to exclude Intel infographic tables (B05).
NUMERIC_CELL_CHARS = 30  # longer text is prose containing a number, not a numeric cell
DATA_TABLE_MIN_NUMERIC = 4  # minimum number of numeric cells
DATA_TABLE_NUMERIC_DIVISOR = 4  # numeric cells must also be at least one quarter of all cells

# L7 heading walk
HEADING_MAX_CHARS = 300  # longer blocks cannot be headings; run this cheapest filter first
SUBHEADING_MAX_CHARS = 80  # maximum length for a level-2 narrative subheading
REPORTED_TITLE_MAX = 150  # maximum stored Section.reported_title length
CANON_MIN_CHARS = 8  # shorter SEC-title candidates match by accident (B11)
CANON_PREFIX_CHARS = 14  # require this many characters for prefix matches (B11)

# L9 detection cascade
NUMBER_MIN_HITS = 5  # fewer matches indicate cross-references, not headings
OUTSIDE_TABLE_MIN_HITS = 15  # inspect tables when too few matches exist outside them (F4)
TOC_MIN_ITEMS = 10  # minimum Item candidates required to classify a TOC
TOC_DENSITY = 0.15  # candidates clustered within this document fraction indicate a TOC (B16)
XREF_MIN_ENTRIES = 10  # minimum entries required for a cross-reference index
XREF_MIN_TOC_ROWS = 5  # minimum rows required for a table of contents

# L8 xref assembly
ORPHAN_MIN_BLOCKS = 3  # discard shorter orphan ranges as fragments (B07)
JOINED_TITLE_MAX = 300  # maximum reported_title after joining narrative titles
PAGE_HEADER_MAX_CHARS = 60  # short, frequent text is a page header (F11)
PAGE_HEADER_MIN_REPEATS = 10  # "Table of Contents" appears 113 times

# L10 status classification
CLASSIFY_SCAN_CHARS = 400  # inspect only this many leading section characters
REF_MAX_BLOCKS = 3  # more blocks indicate body content, not a reference-only section

# L12 validation
CORE_THIN_BLOCKS = 20  # fewer blocks means a core Item has no body
CORE_THIN_COUNT = 2  # this many thin core Items indicate TOC headings were selected (B10)
XREF_THIN_BLOCKS = 5  # thin-section threshold for xref filings
XREF_THIN_RATIO = 0.3  # fail when thin sections exceed this ratio
```


**상수로 빼지 않은 숫자들**도 있다. 측정값이 아니라서다:

| 그대로 둔 것 | 왜 |
|---|---|
| `font_weight` 의 `700` | 튜닝값이 아니라 **CSS 스펙**이다(`bold` == 700) |
| `10**9` (다음 페이지 센티널) | "무한대" 관용구. 이름 붙여도 안 나아진다 |
| `text[:4]` (연도 슬라이스) | 구조. `"2024-01-28"` 의 형태가 정한다 |
| CLI 출력 폭 (`:12`, `:>9,`) | 표시용. 파싱 동작과 무관 |
| 정규식 안의 수량자 (`\d{1,3}`, `{0,80}`) | 패턴의 일부라 밖으로 빼면 오히려 안 읽힌다 |

### 확인

```bash
uv run pytest tests/ingestion/test_02_rules.py -k item_regex -v
```

코퍼스가 없어도 돈다. `Item 15`가 `"15"`로 나오는지(교대 순서)와 `"as described in Item 1A above"`가 `None`인지(`^` 앵커)를 본다.

---

## L2 — 정규화 — 지우는 것과 벗기는 것은 다르다

이제 HTML을 실제로 읽는다. 그런데 그 전에 결정할 게 하나 있다. 어떤 파서를 쓸 것인가.

### 느린 파서를 일부러 골랐다

파이썬에서 HTML을 파싱한다면 보통 `lxml`을 쓴다. 빠르니까. 그런데 `lxml`은 각 요소가 원본 어디에서 왔는지(`sourceline`, `sourcepos`)를 채워주지 않는다. 표준 라이브러리의 `html.parser`는 `store_line_numbers=True`를 주면 채워준다. 대신 20개 파일 전체에서 1.6초가 더 걸린다.

1.6초를 주고 산 것은 **검증 가능성**이다([F15](../01-findings.md#f15)). 앞에서 말한 그 좌표가 여기서 나온다. 이게 없으면 파이프라인 끝까지 인용을 확인할 수 없다.

파서를 바꾸는 건 위험한 작업이라는 점도 알아두자. 파서가 다르면 트리 구조가 미묘하게 달라질 수 있다. 그래서 교체 전에 20개 파일 전부에서 블록 텍스트가 **한 글자도 다르지 않다는 것**을 확인하고 넘어갔다. 파서 교체에는 이런 등가성 확인이 필수다.

### 줄 번호는 이 문서에서 아무 쓸모가 없다

`sourceline`을 얻었다고 끝이 아니다. 10-K는 압축돼서 오기 때문에 2MB 파일이 5줄일 수 있다. "5번째 줄"이라는 정보는 사실상 "파일 어딘가"라는 뜻이다.

`sourcepos`는 그 줄 안에서의 위치다. 그래서 줄의 시작 오프셋을 더해야 파일 전체 기준 절대 위치가 나온다. 실제 값으로 보면 이렇다.

```
line start offsets: [0, 39, 931, 932, 933]
sourceline=5  sourcepos=197,074  →  absolute 198,007
raw[198007:198030] = 'Item 1. Business <span style="color:#76b900;'
```

마지막 줄이 핵심이다. 계산한 오프셋으로 원본을 잘라보니 정말 "Item 1. Business"가 나온다. 이 검증을 사람이 언제든 할 수 있다는 게 이 모듈의 목표였다.

### 한 글자 차이가 재무 데이터의 생사를 가른다

10-K의 숫자는 iXBRL 태그로 감싸여 있다. 이 태그를 걷어내야 하는데, BeautifulSoup에는 비슷해 보이는 메서드가 두 개 있다.

```
<div>Revenue <ix:nonFraction>26,974</ix:nonFraction> million</div>

decompose() → <div>Revenue  million</div>       ← the number vanishes
unwrap()    → <div>Revenue 26,974 million</div>  ← correct
```

`decompose()`는 태그와 그 안의 내용을 통째로 삭제한다. `unwrap()`은 태그만 벗기고 내용은 남긴다. 스크립트·스타일처럼 **내용 자체가 필요 없는 것**은 `decompose()`, iXBRL처럼 **포장만 필요 없는 것**은 `unwrap()`이다.

여기서 `decompose()`를 잘못 쓰면 재무제표의 모든 숫자가 증발한다. 그런데 텍스트는 멀쩡히 남아 있어서 파서는 정상 동작하는 것처럼 보인다. 나중에 "왜 매출액이 검색이 안 되지?"로 며칠을 쓰게 되는 종류의 버그다.

### 접두어가 같다고 처리가 같지는 않다

`ix:`로 시작하는 태그는 전부 `unwrap()` 대상 같지만 예외가 하나 있다. `ix:header`는 iXBRL 규격상 **절대 렌더링되지 않는** 기계용 메타데이터 영역이다. 여기는 `decompose()`로 통째로 지워야 한다.

이걸 놓치면 어떻게 되는지가 재밌다. `ix:header` 안에는 `xbrli:*`, `xbrldi:*` 같은 자식 태그가 들어 있는데, 이들은 `ix:` 접두어가 아니라서 unwrap 대상이 아니다. 그래서 부모만 벗기면 자식들이 그대로 살아남아 **본문 첫 블록에 수만 자로 뭉친다**([F10](../01-findings.md#f10)). 실측으로 MU-FY2024가 34,148자, INTC-FY2019가 59,005자였다.

**순서도 중요하다.** `ix:header`를 먼저 지우고, 그다음에 나머지를 unwrap해야 한다.

### 경고는 전역이 아니라 이 호출에만 억제한다

10-K는 `<?xml ...?>`로 시작하는 XHTML이라 BeautifulSoup이 `XMLParsedAsHTMLWarning`을 낸다. 거슬린다고 모듈 최상단에서 `filterwarnings`를 부르면, 이 라이브러리를 쓰는 **다른 코드의 경고까지 조용히 삼킨다.** 라이브러리 개발에서 흔히 저지르는 민폐다. `catch_warnings()`로 이 호출 안에서만 억제한다.

### 구현 — 정규화 — iXBRL을 걷어내되 숫자는 지킨다

#### 대상 파일: `app/ingestion/parser.py`

<!-- src: app/ingestion/parser.py::line_offsets -->
```python
def line_offsets(html: str) -> list[int]:
    """Return each line's absolute start offset for ``source_pos`` calculation."""
    out, off = [], 0
    for line in html.splitlines(keepends=True):
        out.append(off)
        off += len(line)
    return out
```

**코드에서 꼭 볼 것**

- `keepends=True`가 이 함수의 전부다. 오프셋이 원문과 맞으려면 줄바꿈 문자도 길이에 포함돼야 한다. 빼는 순간 모든 줄이 한 글자씩 밀리고, 오차는 누적된다.
- 반환값은 줄 번호에서 절대 오프셋으로 가는 표다. BeautifulSoup은 줄 번호만 알려주므로, `source_pos`가 이 표로 절대 위치를 복원한다.

<!-- src: app/ingestion/parser.py::source_pos -->
```python
def source_pos(el: Tag, offsets: list[int]) -> int | None:
    """Return the character where this block starts in the original HTML.

    A minified 10-K can contain only five lines, making line numbers useless.
    ``sourcepos`` is relative to its line, so add the line's start offset to
    obtain an absolute character position.
    """
    if el.sourceline is None or el.sourcepos is None:
        return None
    return offsets[el.sourceline - 1] + el.sourcepos
```

좌표와 hash가 같은 입력을 가리키게 하려면 파일을 읽는 방법도 하나여야 한다. `source_pos()` 다음에 다음 두 함수를 정의한다.

<!-- src: app/ingestion/parser.py::read_source,source_digest -->
```python
def read_source(path: str | Path) -> str:
    """Decode source bytes as UTF-8 without universal-newline translation."""
    return Path(path).read_bytes().decode("utf-8")


def source_digest(source: str) -> str:
    """Bind character offsets to the exact UTF-8 source snapshot."""
    return hashlib.sha256(source.encode("utf-8")).hexdigest()
```

**코드에서 꼭 볼 것**

- `read_bytes().decode("utf-8")`을 쓰는 이유는 텍스트 모드로 열면 Python이 `\r\n`을 `\n`으로 바꿔 버리기 때문이다. 그 순간 글자 수가 줄어들고 모든 오프셋이 틀린다.
- `source_digest`는 좌표가 어느 스냅샷의 것인지 못 박는다. hash가 다르면 좌표를 믿을 수 없고, M1.4의 데이터베이스 행과 M3의 골든 식별자가 이 값을 그대로 물려받는다.


<!-- src: app/ingestion/parser.py::normalize -->
```python
def normalize(html: str) -> BeautifulSoup:
    # html.parser + store_line_numbers preserves source positions for validation.
    # lxml leaves sourceline empty. Across 20 measured files, block text was identical,
    # and the total cost of retaining positions was only 1.6 seconds.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", XMLParsedAsHTMLWarning)
        soup = BeautifulSoup(html, "html.parser", store_line_numbers=True)
    for tag in soup.find_all(["script", "style", "noscript", "img"]):
        tag.decompose()  # remove the node and all descendants
    # Drop ix:header entirely. It is a non-rendered machine-readable iXBRL region
    # containing XBRL context definitions (34,148 chars in measured MU-FY2024 and
    # 59,005 in INTC-FY2019). Unwrapping would release all of it into the first body block.
    for tag in soup.find_all("ix:header"):
        tag.decompose()
    for tag in soup.find_all(lambda tag: bool(tag.name and tag.name.startswith("ix:"))):
        tag.unwrap()  # remove other iXBRL tags while preserving their text and numbers
    return soup
```

**코드에서 꼭 볼 것**

- `decompose()`와 `unwrap()`의 차이가 이 함수의 전부다. 앞은 노드와 자손을 통째로 지우고, 뒤는 태그만 벗겨 안의 텍스트를 남긴다.
- `ix:header`만 `decompose`를 받는 이유는 렌더링되지 않는 XBRL 정의 영역이기 때문이다. unwrap하면 3만~6만 글자가 첫 본문 블록으로 쏟아진다.
- 나머지 `ix:*` 태그는 전부 `unwrap`이다. 재무 수치가 그 태그 안에 있으므로, 지우면 숫자가 지워진다.
- `html.parser`를 쓰는 이유는 주석에 있다. `lxml`이 더 빠르지만 `sourceline`을 비워 두기 때문에 좌표가 불가능해진다. 속도 대신 검증 가능성을 골랐다.

### 확인

```bash
uv run pytest tests/ingestion/test_01_blocks.py -k ixbrl_numbers_survive -v
```

숫자가 살아남는지(`unwrap`)와 XBRL 쓰레기가 안 들어오는지(`decompose`)를 양쪽으로 본다. `test_ixbrl_numbers_survive`는 코퍼스 없이 돈다.

**밟은 함정** — [B09](../04-bugs.md#b09) `ix:header` 래퍼 제거 · [B17](../04-bugs.md#b17) `lxml`은 위치를 안 채움

## 여기까지 왔을 때 설명할 수 있어야 하는 것

- **딕셔너리 대신 dataclass로 출력 계약을 고정하면 무엇이 달라지는가?**
  - **답:** 필드 이름과 기본값이 하나의 명시적인 스키마가 되어, 오타가 즉시 드러나고 편집기와 타입 검사기가 계약을 읽을 수 있다. `default_factory`를 쓰면 인스턴스끼리 가변 리스트를 공유하는 문제도 막는다.
- **`source_pos`가 없으면 파싱 결과를 왜 검증할 수 없게 되는가?**
  - **답:** 목차를 잘못 잡아도 Item 개수와 순서는 정상처럼 보일 수 있다. `source_pos`가 있어야 원문의 정확한 위치를 다시 열어 확인하고, 이후 청크도 검증 가능한 인용 좌표를 이어받는다.
- **`Literal`이 런타임에 강제하지 않는데도 선언하는 이유는 무엇인가?**
  - **답:** 허용되는 값의 목록을 독자와 정적 타입 검사기에게 한곳에서 보여주기 위해서다. 런타임 안전성은 판별·분류 함수가 그 값만 반환하도록 구현해서 확보한다.
- **좌표를 정규화 전에 확정해야 하는 이유는 무엇인가?**
  - **답:** 좌표는 디코딩한 원본 HTML을 가리키지만 정규화는 노드를 지우고 태그를 벗긴다. 파서가 처음 기록한 줄과 열 위치를 먼저 잡아야 변환된 트리에서 복원할 수 없는 원본 매핑이 남는다.
- **제거(`decompose`)와 언랩(`unwrap`)을 가르는 기준은 무엇인가?**
  - **답:** `decompose()`는 노드와 내용 전체를 지우므로 스크립트·스타일·화면에 표시되지 않는 `ix:header`에 쓴다. `unwrap()`은 껍데기만 벗기고 텍스트를 남기므로 나머지 iXBRL 태그 안의 재무 수치를 보존할 때 쓴다.

---

[모듈 개요](../03-build.md) · [다음: 블록과 속성 →](02-blocks-props.md)
