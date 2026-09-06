# M1.1 검증

> 이 프로젝트에서 가장 오래 걸린 건 파서를 짜는 게 아니라 **틀렸다는 걸 알아채는 것**이었다. [04-bugs.md](04-bugs.md)의 18건 중 절반 이상이 "실행은 성공했는데 결과가 틀린" 종류다.

---

## 지표 하나로는 부족하다

[F14](01-findings.md#f14)가 이 문서의 전제다. 네 지표가 **서로 다른 것**을 잡는다.

| 지표 | 잡는 것 | **못** 잡는 것 | 자동화 |
|---|---|---|---|
| ① 전체 파싱 | 크래시, 검증 실패 | 내용이 틀린 것 전부 | ✅ |
| ② **커버리지** | 통째로 버려진 텍스트 | **헤딩 누락** | ✅ |
| ③ SEC Item 대조 | 헤딩 누락·오탐 | 섹션 내부 경계 미세 오차 | ✅ |
| ④ **원본 위치 대조** | 헤딩이 정말 거기 있나 | — | **✗ 눈검사** |

②가 ③을 대신할 수 없는 이유:

```
정상:    [Item 7 본문 30k][Item 7A 본문 3k]   → 커버 96%
7A 놓침: [Item 7 본문 33k          ........]  → 커버 96%   ← 똑같다
```

놓친 헤딩의 내용이 앞 섹션에 흡수되어 **총량이 그대로**다.

반대로 ③이 ②를 대신할 수 없다. `ix:header` 유입([B09](04-bugs.md#b09))은 Item 개수·순서·중복을 **전부 통과**했고 커버리지에서만 드러났다.

---

## 한 번에 전부 돌리기

```bash
uv sync --group dev          # Run once
uv run pytest                # Checks ①②③ and per-layer unit tests
```

**골든값의 단일 출처는 `tests/ingestion/golden.py`다.** 아래 표들은 사람이 읽으라고 옮겨 적은 것이고, 단언은 전부 그 파일을 가져온다. 양쪽에 숫자를 적으면 드리프트가 재발한다.

### 테스트 레이아웃

`app/` 구조를 그대로 미러링한다. 새 모듈이 생기면 `tests/` 아래 같은 경로에 디렉터리를 만든다.

```
tests/
  __init__.py
  support.py                  공용 헬퍼 — need(). 픽스처 아님
  test_doc_sync.py            리포 메타 (app/ 무관)
  ingestion/                  ← app/ingestion/ 미러
    __init__.py
    conftest.py               코퍼스 픽스처 — P, manifest, blocks_by_doc, parsed, profiles_dir
    golden.py                 20문서 골든값
    test_01_blocks.py … test_08_items.py
```

**conftest를 루트에 두지 않는 이유.** 원칙은 *"픽스처는 그것을 쓰는 테스트가 **전부** 아래에 있는 가장 얕은 디렉터리에 산다"*. 지금 픽스처는 전부 `data/corpus/`에 묶여 있어서 수집 전용이다. 루트에 올리면 나중에 `tests/retrieval/`이 생겼을 때 쓰지도 않는 20문서 파싱 픽스처를 상속받게 된다. **지금은 진짜로 전역인 게 없어서 루트 conftest가 없다.**

**공용 함수는 `conftest.py`가 아니라 `support.py`에 둔다.** conftest는 pytest가 특별하게 로드하는 파일이고 디렉터리마다 하나씩 생기므로, `from conftest import ...`가 어느 것을 가리키는지 모호해진다.

**`__init__.py`를 두는 이유.** 미러링하면 `tests/ingestion/test_config.py`와 `tests/api/test_config.py`처럼 **파일 이름이 겹치는 일이 생긴다.** 패키지가 아니면 pytest가 "import file mismatch"로 죽는다.

**번호(`test_01_`…)는 `03-build.md`의 레이어 순서다.** 디렉터리가 구조를, 번호가 빌드 순서를 나타낸다. `pytest tests/ingestion -v`가 그대로 진행표로 읽힌다.

### 테스트 파일 대응표

| 파일 | 대응 | 코퍼스 | 시간 |
|---|---|---|---|
| `test_doc_sync.py` | 문서 코드 == 실제 소스 | ✗ | 0.3초 |
| `ingestion/test_01_blocks.py` | [L2·L3](03-build.md) 정규화·블록화 | ✅ | 18초 |
| `ingestion/test_02_rules.py` | [L4·L5](03-build.md) 속성·규칙 평가기 | **✗** | 0.1초 |
| `ingestion/test_03_segment.py` | [L7·L9](03-build.md) + **최종확인①** | ✅ | (공유) |
| `ingestion/test_04_validate.py` | [L10·L12](03-build.md) 상태·검증 | 일부 | (공유) |
| `ingestion/test_05_profile.py` | [L11·L13](03-build.md) 프로파일·수렴 | 일부 | 20초 |
| `ingestion/test_06_xref.py` | [L8](03-build.md) 페이지 조인 | ✅ | (공유) |
| `ingestion/test_07_coverage.py` | **최종확인②** | ✅ | (공유) |
| `ingestion/test_08_items.py` | **최종확인③** | ✅ | (공유) |

`test_02`·`test_04`(앞부분)·`test_05`(앞부분)는 **코퍼스가 필요 없다.** `parser.py`를 짜기 시작한 직후부터 바로 켜진다.

### 내 구현 채점하기

```bash
uv run pytest
uv run pytest tests/ingestion -v
```

두 명령 모두 `app/ingestion/parser.py`를 직접 가져옵니다. 아직 만들지 않은 함수를 쓰는 테스트는 **실패가 아니라 건너뜁니다**(`tests/support.py`의 `need()`). 따라서 `pytest` 출력이 그대로 진행 상황판이 됩니다.

```
3 passed, 306 skipped in 0.5s      ← L1 일부만 짠 상태
```

---

## 최종확인 ① — 전체 파싱

```bash
rm -rf data/profiles
uv run python -m app.ingestion.parser
```

```
집계: {'number': 15, 'xref': 5}
```

전부 `parsed`, 경고 0건이어야 한다.

**자동화** — `test_03_segment.py::test_segment_type_per_document`, `::test_aggregate_is_15_number_5_xref`, `::test_everything_parses_without_warnings`

---

## 최종확인 ② — 커버리지 ★가장 중요

```bash
uv run python -m app.ingestion.parser --coverage
```

분모(`n_chars`)를 `ParsedFiling`이 들고 나오므로 문서를 다시 파싱하지 않는다.

```
AMD-FY2019   전체   358,178  섹션   352,812  커버  98.5%
AMD-FY2020   전체   362,278  섹션   355,792  커버  98.2%
AMD-FY2021   전체   343,224  섹션   336,569  커버  98.1%
AMD-FY2022   전체   380,277  섹션   373,047  커버  98.1%
AMD-FY2023   전체   382,481  섹션   375,210  커버  98.1%
INTC-FY2019  전체   389,944  섹션   366,166  커버  93.9%
INTC-FY2020  전체   398,474  섹션   381,491  커버  95.7%
INTC-FY2021  전체   410,587  섹션   389,769  커버  94.9%
INTC-FY2022  전체   439,377  섹션   416,727  커버  94.8%
INTC-FY2023  전체   440,913  섹션   418,780  커버  95.0%
MU-FY2020    전체   311,918  섹션   302,485  커버  97.0%
MU-FY2021    전체   307,031  섹션   297,276  커버  96.8%
MU-FY2022    전체   292,828  섹션   282,421  커버  96.4%
MU-FY2023    전체   301,271  섹션   292,345  커버  97.0%
MU-FY2024    전체   312,017  섹션   303,550  커버  97.3%
NVDA-FY2020  전체   258,346  섹션   247,153  커버  95.7%
NVDA-FY2021  전체   294,000  섹션   282,319  커버  96.0%
NVDA-FY2022  전체   296,849  섹션   285,038  커버  96.0%
NVDA-FY2023  전체   306,714  섹션   295,261  커버  96.3%
NVDA-FY2024  전체   329,808  섹션   318,319  커버  96.5%
```

> 출처: `tests/ingestion/golden.py`의 `COVERAGE`. 위 표는 읽기용 사본이다.

### **100%는 목표가 아니다 — 상한도 검사한다**

표지·목차·서명은 SEC 기준으로 **어느 Item에도 속하지 않으므로** 정상 상한이 96~98%다. **100%에 가까우면 오히려 표지가 Item 1에 붙었다는 신호**라 의심해야 한다. 지표는 "높을수록 좋다"가 아니라 **"예상 구간 안에 있어야 한다"**.

| 타입 | 허용 구간 | 실측 |
|---|---|---|
| `number` | 95.0 ~ 99.0% | 96.02 ~ 98.50% |
| `xref` | 93.0 ~ 97.0% | 93.90 ~ 95.74% |

### 빠진 4~6%의 정체 (전부 의도된 것)

| 항목 | 규모 | 판정 |
|---|---|---|
| 표지 (SEC 체크박스, 시가총액 문구, 위임장 자료 참조) | 3~10k자 | 의도 — 어느 Item에도 안 속함 |
| 목차 표 | 1~2k자 | 의도 |
| Item 헤딩 줄 자체 | ~600자 | 의도 — `Section.reported_title`로 승격 |
| 서명·날짜 | ~500자 | 의도 |
| 반복 페이지 헤더 | INTC 5~9k자 | 의도 — 노이즈 필터 ([F11](01-findings.md#f11)) |
| INTC 첫 1~2페이지 | ~2k자 | 알려진 한계 (이미지 헤딩) |

`xref`가 더 낮은 건 Intel이 페이지마다 헤더를 넣어서 노이즈 필터가 더 많이 걷어내기 때문이다. **다만 구간은 겹친다** — 최저 `number`(NVDA-FY2020 95.67%)와 최고 `xref`(INTC-FY2020 95.74%)가 0.07pp 차이로 뒤집혀 있다. "xref가 전부 더 낮다"는 성립하지 않고 평균으로 봐야 한다.

### 틀렸을 때 의심할 곳

| 증상 | 원인 |
|---|---|
| **80%대** | `ix:header`의 래퍼를 제거하고 있다([B09](04-bugs.md#b09)). 문서당 34~59k자 XBRL 쓰레기가 분모에 들어간다 |
| 특정 문서만 급락 | 헤딩 하나를 놓쳐 그 뒤 구간이 통째로 사라졌다 |
| **99% 이상** | 표지·목차가 섹션에 유입됐다 |
| `xref`가 90% 미만 | 페이지 조인 실패 |

**자동화** — `test_07_coverage.py` (골든값 정확 일치 + 상·하한 + `n_chars` 캐리 확인)

---

## 최종확인 ③ — 경계 정확도

```bash
uv run python -m app.ingestion.parser --items
```

**누락은 전부 "그 해에 없던 Item"이어야 한다.**

| Item | 언제 생겼나 | 없어도 정상인 연도 |
|---|---|---|
| `1C` Cybersecurity | SEC 2023년 신설 | FY2022 이전 |
| `9C` Foreign Jurisdictions | HFCAA, 2021년 | FY2020 이전 |
| `16` Form 10-K Summary | **선택 항목** | 언제든 (NVDA-FY2020이 생략) |

실측 결과 **20개 전부 누락 0 · 과잉 0**이다(위 셋 제외).

```
AMD-FY2019   21개  누락=['1C', '9C']        과잉=-
AMD-FY2023   23개  누락=-                   과잉=-
NVDA-FY2020  20개  누락=['1C', '9C', '16']  과잉=-
NVDA-FY2024  23개  누락=-                   과잉=-
INTC-FY2023  23개  누락=-                   과잉=-
```

**과잉이 하나라도 나오면** 헤딩 오탐이고, **위 셋 외의 누락이 나오면** 헤딩을 놓친 것이다.

### 보조 지표 — 연도 간 크기 일관성

같은 회사·같은 Item의 크기가 특정 해만 튀면 그 해의 경계가 깨졌다는 신호다.

```
MU    Item 2   변동계수 0.56     778 ~   3,713자   짧은 섹션이라 절대폭이 작다
INTC  Item 3   변동계수 0.39  10,115 ~  32,121자   소송 건수가 해마다 다르다
NVDA  Item 1A  변동계수 0.26  46,627 ~ 106,653자   리스크 요인이 4년간 2배로 늘었다
INTC  Item 7   변동계수 0.25  33,445 ~  76,692자   ★아래 참고
```

**`INTC Item 7`의 FY2019만 작은 건 버그가 아니다.** Intel 자체 색인표가 그 해엔 "Our Products"(p17)를 Item 7이 아니라 **Item 1에 배정**했고, 실제로 FY2019는 Item 1이 다른 해보다 크다. 총량이 보존되고 **우리는 문서가 말하는 대로 따랐다.**

**자동화** — `test_08_items.py` (과잉 0, 누락은 `ALWAYS_OPTIONAL`만, 신설 전 연도에 안 나타나는지 역방향도, 핵심 Item 내용 유무, 위치 필드, `canonical_title`/`part` 일관성, SEC 순서)

---

## 최종확인 ④ — 원본 위치 대조 (눈검사)

**앞의 셋은 전부 간접 지표다.** 파서가 "Item 1A를 찾았다"고 주장할 때 그게 **정말 거기 있는지**는 원본을 직접 봐야 안다.

```bash
uv run python -m app.ingestion.parser \
  --file data/corpus/NVDA/2024-02-21_0001045810-24-000029.html --headings
```

```
--- NVDA-FY2024 (number) ---
  1    blk    65 pos    198007  Item 1. Business
       원본 '<div style="margin-bottom:6pt;margin-top:12pt;'
       본문 'NVIDIA pioneered accelerated computing to help solve t'
  1A   blk   215 pos    289841  Item 1A. Risk Factors
       원본 '<div style="margin-bottom:6pt;margin-top:12pt;'
       본문 'The following risk factors should be considered in add'
  1B   blk   462 pos    462881  Item 1B. Unresolved Staff Comments
       원본 '<div style="margin-bottom:6pt;margin-top:12pt;'
       본문 'Not applicable.'
```

### 그리고 파서 밖에서 독립적으로 확인한다 — 이게 핵심이다

**파서가 자기 주장을 자기 도구로 확인하면 순환**이라, 원본 파일을 직접 열어야 한다:

```bash
python3 -c "
import re
from pathlib import Path
raw = Path('data/corpus/NVDA/2024-02-21_0001045810-24-000029.html').read_text()
for pos in (198007, 289841, 462881, 463352):
    print(pos, repr(' '.join(re.sub('<[^>]+>', ' ', raw[pos:pos+300]).split())[:60]))
"
```

```
198007 'Item 1. Business <span style="color:#76b900;'
289841 'Item 1A. Risk Factors <span style="color:#000000;font-famil'
462881 'Item 1B. Unresolved Staff Comments <span style="color:#0000'
463352 'Item 1C. Cybersecurity <span style="color:#76b900;font-'
```

**나와야 하는 것** — 오프셋 바로 뒤가 그 Item의 헤딩 텍스트여야 한다. 어긋나면 `source_pos` 계산(줄 시작 오프셋 누락)이나 블록 매핑이 틀린 것이다([B17](04-bugs.md#b17)).

**본문 미리보기도 같이 본다.**

| 보이는 것 | 뜻 |
|---|---|
| `Item 1A` 뒤가 "The following risk factors…" | 경계가 맞다 |
| 앞 Item의 끝문단이 보인다 | 헤딩을 하나 놓쳤다 |
| "Not applicable."만 있어야 할 `1B`에 긴 본문 | 다음 헤딩을 놓쳤다 |

### 왜 이것만 자동화하지 않았나

오프셋 4개는 `tests/ingestion/golden.py`의 `NVDA_FY2024_OFFSETS`에 고정돼 있고 `test_08_items.py::test_sections_carry_their_position`이 위치 필드가 채워졌는지는 본다.

하지만 **"이 섹션의 내용이 말이 되는가"는 자동화할 수 없다.** Item 1A 뒤에 리스크 요인 서술이 오는지, Item 8 서두가 재무제표인지는 사람이 읽어야 판단된다. 골든값으로 박으면 "지금과 같은가"만 알 뿐 "옳은가"는 여전히 모른다.

**그래서 CLI를 남긴다.** pytest = 회귀(통과/실패), CLI = 탐색(눈검사).

---

## 내용 검수 결과 (20/20)

방법: 상태 코드가 아니라 **내용**을 검수. Item별 본문량·표 개수·서두 500자의 신호어 (Item 1A면 risk/adversely…, Item 8이면 balance sheet/opinion…) 대조.

| 그룹 | 타입 | 결과 |
|---|---|---|
| NVDA ×5 | `number` | Item 1 40~51k, 1A 46~107k, 7 32~39k. Item 8·11·13은 `incorporated_by_reference`(정상 — 재무제표가 Item 15 아래: 82k, 표 34개) |
| AMD ×5 | `number` (2019 별도 프로파일) | Item 8 85~109k + 표 19~40개 (FY2019 포함 — [B04](04-bugs.md#b04) 수정으로 회복) |
| INTC ×5 | `xref` | 페이지 조인. Item 7 33~77k, Item 8 88~116k(표 최대 65), Item 3은 2차 수색으로 확보, Part III는 참조 처리 |
| MU ×5 | `number` | Item 8 66~90k + 표 31~41개. Item 15의 0k는 별첨 문서 목록이 표라서(정상) |

**신호어 검수의 "불일치" 20건은 전수 확인 결과 전부 오탐이었다** — 예: NVDA Item 1 서두 "NVIDIA pioneered accelerated computing…"(정상), Item 15 서두가 재무제표 색인(정상).

알려진 한계는 [04-bugs.md](04-bugs.md#알려진-한계-버그가-아님)에 있다.
