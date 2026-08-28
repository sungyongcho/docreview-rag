# M3 golden-set review queue

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
