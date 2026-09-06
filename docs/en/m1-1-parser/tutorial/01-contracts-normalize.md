# M1.1 Tutorial 1 — Nail down what comes out first

This document builds the parser's first two layers. L1 declares what the module emits as data structures; L2 prepares the text those structures will hold. No cutting happens yet.

The order can feel backwards. The usual habit is to parse first and tidy up later. Here the **output contract is nailed down first**, so the twelve layers below have a fixed target to stack toward.

**Prerequisite:** `uv sync --locked --group dev` has completed, and `data/corpus/manifest.json` plus the twenty filing snapshots are present. Start with `app/ingestion/parser.py` empty.

## What to write and where to implement it yourself

| Stretch | Learning action | What to take away |
|---|---|---|
| L1 `Block`, `Section`, `ParsedFiling` | **Write the model declarations** | why verification is impossible without coordinate fields |
| L1 SEC constants and regexes | **Define the configuration schema** | confirming that no number was chosen arbitrarily |
| L2 `normalize` | **Implement** the removal/unwrap boundary | stripping iXBRL while keeping the numbers |
| L2 `line_offsets`, `source_pos` | **Review the boundary conversion** | why coordinates are fixed before normalization |

---

## L1 — Data structures come first

First create empty `app/__init__.py` and `app/ingestion/__init__.py`, then open a new canonical `app/ingestion/parser.py`. Do not add the xref import until `xref.py` exists in L8. Begin the file with these imports.

#### Create `app/ingestion/parser.py` — imports and data-structure foundation

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

The most common parser mistake is "parse first, organize later." It feels faster at the start. A month in, intermediate representations are floating around as dicts, accesses like `result["blocks"][0]["pos"]` are scattered through the code, and nobody remembers where that `pos` came from.

So we go the other way. **Nail down what comes out before anything else.** The three classes below are this module's entire output contract.

### Without coordinates, verification is impossible

Once the parser is finished, this moment arrives. You run it and it reports 23 Items. The Item order matches SEC canonical order, there are no duplicates, and the first section is 51k characters. It looks perfect.

Is it actually right?

Without positions in the output there is no way to check. Only indirect metrics remain — counts and sizes. And those metrics **come out just as perfect when the table of contents was mistaken for headings.** A TOC has all 23 Items, in order, without duplicates. That failure really happened in this project ([B10](../04-bugs.md#b10)).

`source_pos` changes that. Open the original HTML at that offset and compare by eye (final check ④ in [05-verify.md](../05-verify.md)). And as described above, this coordinate travels through M1.3 → M1.4 → M4 to become the evidence behind the final citation.

### Why a dataclass instead of a dict

With a dict, a typo like `sec["itme"]` survives until runtime — and with bad luck, blows up in production as a `KeyError`. A dataclass turns the same typo into an immediate `AttributeError`, gives editors field completion, and uses `field(default_factory=list)` to prevent the classic Python trap of sharing a mutable default across instances.

### `Literal` enforces nothing at runtime

Writing `SegmentType = Literal["number", ...]` does not make Python check the value while running. It is documentation for type checkers and people. Actual protection comes from making the detection functions in [L9](06-detect-classify.md#l9--detection-cascade--which-strategy-fits-this-filing) return only those values. Python's model is: types record intent, and code enforces it.

> ⚠ For the record, `SegmentType` is **declared but never used as an annotation**. `ParsedFiling.segment_type` is simply `str`. `ItemStatus` is actually used by `Section.status`.

The `int | None` spelling has been standard since Python 3.10, so no `typing.Optional` import is needed.

### Build

#### Target file: `app/ingestion/parser.py`

<!-- src: app/ingestion/parser.py::SegmentType,ItemStatus -->
```python
SegmentType = Literal["number", "sec_canonical", "custom_title", "xref", "undefined"]
ItemStatus = Literal["parsed", "empty_disclosure", "incorporated_by_reference"]
```

**What to look for in the code**

- Both aliases are `Literal`, so nothing is checked at runtime. The point is to write the set of values down in one place.
- The five values of `SegmentType` are everything the L9 detection cascade may return. A value outside this set means L9 has a bug.
- `ItemStatus` separates the different reasons a body can be absent — present, legitimately not applicable, or deferred to another filing. L10 decides among the three.

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

**What to look for in the code**

- Four of the nine fields (`source_pos`, `end_pos`, `source_group`, `source_heading`) exist for coordinates and provenance. Those four ride all the way to M1.3's chunk bounds and M4's citations.
- `html` is populated for tables only. Whatever L3 judges to be a data table keeps its raw HTML and hands it to M1.2.
- `kind` has exactly three values, which fixes here how many cases every later layer has to branch on.

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

**What to look for in the code**

- Separating `canonical_title` from `reported_title` is the key decision. The first is the SEC's canonical title, the second is what the company actually printed. Collapse them and you lose what Intel called Item 1A.
- `block_index`, `block_range`, and `source_pos` are evidence of where an Item was found, not a claim that it was. Without them L12's validation can only look at counts and ordering.
- `status` is the only place `ItemStatus` is actually used.

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

SEC-defined constants live here too. **Separate what does not change from what does at the top of the file.**

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

**What to look for in the code**

- All three are facts fixed by the SEC, not values measured from the corpus. They are never re-measured; they change only when the regulation does.
- `ORDER = list(CANONICAL)` reuses the dictionary's insertion order. L12's Item-ordering validation takes that order as its reference.
- `PART_OF` is built with `dict.fromkeys` so that a Part can be found directly from an Item. Storing the list of Items per Part instead would mean inverting it on every lookup.

<!-- src: app/ingestion/parser.py::ITEM_RE -->
```python
ITEM_RE = re.compile(
    r"^\s*item\s+(?P<num>1[0-6]|[1-9])(?P<suffix>[A-C])?\s*[.\-–—:]?\s*(?P<title>.*)$",
    re.I,
)
```

This regular expression hides two traps.

First, the **order** in `1[0-6]|[1-9]`. Write `[1-9]|1[0-6]` by reflex and, on meeting "Item 15", it consumes only `1` and stops. Item 15 becomes Item 1. Regex alternation (`|`) tries left to right and takes the first match, so **the longer pattern has to sit on the left.**

Second, the leading `^`. Without it every mid-sentence cross-reference such as "as described in Item 1A above" becomes a heading candidate. A single 10-K contains dozens of those sentences ([F2](../01-findings.md#f2)). The `^` imposes the condition "only when the block starts with these characters."

### Tuning constants — not one arbitrary number

The twenty-odd constants below all come from directly measuring the 20-document corpus. That is why each value carries its evidence in a comment, and why changing one means measuring again.

One rule applies. **Values with different meanings stay separate even when equal.** `LAYOUT_CELL_CHARS` and `HEADING_MAX_CHARS` are both 300 and are distinct constants. The first means "a cell this long makes it a layout table"; the second means "a block longer than this cannot be a heading." Merge them and the day you need to tune only one, a search for `grep 300` edits the wrong place.

> The block below is source code, not a hand-copied table. `scripts/check_doc_code.py` compares it, so the values in the document and the code cannot drift apart.

The first group is used by L3 blockification to separate data tables from layout tables ([F9](../01-findings.md#f9)); the rest follow the layer labels in the comments. There is no need to absorb all of it now — each is explained again on arrival at its layer.

#### Target file: `app/ingestion/parser.py`

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


Some numbers are **deliberately not constants** because they are not measurements:

| Left inline | Why |
|---|---|
| The `font_weight` value `700` | A **CSS specification**, not a tuning value (`bold` == 700) |
| `10**9` (next-page sentinel) | The conventional representation of "infinity"; naming it adds no clarity |
| `text[:4]` (year slice) | Structure determined by the shape of `"2024-01-28"` |
| CLI output widths (`:12`, `:>9,`) | Display-only and unrelated to parser behavior |
| Quantifiers inside regular expressions (`\d{1,3}`, `{0,80}`) | Part of the pattern; extracting them would make it harder to read |

### Verify

```bash
uv run pytest tests/ingestion/test_02_rules.py -k item_regex -v
```

This runs without the corpus. Verify that `Item 15` produces `"15"` (alternation order) and that `"as described in Item 1A above"` produces `None` (the `^` anchor).

---

## L2 — Normalization — removing and unwrapping are different

Now we actually read the HTML. But one decision comes first: which parser?

### A slower parser was chosen on purpose

Parsing HTML in Python usually means `lxml`. It is fast. But `lxml` does not populate where each element came from (`sourceline`, `sourcepos`). The standard library's `html.parser` does, given `store_line_numbers=True`. It costs an extra 1.6 seconds across all 20 files.

What those 1.6 seconds buy is **verifiability** ([F15](../01-findings.md#f15)). The coordinates described above come from here. Without them, citations cannot be checked anywhere downstream.

Note also that swapping parsers is risky work. A different parser can change tree structure in subtle ways. So before switching, block text was confirmed **identical character for character** across all 20 files. Parser swaps require that kind of equivalence check.

### Line numbers are useless in this document

Getting `sourceline` is not the end of it. A 10-K arrives minified, so a two-megabyte file may hold only five lines. "Line 5" effectively means "somewhere in the file."

`sourcepos` is the position within that line, so the line's start offset has to be added to get an absolute position. With real values:

```
line start offsets: [0, 39, 931, 932, 933]
sourceline=5  sourcepos=197,074  →  absolute 198,007
raw[198007:198030] = 'Item 1. Business <span style="color:#76b900;'
```

The last line is the point. Slice the source at the computed offset and "Item 1. Business" really is there. Making that check available to a human at any time was this module's goal.

### One method name decides whether the financials survive

The numbers in a 10-K are wrapped in iXBRL tags. Those tags must go, and BeautifulSoup offers two methods that look similar.

```
<div>Revenue <ix:nonFraction>26,974</ix:nonFraction> million</div>

decompose() → <div>Revenue  million</div>       ← the number vanishes
unwrap()    → <div>Revenue 26,974 million</div>  ← correct
```

`decompose()` deletes the tag and everything inside it. `unwrap()` removes only the tag and keeps the content. Use `decompose()` when **the content itself is unnecessary**, as with scripts and styles; use `unwrap()` when **only the wrapper is unnecessary**, as with iXBRL.

Reach for `decompose()` here and every number in the financial statements evaporates. The text still looks fine, so the parser appears to work. This is the kind of bug that costs days later, under the heading "why doesn't revenue show up in search?"

### A shared prefix does not imply shared treatment

Every `ix:` tag looks like an `unwrap()` target, but there is one exception. Under the iXBRL specification `ix:header` is a machine-readable metadata region that is **never rendered**. It has to be removed whole with `decompose()`.

What happens if you miss that is instructive. Inside `ix:header` are children such as `xbrli:*` and `xbrldi:*`, which do not carry the `ix:` prefix and so are not unwrap targets. Unwrap only the parent and those children survive, merging **tens of thousands of characters into the first body block** ([F10](../01-findings.md#f10)). Measured: 34,148 characters for MU-FY2024 and 59,005 for INTC-FY2019.

**Order matters too.** Remove `ix:header` first, then unwrap the rest.

### Suppress warnings in this call, not globally

A 10-K is XHTML beginning with `<?xml ...?>`, so BeautifulSoup raises `XMLParsedAsHTMLWarning`. It is tempting to silence it with `filterwarnings` at module scope — which would silently consume warnings from **other code using the library**. That is a common piece of library-development rudeness. `catch_warnings()` limits suppression to this call.

### Build — Normalization — strip iXBRL, keep the numbers

#### Target file: `app/ingestion/parser.py`

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

**What to look for in the code**

- `keepends=True` is the whole function. Line-break characters have to count toward the length for the offsets to match the source. Drop them and every line is off by one, and the error accumulates.
- The return value is a table from line number to absolute offset. BeautifulSoup reports only line numbers, so `source_pos` uses this table to recover the absolute position.

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

Coordinates and hashes must refer to the same input, so the project needs one reader. Define these two functions after `source_pos()`.

<!-- src: app/ingestion/parser.py::read_source,source_digest -->
```python
def read_source(path: str | Path) -> str:
    """Decode source bytes as UTF-8 without universal-newline translation."""
    return Path(path).read_bytes().decode("utf-8")


def source_digest(source: str) -> str:
    """Bind character offsets to the exact UTF-8 source snapshot."""
    return hashlib.sha256(source.encode("utf-8")).hexdigest()
```

**What to look for in the code**

- `read_bytes().decode("utf-8")` is used because opening in text mode makes Python translate `\r\n` into `\n`. The moment it does, the character count shrinks and every offset is wrong.
- `source_digest` pins which snapshot the coordinates belong to. A different hash means the coordinates cannot be trusted, and M1.4's database rows and M3's golden identifiers inherit this value unchanged.


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

**What to look for in the code**

- The difference between `decompose()` and `unwrap()` is the whole function. The first deletes the node and its descendants; the second strips only the tag and keeps the text inside.
- `ix:header` alone gets `decompose` because it is a non-rendered XBRL definition region. Unwrap it and thirty to sixty thousand characters spill into the first body block.
- Every other `ix:*` tag gets `unwrap`. The financial figures live inside those tags, so deleting them deletes the numbers.
- The reason for `html.parser` is in the comment. `lxml` is faster but leaves `sourceline` empty, which makes coordinates impossible. Verifiability was chosen over speed.

### Verify

```bash
uv run pytest tests/ingestion/test_01_blocks.py -k ixbrl_numbers_survive -v
```

Check both that numbers survive (`unwrap`) and that XBRL noise stays out (`decompose`). `test_ixbrl_numbers_survive` runs without the corpus.

**Pitfalls encountered** — [B09](../04-bugs.md#b09), unwrapping `ix:header`; and [B17](../04-bugs.md#b17), `lxml` does not populate positions

## What you should be able to explain now

- **What changes when the output contract is fixed as dataclasses rather than dicts?**
  - **Answer:** Field names and defaults become one explicit schema, so misspellings fail immediately and editors and type checkers can inspect the contract. `default_factory` also prevents mutable lists from being shared between instances.
- **Why does a parse become unverifiable without `source_pos`?**
  - **Answer:** Counts and Item order can look correct even when the parser captured the TOC. `source_pos` lets a reviewer reopen the exact source location and later lets chunks carry checkable citation coordinates.
- **Why declare `Literal` at all when it enforces nothing at runtime?**
  - **Answer:** It records the allowed vocabulary for readers and static type checkers in one place. Runtime safety still comes from detection and classification functions returning only those values.
- **Why must coordinates be fixed before normalization?**
  - **Answer:** Coordinates describe the original decoded HTML, but normalization removes nodes and unwraps tags. Capturing the parser's original line and column positions first preserves a mapping that the transformed tree cannot reconstruct.
- **What separates removal (`decompose`) from unwrapping (`unwrap`)?**
  - **Answer:** `decompose()` deletes a node and all its content, so it is for scripts, styles, and the non-rendered `ix:header`. `unwrap()` removes only the wrapper and keeps its text, which is required for financial values inside other iXBRL tags.

---

[Module overview](../03-build.md) · [Next: Blocks and properties →](02-blocks-props.md)
