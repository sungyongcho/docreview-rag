# M1.1 Bugs

> The real traps encountered while completing the parser. Each is recorded in four stages: **symptom → cause → fix → what prevents it now**.
>
> The final stage is what makes this document valuable. Merely recording a fix means the same mistake can happen again. A history becomes regression protection only when every entry names the test that locks it down.

The longest part of this project was not writing the parser, but **realizing that it was wrong**. More than half of the eighteen cases below are cases where "execution succeeded, but the result was wrong"—which shows why [F14](01-findings.md#f14) is necessary.

---

## At a Glance

| ID | Symptom | Cause | **How it was found** | Layer |
|---|---|---|---|---|
| [B01](#b01) | Item Sixteen said "Not applicable" but had content | Absorbed trailing "Signatures\|Page 125" row | Content review | L8 |
| [B02](#b02) | "Form 10-K Summary" became p10 | Read the title as the value in a two-cell row | Content review | L8 |
| [B03](#b03) | FY2019·2020 Item 7 disappeared | A child-row reference marker contaminated the parent status | Content review | L8 |
| [B04](#b04) | 0 tables (three files) | Every cell had a `<div>`, so the table was not a leaf | Zero table blocks in `--blocks` | L3 |
| [B05](#b05) | INTC-FY2020 collapsed | Mistook an infographic table for a data table | Section size | L3 |
| [B06](#b06) | Eight pages of financial statements were absorbed into Item 9B | Heading was an image | Content review | L8 |
| [B07](#b07) | Final 7A paragraph appeared at the start of 1A | Mistook a page spillover for an orphan | Boundary comparison | L8 |
| [B08](#b08) | Incorrect Item 5/10 assignment | No tie-breaking rule | Content review | L8 |
| [B09](#b09) | **Coverage in the 80% range** | Unwrapping `ix:header` let XBRL leak in | **Coverage** | L2 |
| [B10](#b10) | Every section had blocks=2 | Treated TOC table title cells as body headings | Section size | L8 |
| [B11](#b11) | "FORM 10-K"→16, "Exhibit"→15 | Fuzzy matching had no lower bound | False positives | L7 |
| [B12](#b12) | `in_table: true` meant "at least 1" | `bool` is a subclass of `int` | Exploding hit count | L5 |
| [B13](#b13) | 19 thousand wasted calculations | Evaluated unused context conditions for every block | Profiling | L6 |
| [B14](#b14) | Duplicate Item created | Partial `custom_title` match | Duplicate validation | L7 |
| [B15](#b15) | Misread "Pages 1 4, 67" | iXBRL inserted a space between digits | Index-table review | L8 |
| [B16](#b16) | Risk that a TOC could pass after switching to in-table candidates | No density check | Defensive addition | L9 |
| [B17](#b17) | Every `source_pos` was `None` | `lxml` did not populate positions | Position comparison | L2 |
| [B18](#b18) | Call sites broke whenever a field was added | Returned a 4-tuple | Refactoring | L13 |

**Grouped by discovery path**—which metrics actually did useful work:

| Discovery path | Count | What it caught |
|---|---|---|
| Content review (body size and opening cue words by Item) | 6 | Assignment and boundary errors |
| Abnormal section size | 2 | Structural collapse |
| **Coverage** | 1 | **The case all three other checks missed** (B09) |
| Other (unit checks, profiling, refactoring) | 9 | |

---

## L2 — Normalization

### B09

#### Coverage fell into the 80% range

**Symptom**—Item count, order, and duplicate validation **all passed**, but coverage alone was in the 80% range. The structure was perfect, but the denominator was inflated.

**Cause**—Sending every `ix:*` element through `unwrap()`. Under the iXBRL specification, `ix:header` is a non-rendered machine-readable region. Its `xbrli:*`/`xbrldi:*` children do not have the `ix:` prefix, however, so they are not unwrap targets. Removing only the parent left the children alive and merged into the first body block—34 thousand, one hundred forty-eight characters in MU-FY2024 and 59 thousand and five characters in INTC-FY2019. ([F10](01-findings.md#f10))

**Fix**—Let `ix:header` receive `decompose()` first, then let the remaining `ix:*` elements receive `unwrap()`. **Order matters.**

```python
for tag in soup.find_all("ix:header"):
    tag.decompose()          # Remove non-rendered machine-only regions entirely
for tag in soup.find_all(lambda t: bool(t.name and t.name.startswith("ix:"))):
    tag.unwrap()             # Remove other tags but preserve their text, including numbers
```

**What prevents it now**—`tests/ingestion/test_01_blocks.py::test_ix_header_is_dropped_not_unwrapped` checks whether `ix:header` remains in the tree and whether `xbrli`/`explicitMember` appears in the first five blocks. The upper and lower coverage bounds (`test_07_coverage.py`) provide a second guard.

> **This case produced [F14](01-findings.md#f14).** A single metric would never have caught it.

---

### B17

#### Every `source_pos` was `None`

**Symptom**—The section position fields were empty, so the claim "Item 1A was found" could not be checked against the source. Verification was limited to indirect metrics such as count and size.

**Cause**—The parser used `lxml`. It is fast, but does not populate `sourceline`/`sourcepos` at all. In addition, 10-K files are minified (a 2MB file may contain five lines), making line numbers themselves meaningless. ([F15](01-findings.md#f15))

**Fix**—Switch to `html.parser` + `store_line_numbers=True`. Because `sourcepos` is a position within a line, add the line's starting offset to obtain an absolute position.

Before switching, **equivalence was verified**: not one character of block text differed across the twenty files. This check is essential because changing parsers can change the tree structure. The cost was +1.6s.

**What prevents it now**—`tests/ingestion/test_08_items.py::test_sections_carry_their_position` checks that every section has `block_index`/`source_pos`/`block_range` populated. `tests/ingestion/golden.py` locks down four real offsets in `NVDA_FY2024_OFFSETS`.

---

## L3 — Block Extraction

### B04

#### Zero tables were produced (three files)

**Symptom**—NVDA-FY2020, AMD-FY2019, and INTC-FY2019 had **zero table blocks**. Their financial statements were scattered into cell-level paragraphs, destroying the entire structure.

**Cause**—The naive definition "an element with no inner block is a leaf":

```python
# This alone breaks financial statements
[el for el in soup.find_all(["div","p","table"]) if el.find(["div","p","table"]) is None]
```

Older files put a `<div>` in every table cell. The table then ceases to be a leaf, and each cell becomes a paragraph. In all three files, **100% of tables** used this form (158/158, 105/105, 492/492). ([F9](01-findings.md#f9))

**Fix**—Separate data tables from layout tables. Consume a data table as one block, while emitting the inner elements of a layout table as blocks. Old-style leaf tables (`el.find([...]) is None`) are also consumed whole.

**What prevents it now**—`tests/ingestion/test_01_blocks.py::test_no_document_loses_its_tables` asserts table blocks above zero for each of the twenty documents. `test_block_counts` also locks down the exact counts.

---

### B05

#### INTC-FY2020 collapsed completely

**Symptom**—Sections were detected, but their bodies were nearly empty.

**Cause**—While fixing [B04](#b04), the only test for a data table was "high density of numeric cells." Intel's infographic tables (such as "Our Capital") contain many numbers, but also contain paragraphs and headings. Consuming each one whole made every heading inside it disappear.

**B04 and B05 fail in opposite directions.** A rule for only one side inevitably breaks the other.

**Fix**—Evaluate the **long-cell condition before numeric density**. If even one cell exceeds `LAYOUT_CELL_CHARS` (three hundred characters), it is a layout table. Putting the negative condition first allows the candidate to fail fast in the correct order.

```python
if any(len(t) > 300 for t in texts):      # Long cells indicate layout tables; check this first
    return False
numeric = sum(1 for t in texts if t and len(t) < 30 and re.search(r"\d", t))
return numeric >= max(4, len(cells) // 4)
```

**What prevents it now**—`tests/ingestion/test_01_blocks.py::test_block_counts` locks INTC-FY2020 to (2230, 133, 337). Over-consuming tables reduces the block count and creates an immediate mismatch.

---

## L5 — Rule Evaluator

### B12

#### `in_table: true` was interpreted as "at least 1"

**Symptom**—Heading hits exploded from dozens to hundreds.

**Cause**—In Python, `bool` is a subclass of `int`: **`isinstance(True, int)` is `True`.** If the numeric check precedes the Boolean check:

- `in_table: True` → "at least 1" → almost everything passes
- `in_table: False` → "at least 0" → **always passes**

**Fix**—Check `isinstance(expected, bool)` **before** the numeric check.

```python
elif isinstance(expected, bool) or isinstance(actual, bool):
    if actual != expected:
        return False
elif isinstance(expected, int | float):     # Check bool first
    if actual < expected:
        return False
```

**What prevents it now**—`tests/ingestion/test_02_rules.py::test_bool_is_checked_before_numeric`. When `font_weight: True` is required, it directly verifies the ordering through the difference between the numeric contract, which passes (700 ≥ 1), and the Boolean contract, which fails (700 ≠ True).

> This trap is easy to encounter in real Python code. It is even more likely when rule values come from JSON, where `true` naturally becomes `True`.

---

## L6 — Context Signals

### B13

#### Unused context conditions were computed for every block

**Symptom**—Parsing was slow. There was no functional error.

**Cause**—The rule vocabulary included four conditions: `min_body_after`, `max_repeat`, `next_is_table`, and `items`. Their usage in actual profiles was **0**, yet `matches_rule` still computed and passed `body_after` for every block. INTC's 2 thousand four hundred blocks × the next eight blocks meant about **19 thousand calls to `get_text()`**, all wasted. ([F13](01-findings.md#f13))

**Fix**—Remove every context condition from the rule vocabulary. Rules now contain style only.

**Lesson**—**Do not put unused concepts in the vocabulary.** An extension point added because it "might be needed later" imposes costs immediately and may never provide a benefit. Add it when it becomes necessary.

**What prevents it now**—`tests/ingestion/test_03_segment.py::test_learned_rules_match_golden` locks the learned rule keys to exactly `{font_weight, font_size, in_table}`.

> Related: `body_after()` remains defined but **is not called**. It exists for the learning functions for `sec_canonical` and `custom_title`, both of which are unimplemented. See "Designed · not implemented" in [02-spec.md](02-spec.md).

---

## L7 — Segmentation A (Heading Traversal)

### B11

#### "FORM 10-K" matched Item 16, "Exhibit" matched 15, and "Reserved" matched Item Six

**Symptom**—`sec_canonical` matching produced a flood of unrelated false positives.

**Cause**—Prefix matching against standard SEC titles had **no minimum length**. Short strings have a high probability of accidental overlap; "Reserved" is also the standard Item Six title itself.

**Fix**—Add two guards.

```python
t = _norm_title(text)
if len(t) < 8:                    # Guard 1: defer when too short
    return None
for item, canon in CANONICAL.items():
    c = _norm_title(canon)
    if t == c:
        return item
    if len(c) >= 14 and (t.startswith(c[:14]) or c.startswith(t[:14])):
        return item               # Guard 2: prefix matches require enough text
```

**Lesson**—**Fuzzy matching must have a lower bound.** Two axes enforce it: the `CANON_MIN_CHARS` length floor (eight characters) and the `CANON_PREFIX_CHARS` prefix length (fourteen characters).

**What prevents it now**—There is **no** direct regression test. `match_canonical` is called only from `find_item`'s `sec_canonical` branch, and the detector needed to reach that type is not yet implemented, so this corpus never executes the path. When `detect_sec_canonical` is implemented, these cases should be written as tests first.

---

### B14

#### The same Item was created twice

**Symptom**—`custom_title` matching produced the same Item twice.

**Cause**—The implementation used partial title matching. "Risk Factors" also matched a child subheading such as "Risk Factors Summary."

**Fix**—Switch to exact matching. **A mapping table means the answer is known, so there is no reason to use a fuzzy match.**

```python
low = text.strip().lower()
item = next((e["item"] for e in seg["order"] if e["title"].strip().lower() == low), None)
```

**What prevents it now**—The state is the same as [B11](#b11). Because `custom_title` detection is unimplemented, this path does not execute. Duplicate Items themselves are still checked for every document by `tests/ingestion/test_03_segment.py::test_no_duplicate_items`.

---

## L8 — Segmentation B (xref Page Join)

This layer produced the most bugs (nine). Not because the algorithm is difficult, but because **the document does not lie, yet speaks ambiguously**: the meaning of a cell in the index table depends on context.

### B01

#### Item Sixteen said "Not applicable" but acquired content

**Symptom**—The index table said Item Sixteen was "Not applicable," but the parsed result contained text.

**Cause**—Indented child rows in the index table were **always** absorbed into the parent Item. The trailing "Signatures | Page 125" row was attached to the final Item (16).

**Fix**—Expose the state machine as an explicit variable. If an Item receives a value in its own row (a page / "Not applicable" / reference marker), the Item is **closed** and does not absorb rows below it.

```python
closed = True                                  # Whether the current Item received a value on its own row
for r in rows:
    if m := ITEM_CELL.match(r[0]):
        ...
        closed = bool(_spans(tail) or EMPTY_CELL.match(tail) or REF_CELL.match(tail))
    elif cur is not None and not closed and len(r) >= 2:
        tail = r[-1]                           # Only an open Item absorbs a continuation row
```

**Lesson**—**In a parser, "what context are we in now?" should almost always be explicit in a variable.** When it is implicit, edge cases like this fail silently.

**What prevents it now**—`tests/ingestion/test_06_xref.py::test_open_row_absorption_stops_at_a_closed_item`

---

### B02

#### "Form 10-K Summary" was read as page ten

**Symptom**—The page span for Item Sixteen was nonsensical.

**Cause**—In a two-cell row (`번호 | 제목`), the last cell was treated as the value. The **10** in the title "Form 10-K Summary" was misread as a page number.

**Fix**—**Only the third cell is the value cell.** A two-cell row has no value.

```python
tail = r[2] if len(r) > 2 else ""       # The value cell is always the third cell
```

**What prevents it now**—`tests/ingestion/test_06_xref.py::test_value_cell_is_the_third_one` checks that every entry's page is within the 1–400 range. Scraping a number from the title escapes that range.

---

### B03

#### Item 7 disappeared entirely in FY2019 and FY2020

**Symptom**—MD&A was entirely absent from the result, despite clearly being present in the document.

**Cause**—The reference marker in Item 7's **child row**, "Off balance sheet arrangements | (a)," made **the entire Item** `incorporated_by_reference`. Items classified as references are excluded from assignment candidates, so their bodies appeared nowhere.

**Fix**—Prevent a child row from contaminating status and make **the presence of a page span the final authority**. If a span exists, the Item has a real body.

```python
for e in entries:
    if e.spans:
        e.status = "parsed"          # A page reference means the body exists
    elif e.status == "parsed":
        e.status = "empty_disclosure"
```

**Lesson**—When signals conflict, define **which signal has final authority**. Here, "a page exists" is the strongest evidence.

**What prevents it now**—`tests/ingestion/test_06_xref.py::test_status_is_decided_by_page_spans` catches an entry that has a page span but whose status is not `parsed`. `test_item_7_is_joined_from_many_narrative_sections` locks down that Item's size across five years.

---

### B06

#### Eight pages of financial statements were absorbed into Item 9B

**Symptom**—In FY2022, that Item was thin and Item 9B ("Other Information") was abnormally large.

**Cause**—Intel's "Consolidated Financial Statements" heading is an **image**, so it is absent from body text ([F8](01-findings.md#f8)). Because no anchor could be found, the entire region up to the next anchor was attached to the preceding section.

**Fix**—Build a (block → page) map from page-number footers in the body, and cut at the point where the current Item's page span ends. Return the removed blocks **to the Item that owns those pages** (FY2022: p72~80 → Item 8).

The footer-map noise filters also came from measurements:
- Accept only increments from 1 through three (numeric cells inside tables appear in a disorderly sequence)
- Require at least five blocks since the previous footer (exclude consecutive clusters such as "76 77 78…" in the financial-statement index)

**What prevents it now**—`tests/ingestion/test_06_xref.py::test_financial_statements_land_in_item_8` locks down the number of Item 8 tables by year (FY2020 through FY2023 contain 52 through sixty-five).

---

### B07

#### The final paragraph of Item 7A was attached to the start of Item 1A

**Symptom**—A **side effect** introduced by the [B06](#b06) fix. Cutting the boundary also cut a legitimate page spillover.

**Cause**—The FY2021 Item 7A body on p49 continues into the beginning of p50 before Risk Factors starts. Applying "the page span ended, so cut" unconditionally classifies the final 7A paragraph as an orphan and moves it to the Item that owns p50 (1A).

**Fix**—**Cut only when the next anchor is at least one page away.** If it starts on the immediately following page, the intervening text is a spillover, not an orphan.

```python
if clamp is not None and bi < clamp + 1 < end and next_page > hi + 1:
```

Also discard a removed region shorter than three blocks; moving fragments only relocates noise.

**Lesson**—**Always test a fix in the opposite direction for a new failure.** Stopping after B06 would have left B07 behind.

**What prevents it now**—`tests/ingestion/test_06_xref.py::test_item_7_is_joined_from_many_narrative_sections` and the coverage floor guard against this together. An incorrect cut preserves the total amount, so coverage cannot catch it; the per-Item size golden value does.

---

### B08

#### Item Five and Item Ten were assigned incorrectly

**Symptom**—Narrative sections were assigned to the wrong Items.

**Cause**—There was **no tie-breaking rule** when multiple Items covered one page.

**Fix**—Represent priorities as a tuple.

```python
cands.append((-overlap, span[1] - span[0], len(e.item), e))
return min(cands, key=lambda c: c[:3])[3].item if cands else None
```

1. Prefer more overlapping title words (`-overlap`—the sign is reversed for descending order) 2. Prefer the narrower width of **one covering span** (not the Item's total page width) 3. Prefer the shorter Item number (ensures determinism for a complete tie)

Three measured examples:

| Case | Candidates | Correct answer | Deciding axis |
|---|---|---|---|
| FY2021 "Market for Our Common Stock"@64 | Item 2(64,64 width0) vs Item 5(64,65 width1) | **Item 5** | Overlap (market/common) |
| FY2019 "Critical Accounting Estimates"@50 | Item 1A(50-60 width10) vs Item 7(50,50 width0) | **Item 7** | No overlap → width |
| FY2022 "Notes to Consolidated Financial Statements"@81 | Item 8(2) vs 7(1) vs 15(1) | **Item 8** | Overlap |

**Technique**—Put the object itself in the final element, but exclude it from comparison with `key=lambda c: c[:3]`. `XrefEntry` objects do not support `<`, so comparing the full tuple fails.

**What prevents it now**—`tests/ingestion/test_06_xref.py::test_covering_picks_the_narrowest_span` locks down `covering()`'s width selection, while per-Item size golden values lock down the complete assignment result.

---

### B10

#### All twenty-one sections contained two blocks

**Symptom**—The structure was perfect. Item count, order, and duplicate checks all passed. **Only the content was missing.**

**Cause**—All thirty title cells in the TOC table were detected as "body headings." Because the TOC is concentrated near the beginning of the document, every "section" contained only two blocks up to the next TOC entry.

**Fix**—Build a set of blocks (`skip`) that belong to TOC and index tables, and exclude them from body-position searches.

This incident also produced **a new validation rule**. Structural checks cannot catch it, so fail if at least two core Items are parsed yet contain no real body:

```python
thin = sorted(s.item for s in sections
              if s.item in CORE_ITEMS and s.status == "parsed" and len(s.blocks) < 20)
if len(thin) >= 2:
    problems.append(f"looks like a table of contents (core Items without bodies): {thin}")
```

**Lesson**—A failure with **perfect structure** can exist: count, order, and duplicates are all correct, but there is no content.

**What prevents it now**—`tests/ingestion/test_04_validate.py::test_validate_catches_a_perfect_structure_with_no_content` constructs "twenty-three sections, all blocks=2" and verifies that validation actually catches it. `tests/ingestion/test_08_items.py::test_core_items_have_real_content` guards the real documents.

---

### B15

#### "Pages 1 4, 67" was read incorrectly

**Symptom**—The page span was parsed incorrectly.

**Cause**—iXBRL inserts spaces between digits. "Pages 1 4, 67" actually means **fourteen and 67**. There was also a source typo: "88 -86."

**Fix**—Remove spaces before parsing and normalize reversed ranges. "88 -86" → (86, 88).

**Lesson**—Real data contains both **machine-made noise** (iXBRL spaces) and **human-made noise** (typos). Both must be absorbed by the normal path.

**What prevents it now**—The 1~400 range check in `tests/ingestion/test_06_xref.py::test_value_cell_is_the_third_one` catches this kind of misread.

---

## L9 — Detection Cascade

### B16

#### Allowing in-table candidates could let a TOC table pass

**Symptom**—This has **never actually occurred**. It is a predicted risk introduced by the [F4](01-findings.md#f4) switch that considers in-table candidates when there are fewer than `OUTSIDE_TABLE_MIN_HITS` (fifteen) candidates outside tables.

**Cause (hypothesis)**—A TOC contains every Item candidate and is also styled in bold. The instant in-table candidates are allowed, the whole TOC could pass.

**Fix**—Distinguish a TOC by density. A TOC is concentrated in a narrow region of the document because no body text separates its entries, while body headings are spread across the entire document with tens of thousands of characters between them.

```python
if len(idx) < 10:
    return False
return idx[-1] - idx[0] < len(blocks) * 0.15    # Treat as TOC when all entries fit within the first 15%
```

**⚠ This guard never fires in this corpus.** AMD-FY2019's twenty-one Item candidates are distributed over 5 thousand, two hundred twenty blocks, far beyond the threshold (eight hundred twenty-six blocks).

**That led to one misconception**: documentation once claimed that this check made Intel fail `detect_number`, but that is **not true**. Intel has zero candidates, exits at `len(hits) < 5`, and never reaches this point.

**What prevents it now**—`tests/ingestion/test_03_segment.py::test_toc_detector_is_a_dormant_guard` locks down that it does not fire in any of the twenty documents (a change would mean block extraction or the threshold changed), while `test_toc_detector_fires_on_a_dense_index` uses a synthetic TOC to verify that this is not dead code.

---

## L13 — Orchestration

### B18

#### Every call site broke whenever one field was added

**Symptom**—Design friction rather than a functional error. The function returned a 4-tuple, `(sections, index, profile, problems)`, so adding `n_chars` required changing every caller.

**Fix**—Switch to the `ParsedFiling` dataclass. Fields can now be added without breaking existing code.

**Lesson**—**If a return value contains more than three values, use a dataclass.**

This is also why `n_blocks`/`n_chars` are stored in the result. The denominator for coverage is "all document text"; without carrying it out, the CLI must **parse the document again** for every verification. Across the measured twenty files, the difference was forty seconds → eighteen seconds. **It is cheaper to carry a measurement out from where it was taken.**

**What prevents it now**—`tests/ingestion/test_07_coverage.py::test_n_chars_is_carried_not_recomputed` checks that `n_chars`/`n_blocks` match the values measured at parse time.

---

## Known Limitations (Not Bugs)

These are documented and **accepted**. They could be fixed, but the benefit was not worth the cost.

| Limitation | Scale | Why it was accepted |
|---|---|---|
| INTC loses page 1 and sometimes page two at the start of FY2021~FY2023 | ~2k of the 50k-character Item 1 body | The region precedes the first anchor. Its image heading ([F8](01-findings.md#f8)) cannot create an anchor |
| Images themselves (charts and diagrams) are excluded | Qualitative | An image audit confirmed that adjacent text and tables contain the figures |
| 4~6% remains uncovered | 10~25k characters per document | Cover, TOC, signatures, and repeated headers. **Under the SEC definition, they belong to no Item** |
| Twenty cue-word review "mismatches" | — | Manual review found **all of them to be false positives**. For example, NVDA Item 1 starts with "NVIDIA pioneered accelerated computing…" (correct), and Item 15 starts with the financial-statement index (correct) |

### Profile convergence takes three passes, not two

This is not a bug, but it is counterintuitive enough to document. Repeated runs over the same corpus produce:

```
pass1  2019:bootstrap 2020:saved     2021:relearned 2022:saved     2023:relearned
pass2  2019:saved     2020:relearned 2021:saved     2022:relearned 2023:saved
pass3  전부 saved
```

`expected_items` differs by year (the introduction of Items 1C and 9C changes 21→23), while `default_year` points to the **latest** year (as required by [F4](01-findings.md#f4)). Therefore, an older year missing those Items must fail validation against the latest year's expected count. A profile is saved only after relearning succeeds, so no bad rule remains; the missing years are filled one by one until convergence. **It is self-healing, but not idempotent.**

**Locked down by**—`tests/ingestion/test_05_profile.py::test_profiles_converge_but_not_on_the_second_pass`
