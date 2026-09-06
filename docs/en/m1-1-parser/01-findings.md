# M1.1 Findings

> This document is the **single source of truth for measurements**. Every other document only links here, as in `[F9](01-findings.md#f9)`, rather than restating the evidence.
>
> Corpus: NVDA · AMD · INTC · MU × five years = twenty files (`data/corpus/manifest.json`)

None of the design decisions rests on something that merely "looks right." Every statement below was measured directly from this corpus, and every choice in section 02 of [the specification](02-spec.md) follows from these findings.

**Reproducibility notation** — indicates whether each figure can still be reproduced.

| Mark | Meaning |
|---|---|
| ✅ | Remeasured while writing this document and confirmed to match |
| 🔄 | Figure updated (different from the original record; the updated value is shown) |
| 📌 | Locked by a test (regression-monitored under `tests/`) |

---

## At a glance

| # | Finding | Decision | Layer |
|---|---|---|---|
| [F1](#f1) | There is no semantic HTML | Detect headings with style rules | [L4·L5](03-build.md) |
| [F2](#f2) | The text "Item 1A" appears multiple times | Combine the `^` anchor with style | [L7](03-build.md) |
| [F3](#f3) | Layout is consistent within a company | Company-level profiles | [L11](03-build.md) |
| [F4](#f4) | A year change can break even the same company | Per-year profiles + relearning | [L11·L13](03-build.md) |
| [F5](#f5) | Intel has no Item headings in the body | **Change the strategy itself** (`xref`) | [L8·L9](03-build.md) |
| [F6](#f6) | The SEC requires a Cross-Reference Index | Basis for the `xref` type | [L8](03-build.md) |
| [F7](#f7) | One Item = multiple narrative sections | Assign by page-range overlap | [L8](03-build.md) |
| [F8](#f8) | Some headings are images | Correct boundaries with page footers | [L8](03-build.md) |
| [F9](#f9) | Older files put a `<div>` in every table cell | Separate data tables from layout tables | [L3](03-build.md) |
| [F10](#f10) | Unwrap iXBRL, but remove `ix:header` | `unwrap` vs `decompose` | [L2](03-build.md) |
| [F11](#f11) | Real headings occur once; false ones repeat | Filter noise while assembling the body | [L8](03-build.md) |
| [F12](#f12) | Following body volume separates TOC entries from headings | Learning filter (**currently unused**) | [L6](03-build.md) |
| [F13](#f13) | `number` did not need contextual signals | Remove contextual conditions from the rule vocabulary | [L5·L6](03-build.md) |
| [F14](#f14) | One validation metric is not enough | Use four metrics together | [05-verify.md](05-verify.md) |
| [F15](#f15) | Minified 10-Ks make line numbers meaningless | Character-offset anchors | [L2](03-build.md) |

---

## F1

### There is no semantic HTML ✅📌

Across all four companies, `<h1>~<h6>`, `<b>`, and `<strong>` are used **zero times**. Titles are expressed only through inline CSS.

```
NVDA-2024: 0    AMD-2023: 0    INTC-2022: 0    MU-2024: 0
```

```html
<div style="font-weight:700;font-size:10pt;margin-top:12pt">Item 1. Business</div>
```

**Decision** — splitting on HTML heading tags is impossible at the source. Heading detection must be built on measurements of inline CSS such as `font-weight` and `font-size`. That is why [L4](03-build.md) defines `block_props`, whose output is compared key by key against the profile's `rules`.

**Locked by** — `tests/ingestion/test_02_rules.py::test_inline_css_reaches_inner_spans`

---

## F2

### The same "Item 1A" text appears multiple times 🔄📌

NVDA-FY2024 has **eight** leaf blocks containing "Item 1A." (The original record said five; the count changed with the blockification method, but the finding is unchanged.)

| Block | Identity |
|---|---|
| 42 | Table of contents (`Page Part I Item 1. Business 4 Item 1A. Risk Factors 13 …`) |
| 158, 159, 162 | Cross-references in body text (`…as described in Item 1A…`) |
| **215** | **Real heading** (`Item 1A. Risk Factors`) |
| 470, 515, 536 | Cross-references in body text |

**Decision** — a plain text search mistakes the table of contents and cross-references for headings. Exactly one candidate remains only when both conditions are applied **together**:

1. The text must occupy the **entire** block → the `ITEM_RE` `^` anchor filters out references embedded in sentences. 2. The block must satisfy the style rule → the table of contents is inside a table, so it fails `in_table: false`.

**Locked by** — `tests/ingestion/test_03_segment.py::test_headings_are_found_by_style_plus_number` (applying the rules to NVDA-FY2024 yields exactly twenty-three headings)

---

## F3

### Layout is consistent within a company and differs across companies ✅📌

| Company | Heading style | Period |
|---|---|---|
| NVDA | 700 / 11pt (10pt only in FY2024) | five years |
| AMD | 700 / 10pt | five years |
| MU | 700 / 14pt | five years |

**Decision** — **company-level profiles are viable.** Instead of learning rules for every document, learn once per company and apply them across its five years. The cost scales with (companies × layout changes), not with the number of documents.

**Locked by** — `tests/ingestion/test_03_segment.py::test_learned_rules_match_golden`

---

## F4

### A year change can break even the same company ✅📌

**Only AMD FY2019 has headings inside tables.** The other four years place them outside.

```
AMD-FY2019: 표 밖 굵은 Item 블록  4개  /  표 안까지 포함  21개
AMD-FY2023: 표 밖 굵은 Item 블록 23개  /  표 안까지 포함  23개
```

**Two decisions.**

1. **Per-year profiles** — `profiles: {연도: {...}}`. Every entry is self-contained, so there is no merge rule. 2. **Relearn after validation failure** — try the previous year's rules, then learn again from the current document if validation fails.

This finding also produced the **asymmetry** of `in_table`. Interpreting `true` as "must be inside a table" would reject every heading outside tables, so `true` means "unconstrained." It is inelegant, but the measurements require it.

It is also why `default_year` must point to the **latest** year. Fixing it to the first bootstrap year would make the exceptional FY2019 layout AMD's default.

**Locked by** — `tests/ingestion/test_02_rules.py::test_in_table_is_asymmetric`, `tests/ingestion/test_05_profile.py::test_default_year_tracks_the_newest`

---

## F5

### Intel has no Item headings in the body at all 🔄📌

Of the **2,267leaf blocks** in INTC-FY2022, **zero match `ITEM_RE`**. (The original record said "one of 2,416blocks, and even that was inside the index table at the end." Once that index was absorbed as a single data-table block, its cells stopped being leaves and the count fell to zero, strengthening the conclusion.)

Since FY2019, Intel has reorganized the filing around its own narrative structure, with titles such as "Our Capital" and "Other Key Information."

**Decision** — **no amount of refining style rules can find something that is absent.** This is why tuning contextual conditions was wasted effort. The fact that some documents require **changing the strategy itself** is the key design branch in this project and the reason `segmentation.type` is data.

> ⚠ Common misconception — `detect_number` does not fail because Intel's index table is rejected as a table of contents. There are **zero candidates**, so it exits at `len(hits) < 5` without ever reaching `_looks_like_toc`. TOC detection is defensive code that never fires in this corpus.

**Locked by** — `tests/ingestion/test_03_segment.py::test_intel_fails_for_lack_of_candidates_not_toc_density`, `::test_toc_detector_is_a_dormant_guard`

---

## F6

### In exchange for restructuring, the SEC requires a Cross-Reference Index ✅📌

The document **contains its own table** stating which pages belong to each Item:

```
Item 1A. | Risk Factors | Pages 53 - 67
Item 7.  | Management's Discussion and Analysis…      ← 값 없음: 아래 하위행이 페이지 보유
         |   Results of operations | Pages 5-6, 19-44, 47-51
Item 11. | Executive Compensation | (b)               ← proxy 참조 각주
Item 4.  | Mine Safety Disclosures | Not applicable   ← 공시 없음
```

It also contains the company's own table of contents (title → starting page).

| Document | Index entries | TOC rows |
|---|---|---|
| INTC-FY2019 | 21 | 30 |
| INTC-FY2020 | 21 | 29 |
| INTC-FY2021 | 22 | 26 |
| INTC-FY2022 | 22 | 25 |
| INTC-FY2023 | 23 | 29 |

**Decision** — joining the two tables **by page** completes the mapping without an LLM. This is the basis for the `xref` type. Because it uses the document's own metadata, the result is **fact**, not inference, and the system can support an answer such as "this Item is Not applicable" with evidence.

**Locked by** — `tests/ingestion/test_06_xref.py::test_table_row_counts`

---

## F7

### One Item = multiple narrative sections ✅📌

INTC FY2022 Item 7 = Pages 5-6, 19-44, 47-51 → eight narrative sections.

**Decision** — this cannot be solved with a 1:1 anchor mapping; it requires **page-range overlap**. Narrative sections assigned to the same Item are then combined into one `Section`, preserving document order without duplication.

This is also why **order and duplicate checks are meaningless** for `xref` validation: Items are expected to be scattered throughout the document.

**Locked by** — `tests/ingestion/test_06_xref.py::test_item_7_is_joined_from_many_narrative_sections`

---

## F8

### Some Intel headings in recent years are images ✅📌

Titles such as "Segment Trends and Results," "Auditor's Reports," and "Consolidated Financial Statements" in FY2020~FY2023 **do not exist** in the body text; they appear only in the TOC table.

**Decision** — some boundaries cannot be established by text matching. The next anchor is then pushed far forward, causing all intervening content to be absorbed into the preceding section (in FY2022, eight pages of financial statements landed in Item 9B). **The page-number footer becomes the only deterministic boundary signal.**

One qualification: do not split when the next anchor is on the **immediately following page**. That is spillover, not an orphan. In FY2021, the Item 7A body on p49 continues into the beginning of p50 before Risk Factors starts; splitting there would attach 7A's final paragraph to the beginning of 1A.

**Locked by** — `tests/ingestion/test_06_xref.py::test_financial_statements_land_in_item_8`

---

## F9

### Older files put a `<div>` in every table cell ✅📌

| Document | Table count | Tables containing `div`/`p` elements |
|---|---|---|
| NVDA-FY2020 | 158 | **158 (all)** |
| AMD-FY2019 | 105 | **105 (all)** |
| INTC-FY2019 | 492 | **492 (all)** |
| NVDA-FY2024 (control) | 66 | 18 |

**Decision** — under a rule that treats only elements without inner blocks as leaves, these tables cease to be leaves. They break into cell-level paragraphs and **the entire financial statement structure disappears.**

But unconditionally consuming every table as one block breaks the opposite case. Intel wraps whole pages in layout tables, so headings sit inside those tables and would be lost.

**A single rule necessarily breaks one side or the other.** The parser therefore separates tables into two kinds:

| Table type | Detection | Handling |
|---|---|---|
| Data table | High numeric-cell density **+ no long-text cells** | The table itself is one block, preserving structure |
| Layout table | Contains a long-text cell (`LAYOUT_CELL_CHARS`(300chars)↑) | Inner elements become blocks containing body text and headings |

The long-text condition must run **first**. Numeric density alone would classify Intel's infographic tables incorrectly.

**Locked by** — `tests/ingestion/test_01_blocks.py::test_no_document_loses_its_tables`

---

## F10

### iXBRL tags must be unwrapped, not deleted — except for `ix:header` ✅📌

Because `ix:nonFraction` wraps financial values, deleting the tag removes the entire number:

```
<div>매출 <ix:nonFraction>26,974</ix:nonFraction> 백만</div>

decompose() → <div>매출  백만</div>       ← 숫자 증발
unwrap()    → <div>매출 26,974 백만</div>  ← 정상
```

**But `ix:header` itself must be discarded in full.** It is a machine-only region that the iXBRL specification does not render, and it contains XBRL context definitions:

| Document | `ix:header` text | `xbrli:context` | `xbrldi:explicitMember` |
|---|---|---|---|
| MU-FY2024 | **34,148chars** | 421 | 640 |
| INTC-FY2019 | **59,005chars** | 649 | 1,116 |

`xbrli:*` and `xbrldi:*` do **not** use the `ix:` prefix, so they are not unwrap targets. Unwrapping only the parent leaves these children alive, combining tens of thousands of characters of garbage into the first body block.

**Order matters** — handle `ix:header` first with `decompose()`, then `unwrap()` everything else.

> This bug **passed every Item count, order, and duplicate check.** It appeared only after measuring coverage, a concrete example of why [F14](#f14) is necessary.

**Locked by** — `tests/ingestion/test_01_blocks.py::test_ix_header_is_dropped_not_unwrapped`, `::test_ixbrl_numbers_survive`

---

## F11

### Real headings occur once; false headings repeat ✅📌

Repeated text in INTC-FY2022:

```
 113회  'Table of Contents'                            ← 페이지 헤더
  36회  'Notes to Consolidated Financial Statements'
  33회  'MD&A'                                         ← 페이지 헤더
  25회  '■'
  21회  'Other Key Information'
   1회  "Management's Discussion and Analysis"         ← ★진짜 헤딩
```

**Decision** — use this in two places.

1. **Remove noise while assembling body text** — strip text that is short (less than `PAGE_HEADER_MAX_CHARS`(60chars)) and frequent (at least `PAGE_HEADER_MIN_REPEATS`(10occurrences)). Otherwise chunks become contaminated with "Table of Contents." 2. Use it as a **learning filter** for title-based types (the same purpose as [F12](#f12), currently unused).

**Do not use it as a rule condition** — see [F13](#f13).

**Locked by** — `tests/ingestion/test_06_xref.py::test_page_footers_and_repeated_headers_are_stripped`

---

## F12

### The amount of following body text separates TOC entries from headings 🔄

Original record: "RISK FACTORS" appeared three times in INTC-FY2019, followed by 1,851chars after the real heading, forty-one chars after the TOC entry, and ninety chars after the index entry.

When remeasured, only **one** leaf has block text exactly equal to "risk factors" (block 2583, followed by 2,155chars across eight blocks). Changes to blockification absorbed the other two into different structures. **The nature of the finding remains valid, but the original figures are no longer reproducible.**

**Decision** — this observation produced `body_after()`. However:

> ⚠ **`body_after` is not currently called anywhere.** It exists for the **learning** functions of `sec_canonical` and `custom_title`, neither of which has been implemented yet (see section 02, "Designed · not implemented," in [the specification](02-spec.md)). For now it is only defined.

---

## F13

### Yet the `number` type did not need contextual signals at all ✅📌

Of the four final profiles, **zero** have a contextual condition:

```
NVDA / AMD / MU   {font_weight, font_size, in_table}   ← 스타일 3개뿐
INTC              (규칙 자체 없음 — xref)
```

The number is such a strong anchor that `^Item N` + bold text + outside a table leaves exactly one match ([F2](#f2)).

**Decision** — **remove every contextual condition from the rule vocabulary.** The previous design included `min_body_after`, `max_repeat`, `next_is_table`, and `items`, but their actual usage rate was zero. Even so, `matches_rule` calculated `body_after` for every block: 2,400blocks × eight following blocks meant about 19,000calls, all pointless `get_text()` work.

**The rule vocabulary contains only what is actually used.** If a future company cannot be handled by style alone, add a condition then.

**Locked by** — `tests/ingestion/test_03_segment.py::test_learned_rules_match_golden`

---

## F14

### One validation metric is not enough; four catch different failures ✅📌

| Metric | What it catches | What it **cannot** catch |
|---|---|---|
| Coverage (section total / document total) | Text discarded wholesale | **Missing headings** — the preceding section absorbs the text, so the total is unchanged |
| SEC Item-set comparison | Missing or false-positive headings | Small errors in internal section boundaries |
| Size consistency across years | A boundary failure isolated to one year | Cases where every year is wrong in the same way |
| **Source-position comparison** | Whether the heading really exists at that location | More than samples when the check is not automated |

Each has a measured example. Coverage caught leaked `ix:header` content ([F10](#f10)) even though the Item count, order, and duplicate checks were **all perfect**. Conversely, if one heading is missed, the preceding section absorbs its content and coverage does not change:

```
정상:    [Item 7 본문 30k][Item 7A 본문 3k]   → 커버 96%
7A 놓침: [Item 7 본문 33k          ........]  → 커버 96%   ← 똑같다
```

**100% coverage is not the goal.** A result of 100% would mean that the cover page, table of contents, and signatures had been assigned to some Item, even though none belongs to an Item under the SEC structure. The normal upper bound is 96~98%.

Furthermore, because `expected_items` comes from the parser's **own measurements**, using its count for bootstrap validation would be circular. **Item-set comparison is not circular because it checks against an external standard: the SEC-defined Item list.**

**Locked by** — the four metrics in section 05 of [the verification guide](05-verify.md), `tests/ingestion/test_07_coverage.py` (both upper and lower bounds), `tests/ingestion/test_08_items.py`

---

## F15

### Minified 10-Ks make "line numbers" meaningless ✅📌

Measured: a 2MB file contains **five lines**.

```
줄 시작 오프셋: [0, 39, 931, 932, 933]
sourceline=5  sourcepos=197,074  →  절대 198,007
raw[198007:198030] = 'Item 1. Business <span style="color:#76b900;'
```

The location anchor must therefore be a **character offset**, not a line number.

| Parser | Total parsing for twenty files | Block text | `sourcepos` |
|---|---|---|---|
| `lxml` | 17.5seconds | Baseline | **absent** |
| `html.parser` (`store_line_numbers=True`) | 19.1seconds | **identical in all 20/20** | populated everywhere |

**Decision** — spend +1.6seconds to gain **verifiability**. Without locations, there is no way to verify the claim "the parser found the Item," leaving only indirect metrics such as count and size.

The parser was changed only after confirming that block text was identical character for character across all twenty files. Changing parsers can alter tree structure, so **equivalence verification is mandatory**.

**Locked by** — `tests/ingestion/test_08_items.py::test_sections_carry_their_position` and [final check ④](05-verify.md)
