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
