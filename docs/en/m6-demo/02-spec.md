# M6 Spec

This document is normative for M6. It defines what the portfolio may claim, what the demo must expose, and the evidence joined at M6.3 completion.

## 1. Dependency and order

- M6.1 and M6.2 each require M5.3.
- M6.1 and M6.2 may proceed in parallel.
- M6.3 requires both M6.1 and M6.2.
- The visible documentation order shall remain `M6.1 -> M6.2 -> M6.3`.

## 2. Portfolio audience

The primary reader is an engineer or reviewer who needs to decide quickly whether the repository demonstrates evidence-grounded system design. The landing page shall answer:

1. What problem does the system solve? 2. Which boundaries are deterministic and verified? 3. What did evaluation measure? 4. What failed or remains unproven? 5. Which exact commands reproduce the local evidence?

## 3. Public evidence card

Every supported demo result shall expose, directly or through the rendered evidence JSON:

- human citation;
- half-open source span;
- source SHA-256;
- positive chunk ID; and
- evidence body.

An unsupported result shall expose an empty evidence collection. Presentation code shall not invent a placeholder citation.

## 4. Trace and cost surface

The demo shall show mode, status, model/provider label, request count, input tokens, output tokens, estimated cost, and latency. A typed failure may add a sanitized error message. Credential names, values, authorization headers, and arbitrary exception representations shall never be rendered.

## 5. Demo modes and labels

| Mode | Required label | Permitted claim |
|---|---|---|
| Canned | `canned fixture` | deterministic supported/unsupported UI behavior; zero provider cost |
| Runtime query | `local runtime retrieval` | evidence returned through injected M5 retrieval |
| Runtime review | `local runtime review` | guarded review through injected M5 workflow and trace contract |

The current command launches canned mode. The adapter for injected runtime services is verified against the actual M5 return type, but runtime labels may be used only when those services are explicitly injected for the recorded run.

## 6. Evaluation claim rules

- Report all six chunking/strategy arms, not only the best metric.
- State that metrics score the 24 positive cases while artifacts contain all 28 questions.
- State that golden cases are agent-curated and pending author approval.
- State that deterministic token-hash vectors do not represent semantic-provider quality.
- Do not choose a production configuration from the recorded low, mixed metrics.
- Separate paid-provider estimates and runs from deterministic acceptance.

## 7. Screenshot policy

A missing screenshot may be represented only by text containing the word `placeholder` and an explicit statement that it is not evidence. A screenshot is optional; if committed, it must include or accompany:

- the commit/revision under test;
- the demo mode label;
- the query and visible evidence identity;
- the acceptance command result; and
- confirmation that no secret is visible.

No fabricated frame, mock result, or unlabeled canned capture may be presented as current runtime behavior.

## 8. Commands and language

Setup, test, launch, curl, and reproduction commands shall be directly copyable from the repository root. All code blocks, shell commands, code comments, and docstrings shall be in English. Korean explanatory prose is allowed.

## 9. Documentation set

M6 shall include `00-README.md` through `05-verify.md`, plus portfolio-facing architecture, evaluation, and failure reports. The root README, `docs/00-README.md`, and `docs/project/module-plan.md` shall link to the canonical M6 route without duplicating normative implementation details.

## 10. Acceptance

M6.2 is complete when documentation links/source blocks synchronize, its exact commands are valid, measured claims trace to repository artifacts or tests, and screenshots remain honestly labeled.

M6 is complete after M6.3 proves the real M5/M6 return-type integration, reruns the full suite, publishes the measured pass/skip count, and leaves any absent screenshot honestly labeled as a non-evidence placeholder.
