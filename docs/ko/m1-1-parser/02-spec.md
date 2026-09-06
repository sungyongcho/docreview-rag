# M1.1 명세

> 여기는 **무엇을 만드는가**다. 어떻게 짜는가는 [03-build.md](03-build.md). 모든 근거는 [01-findings.md](01-findings.md)의 F번호로 링크한다.

---

## 한 문장

**SEC는 10-K의 "내용"(Part/Item)을 정하지만 "HTML 레이아웃"은 정하지 않는다.** 그래서 파서는 회사마다 다른 문서 구조를 **프로파일(데이터)**로 관리하고, `segmentation.type` 하나가 파싱 전략을 선택해 결정론적으로 파싱한다.

현재 20개 파일 전부 LLM 없이 파싱된다.

---

## 1. 전제: 무엇이 고정이고 무엇이 변하는가

**SEC가 고정한 것** — 코드 상수로 둔다.

| Part | Items | 내용 |
|---|---|---|
| I | 1, 1A, 1B, 1C, 2, 3, 4 | 사업, 리스크, 미해결 코멘트, 사이버보안(2023+), 자산, 소송, 광산 |
| II | 5, 6, 7, 7A, 8, 9, 9A, 9B, 9C | 주식, (예비), MD&A, 시장리스크, **재무제표**, 회계분쟁, 내부통제, 기타 |
| III | 10, 11, 12, 13, 14 | 이사·임원, 보수, 지분, 특수관계, 감사보수 — **대부분 위임장 자료로 위임** |
| IV | 15, 16 | 첨부문서 목록, 요약 |

각 Item의 표준 제목과 표준 순서도 고정이다. → 코드의 `CANONICAL` / `ORDER` / `PART_OF`.

**SEC가 규정하지 않은 것** — 회사별 프로파일로 관리한다.

- 제목의 HTML 표현 ([F1](01-findings.md#f1) — 시맨틱 태그 없음, 인라인 CSS만)
- 폰트·크기·표 안팎 여부 ([F3](01-findings.md#f3), [F4](01-findings.md#f4))
- Item 순서 재배치 가능
- **본문을 Item으로 나누는 것 자체** ([F5](01-findings.md#f5), [F6](01-findings.md#f6))

마지막 항목이 설계의 분기점이다. **"모든 10-K에는 Item 헤딩이 있다"는 가정이 성립하지 않는다.**

---

## 2. 처리 단계

```
① 정규화       HTML → 의미 있는 트리
② 블록화       트리 → 순서 있는 블록 리스트
③ 세그멘테이션  블록 리스트 → Item 섹션들      ← 프로파일이 지배하는 유일한 단계
④ 검증         섹션들이 말이 되는가
⑤ 출력         ParsedFiling
```

프로파일이 ③ 하나만 지배한다는 게 중요하다. ①②는 문서 종류와 무관하게 같고, ④는 타입에 따라 기준만 달라진다.

---

## 3. 세그먼트 유형 — 다섯 가지

`segmentation.type` 하나가 파싱 전략을 결정한다. 축은 **"Item 번호를 어디 보고 아는가"**다.

| `type` | 정의 |
|---|---|
| **`number`** | 본문 헤딩에 SEC Item 번호가 문자 그대로 적혀 있**고**, 그 헤딩들이 일관된 스타일을 갖는**다**. 번호 자체가 정답이어**서**, 스타일 규칙으로 헤딩을 거른 뒤 번호를 그대로 읽**는 것**. |
| **`sec_canonical`** | Item 번호는 없**고**, 헤딩 제목이 SEC 표준 제목과 일치한**다**. 표준을 그대로 써**서**, 헤딩을 거른 뒤 제목을 SEC 표준 제목표(코드 상수)와 대조하**는 것**. |
| **`custom_title`** | 번호도 표준 제목도 없**고**, 회사가 자기 어휘로 제목을 붙인**다**. 측정으로는 어느 Item인지 알 수 없어**서**, 제목→Item 매핑표(`order`)로 대조하**는 것**. |
| **`xref`** | 본문에 Item 경계가 아예 없**고**, 대신 SEC가 의무화한 Cross-Reference Index가 Item↔페이지를 알려준**다**. 거를 헤딩이 존재하지 않아**서**, 색인표와 기업 목차를 페이지로 조인해 경계를 긋**는 것**. |
| **`undefined`** | 판별이 전부 실패했**다**. 짚을 근거가 없어**서**, 사람이 볼 때까지 보류하**는 것**. |

이름이 `custom_item`이 아니라 `custom_title`인 이유: **Item은 SEC가 정한 것이라 자체일 수 없다.** 자체인 건 회사가 그 Item에 붙인 제목뿐이다.

### 기계적 대조

| | `number` | `sec_canonical` | `custom_title` | `xref` | `undefined` |
|---|---|---|---|---|---|
| **헤딩이 있나** | 있음 | 있음 | 있음 | Item 헤딩 없음 | — |
| **Item 식별 근거** | 헤딩의 번호 | SEC 표준 제목표 | `order` 매핑표 | 문서의 색인표 | 없음 |
| **경계 긋는 법** | 헤딩→다음 헤딩 | 헤딩→다음 헤딩 | 헤딩→다음 헤딩 | 페이지 구간 | — |
| **페이로드** | `rules` | `rules` | `rules` + `order` | 없음 | 없음 |
| **이 코퍼스** | 15/20 | 0/20 | 0/20 | 5/20 | 0/20 |

세 축이 어떻게 갈리는지가 요점이다.

- `number` · `sec_canonical` · `custom_title` — **경계 긋는 법이 같고 식별 근거만 다르다.** 같은 순회 루프에 대조 대상만 바뀐다.
- `sec_canonical` · `custom_title` — **대조 동작까지 같고 표의 출처만 다르다.** 그래도 타입을 나눈 건 페이로드를 채우는 주체가 다르기 때문이다(측정과 외부 입력).
- `xref` — **셋 다 다르다.** 그래서 페이로드가 비는 것도 이 하나뿐이다.

---

## 4. 세그멘테이션 로직

파싱은 독립된 두 질문이다.

> **A. 이 블록이 헤딩인가?** → `rules` (순수 스타일) **B. 이 헤딩이 어느 Item인가?** → 타입별로 다름

### 4.1 `number` / `sec_canonical` / `custom_title` — 공통 구조

블록을 순서대로 훑으며 각 블록에 대해:

1. **먼저 B를 푼다**

   | `type` | 무엇과 대조하나 |
   |---|---|
   | `number` | 블록 텍스트에 적힌 Item 번호 (`ITEM_RE`) |
   | `sec_canonical` | SEC 표준 제목표 (코드 상수 `CANONICAL`) |
   | `custom_title` | `order` 배열 — 제목 정확 일치 |

2. **그 다음 A를 검사** — `rules` 중 하나라도 통과하면 헤딩 3. 헤딩이면 새 섹션 시작, 아니면 현재 섹션에 본문으로 누적

**B가 A보다 먼저인 이유는 비용이다.** 텍스트 정규식·딕셔너리 조회는 즉시 끝나지만 `block_props()`는 CSS를 정규식으로 여러 번 훑는다. 2,400블록 중 Item 헤딩은 20여 개뿐이라 대부분이 B에서 탈락해 A까지 가지 않는다.

### 규칙 평가 규약

이걸 문장으로 못 박지 않으면 규칙을 쓰는 사람이 매번 헷갈린다.

| 규약 | 의미 |
|---|---|
| 지정하지 않은 키 | 제약 없음 |
| 수치 | **이상** (`font_size: 14` = 14pt 미만 탈락) |
| 불리언·문자열 | 일치 |
| `in_table` | `false`=표 밖만, `true`=제약 없음 (**비대칭**) |
| 리스트 전체 | 하나라도 통과하면 헤딩 |

`rules`가 **배열**인 이유: 회사가 헤딩을 여러 형식으로 쓸 수 있다.

`in_table`의 비대칭은 [F4](01-findings.md#f4)가 요구한다. 보기 싫지만 실측이 요구하면 따르되 규약 표에 굵게 적어둔다.

**조건은 순수 스타일뿐이다** — 문맥 조건(뒤 본문 분량·반복 횟수)은 규칙 어휘에 없다. [F13](01-findings.md#f13)이 이유고, [B13](04-bugs.md#b13)이 그 비용이었다.

### 4.2 `xref` — 페이지 조인

블록 순회로 헤딩을 찾는 방식이 통하지 않는다([F5](01-findings.md#f5)). 대신:

```
1. 두 표를 찾는다        색인표(Item N. 셀 5행↑) + 기업 목차표(제목|쪽수 10행↑)
2. 색인표를 해석한다      Item → (제목, 페이지 구간들, 상태)
3. 목차표를 해석한다      서사 제목 → 시작 페이지
4. 본문 위치를 찾는다      서사 제목이 본문 어느 블록에서 시작하나
5. Item을 배정한다        페이지 구간 겹침으로
6. 누락을 2차 수색한다     목차엔 없지만 색인표에 페이지가 있는 Item
7. 경계를 보정한다        헤딩이 이미지인 구간 (F8)
8. Item별로 합친다        같은 Item에 배정된 서사 섹션들을 한 Section으로
```

각 단계에서 밟은 함정은 [04-bugs.md의 L8 절](04-bugs.md#l8--세그멘테이션-b-xref-페이지-조인)에 전부 있다 — 2단계는 [B01](04-bugs.md#b01)·[B02](04-bugs.md#b02)·[B03](04-bugs.md#b03), 4단계는 [B10](04-bugs.md#b10), 5단계는 [B08](04-bugs.md#b08), 7단계는 [B06](04-bugs.md#b06)·[B07](04-bugs.md#b07).

**Item 배정 우선순위** (동점 처리):

```
1. 제목 단어 겹침이 많은 쪽
2. 덮는 구간이 좁은 쪽        ← Item의 총 페이지 폭이 아니라 '덮는 구간 하나'의 폭
3. Item 번호가 짧은 쪽         ← 완전 동점 시 결정성 확보
```

한 섹션은 한 Item에만 배정한다. **같은 블록이 두 Item에 중복 적재되지 않는다.** (같은 *텍스트*가 두 Item에 나올 수는 있다 — 원문이 실제로 두 번 싣는 경우가 있다.)

**상태 판정** — 색인표가 직접 알려준다:

| 색인표 셀 | 상태 |
|---|---|
| 페이지 구간 있음 | `parsed` (**최종 권한** — [B03](04-bugs.md#b03)) |
| 페이지 없음 + "Not applicable" | `empty_disclosure` |
| 페이지 없음 + 참조기호 `(a)` | `incorporated_by_reference` (각주 문장을 출처로 보존) |

---

## 5. 프로파일 생명주기

### 로드

```
data/profiles/{TICKER}.json 있나?
 ├ 없음 → 부트스트랩 (아래 '학습')
 └ 있음 → profiles[요청연도] 있나?
           ├ 있음 → 그것
           └ 없음 → profiles[default_year]
```

### 파싱과 검증

```
프로파일로 파싱 → 검증
 ├ 통과 → 끝
 └ 실패 → 이 문서로 재학습 → 재파싱 → 검증
           ├ 통과 → profiles[이 연도]에 저장   (연도 중간 레이아웃 변경 대응, F4)
           └ 실패 → 실패 상태로 반환 (★나쁜 규칙은 저장하지 않는다)
```

> **수렴은 3회차다, 2회차가 아니다.** `expected_items`가 연도마다 다르고 `default_year`가 최신을 가리키므로, 항목이 없는 옛 연도는 반드시 한 번 재학습을 거친다. 자가 복구되지만 멱등적이지 않다 — [04-bugs.md](04-bugs.md#프로파일-수렴이-2회차가-아니라-3회차다) 참조.

### 학습 (타입 판별)

프로파일이 없거나 검증이 실패했을 때, **그 문서를 측정해서** 타입을 정한다. 순서대로 시도하고 먼저 성립하는 것을 채택한다.

```
① number   측정 — 굵은 "Item N" 블록이 5개 이상 있나
② xref     측정 — 색인표 + 목차표가 둘 다 있나
③ undefined  ← 여기가 현재 코드의 끝
```

**①②의 순서에 근거가 있다.**

- ①이 가장 흔하고 가장 싸다(텍스트 정규식).
- **②를 ① 앞에 두면 안 된다.** 일반 10-K의 **목차도** `Item 1. Business … 3` 형태라 색인표와 구분이 안 된다. "본문에 Item 헤딩이 없다"가 먼저 확정돼야 안전하다.

실측 비용: 판별 전체가 **0.06~0.11초**. 지배적 비용인 HTML 파싱(0.31~0.69초)은 어느 방식을 쓰든 한 번 치러야 하고 판별이 그 결과를 공유한다.

각 판별 함수가 **판별기이자 페이로드 생성기**다. 반환값이 곧 답이다 — `{}`이면 "내 타입 아님", 채워져 있으면 "내 타입 + 설정 완성".

---

## 6. 검증

타입에 따라 기준이 다르다.

**`number` / `sec_canonical` / `custom_title`**

| 검사 | 내용 |
|---|---|
| 개수 | `expected_items`와 정확히 일치 |
| 순서 | `custom_title`이면 `order`의 순서, 아니면 SEC 표준 순서 |
| 중복 | 같은 Item이 두 번 나오면 실패 |
| 필수 | `must_have`가 모두 있어야 함 |
| **내용** | 핵심 Item(1·1A·7·8) 중 `CORE_THIN_COUNT`(2개) 이상이 블록 `CORE_THIN_BLOCKS`(20개) 미만이면 실패 |

마지막 항목이 중요하다. **목차를 헤딩으로 잡으면 개수·순서·중복이 전부 완벽한데 내용이 없다**([B10](04-bugs.md#b10)). 구조 검사만으로는 못 잡는다.

**`xref`**

| 검사 | 내용 |
|---|---|
| ~~순서~~ | 무의미 — Item이 문서에 흩어져 있는 게 정상 ([F7](01-findings.md#f7)) |
| ~~중복~~ | 무의미 — Item당 섹션 하나로 이미 합쳐짐 |
| **커버리지** | 색인표의 모든 Item이 {본문 배정 / 공시 없음 / 참조로 대체} 중 하나로 설명되는가 |
| 필수 | `must_have` |
| 얇은 섹션 | 비율이 과도하면 실패 |

`expected_items`를 저장하지 않는 이유가 여기 있다 — **색인표가 연도마다 직접 알려준다.**

**문제를 예외가 아니라 리스트로 반환한다.** `raise`하면 첫 문제에서 멈춰 나머지를 못 본다. 호출부는 `if problems:` 하나로 "재학습해야 하나"를 판단한다.

---

## 7. 출력 계약

<!-- src: app/ingestion/parser.py::SegmentType,ItemStatus,Block,Section,ParsedFiling -->
```python
SegmentType = Literal["number", "sec_canonical", "custom_title", "xref", "undefined"]
ItemStatus = Literal["parsed", "empty_disclosure", "incorporated_by_reference"]


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

**위치 3종의 쓰임이 다르다.**

| 필드 | 쓰임 |
|---|---|
| `block_index` | 파서 내부 디버깅 |
| `block_range` | 섹션 경계 자체의 검증. M1.3에서 청크가 덮는 블록 구간의 입력 |
| `source_pos` | **원본 파일과의 대조.** M1.3에서 **스팬 인용의 기반**이 된다 (아래) |

### `source_pos`가 왜 중요해졌나 — 스팬 인용

인용을 **청크 ID**로 달면 청킹 설정을 바꾸는 순간 정답이 가리키는 청크가 사라진다. 그러면 골든셋이 통째로 무효화되고, **청킹 어블레이션("왜 이 청킹인가"를 숫자로)을 아예 못 하게 된다.**

인용을 **원문 문자 오프셋**으로 달면 청킹과 무관하게 살아남는다. 채점은 정답 구간과의 **겹침(IoU)**으로 하므로 청크 경계가 정확히 일치할 필요도 없다.

그래서 M1.3에서:

```
Block.source_pos / Block.end_pos   ← Section에만 있던 것을 Block까지 내린다
        ↓ 청크를 구성한 블록들의 (min, max)
Chunk.start_char / Chunk.end_char  ← 검색 결과의 인용 좌표
```

`source_pos()`·`line_offsets()`는 **이미 있다**([L1](03-build.md)). Block으로 확장하는 것이 M1.3의 L5다. 사람이 읽는 `citation` 문자열("NVDA FY2024 · Item 7")은 그대로 두고, 스팬은 그 밑의 **기계 판정용 좌표**로 병행한다.

**`n_blocks`/`n_chars`를 결과에 담는 이유** — 커버리지 검증의 분모가 "문서 전체 텍스트"인데 안 담아두면 CLI가 검증할 때마다 문서를 다시 파싱한다. 실측 20개 기준 40초 → 18초 차이. **측정값은 측정한 곳에서 들고 나오는 게 싸다.** ([B18](04-bugs.md#b18))

**`status`의 의미** — 짧은 섹션은 대부분 버그가 아니라 정상 공시다. 출처가 타입마다 다르다: 제목·번호 기반 세 타입은 본문 텍스트로 **추정**하고, `xref`은 색인표가 **직접 알려주는 사실**이다. 후자는 `item_index`에 원본을 보존하므로 "이 Item은 Not applicable"이라고 근거를 갖고 답할 수 있다.

**`Section.canonical_title`은 세그먼트 타입과 무관하다.** 모든 타입에서 채워지는 "그 Item의 SEC 표준 제목"이고, `sec_canonical` 타입은 *그 제목을 매칭에 쓴다*는 뜻이다. 타입 이름을 `canonical_title`이 아니라 `sec_canonical`로 둔 이유가 이 혼동 차단이다.

---

## 8. 프로파일 스키마

`data/profiles/{TICKER}.json` — 한 파일 = 한 회사.

```json
{
  "ticker": "AMD",
  "default_year": "2023",
  "profiles": {
    "2019": {
      "segmentation": {
        "type": "number",
        "rules": [{ "font_weight": 700, "font_size": 10.0, "in_table": true }]
      },
      "validation": { "expected_items": 21, "must_have": ["1", "1A", "7", "8"] },
      "learned_from": "AMD-FY2019",
      "learned_by": "bootstrap",
      "learned_at": "2026-08-05T14:22:19+00:00"
    },
    "2023": {
      "segmentation": {
        "type": "number",
        "rules": [{ "font_weight": 700, "font_size": 10.0, "in_table": false }]
      },
      "validation": { "expected_items": 23, "must_have": ["1", "1A", "7", "8"] },
      "learned_from": "AMD-FY2023",
      "learned_by": "bootstrap",
      "learned_at": "2026-08-05T14:22:11+00:00"
    }
  }
}
```

`2019`가 `in_table: true`인 것이 [F4](01-findings.md#f4)의 흔적이다.

### 최상위 필드

| 필드 | 의미 |
|---|---|
| `ticker` | 회사 |
| `default_year` | 요청 연도가 `profiles`에 없을 때 쓸 연도. **항상 최신 연도** |
| `profiles` | 연도별 프로파일. **각 항목이 자기완결적** — 병합 규칙 없음 |

`default` + 오버라이드 구조를 쓰지 않는 이유: 병합 규칙이 필요 없어지고, `validation.expected_items`가 연도마다 다른 것(Item 1C 신설로 20~23 변동)이 자연스럽게 표현된다. **스키마 설계가 코드 복잡도를 직접 결정하는 예다** — `load_profile`이 3줄로 끝난다.

### 프로파일 필드

| 필드 | 의미 | 채워지나 |
|---|---|---|
| `segmentation` | Item 경계를 찾는 방법. 태그 유니온 (아래) | ✅ |
| `validation` | 파싱 결과 검증 기준 | ✅ |
| `learned_from` | 어느 문서에서 학습했나 | ✅ |
| `learned_by` | `bootstrap` / `llm` / `manual` | ✅ (현재 항상 `bootstrap`) |
| `learned_at` | 학습 시각 | ✅ |
| `evidence` | 판별 근거 측정값 | **✗ 미채움** — 설계에만 있다 |
| `description` | 사람이 읽을 한 줄 | **✗ 미채움** — 설계에만 있다 |

`evidence`/`description`은 "왜 이 타입인지 파일이 스스로 증명한다"는 좋은 아이디어지만 `build_profile`이 아직 채우지 않는다. 실제 `data/profiles/*.json`에 없다.

### `segmentation` — 태그 유니온

`type`이 태그이고 나머지가 그 타입의 페이로드다.

```json
{ "type": "number",        "rules": [ ... ] }
{ "type": "sec_canonical", "rules": [ ... ] }
{ "type": "custom_title",  "rules": [ ... ], "order": [ {"item": "1A", "title": "Our Risk Landscape"} ] }
{ "type": "xref" }
{ "type": "undefined" }
```

**선택 필드가 하나도 없다.** `order`는 `custom_title`의 필수 페이로드이고 다른 타입엔 아예 존재하지 않는다. `rules`도 `xref`·`undefined`엔 없다.

그래서 "`xref`엔 규칙 금지", "`order`는 여기서만" 같은 별도 검증 규칙이 필요 없다 — **스키마 자체가 그 규칙**이 되어 잘못된 조합을 만들 방법이 없어진다.

`sec_canonical`과 `custom_title`을 한 타입의 선택적 `order`로 묶지 않은 이유: **페이로드를 채우는 주체가 다르다.** 앞은 코드 상수와 대조하면 끝이고, 뒤는 외부에서 만든 배열이 반드시 있어야 동작한다. 하나로 묶으면 `order`가 선택 사항이 되고, "있으면 이렇게 없으면 저렇게"라는 조건부가 되살아난다.

---

## 9. 설계됨 · 미구현 ★

**이 절이 문서와 코드의 경계다.** 위의 명세 중 일부는 설계만 있고 코드가 없다. 섞어 적으면 "코드에 있다고 착각하고 호출하는" 사고가 난다.

### 타입별 구현 상태

`sec_canonical`과 `custom_title`은 **"미구현"이 아니라 "반만 구현"**이다. 세그멘테이션 경로는 전부 있고 **판별(학습) 함수만 없다.**

| 타입 | 세그멘테이션 | 판별(학습) | 코드 |
|---|---|---|---|
| `number` | ✅ | ✅ | `parser.py` `detect_number` / `segment_by_heading` |
| `xref` | ✅ | ✅ | `parser.py` `detect_xref` / `segment_by_xref` + `xref.py` |
| `undefined` | ✅ (빈 결과) | ✅ (폴백) | `parser.py` `detect_segmentation` / `segment` |
| `sec_canonical` | ✅ `find_item`의 `case` | **✗ 없음** | `match_canonical`은 있으나 **도달 불가** |
| `custom_title` | ✅ `find_item`의 `case` | **✗ 없음** | `order`를 만들 주체가 없음 |

`validate()`도 `custom_title`의 `order` 순서 분기를 이미 갖고 있다. **타입이 성립하기만 하면 파싱은 동작한다.** 없는 건 "이 문서가 그 타입이다"를 판정하는 부분뿐이다.

### 존재하지 않는 것

아래는 이전 설계 문서에 있었으나 **코드에 없다.** 호출하면 실패한다.

| 이름 | 상태 |
|---|---|
| `detect_sec_canonical` / `detect_custom_title` | 함수 없음 |
| `heading_candidates` / `derive_rules` | 함수 없음 |
| LLM 캐스케이드 ④(`order` 생성) · ⑤(구조 인식) | 없음. `llm_profile.py`는 삭제됨 |
| CLI `--allow-llm` | 플래그 없음 |
| CLI `--disable <type>` | 플래그 없음 |
| CLI `--all` | 플래그 없음 (인자 없이 실행하면 전체가 기본) |
| 프로파일 `evidence` / `description` | 스키마엔 있으나 `build_profile`이 안 채움 |

실제 CLI 플래그는 8개다 — [03-build.md의 L14](03-build.md) 참조.

### 후속 마일스톤에서 추가된 것

§7에서 예고했고 M1.2/M1.3이 구현한 필드와 모듈이다. M1.1 파서의 최초 완료 범위에는 없었지만 현재 코드에는 존재한다.

| 이름 | 상태 | 언제 |
|---|---|---|
| `Block.source_pos` / `Block.end_pos` / `source_group` | ✅ 구현 | [M1.3](../m1-3-chunk/02-spec.md) 선행 조건 |
| `Chunk.start_char` / `Chunk.end_char` | ✅ 구현 | [M1.3](../m1-3-chunk/02-spec.md) L1/L5 |
| `tables.py` (표 → 마크다운) | ✅ 구현 | [M1.2](../m1-2-tables/02-spec.md) |

`source_pos()`·`line_offsets()`를 재사용한 **확장**이다. `Block` 코드 블록은 소스 마커가 붙어 있어 `check_doc_code.py --fix`가 실제 코드에서 갱신한다.

### 정의됐지만 호출되지 않는 것

| 이름 | 상태 |
|---|---|
| `body_after()` | 정의만 있고 **호출부 없음**. `sec_canonical`/`custom_title` 학습용 ([F12](01-findings.md#f12)) |
| `match_canonical()` | `find_item`의 `sec_canonical` 분기에서만 호출 → **도달 불가** |
| `SegmentType` | 선언만 있고 **어디에도 어노테이션으로 안 쓰임**. `ParsedFiling.segment_type`은 `str` |

`ItemStatus`는 `Section.status`에 실제로 쓰인다.

**커버리지가 이걸 독립적으로 확인해준다.** 아래처럼 파서/xref와 수집 테스트 스위트만 범위를 좁히면 빠진 줄이 위의 휴면 분기와 CLI 경계에 모인다. 소스가 바뀔 때마다 낡는 줄 범위와 퍼센트를 문서에 고정하지 않는다.

```bash
uv run pytest --cov=app.ingestion.parser --cov=app.ingestion.xref --cov-report=term-missing tests/ingestion
```

즉 **"안 쓰는 코드"라는 주장은 실행 가능한 측정으로 확인한다.** `--cov=app` 전체 수치는 M0/M4 코드와 연습용 `parser.py`까지 섞으므로 M1.1 판단 기준으로 쓰지 않는다.

### 왜 지금 안 만드나

**도달하지 않는 코드를 먼저 짜면 검증할 방법이 없다.** 이 코퍼스는 `number`와 `xref`로 20/20이 끝나서 나머지 경로를 밟게 할 문서가 없다.

만들 때 지킬 것:

- `xref` 판별을 끄고 Intel로 검증한다 — 그러면 Intel이 정확히 `custom_title`이 겨냥한 상황(헤딩은 있는데 번호도 표준 제목도 아님)이 된다
- LLM이 개입한다면 **④와 ⑤는 배타적**이어야 한다. 한 실행에 최대 한 번
- **게이팅 먼저.** 플래그 없이 배치를 돌렸을 때 호출이 0인지부터 확인
- **규칙은 LLM이 아니라 코드가 만든다.** "어느 줄이 헤딩인가"는 물어도 "그 줄들을 덮는 CSS 규칙"은 묻지 않는다. 고른 줄의 실제 속성을 코드가 측정해서 도출한다

### 이 결론이 나온 실험

마지막 항목은 추측이 아니라 A/B 벤치마크 결과다. Intel 최신 연도의 헤딩 후보 목록을 같이 주고 두 프롬프트를 비교했다:

| | 프롬프트 | LLM이 만드는 것 |
|---|---|---|
| **A** | 제목→Item 매핑만 | `title_map` |
| **B** | 스타일 시그니처까지 심층 분석 | `heading_signals` + `title_map` + 구조 기술 |

**B가 추가로 만든 `heading_signals`(= CSS 규칙)가 자주 틀렸다.** 제목이 어느 Item인지는 잘 맞추는데, 그 제목들을 덮는 폰트 규칙을 스스로 도출하는 건 못 했다. 그래서 지금 설계는 LLM에게 **A만** 시키고 규칙 도출은 코드(`min()`으로 관측 전부를 덮는 가장 느슨한 규칙, [L9](03-build.md))가 한다.

> 실험 스크립트 `scripts/bench_llm_profile.py`는 삭제했다. 답이 나온 일회성 실험이었고, 지금은 없는 `visual_sig`·구 `parse_filing(html, meta, profile)` 시그니처·구 프로파일 스키마(`strategy`/`heading_signals`/`title_map`)에 묶여 있어 돌지도 않았다. 필요하면 `git show f06e59a:scripts/bench_llm_profile.py`.

원칙은 **"LLM은 측정의 경계 밖에서만 일한다"**다. 프로파일은 저장되어 그 회사 5년치를 지배하므로 **한 번 잘못 분류하면 영속화된다.** 반면 측정값("가중치 700에서 `Item N` 블록이 23개")은 틀릴 수가 없다.

---

## 10. 설계 원칙 요약

| 원칙 | 구현 |
|---|---|
| 규칙을 코드가 아니라 데이터로 | `rules`는 프로파일 JSON. 새 속성은 프로파일에 적기만 하면 됨 |
| 전략 선택도 데이터로 | `segmentation.type` 하나가 파싱 경로를 결정 |
| 싼 것부터, 실패가 감지될 때만 비싼 것으로 | 측정(0.1초) → (미구현) LLM. 점진적 기능 저하 |
| 상태를 잃지 않는다 | 판별 실패(`undefined`)도 저장. 재측정 반복 방지 |
| 나쁜 규칙은 저장하지 않는다 | 재학습은 **검증을 통과했을 때만** 저장 |
| 연도 변경은 예외가 아니라 사실 | `profiles`의 독립 항목. 병합 규칙 없음 |
| 종속 관계는 태그 유니온으로 | `type`이 페이로드를 결정 → 잘못된 조합이 표현 불가능 |
| 실패를 감지할 수 있어야 폴백이 성립한다 | 검증 지표 4종 ([F14](01-findings.md#f14)) |
