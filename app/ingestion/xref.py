"""Process ``xref`` 10-K filings by reading their built-in mapping tables.

**Problem.** Not every company divides its body into "Item 1." and "Item 1A."
headings. Since 2019, Intel has organized its 10-K around its own narrative
structure ("Fundamentals of Our Business", "Our Capital", and "Other Key
Information"). The body contains no Item headings: among 2,267 measured leaf
blocks in INTC FY2022, none starts with ``Item N``. The index is also absorbed as
one data-table block.

No font or style rule can find a heading that does not exist.

**Solution.** The SEC permits this organization but requires a **Form 10-K
Cross-Reference Index**. The filing therefore maps its own sections to SEC Items.
Joining that index with the company's table of contents completes the mapping
without an LLM:

    Cross-Reference Index : Item 1A → Risk Factors → Pages 53-67
    Company table of contents: Risk Factors → Page 53
    Therefore, body section "Risk Factors" = Item 1A

The table also shows when one Item spans several narrative sections. In measured
INTC FY2022 data, Item 7 covers pages 5-6, 19-44, and 47-51 across eight narrative
sections. The join therefore uses **page-range overlap**, not one-to-one anchors.
"""

from dataclasses import dataclass, field
import re
from typing import Literal

from bs4 import BeautifulSoup, Tag

ITEM_CELL = re.compile(r"^item\s+(1[0-6]|[1-9])([A-C])?\s*\.?$", re.I)
EMPTY_CELL = re.compile(r"^\s*(not applicable|none|n/?a|\[?reserved\]?)\.?\s*$", re.I)
REF_CELL = re.compile(r"^\s*\(([a-z])\)\s*$", re.I)
REF_NOTE = re.compile(r"^\(([a-z])\)\s*(.+)$", re.S)
PAGE_NUM = re.compile(r"\d[\d\s]*")
STOPWORDS = {"and", "of", "the", "for", "to", "in", "our", "about", "on", "a", "with"}
ItemStatus = Literal["parsed", "empty_disclosure", "incorporated_by_reference"]


# -- Tuning constants ---------------------------------------------------------
# All values were measured across five INTC filings.
# Evidence: F = docs/en/m1-1-parser/01-findings.md, B = docs/en/m1-1-parser/04-bugs.md

# Table discovery: a normal 10-K TOC can resemble an index with `Item 1. Business ... 3`.
# Keep thresholds conservative and classify `xref` only after proving body headings absent.
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
    status: ItemStatus = "parsed"  # parsed | empty_disclosure | incorporated_by_reference
    reference_source: str | None = None

    def covering(self, page: int) -> tuple[int, int] | None:
        """Return the narrowest xref span covering a page.

        Parameters
        ----------
        page
            Page number to match.

        Returns
        -------
        tuple[int, int] | None
            Covered page range if present, otherwise ``None``.
        """
        hits = [(s, e) for s, e in self.spans if s <= page <= e]
        return min(hits, key=lambda t: t[1] - t[0]) if hits else None


# -------------------------------------------------------------- Find tables


def _rows(tbl: Tag) -> list[list[str]]:
    """Extract row text from a table, dropping empty rows.

    Parameters
    ----------
    tbl
        BeautifulSoup table node.

    Returns
    -------
    list[list[str]]
        Normalized rows as text-only cell lists.
    """
    out = []
    for tr in tbl.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
        cells = [c for c in cells if c]
        if cells:
            out.append(cells)
    return out


def _spans(text: str) -> list[tuple[int, int]]:
    """Parse page tokens and ranges from a string.

    Parameters
    ----------
    text
        Source token that may contain values like ``53-67`` or ``70``.

    Returns
    -------
    list[tuple[int, int]]
        Parsed page spans.
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
    """Identify cross-reference-index and TOC tables from a parsed filing.

    Parameters
    ----------
    soup
        Parsed BeautifulSoup document.

    Returns
    -------
    tuple[Tag | None, Tag | None]
        (xref_table, toc_table).
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


# ----------------------------------------------------------- Interpret tables


def parse_xref(tbl: Tag | None) -> list[XrefEntry]:
    """Parse cross-reference rows into ``XrefEntry`` records.

    Parameters
    ----------
    tbl
        Candidate index table.

    Returns
    -------
    list[XrefEntry]
        Parsed item mapping and page spans.
    """
    if tbl is None:
        return []
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


def parse_toc(tbl: Tag | None) -> list[tuple[str, int]]:
    """Parse company table-of-contents rows.

    Parameters
    ----------
    tbl
        Candidate TOC table.

    Returns
    -------
    list[tuple[str, int]]
        ``(title, start_page)`` tuples in order.
    """
    if tbl is None:
        return []
    out = []
    for r in _rows(tbl):
        if len(r) >= 2 and (p := r[-1].replace(" ", "")).isdigit():
            title = r[0].strip()
            if title and not title.lower().startswith("page"):
                out.append((title, int(p)))
    return out


# -------------------------------------------------------------- Connect body


def _norm(s: str) -> str:
    """Normalize text for case-insensitive title matching.

    Parameters
    ----------
    s
        Input title text.

    Returns
    -------
    str
        Lowercased alphanumeric spaces-only string.
    """
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()


def _words(s: str) -> set[str]:
    """Tokenize a title into normalized key words.

    Parameters
    ----------
    s
        Raw text.

    Returns
    -------
    set[str]
        Normalized non-stopword tokens.
    """
    return {w.rstrip("s") for w in _norm(s).split() if w not in STOPWORDS and len(w) > 2}


def in_tables(blocks: list[Tag], tables: list[Tag | None]) -> set[int]:
    """Return indexes of blocks that belong to TOC/xref table nodes.

    Parameters
    ----------
    blocks
        Leaf blocks from the filing body.
    tables
        Candidate TOC/index tables.

    Returns
    -------
    set[int]
        Block positions to skip during narrative matching.
    """
    live = [t for t in tables if t is not None]
    if not live:
        return set()
    return {i for i, el in enumerate(blocks) if any(el is t or t in el.parents for t in live)}


def locate_sections(
    blocks: list[Tag], toc: list[tuple[str, int]], skip: set[int]
) -> list[tuple[str, int, int]]:
    """Locate narrative starts for TOC titles.

    Parameters
    ----------
    blocks
        Leaf blocks.
    toc
        Parsed table-of-contents entries.
    skip
        Block indexes to ignore while searching.

    Returns
    -------
    list[tuple[str, int, int]]
        ``(title, page, block_index)`` tuples in document order.
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
    """Assign located narrative blocks to SEC item numbers.

    Parameters
    ----------
    located
        Candidate body starts from TOC.
    entries
        Parsed xref entries.

    Returns
    -------
    dict[int, str]
        Mapping of block index to SEC Item.
    """
    out: dict[int, str] = {}
    for title, page, bi in located:
        if item := item_for_page(page, entries, title):
            out[bi] = item
    return out


def item_for_page(page: int, entries: list[XrefEntry], title: str = "") -> str | None:
    """Select best matching Item for a page and optional title.

    Parameters
    ----------
    page
        Document page number.
    entries
        Parsed xref entries.
    title
        Optional section title context.

    Returns
    -------
    str | None
        Best matching Item number, or ``None`` if no match.
    """
    cands = []
    for e in entries:
        if e.status != "parsed":
            continue
        if span := e.covering(page):
            overlap = len(_words(title) & _words(e.reported_title)) if title else 0
            cands.append((-overlap, span[1] - span[0], len(e.item), e))
    return min(cands, key=lambda c: c[:3])[3].item if cands else None


def page_map(blocks: list[Tag]) -> list[tuple[int, int]]:
    """Build a mapping of body block index to page number.

    Parameters
    ----------
    blocks
        Leaf content blocks.

    Returns
    -------
    list[tuple[int, int]]
        Footer-like ``(block_index, page)`` pairs.
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
    """Find xref entries missing from TOC but present in body text.

    Parameters
    ----------
    blocks
        Leaf blocks.
    entries
        Parsed xref entries.
    assigned
        Already assigned SEC Items.
    skip
        Block indexes to ignore.

    Returns
    -------
    list[tuple[str, int, int]]
        ``(reported_title, page, block_index)`` candidates.
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
