# M1.1 Tutorial 7 — Persist what was learned, catch failure that looks perfect

L11 carries learned rules forward to the next run; L12 checks whether the result is actually right.

L12 is the most underrated layer in the module, because **a parse can be structurally perfect and still wrong**. Mistake the table of contents for body headings and the Item count, the ordering, and the absence of duplicates all pass. What catches that failure is decided here.

**Prerequisite:** Tutorial 6's `uv run pytest tests/ingestion/test_03_segment.py -k "detect or toc_detector" -v` passes.

## What to write and where to implement it yourself

| Stretch | Learning action | What to take away |
|---|---|---|
| L11 `PROFILES`, `load_profile` | **Write the model declarations** | how schema design decides code complexity |
| L11 `save_profile` | **Implement** the write condition | why only successful profiles are kept |
| L12 `CORE_ITEMS`, `_validate_xref` | **Confirm the design decision** | the basis for deciding what counts as required |
| L12 `validate` | **Implement** the validation rules | the signal that catches structurally perfect failure |

---

## L11 — Profile I/O — schema design decides code complexity

Learned rules are stored in a per-company JSON file. The schema looks like this.

```json
{
  "ticker": "AMD",
  "default_year": "2024",
  "profiles": {
    "2019": { "segmentation": {...}, "validation": {...} },
    "2024": { "segmentation": {...}, "validation": {...} }
  }
}
```

Each year holds a **complete** profile. That is a lot of duplication — AMD's 2020 through 2024 profiles are nearly identical.

### The trap of removing duplication

The natural improvement is a `default` profile with per-year overrides. Duplication disappears and the file shrinks.

But loading then requires a **merge**. And merges have no single right answer.

If `rules` is a list with two entries in default and one in the year, what happens? Concatenate, or replace? What about `validation.must_have`? A merge policy has to be decided per field, documented, and tested.

The current structure has none of that. Loading is three lines: use the year's profile if present, otherwise the one at `default_year`. Done.

**Schema design directly determines code complexity.** It is a trade — remove duplication in the data and policy enters the code — and here duplication won.

### Why year keys are strings

Years are string keys, as in `data["profiles"]["2024"]`, because JSON object keys can only be strings.

The hazard is that `json.dumps({2024: ...})` in Python does not error; it **silently converts to `{"2024": ...}`**. So you save with an int, load a str, and `profiles[year]` raises `KeyError`. It looks fine at write time and blows up on the next run.

Normalizing to `str(year)` from the start closes that path.

### Build — Profile persistence — carrying what was learned forward

#### Target file: `app/ingestion/parser.py`

<!-- src: app/ingestion/parser.py::PROFILES,load_profile -->
```python
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
```

**What to look for in the code**

- The fallback has two steps: requested year, then default year, then `None`. That final `None` is the signal to learn from scratch.
- Having no merge policy is the design. Because each year's profile is self-contained, the question of which fields to combine never arises.
- A missing file returns `None` rather than raising. A first run is a normal path, not an error.

<!-- src: app/ingestion/parser.py::save_profile -->
```python
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
```

The line `data["default_year"] = max(...)` carries a judgment: **the default is always the most recent year.**

At first "the first year learned" seems natural. That breaks AMD. Only AMD FY2019 has headings inside a table ([F4](../01-findings.md#f4)), and processing the corpus in year order makes FY2019 the first learned. **The exception becomes the default.**

The case for latest-as-default is simple. Document layouts evolve forward. A newly arrived filing is more likely to resemble last year's than one from five years ago.

> **There is a cost: convergence takes three passes, not two.** `expected_items` differs per year, and an older year without its own profile is validated against the latest year's expected count. It naturally fails and relearns once. Self-healing, but not idempotent. Details in [04-bugs.md](../04-bugs.md#profile-convergence-takes-three-passes-not-two).

### Verify

```bash
uv run pytest tests/ingestion/test_05_profile.py -v
```

The first seven tests run without the corpus. They separately check saving and loading round trips, year key string conversion, `default_year` updates, and per-year self-containment.

| Check | Why |
|---|---|
| **Only some years have entries, not all** | A year that validates with a prior profile does not create a new one |
| **INTC has one entry** | `xref` has no `expected_items`, so all five years pass |
| `default_year` is the **latest** year | Fixing it to the first year would give AMD the FY2019 rule as its default |

---

## L12 — Validation — fallback only works if failure is detectable

This parser has a self-healing path. If a saved profile produces a strange result, it relearns the rules from that file and retries.

That structure rests on one premise: **you have to be able to tell the result is strange.** Not knowing it is wrong means never getting the chance to relearn. The core of graceful degradation is not the fallback path but **failure detection**.

### Structurally perfect failure

The incident mentioned twice, in L1 and L8, is faced head-on here.

Mistake the table of contents for headings and the validation metrics come out like this.

| Check | Result |
|---|---|
| Item count | 23 ✓ |
| Item order | SEC canonical order ✓ |
| Duplicates | none ✓ |
| Core Items (1, 1A, 7, 8) | all present ✓ |

**Everything passes.** A TOC lists the Items in order, without duplicates, with none missing. Structurally it is a perfect parse.

Only one thing differs: the sections have **no content.** All 21 sections had blocks=2 ([B10](../04-bugs.md#b10)).

So one more check joins the structural ones. **If two or more core Items have too few blocks, treat it as having captured the TOC.** If Item 1 (Business) and Item 7 (MD&A) come in under 20 blocks, that is not a normal 10-K.

Without that single check the bug would have reached production. **Every pipeline needs at least one check for "structure is right, content is missing."**

### Problems are collected as a list, not raised

Using `raise` stops at the first problem. You learn "the Item count is wrong" and only discover on the next run that the order is wrong too. Debugging becomes a round trip.

Collecting a list puts everything in one log line. And the caller can decide "problems mean relearn" with a single `if problems:`.

### `xref` uses different criteria

`_validate_xref` exists for a reason. In Intel filings, Items being scattered across the document is **normal** ([F7](../01-findings.md#f7)). With Item 7 split across pages 5, 19, and 47, asking "are they in order?" or "are there duplicates?" is meaningless.

Instead it checks **coverage**: is every Item in the index explained by one of three things — assigned body text, no disclosure, or incorporation by reference? Anything unexplained means the parse missed something.

**When data characteristics differ, validation criteria have to differ too.** Force one validation path onto both and one side is permanently chasing ghosts.

### Build — Validation — catching structurally perfect failure

#### Target file: `app/ingestion/parser.py`

<!-- src: app/ingestion/parser.py::CORE_ITEMS,_validate_xref -->
```python
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
```

**What to look for in the code**

- Order and duplicate checks are skipped for xref filings. Items are legitimately scattered across the document, which robs both checks of meaning.
- **Coverage** is checked instead: every indexed Item must be explained by body text, an empty disclosure, or an incorporation by reference.
- Thin sections are judged by **ratio**, not count. A large index produces proportionally more thin sections, so a fixed count would be swayed by document size.

<!-- src: app/ingestion/parser.py::validate -->
```python
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
```

**What to look for in the code**

- Problems are collected and returned rather than raised. Stopping at the first one hides the remaining defects until the next run.
- An empty list means success. The caller decides whether to relearn with a single `if problems`.
- The ordering reference changes only for `custom_title`, because that type's company-defined order differs from the SEC's canonical order.
- The last check is why this function exists. Counts, ordering, and duplicates can all pass while the core Items have no body — which means the table of contents was mistaken for headings. This is where **structurally perfect failure** is caught.

### Verify

```bash
uv run pytest tests/ingestion/test_04_validate.py -v
```

**Deliberately causing failure is essential.** Confirming only that valid input passes does not prove that validation works. `test_validate_catches_a_perfect_structure_with_no_content` constructs "all twenty-three sections have blocks=2."

```bash
uv run python -c "
from app.ingestion.parser import validate, Section
secs = [Section(part='I', item=i, canonical_title='', reported_title='') for i in ('1','1A')]
prof = {'segmentation': {'type':'number'}, 'validation': {'expected_items': 23, 'must_have': ['1','1A','7','8']}}
print(validate(secs, prof))
"
```

→ `['item count 2 != expected 23', 'missing core items: ['7', '8']', 'looks like a contents table (core items with no body): ['1', '1A']']`

**Pitfall encountered** — [B10](../04-bugs.md#b10), structurally perfect failure

### Where you are now

The quality gate is complete. On top of count, order, duplicates, and missing core Items, it catches **structurally perfect failures where every section exists but has no body.** `xref` uses coverage as its different criterion.

All the pieces are now in place. What remains is wiring them in order.

## What you should be able to explain now

- **What does it mean that profile schema design decides code complexity?**
  - **Answer:** Self-contained year entries need only a direct lookup and a default fallback. A deduplicated default-plus-overrides schema moves complexity into field-specific merge policies that must be implemented, documented, and tested.
- **Why are per-year profiles kept as independent entries rather than merged?**
  - **Answer:** Lists and validation fields have no universally correct merge rule, so combining overrides would introduce ambiguous policy into the loader. Accepting some data duplication keeps each profile complete and loading deterministic.
- **Why are only successful profiles written to disk?**
  - **Answer:** Only relearned profiles currently follow this rule: a failed relearn is not persisted, so later runs do not reuse a known-bad update. The bootstrap path is an exception because it writes a newly built profile before its first validation.
- **What does a structurally perfect but wrong parse look like?**
  - **Answer:** Capturing the TOC yields every Item in canonical order with no duplicates or missing core Items, yet each section has only a few blocks. The thin-core-content check exposes that the headings were not from the body.
- **Why are there four kinds of validation signal rather than one?**
  - **Answer:** Full parsing, coverage, SEC Item comparison, and source-position review have different blind spots: crashes, wholesale text loss, missing or false headings, and headings at the wrong source location. No one signal can establish all four properties.

---

[← Previous: Detection and classification](06-detect-classify.md) · [Module overview](../03-build.md) · [Next: Orchestration and CLI →](08-orchestration-cli.md)
