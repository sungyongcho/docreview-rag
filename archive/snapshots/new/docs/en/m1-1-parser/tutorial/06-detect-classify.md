# M1.1 Tutorial 6 — Let the filing choose its own strategy

With two strategies in place, something has to choose between them. L9 is that detector.

L10 attaches a status to each extracted section. One judgment matters here: **a short section is not always a bug.** A one-line "Not applicable" Item is correct, and failing to separate that from a genuine parse failure would leave L12's validation meaningless.

**Prerequisite:** Tutorial 5's `uv run pytest tests/ingestion/test_06_xref.py -v` passes in full. Both segmentation paths must exist before a detector can choose between them.

## What to write and where to implement it yourself

| Stretch | Learning action | What to take away |
|---|---|---|
| L9 `_looks_like_toc` | **Implement** the density test | the signal that separates a TOC from body headings |
| L9 `detect_number`, `detect_xref` | **Implement** detection and learning | the design where a detector doubles as a config builder |
| L9 `detect_segmentation`, `build_profile` | **Review the call order** | where cascade order changes the result |
| L10 `classify_sections` | **Implement** the status rules | telling a legitimately short Item from a parse failure |

---

## L9 — Detection cascade — which strategy fits this filing?

With two strategies there has to be code that chooses. And here one of this project's design choices surfaces: **a detection function is both classifier and configuration builder.**

Usually that is split in two — "detect the type" then "build the config for it." Here one function does both, and the return value is the answer.

- `{}` → "not my type"
- a populated dict → "my type, and here is the configuration"

Doing it this way lets the measurements taken during detection be reused directly as configuration. `detect_number`, for instance, already measures the font weight and size of its heading candidates while gathering them — and those values *are* the rule. Split detection from learning and the same measurement gets taken twice.

### Build — Detection cascade — which strategy fits this filing

#### Target file: `app/ingestion/parser.py`

<!-- src: app/ingestion/parser.py::_looks_like_toc -->
```python
def _looks_like_toc(blocks: list[Tag]) -> bool:
    """Detect a TOC by densely clustered Item candidates with little body between them."""
    idx = [
        i
        for i, el in enumerate(blocks)
        if (t := el.get_text(" ", strip=True)) and len(t) < HEADING_MAX_CHARS and ITEM_RE.match(t)
    ]
    if len(idx) < TOC_MIN_ITEMS:
        return False
    return idx[-1] - idx[0] < len(blocks) * TOC_DENSITY
```

The idea separating a table of contents from body headings is neat: it looks at **density**.

A TOC has no body between its entries, so it clusters into a narrow slice of the document. Body headings, by contrast, are separated by tens of thousands of characters and spread evenly. So "if the distance between the first and last Item candidate is under 15% of the document, it is a TOC."

> ⚠ To be candid, **this function never fires in this corpus.** AMD-FY2019's twenty-one Item candidates are spread over 5,220 blocks, far past the threshold (826 blocks). And a common misreading: **"Intel is filtered out by this test" is false.** Intel has zero candidates and stops at `len(hits) < 5`, never reaching here ([B16](../04-bugs.md#b16)). It is an easy spot to assume "ah, this is what excludes Intel", so it is stated explicitly.

<!-- src: app/ingestion/parser.py::detect_number -->
```python
def detect_number(blocks: list[Tag]) -> dict:
    """Strategy 1: detect filings with explicit ``Item 1A.`` body headings."""

    def collect(allow_table: bool) -> list[tuple[int, float]]:
        out = []
        for el in blocks:
            t = el.get_text(" ", strip=True)
            if not t or len(t) > HEADING_MAX_CHARS or not ITEM_RE.match(t):
                continue
            if not allow_table and el.find_parent("table") is not None:
                continue
            props = block_props(el)
            if props["font_weight"] < 700:  # unstyled matches are TOC entries or references
                continue
            out.append((props["font_weight"], props["font_size"]))
        return out

    outside, inside = collect(False), collect(True)
    hits, in_table = (outside, False) if len(outside) >= OUTSIDE_TABLE_MIN_HITS else (inside, True)
    # When table-contained headings are required, confirm the table is not a TOC.
    if len(hits) < NUMBER_MIN_HITS or (in_table and _looks_like_toc(blocks)):
        return {}

    # Use the loosest rule covering every observation; a mean or mode drops valid headings.
    return {
        "type": "number",
        "rules": [
            {
                "font_weight": min(w for w, _ in hits),
                "font_size": min(s for _, s in hits),
                "in_table": in_table,
            }
        ],
    }
```

**What to look for in the code**

- Calling `collect` twice is the core of the design: search outside tables first, then widen to include them if the count falls short. That second path exists for filings like AMD's, whose headings sit inside table cells.
- Filtering on `font_weight < 700` works because an unbolded `Item 1A` is almost always a TOC entry or a cross-reference.
- The rule is built with `min`. A mean or a mode would filter out some of the very headings that were observed; the goal is **the loosest rule that admits every observation**.
- `_looks_like_toc` is called only on the in-table path. If the headings were found outside tables there is no TOC risk, so the check would be wasted.

### The rule decides for itself whether to look inside tables

The `in_table` asymmetry deferred in L5 gets its value here.

`collect()` is called twice — once outside tables, once including them. If enough candidates appear outside (`OUTSIDE_TABLE_MIN_HITS`, fifteen or more), the outside rule is used; otherwise tables are allowed in.

That lets AMD FY2019 — the one file whose headings sit inside a table — learn a different rule **with no human intervention**. The exception is handled by measurement rather than hardcoded into the code.

### Why rules are derived with `min()`

The learning part is short enough to skim past, but an important judgment sits here.

Say the observed headings had font weights 700, 700, and 800. What should the rule be? Mean (733) or mode (700) come to mind. But use the mean and **some of the observed headings fail their own rule** — the 700s do not clear a 733 threshold.

So `min()` is used. Paired with the "at least" convention from L5, it produces **the loosest rule that passes every observation**.

That is this learning step's goal: not accurate classification but **recall first.** A missed heading loses an entire section, while something slightly over-inclusive gets caught by L12's validation.

#### Target file: `app/ingestion/parser.py`

<!-- src: app/ingestion/parser.py::detect_xref -->
```python
def detect_xref(soup: BeautifulSoup, blocks: list[Tag]) -> dict:
    """Strategy 2: detect a filing that maps Items through a Cross-Reference Index.

    Call this only after strategy 1 fails. A normal 10-K TOC can resemble an index
    with ``Item 1. Business ... 3``, so first confirm that the body lacks Item
    headings. There is no payload because style rules cannot locate absent headings.
    """
    xref_tbl, toc_tbl = find_tables(soup)
    if xref_tbl is None or toc_tbl is None:
        return {}
    if len(parse_xref(xref_tbl)) < XREF_MIN_ENTRIES or len(parse_toc(toc_tbl)) < XREF_MIN_TOC_ROWS:
        return {}
    return {"type": "xref"}
```

**What to look for in the code**

- The return value carries no `rules`. Style cannot locate headings that do not exist, so there is nothing for a rule to describe.
- Both tables are required. An index table alone is indistinguishable from an ordinary 10-K's table of contents.
- This function runs only after `detect_number` fails. Reverse the order and a normal 10-K with a table of contents can be misjudged as xref.

<!-- src: app/ingestion/parser.py::detect_segmentation -->
```python
def detect_segmentation(soup: BeautifulSoup, blocks: list[Tag]) -> dict:
    """Try measured segmentation strategies in order and accept the first match.

    Strategy 1 is cheaper and more common. Running strategy 2 first can mistake a
    normal 10-K TOC such as ``Item 1. Business ... 3`` for a cross-reference index;
    establish the absence of body Item headings first.
    """
    return detect_number(blocks) or detect_xref(soup, blocks) or {"type": "undefined"}
```

A one-line function whose **order is itself the policy**.

Put `detect_xref` first and what happens? A normal 10-K's table of contents also looks like `Item 1. Business … 3`, so it reads as an index. NVIDIA's filing gets classified as xref, its perfectly good body headings ignored, and it is cut wrongly on TOC data.

So xref is attempted **only after confirming the body has no headings.** The order encodes the policy "cheap and common first, exceptions later."

This kind of order dependence is best documented **inside the function**, because that is where a reader comes to check the order. Written in a file-header comment, nobody reads it.

<!-- src: app/ingestion/parser.py::build_profile -->
```python
def build_profile(soup: BeautifulSoup, blocks: list[Tag], doc_id: str) -> dict:
    """Measure this filing and build one parsing profile."""
    seg = detect_segmentation(soup, blocks)
    sections, _ = segment(soup, blocks, seg)
    items = [s.item for s in sections if s.item]

    # xref does not store expected_items because each year's index states them directly.
    validation: dict = {"must_have": ["1A", "7", "8"]}
    if seg["type"] not in ("xref", "undefined"):
        validation = {
            "expected_items": len(items),
            "must_have": ["1", "1A", "7", "8"],
        }
    return {
        "segmentation": seg,
        "validation": validation,
        "learned_from": doc_id,
        "learned_by": "bootstrap",
        "learned_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
```

The last piece is `build_profile`, which bundles the detected strategy with validation criteria into a profile.

One asymmetry stands out here. **`xref` does not store `expected_items`.**

The reason is clean: the index table reports the Item count for each year directly, so the parser has no need to remember it. A `number`-type profile, by contrast, must remember "this company usually has 23" to notice next year that only 20 were found.

That difference has a real effect. It is why **a single INTC profile covers all five years** — storing nothing that varies per year means one profile fits them all.

### Verify

```bash
uv run pytest tests/ingestion/test_03_segment.py -k "detect or toc_detector" -v
```

**Pitfall encountered** — [B16](../04-bugs.md#b16), table-of-contents density detection

---

## L10 — Status classification — a short section is not always a bug

Looking at parse results you will find sections with only one or two blocks. The first instinct is that the parser missed something.

Open the source and it reads like this.

```
Item 4. Mine Safety Disclosures
Not applicable.
```

A semiconductor company has no mine safety disclosures. Short is correct. Likewise Part III (Items 10–14) is usually handled this way.

```
Item 11. Executive Compensation
The information required by this Item is incorporated herein by reference
to the Company's Proxy Statement...
```

Executive compensation lives in a separate proxy statement, and the 10-K only points at it. Also correct.

Treat either as "no body = parse failure" and L12's validation keeps chasing ghosts. So sections carry a **status**.

- `empty_disclosure` — the filing states there is nothing to disclose
- `incorporated_by_reference` — delegated to an external document
- `parsed` — real body content

### Inferred is not the same as stated

The `xref` type does not perform this inference, because its index table **reports status directly**.

Those two are different even when the information matches. What happens here is an **inference** from a regex over the first stretch of body text; xref **reads** what the document stated in a table. The latter keeps its original record in `item_index` and can produce evidence later.

Building a RAG system, it is worth making this distinction a habit. **Keeping in the data where the document stopped speaking and where you started guessing** gives you something to reason with when confidence is questioned later.

### Build — Section classification — inferred versus stated

#### Target file: `app/ingestion/parser.py`

<!-- src: app/ingestion/parser.py::EMPTY_RE,REF_RE -->
```python
EMPTY_RE = re.compile(r"^\s*(none|not applicable|n/?a)\.?\s*$", re.I)
REF_RE = re.compile(
    r"(incorporated (herein )?by reference|is set forth in|will be (contained|included) in"
    r"|information (required by|regarding).{0,80}(proxy|incorporated|set forth))",
    re.I,
)
```

**What to look for in the code**

- The two patterns separate two different reasons a body is empty: legitimately not applicable, and deferred to another filing.
- `REF_RE` bounds its gap with `.{0,80}` because an unbounded match swallows the whole paragraph and starts classifying unrelated sentences as references.
- Both use `re.I`. Filings write the same phrases with different capitalization.

<!-- src: app/ingestion/parser.py::classify_sections -->
```python
def classify_sections(sections: list[Section]) -> None:
    """Distinguish a valid short disclosure from a broken thin section.

    Short 10-K sections are usually valid:
      "None." / "Not applicable."        → empty_disclosure
      "...incorporated by reference..."  → incorporated_by_reference (for example, proxy)

    An ``xref`` index reports status directly and needs no inference. This function
    applies only to title- and number-based segmentation.
    """
    for s in sections:
        text = " ".join(b.text for b in s.blocks if b.kind == "paragraph")[
            :CLASSIFY_SCAN_CHARS
        ].strip()
        if not text:
            continue
        if EMPTY_RE.match(text):
            s.status = "empty_disclosure"
        elif len(s.blocks) <= REF_MAX_BLOCKS and REF_RE.search(text):
            s.status = "incorporated_by_reference"
```

It is worth spelling out why `len(s.blocks) <= REF_MAX_BLOCKS` is there.

The phrase "incorporated by reference" can appear inside a section with a long body — a sentence in the middle of Item 1's business description saying "details are incorporated by reference to Exhibit 21." Without the block-count limit, that whole section gets stamped `incorporated_by_reference`.

Then **a body that plainly exists looks absent.** It drops out of retrieval, and validation passes anyway. What happens if the classification is simply missed? It stays `parsed`, treated as having a body — and if it really is short, L12 flags it as a thin section.

**Misclassification is more dangerous than non-classification** is the judgment here. So reference classification is allowed only when there are three blocks or fewer.

Now the dispatcher.

<!-- src: app/ingestion/parser.py::segment -->
```python
def segment(
    soup: BeautifulSoup,
    blocks: list[Tag],
    seg: dict,
    offsets: list[int] | None = None,
    source_end: int | None = None,
) -> tuple[list[Section], list[dict]]:
    """Dispatch segmentation by type and return sections plus source index records.

    Source index records are populated only for ``xref`` filings.
    """
    match seg["type"]:
        case "xref":
            return segment_by_xref(soup, blocks, offsets, source_end)
        case "undefined":
            return [], []
        case _:
            sections = segment_by_heading(blocks, seg, offsets, source_end)
            classify_sections(sections)  # distinguish valid short disclosures from bugs
            return sections, []
```

This short function does more than it looks. **It confines type branching to one place.**

Callers `parse_filing` and `build_profile` call only `segment()` and never need to know which strategy is active. Add a fourth strategy later and the callers do not change.

Calling `classify_sections` here is the same idea. It must not run for `xref`, and if callers had to know that condition, every caller would need review whenever a strategy is added. Inside the dispatcher, that knowledge stays in one place.

**When branch conditions scatter, adding a new case always misses one of them.** Funneling through a single entry point is usually the answer.

### Verify

```bash
uv run pytest tests/ingestion/test_04_validate.py -k classify -v
```

This runs without the corpus and checks four cases: "None.", "Not applicable.", a proxy sentence, and a long body.

## What you should be able to explain now

- **Why does the detection function double as a config builder?**
  - **Answer:** Detection already measures the candidate headings' style and location, and those measurements are the configuration the parser needs. Returning either `{}` or a populated config avoids doing the same measurement twice.
- **What justifies separating a TOC from body headings by density?**
  - **Answer:** TOC entries cluster in a narrow part of the filing because little body text separates them, whereas real body headings are spread across the document. Their relative span therefore provides a measurable density signal.
- **Which filings change result if the cascade order changes?**
  - **Answer:** Ordinary heading-based 10-Ks with a TOC can be misclassified as xref filings if `detect_xref` runs first; NVIDIA is the measured example. Trying `detect_number` first establishes that body Item headings are absent before the exceptional xref path runs.
- **What separates a one-line "Not applicable" Item from a parse failure?**
  - **Answer:** An explicit phrase matched near the start of a short section gives it `empty_disclosure` status. An unexpectedly thin section without that evidence remains `parsed` and is left for validation to flag.
- **Why keep an undetected filing as `undefined` instead of discarding it?**
  - **Answer:** `undefined` preserves the observable fact that no supported strategy matched, instead of making the filing vanish silently. That state can be reported, stored, and revisited when detection improves.

---

[← Previous: Xref segmentation](05-segment-xref.md) · [Module overview](../03-build.md) · [Next: Profiles and validation →](07-profile-validate.md)
