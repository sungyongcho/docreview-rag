# M1.1 Build — Starting from One Two-Megabyte HTML File

## Open the file first

Open `data/corpus/NVDA/2024-02-21_0001045810-24-000029.html` in an editor. It is NVIDIA's 10-K annual report filed with the SEC in 2024. It is over two megabytes, almost entirely without line breaks, and your editor will stall for a moment. Scroll through it and you will find all of this mixed together:

- body text meant for people
- financial figures wrapped in iXBRL tags such as `<ix:nonFraction>`
- a cover page and a table of contents
- a "Table of Contents" page header repeated on every page
- real tables (financial statements) and tables used purely for layout

What we ultimately want is this. **Ask "what are NVIDIA's 2024 risk factors?" and get back the supporting paragraphs, with coordinates showing exactly where in the source they came from.**

To get there, this HTML has to be cut along the SEC's Item boundaries — Item 1 Business, Item 1A Risk Factors, Item 7 MD&A, and so on. That is this chapter's job.

## Why this is hard — every company files differently

Surely a regular expression for "Item 1A" is enough? Measure the 20-document corpus and the answer is no.

| Company | How Items appear in the body |
|---|---|
| NVIDIA, MU | `Item 1A. Risk Factors` as a bold paragraph |
| AMD (FY2019) | The same heading, but **inside a table cell** |
| Intel (2019+) | Item numbers are **absent from the body entirely**, restructured under proprietary titles such as `Fundamentals of Our Business` |

Measured on INTC FY2022: of 2,267 leaf blocks, **zero** begin with `Item N`. No amount of font-rule sophistication finds something that is not there.

On top of that, the literal string "Item 1A" appears throughout the document — in the table of contents, and in mid-sentence cross-references like "see Item 1A above." Same characters, and only one of them is the real heading.

## The path this project takes

A machine-learning classifier is an option, but there is no labeled data. Instead this project **measures the corpus, learns per-company formatting rules, and segments deterministically using them.** No LLM, no trained model. The same input always produces the same output.

There are three strategies.

1. **`number`** — the body has `Item 1A.` headings. 15 of 20 documents. The parser learns from the file itself which typography marks a heading, which separates real headings from the TOC and cross-references. 2. **`xref`** — the body was restructured, as Intel's was. 5 documents. The SEC permits restructuring only in exchange for a mandatory **Cross-Reference Index** — a table stating which pages hold which Item. The document carries its own answer. 3. **`undefined`** — the fallback when both fail. It never fires in this corpus.

All three produce the **same output**: a list of `Section` objects, each holding a list of `Block` objects. And every Block carries a character offset into the original HTML.

## Why those coordinates matter so much

A field like `Block.source_pos` looks incidental at first. It is in fact the axis this entire project turns on.

The most common failure in a RAG system is an answer that sounds right and cannot be checked. When a model says "NVIDIA disclosed supply-chain concentration risk," there has to be a way to tell whether that sentence is really in the document or was invented.

Coordinates make that possible. Open the source file at that offset and compare by eye. And the coordinate does not stop here — it is carried all the way through the pipeline.

```
M1.1 (this chapter)  Block.source_pos / end_pos ────┐
M1.3 chunking         Chunk.start_char / end_char ←─┘  inherited as chunk bounds
M1.4 seeding          the start_char column in chunks  persisted
M2  retrieval         carried on every search result
M4  workflow          the evidence behind the final report
```

Omit this one field now and the end of the pipeline can only say "trust me."

## What you will build in this chapter

You will stack `app/ingestion/parser.py` from L1 through L14, writing `app/ingestion/xref.py` separately in L8.

```
Raw HTML (2 MB, minified, iXBRL)
    │
    ▼
L1  Data structures + SEC constants   nail down the output contract first
L2  Normalization                     strip iXBRL, keep the numbers
L3  Blockification                    data table vs layout table
L4  Property extraction               inline CSS → dict
L5  Rule evaluator                    rules are data, not code
L6  Context signals                   learning filters (unused in final rules)
    │
    ▼
L7  Segmentation A                    heading walk — the number family
L8  Segmentation B                    xref page join — separate module
L9  Detection cascade                 which strategy fits this filing?
L10 Status classification + dispatch  "Not applicable" is not a bug
    │
    ▼
L11 Profile I/O                       per-company, per-year learned rules
L12 Validation                        catches structurally perfect failure
L13 Orchestration                     load → parse → validate → relearn
L14 CLI                               the path for human inspection
```

Layer numbers match the physical order inside `parser.py`. Reading top to bottom builds the file in place. And **lower layers do not know about higher ones.** Blockification (L3) knows nothing of segmentation, and segmentation (L7) knows nothing of where the profile came from. That is what makes each layer separately testable and repairable.

### Fourteen layers are not fourteen equal problems

Fourteen is intimidating, but only four of them contain a real algorithm. The rest are contract declarations or arrangement. Drawing that line first decides where the time goes.

| Character | Layers | Learning action |
|---|---|---|
| Contract declaration | L1, L11 | **Write the model declarations** — check only what each field forbids |
| Algorithm | L3, L7, L8, L9 | **Implement** the core logic yourself — spend the time here |
| Conversion | L2, L4, L10 | **Write the field mapping, then inspect boundary conversions** |
| Rules and validation | L5, L6, L12 | **Implement** the decision rules yourself |
| Arrangement | L13, L14 | **Write the structure, then inspect call order** |

L8 is the only layer that creates a separate file (`app/ingestion/xref.py`). The other thirteen stack into `parser.py` in order.

## Before you start

The `zero` branch may already contain the learning baseline. To rebuild it yourself, do not create a separate `_mine.py`; start with the canonical paths above in an empty state. Commands appear only after the code they exercise is defined. A skip caused by a missing required symbol does not count as a pass.

The `<!-- src: ... -->` marker before a code block is what `scripts/check_doc_code.py` uses to compare against the real source. A marked block is production code for the finished file, not illustrative pseudocode. Corpus-dependent checks require `data/corpus/manifest.json` and the 20 filing snapshots.

---

## The tutorial — built in eight sittings

M1.1 produces fourteen layers across two files. That is more than one sitting, so it is split into eight stretches, each finished and closed by a test. Each document targets **under 30 minutes** to read and implement, with document 5 the one exception.

| Document | Layers | Files produced | Approx. |
|---|---|---|---:|
| [1. Contracts and normalization](tutorial/01-contracts-normalize.md) | L1–L2 | `parser.py` started | 30 min |
| [2. Blocks and properties](tutorial/02-blocks-props.md) | L3–L4 | `parser.py` extended | 30 min |
| [3. Rule evaluator](tutorial/03-rules.md) | L5–L6 | `parser.py` extended | 25 min |
| [4. Heading segmentation](tutorial/04-segment-heading.md) | L7 | `parser.py` extended | 30 min |
| [5. Xref segmentation](tutorial/05-segment-xref.md) | L8 | `xref.py` added | 45 min |
| [6. Detection and classification](tutorial/06-detect-classify.md) | L9–L10 | `parser.py` extended | 30 min |
| [7. Profiles and validation](tutorial/07-profile-validate.md) | L11–L12 | `parser.py` extended | 30 min |
| [8. Orchestration and CLI](tutorial/08-orchestration-cli.md) | L13–L14 | `parser.py` finished, `edgar.py` | 40 min |

Work through them in order. Do not move on while a stretch's focused test is failing. Every document states its prerequisite at the top and links to the next one at the end.

The [reference baseline](#reference-baseline--the-complete-canonical-files) below is not a shortcut past the learning; it is the **standard you check your own work against**. Compare after finishing each stretch, never before.

---

## What this module hands to the next one

Finishing M1.1 turns all 20 files into `ParsedFiling` objects. Here is where each part of that goes.

| What M1.1 produced | Receiver | What happens there |
|---|---|---|
| `Block.html` (data tables) | **M1.2** | HTML table → markdown table |
| `Block.source_pos` / `end_pos` | **M1.3** | inherited as chunk boundary coordinates |
| `Block.source_heading` (level-2 subheadings) | **M1.3** | used as a chunk's context header |
| `Section.item` / `status` | **M1.3** | chunk Item attribution and filters |
| `ParsedFiling.source_sha256` | **M1.4** | source identity check on database rows |
| `ParsedFiling.item_index` (xref) | **M1.4** | evidence for Items with no body |

The very next chapter is M1.2. It takes the **data-table HTML** that was only classified here, never touched, and folds it into markdown while preserving row and column relationships. That is the step where financial statements become searchable.

### What you should be able to explain now

- **Why must coordinates be fixed before normalization?**
  - **Answer:** Coordinates belong to the original decoded HTML; removing or unwrapping tags changes the tree and cannot recreate those original positions. Fixing them first keeps every later block and citation traceable to the source.
- **What happens to the financial statements if data tables are not separated from layout tables?**
  - **Answer:** Traversing every table shatters financial statements into cells and loses row-column relationships, while consuming every table whole hides headings inside layout tables. Classification preserves data tables intact and walks through layout tables.
- **What becomes possible once rules are data rather than code?**
  - **Answer:** One evaluator can interpret learned per-company profiles, so a new format changes profile data instead of adding another parser branch. The rule contract can also be tested in one place.
- **Why are both Segmentation A and Segmentation B needed?**
  - **Answer:** Segmentation A walks explicit Item headings, which works for fifteen corpus filings. The five Intel filings have no such body headings, so Segmentation B joins their required Cross-Reference Index with the company TOC by page range.
- **What does a structurally perfect but failed parse look like, and what catches it?**
  - **Answer:** Mistaking the TOC for body headings can produce the right Item count, order, and uniqueness while every section contains almost no body. Validation catches it by checking for abnormally thin core Items, not structure alone.
- **Why are only successful profiles saved?**
  - **Answer:** This rule currently applies to relearned profiles: a failed relearn is not saved, so the next run does not start from a known-bad update. The bootstrap path is an exception because it writes a newly built profile before its first validation.

---

## When you need one layer again

On the first pass, run each command where its section introduces it. After the implementation is complete, use this list as a bookmark for rerunning one layer. If one turns red, return to that layer and investigate the first failure.

```bash
# L1
uv run pytest tests/ingestion/test_02_rules.py -k "item_regex" -q
# L2
uv run pytest tests/ingestion/test_01_blocks.py -k "ix_header or ixbrl" -q
# L3
uv run pytest tests/ingestion/test_01_blocks.py -q
# L4
uv run pytest tests/ingestion/test_02_rules.py -k "bold_keyword or missing_style or inline_css" -q
# L5
uv run pytest tests/ingestion/test_02_rules.py -q
# L6
uv run pytest tests/ingestion/test_03_segment.py -k "learned_rules_match_golden" -q
# L7
uv run pytest tests/ingestion/test_03_segment.py -k "headings_are_found_by_style_plus_number or cover_page_and_toc_are_dropped" -q
# L8
uv run pytest tests/ingestion/test_06_xref.py -q
# L9
uv run pytest tests/ingestion/test_03_segment.py -k "detect or toc_detector" -q
# L10
uv run pytest tests/ingestion/test_04_validate.py -k "classify" -q
# L11
uv run pytest tests/ingestion/test_05_profile.py -q
# L12
uv run pytest tests/ingestion/test_04_validate.py -q
# L13
uv run pytest tests/ingestion/test_05_profile.py -k "converge or failed_relearn" -q
# L14
uv run pytest tests/ingestion/test_07_coverage.py tests/ingestion/test_08_items.py -q
```

<!-- complete-files:start -->
## Reference baseline — the complete canonical files

Create or replace the canonical paths below directly. Do not create `_mine.py` or another learner-copy module. The earlier excerpts explain individual decisions; the blocks in this section are the finished files to compare against once a checkpoint is done. Preserve the shown type annotations and English comments; `pyproject.toml` is the authoritative Ruff policy.

### M1.1 — Complete checkpoint

#### Create or replace `app/__init__.py`

<!-- file: app/__init__.py -->
```python
```

#### Create or replace `app/ingestion/__init__.py`

<!-- file: app/ingestion/__init__.py -->
```python
```

#### Create or replace `app/ingestion/edgar.py`

<!-- file: app/ingestion/edgar.py -->
```python
import json
from pathlib import Path
import time

import httpx

CIKS = {"NVDA": 1045810, "AMD": 2488, "INTC": 50863, "MU": 723125}
FILING_YEARS = range(2020, 2025)  # filingDate years 2020-2024, about five per company
USER_AGENT = "filing-rag research dev@sungyongcho.com"  # SEC requires a contact address
CORPUS = Path("data/corpus")


def _pick_10k(block: dict) -> list[dict]:
    """Return only the target-year 10-K filings in one submissions block.

    SEC returns a filing list as **parallel arrays**: the same index means the same
    filing. ``strict=True`` matters. If the lengths disagree, a plain ``zip`` stops
    **silently** at the shorter one and drops every filing after it. A document
    missing from the corpus would then raise nothing at all, and a crash is better
    than a silent loss. (Measured: all eight recent and older responses across four
    companies had equal lengths.)
    """
    rows = zip(
        block["form"],
        block["accessionNumber"],
        block["filingDate"],
        block["reportDate"],
        block["primaryDocument"],
        strict=True,
    )
    return [
        {"accession": acc, "filing_date": fd, "report_date": rd, "primary_doc": doc}
        for form, acc, fd, rd, doc in rows
        if form == "10-K" and int(fd[:4]) in FILING_YEARS
    ]


def fetch_10k_list(client: httpx.Client, cik: int) -> list[dict]:
    """Return every target 10-K across the recent and older submissions files."""
    r = client.get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json")
    r.raise_for_status()
    filings = r.json()["filings"]
    result = _pick_10k(filings["recent"])
    # Older filings live in separate files[] entries; fetch one when its range overlaps.
    for extra in filings.get("files", []):
        if int(extra["filingFrom"][:4]) <= max(FILING_YEARS):  # overlaps the target range
            time.sleep(0.2)
            er = client.get(f"https://data.sec.gov/submissions/{extra['name']}")
            er.raise_for_status()
            result += _pick_10k(er.json())
    return result


def download(client: httpx.Client, ticker: str, cik: int, filing: dict) -> dict:
    acc = filing["accession"].replace("-", "")
    url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{filing['primary_doc']}"
    dest = CORPUS / ticker
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / f"{filing['filing_date']}_{filing['accession']}.html"
    if not path.exists():  # idempotent: never re-download a snapshot already on disk
        r = client.get(url)
        r.raise_for_status()
        path.write_text(r.text, encoding="utf-8")
    return {"ticker": ticker, "cik": cik, **filing, "file": str(path), "url": url}


def main() -> None:
    CORPUS.mkdir(parents=True, exist_ok=True)
    manifest = []
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=60.0) as client:
        for ticker, cik in CIKS.items():
            filings = fetch_10k_list(client, cik)
            print(f"{ticker}: {len(filings)} 10-K filings")
            for filing in filings:
                manifest.append(download(client, ticker, cik, filing))
                time.sleep(0.2)  # stay polite to SEC, at most 10 requests per second
    (CORPUS / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    print(f"{len(manifest)} filings total -> {CORPUS}")


if __name__ == "__main__":
    main()
```

#### Create or replace `app/ingestion/parser.py`

<!-- file: app/ingestion/parser.py -->
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

from app.ingestion.xref import (
    _in_tables,
    assign_items,
    find_missing,
    find_tables,
    item_for_page,
    locate_sections,
    page_map,
    parse_toc,
    parse_xref,
)

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


ITEM_RE = re.compile(
    r"^\s*item\s+(?P<num>1[0-6]|[1-9])(?P<suffix>[A-C])?\s*[.\-–—:]?\s*(?P<title>.*)$",
    re.I,
)


# ── Tuning constants ────────────────────────────────────────────────────────
# **Not one of these numbers was chosen arbitrarily.** Every one was measured across the
# 20-document corpus, and changing one means measuring again.
# Evidence notation: F = docs/en/m1-1-parser/01-findings.md, B = docs/en/m1-1-parser/04-bugs.md
#
# Values that happen to be equal but mean different things are declared separately
# (LAYOUT_CELL_CHARS and HEADING_MAX_CHARS are both 300). The code has to say that either
# can move alone, so that `grep 300` does not lead someone to edit the wrong one.

# L3 blocking: separating data tables from layout tables (F9)
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


def read_source(path: str | Path) -> str:
    """Decode source bytes as UTF-8 without universal-newline translation."""
    return Path(path).read_bytes().decode("utf-8")


def source_digest(source: str) -> str:
    """Bind character offsets to the exact UTF-8 source snapshot."""
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def line_offsets(html: str) -> list[int]:
    """Return each line's absolute start offset for ``source_pos`` calculation."""
    out, off = [], 0
    for line in html.splitlines(keepends=True):
        out.append(off)
        off += len(line)
    return out


def source_pos(el: Tag, offsets: list[int]) -> int | None:
    """Return the character where this block starts in the original HTML.

    A minified 10-K can contain only five lines, making line numbers useless.
    ``sourcepos`` is relative to its line, so add the line's start offset to
    obtain an absolute character position.
    """
    if el.sourceline is None or el.sourcepos is None:
        return None
    return offsets[el.sourceline - 1] + el.sourcepos


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


def _is_data_table(tbl: Tag) -> bool:
    """Use numeric-cell density to distinguish financial data from layout tables."""
    cells = tbl.find_all(["td", "th"])
    if len(cells) < DATA_TABLE_MIN_CELLS:
        return False
    texts = [c.get_text(" ", strip=True) for c in cells]
    if any(len(t) > LAYOUT_CELL_CHARS for t in texts):  # a long prose cell means layout
        return False
    numeric = sum(1 for t in texts if t and len(t) < NUMERIC_CELL_CHARS and re.search(r"\d", t))
    return numeric >= max(DATA_TABLE_MIN_NUMERIC, len(cells) // DATA_TABLE_NUMERIC_DIVISOR)


def leaf_blocks(soup: BeautifulSoup) -> list[Tag]:
    data_ids: set[int] = set()
    for t in soup.find_all("table"):
        if _is_data_table(t) and not any(id(p) in data_ids for p in t.find_parents("table")):
            data_ids.add(id(t))  # keep only the outermost nested table

    out = []
    for el in soup.find_all(["div", "p", "table"]):
        inside_data = any(id(p) in data_ids for p in el.find_parents("table"))
        if el.name == "table":
            if not inside_data and (id(el) in data_ids or el.find(["div", "p", "table"]) is None):
                out.append(el)  # keep a data table or legacy leaf table as one block
        elif not inside_data and el.find(["div", "p", "table"]) is None:
            out.append(el)
    return out


def _inline_css(el: Tag) -> str:
    """Combine inline CSS from this element and its first two nested spans."""
    styles: list[str] = []

    own_style = el.get("style")
    if isinstance(own_style, str):
        styles.append(own_style)

    for span in el.find_all("span", limit=2):
        span_style = span.get("style")
        if isinstance(span_style, str):
            styles.append(span_style)

    return " ".join(styles)


def block_props(el: Tag) -> dict:
    css = _inline_css(el)  # element style plus up to two nested span styles

    def num(pattern: str) -> float:
        m = re.search(pattern, css)
        return float(m.group(1)) if m else 0.0

    mw = re.search(r"font-weight:\s*(\d+|bold)", css)
    weight = mw.group(1) if mw else "400"
    return {
        "font_weight": 700 if weight == "bold" else int(weight),
        "font_size": num(r"font-size:\s*([\d.]+)pt"),
        "margin_top": num(r"margin-top:\s*([\d.]+)pt"),
        "margin_bottom": num(r"margin-bottom:\s*([\d.]+)pt"),
        "text_align": (m.group(1) if (m := re.search(r"text-align:\s*(\w+)", css)) else ""),
        "tag": el.name,
        "in_table": el.find_parent("table") is not None,
    }


def matches_rule(el: Tag, rule: dict) -> bool:
    props = block_props(el)
    for key, expected in rule.items():
        actual = props.get(key)
        if actual is None:
            continue  # an unknown key adds no constraint
        if key == "in_table":
            if not expected and actual:  # constrain only when False is expected
                return False
        elif isinstance(expected, bool) or isinstance(actual, bool):
            if actual != expected:
                return False
        elif isinstance(expected, int | float):
            if actual < expected:
                return False  # numeric rules are minimum thresholds
        elif actual != expected:
            return False
    return True


def matches_any(el: Tag, rules: list[dict]) -> bool:
    return any(matches_rule(el, r) for r in rules)


def body_after(blocks: list[Tag], idx: int, span: int = 8) -> int:
    """Measure following body text to filter learning candidates.

    Measured for the three INTC FY2019 "RISK FACTORS" occurrences: 1,851 after
    the heading, 41 after the TOC entry, and 90 after the index entry.
    """
    return sum(
        len(blocks[j].get_text(" ", strip=True))
        for j in range(idx + 1, min(idx + 1 + span, len(blocks)))
    )


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


def block_source_spans(
    blocks: list[Tag], offsets: list[int] | None, source_end: int | None = None
) -> list[tuple[int | None, int | None]]:
    """Return `[start, end)` source spans for an ordered block list.

    A block ends where the next block starts. The final block ends at
    `source_end` when the caller knows the original HTML length. This avoids
    trying to reconstruct closing-tag offsets from BeautifulSoup's normalized
    tree, while preserving the exact coordinate system of the source file.
    """
    if offsets is None:
        return [(None, None) for _ in blocks]

    starts = [source_pos(block, offsets) for block in blocks]
    spans: list[tuple[int | None, int | None]] = [(None, None)] * len(starts)
    next_start = source_end
    for i in range(len(starts) - 1, -1, -1):
        start = starts[i]
        spans[i] = (start, next_start)
        if start is not None:
            next_start = start
    return spans


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


def segment_by_xref(
    soup: BeautifulSoup,
    blocks: list[Tag],
    offsets: list[int] | None = None,
    source_end: int | None = None,
) -> tuple[list[Section], list[dict]]:
    """Segment strategy 2 by joining the index and TOC on page ranges.

    A heading walk cannot work because the body has no Item headings. Return the
    assembled sections and the original index records.
    """
    xref_tbl, toc_tbl = find_tables(soup)
    source_spans = block_source_spans(blocks, offsets, source_end)
    entries = parse_xref(xref_tbl)
    toc = parse_toc(toc_tbl)
    item_index = [
        {
            "item": e.item,
            "reported_title": e.reported_title,
            "pages": e.spans,
            "status": e.status,
            "reference_source": e.reference_source,
        }
        for e in entries
    ]

    skip = _in_tables(blocks, [xref_tbl, toc_tbl])  # TOC and index tables are not body text
    freq = Counter(b.get_text(" ", strip=True) for b in blocks)
    located = locate_sections(blocks, toc, skip)
    assigned = assign_items(located, entries)

    # Search the body for Items omitted from the TOC, such as Legal Proceedings in notes.
    for title, page, bi in find_missing(blocks, entries, set(assigned.values()), skip):
        if bi not in assigned:
            located.append((title, page, bi))
            assigned[bi] = next(e.item for e in entries if e.reported_title == title)
    located.sort(key=lambda t: t[2])
    footer_at = {p: i for i, p in page_map(blocks)}  # page -> footer block

    # A narrative section ends before the next section; image headings can shift the boundary.
    spans: list[tuple[str, str, int, int]] = []  # (item, narrative title, start, end)
    for k, (title, page, bi) in enumerate(located):
        end = located[k + 1][2] if k + 1 < len(located) else len(blocks)
        item = assigned.get(bi)
        if item is None:
            continue
        entry = next(e for e in entries if e.item == item)
        hi = (entry.covering(page) or (page, page))[1]  # end page of this section's range
        next_page = located[k + 1][1] if k + 1 < len(located) else 10**9
        clamp = footer_at.get(hi)
        # Clamp only when the next heading starts more than one page later. A heading on
        # the next page indicates spillover rather than an orphan (measured FY2021 Item 7A).
        if clamp is not None and bi < clamp + 1 < end and next_page > hi + 1:
            orphan_lo, orphan_page = clamp + 1, hi + 1
            end = clamp + 1
            # Assign an orphan range to the Item owning that page (FY2022 pages 72-80 -> Item 8).
            if (
                k + 1 < len(located)
                and (owner := item_for_page(orphan_page, entries))
                and located[k + 1][2] - orphan_lo >= ORPHAN_MIN_BLOCKS  # discard fragments
            ):
                spans.append((owner, CANONICAL.get(owner, ""), orphan_lo, located[k + 1][2]))
        spans.append((item, title, bi, end))
    spans.sort(key=lambda s: s[2])

    # Merge narrative sections assigned to one Item in document order without duplicates.
    by_item: dict[str, list[tuple[str, int, int]]] = {}
    for item, title, lo, hi in spans:
        by_item.setdefault(item, []).append((title, lo, hi))

    sections: list[Section] = []
    for e in entries:
        parts = by_item.get(e.item, [])
        sec = Section(
            part=PART_OF.get(e.item),
            item=e.item,
            canonical_title=CANONICAL.get(e.item, ""),
            reported_title=("; ".join(t for t, _, _ in parts) if parts else e.reported_title)[
                :JOINED_TITLE_MAX
            ],
            status=e.status,
            reference_source=e.reference_source,
            block_index=parts[0][1] if parts else None,
            block_range=(min(p[1] for p in parts), max(p[2] for p in parts)) if parts else None,
            source_pos=(source_pos(blocks[parts[0][1]], offsets) if parts and offsets else None),
        )
        for source_group, (_title, lo, hi) in enumerate(parts):
            for j in range(lo, hi):
                if j in skip:
                    continue
                text = blocks[j].get_text(" ", strip=True)
                if not text:
                    continue
                # Page footers such as "71" and repeated page headers are not body text.
                if re.fullmatch(r"\d{1,3}", text) or (
                    len(text) < PAGE_HEADER_MAX_CHARS and freq[text] >= PAGE_HEADER_MIN_REPEATS
                ):
                    continue
                sec.blocks.append(
                    _body_block(
                        blocks[j],
                        text,
                        *source_spans[j],
                        source_group=source_group,
                        source_heading=_title,
                    )
                )
        sections.append(sec)
    return sections, item_index


def detect_segmentation(soup: BeautifulSoup, blocks: list[Tag]) -> dict:
    """Try measured segmentation strategies in order and accept the first match.

    Strategy 1 is cheaper and more common. Running strategy 2 first can mistake a
    normal 10-K TOC such as ``Item 1. Business ... 3`` for a cross-reference index;
    establish the absence of body Item headings first.
    """
    return detect_number(blocks) or detect_xref(soup, blocks) or {"type": "undefined"}


EMPTY_RE = re.compile(r"^\s*(none|not applicable|n/?a)\.?\s*$", re.I)
REF_RE = re.compile(
    r"(incorporated (herein )?by reference|is set forth in|will be (contained|included) in"
    r"|information (required by|regarding).{0,80}(proxy|incorporated|set forth))",
    re.I,
)


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


PROFILES = Path("data/profiles")


def load_profile(ticker: str, year: int) -> dict | None:
    """Load the requested year's profile, then the default, or ``None`` to bootstrap.

    Each year is self-contained, so these three lines need no merge policy and
    never have to decide which fields should be combined.
    """
    path = PROFILES / f"{ticker}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    return data["profiles"].get(str(year)) or data["profiles"].get(data["default_year"])


def save_profile(ticker: str, year: int, profile: dict) -> None:
    """Store one year entry and point ``default_year`` to the latest year.

    Layouts evolve forward, so a new filing is more likely to resemble a recent
    year. Freezing the first bootstrap year breaks measured AMD data because only
    FY2019 places headings inside a table (F4), making the exception the default.
    """
    PROFILES.mkdir(parents=True, exist_ok=True)
    path = PROFILES / f"{ticker}.json"
    data = (
        json.loads(path.read_text())
        if path.exists()
        else {"ticker": ticker, "default_year": str(year), "profiles": {}}
    )
    data["profiles"][str(year)] = profile
    data["default_year"] = max(data["profiles"], key=int)
    # Store years in ascending order for human readability.
    data["profiles"] = dict(sorted(data["profiles"].items(), key=lambda kv: int(kv[0])))
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


CORE_ITEMS = ("1", "1A", "7", "8")


def _validate_xref(sections: list[Section], index: list[dict], exp: dict) -> list[str]:
    """Validate xref filings with coverage rather than order and uniqueness.

    Items are legitimately scattered across the filing, so order and duplicates
    are not meaningful. Instead, require every indexed Item to be explained by
    assigned body text, an empty disclosure, or incorporation by reference.
    """
    problems: list[str] = []
    explained = {s.item for s in sections if s.item and (s.blocks or s.status != "parsed")}
    if missing := sorted({e["item"] for e in index} - explained):
        problems.append(f"unexplained items: {missing}")
    if miss := sorted(set(exp["must_have"]) - {s.item for s in sections if s.blocks}):
        problems.append(f"missing core items: {miss}")
    thin = sorted(
        s.item for s in sections if s.status == "parsed" and len(s.blocks) < XREF_THIN_BLOCKS
    )
    if index and len(thin) > len(index) * XREF_THIN_RATIO:
        problems.append(f"too many thin sections: {thin}")
    return problems


def validate(sections: list[Section], profile: dict, index: list[dict] | None = None) -> list[str]:
    """Return all parse problems; an empty list means validation succeeded.

    Collecting problems instead of raising at the first one exposes every defect.
    The caller can decide whether to relearn with one ``if problems`` check.
    """
    seg, exp = profile["segmentation"], profile["validation"]
    if seg["type"] == "xref":
        return _validate_xref(sections, index or [], exp)
    items = [s.item for s in sections if s.item]
    problems: list[str] = []

    if len(items) != exp["expected_items"]:
        problems.append(f"item count {len(items)} != expected {exp['expected_items']}")

    # Use custom_title array order when present; otherwise use canonical SEC order.
    ranking = [e["item"] for e in seg["order"]] if seg["type"] == "custom_title" else ORDER
    rank = {v: i for i, v in enumerate(ranking)}
    checked = [i for i in items if i in rank]
    if checked != sorted(checked, key=lambda i: rank[i]):
        problems.append("items are out of order")

    if dup := sorted({i for i in items if items.count(i) > 1}):
        problems.append(f"duplicates: {dup}")

    if miss := sorted(set(exp["must_have"]) - set(items)):
        problems.append(f"missing core items: {miss}")

    # Fail even with perfect structure when body content is absent, as with TOC headings.
    thin = sorted(
        s.item
        for s in sections
        if s.item in CORE_ITEMS and s.status == "parsed" and len(s.blocks) < CORE_THIN_BLOCKS
    )
    if len(thin) >= CORE_THIN_COUNT:
        problems.append(f"looks like a contents table (core items with no body): {thin}")

    return problems


def parse_filing(entry: dict) -> tuple[ParsedFiling, dict]:
    """Run one filing through profile loading, parsing, validation, and relearning.

    Return the parsed result and the profile used.
    """
    ticker, year = entry["ticker"], int(entry["report_date"][:4])
    doc_id = f"{ticker}-FY{year}"
    raw = read_source(entry["file"])
    soup = normalize(raw)
    blocks = leaf_blocks(soup)
    offsets = line_offsets(raw)

    out = ParsedFiling(
        doc_id=doc_id,
        ticker=ticker,
        cik=str(entry.get("cik", "")),
        form="10-K",
        filing_date=entry.get("filing_date", ""),
        report_period=entry.get("report_date", ""),
        fiscal_year=year,
        accession=entry.get("accession", ""),
        source_url=entry.get("url", ""),
        source_length=len(raw),
        source_sha256=source_digest(raw),
        n_blocks=len(blocks),
        n_chars=sum(len(b.get_text(" ", strip=True)) for b in blocks),
    )

    profile = load_profile(ticker, year)
    out.profile_used = "saved"
    if profile is None:
        profile = build_profile(soup, blocks, doc_id)
        save_profile(ticker, year, profile)
        out.profile_used = "bootstrap"

    sections, index = segment(soup, blocks, profile["segmentation"], offsets, len(raw))
    problems = validate(sections, profile, index) if sections else ["zero sections"]

    if problems:
        # On failure, relearn from this filing and store only this year after success (F4).
        relearned = build_profile(soup, blocks, doc_id)
        r_sections, r_index = segment(soup, blocks, relearned["segmentation"], offsets, len(raw))
        r_problems = validate(r_sections, relearned, r_index) if r_sections else ["zero sections"]
        if not r_problems:
            save_profile(ticker, year, relearned)  # save only a successful profile
            profile, sections, index, problems = relearned, r_sections, r_index, r_problems
            out.profile_used = "relearned"

    out.sections = sections
    out.item_index = index
    out.warnings = problems
    out.parse_status = "parsed" if not problems else "needs_profile_update"
    out.segment_type = profile["segmentation"]["type"]
    return out, profile


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="10-K parser, for step-by-step inspection")
    ap.add_argument("--ticker", help="one company only, for example NVDA")
    ap.add_argument("--file", help="one file only, by path")
    ap.add_argument("--blocks", action="store_true", help="stages 1-2: the blocking result")
    ap.add_argument("--sections", action="store_true", help="body size and table count per section")
    ap.add_argument(
        "--headings",
        action="store_true",
        help="block index, source offset, and following body for every Item heading",
    )
    ap.add_argument(
        "--coverage",
        action="store_true",
        help="section body total over document total, which catches discarded text",
    )
    ap.add_argument(
        "--items",
        action="store_true",
        help="compare against the SEC Item list, catching missed and false headings",
    )
    ap.add_argument("--profile", action="store_true", help="the learned profile as JSON")
    a = ap.parse_args()

    manifest = json.loads(Path("data/corpus/manifest.json").read_text())
    targets = [e for e in manifest if not a.ticker or e["ticker"] == a.ticker]
    if a.file:
        targets = [e for e in manifest if e["file"] == a.file]
    if not targets:
        raise SystemExit(f"no targets (ticker={a.ticker} file={a.file})")

    stats: dict[str, int] = {}
    for entry in sorted(targets, key=lambda e: (e["ticker"], e["report_date"])):
        # Stages 1-2 run before parsing, so they are handled separately
        if a.blocks:
            soup = normalize(read_source(entry["file"]))
            blocks = leaf_blocks(soup)
            tables = [b for b in blocks if b.name == "table"]
            doc_id = f"{entry['ticker']}-FY{entry['report_date'][:4]}"
            print(
                f"{doc_id:12} blocks {len(blocks):5,}  table blocks {len(tables):4}  "
                f"document tables {len(soup.find_all('table')):4}"
            )
            continue

        r, profile = parse_filing(entry)
        stats[r.segment_type] = stats.get(r.segment_type, 0) + 1

        if a.profile:
            print(f"--- {r.doc_id} ({r.profile_used}) ---")
            print(json.dumps(profile, indent=2, ensure_ascii=False))
            continue

        if a.headings:
            raw = read_source(entry["file"])
            print(f"--- {r.doc_id} ({r.segment_type}) ---")
            for sec in r.sections:
                head = raw[sec.source_pos : sec.source_pos + 46] if sec.source_pos else ""
                body = next((b.text for b in sec.blocks if b.kind == "paragraph"), "")
                print(
                    f"  {sec.item or '-':4} blk{str(sec.block_index):>6} "
                    f"pos{str(sec.source_pos):>10}  {sec.reported_title[:42]}"
                )
                print(f"       source {head!r}")
                print(f"       body   {body[:54]!r}")
            continue

        if a.items:
            # Coverage cannot catch a missed heading: the previous section absorbs it and
            # the total is unchanged. Only comparing against the SEC Item list shows
            # whether the boundaries are right.
            got = [s.item for s in r.sections if s.item]
            missing = [i for i in ORDER if i not in got]
            extra = [i for i in got if i not in ORDER]
            # 1C (added 2023), 9C (added 2021), and 16 (optional) are absent legitimately
            odd = [m for m in missing if m not in ("1C", "9C", "16")]
            print(
                f"{r.doc_id:12} {len(got):2} items  missing={missing or '-'}  "
                f"extra={extra or '-'}{'  <-' if (odd or extra) else ''}"
            )
            continue

        body = sum(len(b.text) for s in r.sections for b in s.blocks)
        tbl_chars = sum(
            len(BeautifulSoup(b.html, "html.parser").get_text(" ", strip=True))
            for s in r.sections
            for b in s.blocks
            if b.kind == "table" and b.html
        )

        if a.coverage:
            pct = (body + tbl_chars) / r.n_chars * 100 if r.n_chars else 0
            print(
                f"{r.doc_id:12} total {r.n_chars:>9,}  sections {body + tbl_chars:>9,}  "
                f"covered {pct:5.1f}%{'   <- low' if pct < 90 else ''}"
            )
            continue

        items = [s.item for s in r.sections if s.item]
        tbl = sum(1 for s in r.sections for b in s.blocks if b.kind == "table")
        print(
            f"{r.doc_id:12} {r.parse_status:20} type={r.segment_type:9} "
            f"{r.profile_used:10} items={len(items):2} body={body:>8,} tables={tbl:3}"
        )
        for w in r.warnings:
            print(f"               ⚠ {w}")

        if a.sections:
            for s in r.sections:
                n = sum(len(b.text) for b in s.blocks)
                t = sum(1 for b in s.blocks if b.kind == "table")
                flag = "" if s.status == "parsed" else f"  [{s.status}]"
                print(
                    f"     Item {s.item or '-':4} {n:>8,} chars tables{t:3}  "
                    f"{s.reported_title[:52]}{flag}"
                )

    if not (a.blocks or a.profile or a.headings):
        print(f"\ntotals: {stats}")
```

#### Create or replace `app/ingestion/xref.py`

<!-- file: app/ingestion/xref.py -->
```python
"""Handle `xref` style 10-K filings by reading the mapping table the document carries.

**Problem.** Not every company divides its body by "Item 1." and "Item 1A.". Since 2019
Intel has restructured its 10-K around its own narrative ("Fundamentals of Our Business" /
"Our Capital" / "Other Key Information" and so on). The body contains **no Item heading at
all** (measured: of 2,267 leaf blocks in INTC FY2022, zero begin with `Item N`, because the
index table is absorbed whole into a data table).

No amount of font and style rules can find something that is not there.

**Solution.** SEC permits this restructuring but requires a **Form 10-K Cross-Reference
Index** with it. The document therefore carries its own table saying which of its parts is
which Item. Combined with the company's own table of contents, the mapping is complete
without an LLM:

    Cross-Reference Index : Item 1A -> Risk Factors -> Pages 53-67
    company contents      : Risk Factors -> Page 53
    => body section "Risk Factors" = Item 1A

The table also reveals that one Item can span several narrative sections (measured, INTC
FY2022: Item 7 = Pages 5-6, 19-44, 47-51, which is eight narrative sections). That is why
this resolves by **page-range overlap** rather than by a one-to-one anchor.
"""

from dataclasses import dataclass, field
import re

from bs4 import BeautifulSoup, Tag

ITEM_CELL = re.compile(r"^item\s+(1[0-6]|[1-9])([A-C])?\s*\.?$", re.I)
EMPTY_CELL = re.compile(r"^\s*(not applicable|none|n/?a|\[?reserved\]?)\.?\s*$", re.I)
REF_CELL = re.compile(r"^\s*\(([a-z])\)\s*$", re.I)
REF_NOTE = re.compile(r"^\(([a-z])\)\s*(.+)$", re.S)
PAGE_NUM = re.compile(r"\d[\d\s]*")
STOPWORDS = {"and", "of", "the", "for", "to", "in", "our", "about", "on", "a", "with"}


# ── Tuning constants ────────────────────────────────────────────────────────
# All values were measured across five INTC filings.
# Evidence: F = docs/en/m1-1-parser/01-findings.md, B = docs/en/m1-1-parser/04-bugs.md

# Finding the tables. An ordinary 10-K contents table also reads `Item 1. Business … 3`
# and so looks like an index table. The thresholds are therefore generous, and the `xref`
# decision itself is gated first on "the body has no Item heading".
XREF_TABLE_MIN_ITEM_ROWS = 5  # minimum `Item N.` cells required for an index
TOC_HEADER_SCAN_ROWS = 3  # leading rows scanned for the "Page" header
TOC_TABLE_MIN_ROWS = 10  # minimum `title | page` rows required for a TOC
REF_NOTE_MIN_CHARS = 8  # shorter "(a) Incorporated by ..." text is not a note

# Body connection
TOC_TITLE_MAX_CHARS = 120  # longer blocks are paragraphs, not titles
MISSING_TITLE_MIN_CHARS = 8  # second pass: short titles match accidentally

# Page-footer map (F8)
FOOTER_MAX_STEP = 3  # page increment; rejects unordered numeric table cells
FOOTER_MIN_GAP = 5  # gap from prior footer; rejects financial-index number clusters


@dataclass
class XrefEntry:
    """Represent one Cross-Reference Index row locating one SEC Item."""

    item: str
    reported_title: str
    spans: list[tuple[int, int]] = field(default_factory=list)  # page ranges
    status: str = "parsed"  # parsed | empty_disclosure | incorporated_by_reference
    reference_source: str | None = None

    def covering(self, page: int) -> tuple[int, int] | None:
        """Return the narrowest range that covers this page."""
        hits = [(s, e) for s, e in self.spans if s <= page <= e]
        return min(hits, key=lambda t: t[1] - t[0]) if hits else None


# ------------------------------------------------------------- finding tables


def _rows(tbl: Tag) -> list[list[str]]:
    out = []
    for tr in tbl.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
        cells = [c for c in cells if c]
        if cells:
            out.append(cells)
    return out


def _spans(text: str) -> list[tuple[int, int]]:
    """ "Pages 53 - 67 , 70" → [(53,67),(70,70)].

    iXBRL rendering can insert spaces inside numbers ("1 4" = 14), so remove
    spaces before parsing them.
    """
    out: list[tuple[int, int]] = []
    for part in re.split(r"[,;]", text or ""):
        ns = [int(m.group().replace(" ", "")) for m in PAGE_NUM.finditer(part)]
        if not ns:
            continue
        if len(ns) >= 2 and "-" in part:
            lo, hi = ns[0], ns[-1]
            out.append((lo, hi) if lo <= hi else (hi, lo))  # tolerate typos such as "88 -86"
        else:
            out.extend((n, n) for n in ns)
    return out


def find_tables(soup: BeautifulSoup) -> tuple[Tag | None, Tag | None]:
    """Find the cross-reference index and company table of contents.

    ``xref`` is a table with at least five ``Item N.`` cells. ``toc`` has a
    "Page" header and at least ten ``title | page`` rows.

    A normal 10-K table of contents can also look like
    ``Item 1. Business ... 3``. Call this only after confirming that the body
    has no Item headings and the filing is therefore an ``xref`` candidate.
    """
    xref = toc = None
    for tbl in soup.find_all("table"):
        rs = _rows(tbl)
        if not rs:
            continue
        if sum(1 for r in rs if any(ITEM_CELL.match(c) for c in r)) >= XREF_TABLE_MIN_ITEM_ROWS:
            xref = tbl
        elif toc is None and any(r[-1].lower() == "page" for r in rs[:TOC_HEADER_SCAN_ROWS]):
            if (
                sum(1 for r in rs if len(r) >= 2 and r[-1].replace(" ", "").isdigit())
                >= TOC_TABLE_MIN_ROWS
            ):
                toc = tbl
    return xref, toc


# ---------------------------------------------------------- interpreting tables


def parse_xref(tbl: Tag) -> list[XrefEntry]:
    """Convert the Cross-Reference Index into Item locations and statuses.

    Indented rows can follow an Item row, such as "Results of operations" under
    Item 7. Add those pages to the parent Item. The filing states the result, so
    body-text inference is unnecessary:
      "Not applicable"                         → empty_disclosure
      "(a)" + note "Incorporated by ..."       → incorporated_by_reference
    """
    entries: list[XrefEntry] = []
    notes: dict[str, str] = {}  # (a) -> reference explanation
    cur: XrefEntry | None = None
    closed = True  # whether the current Item received a value on its own row
    for r in _rows(tbl):
        if m := ITEM_CELL.match(r[0]):
            cur = XrefEntry(
                item=(m.group(1) + (m.group(2) or "")).upper(),
                reported_title=(r[1] if len(r) > 1 else "").rstrip(":").strip(),
            )
            entries.append(cur)
            # Only the third cell is a value. A two-cell title row has no value yet;
            # treating its title as a value misreads the "10" in "Form 10-K Summary".
            tail = r[2] if len(r) > 2 else ""
            # An Item is closed when its row contains a page, Not applicable, or a note.
            # Only an Item without a value absorbs the indented rows below it. Otherwise,
            # the final "Signatures | Page 125" row attaches to Item 16 and makes a
            # Not-applicable Item appear to have body content.
            closed = bool(_spans(tail) or EMPTY_CELL.match(tail) or REF_CELL.match(tail))
        elif cur is not None and not closed and len(r) >= 2:
            tail = r[-1]
        else:
            # "(a) Incorporated by …"
            if (n := REF_NOTE.match(r[0])) and len(r[0]) > REF_NOTE_MIN_CHARS:
                notes[n.group(1).lower()] = n.group(2).strip()
            continue

        if EMPTY_CELL.match(tail):
            cur.status = "empty_disclosure"
        elif rm := REF_CELL.match(tail):
            cur.status = "incorporated_by_reference"
            cur.reference_source = rm.group(1).lower()
        cur.spans += _spans(tail)

    for e in entries:
        if e.reference_source:
            e.reference_source = notes.get(e.reference_source, e.reference_source)
        # Page ranges make the final decision. Even if one child row contains "(a)"
        # (measured in FY2019 Item 7, "Off balance sheet arrangements (a)"), the
        # Item has real body content when its other rows provide pages.
        if e.spans:
            e.status = "parsed"
        elif e.status == "parsed" or EMPTY_CELL.match(e.reported_title):
            e.status = "empty_disclosure"
    return entries


def parse_toc(tbl: Tag) -> list[tuple[str, int]]:
    """Return company TOC entries as ``(section title, start page)`` in document order."""
    out = []
    for r in _rows(tbl):
        if len(r) >= 2 and (p := r[-1].replace(" ", "")).isdigit():
            title = r[0].strip()
            if title and not title.lower().startswith("page"):
                out.append((title, int(p)))
    return out


# ------------------------------------------------------------ linking to the body


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()


def _words(s: str) -> set[str]:
    return {w.rstrip("s") for w in _norm(s).split() if w not in STOPWORDS and len(w) > 2}


def _in_tables(blocks: list[Tag], tables: list[Tag | None]) -> set[int]:
    """Return block indexes inside TOC/index tables so body search can skip them.

    Without this exclusion, title cells in the table of contents become body
    headings. In measured INTC FY2019 data, all thirty sections were incorrectly
    placed in blocks 91-196 inside the TOC table.
    """
    live = [t for t in tables if t is not None]
    if not live:
        return set()
    return {i for i, el in enumerate(blocks) if any(el is t or t in el.parents for t in live)}


def locate_sections(
    blocks: list[Tag], toc: list[tuple[str, int]], skip: set[int]
) -> list[tuple[str, int, int]]:
    """Locate the body block where each TOC title begins.

    A title also appears in the TOC and page headers. Preserve document order and
    consume each match once from left to right. Return
    ``[(title, start_page, block_index), ...]``.
    """
    texts = [_norm(b.get_text(" ", strip=True)) for b in blocks]
    wordsets = [_words(t) if len(t) < TOC_TITLE_MAX_CHARS else set() for t in texts]
    found, cursor = [], 0
    for title, page in toc:
        want = _norm(title)
        ww = _words(title)
        hit = next(
            (
                j
                for j in range(cursor, len(blocks))
                if j not in skip and texts[j] == want and len(texts[j]) < TOC_TITLE_MAX_CHARS
            ),
            None,
        )
        if hit is None and ww:
            # Fall back to word-set equality for article/case differences between
            # TOC and body titles (FY2020: "Notes to the Consolidated..." versus
            # "Notes to Consolidated...").
            hit = next(
                (j for j in range(cursor, len(blocks)) if j not in skip and wordsets[j] == ww),
                None,
            )
        if hit is None:
            continue
        found.append((title, page, hit))
        cursor = hit + 1
    return found


def assign_items(located: list[tuple[str, int, int]], entries: list[XrefEntry]) -> dict[int, str]:
    """Assign each narrative section to one SEC Item without duplicating body text.

    Among Items covering the section's **start page**, choose the narrowest
    **individual covering range**, not the smallest total span. For measured INTC
    FY2019, "Critical Accounting Estimates" on page 50 is covered by Item 1A's
    50-60 range and Item 7's 50-50 range; Item 7 correctly wins.

    Title-word overlap outranks range width. For example, FY2021 "Market for Our
    Common Stock" on page 64 overlaps Item 2's 64-64 range and Item 5's 64-65
    range. Width alone picks Properties, while the words ``market`` and ``common``
    identify Item 5. The same rule maps FY2019 "Information about Our Executive
    Officers" to Item 10 instead of Item 1.
    """
    out: dict[int, str] = {}
    for title, page, bi in located:
        if item := item_for_page(page, entries, title):
            out[bi] = item
    return out


def item_for_page(page: int, entries: list[XrefEntry], title: str = "") -> str | None:
    """Return the owning Item using title overlap, range width, then shorter number."""
    cands = []
    for e in entries:
        if e.status != "parsed":
            continue
        if span := e.covering(page):
            overlap = len(_words(title) & _words(e.reported_title)) if title else 0
            cands.append((-overlap, span[1] - span[0], len(e.item), e))
    return min(cands, key=lambda c: c[:3])[3].item if cands else None


def page_map(blocks: list[Tag]) -> list[tuple[int, int]]:
    """Build a ``(block_index, page)`` map from body page-number footer blocks.

    Title matching cannot define boundaries when a filing renders section headings
    as images. In measured INTC FY2022+ data, headings such as "Segment Trends and
    Results" and "Auditor's Reports" do not exist in body text. Page footers are
    then the only deterministic boundary signal.

    Measured noise filters accept only increments of one to three, rejecting
    unordered numeric table cells, and require five blocks since the prior footer.
    The gap prevents the FY2022 financial-index cluster "76 77 78..." at blocks
    1378-1384 from being mistaken for page footers.
    """
    marks = []
    # Initialize last_blk far enough back that the first footer passes the gap condition.
    cur, last_blk = 0, -FOOTER_MIN_GAP
    for i, b in enumerate(blocks):
        t = b.get_text(" ", strip=True)
        if not re.fullmatch(r"\d{1,3}", t):
            continue
        n = int(t)
        if cur < n <= cur + FOOTER_MAX_STEP and i - last_blk >= FOOTER_MIN_GAP:
            marks.append((i, n))
            cur, last_blk = n, i
    return marks


def find_missing(
    blocks: list[Tag], entries: list[XrefEntry], assigned: set[str], skip: set[int]
) -> list[tuple[str, int, int]]:
    """Find Items omitted from the TOC whose titles still appear in the body.

    In measured INTC FY2022 data, Item 3 Legal Proceedings is inside the financial
    statement notes and absent from the company TOC, but a "Legal Proceedings"
    heading exists at body block 2100.
    """
    texts = [_norm(b.get_text(" ", strip=True)) for b in blocks]
    out = []
    for e in entries:
        if e.item in assigned or e.status != "parsed" or not e.reported_title:
            continue
        want = _norm(e.reported_title)
        if len(want) < MISSING_TITLE_MIN_CHARS:
            continue
        hit = next(
            (j for j in range(len(blocks)) if j not in skip and texts[j] == want),
            None,
        )
        if hit is not None:
            out.append((e.reported_title, e.spans[0][0] if e.spans else 0, hit))
    return out
```

Run the checkpoint:

```bash
uv run pytest tests/ingestion/test_01_blocks.py tests/ingestion/test_02_rules.py tests/ingestion/test_03_segment.py tests/ingestion/test_04_validate.py tests/ingestion/test_05_profile.py tests/ingestion/test_06_xref.py tests/ingestion/test_07_coverage.py tests/ingestion/test_08_items.py -q
```

**Expected:** every selected offline test passes. A declared integration test may skip only when its external service is unavailable.

**Stop:** do not continue if a test fails or skips because a required symbol is missing.

**Debug:** rerun the same pytest target with `-vv --tb=long`, then fix the first failing contract before continuing.

<!-- complete-files:end -->
