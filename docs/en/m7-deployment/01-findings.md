# M7 Findings

These findings separate executable local evidence from external deployment claims. The record date is 2026-08-13.

## F1 — Canned mode wins over ambient credentials

`ReleaseSettings` defaults to `mode=canned`. An ambient `OPENAI_API_KEY` remains a redacted configuration value but does not enable provider work. Both runtime mode and an operator secret must be present before `openai_enabled` becomes true. The public Gradio surface has no credential input.

This is stronger than checking whether a key exists: credential presence is not user consent to spend.

## F2 — Cost has three explicit server-side caps

The optional provider boundary uses `gpt-4.1-mini`, at most 12,000 input tokens, at most 600 output tokens, and at most `$0.01` estimated cost per workflow. At the configured prices, the maximum token-bound estimate is `$0.00576`, below the cost cap.

The price inputs of `$0.40` per million input tokens and `$1.60` per million output tokens were checked on 2026-08-13 against the official [`gpt-4.1-mini` model page](https://developers.openai.com/api/docs/models/gpt-4.1-mini). They are dated configuration, not a permanent promise; recheck before any authorized live run. No provider request was made for M7 acceptance.

## F3 — The limiter is bounded and deliberately single-process

Each client has rolling minute/day timestamps. State is capped at 1,024 LRU client entries, and stored identifiers are keyed hashes rather than raw addresses. Concurrent checks share one async lock, so only the configured number of requests is admitted in one process.

Eviction can weaken per-client enforcement during high-cardinality traffic, and multiple workers or replicas would each have independent counters. The Docker Space command pins one worker. Public scale-out requires a shared external limiter and is not claimed.

## F4 — Security headers cover policy failures

The security header middleware is registered outside the request guard. Tests assert `x-content-type-options=nosniff` and `cache-control=no-store` on ordinary responses, the read-only 403, and the rate-limit 429. This ordering matters because a guard-generated response can otherwise bypass an inner header layer.

No restrictive frame header is added because Hugging Face renders Spaces in an iframe. The release instead uses same-origin opener, same-site resource, no-referrer, no-store, permissions, and no-sniff policies.

## F5 — Provider secrets are server-only and non-persistent

The operator key is read through `SecretStr`, passed only to the provider constructor, added to persistence redaction, and filtered from release/Uvicorn log records. The OpenAI adapter already sends `store=False`. Public `/release` metadata exposes only a boolean and fixed caps.

Process memory necessarily contains the secret while runtime mode is active. M7 does not claim hardware isolation, multi-tenant secret custody, or a browser BYO-key flow.

## F6 — Clean Git evidence has a narrower corpus scope

Only `data/corpus/manifest.json` is tracked; the 20 SEC HTML files are intentionally ignored. The temporary clean archive therefore runs the self-contained release, demo, and API suites, fresh locked sync, lint, documentation, Compose validation, both container builds, and the canned health/UI smoke. The populated working repository separately owns the full offline suite.

## F7 — Focused integration is measured

The combined `tests/release tests/demo tests/api` gate measured `67 passed`. It covers the 21 M7 release tests, the six M6 demo tests, and the existing M5 API surface without database or provider network calls. The populated offline suite measured `718 passed, 1 skipped` in 111.31 seconds. A fresh temporary archive then repeated locked dependency sync, the 67 focused tests, lint, formatting, documentation checks, both container builds, and canned health/UI smoke; all passed. Exact commands are recorded in [verification](05-verify.md).
