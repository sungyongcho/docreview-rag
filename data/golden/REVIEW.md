# Built-in golden set review

## Integration update — 2026-09-08

The evaluator now binds required official filing identities through
`requirements/sources.json`, verifies unchanged source hashes and spans, and maps runtime
answer IDs to current acquisition IDs without editing golden JSON. Shared preflight runs
before job admission and again before execution. Missing sources and stale parsed/index
inputs are preparation states. Built-in and user-revision provenance remain separate from
human review; no approval flags were upgraded. The audit snapshot below predates this fix.

## Current audit — 2026-09-08

“Built-in golden set” describes bundled evaluation questions and reference evidence. It does
not mean human-approved ground truth or readiness against every locally acquired corpus.
All seven currently registered suites remain `agent-curated`, `pending-author-approval`,
and `human_verified: false`.

### Dataset structure

All 172 cases passed the current `GoldenCase` schema and `validate_unique_cases` checks,
including question/ID/span uniqueness within each suite and positive/absent contracts.
There are 150 positive cases and 22 absent cases across the seven language/version files;
these totals include parallel language versions, not 172 distinct questions.

| File | Cases | Positive | Absent | Referenced documents |
|---|---:|---:|---:|---:|
| `retrieval.json` | 28 | 24 | 4 | 20 |
| `retrieval_ko.json` | 28 | 24 | 4 | 20 |
| `sec_en_v2_astra.json` | 20 | 18 | 2 | 16 |
| `sec_ko_v2_astra.json` | 20 | 18 | 2 | 16 |
| `sec_mixed_v2_astra.json` | 20 | 18 | 2 | 16 |
| `dart_retrieval.json` | 28 | 24 | 4 | 2 |
| `dart_retrieval_ko.json` | 28 | 24 | 4 | 2 |

### Current corpus compatibility

The inspected local manifest contains six SK hynix annual reports for FY2020–FY2025.
It has no SEC reports and no Samsung Electronics FY2024 report. Its selection IDs are
acquisition-generated DART identifiers, not `sec-evaluation` or `dart-evaluation`.
The evaluation service still requires these fixed selection names. Consequently, no
complete bundled suite is currently executable through the existing loader.

The DART suites each require SK hynix FY2024 and Samsung Electronics FY2024. For SK hynix:

- Golden document identity: `000660-FY2024`.
- Current acquired identity: `dart-20250319000665`.
- Exact decoded-source SHA-256 matches all 12 referenced spans in each language file:
  `bfd3322e362217cddde1020608b6ee3d65cb33b58be2dd8957e788da63ab0a20`.
- All 12 intervals are within the current source. The Korean questions and reference
  answers were compared with the extracted intervals; no unsupported answer claim was
  identified in that bounded agent review.
- This verifies 12 shared source intervals, not 24 independent pieces of evidence, and
  does not establish human approval or corpus-wide answer uniqueness.

The missing Samsung and SEC sources were not downloaded. Their source hashes, intervals,
and answer claims were not revalidated in this audit. Absent-case correctness also remains
unverified against the intended full evaluation corpus; a smaller local corpus cannot prove
that an answer is absent from the benchmark corpus.

### Required updates before runnable evaluation

1. Replace the evaluator's dependency on acquisition selection names with explicit,
   versioned evaluation-source requirements. Bind official filing identity and exact
   source hash; reconcile document identity consistently in both cases and retrieval.
2. Expose required-versus-present sources per built-in suite, and validate parsing and
   the chosen retrieval index before queueing a job. Report missing data as preparation
   requirements rather than discovering it after the job starts.
3. Obtain and verify missing sources before changing reference answers, hashes, or offsets.
   Do not fabricate aliases, remove inconvenient cases, or relabel unreviewed data as approved.
4. Record the evaluated corpus scope and golden-set version in each result. Revalidate
   absent cases if the corpus scope changes.

No golden JSON, raw source, database, approval flag, or evaluation result was modified by
this audit. The historical SEC-only notes below are retained as prior evidence; their old
source-validation claims do not establish readiness for today's local corpus. In particular,
the current base SEC files reference 19 documents, whereas those notes describe 20.

## Historical SEC-only review

## Status

Every case in `retrieval.json` is **agent-curated**, **pending author approval**, and
explicitly marked `human_verified: false`. No case has been human-verified, and this file
does not claim otherwise.

The committed set contains 28 cases: 24 positive source-grounded questions and four honest
`NOT_IN_DOCS` candidates. The positive cases are evenly distributed across tickers (six
each for AMD, INTC, MU, and NVIDIA) and collectively cite all 20 immutable filings. The
four negative cases have no answer spans by contract.

## Machine validation completed

- Every positive answer uses a half-open raw-source interval `[start_char, end_char)`.
- Every positive answer SHA-256 matches the exact UTF-8 corpus file bytes.
- Every interval is ordered, in bounds, nonempty, and contains visible source evidence.
- Whole-chunk reconnaissance spans were replaced with answer-bearing sentences, fragments,
  or table rows; no committed answer span exceeds 2,500 raw characters.
- IDs, normalized questions, answer identities, and tags are unique where required.
- Positive cases require `SUPPORTED` and at least one span; absent cases require
  `NOT_IN_DOCS` and zero spans.
- Category counts are `simple_lookup=13`, `exact_number=5`, `multi_hop=6`, and `absent=4`.
- Facet counts are `factual=6`, `comparison=6`, `risk=6`, `policy=5`, and `numeric=5`.
- Eight positive cases retain the `demo-hero` tag, two per ticker.

These checks establish structural and source integrity. They do not establish domain
correctness or human approval.

## Author review checklist

For every row, inspect the question, reference answer, and rendered raw-source span. Confirm
that every fact required by the answer is inside the cited interval, the wording is
unambiguous, the category and facet are useful, and no equally valid answer exists elsewhere
in the corpus. For an absent case, search the full corpus and confirm that the requested fact
is genuinely undisclosed rather than merely hard to retrieve. Only the author may change
`approval_status` or make a human-verification claim in a later reviewed change.

| ID | Category | Facet | Positive source | Curation | Author approval |
|---|---|---|---|---|---|
| m3c-01 | multi_hop | comparison | AMD-FY2019 | agent-curated | pending |
| m3c-02 | simple_lookup | factual | AMD-FY2020 | agent-curated | pending |
| m3c-03 | simple_lookup | risk | AMD-FY2021 | agent-curated | pending |
| m3c-04 | simple_lookup | factual | AMD-FY2022 | agent-curated | pending |
| m3c-05 | multi_hop | comparison | AMD-FY2022 | agent-curated | pending |
| m3c-06 | absent | policy | none | agent-curated | pending |
| m3c-07 | exact_number | numeric | AMD-FY2023 | agent-curated | pending |
| m3c-08 | simple_lookup | policy | INTC-FY2019 | agent-curated | pending |
| m3c-09 | simple_lookup | risk | INTC-FY2020 | agent-curated | pending |
| m3c-10 | absent | factual | none | agent-curated | pending |
| m3c-11 | multi_hop | comparison | INTC-FY2021 | agent-curated | pending |
| m3c-12 | multi_hop | comparison | INTC-FY2022 | agent-curated | pending |
| m3c-13 | simple_lookup | risk | INTC-FY2023 | agent-curated | pending |
| m3c-14 | exact_number | numeric | INTC-FY2023 | agent-curated | pending |
| m3c-15 | simple_lookup | policy | MU-FY2020 | agent-curated | pending |
| m3c-16 | simple_lookup | factual | MU-FY2021 | agent-curated | pending |
| m3c-17 | exact_number | numeric | MU-FY2022 | agent-curated | pending |
| m3c-18 | simple_lookup | risk | MU-FY2023 | agent-curated | pending |
| m3c-19 | multi_hop | comparison | MU-FY2023 | agent-curated | pending |
| m3c-20 | absent | risk | none | agent-curated | pending |
| m3c-21 | simple_lookup | policy | MU-FY2024 | agent-curated | pending |
| m3c-22 | multi_hop | comparison | NVDA-FY2020 | agent-curated | pending |
| m3c-23 | simple_lookup | factual | NVDA-FY2021 | agent-curated | pending |
| m3c-24 | simple_lookup | factual | NVDA-FY2022 | agent-curated | pending |
| m3c-25 | exact_number | numeric | NVDA-FY2022 | agent-curated | pending |
| m3c-26 | simple_lookup | risk | NVDA-FY2023 | agent-curated | pending |
| m3c-27 | absent | policy | none | agent-curated | pending |
| m3c-28 | exact_number | numeric | NVDA-FY2024 | agent-curated | pending |

## Negative-case review

The four absent questions intentionally ask for a declared AMD quarterly dividend amount,
an Intel commercial quantum-computing subscription service, a Micron ransomware payment
amount, and an NVIDIA Board-approved employee password-rotation interval. Exact-phrase and
concept reconnaissance found no answer for these questions in the immutable corpus. That is
an agent finding only; the author must independently confirm each negative before approval.
