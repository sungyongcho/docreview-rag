# M1.1 Verification

> The longest part of this project was not writing the parser, but **realizing that it was wrong**. More than half of the eighteen cases in [04. Debugging History](04-bugs.md) are cases where "execution succeeded, but the result was wrong."

---

## One Metric Is Not Enough

[F14](01-findings.md#f14) is the premise of this document. The four metrics catch **different things**.

| Metric | What it catches | What it **does not** catch | Automated |
|---|---|---|---|
| ① Full parse | Crashes and validation failures | Every kind of incorrect content | ✅ |
| ② **Coverage** | Text discarded wholesale | **Missing headings** | ✅ |
| ③ SEC Item comparison | Missing headings and false positives | Small internal section-boundary errors | ✅ |
| ④ **Source-position comparison** | Whether a heading is really there | — | **✗ visual review** |

Why ② cannot replace ③:

```
정상:    [Item 7 본문 30k][Item 7A 본문 3k]   → 커버 96%
7A 놓침: [Item 7 본문 33k          ........]  → 커버 96%   ← 똑같다
```

The content following a missed heading is absorbed into the preceding section, so **the total amount stays the same**.

Conversely, ③ cannot replace ②. The `ix:header` leak ([B09](04-bugs.md#b09)) passed **every** Item count, order, and duplicate check and was exposed only by coverage.

---

## Run Everything at Once

```bash
uv sync --group dev          # Run once
uv run pytest                # Checks ①②③ and per-layer unit tests
```

**The single source of truth for golden values is `tests/ingestion/golden.py`.** The tables below are copies for human readers; every assertion imports that file. Writing the numbers in both places would reintroduce drift.

### Test Layout

The tests mirror the `app/` structure exactly. When a new module is added, create a directory at the same path under `tests/`.

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

**Why the conftest is not at the root.** The principle is: *"A fixture lives in the shallowest directory that contains **all** tests using it."* The current fixtures are all tied to `data/corpus/`, so they are ingestion-only. Moving them to the root would make a future `tests/retrieval/` directory inherit the twenty-document parsing fixture even though it never uses it. **Nothing is truly global today, so there is no root conftest.**

**Do not put shared functions in `conftest.py`; put them in `support.py`.** Pytest loads conftest files specially, and each directory may contain one, making it ambiguous which file `from conftest import ...` refers to.

**Why include `__init__.py`.** Mirroring creates duplicate filenames such as `tests/ingestion/test_config.py` and `tests/api/test_config.py`. Without packages, pytest fails with "import file mismatch."

**The numbers (`test_01_`…) follow the layer order in `03-build.md`.** Directories represent structure, while the numbers represent build order. The output of `pytest tests/ingestion -v` therefore reads like a progress chart.

### Test File Map

| File | Corresponds to | Corpus | Time |
|---|---|---|---|
| `test_doc_sync.py` | Document code == actual source | ✗ | 0.3s |
| `ingestion/test_01_blocks.py` | [L2·L3](03-build.md) normalization and block extraction | ✅ | eighteen seconds |
| `ingestion/test_02_rules.py` | [L4·L5](03-build.md) attributes and rule evaluator | **✗** | one tenth of a second |
| `ingestion/test_03_segment.py` | [L7·L9](03-build.md) + **final check ①** | ✅ | (shared) |
| `ingestion/test_04_validate.py` | [L10·L12](03-build.md) status and validation | Some | (shared) |
| `ingestion/test_05_profile.py` | [L11·L13](03-build.md) profiles and convergence | Some | twenty seconds |
| `ingestion/test_06_xref.py` | [L8](03-build.md) page join | ✅ | (shared) |
| `ingestion/test_07_coverage.py` | **final check ②** | ✅ | (shared) |
| `ingestion/test_08_items.py` | **final check ③** | ✅ | (shared) |

The first parts of `test_02`, `test_04`, and `test_05` **do not require the corpus**. They become active as soon as implementation of `parser.py` begins.

### Grade Your Implementation

```bash
uv run pytest
uv run pytest tests/ingestion -v
```

Both commands import `app/ingestion/parser.py` directly. A test that uses a function not yet implemented is **skipped, not failed**. `tests/support.py` uses `need()` for this purpose, so the `pytest` output becomes a live progress board:

```
3 passed, 306 skipped in 0.5s      ← L1 일부만 짠 상태
```

---

## Final Check ① — Full Parse

```bash
rm -rf data/profiles
uv run python -m app.ingestion.parser
```

```
집계: {'number': 15, 'xref': 5}
```

Every document must be `parsed`, with 0 warnings.

**Automation**—`test_03_segment.py::test_segment_type_per_document`, `::test_aggregate_is_15_number_5_xref`, `::test_everything_parses_without_warnings`

---

## Final Check ② — Coverage ★Most Important

```bash
uv run python -m app.ingestion.parser --coverage
```

Because the denominator (`n_chars`) is carried by `ParsedFiling`, the document is not parsed again.

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

> Source: `tests/ingestion/golden.py`, in `COVERAGE`. The table above is a reader-facing copy.

### **100% Is Not the Goal — Check the Upper Bound Too**

The cover, TOC, and signatures belong to **no Item under the SEC definition**, so the normal upper bound is 96~98%. **Coverage near 100% is instead a warning that the cover may have been attached to Item One.** The metric is not "higher is better"; it must **remain within the expected range**.

| Type | Allowed range | Measured |
|---|---|---|
| `number` | 95.0 ~ 99.0% | 96.02 ~ 98.50% |
| `xref` | 93.0 ~ 97.0% | 93.90 ~ 95.74% |

### What the Missing 4~6% Contains (All Intentional)

| Content | Scale | Assessment |
|---|---|---|
| Cover (SEC checkboxes, market-cap text, proxy references) | 3~10k characters | Intentional—belongs to no Item |
| TOC table | 1~2k characters | Intentional |
| Item heading lines themselves | About six hundred characters | Intentional—promoted to `Section.reported_title` |
| Signatures and dates | About five hundred characters | Intentional |
| Repeated page headers | INTC 5~9k characters | Intentional—noise filter ([F11](01-findings.md#f11)) |
| INTC page 1 and the following page | ~2k characters | Known limitation (image headings) |

`xref` is lower because Intel puts a header on every page, causing the noise filter to remove more. **The ranges still overlap**, however: the lowest `number` value (NVDA-FY2020 95.67%) and the highest `xref` value (INTC-FY2020 95.74%) reverse order by 0.07pp. The claim "every xref value is lower" is false; compare averages instead.

### Where to Look When It Is Wrong

| Symptom | Cause |
|---|---|
| **80% range** | `ix:header` is being unwrapped ([B09](04-bugs.md#b09)). 34~59k characters of XBRL garbage per document inflate the denominator |
| Only one document drops sharply | One missed heading caused the entire following region to disappear |
| **99% or higher** | Cover or TOC leaked into a section |
| `xref` below 90% | Page join failed |

**Automation**—`test_07_coverage.py` (exact golden-value match + upper and lower bounds + `n_chars` carry check)

---

## Final Check ③ — Boundary Accuracy

```bash
uv run python -m app.ingestion.parser --items
```

**Every missing Item must be one that did not exist in that year.**

| Item | Introduced | Years where absence is normal |
|---|---|---|
| `1C` Cybersecurity | Introduced by the SEC in the year twenty twenty-three | Before FY2022 |
| `9C` Foreign Jurisdictions | HFCAA, in the year twenty twenty-one | Before FY2020 |
| `16` Form 10-K Summary | **Optional Item** | Any year (omitted by NVDA-FY2020) |

Measured results show **0 missing and 0 extra Items in all twenty documents**, excluding the three above.

```
AMD-FY2019   21개  누락=['1C', '9C']        과잉=-
AMD-FY2023   23개  누락=-                   과잉=-
NVDA-FY2020  20개  누락=['1C', '9C', '16']  과잉=-
NVDA-FY2024  23개  누락=-                   과잉=-
INTC-FY2023  23개  누락=-                   과잉=-
```

**Any extra Item** is a heading false positive, while **a missing Item other than the three above** means a heading was missed.

### Supporting Metric — Size Consistency Across Years

If the size of the same company's same Item jumps in only one year, that year's boundary may be broken.

```
MU    Item 2   변동계수 0.56     778 ~   3,713자   짧은 섹션이라 절대폭이 작다
INTC  Item 3   변동계수 0.39  10,115 ~  32,121자   소송 건수가 해마다 다르다
NVDA  Item 1A  변동계수 0.26  46,627 ~ 106,653자   리스크 요인이 4년간 2배로 늘었다
INTC  Item 7   변동계수 0.25  33,445 ~  76,692자   ★아래 참고
```

**The small FY2019 value for `INTC Item 7` is not a bug.** Intel's own index assigned "Our Products" (p17) to **Item One**, not Item Seven, that year; accordingly, FY2019 Item One is larger than in other years. The total is preserved, and **the parser follows what the document says**.

**Automation**—`test_08_items.py` (0 extras, only `ALWAYS_OPTIONAL` may be missing, reverse check that Items do not appear before their introduction year, core Item content, position fields, `canonical_title`/`part` consistency, and SEC order)

---

## Final Check ④ — Source-Position Comparison (Visual Review)

**The first three are all indirect metrics.** When the parser claims "Item 1A was found," the only way to know whether it is **really there** is to inspect the source.

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

### Then Verify Independently, Outside the Parser — This Is the Key

**Using the parser's own tools to verify its claim would be circular**, so open the source file directly:

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

**Expected result**—The text immediately after each offset must be that Item's heading. A mismatch means the `source_pos` calculation (missing line-start offset) or block mapping is wrong ([B17](04-bugs.md#b17)).

**Inspect the body preview as well.**

| What appears | Meaning |
|---|---|
| "The following risk factors…" follows `Item 1A` | The boundary is correct |
| The preceding Item's final paragraph appears | A heading was missed |
| A long body appears in `1B`, which should contain only "Not applicable." | The next heading was missed |

### Why This Check Alone Is Not Fully Automated

The four offsets are locked down in `tests/ingestion/golden.py` as `NVDA_FY2024_OFFSETS`, and `test_08_items.py::test_sections_carry_their_position` checks that position fields are populated.

However, **"does this section's content make sense?" cannot be automated.** A person must judge whether a risk-factor narrative follows Item 1A and whether the section containing financial statements begins with them. A golden value can say only "it matches the current result," not "the current result is correct."

**That is why the CLI remains.** pytest = regression (pass/fail), CLI = exploration (visual review).

---

## Content Review Results (20/20)

Method: Review **content**, not status codes. Compare body length, table count, and cue words in the first five hundred characters for every Item (risk/adversely… for Item 1A, balance sheet/opinion… for Item 8).

| Group | Type | Result |
|---|---|---|
| NVDA ×5 | `number` | Item 1 40~51k, 1A 46~107k, 7 32~39k. Items 8 and 11, as well as the thirteenth Item, are `incorporated_by_reference` (correct—the financial statements are under Item 15: 82k, thirty-four tables) |
| AMD ×5 | `number` (separate 2019 profile) | Item 8 85~109k + between 19 and forty tables (including FY2019—restored by the [B04](04-bugs.md#b04) fix) |
| INTC ×5 | `xref` | Page join. Item 7 33~77k, Item 8 88~116k (up to 65 tables), Item Three recovered by the second search, Part III handled as incorporated by reference |
| MU ×5 | `number` | Item 8 66~90k + between 31 and forty-one tables. Item Fifteen's 0k is correct because the exhibit list is a table |

Manual review found **all twenty cue-word "mismatches" to be false positives**. For example, NVDA Item 1 starts with "NVIDIA pioneered accelerated computing…" (correct), and Item 15 starts with the financial-statement index (correct).

Known limitations are listed in [04-bugs.md](04-bugs.md#known-limitations-not-bugs).
