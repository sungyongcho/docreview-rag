# M1.1 Tutorial 5 — Cutting a filing whose body has no Item headings

Intel's 10-K contains **not one block** that starts with `Item N`. The heading walk built in the previous document finds nothing.

But in exchange for allowing a restructured body, the SEC requires a **Cross-Reference Index**: a table stating which page holds which Item. The filing carries the answer itself, and this document builds the separate module that reads it, `app/ingestion/xref.py`.

This is the longest of the eight documents. Work through it section by section rather than in one sitting.

**Prerequisite:** The heading walk through tutorial 4 works. This document starts not in `parser.py` but in a new file, `app/ingestion/xref.py`.

## What to write and where to implement it yourself

| Stretch | Learning action | What to take away |
|---|---|---|
| `XrefEntry` and constants | **Write the model declarations** | the minimum values a page join needs |
| `find_tables`, `parse_xref` | **Implement** table recognition | what separates a Cross-Reference Index from other tables |
| `parse_toc`, `_in_tables` | **Write the structure** | keeping the TOC and the xref table from mixing |
| `locate_sections`, `assign_items` | **Implement** the page join | how a page number becomes a character coordinate |
| `page_map`, `find_missing` | **Review the boundary conversion** | recording an Item that has no body text |

---

## L8 — Segmentation B — reading the answer the document carries

This is where the Intel problem is solved. As shown earlier, Intel restructured its 10-K in 2019 under proprietary narrative headings, and the body contains **no Item headings at all**. L7's heading walk returns zero here no matter how refined the rules are. You cannot find what is not there.

### The escape hatch regulation created

The SEC permits this restructuring — on a condition. The filing must carry a **Form 10-K Cross-Reference Index**, a table stating which pages hold which Item.

In other words, the document carries its own answer. Overlay the company's own table of contents and the mapping completes.

```
Cross-Reference Index : Item 1A → Risk Factors → Pages 53-67
Company TOC           : Risk Factors → Page 53
⇒ body "Risk Factors" section = Item 1A
```

No LLM, no heuristics. Two joins over facts stated in the document. When working with regulated documents, it pays to look first for **the structure the regulation itself created**.

### Why a 1:1 match does not work

It would be simpler to solve this as "one title = one Item," but that fails: a single Item is scattered across several narrative sections. Measured on INTC FY2022, Item 7 spans Pages 5-6, 19-44, and 47-51 — eight narrative sections in all.

So it is solved by **page-range overlap** rather than 1:1 anchoring. The question becomes "which Item covers the page this section starts on?"

### The algorithm in eight stages

```
1. Find two tables       index (5+ `Item N.` rows) + company TOC (10+ title|page rows)
2. Parse the index       Item → (title, page ranges, status)
3. Parse the TOC         narrative title → start page
4. Locate the body       which block does each narrative title start at
5. Assign Items          by page-range overlap
6. Second-pass search    Items absent from the TOC but paged in the index
7. Correct boundaries    ranges whose heading is an image (F8)
8. Merge per Item        narrative sections assigned to one Item become one Section
```

Compared with L7's single loop this is involved, which is why it lives in a separate module, `xref.py`. It shares only the block list with the heading walk and uses a fundamentally different algorithm. The file does not import parser dataclasses, which also prevents a circular import.

Begin with the module rationale and imports.

#### Create `app/ingestion/xref.py` — module foundation

```python
"""`xref` 타입 10-K 처리 — 문서가 스스로 들고 있는 매핑표를 읽는다.

**문제.** 모든 기업이 본문을 "Item 1.", "Item 1A." 로 나누지는 않는다. Intel은 2019년부터
자사 서사 구조("Fundamentals of Our Business" / "Our Capital" / "Other Key Information" …)로
10-K를 재구성했다. 본문에 Item 헤딩이 **하나도 없다** (실측: INTC FY2022 리프 블록
2,267개 중 `Item N` 으로 시작하는 블록 0개 — 색인표는 데이터 표로 통째로 흡수된다).

폰트·스타일 규칙을 아무리 정교하게 만들어도 없는 것을 찾을 수는 없다.

**해법.** SEC는 이런 재구성을 허용하되 **Form 10-K Cross-Reference Index** 를 의무화한다.
즉 문서가 "내 어느 부분이 어느 Item인가"를 스스로 표로 들고 있다. 여기에 기업 자체 목차를
합치면 LLM 없이 매핑이 완성된다:

    Cross-Reference Index : Item 1A → Risk Factors → Pages 53-67
    기업 목차             : Risk Factors → Page 53
    ⇒ 본문 "Risk Factors" 섹션 = Item 1A

Item 하나가 여러 서사 섹션에 걸치는 것도 표가 알려준다 (실측 INTC FY2022:
Item 7 = Pages 5-6, 19-44, 47-51 → 서사 섹션 8개). 그래서 앵커 1:1이 아니라
**페이지 구간 겹침**으로 푼다.
"""

from dataclasses import dataclass, field
import re

from bs4 import BeautifulSoup, Tag
```

The evidence is in [F5](../01-findings.md#f5) and [F6](../01-findings.md#f6).

> As an aside, this docstring was corrected once. It originally read "one of 2,416 blocks"; re-measured under current blockification it is **zero of 2,267 blocks**, because the index table is now absorbed as a data table and its cells are no longer leaves. The conclusion got stronger, so the figure was updated. **Numbers in documentation have to be re-measured when the code changes.**

### Build

### 8.0 Data structures and constants

#### Target file: `app/ingestion/xref.py`

<!-- src: app/ingestion/xref.py::ITEM_CELL,EMPTY_CELL,REF_CELL,REF_NOTE,PAGE_NUM,STOPWORDS -->
```python
ITEM_CELL = re.compile(r"^item\s+(1[0-6]|[1-9])([A-C])?\s*\.?$", re.I)
EMPTY_CELL = re.compile(r"^\s*(not applicable|none|n/?a|\[?reserved\]?)\.?\s*$", re.I)
REF_CELL = re.compile(r"^\s*\(([a-z])\)\s*$", re.I)
REF_NOTE = re.compile(r"^\(([a-z])\)\s*(.+)$", re.S)
PAGE_NUM = re.compile(r"\d[\d\s]*")
STOPWORDS = {"and", "of", "the", "for", "to", "in", "our", "about", "on", "a", "with"}
```

After the regular-expression constants, define the xref thresholds measured across the five Intel filings.

<!-- src: app/ingestion/xref.py::XREF_TABLE_MIN_ITEM_ROWS,FOOTER_MIN_GAP -->
```python
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
```

**What to look for in the code**

- All nine constants are measured from the corpus. The comment beside each value is its evidence, and changing one means measuring again.
- `FOOTER_MAX_STEP` and `FOOTER_MIN_GAP` are a pair. The first enforces that page numbers advance by one to three; the second that at least five blocks separate consecutive footers. Either alone fails to filter out the financial index's cluster of numbers.
- `TOC_TITLE_MAX_CHARS` caps title length because a longer block is a paragraph, not a title. Without the cap, body paragraphs become title candidates.


#### Target file: `app/ingestion/xref.py`

<!-- src: app/ingestion/xref.py::XrefEntry -->
```python
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
```

`covering()` would work as a free function. But it is **a question asked about these ranges**, so it belongs with the data.

The payoff shows up in stage five. `entry.covering(page)` reads as "does this Item own that page?", and the whole assignment rule gets shorter. When choosing which methods to attach to a data structure, "is this a question about that data?" is usually the right test.

### 8.1 Find tables

#### Target file: `app/ingestion/xref.py`

<!-- src: app/ingestion/xref.py::_rows -->
```python
def _rows(tbl: Tag) -> list[list[str]]:
    out = []
    for tr in tbl.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
        cells = [c for c in cells if c]
        if cells:
            out.append(cells)
    return out
```

**What to look for in the code**

- Empty cells go first, then empty rows. SEC tables are full of alignment spacers, and without this cleanup every judgment below is swayed by blank counts.
- `td` and `th` are collected together. SEC tables often mark header cells as `td`, so distinguishing them would misalign row lengths.
- The return shape is a two-dimensional list of strings. From here on `find_tables`, `parse_xref`, and `parse_toc` all see exactly one shape.

<!-- src: app/ingestion/xref.py::_spans -->
```python
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
```

This short function absorbs two kinds of real-world mess.

First, **iXBRL inserts spaces inside numbers.** "Pages 1 4, 67" is not 1, 4 and 67 — it is 14 and 67. The spacing comes from rendering, and the source really does read that way.

Second, **the source contains typos.** Ranges like "88 -86", where the start exceeds the end, genuinely occur. People wrote these documents.

Neither raises; both are handled quietly on the normal path ([B15](../04-bugs.md#b15)). **A parser over real data lives in the wide grey zone between "ideal input" and "error", and absorbing that grey zone into the normal path is most of the work.**

<!-- src: app/ingestion/xref.py::find_tables -->
```python
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
```

**What to look for in the code**

- Both tables are found in one pass. The index is identified by its count of `Item N.` cells, the TOC by a "Page" header plus a count of `title | page` rows.
- The `elif` matters. A table already judged to be the index is excluded from TOC candidacy; one table cannot be both.
- The `toc is None` condition keeps only the first TOC, preventing a later financial-statement index from overwriting it.
- The docstring pins the call order: only after confirming the body has no Item headings — because an ordinary 10-K's TOC also looks like `Item 1. Business ... 3`.

### 8.2 Interpret tables — encode three traps in code

#### Target file: `app/ingestion/xref.py`

<!-- src: app/ingestion/xref.py::parse_xref -->
```python
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
```

This function is short, but three traps hit in real documents are frozen into it. One at a time.

### Trap 1 — without `closed`, Signatures becomes Item 16

An index table may follow an Item row with indented child rows, such as "Results of operations | 25" under Item 7. Those pages should merge into the parent Item 7.

The problem is knowing when to stop consuming child rows. The end of the table usually carries a "Signatures | Page 125" row; keep consuming and it attaches to the preceding Item, typically Item 16. Item 16 then appears to have body content even though it reads "Not applicable" ([B01](../04-bugs.md#b01)).

The `closed` variable makes that boundary explicit. If the Item row already carried a value (pages, Not applicable, or a reference marker) it is considered closed and absorbs nothing. Only an Item without a value takes in the rows below it.

**In a parser, "what context am I in right now" is almost always better as an explicit variable.** Left implicit, boundary bugs like this arrive silently.

### Trap 2 — the title of a two-cell row is not a value

That is the `tail = r[2] if len(r) > 2 else ""` line. Values live **only in the third cell**.

A two-cell row has a title and no value yet. Read the second cell as a value and the `PAGE_NUM` regex **extracts "10" from the title "Form 10-K Summary"** — recording Item 16 as living on page 10.

### Trap 3 — when signals conflict, name the final authority

Under FY2019's Item 7 there is a child row "Off balance sheet arrangements (a)". The `(a)` marks "incorporated by reference." Propagate it and Item 7 as a whole becomes `incorporated_by_reference` and **disappears entirely despite having body content** ([B03](../04-bugs.md#b03)). Item 7 is MD&A, one of the most important sections in a 10-K.

The final loop's `if e.spans: e.status = "parsed"` is the resolution. **If any pages exist, the body exists.** The presence of page ranges is stronger evidence than one child row's reference marker.

Code where several signals can conflict needs exactly this kind of step that **names who has final authority**. Without it, the result depends on input order.

#### Target file: `app/ingestion/xref.py`

<!-- src: app/ingestion/xref.py::parse_toc -->
```python
def parse_toc(tbl: Tag) -> list[tuple[str, int]]:
    """Return company TOC entries as ``(section title, start page)`` in document order."""
    out = []
    for r in _rows(tbl):
        if len(r) >= 2 and (p := r[-1].replace(" ", "")).isdigit():
            title = r[0].strip()
            if title and not title.lower().startswith("page"):
                out.append((title, int(p)))
    return out
```

**What to look for in the code**

- Only rows whose last cell is numeric are kept; a row without a page number is not a TOC entry.
- `replace(" ", "")` is there because SEC tables contain numbers with spaces inside them. Without that one cleanup, perfectly good entries are discarded wholesale.
- Titles beginning with "page" are dropped — the guard that stops a header row from entering as an entry.

### 8.3 Connect the body

#### Target file: `app/ingestion/xref.py`

<!-- src: app/ingestion/xref.py::_norm -->
```python
def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()
```

**What to look for in the code**

- Lowercase, then keep only alphanumerics and spaces. TOC titles and body titles routinely differ by nothing more than punctuation and case, and that difference is absorbed here.
- It is one line, yet `locate_sections` and `find_missing` both compare strings that passed through it. Keeping normalization in one place is what stops the two comparisons from drifting apart.

<!-- src: app/ingestion/xref.py::_words -->
```python
def _words(s: str) -> set[str]:
    return {w.rstrip("s") for w in _norm(s).split() if w not in STOPWORDS and len(w) > 2}
```

**What to look for in the code**

- Stopwords go, words of three characters or fewer go, a trailing plural `s` is stripped, and the rest becomes a set. The point is to treat titles as equal despite differing word order and articles.
- Being a set, it loses order. That is deliberate — it makes "Notes to the Consolidated..." and "Notes to Consolidated..." the same thing.
- `item_for_page`'s title-overlap score uses the same sets. One normalization rule governs both judgments at once.

<!-- src: app/ingestion/xref.py::_in_tables -->
```python
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
```

`_in_tables` looks trivial and everything collapses without it.

You are about to search for "which body block does this narrative title start at" — and that title also appears inside the TOC table. Searching from the top of the document **always finds the TOC first**.

Running INTC FY2019 without it produced [B10](../04-bugs.md#b10). All 30 sections were placed inside the TOC table (blocks 91–196), each with two blocks. Yet the surface metrics looked fine — Item count correct, order correct, no duplicates. **This is exactly the "structurally perfect failure" named in L1**, and it is what L12's validation exists to catch.

<!-- src: app/ingestion/xref.py::locate_sections -->
```python
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
```

**What to look for in the code**

- `cursor` is the heart of the function. Matches are consumed left to right, once each, which preserves document order. Without it, the header repeated on every page all matches the same title.
- Exact equality is tried first, and the word-set comparison runs only when it fails. Reverse the order and the looser comparison steals candidates the exact one would have matched.
- The `skip` set excludes the index table's and the TOC's own blocks. Without it, a title inside the TOC is taken as the start of the body.
- `wordsets` is built outside the loop. Computing it inside would run normalization once per title per block.

### The cursor never goes backwards

Excluding the TOC table with `skip` is not enough. The same title also appears in page headers and in mid-body mentions.

The fix is a **monotonically advancing cursor**. Using the fact that TOC order matches body order, each match moves the cursor past it and the next title is searched only after the cursor.

Positions already consumed are never revisited, so there are no duplicate matches, and as a bonus the whole search escapes O(n²). **This is a case of putting a document-order constraint to algorithmic use** — the reason L3 stressed that `find_all` guarantees document order.

### The fallback opens exactly one step

If exact matching fails, word-set matching is tried once. The TOC says "Notes to **the** Consolidated…" while the body says "Notes to Consolidated…" in FY2020, so the article difference is real.

What matters is that **it stops there.** Keep loosening with substring matching, edit distance, similarity thresholds, and eventually you have code that matches but nobody can say why. A fallback opens only far enough to absorb a difference that was actually observed.

### 8.4 Assign Items

#### Target file: `app/ingestion/xref.py`

<!-- src: app/ingestion/xref.py::assign_items -->
```python
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
```

**What to look for in the code**

- The priority order is stated in the docstring and the code follows it exactly: title-word overlap, then range width, then Item-number length.
- The width compared is the **individual covering range**, not a total span. When Item 1A's 50-60 and Item 7's 50-50 both cover a page, the narrower Item 7 wins.
- The example explains why overlap outranks width. On page 64 width alone picks Properties, but the words `market` and `common` point at Item 5.

<!-- src: app/ingestion/xref.py::item_for_page -->
```python
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
```

**What to look for in the code**

- The sort key is the tuple `(-overlap, width, number length)`, which settles three criteria in a single `min`.
- Negating `overlap` is what lets `min` pick the maximum — the idiom that avoids writing a separate comparator.
- Filtering `e.status != "parsed"` first stops an Item that ended as an empty disclosure or a reference from claiming body text.
- The third key breaks ties deterministically: all else equal, `1` is shorter than `1A` and wins.

### When several Items claim the same page

Assignment is not simple, because index page ranges can overlap.

INTC FY2019's "Critical Accounting Estimates" starts on page 50, and Item 1A claims 50-60 while Item 7 claims 50-50. Here the **narrower range** is the more specific claim, so Item 7 is right.

But range width alone is not enough. FY2021's "Market for Our Common Stock" is on page 64, where Item 2 (Properties) claims 64-64 and Item 5 (Market for Registrant's Common Equity) claims 64-65. On width, Item 2 wins. But the title words `market` and `common` point at Item 5.

So the priority is threefold: **most title-word overlap → narrowest range → shortest Item number.** All three cases are recorded with measurements in [B08](../04-bugs.md#b08).

### Multi-criteria sorting is written as tuples

Expressing that priority as an `if/elif` chain tangles quickly. Instead a tuple is built and handed to `min()`.

```python
cands.append((-overlap, span[1] - span[0], len(e.item), e))
```

Python compares tuples lexicographically from the left, so element order *is* priority order. Values needing descending order get their sign flipped (`-overlap`).

Storing the object itself as the last element while excluding it from comparison with `key=lambda c: c[:3]` is the other trick. It keeps "the sort keys" and "the value to pull out" in one tuple while preventing an incomparable object from entering the comparison — `XrefEntry` does not support `<`, so passing it without the slice raises `TypeError`.

### 8.5 Correct boundaries and run a second search

By this point most sections are assigned. Two gaps remain in the real Intel documents.

**Gap 1 — the heading is an image.** From INTC FY2022 onward, section titles such as "Segment Trends and Results" and "Auditor's Reports" are **rendered as images and do not exist in the body text at all.** Title matching cannot find those boundaries.

The only deterministic signal left is the **page-number footer**. A block containing just "71" between body blocks marks a page boundary, and `page_map()` builds that map.

The catch is that number-only blocks are not always page footers. Clusters like "76 77 78…" in the financial-statement index also qualify (FY2022, blocks 1378–1384). So two filters apply — **increments of 1 to 3 only** (rejecting unordered table cells) and **at least five blocks since the previous footer** (rejecting number clusters).

**Gap 2 — some Items are missing from the TOC.** INTC FY2022's Item 3 (Legal Proceedings) sits inside the financial-statement notes and is absent from the company TOC. But the index table lists pages for it, and a "Legal Proceedings" heading really does exist at body block 2100.

`find_missing()` makes that second pass, searching the body directly for the titles of Items that the index lists but that remain unassigned. It also applies a `MISSING_TITLE_MIN_CHARS`(eight chars) floor to prevent accidental matches on short titles — the same defense as L7's `match_canonical`.

#### Target file: `app/ingestion/xref.py`

<!-- src: app/ingestion/xref.py::page_map -->
```python
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
```

**What to look for in the code**

- This is the last resort for filings where title matching cannot work. From INTC FY2022 on, section headings are images and do not exist in body text at all.
- There are two conditions: the increment must be one to three, and at least five blocks must separate this footer from the previous one. The first filters out unordered numeric cells, the second the financial index's run of consecutive numbers.
- `last_blk` starts negative — the initialization that keeps the document's first footer from failing the gap condition.
- Because it is `fullmatch`, only blocks that are nothing but digits qualify. A form like "Page 12" is rejected right here.

<!-- src: app/ingestion/xref.py::find_missing -->
```python
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

**What to look for in the code**

- This is the second pass, for Items the TOC omits. INTC FY2022's Item 3 sits inside the financial statement notes and never appears in the company TOC.
- `MISSING_TITLE_MIN_CHARS` rules out short titles. A two- or three-character title matches by accident easily, and without this filter an unrelated block gets assigned to an Item.
- This pass scans the whole document with no `cursor`. These entries were missed on the first pass, so preserving order buys nothing.
- Items already assigned and blocks in `skip` are passed over — the guard that stops one stretch of body text from being assigned to two Items.

### 8.6 Assemble

#### Target file: `app/ingestion/parser.py`

<!-- src: app/ingestion/parser.py::segment_by_xref -->
```python
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
```

Two last points about this assembly function.

### Detached blocks get an owner rather than the bin

Cutting boundaries at page footers because of image headings leaves ranges of blocks belonging to no section. Discard them and coverage drops while real content disappears.

Instead they are **assigned to the Item that owns that page.** FY2022's pages 72–80 went to Item 8 this way ([B06](../04-bugs.md#b06)). `item_for_page()` already exists, so it is reused.

Very short fragments are still dropped (`ORPHAN_MIN_BLOCKS`, three blocks), on the grounds that they are more likely trimmings than meaningful body text.

### Fixing a bug means checking the opposite direction

The `next_page > hi + 1` condition stands out. It comes from [B07](../04-bugs.md#b07).

Applying boundary correction unconditionally created the opposite problem: sections that naturally spill onto the next page were cut too, attaching Item 7A's final paragraph to the start of Item 1A. If the next heading begins on the **very next page**, that is not an orphan range — it is normal spillover.

**Get in the habit of checking the opposite direction after a fix.** "Fixed" usually means "fixed this direction of failure," not "correct in every direction.

### Verify

After writing the final `xref.py` function, add this import below the BeautifulSoup import near the top of `app/ingestion/parser.py`. The two modules are now connected in the canonical direction.

#### Update `app/ingestion/parser.py` — connect xref

```python
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
```

First confirm that both tables are found:

```bash
uv run pytest tests/ingestion/test_06_xref.py -k "tables_are_found or row_counts" -v
```

```
INTC-FY2019  색인표 21  목차 30
INTC-FY2022  색인표 22  목차 25
```

Then run the complete check:

```bash
uv run pytest tests/ingestion/test_06_xref.py -v
```

**Required checks**

| Check | Why |
|---|---|
| Item Seven has 69k~77k characters from FY2020 through FY2023 | Several narrative sections were joined ([F7](../01-findings.md#f7)); a value near 10k means the join failed |
| Item Eight contains 52 to sixty-five tables in FY2020~23 | Confirms correct financial-statement ownership; a low count suggests an image-heading clamp problem |
| Item Three exists | It is absent from the table of contents and hidden in a note, so only the second search finds it |
| Part III (10~14) is marked as referenced | The index communicates this through footnotes `(a)`~`(e)` |

> ⚠ **FY2019 is an exception for both metrics.** Item Seven has 33k characters because the index assigns "Our Products" to Item One that year, and Item 8 has seven tables because the legacy file contains only eighteen table blocks in total. **This is not a bug**; `tests/ingestion/golden.py` stores `XREF_ITEM_SHAPE`, which freezes each year separately.

**Pitfalls encountered** — [B01](../04-bugs.md#b01) · [B02](../04-bugs.md#b02) · [B03](../04-bugs.md#b03) · [B06](../04-bugs.md#b06) · [B07](../04-bugs.md#b07) · [B08](../04-bugs.md#b08) · [B10](../04-bugs.md#b10) · [B15](../04-bugs.md#b15)

### Where you are now

Both segmentation strategies are complete. `segment_by_heading` handles the 15 filings with explicit Item headings; `segment_by_xref` handles the 5 Intel filings by joining the Cross-Reference Index with the company TOC on page ranges. The algorithms are entirely different, and **both produce the same `list[Section]`** — same shape, same coordinates, same block attribution.

That matters. The layers below (L10 onward) and every later module never need to know which strategy ran.

One question is still unanswered. **"Which strategy should this file use?"** That is L9.

## What you should be able to explain now

- **Where does the answer come from when the body carries no Item headings?**
  - **Answer:** The SEC-required Cross-Reference Index states which pages belong to each Item, and the company TOC states where narrative sections begin. Joining those two document-provided facts by page range replaces a heading walk.
- **What signal separates a Cross-Reference Index from any other table?**
  - **Answer:** It contains a measured minimum number of rows whose cells begin with `Item N`, while the TOC is identified separately by its Page header and title-page rows. The `elif` also prevents one table from being accepted as both.
- **What results when the TOC and the xref table get mixed together?**
  - **Answer:** Title matching finds the copies inside the TOC instead of the body, so all sections collapse into tiny ranges inside that table. Item count and order can still look perfect, creating a structurally convincing but content-empty parse.
- **How does a page number become a character coordinate?**
  - **Answer:** The xref page range is joined to a TOC title, that title is located at a body block, and the block index is mapped through `source_pos` and `block_source_spans`. The result is an absolute offset in the original HTML.
- **Why record an Item that has no body text instead of dropping it?**
  - **Answer:** The index may explicitly say that an Item is not applicable or incorporated by reference. Keeping that Item and status preserves the document's statement, makes index coverage checkable, and distinguishes legitimate absence from parser loss.

---

[← Previous: Heading segmentation](04-segment-heading.md) · [Module overview](../03-build.md) · [Next: Detection and classification →](06-detect-classify.md)
