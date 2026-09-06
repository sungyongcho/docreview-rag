# M1.1 튜토리얼 4 — 드디어 문서를 자른다

앞의 다섯 층이 준비 작업이었다. 이제 실제로 문서를 Item 단위로 자른다.

코퍼스 20개 중 15개가 이 경로로 처리된다. 본문에 `Item 1A.` 같은 헤딩이 실제로 있는 경우다. 나머지 5개는 다음 문서에서 다룬다.

**선행 조건:** 튜토리얼 3의 `uv run pytest tests/ingestion/test_02_rules.py -v`가 전부 통과해야 한다.

## 무엇을 작성하고 어디를 직접 구현할까

| 구간 | 학습 행동 | 여기서 얻어야 하는 것 |
|---|---|---|
| L7 `_norm_title`·`match_canonical` | **구조 작성** | 표기가 흔들려도 같은 Item으로 모으는 법 |
| L7 `find_item` | 후보 선별을 **직접 구현** | 같은 `Item 1A` 중 하나만 진짜 헤딩인 이유 |
| L7 `segment_by_heading` | 워크 알고리즘을 **직접 구현** | 표지·목차를 버리고 본문만 남기는 경계 |

---

## L7 — 세그멘테이션 A — 드디어 문서를 자른다

지금까지 만든 걸 다 쓰는 레이어다. 블록 리스트(L3)를 위에서 아래로 훑으면서, 규칙 평가기(L5)로 헤딩을 찾고, 헤딩을 만날 때마다 새 섹션을 연다. 헤딩이 아닌 블록은 현재 열려 있는 섹션에 쌓는다.

`number` / `sec_canonical` / `custom_title` 세 타입이 **같은 루프**를 공유한다. 다른 건 "이 헤딩이 어느 Item인가"를 판정할 때 무엇과 대조하느냐뿐이다.

- `number` — 정규식 `ITEM_RE`로 번호를 뽑는다
- `sec_canonical` — SEC 표준 제목표와 대조한다
- `custom_title` — 프로파일에 적힌 매핑표와 대조한다

### 두 질문의 순서가 성능을 가른다

헤딩 판정은 두 질문으로 나뉜다.

① 이 텍스트가 **어느 Item을 가리키나** (식별) ② 이 블록이 **헤딩처럼 보이나** (서식 판별)

코드는 ①을 먼저 한다. 값싼 판별을 앞에 두는 원칙 때문이다. 텍스트 정규식과 딕셔너리 조회는 즉시 끝나지만, ②의 `block_props()`는 CSS 문자열을 정규식으로 여러 번 훑는다.

효과는 크다. 2,400개 블록 중 Item 헤딩은 20여 개뿐이다. 나머지 2,380개는 ①에서 탈락해서 비싼 ②까지 가지 않는다.

### `match`/`case`를 쓰는 이유

세 타입 분기를 `if/elif` 체인 대신 `match`/`case`로 쓴다. 분기가 오직 `type` 값 하나에만 걸린다는 사실이 구조로 드러나고, `case _`가 처리 안 된 값을 잡아준다. 파이썬 3.10+ 문법이다.

### 구현 — 세그멘테이션 A — 헤딩으로 문서를 가른다

먼저 `sec_canonical`이 쓰는 대조 함수부터 본다. **가드 두 개가 핵심이다.**

#### 대상 파일: `app/ingestion/parser.py`

<!-- src: app/ingestion/parser.py::_norm_title,match_canonical -->
```python
def _norm_title(s: str) -> str:
    """Normalize comparison text to lowercase ASCII letters and spaces."""
    return re.sub(r"[^a-z ]", "", s.lower()).strip()


def match_canonical(text: str) -> str | None:
    """Match text against canonical SEC titles and return its Item number.

    Two guards prevent accidental matches by short strings. Without them,
    measured false positives map "FORM 10-K" to Item 16, "Exhibit" to Item 15,
    and "Reserved" to Item 6.
    """
    t = _norm_title(text)
    if len(t) < CANON_MIN_CHARS:  # guard 1: defer when the candidate is too short
        return None
    for item, canon in CANONICAL.items():
        c = _norm_title(canon)
        if t == c:
            return item
        # Guard 2: permit prefix matching only with enough characters.
        if len(c) >= CANON_PREFIX_CHARS and (
            t.startswith(c[:CANON_PREFIX_CHARS]) or c.startswith(t[:CANON_PREFIX_CHARS])
        ):
            return item
    return None
```

이 함수는 접두 일치를 허용한다. 문서가 "Risk Factors"라고만 쓸 수도 있고 "Risk Factors Related to Our Business"라고 쓸 수도 있어서다. 그런데 느슨하게 열면 사고가 난다.

가드를 빼고 실측하면 이런 일이 벌어진다([B11](../04-bugs.md#b11)).

```
"FORM 10-K"  →  Item 16 (Form 10-K Summary)
"Exhibit"    →  Item 15 (Exhibits and ...)
"Reserved"   →  Item 6  (Reserved)
```

표지의 "FORM 10-K"가 Item 16 헤딩으로 둔갑한다. 짧은 문자열은 우연히 겹칠 확률이 높기 때문이다.

그래서 두 축으로 막는다. **후보 길이 하한 `CANON_MIN_CHARS`(8자)** 로 너무 짧은 후보를 아예 거르고, **접두 길이 `CANON_PREFIX_CHARS`(14자)** 로 접두 일치를 쓸 자격 자체를 제한한다. 느슨한 매칭을 도입할 때는 이런 하한을 같이 설계해야 한다.

<!-- src: app/ingestion/parser.py::find_item -->
```python
def find_item(el: Tag, text: str, seg: dict) -> str | None:
    """Return the Item number when this block is an Item heading, otherwise ``None``."""
    # First determine which Item the text names.
    match seg["type"]:
        case "number":
            m = ITEM_RE.match(text)
            item = (m.group("num") + (m.group("suffix") or "")).upper() if m else None
        case "sec_canonical":
            item = match_canonical(text)  # compare against the canonical SEC title table
        case "custom_title":
            low = text.strip().lower()
            item = next(
                (e["item"] for e in seg["order"] if e["title"].strip().lower() == low),
                None,
            )
        case _:
            return None
    if item is None:
        return None

    # Then use presentation alone to decide whether it is a heading.
    return item if matches_any(el, seg["rules"]) else None
```

`custom_title` 분기만 유독 정확 일치(`==`)를 쓰는 게 눈에 띈다. 바로 위 `sec_canonical`은 접두 일치를 허용했는데 왜 여기선 아닐까.

차이는 **정답을 아느냐**다. `sec_canonical`은 SEC 표준 제목과 문서가 실제 쓴 제목이 다를 수 있어서 느슨함이 필요하다. 반면 `custom_title`은 그 회사가 쓰는 제목을 프로파일에 그대로 적어둔 것이다. 정답을 이미 아는데 느슨하게 볼 이유가 없다.

느슨하게 하면 실제로 깨진다. 부분 일치를 쓰면 "Risk Factors"가 "Risk Factors Summary" 같은 하위 소제목까지 잡아서 같은 Item이 두 번 생성된다([B14](../04-bugs.md#b14)).

### 헤딩이 아닌 블록도 종류를 나눈다

헤딩으로 판정되지 않은 블록은 현재 섹션에 쌓는데, 그냥 쌓는 게 아니라 세 종류로 나눠 담는다.

#### 대상 파일: `app/ingestion/parser.py`

<!-- src: app/ingestion/parser.py::_body_block -->
```python
def _body_block(
    el: Tag,
    text: str,
    start_char: int | None = None,
    end_char: int | None = None,
    source_group: int = 0,
    source_heading: str | None = None,
) -> Block:
    """Convert a non-Item source element into the output Block contract."""
    if el.name == "table":
        return Block(
            "table",
            "",
            html=str(el),
            source_pos=start_char,
            end_pos=end_char,
            source_group=source_group,
            source_heading=source_heading,
        )
    if len(text) <= SUBHEADING_MAX_CHARS and block_props(el)["font_weight"] >= 700:
        return Block(
            "heading",
            text,
            level=2,
            source_pos=start_char,
            end_pos=end_char,
            source_group=source_group,
            source_heading=source_heading,
        )  # narrative subheading
    return Block(
        "paragraph",
        text,
        source_pos=start_char,
        end_pos=end_char,
        source_group=source_group,
        source_heading=source_heading,
    )
```

여기서 다음 두 모듈로 이어지는 연결선이 두 개 생긴다.

**표 블록**은 텍스트를 비워두고 원문 HTML을 `html` 필드에 통째로 담는다. 표는 텍스트로 펴는 순간 행·열 관계가 사라지기 때문이다. **M1.2가 이 HTML을 받아 마크다운 표로 변환한다.**

**level-2 헤딩**("Gross Margin" 같은 소제목)은 Item 헤딩과 달리 섹션을 새로 열지 않고 **블록으로 남는다.** 이게 나중에 쓸모가 있다. **M1.3이 청킹할 때 이 소제목을 청크의 문맥 헤더로 붙인다.** "이 문단은 Item 7의 Gross Margin 절에서 나왔다"는 정보가 검색 품질을 크게 올린다.

이제 본 루프다.

<!-- src: app/ingestion/parser.py::segment_by_heading -->
```python
def segment_by_heading(
    blocks: list[Tag],
    seg: dict,
    offsets: list[int] | None = None,
    source_end: int | None = None,
) -> list[Section]:
    """Start a section at each heading and append other blocks in one pass."""
    texts = [b.get_text(" ", strip=True) for b in blocks]
    source_spans = block_source_spans(blocks, offsets, source_end)
    sections: list[Section] = []
    current: Section | None = None

    for i, el in enumerate(blocks):
        text = texts[i]
        if not text:
            continue
        # A long paragraph cannot be a heading; apply the cheapest filter first.
        item = find_item(el, text, seg) if len(text) < HEADING_MAX_CHARS else None

        if item:
            if current is not None:  # the previous section ends here
                current.block_range = (current.block_index or 0, i)
            current = Section(
                part=PART_OF.get(item),
                item=item,
                canonical_title=CANONICAL.get(item, ""),
                reported_title=text[:REPORTED_TITLE_MAX],
                block_index=i,
                source_pos=source_pos(el, offsets) if offsets else None,
            )
            sections.append(current)
        elif current is not None:
            current.blocks.append(_body_block(el, text, *source_spans[i]))
        # Before the first Item, discard cover and TOC blocks that belong to no section.
    if current is not None:
        current.block_range = (current.block_index or 0, len(blocks))
    return sections
```

이 짧은 루프에 놓치기 쉬운 결정이 두 개 들어 있다.

### 첫 헤딩 이전의 블록은 어디로 가나

`current`가 아직 `None`인 구간 — 표지, 목차, 서문 — 의 블록은 **버려진다.** `elif current is not None`이라 `current`가 없으면 아무 데도 안 담긴다.

이게 의도다. 그 구간은 어느 Item에도 속하지 않으니 담을 곳이 없다. 나중에 "문서 전체 대비 섹션 합계"로 커버리지를 재면 100%가 안 나오는데, 그 차이의 대부분이 여기서 생긴다.

중요한 건 **버린다는 사실을 코드가 명시하고 있다**는 점이다. `if item: ... else: store`로 썼다면 표지가 첫 섹션에 딸려 들어갔을 것이고, 나중에 "왜 Item 1에 표지 내용이 있지?"를 추적하게 된다. 반대로 지금 형태는 "왜 표지가 없지?"라는 질문에 코드가 바로 답한다.

### 경계는 두 번 닫는다

`block_range`를 채우는 곳이 두 군데다. 다음 헤딩을 만났을 때 직전 섹션을 닫고 (`current.block_range = (..., i)`), 루프가 끝난 뒤 마지막 섹션을 한 번 더 닫는다.

루프 안에서만 처리하면 **마지막 섹션의 경계가 영영 안 채워진다.** 다음 헤딩이 없으니 닫아줄 사람이 없기 때문이다. 누적 상태를 들고 도는 루프에서 자주 나오는 실수라, "루프가 끝난 뒤 마지막 하나를 처리한다"는 패턴을 기억해두면 좋다.

### 확인

L13의 `parse_filing`을 아직 정의하지 않았으므로 `parsed` 픽스처를 요구하는 전체 테스트는 지금 실행하지 않는다. 대신 완성된 헤딩 순회 함수를 직접 호출한다.

```bash
PARSER_MODULE=app.ingestion.parser uv run python -c "
from app.ingestion.parser import normalize, leaf_blocks, segment_by_heading
from pathlib import Path
soup = normalize(Path('data/corpus/NVDA/2024-02-21_0001045810-24-000029.html').read_text())
seg = {'type': 'number', 'rules': [{'font_weight': 700, 'font_size': 10.0, 'in_table': False}]}
secs = segment_by_heading(leaf_blocks(soup), seg)
print(len(secs), [s.item for s in secs])
for s in secs[:3]:
    print(f'  {s.item:4} blk{s.block_index} {sum(len(b.text) for b in s.blocks):>7,}자  {s.reported_title[:40]}')
"
```

**나와야 하는 값** — 23개, SEC 표준 순서(`['1','1A','1B','1C','2',…]`), Item 1이 약 51k자. 개수가 40+면 상호참조까지 잡은 것이고, 0개면 규칙이 안 맞은 것이다.

**반드시 확인할 것**

| 확인 | 왜 |
|---|---|
| **중복 Item 0개** | 하나라도 있으면 규칙이 느슨하다 |
| **INTC 5개가 전부 `detect_number` 실패** | 성공하면 목차를 헤딩으로 잡은 것 |
| Item 수가 연도별로 20→23 증가 | 정상. Item 1C가 2023년 신설, 9C가 2021년 |
| **Item 15가 82k + 표 34개** | NVDA는 재무제표를 Item 15 아래에 싣는다. 여기가 두꺼운 게 정상 |

**틀렸을 때** — Item 수가 40+면 상호참조까지 잡은 것(`ITEM_RE`의 `^` 앵커 확인). 0개면 `in_table` 비대칭 처리를 뒤집었을 가능성.

**밟은 함정** — [B11](../04-bugs.md#b11) 짧은 제목 오탐 · [B14](../04-bugs.md#b14) 부분 일치 중복

## 여기까지 왔을 때 설명할 수 있어야 하는 것

- **문서 곳곳의 같은 `Item 1A` 문자열 중 하나만 헤딩인 것을 무엇으로 가르는가?**
  - **답:** `find_item`은 먼저 블록 시작에서 Item을 지칭하는 텍스트인지 확인한 뒤 학습한 서식 규칙을 적용한다. 시작 앵커와 표 안팎 규칙이 문장 중간 참조와 목차 항목을 걸러낸다.
- **표기가 흔들리는 Item 제목을 정식 이름으로 모으는 방법은 무엇인가?**
  - **답:** `_norm_title`로 보고된 제목을 정규화하고 `match_canonical`이 길이 하한을 둔 접두 일치로 SEC 표준 제목과 비교한다. 회사별 제목이 프로파일에 이미 들어 있다면 정확한 매핑을 쓴다.
- **표지와 목차를 버리는 판단은 어느 단계에서 이뤄지는가?**
  - **답:** `segment_by_heading`에서 아직 Item 헤딩이 `current`를 열지 않은 동안 비헤딩 블록을 어디에도 넣지 않는다. 따라서 첫 실제 Item 앞의 표지와 목차가 의도적으로 버려진다.
- **이 경로가 코퍼스 20개 중 15개만 처리하는 이유는 무엇인가?**
  - **답:** 이 15개 문서에는 워크가 찾을 수 있는 명시적인 Item 헤딩이 있다. Intel 문서 5개는 서사형 제목을 쓰므로 Cross-Reference Index와 목차를 이용하는 별도 경로가 필요하다.
- **헤딩 워크가 찾은 경계를 소스 좌표로 되돌리는 지점은 어디인가?**
  - **답:** `segment_by_heading`이 `block_source_spans`를 미리 만들고, Item 헤딩에는 `source_pos`를 저장하며 본문에는 `_body_block`으로 각 구간을 넘긴다. 이 지점에서 블록 인덱스가 원문의 절대 오프셋으로 바뀐다.

---

[← 이전: 규칙 평가기](03-rules.md) · [모듈 개요](../03-build.md) · [다음: xref 세그멘테이션 →](05-segment-xref.md)
