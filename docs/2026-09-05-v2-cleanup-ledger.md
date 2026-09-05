# DocReview RAG v2 cleanup ledger

Baseline: `assemble@1dd72a7`. Protected work: `AGENTS.md`, `README.md`, `web/next-env.d.ts`,
`NOTES.md`, and `docs/2026-09-04-local-development-ui-report.md`. Initial SHA-256 hashes are
recorded locally and rechecked at phase boundaries. They are excluded from staging.

## Application unit — be3d837

Feature changes: canonical Small full/DR assets, shell/Web parity, localized attribution,
retained-panel activity propagation, suspended hidden overlays, and explicit Pin citation semantics.

Cleanup changes, separate from features:

- Removed obsolete SVG/slanted branding and old wordmark/tiny-font selectors in
  `web/components/product-brand.tsx`, `web/app/styles.css`, and `web/app/v2.css`.
- Kept responsive brand styles in the existing component boundary, without a dependency or formatter change.
- Checked the new shell tests for required short docstrings and direct imports; no learning shims,
  package façades, test-to-test helper imports, or added package initializers were introduced.
- Reviewed all 22 staged paths for unrelated deletion and foreign-state absorption: none.

Before/after evidence:

- Hidden request inspector and delayed reset dialog: two reproduced failing regressions → passed after activity gating.
- Initial new branding parity tests: two failures from the test's Vite-transformed asset path → both passed after fixing the test path.
- Final worktree and actual staged snapshot: 324 Web tests passed; staged shell suite: 22 passed.
- TypeScript, scoped Ruff check/format, staged static build, and diff whitespace checks passed.
- An attempted dependency hardlink copy crossed filesystems; a fresh ordinary copy completed the isolated snapshot.

No cleanup was applied to protected files. Python type checker was unavailable; no backend implementation
changed in this unit. No paid calls, user-data reset, operator restart, or external writes occurred.

## Guided local connections and documentation unit — ready for snapshot verification

Feature changes:

- Default resolves the existing environment endpoint; a named server catalog preserves legacy settings and working connections.
- Web and CLI share metadata-only diagnosis, reason codes, model roles, and recovery guidance.
- Use Default in the UI selects a probed endpoint; the legacy reset API remains compatible.
- A shared registry drives 15 documents in two languages, 12 tutorial steps, routes, grouping, navigation, and legacy anchors.
- Added the macOS/Linux Ollama guide and updated the affected operational instructions.

Cleanup changes:

- Removed the replaced four-record documentation inventory and duplicate learning-path JSX/table; the Markdown marker expands from the registry.
- Removed the obsolete connection URL-first form and unused reset import; retained the existing exported legacy API wrapper.
- Removed an unused newly introduced translation after validation wording changed.
- Shared transport failure classification replaces duplicated CLI logic. Cause codes and remedies contain no executable server text.
- Named-server storage retains direct imports and existing atomic write/immutable connection architecture. No SQL migration or dependency change.

Verification before snapshot:

- Web 343 passed across 50 files; TypeScript passed. Initial missing Connect/Next steps translations were corrected and retested.
- Backend/caller/configuration suites: 101 passed; nullable-count follow-up: 58 relevant tests passed (overlapping, not additive).
- CLI/shell: 53 passed, including null-versus-measured-zero formatting. Scoped Ruff/format and shell syntax passed.
- Documentation preparation: 30 documents and one existing real image; all internal targets, registry entries, and bilingual step anchors passed.
- Actual Web and CLI Default diagnosis: reachable, 3 installed models, 1 answer-capable; no inference or configuration write.
- Existing protected file hashes remain unchanged. No broad cleanup, staging, reset, permission change, or provider call.

## Consolidated interaction and production preview unit

Completed user-requested changes: two-screen Help with four inline task filters and a single passive target highlight; one Review settings drawer; compact SVG request inspection; EN-first language controls; prominent company/FY identity; semantic documentation icons; an isolated read-only public preview that retains DEV work; and public readiness redaction.

Cleanup: removed obsolete Help badge/triangle/accordion and inline-editor styles; removed duplicate Filters/RAG entry points and the redundant Custom link; reused registry metadata and existing icon library. Preview uses the existing ServiceShell renderer in an isolated document, shared API/storage boundaries, and active polling controls. No dependency, corpus, acquisition-range, or database changes.

Verification: full Web suite374 passed, TypeScript passed; public release tests17 passed plus scoped Ruff/format. Semantic navigation icons passed existing16 focused tests and TypeScript. Dynamic primer translations and complete topic reachability are checked. Actual browser verified one drawer with unchanged composer height62px, Escape/focus return/background restoration, EN→Korean ordering, public preview private-history absence/read-only Send/public-only HTTP reads, and exact draft/scroll restoration. Live public /ready returns nullable inventory counts while private DEV retains actual counts.

Scope freeze: the user explicitly cancelled further parsing/company/year/database expansion. No acquisition API/range redesign or new general polish was implemented.
