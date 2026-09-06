# M8 Overview — Cross-Lingual Retrieval

> **`zero` branch note:** The complete code below is the pinned reference target — write the canonical files yourself. Live progress: [module plan](../../project/module-plan.md).

The corpus is twenty English SEC 10-K filings, and nothing in the system knows that a query has a language. The lexical index is built with the `english` text-search configuration, so a Korean question is tokenized by an English stemmer and the hybrid fusion is left ranking on a vector arm whose only committed numbers came from deterministic token-hash vectors. M8 answers "does a Korean question find the right English passage?" with measurements instead of a claim: a bilingual twin golden suite, language-sliced runs through the unmodified M3 harness, language-aware query handling entered as arms, and a ko/en parity gate that drives one documented improvement cycle.

## Milestone contract

`twin golden suites -> language-sliced runs -> query-path arms -> a gated parity ratio`

Every number in this module is produced by the M3 evaluation harness without modifying it. Language is not a new dimension inside the scorer; it is a separate run of the same harness over a suite whose answer spans are byte-identical to the English one.

| Layer | Goal | Key files | Stop condition |
|---|---|---|---|
| M8.1 | Korean twins over the same immutable spans | `bilingual.py`, `retrieval_ko.json` | A ko/en metric gap can only be a retrieval fact |
| M8.2 | Make the collapse a number | `crosslingual.py`, `sbert.py` | The "before" table exists before any fix |
| M8.3 | Language-aware query handling as arms | `language.py`, `translate.py`, `service.py` | Routing and translation are measured, not believed |
| M8.4 | Parity definition and its gate | `parity.py`, `crosslingual.py` | The ratio has a floor, a tolerance, and a verdict |

## Six-document reading order

1. [Overview](00-README.md) gives the checkpoint route and its stop gates. 2. [Findings](01-findings.md) records the evidence that made this module necessary. 3. [Specification](02-spec.md) defines the twin contract, the arm grammar, and the parity definition. 4. [Build guide](03-build.md) walks M8.1 → M8.4 and carries the complete reference files. 5. [Bugs](04-bugs.md) records the traps this module actually hit. 6. [Verification](05-verify.md) gives the acceptance commands and the measured tables.

The four tutorial chapters under [`tutorial/`](tutorial/01-bilingual-golden.md) build one checkpoint each.

## Sortable checkpoint route

### M8.1 — Bilingual twin golden suite

- Prerequisite: M1–M7 complete; `uv run pytest tests/evals -q` passes and `data/golden/retrieval.json` is unchanged.
- Files: `data/golden/retrieval_ko.json`, `app/evals/bilingual.py`.
- Canonical command:

  ```bash
  uv run pytest tests/crosslingual/test_01_bilingual.py -q
  ```

- Expected result: `13 passed` with no network call and no database.
- Stop condition: twenty-eight Korean twins load through the unmodified golden loader and agree with their English counterparts on every field except the question.

### M8.2 — Measurement before any fix

- Prerequisite: M8.1 is complete.
- Files: `app/evals/crosslingual.py`.
- Canonical command:

  ```bash
  uv run pytest tests/crosslingual/test_02_crosslingual.py -q
  ```

- Expected result: `23 passed` with no network call and no database.
- Stop condition: an arm carries its own provenance, the twin-alignment and lexical-coverage diagnostics return measured numbers, and both language runs render as one table.

### M8.3 — Routing and translation

- Prerequisite: M8.2 is complete.
- Files: `app/retrieval/language.py`, `app/retrieval/translate.py`, `app/retrieval/service.py`, `app/config.py`, `app/evals/crosslingual.py`.
- Canonical command:

  ```bash
  uv run pytest tests/crosslingual/test_03_language.py tests/crosslingual/test_04_translate.py -q
  ```

- Expected result: `22 passed` (`15` for detection and routing, `7` for translation) with no network call.
- Stop condition: detection is a pure character scan, routing is observable in `ComponentRankings`, and translation fails closed instead of returning the untranslated query.

### M8.4 — Parity gate and the improvement cycle

- Prerequisite: M8.3 is complete.
- Files: `app/evals/parity.py`, `app/evals/crosslingual.py`.
- Canonical command:

  ```bash
  uv run pytest tests/crosslingual/test_05_parity.py -q
  ```

- Expected result: `11 passed` with no network call.
- Stop condition: the ratio is defined per metric, fails closed at a zero English slice, and `--gate` judges only the arms that claim to have fixed something.

## Offline quick start

```bash
uv run pytest tests/crosslingual -q
uv run ruff check app/evals app/retrieval tests/crosslingual
```

Expected: `69 passed`. The whole suite is offline and deterministic — no PostgreSQL, no network, no API key.

## Measured runs

```bash
docker compose up -d db
uv run python -m app.evals.crosslingual --provider deterministic --languages en ko --strategies lexical vector hybrid --handling direct
uv run python -m app.evals.crosslingual --provider sbert-multi --languages en ko --strategies vector hybrid --handling direct routed --gate
```

Measurement is a command-line run, never a test. It needs the seeded local PostgreSQL from M2, builds its own temporary corpus, and leaves the populated corpus embeddings untouched. The recorded numbers live in [verification](05-verify.md).
