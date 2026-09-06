# M1.1 Tutorial 4 — Finally cutting the document

The previous five layers were preparation. Now the document actually gets cut into Items.

Fifteen of the twenty corpus files take this path — the ones whose body really does contain headings like `Item 1A.`. The other five are handled in the next document.

**Prerequisite:** Tutorial 3's `uv run pytest tests/ingestion/test_02_rules.py -v` passes in full.

## What to write and where to implement it yourself

| Stretch | Learning action | What to take away |
|---|---|---|
| L7 `_norm_title`, `match_canonical` | **Write the structure** | collapsing unstable spellings onto one Item |
| L7 `find_item` | **Implement** candidate selection | why only one of many `Item 1A` strings is the heading |
| L7 `segment_by_heading` | **Implement** the walk | the boundary that drops the cover page and TOC |

---

## L7 — Segmentation A — finally cutting the document

This layer uses everything built so far. Walk the block list (L3) top to bottom, find headings with the rule evaluator (L5), and open a new section at each heading. Non-heading blocks accumulate into the currently open section.

The `number`, `sec_canonical`, and `custom_title` types share **the same loop**. Only the reference consulted to decide "which Item is this?" differs.

- `number` — extract the number with the `ITEM_RE` regex
- `sec_canonical` — compare against the SEC canonical title table
- `custom_title` — compare against a mapping table stored in the profile

### The order of two questions decides performance

Heading detection splits into two questions.

① Which Item does this text **name**? (identification) ② Does this block **look like** a heading? (presentation)

The code does ① first, following the principle that cheap checks come first. A text regex and a dict lookup finish instantly, while ②'s `block_props()` scans a CSS string through several regular expressions.

The effect is large. Of 2,400 blocks, only about twenty are Item headings. The other 2,380 fail at ① and never reach the expensive ②.

### Why `match`/`case`

Instead of an `if/elif` chain, the three-type branch uses `match`/`case`. The structure makes visible that branching depends on the `type` value alone, and `case _` catches unhandled values. The syntax requires Python 3.10 or newer.

### Build — Segmentation A — splitting the document by headings

First, the matching function used by `sec_canonical`. **Its two guards are essential.**

#### Target file: `app/ingestion/parser.py`

<!-- src: app/ingestion/parser.py::_norm_title,match_canonical -->
```python
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
```

This function permits prefix matching. A document may write just "Risk Factors" or "Risk Factors Related to Our Business." But opening it up loosely causes accidents.

Remove the guards and measurement produces this ([B11](../04-bugs.md#b11)).

```
"FORM 10-K"  →  Item 16 (Form 10-K Summary)
"Exhibit"    →  Item 15 (Exhibits and ...)
"Reserved"   →  Item 6  (Reserved)
```

The cover page's "FORM 10-K" becomes an Item 16 heading. Short strings collide by chance.

Two dimensions guard against it. **A candidate-length floor, `CANON_MIN_CHARS`(eight chars)**, drops candidates that are too short outright, and a **prefix length, `CANON_PREFIX_CHARS`(fourteen chars)**, restricts who is even eligible for prefix matching. Whenever you introduce loose matching, design its floors alongside it.

<!-- src: app/ingestion/parser.py::find_item -->
```python
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
```

It stands out that only the `custom_title` branch uses exact equality (`==`), while `sec_canonical` just above permits prefix matching. Why the difference?

The difference is **whether the answer is known.** For `sec_canonical`, the SEC's canonical title and the filing's reported title may differ, so looseness is required. For `custom_title`, the titles that company uses were written into the profile by hand. When the answer is already known there is no reason to look loosely.

Loosening it really does break. With partial matching, "Risk Factors" also matches a subheading such as "Risk Factors Summary," and the same Item is created twice ([B14](../04-bugs.md#b14)).

### Non-heading blocks are classified too

Blocks not judged headings accumulate into the current section — but not indiscriminately. They are stored in three kinds.

#### Target file: `app/ingestion/parser.py`

<!-- src: app/ingestion/parser.py::_body_block -->
```python
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
```

Two threads to the next modules start here.

**Table blocks** keep their text empty and store the source HTML whole in the `html` field, because flattening a table to text destroys its row and column relationships. **M1.2 takes that HTML and converts it to a markdown table.**

**Level-2 headings** — subheadings such as "Gross Margin" — do not open a new section and **remain as blocks**. That pays off later: **M1.3 attaches such a subheading to a chunk as its context header** during chunking. Knowing that a paragraph came from the Gross Margin part of Item 7 markedly improves retrieval.

Now the main loop.

<!-- src: app/ingestion/parser.py::segment_by_heading -->
```python
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
```

This short loop carries two decisions that are easy to miss.

### Where do blocks before the first heading go?

Blocks in the interval where `current` is still `None` — cover page, table of contents, front matter — are **discarded.** Because the branch is `elif current is not None`, they land nowhere when `current` is absent.

That is intentional. Those blocks belong to no Item, so there is nowhere to put them. Later, measuring coverage as "section totals over whole document" will not reach 100%, and most of that gap originates here.

What matters is that **the code states the discard.** Written as `if item: ... else: store`, the cover page would have been swept into the first section, and someone would later chase "why does Item 1 contain cover-page text?" The current form instead answers "why is the cover missing?" immediately.

### Boundaries close twice

`block_range` is filled in two places. On meeting the next heading, the previous section is closed (`current.block_range = (..., i)`), and after the loop the final section is closed once more.

Handling it only inside the loop would **leave the final section's boundary unset forever**, because no next heading arrives to close it. This is a common mistake in loops carrying accumulated state; the pattern "handle the last one after the loop" is worth remembering.

### Verify

The full test module requires L13's `parse_filing` through its `parsed` fixture, so do not run it yet. Call the completed heading walk directly instead.

```bash
PARSER_MODULE=app.ingestion.parser uv run python -c "
from app.ingestion.parser import normalize, leaf_blocks, segment_by_heading
from pathlib import Path
soup = normalize(Path('data/corpus/NVDA/2024-02-21_0001045810-24-000029.html').read_text())
seg = {'type': 'number', 'rules': [{'font_weight': 700, 'font_size': 10.0, 'in_table': False}]}
secs = segment_by_heading(leaf_blocks(soup), seg)
print(len(secs), [s.item for s in secs])
for s in secs[:3]:
    print(f'  {s.item:4} blk{s.block_index} {sum(len(b.text) for b in s.blocks):>7,}자  {s.reported_title[:40]}')
"
```

**Expected values** — twenty-three Items, SEC canonical order (`['1','1A','1B','1C','2',…]`), and about 51k characters in the first Item. A count of 40+ means cross-references were also captured; zero means the rule did not match.

**Required checks**

| Check | Why |
|---|---|
| **Zero duplicate Items** | Any duplicate means the rule is too loose |
| **All five INTC files fail `detect_number`** | Success would mean table-of-contents entries were mistaken for headings |
| Items increase from 20→23 by year | Expected: Item 1C was added in FY2023 and 9C in FY2021 |
| **Item 15 has 82k characters and thirty-four tables** | NVDA places its financial statements under this section, so it should be large |

**If it is wrong** — 40+ Items means cross-references were captured; check `ITEM_RE` and its `^` anchor. A count of zero suggests that the asymmetric `in_table` behavior was reversed.

**Pitfalls encountered** — [B11](../04-bugs.md#b11), short-title false positives; and [B14](../04-bugs.md#b14), duplicates from partial matching

## What you should be able to explain now

- **What separates the one real heading from every other `Item 1A` string in the file?**
  - **Answer:** `find_item` first requires text that names an Item at the block start, then applies the learned presentation rule. The start anchor and table-location rule reject mid-sentence cross-references and TOC entries.
- **How are unstable Item titles collapsed onto a canonical name?**
  - **Answer:** `_norm_title` normalizes the reported text and `match_canonical` compares it with the SEC title table using guarded prefix matching. Company-specific titles already stored in a profile use exact mapping instead.
- **At what stage is the decision made to discard the cover page and the TOC?**
  - **Answer:** It happens inside `segment_by_heading`: while no Item heading has opened `current`, non-heading blocks are appended nowhere. Everything before the first real Item is therefore intentionally discarded.
- **Why does this path handle only fifteen of the twenty corpus files?**
  - **Answer:** Those fifteen filings contain explicit Item headings that the walk can detect. The five Intel filings use narrative headings and must instead be segmented through their Cross-Reference Index and TOC.
- **Where do the boundaries found by the walk turn back into source coordinates?**
  - **Answer:** `segment_by_heading` precomputes `block_source_spans`, stores `source_pos` on each Item heading, and passes each body's span into `_body_block`. That is where block indices become absolute source offsets.

---

[← Previous: Rule evaluator](03-rules.md) · [Module overview](../03-build.md) · [Next: Xref segmentation →](05-segment-xref.md)
