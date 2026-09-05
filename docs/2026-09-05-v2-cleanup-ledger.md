# DocReview RAG v2 cleanup ledger

## Final scoped cleanup — 2026-09-05

- Preserved the existing uncommitted theme/viewer/availability work. The only new functional correction from joined-source review was the missing evaluation-workspace prerequisite in snapshot Help; its regression failed before the fix and passed afterward.
- Added only requested development-outline rendering/navigation and the build/dev-source inclusion it requires. The existing Korean outline bytes were preserved; a temporary whitespace-only atomic-save test was restored exactly. Directory mounting now observes editor replacement saves while retaining the existing tutorial/source mounts and runtime environment.
- Replaced the superseded captures with 60 independent realLight images; image references, captions, alt text and provenance were reconciled against actual scenes. Final reuse and locale-crossing counts are 0;94 manual image references resolve to 60 final assets. Internal links 311 and legacy targets 60 pass.
- Reviewed task-owned diffs for unrelated deletion/import changes and protected-file absorption. No backend/schema source, learning shim, package facade, or cross-test helper layout was added. The changed Python build helper retains documented functions and passes Ruff check/format. No broad formatting/dependency upgrade/stash/reset was used.
- Frozen product 157-file digest matches the isolated tested and image-built source.406 Web tests, TypeScript,35 focused documentation tests,11 Compose tests, static export, both image builds, and per-image 32 routes/60 assets/14 APIchecks pass. Python type checking is unavailable; full backend/liveDB tests were not repeated for this web/docs/build scope.
- Later user-authorized runtime ACL repair is local operational state, not committed configuration or credentials. No database reset/data deletion followed. H01 remains an investigation queue item; H05 is historical and not reproduced on the final source.
- The five protected files are excluded from staging. Two earlier unused mobile QA captures are retained untracked, outside the final 60 and outside the product commit.

### Verified product commit and approval history

Product commit `737b70b8fdba711f3c56543cd9c1eb659e9c4e36` (`feat(web): complete bilingual guides, themes, and image viewing`) contains exactly the 157 reviewed product paths. Its tree is `7d2f5f9c0fd3b49b210f4fe6ee8a419c04590bb1`; every product byte matches the frozen tested/image-built source. The five reports are recorded in a separate evidence-only commit. No push or external deployment was performed.

The first commit attempt was rejected by automatic approval review under AGENTS.md. The user then explicitly authorized all task commits as an exception and required commit-it staging. Execution resumed only after that direct approval; no rejection was bypassed. Exact paths and complete English messages were reviewed before staging/commit, and protected hashes were rechecked.

H01 (translation routing) and H06 (scrollbar UX) remain queued for their later implementation/investigation. H06 has not changed CSS or the frozen captures/images. H02–H04 are resolved; H05 did not recur on the final source.

## Historical cleanup checkpoints

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

## Guided local connections and documentation unit — committed checkpoints

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
- Web diagnostics use safe transport classification and remediation identifiers. CLI reads the structured report while retaining the self-contained metadata fallback for older images. Neither path executes server-supplied commands.
- Named-server storage retains direct imports and existing atomic write/immutable connection architecture. No SQL migration or dependency change.

Verification before snapshot:

- Web 343 passed across 50 files; TypeScript passed. Initial missing Connect/Next steps translations were corrected and retested.
- Backend/caller/configuration suites: 101 passed; nullable-count follow-up: 58 relevant tests passed (overlapping, not additive).
- CLI/shell: 53 passed, including null-versus-measured-zero formatting. Scoped Ruff/format and shell syntax passed.
- Documentation preparation: 30 documents and one existing real image; all internal targets, registry entries, and bilingual step anchors passed.
- Actual Web and CLI Default diagnosis: reachable, 3 installed models, 1 answer-capable; no inference or configuration write.
- Existing protected changes were preserved and excluded from the committed unit. No broad cleanup, blanket staging, data reset, permission change, or provider generation call.

## Consolidated interaction and production preview unit — 3c83469

Completed user-requested changes: two-screen Help with four inline task filters and a single passive target highlight; one Review settings drawer; compact SVG request inspection; EN-first language controls; prominent company/FY identity; semantic documentation icons; an isolated read-only public preview that retains DEV work; and public readiness redaction.

Cleanup: removed obsolete Help badge/triangle/accordion and inline-editor styles; removed duplicate Filters/RAG entry points and the redundant Custom link; reused registry metadata and existing icon library. Preview uses the existing ServiceShell renderer in an isolated document, shared API/storage boundaries, and active polling controls. No dependency, corpus, acquisition-range, or database changes.

Verification: the same-source staged snapshot for `3c83469` passed 374 Web tests, 17 release tests, TypeScript, and the static Web build; scoped Ruff/format passed. Semantic navigation icons passed existing 16 focused tests and TypeScript. Dynamic primer translations and complete topic reachability are checked. Actual browser verified one drawer with unchanged composer height 62px, Escape/focus return/background restoration, EN→Korean ordering, public preview private-history absence/read-only Send/public-only HTTP reads, and exact draft/scroll restoration. Live public /ready returns nullable inventory counts while private DEV retains actual counts.

Scope freeze: the user explicitly cancelled further parsing/company/year/database expansion. No acquisition API/range redesign or new general polish was implemented.

## Final documentation and capture closure

Completed code checkpoints: `be3d837`, `c5bb137`, `a4d3d1b`, and `3c83469`. Historical 324/343-test entries above belong to their own checkpoints and are not the latest full-suite result or additive totals.

The final capture set contains 30 English scenes and 7 separately captured Korean scenes: 37 real image assets, 36 JPEG and 1 PNG. The 60 locale slots consist of 37 captured slots and 23 explicitly recorded English-image reuses. Reuse is not counted as another Korean capture. The documentation agent is validating the final asset links and bilingual captions; no placeholder image is introduced.

Measured Review EN/KO and Documentation EN widths were 390, 768, 1280, 1440, 1920, 2560, and 3440 CSS px with no root horizontal overflow. The 390px light/reduced-motion/sidebar state and 390 × 844 full-screen Review settings were visually checked. These bounded observations do not claim every theme, state, zoom, or sidebar combination passed.

The separately authorized web/operator reload is complete, preserving ports 8000 and 18001, existing operator credentials/origin, source mounts, and the database. Runtime deletion remains blocked by file permissions; no permission or data change was made.

Final ordinary/HF image builds and actual image browser/API/docs verification remain to be completed with the integrated capture assets. The portable plan contains the single placeholder for final image IDs, addresses, source revision, and results; the verification report will retain the executed evidence.

No new feature implementation, corpus growth, acquisition/year expansion, or general polish is authorized after the scope freeze. Remaining cleanup is limited to the final documentation/capture/image-verification unit and its explicit commit paths. Protected files remain excluded.

## Latest hotfix handoff (uncommitted)

Shared availability badges, capability-aware global/contextual Help, complete manual visibility,
Light/Dark/System controls, the image viewer and external new-tab references are implemented.
The integrated source passed 398 Web tests and TypeScript. The later LightningCSS correction
passed six focused compiler/theme tests and TypeScript, followed by actual browser color checks.

The development story remains a bare outline for the user to edit. No full article was written.
At the user's handoff boundary, the 60 Light captures, remaining browser checks, story rendering
and navigation, final images, cleanup/staging/commits remain pending. Earlier image reuse is
superseded. No new files were staged or committed; protected foreign work is preserved.
