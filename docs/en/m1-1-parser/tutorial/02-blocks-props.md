# M1.1 Tutorial 2 — Extract text without shattering the financial statements

L3 flattens the HTML tree into a list of blocks; L4 extracts formatting properties from a single block. This is where the first real algorithm appears.

L3 is the subtlest layer in the module. Written naively it shatters the financial statements cell by cell, and that damage only surfaces past M1.2 and M2, in the final citation.

**Prerequisite:** Tutorial 1's `uv run pytest tests/ingestion/test_01_blocks.py -k ixbrl_numbers_survive -v` and `-k item_regex -v` pass.

## What to write and where to implement it yourself

| Stretch | Learning action | What to take away |
|---|---|---|
| L3 `_is_data_table` | **Implement** the classification test | the basis for separating data tables from layout tables |
| L3 `leaf_blocks` | **Implement** the traversal | the single condition order that shatters financial statements |
| L4 `_inline_css` | **Write the structure** | formatting that lives in a nested span, not the element |
| L4 `block_props` | **Write the field mapping, then review the conversion** | why a dict is the right choice only here |

---

## L3 — Blockification — the subtlest layer in this chapter

HTML is a tree. But our job is to group everything "from this heading to the next heading" into one section. Expressing "until the next heading" over a tree means walking siblings, climbing to a parent, descending again. It gets messy fast.

So the tree is flattened into an **ordered flat list**. Lay the document out in reading order and section splitting becomes list slicing.

### Written naively, the financial statements shatter

Defining a leaf as "an element with no other block inside" feels natural.

```python
# ❌ this alone shatters the financial statements
[el for el in soup.find_all(["div","p","table"]) if el.find(["div","p","table"]) is None]
```

Why this breaks is visible in the real files ([F9](../01-findings.md#f9)). Filings from around 2019 put **a `<div>` in every table cell.** With a `<table>` then containing a `<div>`, the table is no longer a leaf, and each `<div>` inside a cell becomes one instead.

The result: a single financial statement holding three years of revenue scatters into dozens of fragments — "2024", "26,974", "2023", "26,974"… The fact that it was a table disappears, and so does which number belongs to which year.

So consume every `<table>` whole instead? That fails too. Intel filings sometimes wrap an entire page in a table. Swallowing it whole eats the section headings inside, and the document looks as if it has no headings at all.

### So tables are split into two kinds

| Table kind | Detection | Treatment |
|---|---|---|
| Data table | High numeric-cell density **and no long cells** | The table itself is one block, preserving structure |
| Layout table | Contains a long cell (`LAYOUT_CELL_CHARS`(three hundred chars) or more) | Inner elements become blocks because they contain body text and headings |

A block judged a data table keeps its source HTML verbatim in `Block.html`. **The next chapter, M1.2, takes that HTML and converts it to a markdown table.** Fragment the table now and M1.2 has no way to recover it, which makes this judgment a contract spanning two modules.

### Condition order creates bugs

In `_is_data_table()`, "reject immediately if any cell is long" comes **before** the numeric-density calculation. What happens if you swap them?

Intel's infographic tables become the problem. They hold many numbers, so density alone classifies them as data tables. In reality they also contain explanatory paragraphs and section headings. Classify them as data and consume them whole, and those headings disappear.

With the long-cell condition first, such a table is rejected before density is ever computed. **Putting the negative condition first for early rejection** is basic hygiene for this kind of classifier ([B05](../04-bugs.md#b05)).

### Build — Leaf blocks — extract text without shattering tables

#### Target file: `app/ingestion/parser.py`

<!-- src: app/ingestion/parser.py::_is_data_table -->
```python
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
```

**What to look for in the code**

- Density of numeric cells is the only criterion. The presence of `<th>` is ignored, because SEC tables barely use `<th>` at all.
- Condition order matters. A single long prose cell settles the table as layout immediately, before the density calculation is ever reached.
- The threshold is the `max` of a fixed count and a ratio, so small tables are judged by absolute count and large ones by proportion, and neither is swayed by table size.

<!-- src: app/ingestion/parser.py::leaf_blocks -->
```python
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
```

The code builds a set with `id(t)` rather than `data_ids.add(t)`. There is a reason for `data_ids.add(id(t))`. BeautifulSoup's `Tag` may implement `__hash__` differently from the identity we want — "is this the same node in memory." Judging two distinct nodes with identical content to be equal would break nested-table handling. Using `id()` as the key sidesteps that risk entirely.

And one quiet but important fact. **`find_all` preserves document order.** So `out` in the loop above is already in document order without any sort.

Every later stage assumes this. L7's "from this heading to the next" and L8's monotonically advancing title cursor both rest on it. If you ever want to parallelize this loop for speed, breaking that order makes everything beneath it quietly wrong.

### Verify

The CLI arrives in L14, so compare blockification directly against the golden data here. `tests/ingestion/golden.py` contains the `BLOCKS` values for all twenty documents.

```bash
uv run pytest tests/ingestion/test_01_blocks.py -v
```

**Required checks**

| Check | Why |
|---|---|
| **No file has zero table blocks** | Zero indicates [F9](../01-findings.md#f9): the table fragmented into individual cells |
| AMD-FY2019, NVDA-FY2020, and INTC-FY2019 have 3 to five times more blocks | Expected for legacy files with many wrapper divs |
| INTC has fewer table blocks than document tables (492→18) | Expected because most are layout tables whose contents are traversed |

**If it is wrong** — 0 table blocks points to the long-cell or numeric-density conditions in `_is_data_table`. An abnormally low block count means `leaf_blocks` is consuming tables whole.

**Pitfalls encountered** — [B04](../04-bugs.md#b04), zero tables; and [B05](../04-bugs.md#b05), misclassified infographic tables

---

### Where you are now

Three functions — `normalize`, `_is_data_table`, `leaf_blocks` — have turned a 2 MB HTML blob into a list of leaf elements that preserves document order. Financial statements survive whole as single blocks, layout tables have been unwrapped into their contents, and source coordinates survived normalization.

You still do not know which block is the heading for Item 1A. That is L7's job. Before that, the material for the judgment has to be prepared (L4–L5).

### A block's end coordinate is the next block's start

You have start positions (`source_pos`) but no end positions. Trying to reconstruct closing-tag offsets from BeautifulSoup's normalized tree goes wrong quickly.

There is a simple detour. Because blocks are laid out in document order, **one block's end is the next block's start.** Only the final block needs closing, using the file length. The function below walks the list backwards to fill in those spans. L7 and L8 carry them straight into `Block`, and they end up as M1.3's chunk boundaries.

#### Target file: `app/ingestion/parser.py`

<!-- src: app/ingestion/parser.py::block_source_spans -->
```python
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
```

---

## L4 — Property extraction — "is this block bold?"

Finding headings requires knowing whether text is bold and how large it is. But a 10-K has no semantic tags like `<h1>` ([F1](../01-findings.md#f1)). Everything is a `<div>` and formatting is scattered across inline CSS.

So this layer's job is simple. Take one block and **return every extractable formatting property as a dict**.

### A dict is the right choice here

[L1](01-contracts-normalize.md#l1--data-structures-come-first) argued for dataclasses over dicts, and this is the opposite. That looks contradictory; there is a reason.

This dict is compared with profile JSON **key by key**. If the profile says `{"font_weight": 700}`, the evaluator pulls `props["font_weight"]` and compares. In other words, **the data names the keys, not the code.**

So supporting a property like `padding_top` later means one change in one place: add a line to the dict below and leave `matches_rule` in [L5](03-rules.md#l5--rule-evaluator--the-only-point-where-code-meets-data) untouched. A dataclass would require editing **two** places — field declaration and extraction logic — which breaks the premise that rules are data.

The boundary, then: **use a dataclass when code knows the names, and a dict when data defines them.**

> ⚠ One misconception is worth naming. "So I can just add it to the profile JSON and it works without code changes" is **false**. If `block_props` does not create the key, `matches_rule` sees `props.get(key) is None` and **silently skips the constraint**. Adding `padding_top` to a profile without extracting it here does nothing, and raises no error. The price of that silence is revisited in [L5](03-rules.md#l5--rule-evaluator--the-only-point-where-code-meets-data).

### Normalize as low in the stack as possible

In CSS, bold is written both as `font-weight: bold` and `font-weight: 700`. Same meaning, different strings.

Normalize to 700 here and every layer above compares a single number. Carry the difference upward instead and every rule author has to remember "did I handle bold too?" **Absorb representational differences as low as possible.**

Style also frequently lives on an inner `<span>` rather than the element itself. `_inline_css` combines the element's own style with up to two nested spans.

### A fair use of the walrus operator

The code contains `(m := re.search(...))` — store the match and use it as the condition at once. Without it the assignment needs its own line and cannot sit inside a dict literal. Overuse hurts readability, but a short conditional expression like this is a fair place for it.

### Build — Visual properties — what makes something look like a heading

#### Target file: `app/ingestion/parser.py`

<!-- src: app/ingestion/parser.py::_inline_css -->
```python
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
```

**What to look for in the code**

- The element's own `style` is merged with up to two nested `span` styles. SEC HTML routinely puts the weight on an inner span rather than the element, so looking at the element alone misses headings entirely.
- `limit=2` is the cap. Going deeper mixes in styles from unrelated descendants and blurs the judgment, and it adds the cost of walking deep into the tree for every block.
- The `isinstance(..., str)` check appears twice. BeautifulSoup attributes are not guaranteed to be strings, and without the guard this raises a type error in rare cases.

<!-- src: app/ingestion/parser.py::block_props -->
```python
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
```

**What to look for in the code**

- The single line turning `bold` into 700 is the point of this function. CSS writes the same weight as either `bold` or `700`, and unifying it here lets every layer above compare one number.
- The default when no style exists is `400`, the CSS default weight. Defaulting to zero instead would drop every block below the rules' minimum threshold.
- The key names exist only in this dictionary. Profile JSON writes rules under the same names and `matches_rule` looks them up by those names, so a key missing here does nothing even when a profile names it.
- `in_table` is position, not style. Carrying formatting and structural properties in one dictionary is what keeps the rules simple.

### Verify

```bash
uv run pytest tests/ingestion/test_02_rules.py -k "bold_keyword or missing_style or inline_css" -v
```

This runs without the corpus. It separately verifies `bold` → 700 normalization, a default of 400 when style is absent, and discovery of style inside a span.

## What you should be able to explain now

- **What happens to the financial statements if data and layout tables are not separated?**
  - **Answer:** Walking into data tables fragments statements into isolated cells and destroys their row-column meaning; keeping layout tables whole can swallow body headings. Separating them preserves financial tables for M1.2 while exposing layout contents to the parser.
- **What damage appears silently when `leaf_blocks` reorders its conditions?**
  - **Answer:** If numeric density is allowed to win before the long-prose rejection, infographic and layout tables are misclassified as data. They are then consumed whole, silently removing the headings and paragraphs inside them.
- **What justifies treating a block's end coordinate as the next block's start?**
  - **Answer:** Blocks are emitted in source order, while closing-tag offsets cannot be reconstructed reliably from BeautifulSoup's normalized tree. The next start therefore gives a deterministic non-overlapping half-open span; only the last block needs the source length.
- **L1 argued against dicts — why is `block_props` a dict?**
  - **Answer:** Here profile data names the keys dynamically and the evaluator compares them key by key. A dict lets a new extracted property work without changing the evaluator, whereas dataclasses are better when code owns a fixed field set.
- **What happens when a profile names a key that `block_props` never extracts?**
  - **Answer:** `props.get(key)` returns `None`, and the evaluator silently skips that constraint. The rule therefore has no effect, which is why profile keys eventually need validation against an allow-list.

---

[← Previous: Contracts and normalization](01-contracts-normalize.md) · [Module overview](../03-build.md) · [Next: Rule evaluator →](03-rules.md)
