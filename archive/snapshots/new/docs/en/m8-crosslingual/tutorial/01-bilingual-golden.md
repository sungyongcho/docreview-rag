# M8.1 Tutorial 1 — Two languages, one set of answers

You are about to compare Korean retrieval with English retrieval. That comparison is worthless unless the two question sets agree about what the right answer is — and "agree" cannot mean "look similar", because **a metric gap between two suites that differ in more than one field measures nothing you can name.** This document builds the Korean twin suite and the validator that makes the single difference structural.

**Prerequisite:** M1–M7 are complete and `uv run pytest tests/evals -q` passes.

### What to define, what to implement, and what to inspect

| Area | Learning action | What to take away |
|---|---|---|
| `data/golden/retrieval_ko.json` | **Author the twins** | Why a second file, and not a `language` field |
| `TWIN_INVARIANT_FIELDS` | **Write the declaration** | The list is the definition of "differs only in the question" |
| `validate_twin_cases` | **Implement** the pairing rules | Check order is part of the contract |
| `load_bilingual_suites` | **Implement** the two-call load | The loader's verification comes for free, twice |

### 1. The failure that decides the file layout

Start with the obvious design and watch it die. Put the Korean cases in `data/golden/` beside the English ones and load the directory:

```bash
uv run python -c "from app.evals.loader import load_golden_cases; load_golden_cases('data/golden')"
```

`GoldenDataError`, complaining about a duplicate answer-span identity. The loader accepts a directory and merges every `*.json` into one batch, and `_validate_unique_cases` rejects duplicate spans *across cases within one batch*. Twins share every span on purpose. **The loader is not in the way — it is enforcing exactly the rule that makes twins meaningful, and the only way to satisfy it is to stop putting them in one batch.**

A `language` field on the case would dodge the loader and cost more: `GoldenCase` is frozen from M3, `id` still has to match `^m3c-[0-9]{2}$`, and every consumer — scoring, breakdown, curation, the artifact schema — would have to learn about a dimension none of them needs. Two files change nothing and add nothing.

#### Create `data/golden/retrieval_ko.json` — twenty-eight twins

**Learning action — author the twins:** translate the question, copy everything else byte for byte.

```json
{
  "id": "m3c-01",
  "question": "AMD의 매출총이익률은 2018 회계연도에서 2019 회계연도까지 어떻게 변화했습니까?",
  "category": "multi_hop",
  "facet": "comparison",
  "tags": [],
  "answers": [
    {
      "doc_id": "AMD-FY2019",
      "source_sha256": "45e9c96250b900ff5d329b1e76515e4ac1d93ceb5a1c28dccb7fe8a1a0b5be14",
      "start_char": 643376,
      "end_char": 644582
    }
  ],
  "expected_label": "SUPPORTED",
  "reference_answer": "Gross margin increased from 38% to 43%, a rise of 5 percentage points.",
  "note": "Year-over-year percentage comparison in an MD&A table. Korean twin of the EN case.",
  "curation_status": "agent-curated",
  "approval_status": "pending-author-approval",
  "human_verified": false
}
```

The composition matches the English suite exactly: 13 `simple_lookup`, 5 `exact_number`, 6 `multi_hop`, and 4 `absent`. The four absent cases are asked in Korean and keep zero spans, `expected_label="NOT_IN_DOCS"`, and `reference_answer="NOT_IN_DOCS"` — an honest "not in the documents" has to survive translation too.

`reference_answer` stays in English. Retrieval scoring never reads it, and requiring the two files to hold the identical string turns a soft expectation into a checkable invariant.

### 2. The invariant list is the contract

#### Create `app/evals/bilingual.py` — what may not differ

**Learning action — write the declaration:** name every field a retrieval metric could be attributed to, then justify each one.

<!-- src: app/evals/bilingual.py::HANGUL,TWIN_INVARIANT_FIELDS -->
```python
HANGUL = re.compile(r"[가-힣ᄀ-ᇿ㄰-㆏]")

# Every field a retrieval metric could be attributed to. Holding all of them identical
# is what makes an en/ko metric gap a fact about retrieval rather than about the data.
TWIN_INVARIANT_FIELDS = (
    "category",
    "facet",
    "tags",
    "answers",
    "expected_label",
    "reference_answer",
)
```

**What to look for in the code**

- The Hangul pattern is local to this module instead of imported from `app/retrieval/language.py`. That detector is an M8.3 deliverable, and **the suite contract has to hold before any query-path code exists** — a shared helper would make the first checkpoint depend on the third and break the learner's build order.
- `answers` is on the list, and it is the one that matters most: identical spans mean the Korean run and the English run are scored against the same immutable source coordinates.
- `category` and `facet` are on the list because every slice in the report groups by them. A twin filed under a different category would move a category average without any retrieval changing.

#### Extend `app/evals/bilingual.py` — the suite value object

<!-- src: app/evals/bilingual.py::BilingualSuite -->
```python
@dataclass(frozen=True, slots=True)
class BilingualSuite:
    """One English suite and its validated Korean twin, in shared case-id order."""

    en: tuple[GoldenCase, ...]
    ko: tuple[GoldenCase, ...]

    def pairs(self) -> tuple[tuple[GoldenCase, GoldenCase], ...]:
        """Return ``(en, ko)`` case pairs ordered by their shared id."""
        by_id = {case.id: case for case in self.ko}
        return tuple((case, by_id[case.id]) for case in self.en)

    def cases(self, language: str) -> tuple[GoldenCase, ...]:
        """Return the suite for one language, so a run can name its slice."""
        if language == "en":
            return self.en
        if language == "ko":
            return self.ko
        raise ValueError(f"unsupported suite language: {language}")
```

**What to look for in the code**

- `cases(language)` returns a plain tuple of `GoldenCase`, which is exactly what `evaluate_retriever` already takes. **A language run is not a new kind of evaluation; it is the same evaluation over a different slice.**
- `pairs()` exists for the diagnostics in the next chapter, which need the two questions side by side without a corpus.

### 3. Check order is part of the contract

#### Extend `app/evals/bilingual.py` — the validator

**Learning action — implement the pairing rules:** write the checks, then break each one deliberately and read the message you get.

<!-- src: app/evals/bilingual.py::validate_twin_cases -->
```python
def validate_twin_cases(
    en_cases: Sequence[GoldenCase],
    ko_cases: Sequence[GoldenCase],
) -> tuple[tuple[GoldenCase, GoldenCase], ...]:
    """Validate that two suites differ in exactly one field, and return the pairs.

    Twin cases share their ids, their taxonomy, and — decisively — their answer spans,
    so a Korean run and an English run are scored against the same immutable source
    coordinates. That is the whole reason the parity number means anything: if the
    suites could drift, a ko/en gap would be ambiguous between "retrieval is worse in
    Korean" and "the Korean cases ask something easier".

    ``reference_answer`` stays English on both sides. Retrieval scoring never reads it,
    and requiring identity makes the invariant checkable instead of approximate.

    The two suites must live in separate files. ``load_golden_cases`` rejects duplicate
    answer-span identities inside one loaded batch, and twins share every span by
    design, so loading a directory that holds both raises before this validator runs.
    """
    if not en_cases or not ko_cases:
        raise TwinCaseError("both twin suites must be nonempty")

    en_index = {case.id: case for case in en_cases}
    ko_index = {case.id: case for case in ko_cases}
    if len(en_index) != len(en_cases) or len(ko_index) != len(ko_cases):
        raise TwinCaseError("twin suites must not repeat a case id")
    if set(en_index) != set(ko_index):
        missing = sorted(set(en_index) ^ set(ko_index))
        raise TwinCaseError(f"twin suites do not cover the same cases: {', '.join(missing)}")

    pairs: list[tuple[GoldenCase, GoldenCase]] = []
    for case_id in sorted(en_index):
        english = en_index[case_id]
        korean = ko_index[case_id]
        for field in TWIN_INVARIANT_FIELDS:
            if getattr(english, field) != getattr(korean, field):
                raise TwinCaseError(f"{case_id} twins disagree about {field}")
        # Checked before the script rules: a copied-across question is the likely
        # authoring slip, and reporting it as "no Hangul" would name the symptom.
        if _normalized(english.question) == _normalized(korean.question):
            raise TwinCaseError(f"{case_id} twins share one untranslated question")
        if HANGUL.search(english.question) is not None:
            raise TwinCaseError(f"{case_id} English question contains Hangul")
        if HANGUL.search(korean.question) is None:
            raise TwinCaseError(f"{case_id} Korean question contains no Hangul")
        pairs.append((english, korean))
    return tuple(pairs)
```

**What to look for in the code**

- The untranslated check runs before the Hangul checks, and that ordering is load-bearing. Paste an English question into a Korean case and both rules fail; only one of them names the cause. **A validator that reports the second-order consequence sends the reader looking for an encoding bug in a case that was simply never translated.**
- Every failure raises. Nothing is skipped, repaired, or normalized — the same posture the M3 loader takes, for the same reason.
- The error messages carry the case id, because the first thing you do with a twin failure is open that one case in both files.

### 4. Two loads, full verification, twice

#### Extend `app/evals/bilingual.py` — the entry point

<!-- src: app/evals/bilingual.py::load_bilingual_suites -->
```python
def load_bilingual_suites(
    en_path: str | Path = DEFAULT_GOLDEN_PATH,
    ko_path: str | Path = KO_GOLDEN_PATH,
    *,
    manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
) -> BilingualSuite:
    """Load both suites through the unmodified loader and validate them as twins.

    Two separate ``load_golden_cases`` calls, not one directory load: each file gets
    the loader's full SHA-256 and span-source verification, and the Korean file is
    bound to the same raw filings as the English one, for free.
    """
    en_cases = load_golden_cases(en_path, manifest_path=manifest_path)
    ko_cases = load_golden_cases(ko_path, manifest_path=manifest_path)
    validate_twin_cases(en_cases, ko_cases)
    order = sorted(en_cases, key=lambda case: case.id)
    ko_index = {case.id: case for case in ko_cases}
    return BilingualSuite(
        en=tuple(order),
        ko=tuple(ko_index[case.id] for case in order),
    )
```

**What to look for in the code**

- Not one line of `app/evals/loader.py` changes. **The constraint that forced two files is the same constraint that makes both files verified against the corpus manifest and the raw filing hashes.**
- Both suites come back in the same case-id order, so `pairs()` and every later join are positional rather than lucky.

### Focused tests and the contract they keep

```bash
uv run pytest tests/crosslingual/test_01_bilingual.py -q
```

Expected: `13 passed`.

| What the test breaks | Contract it protects |
|---|---|
| A Korean case pointing at a different span | Twins are scored against one set of source coordinates |
| A Korean question copied from the English one | The untranslated check fires first, by name |
| A Korean question with no Hangul | Both script rules hold, in both directions |
| A missing or extra case id | The two suites cover the same questions |
| A different `category` or `reference_answer` | Every field a metric could be attributed to stays identical |

### What you should be able to explain now

The answers are in the **bold key sentences** above.

- **Why is the Korean suite a separate file rather than a field on the case?**
  - **Answer:** The loader rejects duplicate answer-span identities inside one batch, and twins share every span by design — the rule that blocks the merge is the same rule that makes twins comparable.
- **Why does `validate_twin_cases` check for an identical question before checking for Hangul?**
  - **Answer:** Both rules fail on an untranslated copy, and only the first one names the cause instead of the symptom.
- **Why does `bilingual.py` carry its own Hangul pattern?**
  - **Answer:** The suite contract must hold before any query-path code exists; importing the M8.3 detector would make checkpoint one depend on checkpoint three.

---

[Module overview](../03-build.md) · [Next: measuring the collapse →](02-measuring-the-collapse.md)
