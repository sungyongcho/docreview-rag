# M3.1 Tutorial 2 — Reading the answer file so it can be trusted

Tutorial 1 defined what a valid case **is**. `GoldenCase` validates everything visible inside one JSON entry — its shape and its internal consistency, down to the label-versus-answers contradictions. What it cannot do is prove that a case tells the truth about the corpus. A case can validate perfectly and still cite bytes that do not exist.

The same question appears twice. Coordinates point at a filing that is not in the corpus. A hash is written down but the file changed in the meantime. A span runs past the end of the document. A span contains only HTML tags with no human-readable text inside it.

Pydantic catches none of these, because every one is invisible **when looking at a single entry** — they live in the relationships between a case and its neighbors, the manifest, and the raw filing on disk. If no layer checks those relationships, evaluation still runs and still prints numbers; the broken cases simply score as retrieval failures forever, and the scoreboard blames the retriever for what is a data fault. Catching them is this file's job, and it compresses into one testable invariant: **every case that `load_golden_cases` returns has been byte-verified against the exact corpus snapshot it cites — on every load, with no cached trust.**

**Prerequisite:** Tutorial 1's `app/evals/types.py` is written. Its focused test starts passing at the end of this document, once the package API opens.

### What the loader refuses

`data/golden/retrieval.json` → strict `GoldenCase` parsing → manifest lookup → source-byte SHA-256 verification → UTF-8 half-open span validation → immutable in-memory cases.

The loader rejects unknown fields, coercion, duplicate keys, duplicate IDs or normalized questions, wrong hashes, out-of-bounds spans, and invisible evidence. Source bytes are hashed **before UTF-8 decoding** so the coordinate system cannot drift.

That last sentence is subtle. Hashing the decoded string lets the same document produce different hashes depending on how encoding was handled. Hashing bytes names exactly one file.

`data/golden/retrieval.json` itself has a history worth knowing before trusting it. The golden curation stage produced it: an agent drafted the 28 cases against the immutable corpus, machine checks verified structure and source integrity, and the whole set was committed with `human_verified` false — every case pending author approval. The review queue that records this state, and the checklist that moves a case out of it, is `data/golden/REVIEW.md`; only the author flips approval status, in a reviewed change. The loader treats both states identically: validation runs on every load, approved or not.

### What to define, what to implement, and what to inspect

`app/evals/loader.py` is built in six steps, then the package surface opens.

| Area | Learning action | What to take away |
|---|---|---|
| Module header and path constants | **Define the structure** | Defaults live in code and callers may override them |
| `GoldenDataError` | **Review the design decision** | Why data faults collapse into one exception |
| JSON reading and duplicate-key rejection | **Implement** the parsing guard yourself | What the standard JSON parser silently discards |
| Cross-case uniqueness | **Implement** the batch invariants yourself | Faults invisible in a single entry |
| Manifest lookup | **Write the field mapping, then inspect boundary conversions** | Where ground truth meets the real corpus |
| Source verification | **Implement** the core validation yourself | Three gates: hash, range, visibility |

### 1. Module header and default paths

#### Create `app/evals/loader.py` — module header

**Learning action — define the structure:** note why `BeautifulSoup` is among the imports.

```python
"""Load strict golden cases and bind every positive span to the raw corpus."""

from __future__ import annotations

from collections.abc import Iterable
import hashlib
import json
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup
from pydantic import TypeAdapter, ValidationError

from app.evals.types import GoldenCase
```

#### Extend `app/evals/loader.py` — path constants and the data error

**Learning action — review the design decision:** four constants and one exception. Work out why the exception inherits from `ValueError`.

<!-- src: app/evals/loader.py::REPO_ROOT,GoldenDataError -->
```python
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GOLDEN_PATH = REPO_ROOT / "data" / "golden" / "retrieval.json"
DEFAULT_MANIFEST_PATH = REPO_ROOT / "data" / "corpus" / "manifest.json"
GOLDEN_CASES = TypeAdapter(list[GoldenCase])


class GoldenDataError(ValueError):
    """A golden file or its cited source snapshot violates the M3 contract."""
```

**What to look for in the code**

- `REPO_ROOT` is computed from `__file__`. Whatever directory evaluation runs in, the default paths point at the same place.
- `GOLDEN_CASES = TypeAdapter(list[GoldenCase])` is built once at module level. Building a `TypeAdapter` compiles a schema, so rebuilding it per file would be waste.
- `GoldenDataError` inherits from `ValueError`. A caller who knows nothing about this module can still catch it as a `ValueError`, while code that cares can filter data faults alone.

> **Concept — one error surface for data faults**
>
> The loader can refuse a file for a dozen reasons: unreadable bytes, broken JSON, a duplicate key, a failed pydantic validation, a missing filing, a wrong hash. A caller does not care which library detected the problem — it cares about one question: is the data bad, or is the code broken? Collapsing every data fault into GoldenDataError answers that question with a single except clause.
>
> This is also why the entry point wraps pydantic's ValidationError instead of letting it escape. An escaping ValidationError leaks an implementation choice into every caller: the evaluation CLI and the tests would have to import pydantic just to catch it, and swapping the validation library would break them all. Wrapped with the original exception chained as the cause, the detail stays readable in the traceback while the public type stays this module's own.
>
> The rejected alternative — a hierarchy of one exception class per fault kind — would buy nothing here. No caller recovers differently from a wrong hash than from a duplicate key; both mean stop and fix the data by hand. One type whose message names the file and the case is exactly the granularity that repair needs.

### 2. What the standard JSON parser silently discards

`json.loads` does not treat duplicate keys as an error. Give it `{"id": "m3c-01", "id": "m3c-02"}` and it **keeps the last one and drops the rest silently.** Watch it happen:

```bash
python3 -c "import json; print(json.loads('{\"id\": \"m3c-01\", \"id\": \"m3c-02\"}'))"
```

The output is `{'id': 'm3c-02'}`. No warning, no error — the first pair is simply gone, and the resulting dictionary carries no trace that it ever existed.

> **Concept — duplicate keys are legal JSON, and that is the problem**
>
> The JSON specification only says object names should be unique — should, not must. A conforming parser may reject duplicates, keep the first, or keep the last; Python keeps the last, silently. So this is not a parser bug to route around: it is permitted behavior that has to be guarded against at the only moment the information still exists.
>
> That moment is before the pairs are merged into a dictionary. The pairs hook receives the raw key-value list exactly as parsed. Once the merge happens, both duplicates have collapsed into one slot, and no downstream validation — not pydantic, not the uniqueness checks — can ever detect that a value was overwritten.
>
> The realistic accident is not a duplicated id. It is hand-editing a span: copy an end-offset line while adjusting coordinates, forget to delete the old one, and the parser silently keeps whichever came last. The field you thought you fixed is gone, the case still validates, and evaluation scores against the wrong span without a word.

In an answer file that silence is fatal: a file that quietly lost fields or cases still loads, evaluation still prints plausible numbers, and nothing marks them as measured against less than the intended suite.

#### Extend `app/evals/loader.py` — the JSON reading guard

**Learning action — implement the parsing guard:** check what `object_pairs_hook` receives, then implement it yourself.

<!-- src: app/evals/loader.py::_reject_duplicate_keys,_golden_files -->
```python
def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise GoldenDataError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _read_json(path: Path) -> object:
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except GoldenDataError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GoldenDataError(f"cannot read valid UTF-8 JSON from {path}: {exc}") from exc


def _golden_files(path: Path) -> list[Path]:
    if path.is_dir():
        files = sorted(path.glob("*.json"))
        if not files:
            raise GoldenDataError(f"no golden JSON files found in {path}")
        return files
    return [path]
```

**What to look for in the code**

- `object_pairs_hook=_reject_duplicate_keys` receives the pair list **before** it is merged into a dictionary. That is what makes duplicates visible. After parsing it is too late.
- `except GoldenDataError: raise` comes first. Without it, our own exception raised inside the hook would be caught below and rewritten as an unrelated "cannot read JSON" message.
- `_golden_files` accepts a directory too. Answers may be split across files, but an empty directory is rejected — that stops evaluation from passing with zero cases. The listing is also sorted deliberately: glob order is filesystem-dependent, so sorting keeps the case order — and the first error a broken directory reports — identical on every machine.

### 3. Faults invisible in a single entry

#### Extend `app/evals/loader.py` — cross-case uniqueness

**Learning action — implement the batch invariants:** implement it while checking why each of the three sets is tracked.

<!-- src: app/evals/loader.py::_validate_unique_cases -->
```python
def _validate_unique_cases(cases: Iterable[GoldenCase]) -> None:
    ids: set[str] = set()
    questions: set[str] = set()
    answer_identities: set[tuple[str, str, int, int]] = set()
    for case in cases:
        if case.id in ids:
            raise GoldenDataError(f"duplicate golden case id: {case.id}")
        ids.add(case.id)

        normalized = " ".join(case.question.casefold().split())
        if normalized in questions:
            raise GoldenDataError(f"duplicate normalized question: {case.question}")
        questions.add(normalized)

        for answer in case.answers:
            identity = (
                answer.doc_id,
                answer.source_sha256,
                answer.start_char,
                answer.end_char,
            )
            if identity in answer_identities:
                raise GoldenDataError(f"duplicate answer span identity in {case.id}")
            answer_identities.add(identity)
```

**What to look for in the code**

- Questions are compared normalized as `" ".join(case.question.casefold().split())`, not raw. Two questions differing only in case and whitespace are the same question, and counting both double-weights that topic in the evaluation.
- Answer-span uniqueness is checked **across cases**. The validator inside `GoldenCase` only sees duplicates within one case. If two different cases use the same span as ground truth, the score rises merely because that span is easy.
- The exception messages name the offending case. To a person hunting through 28 cases, that is the whole message.

> **Concept — what a near-duplicate question does to the average**
>
> The metrics this suite later reports are macro-averages: every case casts one equal vote, and the suite's verdict is the mean of those votes. Two questions differing only in capitalization or spacing are one fact wearing two IDs. Leave both in and that single fact votes twice — whatever the retriever does on it, success or failure, is counted double while every other fact counts once. The average stops describing the corpus and starts describing the accident of duplication.
>
> Casefold plus whitespace collapse is deliberately the entire normalization. It catches the duplicates plain string equality misses — a retyped question with one capital changed, a doubled space — while never merging two genuinely different questions, which stemming or punctuation stripping could. A dedup that can false-merge silently deletes a real case; this one cannot.
>
> The macro-average itself, and the metric resolution it implies, belongs to the scoring tutorial.

### 4. Where ground truth meets the real corpus

The other side of the binding is `data/corpus/manifest.json`. That file was written once, by the M1 EDGAR download step, at the moment the 20 filings were fetched — one entry per filing, recording ticker, dates, accession number, local file path, and source URL. It is the corpus's birth certificate: nothing regenerates it, and the filings it names are treated as immutable from that point on. The loader reads it for exactly one purpose — turning the `doc_id` written in a golden case into the path of the file those coordinates were measured against.

#### Extend `app/evals/loader.py` — manifest lookup

**Learning action — write the field mapping, then inspect boundary conversions:** note the search order in `_resolve_source_path` and the `doc_id` assembly rule.

<!-- src: app/evals/loader.py::_resolve_source_path,_manifest_sources -->
```python
def _resolve_source_path(file_name: str, manifest_path: Path) -> Path:
    source = Path(file_name)
    if source.is_absolute() and source.is_file():
        return source

    bases = [Path.cwd(), REPO_ROOT, manifest_path.resolve().parent]
    bases.extend(manifest_path.resolve().parents)
    for base in bases:
        candidate = (base / source).resolve()
        if candidate.is_file():
            return candidate
    raise GoldenDataError(f"manifest source file does not exist: {file_name}")


def _manifest_sources(manifest_path: Path) -> dict[str, Path]:
    payload = _read_json(manifest_path)
    if not isinstance(payload, list):
        raise GoldenDataError("corpus manifest root must be a JSON array")

    sources: dict[str, Path] = {}
    for index, entry in enumerate(payload):
        if not isinstance(entry, dict):
            raise GoldenDataError(f"manifest entry {index} must be an object")
        try:
            ticker = entry["ticker"]
            report_date = entry["report_date"]
            file_name = entry["file"]
        except KeyError as exc:
            raise GoldenDataError(f"manifest entry {index} is missing {exc.args[0]}") from exc
        if not all(isinstance(value, str) and value for value in (ticker, report_date, file_name)):
            raise GoldenDataError(f"manifest entry {index} has invalid identity fields")
        if len(report_date) < 4 or not report_date[:4].isdigit():
            raise GoldenDataError(f"manifest entry {index} has an invalid report_date")

        doc_id = f"{ticker}-FY{report_date[:4]}"
        if doc_id in sources:
            raise GoldenDataError(f"duplicate manifest document id: {doc_id}")
        sources[doc_id] = _resolve_source_path(file_name, manifest_path)
    return sources
```

**What to look for in the code**

- `doc_id` is **assembled** as `f"{ticker}-FY{report_date[:4]}"` because the manifest has no `doc_id` field. If this rule drifts from M1.4's, ground truth stops finding its document. Storing a `doc_id` field in the manifest would look simpler, but it would be a second copy of derivable identity — the moment the two copies disagree, every hash check chases the wrong file. One assembly rule applied everywhere cannot disagree with itself.
- `_resolve_source_path` tries several base directories in order. Manifest paths are relative and therefore depend on the working directory; rather than failing quietly, it exhausts the candidates and then refuses.
- A `doc_id` appearing twice in the manifest is rejected. Without that, a later entry would overwrite an earlier one and ground truth would verify against the wrong file.

### 5. Three gates: hash, range, visibility

This is where the invariant from the top of the document is enforced. Each positive answer names a document, a snapshot hash, and two character offsets, and the three gates check in order that this record still describes reality.

> **Concept — the provenance chain from doc id to bytes**
>
> Read the hash gate as a chain of four links: the doc id names a manifest entry, the manifest entry names a file on disk, the file yields bytes, and the SHA-256 of those bytes must equal the hash recorded in the golden case. Every link is checked on every load. If any link breaks — entry missing, file missing, bytes changed — the load refuses loudly instead of proceeding.
>
> The failure this closes is corpus drift. Refetch one filing and get a single byte of difference — a changed header, a re-served template — and every span into that filing is now measured in a coordinate system that no longer exists. Without the hash gate nothing fails: the offsets still index somewhere in the new text, the spans silently point at the wrong characters, retrieval can never match them, and those cases score as unfindable forever. The scoreboard would report a retrieval regression when the truth is a stale citation.
>
> With the gate, the same drift becomes one loud load-time error naming the case and the document. The difference is not whether the problem exists — it is whether it surfaces as a visible data fault or hides as a permanent metric lie.

#### Extend `app/evals/loader.py` — source verification

**Learning action — implement the validation:** implement the three gates in order. You should be able to say how evaluation goes quietly wrong without each one.

<!-- src: app/evals/loader.py::validate_golden_sources -->
```python
def validate_golden_sources(
    cases: Iterable[GoldenCase],
    manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
) -> None:
    """Verify each positive span against its exact UTF-8 source and SHA-256."""
    sources = _manifest_sources(Path(manifest_path))
    cache: dict[str, tuple[str, str]] = {}

    for case in cases:
        for answer in case.answers:
            source_path = sources.get(answer.doc_id)
            if source_path is None:
                raise GoldenDataError(f"{case.id} cites unknown corpus document {answer.doc_id}")
            if answer.doc_id not in cache:
                try:
                    source_bytes = source_path.read_bytes()
                    raw_source = source_bytes.decode("utf-8")
                except (OSError, UnicodeDecodeError) as exc:
                    raise GoldenDataError(
                        f"cannot read UTF-8 source for {answer.doc_id}: {exc}"
                    ) from exc
                cache[answer.doc_id] = (
                    raw_source,
                    hashlib.sha256(source_bytes).hexdigest(),
                )

            raw_source, source_sha256 = cache[answer.doc_id]
            if answer.source_sha256 != source_sha256:
                raise GoldenDataError(f"{case.id} source hash does not match {answer.doc_id}")
            if answer.end_char > len(raw_source):
                raise GoldenDataError(
                    f"{case.id} span ends beyond {answer.doc_id}: "
                    f"{answer.end_char} > {len(raw_source)}"
                )
            evidence = BeautifulSoup(
                raw_source[answer.start_char : answer.end_char],
                "html.parser",
            ).get_text(" ", strip=True)
            if not evidence:
                raise GoldenDataError(
                    f"{case.id} span has no visible source evidence in {answer.doc_id}"
                )
```

**What to look for in the code**

- `cache` computes source text and hash once per document. The committed set's 24 positive cases carry 34 spans across 20 filings, and each filing is 2 to 5 MB of raw HTML — the cache turns what would be 34 read-and-hash passes into exactly 20, one per filing.
- The hash comes from `source_bytes` while the length check uses the decoded `raw_source`. Coordinates are in characters, so length must be measured in characters, while identity must be measured in bytes. **Mixing the two drifts on any document with multibyte characters.**
- The last gate is the subtlest. After `BeautifulSoup` strips tags, an empty result is rejected. That is a span pointing only at whitespace between HTML tags — formally a valid interval, so it passes the first two gates. It stops **ground truth that retrieval could never hit.**

> **Concept — visible evidence, or a citation a human can follow**
>
> The raw sources are HTML, and golden offsets are measured over that raw string — so a character interval can be formally perfect and still land entirely inside markup: inside a tag, across a run of style attributes, in the whitespace between elements. Render such a span the way a reader would see it and nothing remains.
>
> That case is worse than a wrong answer. A reviewer following the citation opens the filing and finds literally nothing to read, so the case can never be approved honestly. And a retriever that indexes visible text has no way to return evidence for it, so the case is unwinnable by construction — a permanent, unexplained zero in every future evaluation.
>
> Stripping the span's tags and asking whether any text survives is the cheapest form of the real question: would a person following this citation see anything at all? An empty answer means the coordinates describe markup, not evidence — and the data, not the retriever, is what is wrong.

### 6. Entry point and public surface

#### Complete `app/evals/loader.py` — the load entry point

**Learning action — define the structure, then inspect call order:** work out why the three stages come in this order.

<!-- src: app/evals/loader.py::load_golden_cases -->
```python
def load_golden_cases(
    path: str | Path = DEFAULT_GOLDEN_PATH,
    *,
    manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
) -> list[GoldenCase]:
    """Load one file or a directory of files and validate all source citations."""
    cases: list[GoldenCase] = []
    for golden_path in _golden_files(Path(path)):
        payload = _read_json(golden_path)
        if not isinstance(payload, list):
            raise GoldenDataError(f"golden file root must be a JSON array: {golden_path}")
        try:
            cases.extend(GOLDEN_CASES.validate_python(payload))
        except ValidationError as exc:
            raise GoldenDataError(f"invalid golden cases in {golden_path}: {exc}") from exc

    _validate_unique_cases(cases)
    validate_golden_sources(cases, manifest_path)
    return cases
```

**What to look for in the code**

- The order is parse, then cross-case uniqueness, then source verification. Source verification is the most expensive (file I/O plus hashing), so the cheap checks filter first.
- Uniqueness runs **after** every file has been read into `cases`. Checking per file would miss duplicates that span files — exactly the duplicates a split answer set produces when a case is copied into a second file and the original is left behind.

Note also what this function does not do: it never caches a verdict. There is no marker file, no validated-at timestamp, no fast path that trusts a previous run — every call re-reads and re-hashes all 20 filings, about 58.5 MB in total. That cost is deliberate. A cached verdict is only as good as the assumption that nothing changed after it was written, and that is precisely the claim this loader exists to prove rather than assume. An evaluation run loads the suite once, so the price is paid once per run.

#### Create `app/evals/__init__.py` — the M3 public API

**Learning action — define the structure:** note what is exported and what is not.

```python
"""Public contracts and loader for the M3 evaluation milestone."""

from app.evals.loader import (
    DEFAULT_GOLDEN_PATH,
    DEFAULT_MANIFEST_PATH,
    GoldenDataError,
    load_golden_cases,
    validate_golden_sources,
)
from app.evals.types import (
    ExpectedLabel,
    GoldenCase,
    GoldenCategory,
    GoldenFacet,
    GoldenSpan,
    GoldenTag,
)

__all__ = [
    "DEFAULT_GOLDEN_PATH",
    "DEFAULT_MANIFEST_PATH",
    "ExpectedLabel",
    "GoldenCase",
    "GoldenCategory",
    "GoldenDataError",
    "GoldenFacet",
    "GoldenSpan",
    "GoldenTag",
    "load_golden_cases",
    "validate_golden_sources",
]
```

Not one underscore-prefixed helper leaves the module. The surface a later module may depend on is exactly this list.

### Focused tests and the contracts they protect

```bash
uv run pytest tests/evals/test_01_contract.py tests/evals/test_02_loader.py -q
```

| Value the test breaks | Contract being protected |
|---|---|
| A duplicate JSON key | A hand-editing overwrite never passes silently. |
| The same question differing only in case | One topic is not double-weighted in evaluation. |
| The same answer span across cases | One easy span does not inflate the score. |
| Changed source bytes | Evaluation never runs with coordinates aimed at another snapshot. |
| A span past the end of the document | Ground truth never points at a position that does not exist. |
| A span holding tags but no text | Ground truth retrieval could never hit stays out of the data. |

Done correctly, the selected tests all pass. The suite holds 28 cases in total: 24 positive and four absent. The positive cases carry 34 answer spans between them, all 20 filings appear in positive evidence, and the ticker balance is exact — six positive cases each for AMD, INTC, MU, and NVDA. Verify the counts against the committed file directly:

```bash
python3 -c "import json; g = json.load(open('data/golden/retrieval.json')); pos = [c for c in g if c['answers']]; spans = [a for c in pos for a in c['answers']]; print(len(g), len(pos), len(g) - len(pos), len({a['doc_id'] for a in spans}), len(spans))"
```

This prints `28 24 4 20 34`. The tests pin the same counts as constants in `tests/evals/golden.py`, so a drive-by edit to the golden file fails the suite before it can skew a metric. Every case is still agent-curated and awaiting author approval — `data/golden/REVIEW.md` records the per-case queue — and no committed span is wider than 2,280 characters, inside the 2,500-character ceiling that record promises.

The bar for moving on is simple: a failing schema, source-hash, range, distribution, or review-provenance assertion — or a skip from a missing canonical symbol — means M3.1 is not complete.

On failure, a hash or bounds failure means checking manifest path resolution before editing data. Hash source bytes before UTF-8 decoding, keep offsets half-open, and do not move a golden span to fit the current chunker.

### What you should be able to explain now

- **What gets missed when an answer file is read without `object_pairs_hook`?**
  - **Answer:** Duplicate JSON keys disappear because the standard parser silently keeps the last value; the hook exposes the original key pairs before that merge.
- **Why are questions normalized before comparison?**
  - **Answer:** Questions that differ only in case or whitespace are logically duplicates and would otherwise double-weight one topic in the evaluation.
- **Why is the hash taken over bytes while the length check uses characters?**
  - **Answer:** File identity must cover the exact bytes, while the stored coordinates count decoded characters; using one unit for both would drift on multibyte text.
- **Which cases survive in the data if tag-only spans are not rejected?**
  - **Answer:** Formally valid coordinate ranges containing only HTML tags or whitespace survive even though retrieval can never return visible evidence for them.
- **Why does source verification come after the uniqueness check?**
  - **Answer:** Uniqueness is a cheap cross-file check, so invalid duplicate data should be rejected before expensive source reads and hashing begin.

---

[← Previous: Golden types](01-golden-types.md) · [Module overview](../03-build.md) · [Next: Scoring →](03-scoring.md)
