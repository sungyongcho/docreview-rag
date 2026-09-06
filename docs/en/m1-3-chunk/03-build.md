# M1.3 Build — Chunks Whose Citations Are Not Lies

## What has been collected so far

M1.1 pulled 51,879 Blocks out of twenty filings, and M1.2 converted the tables among them to markdown. Now they have to become retrieval units.

Blocks cannot be used as they are. Measure the real sizes and you get this.

```
shortest paragraph   57 chars     ← a sentence fragment; embedding it captures no meaning
longest paragraph   3,773 chars   ← a wall of text; one hit drags in unrelated content
```

Neither works for retrieval. They have to be grouped or divided into reasonable sizes.

## What the tutorials teach is wrong here

The standard RAG answer is **fixed-length splitting**: cut text every 500 characters with 50 characters of overlap. Every library ships it. For most use cases it works well.

**For cited evidence, it is wrong.**

Here is concretely why. Cut at 500 characters and nobody knows where that point lands. It may be mid-sentence, between rows 3 and 4 of a table, or between Item 7's last paragraph and Item 8's first.

When such a chunk is retrieved, the system says this.

> "NVIDIA recorded a gross margin of 72.7%. (source: Item 7, chars 14823-15323)"

Open that range in the source and it starts mid-sentence and ends mid-table. From that span alone there is no telling which line item the number 72.7 belongs to. **The citation formally exists and is substantively false.**

M1.1 went as far as switching to a slower parser to protect those coordinates. Cut arbitrarily here and all of that effort becomes meaningless.

## The chunking strategy landscape

If RAG is new to you, "chunking" can sound like one settled technique. It is really a small set of choices that give up different things, and picking among them is what this module is about.

| Strategy | Cut on | What it gains | What it gives up |
|---|---|---|---|
| Fixed length | every N characters | simplest to implement, uniform sizes | cuts sentence, table, and section boundaries anywhere |
| Recursive splitting | try paragraph, then sentence, then word | mid-sentence cuts drop sharply | still knows nothing of document-specific structure (Items, tables) |
| Semantic | where embedding similarity between adjacent sentences drops | breaks where the topic changes | costs embedding calls, and boundaries can shift between runs |
| Structure-aware | the document's own structural markers | boundaries match the source structure, so citations verify | needs code that knows the structure of each document type |

The first three work on any document type, which is why libraries ship them as defaults. **This module picks the fourth.** A 10-K has a structure fixed by regulation, and M1.1 already extracted that structure together with its coordinates — meaning the cost of the fourth option, code that knows the structure, was already paid in the previous two modules.

Worth adding: the four are not exclusive. In practice it is common to cut large units structurally and then apply recursive splitting inside them. Why that is not done here follows from the boundary rules below.

## So the boundaries come first

The problem this module solves: **build chunks large enough to embed and small enough to retrieve, without ever crossing a boundary that would make a citation false.**

There are four such boundaries.

| Boundary | What crossing it causes |
|---|---|
| **Item boundary** | Item 8 text mixed into an Item 7 chunk, citing the wrong section |
| **Table boundary** | splitting a table leaves no row-level coordinates, so there is no span to cite |
| **Narrative heading boundary** | the "Gross Margin" and "Operating Expenses" passages in one chunk |
| **Source group boundary** | xref Items are scattered across several ranges (M1.1 L8) |

And one rule. **Paragraphs are never split.** A long paragraph over the target size simply becomes a large chunk instead of being divided.

The reason is in M1.1. A Block is the **smallest unit** whose source coordinates can be verified. There are no coordinates inside a paragraph, so the moment you split one, that fragment's citation becomes unverifiable. Verifiability was chosen over size optimization.

## Starting conditions

The M1.1 and M1.2 focused suites must pass against the 20-file corpus. Start from an empty `app/ingestion/chunk.py`, verify the input contract in L1, and stack layers in the same file.

One prohibition applies. **Do not reopen or reinterpret HTML here.** M1.3 only consumes the coordinates M1.1 produced and the markdown M1.2 produced. Parse again here and two layers describe different source text, and the coordinates begin to drift.

---

## The path from Blocks to retrieval units

```
ParsedFiling.sections
    │
    ▼
L1  Verify source coordinates              M1.1 contract, not new code
    │
    ▼
L2  Chunk schema + _source_span()          fail-closed provenance validation
    │
    ▼
L3  section_units()                        structure-aware grouping
    │
    ▼
L4  _citation() + _context_header()        synthetic retrieval context
    │
    ▼
L5  chunk_filing()                         assembly, source-sort, ordinals
```

Only `chunk_filing()` is public. Everything before it is internal machinery.

| Layer | Responsibility | Focused test |
|---|---|---|
| L1 | canonical source identity and Block coordinates | `test_02_block_spans.py` |
| L2 | immutable Chunk contract and fail-closed spans | `test_01_contract.py` |
| L3 | structure-aware text/table units | `test_03_text.py`, `test_04_tables.py` |
| L4 | isolated retrieval context and citations | `test_03_text.py -k "context or narrative_heading"` |
| L5 | assembly, source order, round trip, golden counts | `test_05_roundtrip.py`, `test_06_golden.py` |

---

## L1 — Verify the source contract before building on it

### Why start here and not with the chunker

A character offset like `source_pos=14823` is just a number. It becomes meaningful only when bound to a specific file — the exact bytes, decoded as UTF-8, without newline translation. If the parser ever silently changes how it decodes the source, every offset becomes wrong, and every citation points to the wrong text.

M1.1 already provides this contract: `read_source()` decodes bytes directly, `source_digest()` computes the SHA-256, and `ParsedFiling` records `source_length` and `source_sha256`. The chunker will rely on these values for every single chunk it produces. If they are wrong, every chunk is wrong.

So before writing a single line of chunking code, verify the input.

### The input contract

These are M1.1 data structures — not new code for this module. Read them to understand what the chunker will receive.

#### Reference file: `app/ingestion/parser.py`

<!-- src: app/ingestion/parser.py::Block,ParsedFiling -->
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
```

<!-- src: app/ingestion/parser.py::read_source,source_digest -->
```python
def read_source(path: str | Path) -> str:
    """Decode source bytes as UTF-8 without universal-newline translation."""
    return Path(path).read_bytes().decode("utf-8")


def source_digest(source: str) -> str:
    """Bind character offsets to the exact UTF-8 source snapshot."""
    return hashlib.sha256(source.encode("utf-8")).hexdigest()
```

The source is decoded directly from bytes as UTF-8. `source_length` is the length of the decoded string, and `source_sha256` binds it to the exact bytes.

### Verify

```bash
uv run pytest tests/chunk/test_02_block_spans.py -q
```

Passing tests prove that text and table Blocks round-trip into the same snapshot, including CRLF input. If a coordinate is missing, reversed, overlapping, or outside the document, do not create the chunker yet. Compare `source[block.source_pos:block.end_pos]` with the original element first.

**What you have now:** Zero new lines of code, but verified trust. Every Block offset in the corpus points into the right file, at the right position, bound by the right hash. This is the foundation everything else rests on.

---

## L2 — The Chunk contract and fail-closed spans

### The long road a chunk will travel

The `Chunk` objects created here go on this journey.

```
M1.3 creation → M1.4 DB storage → M2 embedding/retrieval → M4 LLM judgment → M4 report citation
```

What happens if someone mutates a field somewhere along the way — tidies the body, nudges the span, renumbers the ordinal?

**The citation silently becomes false.** No crash, no error. A wrong answer simply arrives at the user complete with supporting evidence. Bugs of this kind are extremely hard to find after the fact.

So `frozen=True`. Mutation raises `FrozenInstanceError` **at the point of attempt**. The only way to "modify" a chunk is `dataclasses.replace()` to build a new object, and that is explicit enough to show up in code review.

### On an odd span, refuse rather than guess

Odd coordinates do occur. `source_pos` is `None`, or the end precedes the start, or the span runs past the document length.

The temptation is to "handle it reasonably." Default the missing one to 0, fix the reversed one, clip the overflow. The program keeps running.

The problem is that those chunks **cite the wrong text.** A plausible answer comes out, carrying evidence coordinates, and opening them shows an unrelated paragraph.

In a search system **a wrong citation is worse than no citation.** A user who sees "no results" knows to ask again. A user who sees a confident, incorrect citation makes a judgment on false evidence. In a 10-K review that judgment may be an investment or an audit call.

So this chunker **refuses to create a chunk rather than create one with uncertain provenance.** A halted pipeline gets a person looking at the cause; one that quietly continues gets nobody looking at all.

### What to define, what to implement, and what to inspect

L2 does not chunk anything yet. It settles what a chunk *is* and what the system refuses to build, in three cumulative steps on one file.

| Area | Learning action | What to take away |
|---|---|---|
| Module foundation | **Define the structure** | Which contracts this module stands on |
| `ChunkConfig` and `Chunk` | **Write the model declarations** | Why two text fields instead of one |
| `_source_span` | **Implement** the fail-closed gate yourself | Which malformed spans never become a chunk |

### Create the module

Create `app/ingestion/chunk.py` with the module rationale, imports, and public types:

#### Create `app/ingestion/chunk.py` — module foundation

```python
"""Structure-aware chunking with source-stable citations.

The chunk id is deliberately not the citation. Re-chunking changes ids and would
invalidate a golden set, making chunk-size ablation impossible. Every chunk instead
carries a `[start_char, end_char)` span into the immutable source filing.

The pipeline keeps source text and synthetic context separate:

    body             text derived from the cited source span
    context_header   filing / Item / narrative heading metadata
    content          context_header + body (the text indexed for retrieval)

This separation makes citation round-trip tests possible even though contextual
headers are intentionally repeated across chunks.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import re
from typing import Literal

from app.ingestion.parser import Block, ParsedFiling, Section
from app.ingestion.tables import table_to_markdown

ChunkKind = Literal["text", "table"]
```

### 1,200 characters is not the right answer

Seeing `DEFAULT_TARGET_TEXT_CHARS = 1_200` invites the question "why 1,200?" The honest answer is **we do not know yet.**

Chunk size is the parameter with no right answer in RAG. Small is precise but context-starved; large carries context but drags in the irrelevant. It varies by domain and by embedding model.

So this value is treated as **an experimental arm, not a conclusion.** M3 chunks the same corpus at several values, compares retrieval quality, and records the winner.

What makes that possible connects to the heart of M1.3's design: **citations use source coordinates, not chunk IDs.** Change the chunk size and every chunk ID changes while the source coordinates stay put. So configurations can be compared without rebuilding the golden set.

Had citations been chunk IDs, every size change would invalidate the golden set and this experiment would be impossible.

First the comment that records that intent, then the constants and types.

#### Extend `app/ingestion/chunk.py` — settings and public types

```python
# Defaults are starting arms, not conclusions. M3 evaluates alternatives and records
# the winning configuration; callers can change the value without changing logic.
```

<!-- src: app/ingestion/chunk.py::DEFAULT_TARGET_TEXT_CHARS,SOURCE_SHA256_RE -->
```python
DEFAULT_TARGET_TEXT_CHARS = 1_200
SOURCE_SHA256_RE = re.compile(r"[0-9a-f]{64}", re.ASCII)
```

<!-- src: app/ingestion/chunk.py::ChunkConfig,Chunk -->
```python
@dataclass(frozen=True, slots=True)
class ChunkConfig:
    """Tunable chunking parameters used by the M3 ablation."""

    target_text_chars: int = DEFAULT_TARGET_TEXT_CHARS

    def __post_init__(self) -> None:
        if self.target_text_chars <= 0:
            raise ValueError("target_text_chars must be positive")


@dataclass(frozen=True, slots=True)
class Chunk:
    """A retrieval unit whose citation survives re-chunking."""

    doc_id: str
    item: str | None
    kind: ChunkKind
    ordinal: int
    body: str
    context_header: str
    citation: str
    start_char: int
    end_char: int
    source_sha256: str = ""

    @property
    def content(self) -> str:
        """Text sent to indexing: repeated context followed by source-derived body."""
        return f"{self.context_header}\n\n{self.body}" if self.context_header else self.body
```

The complete `Chunk` contract is easier to use as a field map than as a list to infer from later functions.

| Field | Value or constraint | Role |
|---|---|---|
| `doc_id` | filing identity | Connects the chunk to one parsed filing. |
| `item` | SEC Item or `None` | Preserves the section identity when one exists. |
| `kind` | `"text"` or `"table"` | Selects the source-preserving conversion path. |
| `ordinal` | zero-based document order | Gives each chunk a deterministic position within its filing. |
| `body` | source-derived text | Supplies the evidence checked by the round-trip test. |
| `context_header` | synthetic metadata | Adds retrieval context without pretending it came from the source. |
| `citation` | human-readable source label | Lets people identify the filing and section. |
| `start_char`, `end_char` | half-open source span `[start_char, end_char)` | Lets machines reopen the exact evidence in the source. |
| `source_sha256` | lowercase SHA-256 | Binds the span to one immutable source snapshot. |
| `content` | derived property | Joins `context_header` and `body` for indexing without changing either field. |

### Why `body` and `context_header` were deliberately split

You may wonder why `Chunk` has two text fields. One would be simpler.

Here is the background. A retrieved chunk has to declare what it is about. "Gross margin was 72.7%" alone says nothing about which company, which year, which section. So a label like `NVDA FY2024, Item 7, Liquidity` is attached and embedded along with it. Retrieval quality rises, and the LLM understands the excerpt.

The problem is that **this label is not in the source.** It is synthetic text we produced.

Mix it into `body` and M1.3's most important test breaks: the **round-trip test** that slices `source[start_char:end_char]` and compares it against `body`. The body now carries a prefix absent from the source, so it mismatches.

At that point the temptation is "loosen the test to tolerate a prefix." That does pass. And it **loses the ability to detect real citation drift**, because a mismatch caused by drifted coordinates becomes indistinguishable from one caused by the prefix.

So the fields are split. The rule is simple.

| Field | Contents | Used by |
|---|---|---|
| `body` | **only text that came from the source** | round-trip test, citation verification |
| `context_header` | **only metadata we produced** | — |
| `content` | the two combined | embedding, retrieval index |

The round-trip test checks `body` strictly and retrieval uses `content`. They do not interfere. **Separating synthetic from source-derived in the data structure is what keeps verifiability alive.**

### The span validator

This function is the fail-closed gate. Every chunk must pass through it.

#### Target file: `app/ingestion/chunk.py`

<!-- src: app/ingestion/chunk.py::_source_span -->
```python
def _source_span(blocks: list[Block], source_length: int | None = None) -> tuple[int, int]:
    """Validate and aggregate one ordered, contiguous narrative block group."""
    if not blocks or any(block.source_pos is None or block.end_pos is None for block in blocks):
        raise ValueError("cannot create a chunk without complete source spans")

    groups = {block.source_group for block in blocks}
    if len(groups) != 1:
        raise ValueError("cannot create a chunk across source groups")

    previous_end: int | None = None
    for block in blocks:
        start, end = block.source_pos, block.end_pos
        assert start is not None and end is not None
        if not 0 <= start < end:
            raise ValueError(f"invalid block source span: [{start}, {end})")
        if previous_end is not None and start < previous_end:
            raise ValueError("chunk blocks are out of source order or overlap")
        if source_length is not None and end > source_length:
            raise ValueError(
                f"block source span ends beyond source length: {end} > {source_length}"
            )
        previous_end = end

    start = blocks[0].source_pos
    end = blocks[-1].end_pos
    assert start is not None and end is not None
    return start, end
```

### What each check catches

Walk through the validation in order:

1. **Missing coordinates.** If any Block lacks `source_pos` or `end_pos`, the span is unknowable. Rejecting early prevents a `None` from becoming `0` through arithmetic.

2. **Cross-group spans.** A `source_group` identifies a contiguous narrative range within a Section. Intel filings have Items that own multiple discontiguous ranges. Allowing a chunk to span two groups would create a citation that covers text from a different Item that sits between them.

3. **Reversed or zero-width spans.** `0 <= start < end` catches negative positions, start-after-end, and empty spans. Any of these would produce a citation that slices the wrong text or no text at all.

4. **Out-of-order or overlapping Blocks.** If Block B starts before Block A ends, the same source text would be cited by two chunks. The overlap check prevents double counting.

5. **Beyond document bounds.** If `end > source_length`, the citation points past the end of the file. This catches off-by-one errors in the parser.

The function returns the tightest enclosing span: from the first Block's start to the last Block's end. Gaps between Blocks (where headings or other elements sit) are acceptable — they are part of the source range but not part of the chunk body.

### Verify

```bash
uv run pytest tests/chunk/test_01_contract.py -q
```

Passing tests prove that invalid limits and spans are rejected and `Chunk` is immutable. On failure, call `_source_span()` with two tiny Blocks and inspect their group IDs and adjacent start/end values first.

**What you have now:** An importable module with a frozen schema and a span validator that refuses to produce chunks with uncertain provenance. No chunks exist yet — the gate is built before anything can pass through it.

---

## L3 — Structure-aware text and table units

### What to define, what to implement, and what to inspect

L3 is the only section in this module with an algorithm in it. Two steps, one file.

| Area | Learning action | What to take away |
|---|---|---|
| `_Unit` | **Write the record declaration** | What a grouping decision has to remember |
| `section_units` | **Implement** the accumulator yourself | Which boundaries are hard and which are preferences |

### The grouping problem

Consider a Section with these Blocks in order:

```
heading   "Revenue Recognition"          group=1
paragraph "The Company recognizes..."    group=1  (312 chars)
paragraph "Performance obligations..."   group=1  (487 chars)
paragraph "Contract assets decreased..." group=1  (203 chars)
table     <table>...</table>             group=1
paragraph "The following table..."       group=1  (89 chars)
heading   "Deferred Revenue"             group=2
paragraph "Deferred revenue was..."      group=2  (445 chars)
```

The first three paragraphs total 1,002 characters — under the 1,200-character target. They should become one text chunk. The table must be its own chunk. The short paragraph after the table starts a new text accumulation. The heading "Deferred Revenue" flushes whatever is pending and resets the narrative context. The paragraph after it belongs to a different source group.

### What the `_Unit` intermediate represents

A `_Unit` is the last stage before a public `Chunk`. It carries the body text, the source Blocks (for span computation), and the narrative heading (for context). It does not carry filing-level metadata — that comes from L4. Keeping the intermediate lightweight means a full `ParsedFiling` need not be constructed to test `section_units()`.

### Concretely, why long paragraphs must not be split

The rule "paragraphs are never split" was stated earlier, and a 3,773-character paragraph tests your resolve. Three clean 1,200-character pieces would be tidy. Every character-level splitter does exactly that.

Look at what actually goes wrong.

Split a paragraph at character 1,200 and that fragment needs a source coordinate. But the parser gives coordinates only for **Block boundaries.** There is no coordinate for an arbitrary position inside a Block.

Could it be computed? The Block spans `[14823, 18596)`, so text character 1,200 is roughly at `14823 + 1200 = 16023`.

**"Roughly" is the problem.** The original HTML is full of things the extracted text does not contain: tags, HTML entities, whitespace, attributes. Text character 1,200 might sit at HTML character 3,000, or 1,500.

In the worst case the interpolated coordinate lands **in the middle of an HTML tag.** Open that citation and this is what appears.

```
"...cited evidence: <td class=\"num\" colspan=\"2\" style=\"padding-l"
```

That is not a citation anyone can be shown.

**So a Block is never split. A long paragraph simply becomes a large chunk.** `target_text_chars` is a preference — "group up to about this size" — not a hard limit that forces a cut.

It trades size uniformity for verifiability. Deciding where to make trades like this is most of RAG design.

### Code

Add this divider after `_source_span()`, then the `_Unit` type and `section_units()` directly below it:

#### Extend `app/ingestion/chunk.py` — assemble text chunks

```python
# ── L2. Text chunks ──────────────────────────────────────────────────────────
```

<!-- src: app/ingestion/chunk.py::_Unit,section_units -->
```python
@dataclass(frozen=True, slots=True)
class _Unit:
    kind: ChunkKind
    body: str
    blocks: list[Block]
    narrative_heading: str | None


def section_units(section: Section, config: ChunkConfig) -> list[_Unit]:
    """Build source-ordered units without crossing a table or narrative heading.

    Paragraphs are never split internally: source block boundaries are the stable
    units. A single long paragraph may therefore exceed the target. The target is a
    grouping preference, not a destructive hard limit.
    """
    units: list[_Unit] = []
    pending: list[Block] = []
    pending_chars = 0
    narrative_heading: str | None = None
    active_group: int | None = None

    def flush() -> None:
        nonlocal pending, pending_chars
        if pending:
            units.append(
                _Unit(
                    kind="text",
                    body="\n\n".join(block.text for block in pending),
                    blocks=pending,
                    narrative_heading=narrative_heading,
                )
            )
        pending = []
        pending_chars = 0

    for block in section.blocks:
        if active_group != block.source_group:
            flush()
            active_group = block.source_group
            narrative_heading = block.source_heading
        if block.kind == "heading":
            flush()
            narrative_heading = block.text
            continue
        if block.kind == "table":
            flush()
            markdown = table_to_markdown(block.html)
            if markdown:
                units.append(_Unit("table", markdown, [block], narrative_heading))
            continue
        if not block.text.strip():
            continue

        separator = 2 if pending else 0
        if pending and pending_chars + separator + len(block.text) > config.target_text_chars:
            flush()
        pending.append(block)
        pending_chars += (2 if len(pending) > 1 else 0) + len(block.text)
    flush()
    return units
```

### How the accumulator works

The function maintains a `pending` buffer of paragraph Blocks. Walk through the control flow for each Block kind:

1. **Source group change.** Flush pending text. Update the active group and narrative heading. This prevents a chunk from spanning discontiguous ranges — the exact problem that caused twelve false citations in the first implementation.

2. **Heading.** Flush pending text. Update the narrative heading. The heading itself does not become a chunk — it goes into `context_header` via L4. Including heading text in the body would add content that is not part of the cited source evidence.

3. **Table.** Flush pending text. Convert HTML to markdown via M1.2. If the result is non-empty, create a single-Block table unit. If empty (layout-only table), discard. A table is never grouped with adjacent paragraphs because it has a fundamentally different structure.

4. **Empty paragraph.** Skip. Empty Blocks carry no evidence.

5. **Content paragraph.** Check if adding this paragraph would exceed the target. If so, flush first, then start a new accumulation. The `separator = 2` accounts for the `\n\n` that joins paragraphs in the body.

6. **End of Section.** The final `flush()` after the loop ensures the last group of paragraphs is not lost.

### Why `\n\n` joins and not space

Paragraphs are semantically distinct. Joining with a space would merge "...decreased by 15%." and "The Company expects..." into a single sentence. Double newlines preserve paragraph identity in the body text, which matters for both readability and token boundaries in the embedding model.

### Verify

The public `chunk_filing()` assembler does not exist yet, so its tests would only skip. Call this layer directly instead:

```bash
uv run python -c "from app.ingestion.chunk import ChunkConfig, section_units; from app.ingestion.parser import Block, Section; s = Section('II', '7', 'MD&A', 'MD&A', [Block('paragraph', 'first', source_pos=10, end_pos=20), Block('paragraph', 'second', source_pos=20, end_pos=30)]); u = section_units(s, ChunkConfig()); assert [x.body for x in u] == ['first\\n\\nsecond']"
```

A silent exit proves that adjacent paragraphs were grouped in order. If a boundary case fails, print each unit's kind, source group, and span, then find the missing `flush()` at the first transition.

**What you have now:** Structure-aware grouping that respects every boundary — Item, table, heading, source group. Paragraphs are never split. Tables are never merged with prose. The accumulator flushes at every transition point.

---

## L4 — Retrieval context and citation labels

### A chunk without context is half useless

Suppose retrieval returns this chunk.

```text
"Net revenue increased 122% compared to the prior year, driven by Data Center revenue growth of 217%."
```

An impressive number. But **whose, and for which year?** Across an index of 20 filings that sentence alone cannot say. Hand it to an LLM as evidence and it is well placed to confuse the company or misstate the year.

So context is attached.

```text
"NVDA FY2024 · Item 7 · Management's Discussion · Liquidity

Net revenue increased 122%..."
```

Now the chunk describes itself. Retrieval improves too — a search for "NVIDIA 2024 revenue" hits the header even when the body contains neither "NVIDIA" nor "2024."

This string is not in the source. We assembled it from filing metadata and section titles, which is why — as established above — it lands not in `body` but in `context_header`.

### What to define, what to implement, and what to inspect

L4 adds no new data. It derives two labels from what a filing already knows.

| Area | Learning action | What to take away |
|---|---|---|
| `_citation` | **Write the field mapping** | The one label a person reads |
| `_context_header` | **Implement** the composition yourself | Why the deduplication check exists |

### Why `citation` and `context_header` both exist

Both are synthetic, so why two fields? They serve different purposes.

| Field | Example | Purpose |
|---|---|---|
| `citation` | `NVDA FY2024 · Item 7` | a stable label **shown to people** |
| `context_header` | `NVDA FY2024 · Item 7 · Management's Discussion · Liquidity` | rich context **put into the retrieval index** |

`citation` is printed verbatim in the final report, so it must be short and stable. Add the narrative subheading and citations for the same Item look different chunk to chunk, which is more confusing than helpful.

`context_header` is for retrieval, where longer helps. Including the subheading is what makes a search for "NVIDIA liquidity" land.

**Use one field for both display and processing and one of them is always awkward.**

### Code

Insert these two functions after `_source_span()` and immediately before the L2 divider you added in the previous step:

#### Target file: `app/ingestion/chunk.py`

<!-- src: app/ingestion/chunk.py::_citation,_context_header -->
```python
def _citation(filing: ParsedFiling, section: Section) -> str:
    item = f"Item {section.item}" if section.item else "Unnumbered section"
    return f"{filing.ticker} FY{filing.fiscal_year} · {item}"


def _context_header(
    filing: ParsedFiling, section: Section, narrative_heading: str | None = None
) -> str:
    """Build context that remains useful when a chunk is retrieved in isolation."""
    parts = [_citation(filing, section)]
    title = section.canonical_title or section.reported_title
    if title:
        parts.append(title)
    if narrative_heading and narrative_heading != title:
        parts.append(narrative_heading)
    return " · ".join(parts)
```

### Why the deduplication check exists

The condition `narrative_heading != title` prevents output like `"NVDA FY2024 · Item 7 · Management's Discussion · Management's Discussion"`. This happens when the section's canonical title and the current narrative heading are the same string — common for Items that have no sub-sections. Without the check, the repeated title wastes tokens and looks broken.

### Verify

```bash
uv run python -c "from app.ingestion.chunk import _context_header; from app.ingestion.parser import ParsedFiling, Section; f = ParsedFiling('NVDA-FY2024', 'NVDA', '1045810', '10-K', '2024-02-21', '2024-01-28', 2024, 'x', 'https://example.test'); s = Section('II', '7', 'Management Discussion', 'Management Discussion'); assert _context_header(f, s, 'Liquidity').endswith('Liquidity')"
```

A silent exit proves that the narrative title appears in context and is not deduplicated against itself. For a suspicious real boundary, compare `source_group`, `source_heading`, `reported_title`, and the resulting header for two adjacent ranges.

**What you have now:** Every chunk will carry a human-readable citation and a machine-useful context header. The synthetic text is confined to its own field — `body` remains pure source evidence.

---

## L5 — Assemble, source-sort, re-number

### What to define, what to implement, and what to inspect

L5 writes the only public function in the module. Everything before it was preparation.

| Area | Learning action | What to take away |
|---|---|---|
| `chunk_filing` guards | **Implement** the corpus-level guards yourself | Why a filing without a hash cannot be chunked |
| The nested `append` | **Write the field mapping** | Where every earlier piece finally meets |
| Sort and re-number | **Implement** the ordering invariant yourself | Why ordinals are assigned last, not first |

### The final connection

This function is where every contract built so far comes together. It validates the filing's source identity, iterates through sections, builds units, computes spans, and produces the final chunk list.

### The ordering problem

Ordinary heading-based documents pose no problem. The parser built them walking top to bottom, so the section list is already in source order.

**xref documents are different.** Recall M1.1's L8: `segment_by_xref` walks the index table to build Sections, so its output comes out in **SEC Item number order** — Item 1, 1A, 2, 3 — regardless of where that content actually sits in the document.

And Intel's Item 7 is scattered across pages 5, 19-44, and 47-51.

Assign ordinals in arrival order from that state and Item 1's chunks take 0–15 while Item 2's take 16–30 — even though Item 2's content may physically precede Item 1.

Someone scanning chunks in ordinal order then sees **content jumping back and forth through the document.** Build a "previous chunk" or "next chunk" feature and it returns the wrong thing.

**The fix is simple: build them all, sort by source position, then assign ordinals.** A stable sort by `(start_char, end_char)` restores document order, and ordinals `0..n-1` then mean "how far into the document this is" rather than "which Item this belongs to."

### Changing a number on a frozen object

The sort happens after all chunks are built, but each chunk already received a provisional ordinal at creation. They have to be reassigned.

`chunk.ordinal = i` will not work: `frozen=True` from L2 raises `FrozenInstanceError`.

`dataclasses.replace(chunk, ordinal=i)` is used instead, producing a new object with only the ordinal changed and everything else copied.

It looks like a nuisance, and it is exactly what frozen buys you. **The code guarantees that ordinals change in exactly one place across the whole pipeline.** Had anything else changed one quietly, it would have raised on the spot.

### Code

Add this divider after `section_units()`, then place `chunk_filing()` below it:

#### Extend `app/ingestion/chunk.py` — filing chunking entry point

```python
# ── L3/L4/L5. Tables, context, and source spans ──────────────────────────────
```

<!-- src: app/ingestion/chunk.py::chunk_filing -->
```python
def chunk_filing(filing: ParsedFiling, config: ChunkConfig | None = None) -> list[Chunk]:
    """Convert a parsed filing into ordered text/table chunks with source spans."""
    if filing.source_length <= 0:
        raise ValueError(f"{filing.doc_id} has no canonical source length")
    if SOURCE_SHA256_RE.fullmatch(filing.source_sha256) is None:
        raise ValueError(f"{filing.doc_id} has no canonical source SHA-256")
    cfg = config or ChunkConfig()
    chunks: list[Chunk] = []

    def append(
        section: Section,
        kind: ChunkKind,
        body: str,
        blocks: list[Block],
        narrative_heading: str | None = None,
    ) -> None:
        start, end = _source_span(blocks, filing.source_length)
        chunks.append(
            Chunk(
                doc_id=filing.doc_id,
                item=section.item,
                kind=kind,
                ordinal=len(chunks),
                body=body,
                context_header=_context_header(filing, section, narrative_heading),
                citation=_citation(filing, section),
                start_char=start,
                end_char=end,
                source_sha256=filing.source_sha256,
            )
        )

    for section in filing.sections:
        for unit in section_units(section, cfg):
            append(
                section,
                unit.kind,
                unit.body,
                unit.blocks,
                unit.narrative_heading,
            )

    # Heading-based sections already arrive in source order. Xref sections arrive
    # in SEC Item order instead, and one Item can own multiple narrative ranges.
    # A stable span sort restores document order before ordinals are materialized.
    chunks.sort(key=lambda chunk: (chunk.start_char, chunk.end_char))
    return [replace(chunk, ordinal=ordinal) for ordinal, chunk in enumerate(chunks)]
```

### Walk through the function

1. **Validate filing identity.** If `source_length` is not positive or `source_sha256` is not a valid 64-character hex string, reject the entire filing. A filing without identity cannot produce verifiable citations.

2. **Build an inner `append()`.** This closure captures the filing and the growing `chunks` list. Each call validates the span (via `_source_span`), builds the context header (via `_context_header`), and creates a frozen `Chunk`. The provisional ordinal is `len(chunks)` — correct only if sections arrive in source order.

3. **Iterate sections and units.** For each section, `section_units()` produces the structure-aware grouping from L3. Each unit becomes a chunk via `append()`.

4. **Sort by source position.** The stable sort by `(start_char, end_char)` fixes ordinal assignment for xref filings. For heading-based filings, the sort is a no-op — they already arrive in order.

5. **Reassign ordinals.** The list comprehension with `replace()` produces the final chunk list with dense ordinals `0..n-1` in source order.

### Verify

After pasting this code, `chunk_filing()` exists for the first time. Run the behavior that was deferred from L3 and L4, then continue into the round-trip and golden gates:

```bash
uv run pytest tests/chunk/test_03_text.py tests/chunk/test_04_tables.py -q
uv run pytest tests/chunk/test_03_text.py -k "context or narrative_heading" -q
uv run pytest tests/chunk/test_05_roundtrip.py tests/chunk/test_06_golden.py -q
```

When all three commands pass:
- Long paragraphs and tables remain whole (no internal splitting)
- Synthetic context stays isolated from source-derived body
- Every body Block is consumed exactly once (no gaps, no duplicates)
- Chunk spans do not overlap
- Golden counts match the corpus baseline

Do not change a golden value on failure. Find the first gap, overlap, or repeated Block in source order.

### Where you are now

Twenty filings produce **9,172 chunks** — 8,083 text and 1,089 table.

That number is this project's baseline. Fix the parser or change a chunking parameter and it moves, and the golden test says so.

Every chunk carries a verified source span, a citation, and retrieval context. The `body` contains only text that came from the source, and ordinals reflect document order no matter what order sections arrived in.

### What you should be able to explain now

- **Why can a chunk id not serve as the citation?**
  - **Answer:** Chunk IDs change when chunk size or grouping changes and do not identify an exact source passage. A document identity, source hash, and half-open character span remain verifiable across chunking experiments.
- **Which test becomes impossible if `body` and `context_header` are merged?**
  - **Answer:** The strict round-trip test comparing source-derived `body` with the cited source range becomes impossible because the synthetic header is absent from the source. Loosening that comparison would also hide real coordinate drift.
- **What does `_source_span` protect by refusing rather than guessing?**
  - **Answer:** It blocks chunks with missing, reversed, overlapping, cross-group, or out-of-bounds coordinates. Failing closed prevents plausible retrieval text from being paired with evidence coordinates that point somewhere else.
- **Why may a single long paragraph exceed the target size?**
  - **Answer:** M1.1 provides coordinates only at Block boundaries, and extracted-text positions cannot be interpolated reliably through HTML markup. The target is therefore a grouping preference, while an indivisible long paragraph stays whole to keep its citation verifiable.
- **Why are ordinals assigned after the sort rather than before it?**
  - **Answer:** Xref Sections arrive in SEC Item order, not physical source order. Sorting all chunks by source span first makes dense ordinals represent document order and keeps previous/next navigation deterministic.

---

## What this module hands to the next one

M1.3 is the last computational module of stage M1. Here is where the `Chunk` objects go.

| What M1.3 produced | Receiver | What happens there |
|---|---|---|
| `Chunk.content` (context+body) | **M1.4 → M2** | text to embed, full-text search index |
| `Chunk.body` | **M4** | the source evidence handed to the LLM |
| `Chunk.start_char` / `end_char` | **M1.4** | coordinate columns on the `chunks` table |
| `Chunk.source_sha256` | **M1.4** | identity match against the document row |
| `Chunk.citation` | **M4** | the citation label printed in the final report |
| `Chunk.ordinal` | **M1.4** | the upsert conflict key `(doc_id, ordinal)` |
| the count 9,172 | **M3** | baseline for the chunk-size ablation |

The very next chapter, M1.4, puts these chunks into PostgreSQL. Not with a plain INSERT, though. **Loading the same corpus twice must leave the database identical**, and when a parser fix forces a reload, **embeddings for unchanged chunks must survive.** The `ordinal` and `source_sha256` built here are the keys that make that possible.

---

## Add the inspection CLI and verify

With `chunk_filing()` in place, the core module is complete. Append this CLI to `app/ingestion/chunk.py`. It calls the same public function and prints the result for a human reader.

#### Extend `app/ingestion/chunk.py` — inspection CLI

```python
if __name__ == "__main__":  # pragma: no cover - manual inspection helper
    import argparse
    import json
    from pathlib import Path

    from app.ingestion.parser import parse_filing

    parser = argparse.ArgumentParser(description="Inspect structure-aware 10-K chunks.")
    parser.add_argument("--doc", default="NVDA-FY2024", help="doc_id, e.g. NVDA-FY2024")
    parser.add_argument("--kind", choices=("text", "table"))
    parser.add_argument("--limit", type=int, default=3)
    args = parser.parse_args()

    manifest = json.loads(Path("data/corpus/manifest.json").read_text())
    entry = next(
        item for item in manifest if f"{item['ticker']}-FY{item['report_date'][:4]}" == args.doc
    )
    parsed, _ = parse_filing(entry)
    selected = [chunk for chunk in chunk_filing(parsed) if not args.kind or chunk.kind == args.kind]
    for chunk in selected[: args.limit]:
        print(f"\n{'─' * 80}\n#{chunk.ordinal} {chunk.kind} [{chunk.start_char}, {chunk.end_char})")
        print(chunk.content)
```

Run the full verification:

```bash
uv run pytest tests/chunk -q
uv run python scripts/check_doc_code.py docs/en/m1-3-chunk/03-build.md docs/ko/m1-3-chunk/03-build.md
uv run ruff check --no-fix app/ingestion/chunk.py tests/chunk
uv run python -m app.ingestion.chunk --doc INTC-FY2022 --kind table --limit 2
```

When all four commands pass without a missing-symbol skip, the CLI displays two citation-labeled table chunks in source order. Resolve failures in command order. If the corpus is absent, restore that prerequisite first; never hide a provenance failure behind a looser fallback or a changed golden count that was not re-measured from the source.

<!-- complete-files:start -->
## Reference baseline — the complete canonical files

Create or replace the canonical paths below directly. Do not create `_mine.py` or another learner-copy module. The earlier excerpts explain individual decisions; the blocks in this section are the finished files to compare against once a checkpoint is done. Preserve the shown type annotations and English comments; `pyproject.toml` is the authoritative Ruff policy.

### M1.3 — Complete checkpoint

#### Create or replace `app/ingestion/chunk.py`

<!-- file: app/ingestion/chunk.py -->
```python
"""Structure-aware chunking with source-stable citations.

The chunk id is deliberately not the citation. Re-chunking changes ids and would
invalidate a golden set, making chunk-size ablation impossible. Every chunk instead
carries a `[start_char, end_char)` span into the immutable source filing.

The pipeline keeps source text and synthetic context separate:

    body             text derived from the cited source span
    context_header   filing / Item / narrative heading metadata
    content          context_header + body (the text indexed for retrieval)

This separation makes citation round-trip tests possible even though contextual
headers are intentionally repeated across chunks.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import re
from typing import Literal

from app.ingestion.parser import Block, ParsedFiling, Section
from app.ingestion.tables import table_to_markdown

ChunkKind = Literal["text", "table"]

# Defaults are starting arms, not conclusions. M3 evaluates alternatives and records
# the winning configuration; callers can change the value without changing logic.
DEFAULT_TARGET_TEXT_CHARS = 1_200
SOURCE_SHA256_RE = re.compile(r"[0-9a-f]{64}", re.ASCII)


@dataclass(frozen=True, slots=True)
class ChunkConfig:
    """Tunable chunking parameters used by the M3 ablation."""

    target_text_chars: int = DEFAULT_TARGET_TEXT_CHARS

    def __post_init__(self) -> None:
        if self.target_text_chars <= 0:
            raise ValueError("target_text_chars must be positive")


@dataclass(frozen=True, slots=True)
class Chunk:
    """A retrieval unit whose citation survives re-chunking."""

    doc_id: str
    item: str | None
    kind: ChunkKind
    ordinal: int
    body: str
    context_header: str
    citation: str
    start_char: int
    end_char: int
    source_sha256: str = ""

    @property
    def content(self) -> str:
        """Text sent to indexing: repeated context followed by source-derived body."""
        return f"{self.context_header}\n\n{self.body}" if self.context_header else self.body


def _source_span(blocks: list[Block], source_length: int | None = None) -> tuple[int, int]:
    """Validate and aggregate one ordered, contiguous narrative block group."""
    if not blocks or any(block.source_pos is None or block.end_pos is None for block in blocks):
        raise ValueError("cannot create a chunk without complete source spans")

    groups = {block.source_group for block in blocks}
    if len(groups) != 1:
        raise ValueError("cannot create a chunk across source groups")

    previous_end: int | None = None
    for block in blocks:
        start, end = block.source_pos, block.end_pos
        assert start is not None and end is not None
        if not 0 <= start < end:
            raise ValueError(f"invalid block source span: [{start}, {end})")
        if previous_end is not None and start < previous_end:
            raise ValueError("chunk blocks are out of source order or overlap")
        if source_length is not None and end > source_length:
            raise ValueError(
                f"block source span ends beyond source length: {end} > {source_length}"
            )
        previous_end = end

    start = blocks[0].source_pos
    end = blocks[-1].end_pos
    assert start is not None and end is not None
    return start, end


def _citation(filing: ParsedFiling, section: Section) -> str:
    item = f"Item {section.item}" if section.item else "Unnumbered section"
    return f"{filing.ticker} FY{filing.fiscal_year} · {item}"


def _context_header(
    filing: ParsedFiling, section: Section, narrative_heading: str | None = None
) -> str:
    """Build context that remains useful when a chunk is retrieved in isolation."""
    parts = [_citation(filing, section)]
    title = section.canonical_title or section.reported_title
    if title:
        parts.append(title)
    if narrative_heading and narrative_heading != title:
        parts.append(narrative_heading)
    return " · ".join(parts)


# ── L2. Text chunks ──────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class _Unit:
    kind: ChunkKind
    body: str
    blocks: list[Block]
    narrative_heading: str | None


def section_units(section: Section, config: ChunkConfig) -> list[_Unit]:
    """Build source-ordered units without crossing a table or narrative heading.

    Paragraphs are never split internally: source block boundaries are the stable
    units. A single long paragraph may therefore exceed the target. The target is a
    grouping preference, not a destructive hard limit.
    """
    units: list[_Unit] = []
    pending: list[Block] = []
    pending_chars = 0
    narrative_heading: str | None = None
    active_group: int | None = None

    def flush() -> None:
        nonlocal pending, pending_chars
        if pending:
            units.append(
                _Unit(
                    kind="text",
                    body="\n\n".join(block.text for block in pending),
                    blocks=pending,
                    narrative_heading=narrative_heading,
                )
            )
        pending = []
        pending_chars = 0

    for block in section.blocks:
        if active_group != block.source_group:
            flush()
            active_group = block.source_group
            narrative_heading = block.source_heading
        if block.kind == "heading":
            flush()
            narrative_heading = block.text
            continue
        if block.kind == "table":
            flush()
            markdown = table_to_markdown(block.html)
            if markdown:
                units.append(_Unit("table", markdown, [block], narrative_heading))
            continue
        if not block.text.strip():
            continue

        separator = 2 if pending else 0
        if pending and pending_chars + separator + len(block.text) > config.target_text_chars:
            flush()
        pending.append(block)
        pending_chars += (2 if len(pending) > 1 else 0) + len(block.text)
    flush()
    return units


# ── L3/L4/L5. Tables, context, and source spans ──────────────────────────────


def chunk_filing(filing: ParsedFiling, config: ChunkConfig | None = None) -> list[Chunk]:
    """Convert a parsed filing into ordered text/table chunks with source spans."""
    if filing.source_length <= 0:
        raise ValueError(f"{filing.doc_id} has no canonical source length")
    if SOURCE_SHA256_RE.fullmatch(filing.source_sha256) is None:
        raise ValueError(f"{filing.doc_id} has no canonical source SHA-256")
    cfg = config or ChunkConfig()
    chunks: list[Chunk] = []

    def append(
        section: Section,
        kind: ChunkKind,
        body: str,
        blocks: list[Block],
        narrative_heading: str | None = None,
    ) -> None:
        start, end = _source_span(blocks, filing.source_length)
        chunks.append(
            Chunk(
                doc_id=filing.doc_id,
                item=section.item,
                kind=kind,
                ordinal=len(chunks),
                body=body,
                context_header=_context_header(filing, section, narrative_heading),
                citation=_citation(filing, section),
                start_char=start,
                end_char=end,
                source_sha256=filing.source_sha256,
            )
        )

    for section in filing.sections:
        for unit in section_units(section, cfg):
            append(
                section,
                unit.kind,
                unit.body,
                unit.blocks,
                unit.narrative_heading,
            )

    # Heading-based sections already arrive in source order. Xref sections arrive
    # in SEC Item order instead, and one Item can own multiple narrative ranges.
    # A stable span sort restores document order before ordinals are materialized.
    chunks.sort(key=lambda chunk: (chunk.start_char, chunk.end_char))
    return [replace(chunk, ordinal=ordinal) for ordinal, chunk in enumerate(chunks)]


if __name__ == "__main__":  # pragma: no cover - manual inspection helper
    import argparse
    import json
    from pathlib import Path

    from app.ingestion.parser import parse_filing

    parser = argparse.ArgumentParser(description="Inspect structure-aware 10-K chunks.")
    parser.add_argument("--doc", default="NVDA-FY2024", help="doc_id, e.g. NVDA-FY2024")
    parser.add_argument("--kind", choices=("text", "table"))
    parser.add_argument("--limit", type=int, default=3)
    args = parser.parse_args()

    manifest = json.loads(Path("data/corpus/manifest.json").read_text())
    entry = next(
        item for item in manifest if f"{item['ticker']}-FY{item['report_date'][:4]}" == args.doc
    )
    parsed, _ = parse_filing(entry)
    selected = [chunk for chunk in chunk_filing(parsed) if not args.kind or chunk.kind == args.kind]
    for chunk in selected[: args.limit]:
        print(f"\n{'─' * 80}\n#{chunk.ordinal} {chunk.kind} [{chunk.start_char}, {chunk.end_char})")
        print(chunk.content)
```

Run the checkpoint:

```bash
uv run pytest tests/chunk -q
```

**Expected:** every selected offline test passes. A declared integration test may skip only when its external service is unavailable.

**Stop:** do not continue if a test fails or skips because a required symbol is missing.

**Debug:** rerun the same pytest target with `-vv --tb=long`, then fix the first failing contract before continuing.

<!-- complete-files:end -->
