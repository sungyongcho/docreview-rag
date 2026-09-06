# M7 Spec

This document is normative for M7. It defines what a local release artifact may claim and what must remain explicitly unproven without an external deployment.

## 1. Dependency and order

- M7.1 requires M6.3.
- M7.2 requires M7.1.
- M7.3 requires M7.2.
- Documentation shall remain visibly sorted `M7.1 -> M7.2 -> M7.3`.

## 2. Canned-default policy

The release entrypoint shall default to `canned` and make zero database or provider calls. An ambient provider key shall not change the mode. The UI and `/release` resource shall make the active mode inspectable without exposing credentials.

## 3. Optional provider policy

- The public browser shall not accept, store, or render a key.
- Optional OpenAI access shall use an operator-provided server environment secret.
- A key shall activate only with explicit `runtime` mode.
- Provider requests shall set remote storage off and use strict structured outputs.
- Secret values shall be supplied to persistence and logging redaction.
- User credentials, account creation, live calls, and external publishing are not M7 acceptance prerequisites.

## 4. Cost policy

Every optional provider workflow shall have positive input/output token limits, explicit per-million prices, and a finite nonnegative estimated-cost ceiling. Unknown prices shall fail closed. Current defaults are 12,000 input tokens, 600 output tokens, and `$0.01`. Pricing shall be dated and rechecked before an authorized run.

## 5. Rate-limit policy

The public single-worker artifact shall enforce rolling minute and day limits for POST-like work. Client state shall have a finite bound. Direct client addresses shall be used unless proxy-header trust is explicitly enabled. A 429 shall include a retry interval and remaining limits.

The in-process limiter shall not be presented as distributed protection. Multiple workers or replicas require a shared limiter before public scale-out.

## 6. HTTP and mutation policy

Public ingestion shall be disabled by default. Security headers shall wrap success, typed application errors, read-only 403 responses, and rate-limit 429 responses. Frame-blocking headers shall not prevent the documented Hugging Face embedding path.

## 7. Container and Space policy

- The Space metadata template shall declare `sdk: docker` and `app_port: 7860`.
- The image shall run as UID 1000, expose port 7860, include a health check, and pin one Uvicorn worker.
- Locked dependencies and the optional demo extra shall be installed at build time.
- Compose shall retain PostgreSQL while applying no-new-privileges, dropped capabilities, read-only root filesystem, and writable `/tmp` to the app container.

## 8. Verification policy

M7 completion requires focused release/demo/API tests, the populated repository full offline suite, Ruff, owned formatting, documentation/link sync, lock validation, Compose validation, container builds, a local canned health/UI smoke, and a temporary clean archive with a fresh environment.

The clean archive shall not copy `.env`, ignored corpus HTML, caches, or virtual environments. External credentials and external account mutations shall remain absent.

## 9. Language and evidence

All commands, code blocks, code comments, and docstrings shall be English. Counts shall be copied from measured command output, not calculated from predecessor totals. Golden data remains agent-curated and shall never be labeled human-verified.
