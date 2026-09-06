# M1.1 Overview — 10-K HTML → Item Section Parser

> **`zero` branch note:** The complete code below is the pinned reference target — write the canonical files yourself. Live progress: [module plan](../../project/module-plan.md).

> Code: `app/ingestion/parser.py`, `app/ingestion/xref.py` Corpus: NVDA · AMD · INTC · MU × five years = twenty files M1.1 completion criteria: **20/20 parsed successfully, zero warnings** · 309 tests at the time The current full-suite result is maintained in [`docs/00-README.md`](../00-README.md).

## In one sentence

**The SEC defines the "content" of a 10-K (Part/Item), but not its "HTML layout."** The parser therefore manages each company's distinct document structure as a **profile (data)**, while a single `segmentation.type` selects the parsing strategy for deterministic execution.

## Pipeline

```
① 정규화       HTML → 의미 있는 트리
② 블록화       트리 → 순서 있는 블록 리스트
③ 세그멘테이션  블록 리스트 → Item 섹션들      ← 프로파일이 지배하는 유일한 단계
④ 검증         섹션들이 말이 되는가
⑤ 출력         ParsedFiling
```

---

## Reading order

| | Document | What it covers | When to read it |
|---|---|---|---|
| 1 | [01-findings.md](01-findings.md) | **Measured findings F1–F15** | First; every other document relies on this evidence |
| 2 | [02-spec.md](02-spec.md) | **What to build** — contracts, types, schemas, and validation criteria | When you want to understand the design |
| 3 | [03-build.md](03-build.md) | **How to build it** — layers L1–L14 across eight documents | When implementing it yourself |
| 4 | [04-bugs.md](04-bugs.md) | **Debugging history B01–B18** | When something looks wrong or you want to know why it was designed this way |
| 5 | [05-verify.md](05-verify.md) | **Verification** — final checks ①–④ and the pytest mapping | When checking correctness |

### Entry points by goal

| Goal | Start here |
|---|---|
| Implement it yourself from the beginning | Start with tutorial 1 in [03-build.md](03-build.md) and proceed in order |
| Understand the design rationale | [02-spec.md](02-spec.md), then the evidence in [01-findings.md](01-findings.md) |
| Investigate an unexpected result | "Where to look when it is wrong" in section 05 of the [verification guide](05-verify.md), then [04-bugs.md](04-bugs.md) |
| See what is and is not implemented | Section 02, [§9, "Designed · not implemented," in the specification](02-spec.md#9-designed--not-implemented) |

### Rules across documents

- **Measurements live only in [01-findings.md](01-findings.md).** Other documents link to them as `[F9]`.
- **Bug history lives only in [04-bugs.md](04-bugs.md).** Other documents link to it as `[B04]`.
- **Golden values live only in `tests/ingestion/golden.py`.** Tables in the documentation are reading copies.
- **Lecture code comes from the pinned completed reference.** On `zero`, `scripts/check_doc_code.py` populates and compares the code blocks in section 03 of the [build guide](03-build.md) against that reference. Focused tests grade the local rebuild.
- **Thresholds live only in reference constant declarations.** When prose mentions one, write its name and value together, as in `` `LAYOUT_CELL_CHARS`(300chars) ``; the same checker compares the value.

Writing the same fact in two places guarantees that the copies will diverge. This document set grew out of that failure.

`scripts/check_doc_code.py` enforces three rules at once. Because `tests/test_doc_sync.py` runs it under pytest, **documentation drift breaks the test**:

| Check | What it verifies | Can `--fix` repair it? |
|---|---|---|
| Code blocks | Match the pinned-reference symbol selected by `<!-- src: … -->` | ✅ |
| Prose constants | Match the value in `` `NAME`(value) `` to the pinned-reference constant | ✗ A person must review the surrounding sentence |
| Links and anchors | Confirm that linked files and `#앵커` exist | ✗ |

```bash
uv run python scripts/check_doc_code.py         # check all three contracts
uv run python scripts/check_doc_code.py --fix   # refresh blocks from the pinned reference
```

---

## Quick start

```bash
uv sync --group dev

# Run all checks (includes parsing 20 documents, ~50 seconds)
uv run pytest

# Run only corpus-independent checks (~0.2 seconds)
uv run pytest tests/ingestion/test_02_rules.py

# Manual inspection
uv run python -m app.ingestion.parser --sections
uv run python -m app.ingestion.parser --coverage
```

### Development tools

Installed by `uv sync --group dev`:

| Tool | Usage | Purpose |
|---|---|---|
| `pytest` | `uv run pytest` | Tests |
| `pytest-cov` | `uv run pytest --cov=app.ingestion.parser --cov=app.ingestion.xref --cov-report=term-missing tests/ingestion` | Inspect unused branches and CLI boundaries ([why coverage is not 100%](02-spec.md#9-designed--not-implemented)) |
| `ruff` | `uv run ruff check .` / `uv run ruff format .` | Linting and formatting |
| `ipython` | `uv run ipython` | Exploratory REPL |

```bash
# Verify lecture code against the pinned reference
uv run python scripts/check_doc_code.py
uv run python scripts/check_doc_code.py --fix    # refresh blocks from the pinned reference
```

> **The `pyproject.toml` `[tool.ruff]` section configures Ruff and replaces rather than merges with global user settings.** Applying the global profile (ANN + pydocstyle) to this codebase reports three hundred seventy-six findings, almost all noise (two hundred twenty-six test-function annotations and forty-eight `P` fixture names), so only actionable rules are enabled here. The global configuration also sets `fix = true`, which means **`ruff check` edits files by default**; add `--no-fix` for a read-only check.

### Implement the canonical file

Create and edit `app/ingestion/parser.py` directly. The default test target already imports that canonical path:

```bash
uv run pytest
```

Tests that use a function you have not implemented yet are **skipped rather than failed**, so `pytest` output acts as a progress board.

---

## Why not use an off-the-shelf library?

The parser uses BeautifulSoup directly instead of sec-parser or edgartools — ***for education/practice purposes***.

The project is intended to expose the core difficulty of ingestion and table handling. That led it to address:

- data-driven document-type classification and strategy selection;
- use of **the document's own metadata**, specifically its Cross-Reference Index;
- validation-driven fallback (graceful degradation);
- tagged unions that make invalid states unrepresentable; and
- **metrics that detect failure**, which proved to be the hardest part.

This is practical evidence that "RAG ingestion is harder than retrieval."

---

## Design principles at a glance

| Principle | Implementation |
|---|---|
| Put rules in data, not code | `rules` are profile JSON |
| Put strategy selection in data too | One `segmentation.type` selects the parsing path |
| Start cheap; use expensive work only when failure is detected | Measure first (0.1seconds), then degrade gracefully |
| Do not discard state | Store classification failure as `undefined` |
| Do not save bad rules | Persist relearning **only after validation passes** |
| Treat year changes as facts, not exceptions | Independent `profiles` entries with no merge rule |
| Encode dependencies with tagged unions | `type` determines the payload |
| **Fallback works only when failure is detectable** | Four validation metrics ([F14](01-findings.md#f14)) |

---

## Next steps (M1.2 and beyond)

Module contracts, layers, and completion criteria are in [`docs/project/planning/04-build-plan.md`](../../project/planning/04-build-plan.md).

**M1.2 — Tables → markdown** (`app/ingestion/tables.py`, complete six-document set) L1 table-structure detection → L2 cell normalization → L3 markdown serialization. After the [B04](04-bugs.md#b04) fix, tables are preserved intact in every file, including the three legacy files, so the raw material already exists in `Block.html`.

**M1.3 — Structure-aware chunking ★** (`app/ingestion/chunk.py`, complete six-document set) L1 chunk type (+span) → L2 text chunker → L3 **table chunker** → L4 context header (narrative title) → **L5 span assignment**. L5 is new here: adding fields to `Block`, specifically `source_pos`/`end_pos`, gives each chunk a **source-text character offset**. See [02-spec §7](02-spec.md#why-source_pos-became-important--span-citations) for the rationale. The completion criteria add a **span round-trip test** that checks whether the source slice contains the chunk body.

**M1.4 — Database ingestion** (`app/ingestion/seed.py`, complete six-document set) Includes `Chunk.source_sha256`/`start_char`/`end_char`. It also stores `item_index` and `status` as metadata so the system can answer "Not applicable" with evidence. Reruns are safe.

Parsing paths deliberately left unimplemented (`sec_canonical` and `custom_title` classification, plus the LLM cascade), together with **fields added by the milestones above**, are listed in section 02 of [the specification](02-spec.md#9-designed--not-implemented), under section nine. They were deferred because **there is no way to validate unreachable code written in advance**.

---

## This document set is a template

Every milestone after M1.2 repeats **this six-document structure and test harness** ([§4 of `docs/project/planning/00-plan.md`](../../project/planning/00-plan.md)).

| Built here | Used in later milestones |
|---|---|
| canonical `parser.py` path | canonical `chunk.py`, retrieval, evaluation, and later module paths |
| completed M1.1 implementation | later modules start absent and are created directly from their tutorials |
| `tests/support.py` and its `need()` helper | Reused unchanged; unimplemented work is skipped rather than failed |
| `tests/ingestion/golden.py` | Each area has `tests/<area>/golden.py` |
| `scripts/check_doc_code.py` | Extended to each new documentation directory |
| six-document set | The M1.1~M1.4_scope uses complete responsibility-specific sets; later modules use complete or abbreviated sets according to difficulty |

The rule **"writing the same fact in two places guarantees divergence"** carries forward: measurements live only in `01-findings`, bugs only in `04-bugs`, golden values only in `golden.py`, and code only in source files.
