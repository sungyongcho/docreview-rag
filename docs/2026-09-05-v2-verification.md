# DocReview RAG v2 verification

Date: 2026-09-05. This report separates current execution from historical handoff evidence.
Runtime selection was read from this task's session record: `gpt-6-astra`, reasoning `ultra`.

## Current passed checks

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

## Browser evidence before final capture

- Separate verification tab; inspected existing state without sending a question or starting a job.
- Actual CSS viewport at 390 × 844 measured as 390 × 844; document/body width 390, no page overflow.
- Visible engine, local model, and preset selectors measured 44px high.
- Request inspector opened, Escape closed it, and focus returned to its trigger.
- View corpus readiness navigated to Build with an explicit Back to conversation action.

These checks are a limited interaction sample, not the completed visual matrix. Final captures follow
documentation validation and are listed in `TUTORIAL/captures.json`.

## Local connection hotfix and documentation checks

- Full current Web suite: `npm --prefix web test` → 343 passed across 50 files; TypeScript passed.
- Local connection/inventory/diagnostics/API/caller/configuration tests → 101 passed. Nullable diagnostic-count follow-up → 58 passed; these counts overlap.
- CLI diagnostics and shell contracts → 53 passed; Ruff/format and Bash/Zsh syntax passed.
- Actual web and `rag-ollama-check` metadata checks reached Default: 3 installed models and 1 answer-capable model. No generation, model loading/download, settings save, or service change.
- Selected-server diagnostics do not replace active state. UI Use Default uses verified selection, preserving the old server on failure.
- Documentation preparation validates 30 localized documents (15 topics), 12 tutorial steps, and existing real image references. Focused documentation tests: 38 passed.
- The Ollama guide covers macOS and Linux using linked official instructions. Installation/service-configuration/model-download commands were syntax/source checked, not executed on either platform.
- Initial host check found app active/queued jobs 0/0, operator running jobs 0 and reset idle. Web/operator reload permission requested separately; recheck before any approved restart.

## Remaining verification and boundaries

- Registry, bilingual links and source preparation passed; actual browser copy/outline/images and live editing remain pending.
- Current 8000 wrapper loaded the previous watcher before these source changes. Its cached callbacks cannot
  adopt the new watcher without restarting that process. Preserve it; verify the new wrapper in an isolated dev instance.
- Final ordinary/HF rebuilds and actual browser API requests: pending. Earlier running preview image IDs are historical.
- Host operator on 18001 still needs separately authorized reload; commit approval does not authorize it.
- Python `pyright`/`basedpyright`: unavailable. No Python type-check pass is claimed.
- Destructive reset, paid provider execution, external deployment/push, and credential/permission changes: not run.

## Frozen-scope final application checks

- Full Web suite:374 passed across52 files; TypeScript passed. Navigation-icon addition subsequently passed16 focused tests and TypeScript.
- Public release app tests:17 passed; Ruff and format passed for the two changed Python files.
- Actual /ready HTTP200: private DEV reports30 documents/22,367 chunks; public-header response returns null for documents/chunks/embedded/pending/writable. Database/schema/readiness remain available.
- Actual single Review settings dialog:720px at1440 viewport; composer stayed62px high; Escape closed the only dialog, removed background inert attributes, and restored its trigger focus.
- Actual language buttons render EN before Korean.
- Actual Production preview: iframe had no prior private question, Send disabled, read-only notice visible. Captured requests were GET capabilities/health/public documents; no /admin or /ready calls. Exit restored the temporary draft and original scroll exactly, then the original draft was restored.
- Web and operator reload were directly authorized and completed, preserving8000/18001, existing operator token/origin, source mounts, and the database. The new Ollama document was live-edited and restored byte-for-byte; both changes appeared automatically without page reload.
- Documentation: copy returned exact command text, language switching retained ollama#connect,390px tables scrolled within337px containers, mobile navigation expanded, and the real existing image opened full size in a separate tab.

Final capture matrix and actual production image checks are recorded below when completed. No dev corpus-growth feature was added after the user's scope freeze.
