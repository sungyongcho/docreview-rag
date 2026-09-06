# M7 Overview — deployment-ready release

> **`zero` branch note:** The complete code below is the pinned reference target — write the canonical files yourself. Live progress: [module plan](../../project/module-plan.md).

M7 turns the verified local portfolio into a bounded deployment artifact without claiming that an external service was published. The visible route is **M7.1 release guards -> M7.2 Hugging Face/container assets -> M7.3 clean-archive release proof**.

## Current milestone state

| Step | Outcome | State |
|---|---|---|
| M7.1 | Canned-default policy, bounded rate limiting, server-only optional provider key, cost caps, and security headers | Implemented; focused release/demo/API suite measured 67 passed |
| M7.2 | Docker Space metadata, nonroot image, health checks, and hardened Compose app | Implemented; local container evidence is recorded by M7.3 |
| M7.3 | Full offline regression plus temporary clean-archive sync/build/smoke | Complete; 718 passed, 1 skipped, and clean-archive proof passed |

No command in this tutorial creates a Hugging Face Space, pushes a repository or image, or makes a provider request.

## Release contract

`canned by default -> explicit runtime opt-in -> bounded server work -> non-secret evidence`

- `DOCREVIEW_MODE=canned` is the default even when an ambient `OPENAI_API_KEY` exists.
- The public UI has no key field. Optional OpenAI access is an operator-supplied server secret and activates only with `DOCREVIEW_MODE=runtime`.
- Provider work is capped at 12,000 input tokens, 600 output tokens, and an estimated `$0.01` per workflow. These caps do not grant permission to spend.
- POST-like work is limited to 10 requests per rolling minute and 100 per rolling day for each bounded in-process client key. This is suitable for one worker, not replicas.
- Public ingestion is disabled. Responses include no-store, no-sniff, referrer, permissions, and cross-origin headers, including early 403 and 429 responses.
- The default canned fixture makes zero database or provider calls.

## Six-document route

1. [Overview](00-README.md) states the deployment boundary and status. 2. [Findings](01-findings.md) records measured behavior and residual limits. 3. [Specification](02-spec.md) freezes release security and honesty requirements. 4. [Build guide](03-build.md) proceeds visibly from M7.1 to M7.3. 5. [Bugs](04-bugs.md) explains concrete deployment traps and regressions. 6. [Verification](05-verify.md) records exact local and clean-archive gates.

## Local canned launch

```bash
uv sync --locked --extra demo
DOCREVIEW_MODE=canned uv run --extra demo uvicorn app.release.space:app --host 127.0.0.1 --port 7860 --workers 1 --log-level warning
```

From another terminal:

```bash
curl --fail --silent --show-error http://127.0.0.1:7860/health
curl --fail --silent --show-error http://127.0.0.1:7860/release
```

Expected labels are `mode=canned` and `openai_enabled=false`. The browser landing page is a **canned fixture**, not a live SEC retrieval or model-backed review.

## External actions intentionally not run

The metadata template under `deploy/huggingface/` follows the official [Docker Spaces metadata and port convention](https://huggingface.co/docs/hub/en/spaces-sdks-docker). Creating a Space, adding a secret in its Settings page, and pushing the prepared files all require an explicitly authorized user account and remain outside this release proof.
