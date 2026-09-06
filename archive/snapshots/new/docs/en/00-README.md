# Implementation Documentation Map

This is the complete English tutorial edition for the `zero` learning branch. Milestone numbers map one-to-one to responsibilities, code boundaries, tests, and six-document tutorials. The documentation retains the completed reference code as implementation targets, not as claims of current progress. Use the [Korean edition](../ko/00-README.md) when you want the same route in Korean.

| Stage | Responsibility | Code | Tests | Documentation |
|---|---|---|---|---|
| M1.1 | 10-K HTML → Item sections | `parser.py`, `xref.py` | `tests/ingestion/test_01_*`~`test_08_*` | [Parser](m1-1-parser/00-README.md) |
| M1.2 | HTML tables → Markdown | `tables.py` | `tests/ingestion/test_09_tables.py` | [Tables](m1-2-tables/00-README.md) |
| M1.3 | Sections → source-stable chunks | `chunk.py` | `tests/chunk/` | [Chunking](m1-3-chunk/00-README.md) |
| M1.4 | Chunks → idempotent DB upsert | `seed.py`, DB models | `tests/db/` | [Database seed](m1-4-seed/00-README.md) |
| M2 | Exact vector + PostgreSQL FTS → RRF | `app/retrieval/` | `tests/retrieval/` | [Retrieval](m2-retrieval/00-README.md) |
| M3 | Span golden set → metrics, regression, ablation | `app/evals/` | `tests/evals/` | [Evaluation](m3-evals/00-README.md) |
| M4 | Retrieve → grade → check → report | `app/workflow/` | `tests/workflow/` | [Workflow](m4-workflow/00-README.md) |
| M5 | Typed CLI, API, runtime, and container | `app/api/`, `app/cli.py` | `tests/api/` | [Serving](m5-serving/00-README.md) |
| M6 | Evidence-first portfolio demo | `app/demo.py` | `tests/demo/` | [Demo](m6-demo/00-README.md) |
| M7 | Guarded release package and clean-archive proof | `app/release/`, `deploy/` | `tests/release/` | [Deployment](m7-deployment/00-README.md) |
| M8.1 | Korean twin suite over the same immutable spans | `bilingual.py`, `retrieval_ko.json` | `tests/crosslingual/test_01_*` | [Cross-lingual](m8-crosslingual/00-README.md) |
| M8.2 | Language-sliced measurement before any fix | `crosslingual.py` | `tests/crosslingual/test_02_*` | [Cross-lingual](m8-crosslingual/03-build.md) |
| M8.3 | Detection, routing, and translation as arms | `language.py`, `translate.py` | `tests/crosslingual/test_03_*`~`test_04_*` | [Cross-lingual](m8-crosslingual/03-build.md) |
| M8.4 | ko/en parity ratio, its floor, and its gate | `parity.py` | `tests/crosslingual/test_05_*` | [Verification](m8-crosslingual/05-verify.md) |
| M9 | Tool-calling agent with evidence-gated citations | `app/agent/` | `tests/agent/` | [Agent](m9-agent/00-README.md) |

Documentation availability is not implementation completion. Follow the live state in [`docs/project/learning.toml`](../project/learning.toml) and the detailed [`module-plan.md`](../project/module-plan.md).

Use the [unified documentation hub](../00-README.md) to choose between current tutorials, the ordered implementation route, historical planning evidence, and portfolio closeout work. [`docs/project/module-plan.md`](../project/module-plan.md) owns only the detailed dependency sequence.

Portfolio-facing documents are [architecture](architecture.md), [evaluation](eval-report.md), and [failure analysis](failure-analysis.md).

## Current starting point

The retained reference edition freezes one shared relative-path inventory under `docs/en/**` and `docs/ko/**`; English is the structural reference, while Korean is a natural translation with the same executable literals, evidence, and document destinations. `docs/project/**` holds shared route and planning records; `docs/00-README.md` selects the edition without creating a third localized copy.

Run these gates before treating either edition as complete:

```bash
uv run python scripts/check_doc_code.py README.md docs deploy/huggingface/README.md
uv run python scripts/check_doc_parity.py inventory
uv run python scripts/check_doc_parity.py parity
uv run python scripts/check_doc_parity.py language
```

The last recorded full-suite baseline was `718 passed, 1 skipped` on 2026-08-13. The skip is the explicitly opt-in live OpenAI workflow test; ordinary verification makes no paid-provider call. The count is refreshed only after rerunning the populated repository.

## Documentation contract

- Every implementation milestone keeps a responsibility-specific `00` through `05` tutorial set.
- Each `03-build.md` gives prerequisites, canonical files, commands, expected results, stop conditions, and debugging checks in dependency order.
- Code fences, commands, paths, inline code, source markers, checkpoint IDs, measured values, and table topology are protected technical literals rather than translatable prose. Existing M1.1 sources are compared with local files; future sources are compared with pinned `reference_revision` without creating them under `zero/app/`.
- Local links may use translated heading fragments, but they must resolve to the same logical document in both editions.
- [`localization-manifest.json`](../localization-manifest.json) freezes the inventory; [`localization.toml`](../localization.toml) defines the reference locale and protected fields.
- `scripts/` remains part of the product: the test suite verifies generated complete-file sections and calls the documentation gates directly.

## Bilingual verification

The inventory gate rejects missing or extra files. The parity gate compares translation-invariant Markdown structure against the English reference and resolves links by document identity instead of requiring translated fragments to be textually identical. The language gate rejects Hangul in unprotected English prose, suspicious untranslated English paragraphs in Korean, and inconsistent Korean terminology. The link and source-code gate independently proves that every local target, anchor, and marked source excerpt exists and is current.

```bash
make docs
```
