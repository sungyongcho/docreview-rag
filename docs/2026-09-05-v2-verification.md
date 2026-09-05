# DocReview RAG v2 verification

## Final execution — 2026-09-05

The final capture and release gates are complete. Earlier checkpoint counts below are historical and are not added to these results.

- Shared Light/Dark/System controls, complete DEV/PROD manuals, capability-filtered global/contextual Help, and the accessible image viewer are verified.
- Development log navigation is connected from the app, About, and manuals at both locale routes. The single Korean outline remains a draft; no full article or translated chapter was authored.
- 60 separate real Light captures: 30 English and 30 Korean, 60 distinct hashes, no reused rows or cross-language image references. The manifest includes actual locale, viewport, DPR, time, source revision, native clip where applicable, image format/dimensions, and SHA-256.
- Frozen product source: 157 paths, digest `b767f307344ac75f7cd18383c7b14455cdacbdc9f607815305d5e0023a560561`, based on `3c83469`. Screenshot application revision: `3c83469+hotfix:7661cebd3d89fbef`.
- The isolated candidate passed 406 Web tests across 56 files and static export. TypeScript passed; final documentation checks passed 35 focused tests. Counts overlap.
- Compose contracts: 11 passed. Scoped Ruff check/format and diff whitespace checks passed. Backend/schema source was unchanged; the full backend/live-PostgreSQL suites were not repeated. Python pyright/basedpyright was unavailable.
- Each final image passed 32 page routes (30 manuals plus two draft routes), all 60 referenced asset hashes/versioned URLs, and 14 API checks. Public lists/facets are empty; an actual unpublished document returns 404, admin GETs 403, and `/ready` private counts are null.
- Actual standard-image browser requests used root `/capabilities`, `/health`, `/ready`, `/public/documents`, and `/public/documents/facets`; no obsolete `/docreview-rag-agent/api/` prefix. Public Help searches in English/Korean do not expose local/admin topics.
- Final browser checks passed persisted Light on reload, manual Light under dark OS, Dark under light OS, System following an OS change, keyboard selection, 390 px documentation headers, viewer zoom/independent scrolling, Escape/backdrop close, focus/background restoration, and bilingual guide/draft navigation. No hydration errors in final standard/HF browser sessions.
- The user later authorized minimal file access and system authentication. Existing UID 10001 ownership was preserved; UID 1000 received only file-read and parent-directory access/write ACLs. The operator check now reports `available: true`; browser recheck enables the reset action. No reset, credential/content change, chmod, or chown was executed. Scene 17 intentionally records the genuine blocked state before this repair.
- Protected files remain byte-for-byte unchanged from the saved baseline: AGENTS.md, README.md, web/next-env.d.ts, NOTES.md, and the 2026-09-04 local UI report. Existing 8000/18001/18080/17860 services and web environment values/source mounts are retained.
- No question generation, paid provider request, ingest/evaluation queue, publish, source deletion, user database reset, push, or external deployment was performed.

### Final local images

| Image | Local URL | Image ID |
|---|---|---|
| Ordinary | http://127.0.0.1:18081/docreview-rag-agent/ | `sha256:c355a23cb61885d681c5c2774d2653118c88f1e428a946d4199f28a0d2fbe4bc` |
| Hugging Face | http://127.0.0.1:17861/docreview-rag-agent/ | `sha256:5c59d5b66ec7b0e1a57d1346424b3bffe1d6cdb4b477170ae51ae9c3481bf8f5` |

Both run non-root with a read-only root filesystem, no mounts, and no provider/operator secrets. They use the image-owned Python interpreter for the same uvicorn entrypoint to avoid uv cache writes; the Dockerfiles' default `uv run` startup command was not tested under this mount-free read-only configuration.

### Remaining observations

- H01: the user-provided `QueryTranslationError` for the English NVIDIA question is queued for investigation; this request authorized queueing, not a paid reproduction or backend repair.
- H02 Help partial-permission guidance and H03 atomic-save document watching are fixed and verified. H04 local access is repaired as described above.
- H05: one hydration mismatch was recorded during initial development-log wiring. Its historical cause is unconfirmed; fresh English/Korean DEV reloads and both final static browser sessions report no new hydration error. No warning suppression was added.
- The development story is deliberately a Korean outline, visibly marked as a draft on both locale routes. Actual model execution, destructive reset, a complete Cartesian browser matrix, Python type checking, and default `uv run` container startup are not claimed.

### Verified product commit and approval history

Product commit `737b70b8fdba711f3c56543cd9c1eb659e9c4e36` (`feat(web): complete bilingual guides, themes, and image viewing`) contains exactly the 157 reviewed product paths. Its tree is `7d2f5f9c0fd3b49b210f4fe6ee8a419c04590bb1`; every product byte matches the frozen tested/image-built source. The five reports are recorded in a separate evidence-only commit. No push or external deployment was performed.

The first commit attempt was rejected by automatic approval review under AGENTS.md. The user then explicitly authorized all task commits as an exception and required commit-it staging. Execution resumed only after that direct approval; no rejection was bypassed. Exact paths and complete English messages were reviewed before staging/commit, and protected hashes were rechecked.

H01 (translation routing) and H06 (scrollbar UX) remain queued for their later implementation/investigation. H06 has not changed CSS or the frozen captures/images. H02–H04 are resolved; H05 did not recur on the final source.

## Historical checkpoint evidence

Date: 2026-09-05. This report separates current execution from historical handoff evidence.
Runtime selection was read from this task's session record: `gpt-6-astra`, reasoning `ultra`.

Latest user requirements supersede earlier capture completion: 60 separate English/Korean Light captures,
Light/Dark/System controls, mode-aware Help, complete manuals with DEV labels, an image viewer,
and a bare evidence-backed development-story outline. See
`2026-09-05-v2-final-hotfix-handoff.md` for the current scope and parallel ownership.

## Earlier application checkpoint — be3d837

| Scope | Executed check | Result |
|---|---|---|
| Application worktree | `npm --prefix web test` | 324 passed across 48 files |
| Application staged tree `057be87937c7a083c754a8b11af60ad779be787b` | `npm test` in isolated Web source | 324 passed |
| Same staged tree | `python -m pytest -q tests/scripts/test_rag_alias.py` | 22 passed |
| Same staged tree | `npm run build` | Static export passed |
| Changed Web code | `npm --prefix web run typecheck` | Passed |
| Shell test code | Ruff check and format check | Passed |
| Application diff | `git diff --cached --check` | Passed |
| Public catalog, stage records, reset/operator contracts | Focused pytest with explicit disposable catalog DB and `--require-live-postgres` | 42 passed, destructive compose reset test deselected |

The backend command selected `tests/api/test_document_catalog.py`, `tests/observability/test_stages.py`,
`tests/operator/test_wipe.py`, `tests/operator/test_service.py`, and `tests/scripts/test_local_operator.py`,
with `-k 'not disposable_compose_reset'`. The catalog test performed real SQL in a temporary schema
on the existing disposable PostgreSQL container. The source database was not modified.

Counts overlap between focused and full suites and must not be added together. The application
snapshot was committed as `be3d837` after the user directly confirmed the task's commit exception.

## Initial browser checks

- Separate verification tab; inspected existing state without sending a question or starting a job.
- Actual CSS viewport at 390 × 844 measured as 390 × 844; document/body width 390, no page overflow.
- Visible engine, local model, and preset selectors measured 44px high.
- Request inspector opened, Escape closed it, and focus returned to its trigger.
- View corpus readiness navigated to Build with an explicit Back to conversation action.

These were the initial interaction sample. Final capture and measured-width evidence is recorded in
`2026-09-05-v2-ui-polish-qa.md` and `TUTORIAL/captures.json`.

## Local connection and documentation checkpoint — c5bb137

- Web suite at this checkpoint: `npm --prefix web test` → 343 passed across 50 files; TypeScript passed.
- Local connection/inventory/diagnostics/API/caller/configuration tests → 101 passed. Nullable diagnostic-count follow-up → 58 passed; these counts overlap.
- CLI diagnostics and shell contracts → 53 passed; Ruff/format and Bash/Zsh syntax passed.
- Actual web and `rag-ollama-check` metadata checks reached Default: 3 installed models and 1 answer-capable model. No generation, model loading/download, settings save, or service change.
- Selected-server diagnostics do not replace active state. UI Use Default uses verified selection, preserving the old server on failure.
- Documentation preparation validates 30 localized documents (15 topics), 12 tutorial steps, and existing real image references. Focused documentation tests: 38 passed.
- The Ollama guide covers macOS and Linux using linked official instructions. Installation/service-configuration/model-download commands were syntax/source checked, not executed on either platform.
- Actual staged snapshot passed 343 Web tests, 154 Python/shell tests, and the static Web build.
- Initial host check found app active/queued jobs 0/0, operator running jobs 0 and reset idle. The separately approved web/operator reload was subsequently completed; see the final application checks below.

## Verification boundaries

- Registry, bilingual links, source preparation, actual browser copy/outline/images, and live editing passed.
- The approved 8000 web restart loaded the new watcher; no development `.next` output was replaced by a verification build.
- The approved 18001 host operator reload preserved its existing token, origin and port. Actual reset remains correctly blocked by local-settings file permissions; neither permissions nor data were changed.
- Python `pyright`/`basedpyright`: unavailable. No Python type-check pass is claimed.
- Destructive reset, paid provider execution, external deployment/push, and credential/permission changes: not run.

## Frozen-scope application checkpoint — 3c83469

- Full Web suite:374 passed across52 files; TypeScript passed. Navigation-icon addition subsequently passed16 focused tests and TypeScript.
- Public release app tests:17 passed; Ruff and format passed for the two changed Python files.
- Actual staged tree `ab290d22cb239f5625428befab649dd224cf4642`: 374 Web tests, 17 release tests, and static Web export passed in an isolated checkout. The live development output was preserved.
- Actual /ready HTTP200: private DEV reports30 documents/22,367 chunks; public-header response returns null for documents/chunks/embedded/pending/writable. Database/schema/readiness remain available.
- Actual single Review settings dialog:720px at1440 viewport; composer stayed62px high; Escape closed the only dialog, removed background inert attributes, and restored its trigger focus.
- Actual language buttons render EN before Korean.
- Actual Production preview: iframe had no prior private question, Send disabled, read-only notice visible. Captured requests were GET capabilities/health/public documents; no /admin or /ready calls. Exit restored the temporary draft and original scroll exactly, then the original draft was restored.
- Web and operator reload were directly authorized and completed, preserving8000/18001, existing operator token/origin, source mounts, and the database. The new Ollama document was live-edited and restored byte-for-byte; both changes appeared automatically without page reload.
- Documentation: copy returned exact command text, language switching retained ollama#connect,390px tables scrolled within337px containers, mobile navigation expanded, and the real existing image opened full size in a separate tab.

No dev corpus-growth feature was added after the user's scope freeze.

## Final documentation and visual evidence

- 30 scenes, 37 actual images (30 English and 7 Korean); 23 Korean entries explicitly reuse an English capture. All 60 manifest entries distinguish captured versus reused evidence.
- All 37 images were visually inspected. Company/diagnostic headings and the Add server form were reframed; the blocked reset summary was cropped without altering pixels or showing machine-specific remediation paths.
- Actual image bytes are preserved: 36 JPEGs and one PNG, with matching file extensions.
- Conversation EN/KO and English Ollama documentation were measured at 390, 768, 1280, 1440, 1920, 2560 and 3440 CSS pixels without root overflow. The 390×844 light/reduced-motion conversation, navigation and full-screen settings panel were visually checked.
- This is a scoped matrix sample, not the complete Cartesian product of languages, themes, states and widths. Browser zoom and every pointer/keyboard combination were not repeated in the final pass.
- Existing successful and failed review records are historical evidence. Evaluation comparison is actually empty, new evaluation setup was not queued, and the prepared embeddings are deterministic. No retrieval-quality benchmark is implied.

## Final static production images

Final source/image IDs and browser network evidence are added after the ordinary and Hugging Face image checks complete. Previous previews at 18080/17860 remain historical and are preserved.

## Additional availability/theme/viewer checkpoint

- The joined Web suite passed 398 tests across 55 files; TypeScript passed.
- Focused checkpoints passed 88 Help/contextual Help/ServiceShell/Measure tests, 56 theme/app badge/policy tests, and 40 viewer/Markdown/navigation tests. Counts overlap.
- Browser QA caught a real compiler issue: choosing Light changed theme state but colors remained dark. Two explicit source color-scheme selectors corrected the LightningCSS fallback behavior. Six focused compiler/theme tests and TypeScript passed afterward. Actual Light under dark OS rendered white, Dark under light OS rendered dark, and System followed the OS. The full suite and static images were not rerun after that small correction.
- Actual Documents and Indexing page labels agree with their navigation badges, while both retain all 15 manual links.
- The actual image viewer showed its authored Korean caption, wheel zoom and larger scroll ranges. Backdrop close removed all background inert attributes and returned focus to the image trigger.
- An additional node --test invocation was invalid because the tutorial suites use Vitest. The integrated Vitest suite includes those tests; no source change was needed for the invocation error.

## Handoff boundary

The user chose to carry incomplete and unstarted work to the next task. The 60 Light captures,
final Docker builds, story rendering/About links, staging and commits were not started.
The latest portable handoff records the remaining browser checks and implementation boundaries.
