# M1.1 Tutorial 3 — Handle per-company differences as data, not code

Every company formats headings differently. That problem is solved with a **profile JSON plus one evaluator** rather than per-company branches. L5 is that evaluator.

L6 is a different kind of layer. It was built and then left out of the final rules. It stays in the tutorial as the record of a hypothesis that measurement rejected.

**Prerequisite:** Tutorial 2's `uv run pytest tests/ingestion/test_01_blocks.py -v` passes in full.

## What to write and where to implement it yourself

| Stretch | Learning action | What to take away |
|---|---|---|
| L5 convention table | **Confirm the design decision** | letting rule authors skip reading the evaluator source |
| L5 `matches_rule`, `matches_any` | **Implement** the match rules | why `in_table` is asymmetric |
| L6 `body_after` | **Write the structure** | why a built-but-unadopted layer stays in the record |

---

## L5 — Rule evaluator — the only point where code meets data

In this project, "every company formats differently" is expressed as data, not code. There is no NVIDIA branch and no AMD branch. Per-company rules live in profile JSON and a single evaluator interprets them.

A profile's `rules` look like this.

```json
"rules": [
  {"font_weight": 700, "font_size": 10.0, "in_table": false}
]
```

It means "weight at least 700, size at least 10pt, outside tables." But that reading is not self-evident. Is `700` exactly 700 or 700-or-more? What about keys that are absent?

### State the contract in prose first

Without it, every rule author has to open the evaluator source.

| Contract | Meaning |
|---|---|
| Omitted key | No constraint |
| Number | **Minimum** (`font_size: 14` rejects values below fourteen points) |
| Boolean or string | Exact match |
| `in_table` | `false` = outside tables only; `true` = no constraint (**asymmetric**) |
| Entire list | A block is a heading if any rule passes |

Numbers mean "at least" for a reason that returns in L9. Learning produces **the loosest rule that covers every observation**, so using the minimum as the threshold is the natural fit.

The `in_table` asymmetry will look wrong right now. It is explained after the code.

### Build

#### Target file: `app/ingestion/parser.py`

<!-- src: app/ingestion/parser.py::matches_rule,matches_any -->
```python
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
```

**What to look for in the code**

- The single `actual is None` guard with its `continue` implements the "an unspecified key adds no constraint" convention. It also silently skips any key a profile names that `block_props` never extracts.
- The `in_table` branch comes before the others. It is the only asymmetric key, so it cannot ride the general comparison rule.
- The boolean check precedes the numeric one. In Python `True` is a subclass of `int`, so reversing the order lets booleans leak into a numeric comparison.
- `matches_any` ORs the rule list together: passing one rule is enough to be a heading.

### The Python trap you are most likely to hit

In the code, the `isinstance(expected, bool)` check comes **before** the numeric check. What if you swap them?

In Python, `bool` is a subclass of `int`. That is, **`isinstance(True, int)` is `True`.** So with the numeric check first, `in_table: true` is read as "is it at least 1?" and `in_table: false` as "is it at least 0?" — the latter is **always true**.

The effect is that the "outside tables only" constraint vanishes entirely and every Item entry in the table of contents is captured as a heading. This bug really happened ([B12](../04-bugs.md#b12)). It is easier to hit than it looks, because a JSON `true` naturally becomes a Python `True`.

### Why `in_table` is asymmetric

The point deferred above. Of 20 files, **only AMD FY2019** puts headings inside a table ([F4](../01-findings.md#f4)).

That tempts you to read `in_table: true` as "must be inside a table." Do that and the rule learned from AMD FY2019 fits no other year at all — AMD FY2020's headings are outside tables.

So `true` means "no constraint." Only one direction of constraint is actually needed: the `false` side, meaning "inside tables is probably the TOC, so exclude it."

It is not symmetric and it is not pretty, but when measurement demands it, measurement wins. The exception is written in bold in the contract table so the next reader is not confused. **Measurement outranks elegance, and the exception is documented.**

### The price of tolerance

When `props.get(key)` is `None`, that key is skipped. A profile typo such as `font_wieght` will not crash the program.

That looks tolerant. Inverted, it means **the typo is never caught**. You can change a rule, see no effect at all, and spend a long time confused before noticing the key name was wrong.

The better design validates against an allow-list **when the profile is saved**. Only one learning function creates rules, so a single place would do. This project has not done it — a debt taken knowingly.

### Verify

```bash
uv run pytest tests/ingestion/test_02_rules.py -v
```

This completes in 0 point one seconds without the corpus. Each of the five contract rules has its own test.

**Pitfall encountered** — [B12](../04-bugs.md#b12), `bool` is a subclass of `int`

### Where you are now

Given a block and a rule list, the code can answer "is this a heading?" What matters is that the evaluator **has no idea which strategy produced those rules.** Rules are just dicts, and the evaluator interprets them per the contract.

That ignorance is the design. It means supporting a new company or format never touches the evaluator; only the profile JSON grows.

The open question is who creates the rules — that is L9's learning function. Before that, L7 puts the rules to work cutting an actual document.

---

## L6 — Context signals — built, and ultimately unused

This layer is best told ending-first. **Nothing built here made it into the final rules.** Why it was kept anyway, and why it went unused, is one of the more instructive passages in this project.

### The original hypothesis

The problem named by [F2](../01-findings.md#f2), [F11](../01-findings.md#f11), and [F12](../01-findings.md#f12) is this: the identical string "RISK FACTORS" appears several times in one document. Once in the table of contents, once in a cross-reference index, once as the real body heading. And **the styling can be identical too.**

If style cannot separate them, context must. For instance: "a heading is followed by a long run of body text, while a TOC entry is followed by the next TOC entry." Measured on the three INTC FY2019 occurrences, the following body text is 1,851 / 41 / 90 characters. Clearly separable.

### Measurement said it was unnecessary

None of the final four profiles carries a context condition ([F13](../01-findings.md#f13)).

```
NVDA / AMD / MU   {font_weight, font_size, in_table}   ← three style keys only
INTC              (no rules at all — xref)
```

For the `number` type, **the number itself turned out to be a strong enough anchor.** Even when "Item 1A" occurs eight times, seven are mid-sentence cross-references that fail `ITEM_RE` at the `^` anchor, and the TOC occurrence sits inside a table and fails `in_table: false`. Exactly one remains.

Context signals therefore stayed **candidate filters during learning, not rule vocabulary**.

> ⚠ More bluntly: **`body_after` is currently called nowhere.** It exists for the `sec_canonical` and `custom_title` learning functions, which are unimplemented ("Designed · not implemented" in [02 specification](../02-spec.md)). Only the definition remains.

### Build — Body start — a hypothesis measurement rejected

#### Target file: `app/ingestion/parser.py`

<!-- src: app/ingestion/parser.py::body_after -->
```python
def body_after(blocks: list[Tag], idx: int, span: int = 8) -> int:
    """Measure following body text to filter learning candidates.

    Measured for the three INTC FY2019 "RISK FACTORS" occurrences: 1,851 after
    the heading, 41 after the TOC entry, and 90 after the index entry.
    """
    return sum(
        len(blocks[j].get_text(" ", strip=True))
        for j in range(idx + 1, min(idx + 1 + span, len(blocks)))
    )
```

The signal "how often does this text appear in the document" is used, though. Not through a function, but directly during body assembly in [L8](05-segment-xref.md#l8--segmentation-b--reading-the-answer-the-document-carries). It removes the page header "Table of Contents", which appears 113 times in one document.

```python
freq = Counter(b.get_text(" ", strip=True) for b in blocks)
```

One line, but it carries an important performance choice. Counting "how often does this text appear" per block, on demand, makes the whole thing O(n²) — 5.7 million comparisons at 2,400 blocks. Building one `Counter` and doing lookups is O(n).

The `texts` list is prebuilt for the same reason. `get_text()` is an expensive tree walk and must not be repeated inside the loop.

### The cost of adding an extension point nobody used

The most valuable lesson in this layer is a failure.

The initial design put `min_body_after`, `max_repeat`, `next_is_table`, and `items` into the rule vocabulary, on the grounds that they would probably be needed. Their usage rate in the final profiles was **zero**.

The problem was not that they went unused — it was that **they cost something.** Every time `matches_rule` evaluated a block it computed `body_after`, which added up to roughly 19,000 `get_text()` calls ([B13](../04-bugs.md#b13)). All of it wasted.

**An extension added because it "might be needed later" imposes cost immediately and may never return value.** Adding it when it is actually needed is usually cheaper.

**Pitfall encountered** — [B13](../04-bugs.md#b13), 19 thousand wasted computations

## What you should be able to explain now

- **What becomes possible when rules are data rather than code?**
  - **Answer:** Company and year differences can be learned and stored as profiles without adding branches to the evaluator. One tested contract can interpret every profile.
- **Why are numeric rules "at least" rather than "exactly equal"?**
  - **Answer:** Learning takes the minimum observed weight or size, producing the loosest threshold that still admits every observed heading. Exact equality would reject valid headings with a stronger style value.
- **Why is `in_table` the only asymmetric key?**
  - **Answer:** `false` must exclude TOC entries inside tables, but `true` means no location constraint so AMD FY2019's in-table headings do not make its learned rule unusable for later outside-table years. Measurement showed that only this one direction needs enforcement.
- **Who has to do what if the conventions are not stated in prose first?**
  - **Answer:** Every profile author must open and reverse-engineer the evaluator to learn how omitted, numeric, exact, and `in_table` values behave. That invites inconsistent rules, so the prose contract is part of the interface.
- **Why does L6 stay in the document after being dropped from the final rules?**
  - **Answer:** It records a measured hypothesis that context signals were unnecessary and exposes the cost of a speculative extension point. Keeping that evidence helps prevent the same unused, expensive rule vocabulary from being reintroduced.

---

[← Previous: Blocks and properties](02-blocks-props.md) · [Module overview](../03-build.md) · [Next: Heading segmentation →](04-segment-heading.md)
