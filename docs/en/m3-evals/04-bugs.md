# M3 Bugs

## B01 — Chunk IDs looked like golden identities

- **Symptom:** re-chunking changed every expected answer even though the source evidence was unchanged.
- **Root cause:** database chunk IDs and parser ordinals are configuration-dependent.
- **Fix:** golden answers use `doc_id`, raw-source SHA-256, and half-open source offsets.
- **Guard:** loader and scoring tests reject source/hash mismatches and prove equivalent source coverage scores the same after chunk identity changes.

## B02 — Absent cases depressed retrieval metrics

- **Symptom:** a correct no-hit result for an absent claim appeared as zero recall.
- **Root cause:** absence has no positive span, so span recall is undefined rather than zero.
- **Fix:** retrieve and record all cases, but score only source-bearing positives; store `score=null` for absent cases.
- **Guard:** runner tests require 28 recorded cases, 24 scored positives, and four unscored absent cases.

## B03 — Full questions produced no lexical candidates

- **Symptom:** both lexical arms measured zero hits, zero Recall@5, and empty raw hit lists.
- **Root cause:** `websearch_to_tsquery` joined the representative question's retained lexemes with AND, and no chunk contained every term. This was a retrieval result, not a scorer or artifact failure.
- **Fix in M3:** none; the finding was measurement working as intended. The fix landed in M2.4 afterwards: the parsed conjunction is relaxed to a disjunction and ranked under `ts_rank_cd` normalization `4 | 1`, taking the lexical arm from 0.000 to 0.271 recall@5 while BM25 stayed ahead at 0.521.
- **Guard:** the report states this limitation and does not attribute hybrid/vector equality to semantic equivalence.

## B04 — A timer initially excluded parsing and chunking

- **Symptom:** an early local budget file reported only temporary DDL, persistence, and embedding time.
- **Root cause:** the clock started after `build_chunking_batch()` returned.
- **Fix:** capture the monotonic start time before manifest loading, parsing, and chunking, then pass it into the temporary corpus session. Regenerate the complete matrix.
- **Guard:** only the corrected `20260812T200916Z` artifacts are committed. The superseded partial-timing files were removed so they cannot be mistaken for portfolio evidence.

## B05 — Provider identity could be inferred from populated vectors

- **Symptom:** an experiment risked labeling existing vectors from the current environment or query provider.
- **Root cause:** the populated chunk schema does not persist embedding-provider identity.
- **Fix:** every experiment creates and embeds its own temporary corpus with an explicit provider; existing provider identity remains unknown.
- **Guard:** configs and artifacts record provider, dimensions, paid-call state, environment, and `populated_corpus_embeddings_modified=false`; validation rechecks the public chunk and non-null embedding counts after the run.

## B06 — Config key order split or merged baselines

- **Symptom:** equivalent dictionaries could miss a baseline, while incomplete configs could compare experiments that changed meaningful variables.
- **Root cause:** comparison depended on caller representation instead of complete canonical configuration.
- **Fix:** validate finite JSON, sort every object key, and persist the full nested chunking/retrieval/embedding/measurement config.
- **Guard:** regression tests cover nested canonical serialization, exact suite/config matching, latest ordering, and non-comparable configs.

## B07 — Latency was accidentally treated as higher-is-better

- **Symptom:** a slower run could appear improved because all numeric metrics shared one comparison rule.
- **Root cause:** metric direction was implicit.
- **Fix:** regression comparison accepts only the explicit higher-is-better tuple `recall_at_k`, `hit_rate_at_k`, and `mrr`. Latency remains observable but is governed by separate upper budgets.
- **Guard:** pure comparison tests prove extra metrics are ignored and tolerance boundaries are inclusive.

## B08 — Machine checks could be mistaken for human review

- **Symptom:** valid hashes and spans were described as author-approved golden answers.
- **Root cause:** structural validation and editorial judgment were conflated.
- **Fix:** carry literal curation, approval, and human-verification fields into every raw artifact and report.
- **Guard:** loader and runner reject mixed provenance or any M3 case claiming human verification. Author review remains a stop gate.
