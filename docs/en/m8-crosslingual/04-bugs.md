# M8 Bugs

This file records the traps this module actually hit and the narrow fix for each. It is not a list of speculative future features.

## B01 — Loading the golden directory put the twins in one batch

**Symptom:** `load_golden_cases("data/golden")` raised `GoldenDataError` about duplicate answer-span identity as soon as `retrieval_ko.json` existed beside `retrieval.json`, even though both files were individually valid.

**Root cause:** the loader accepts a directory and merges every `*.json` in filename order into one batch, and `_validate_unique_cases` rejects duplicate answer-span identities *across cases within one batch*. Twins share every span deliberately — that shared span is what makes the parity number mean anything — so a merged load is exactly the case the rule forbids.

**Fix:** never load the two suites as a directory. `load_bilingual_suites` makes two separate `load_golden_cases` calls and validates the pairing afterwards. Each file still receives the loader's full manifest, SHA-256, bounds, and visible-evidence verification, and the English file is untouched.

**Guard:**

```bash
uv run pytest tests/crosslingual/test_01_bilingual.py -k "same_spans" -q
```

## B02 — The twin validator named the symptom instead of the cause

**Symptom:** pasting an English question into a Korean case during authoring produced `m3c-12 Korean question contains no Hangul`, which sent the reader looking for an encoding problem in a case whose only fault was that it had never been translated.

**Root cause:** the script checks ran before the difference check. "No Hangul" is true of an untranslated copy, but it is the second-order consequence; the first-order fact is that the two questions are the same string.

**Fix:** check order is part of the contract. `validate_twin_cases` compares the case-folded, whitespace-normalized questions first and raises `twins share one untranslated question`; only then does it apply the Hangul rules. The order is pinned by a comment in the source so a later refactor cannot silently reshuffle it.

**Guard:**

```bash
uv run pytest tests/crosslingual/test_01_bilingual.py -k "untranslated" -q
```

## B03 — Routed handling walked past the retriever the test had faked

**Symptom:** a test that stubbed `make_retriever` still tried to open a real database connection when the arm's handling was `routed`, and failed with a session error rather than an assertion.

**Root cause:** `direct` and `translated` handling are built on `make_retriever`, but `routed` is not. Routing is a property of the production query path, so the routed wrapper calls `retrieve()` directly with `route_by_language=True` — which is the point of the arm, and also means it never passes through the factory a test had replaced.

**Fix:** none in the source; the arm is correct as written. The test contract changed instead: anything faking the retrieval boundary for a routed arm has to fake `retrieve` as well. The routed test asserts on the arguments `retrieve` received, which is also the cleanest proof that routing was actually requested.

**Guard:**

```bash
uv run pytest tests/crosslingual/test_02_crosslingual.py -k "routed" -q
```

## B04 — The "dead" lexical arm was not entirely dead

**Symptom:** an early draft of the coverage diagnostic asserted a 100% zero-candidate rate for Korean and failed against the real corpus.

**Root cause:** Korean questions about semiconductor filings are mixed-script by nature. `AMD의 7nm 공급 위험` carries a ticker, a unit, and a number in Latin script, and the English tsquery happily matches those lexemes. The collapse is partial, and how partial is a property of this question set, not a constant.

**Fix:** `lexical_candidate_coverage` reports the rate as a measurement — zero-candidate case count, rate, mean candidate count, and the ids of the empty cases — and no test asserts a specific rate. The offline test drives a scripted arm whose behaviour is known; the real rate is a number the measured run produces.

**Guard:**

```bash
uv run pytest tests/crosslingual/test_02_crosslingual.py -k "lexical_coverage" -q
```

## B05 — Hash collisions made "orthogonal" vectors slightly non-orthogonal

**Symptom:** a test asserting `cosine == 0.0` for deterministic twin-query vectors failed with values around `1e-2`.

**Root cause:** the deterministic provider hashes tokens into 384 buckets. A Korean question and its English twin share almost no tokens, but 384 buckets over a real vocabulary collide, so unrelated tokens land in the same dimension and produce a small positive dot product. The provider also keeps Hangul eojeols as tokens — its tokenizer normalizes with NFKC and matches `[^\W_]+` — so the Korean side is not an empty vector either.

**Fix:** assert near-zero, never exact zero. The structural claim is "this space does not relate the two languages", and the honest test of that claim is a small bound, not an equality. The same reasoning appears in the diagnostic's own docstring so nobody tightens it later.

**Guard:**

```bash
uv run pytest tests/crosslingual/test_02_crosslingual.py -k "twin_alignment" -q
```

## B06 — A dead English slice looked like perfect parity

**Symptom:** an arm whose English recall was `0.0` and Korean recall was `0.0` produced a parity verdict of `PASS` in an early draft, because `0/0` had been coerced to `1.0`.

**Root cause:** the ratio is undefined at a zero denominator, and a default of `1.0` reads as "the two languages agree" when the truth is "neither arm retrieved anything".

**Fix:** `ParityMetric.ratio` is `float | None`, `None` means undefined, and an undefined gated ratio is recorded as a failure — the gate fails closed. `parity_markdown` renders it as the literal word `undefined` rather than a number, so a table cannot be read as a passing result.

**Guard:**

```bash
uv run pytest tests/crosslingual/test_05_parity.py -k "zero" -q
```
