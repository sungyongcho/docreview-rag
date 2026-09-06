# M6 Overview — portfolio surface

> **`zero` branch note:** The complete code below is the pinned reference target — write the canonical files yourself. Live progress: [module plan](../../project/module-plan.md).

M6 turns the working document-review system into an honest, reproducible portfolio surface. The visible route is **M6.1 Gradio demo -> M6.2 portfolio documentation -> M6.3 integration**. M6.1 and M6.2 share the M5.3 prerequisite and may be built in parallel; M6.3 joins them.

## Current milestone state

| Step | Outcome | Measured state |
|---|---|---|
| M6.1 | Gradio evidence demo | Complete: 6 tests passed; UI build and loopback launch/close at `127.0.0.1:7861` succeeded |
| M6.2 | Portfolio narrative and reports | Complete: architecture, evaluation, failure, tutorial, commands, and indexes synchronized |
| M6.3 | Runtime/demo integration and final regression | Complete: real `RetrievalResult.hits` regression, repository gates, and `697 passed, 1 skipped` |

The post-M6 checkpoint is `697 passed, 1 skipped`, measured by a complete suite run rather than arithmetic on the `691 passed, 1 skipped` predecessor. M6 is complete; M7 deployment-ready release work is next.

## Milestone contract

`measured repository behavior -> explicit tradeoffs -> reproducible commands -> honest demo`

The portfolio must make four states distinguishable:

1. supported evidence with citation, source span, hash, and chunk ID; 2. a fact not found in supplied documents, with no fabricated evidence; 3. trace, request, token, cost, and latency information without secrets; and 4. typed service or budget failure instead of a polished fallback answer.

The default Gradio service uses synthetic Acme fixtures. It proves UI behavior and zero-cost execution, not retrieval against the committed AMD, INTC, MU, and NVDA corpus. The injected runtime adapter is separately verified against the real M5 `RetrievalResult.hits` contract.

## Six-document reading order

1. [Overview](00-README.md) states scope, status, and portfolio claims. 2. [Measured findings](01-findings.md) records repository evidence and limitations. 3. [Specification](02-spec.md) freezes the portfolio and demo contract. 4. [Sortable build guide](03-build.md) proceeds visibly from M6.1 to M6.3. 5. [Bugs and traps](04-bugs.md) records presentation failures and regression guards. 6. [Verification](05-verify.md) gives exact acceptance and M6.3 handoff commands.

Portfolio-facing companions:

- [Repository README](../../../README.md)
- [Architecture](../architecture.md)
- [Evaluation report](../eval-report.md)
- [Failure analysis](../failure-analysis.md)

## Fastest honest demo

```bash
uv sync --locked --extra demo
uv run --extra demo python -m app.demo
```

Open the URL printed by Gradio. Label the result **canned fixture**. Do not call it a live SEC retrieval or model-backed answer.

## Screenshot status

> **Placeholder — not a screenshot and not evidence.** No image is committed. A future capture must identify its `canned fixture` or local-runtime mode and pass the screenshot release gate; this placeholder carries no evidentiary weight.
