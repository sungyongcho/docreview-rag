# DocReview RAG v2 — portable final-hotfix execution prompt

> COMMIT UPDATE: product commit `737b70b8fdba711f3c56543cd9c1eb659e9c4e36` has been created after the user explicitly renewed the task-specific agent-commit exception and approved commit-it staging. Its tree matches the frozen tested and image-built source. Reports are kept in a separate evidence-only commit; no push/deployment. H01 and H06 remain queued. The earlier automatic rejection was respected until this explicit approval.

> Execution update, 2026-09-05: the60realLightcaptures, minimal story wiring, final static export and both local image/browser gates are complete. See the final verification report for source/image identities and commit results. The original continuation contract below is retained as history. Later direct user approval allowed only the scoped runtime-file ACL access repair via system authentication; ownership, credentials and data were preserved. H01 is queued for later investigation, H06 is queued for scrollbar UX, H02–H04 are resolved, H05 did not recur on the final source.


Updated: 2026-09-05. This is a self-contained continuation contract for a new task, not permission to restart completed work.

**Handoff state:** the user stopped the originating task after the current hotfix work and chose to carry unfinished and unstarted work forward. The originating task did not start the 60-capture pass, final image builds, story rendering/navigation, staging or commits. **The receiving task should execute the remaining gates below**, preserving the completed uncommitted hotfixes and reusing valid evidence. The user requested GPT-6 Astra with **ultra** reasoning. Confirm the actual task model/effort where available; a prompt does not switch the runtime. Do not silently substitute a model.

## Outcome and exact scope

Finish the current DocReview RAG hotfixes, then recapture the bilingual tutorials, clean only the changed scope, verify the static release images, and commit coherent verified units. Maintain the existing restrained monochrome/ASCII design and English/Korean experience. The target audience includes France, English-speaking EU/North America, Korea, recruiters, developers, IT/PMs, and first-time older users.

The user cancelled expanding parsing, companies, fiscal-year ranges, acquisition APIs, and database size. **Do not reactivate that work.** Later explicit requests below are the final hotfix scope; do not conduct another general redesign or invent adjacent improvements.

1. Keep the completed Default local-server selector, Add a server flow, failure-safe connection replacement, Web/CLI metadata diagnostics, and macOS/Linux Ollama guide.
2. Keep two-screen Help (home → topic), direct topics/search, one Back action, and one passive target highlight. No numbered circle/triangle overlays. Preserve the single Review settings drawer, compact Inspect request icon, EN-first language order, prominent company/FY identity, and semantic documentation icons.
3. **DEV availability:** use a restrained wrench SVG and DEV label at restricted app entry points. Public document reading, permitted presets/filters/questions, and published snapshot reading must not be mislabeled DEV-only. Visibility and navigation continue to follow actual effective capabilities; badges do not grant permission.
4. **Documentation remains complete in every deployment:** render all 15 topics × 2 locales, navigation, sections, screenshots, and links in DEV and PROD. The shared registry's `developmentOnly` field is descriptive only. Restricted instructions use `[!DEV]` callouts. Mixed pages such as Documents show **Shared guide / 공통 안내** at the top; dedicated local-operation guides show **DEV only / 개발 모드 전용**. The sidebar and page header must agree. Never filter documentation by runtime permissions.
5. **Help differs by permissions:** public/production-preview Help recommendations, group rows, EN/KO search, related topics, selected details, and Go to control actions must not expose unavailable admin/local controls. Keep public reading and permitted controls discoverable. Apply the same policy to the smaller contextual WorkflowHelp consumer, not only global Help. Plain full-manual links may open any documentation page.
6. **Theme control:** one shared Light / Dark / System icon control in both the app and documentation. Persist the user's explicit choice, track OS changes in System, avoid first-paint/hydration mismatch, support keyboard and accessible labels, and keep narrow headers usable. Production UI preview must not overwrite DEV theme/preferences; respect its memory-only storage boundary.
7. **Image viewer:** inspect `/home/wwaya/Documents/sungyongcho.github.io` read-only and the actual `https://sungyongcho.com/logs` article viewer. Adapt its image scrolling, bottom caption, and empty-backdrop click-to-close mechanics to DocReview's design. Use the current document language's caption. Preserve keyboard Escape, focus return, background interaction protection, independent image scrolling, narrow-screen usability, and access to the original asset. Do not modify the portfolio repository.
8. **Final captures must be Light and fully bilingual:** capture every one of the 30 planned scenes twice, once after switching the actual UI to English and once to Korean: **60 real captures**. Set the new theme control explicitly to Light. Do not reuse English images in Korean guides. Do not translate screenshot pixels, composite screenshots, or fabricate data. Update captions, alt text, image references, and provenance from the actual scene.

## Next queued stage: development-story skeleton and navigation

After the active availability/Help/theme/viewer hotfixes are complete, wire a **Development log / 개발 기록** area without authoring full articles. **Strict authoring boundary: leave only a very bare outline and brief storyline. The user will read, edit and flesh it out personally. Do not expand prose, invent examples, research additional content, write promotional copy, or spawn another writing agent. Minimize token use and implement only the requested file/rendering/navigation connections.** The single initial source is `docs/DEVELOPMENT_STORY_OUTLINE.md`, created at the user's request. It separates concept study, implementation choices, evidence-backed development journal entries, and honest AI-assisted UI/product refinement.

Structural reference: `https://sungyongcho.com/gomoku/docs` was inspected live. Minimax/AlphaZero demonstrate a concept-to-implementation-to-lessons structure. Reserve that structure for the user’s future parsing/chunking/embedding/search notes; do not write those chapters now or repeat the research.

- Reuse the existing documentation directory/Markdown renderer; initially render the one outline file with a visible outline/draft label. Do not write full study chapters or diary prose now.
- Provide **User guide / 사용 가이드** and **Development log / 개발 기록** under a discoverable **Guides & development / 가이드와 개발 기록** app entry. Link the story from About and the documentation area without breaking current docs/tutorial URLs.
- Keep the story and all manuals readable in DEV/PROD. DEV badges describe executable actions, not reading permission.
- Treat rendering/navigation wiring as a bounded follow-on lane only after shared renderer/theme files are handed back. Verify both locale navigation, About entry, static export, and absence of broken source links.
- Full chapter writing is a later content task. Do not advertise an outline as a completed technical publication.
- The user additionally required verification against all available branch commit history and related Codex/Claude logs. Search only project-related conversations, deduplicate imported/forked history, distinguish direct user statements from assistant summaries, and do not publish private conversation paths or credentials. Git authorship alone does not prove who typed each line. Keep a compact private source map and use only supported storyline points.
- Put actual identified study links under a final **References** heading. Do not convert an AI-recommended course into a completed course. The Markdown renderer opens external HTTP(S) references in a new tab with safe rel attributes; internal document/anchor navigation stays in the same tab.
- Initial evidence already found: all 9 local branch refs and 251 reachable commit entries indexed; 326 project-matching Codex session/archive files searched, containing 2,525 unique user messages. Direct June 11/18/24 course-progress statements, an August 24 zero-branch typing/reconstruction statement, an August 26 module-3 review statement, and August 27/28 orphan reassembly requests were found. Historical `docs/lecture-videos.md` and `new-docs/06-lecture-notes.md` blobs recovered read-only. Reuse this evidence rather than repeating scans; The Claude audit also completed: 1,401 project-related JSONL files and 406 project-tagged history prompts were searched; its private source map has 16 dated entries and 7 original user-supplied resource URLs. Duplicates, sidechains and compact summaries were separated. The video completion caveat is preserved: one course video was stopped after the first 30 minutes, not completed. Counts are this audit snapshot, not all possible deleted logs.

## Repository and authorization boundaries

- Repository: `/home/wwaya/Documents/docreview-rag-agent`; writable branch: `assemble`.
- Read the live root `AGENTS.md`, applicable DocReview workflow skill, and commit-it skill. Scope/permission history below does not permit unrelated changes.
- The user directly approved an exception allowing agent staging/commits for this task after an initial automatic review rejection. The user separately approved necessary web/operator restarts. These are distinct approvals. If a new execution environment rejects an action, report that exact rejection; never rewrite instructions or bypass the reviewer.
- No push or external deployment. Final Docker previews are local only. No paid model calls, actual user DB reset, source-filings deletion, permission/ownership/ACL changes, credential changes, shell startup edits, or model/context/token tuning to improve apparent timing.
- Preserve the DEV service on **8000**, host operator **18001**, their existing configuration and source mounts, and live documentation editing. The approved web/operator reload already happened. Do not repeat it without an actual need and idle-state check.
- Protected foreign state: `AGENTS.md`, `README.md`, `web/next-env.d.ts`, `NOTES.md`, `docs/2026-09-04-local-development-ui-report.md`. Never stage, reset, stash, format, or absorb it. Baseline hashes are in `/tmp/docreview-v2-protected-sha256.json` if still available. Do not read old NOTES entries.
- No blanket `git add .`, reset/revert/stash, amend/rebase, broad formatting, dependency upgrades, or edits to `new`/`zero` branches. Inspect each target's dirty state before editing; current task-owned changes must also be preserved.

## Completed checkpoints — reuse their evidence

| Commit | Completed outcome | Verification at that actual snapshot |
|---|---|---|
| `be3d837` | Shared FIGlet Small full/DR branding; hidden overlay activity guards; accurate Pin meaning | 324 Web tests, 22 shell tests, static export |
| `c5bb137` | Default/named local servers, metadata-only diagnostics, 15 paired docs and 12 tutorial steps | 343 Web tests, 154 Python/shell tests, static export |
| `a4d3d1b` | Korean diagnostic labels and restrained setup links | 22 focused Web tests, TypeScript |
| `3c83469` | Two-screen Help, unified settings, request icon, company/FY, EN first, doc icons, isolated public preview, public readiness redaction | 374 Web tests, 17 release tests, static export of staged tree `ab290d22cb239f5625428befab649dd224cf4642` |

These are historical checkpoints, not proof for new edits. Do not add overlapping test counts. Backend source has not needed another change for the current theme/viewer/availability hotfixes.

Actual existing-state evidence: private DEV has 30 documents and 22,367 deterministic embedded chunks; public published snapshot count is zero, so an empty public catalog is correct. A metadata-only Ollama check found 3 installed models and 1 answer-capable `gemma4:e4b`; no inference was run. Existing saved successful/failed reviews can be inspected. Current evaluation comparison is empty; a new evaluation setup was inspected but not queued. Do not invent measurements or publish data for screenshots.

Actual reset eligibility remains blocked by local-settings permissions. The approved operator reload resolved the old-code issue, not the permissions issue. No actual reset or chmod/chown was performed. Python pyright/basedpyright was unavailable; do not claim a Python type-check pass.

## Parallel process: one owner per file, one browser controller

Use at most **four concurrent agents including the coordinator**. In a new task, give workers only the relevant paths, required behavior, known evidence, and edit ownership; do not fork the entire conversation or re-run the same repository inventory in every worker. Keep all workers on the requested Astra/ultra configuration when delegation supports it. A bounded completed task should stop, not search for more work.

| Owner | Independent lane | Files / contract |
|---|---|---|
| Coordinator | Shared availability semantics, integration, real UI QA, captures, final build/commit gates | `development-badge.*`, documentation registry/page availability/CSS, capture manifest/assets, four QA/verification reports and this handoff. Only coordinator controls the browser. |
| A — theme/app | Light/Dark/System, app-only DEV entry badges, ServiceShell integration | Theme storage/provider/control/bootstrap, root layout, app headers and preview theme isolation. Own app workspace badge files. DocumentationPage header theme hunk only; coordinate before touching another owner's area. |
| B — Help | Effective-capability topic projection and DEV labels | HelpOverlay, help-content/search/primer, contextual WorkflowHelp, their tests, necessary translation keys. A owns ServiceShell/Measure caller props unless explicitly handed over. |
| C — docs/viewer | Fully visible bilingual instructions and portfolio-style viewer | Topic Markdown, new viewer component/CSS/tests, tutorial renderer image callback and type declaration. Do not edit capture files while the coordinator is photographing. |

Before assigning, inspect `collaboration.list_agents` in the current task and reuse existing workers; do not duplicate active lanes. Existing names are `branding` (A), `interaction` (B), and `docs_architecture` (C). New tasks cannot assume these agents survive; recreate only unfinished lanes. Ask each worker for a short outcome, exact touched paths, checks, and remaining blocker. Avoid full diff/context dumps.

Shared-file protocol: announce exact file/hunk ownership, make the owning worker integrate caller changes, and hand ownership back when done. No two writers should race on ServiceShell, DocumentationPage, tutorial-markdown, the registry, translations, captures.json, or reports.

### Join gates and economical verification

1. Inspect current HEAD/status and this handoff. Reuse passing unchanged evidence; inspect only the relevant definitions/callers/tests.
2. Finish A/B/C in parallel. Each runs focused behavioral tests for its own change. Do not run the full Web suite or image builds simultaneously in every lane.
3. Coordinator reviews the combined diff for permission leaks, stale hidden Help paths, theme storage/preview isolation, all-doc visibility, image-viewer focus/backdrop/scroll behavior, and preservation of foreign state.
4. Run one integrated Web suite and TypeScript after source stabilizes; run relevant tutorial preparation/watch tests. Existing Python checks need repeating only if backend code or its contract changes.
5. Verify actual DEV and public-preview UI, both locales/themes, keyboard/focus and mobile headers. Fix only defects observed in this scope. Record before/after evidence without starting a new polish campaign.
6. **Only now capture all 60 Light scenes.** One browser owner prevents viewport, locale, theme, focus, clipboard, and saved-state races. Workers may independently validate completed files, but must not alter the manifest/assets during capture.
7. C integrates final references/captions and validates registered/legacy links, image signatures/dimensions/hashes, complete bilingual pairs, and absence of `reused` rows. Coordinator freezes assets and sends one `captures-final-ready` signal.
8. Run final isolated static export plus ordinary/HF local images against the same frozen source. Do not rebuild before the capture join gate or repeat a successful build without changed source or a new failure.
9. Prepare exact individual staging paths and a complete English Conventional Commit body, verify the actual staged snapshot, then commit within the user's exception. A final evidence-only report commit may follow. Preserve all protected hashes; no push.

## Capture map and reliable provenance

The existing manifest has 60 slots but currently only 37 real images and 23 explicit English reuses; many are dark. **This set is superseded as final evidence by the user's Light/bilingual requirement.** Keep it as temporary evidence until replacements exist; do not declare capture completion from those rows.

Scene IDs 01–30: system status; pipeline; real Samsung FY2022 document; valid SEC acquisition inputs; manifest ingest; deterministic embeddings; BM25; historical job; unexecuted search inputs; Golden question; unqueued evaluation setup; actual empty comparison; Default connection; browser data controls; saved cited answer; saved run trace; blocked reset summary; scope explanation; request inspector; failed legacy performance; Help home; company/year filters; About; actual connection diagnosis; unsaved Add server; Help topic; single Review settings; public UI preview; documentation menu; preset explanation.

- Switch the actual UI language before each shot and confirm visible translated chrome. Stored source text, company names, IDs and logs stay in their original language.
- Set Light through the actual control. Record `document_locale`, actual `locale`, Light theme, measured CSS viewport, sidebar state, source revision, route, time, asset path and real caption. All 60 entries must have `capture_status: captured`; clear reuse metadata only after its real replacement is saved.
- Use actual existing records or honest empty/blocked forms. No Send, evaluation queue, ingestion, publish, reset, model download/load, or settings save solely to manufacture a scene.
- The previous JPEG screenshot API sometimes returned scaled/surface-sized images despite a `.png` name. Check actual file signatures and pixel dimensions. Prefer native CDP JPEG/PNG screenshot bytes after verifying viewport/DPR/visualViewport and theme. Never infer CSS dimensions from image pixels. Preserve exact image bytes and correct extensions.
- A reset screenshot may be a documented native crop of the blocked summary to omit machine-specific remediation paths. Do not edit pixels. Record the clip. Do not imply reset success.
- Existing real browser tabs may survive: IAB IDs 5 (127.0.0.1 DEV), 6 (localhost saved result), 7 (documentation). Discover live tabs rather than assuming IDs/bindings survive. Do not operate the user's unrelated Chrome tabs.
- All temporary viewport/media/theme/language changes should be restored after testing, except an intentionally left final deliverable tab. Avoid touching clipboard unless needed; preserve it when testing copy.

## Final static release checks

Old local previews on 18080/17860 are historical; preserve them. Planned new loopback-only containers: `docreview-v2-final-preview` on18081 and `docreview-v2-final-preview-hf` on17861. Recheck names/ports before creating. Existing disposable `docreview-v2-catalog-test` contains a clone with 30 documents and no published snapshots; reuse only its established safe DB settings without printing credentials or writing data. Never connect tests to the user DB by guessing a DSN.

```bash
.venv/bin/python scripts/check_web_build.py
docker buildx build --builder limited --load -f docker/Dockerfile -t docreview:v2-preview .
docker buildx build --builder limited --load -f deploy/huggingface/Dockerfile -t docreview:v2-hf-preview .
```

- Isolated builds must not overwrite live `web/.next`; copy dependencies into the snapshot instead of symlinking outside it when Turbopack requires an internal path.
- Run mount-free readonly PROD previews with no provider/operator keys and no dev watcher/reload. No external deployment.
- Verify every one of 30 docs routes and all final referenced assets/hashes in **both images**, including DEV-only manuals/labels still visible.
- Inspect actual browser requests: root `/capabilities`, `/health`, `/public/documents` etc., not the obsolete `/docreview-rag-agent/api/...` prefix. Verify empty public list/facets, unpublished detail404, admin403, private count redaction, and no source mounts/secrets.
- Inspect actual lightbox/theme/Help behavior in a final image, not only the DEV server. Record image IDs, source revision and local URLs.

## Current work and final reporting

Current HEAD remains `3c83469`; all changes below are **uncommitted**. No staging, final ordinary/HF build, or 60-capture pass was started after the user's handoff decision.

| State | Work | Evidence and remainder |
|---|---|---|
| Implemented and tested | Shared DEV badge, restricted app entry badges, complete manual visibility and accurate page labels | Actual Documents and Indexing headers agree with navigation; both retain 15 links. |
| Implemented and tested | Global and contextual Help capability filtering | 88 focused tests and the integrated suite passed. Final public Help browser verification remains. |
| Implemented and tested | App/docs Light, Dark and System control with preview isolation | 56 focused tests passed. Browser QA found LightningCSS ignoring manual theme selection; two standard CSS selectors corrected it. Six compiler/theme tests and TypeScript then passed. Actual Light under dark OS renders white, Dark under light OS renders dark, and System follows the OS. Mobile, first-paint and preview browser checks remain. |
| Implemented and tested | Image viewer and external reference links | 40 focused tests passed. Actual Korean caption, wheel zoom from 100% to 190%, scroll ranges, backdrop close and focus/background restoration passed. EN/mobile, Escape, modified click and external new-tab browser checks remain. |
| Integrated checkpoint | Joined source before the tiny theme compiler correction | 398 Web tests across 55 files and TypeScript passed. No full-suite run after the final two CSS selectors is claimed. Tutorial preparation reports 30 docs and 37 images. Use Vitest for tutorial tests, not node --test. |
| Minimal outline prepared | Development story | `docs/DEVELOPMENT_STORY_OUTLINE.md` contains only chronology and References. The user will write the full text. Rendering/About/navigation wiring has not started. |
| Superseded as final evidence | 37 real screenshots and 23 EN reuses, mixed themes | Keep this checkpoint provenance. The required 60 separate Light captures and corresponding references/captions have not started. |
| Not started | Final release and commits | Static image builds, release browser checks, final scoped cleanup, staging and commits follow the next task's join and capture gates. |

Private research artifacts: `/tmp/docreview-story-codex-git-evidence.md`, `/tmp/docreview-story-codex-log-files.txt`, `/tmp/docreview-story-codex-selected.json`, `/tmp/docreview-story-all-commits.txt`, and `/tmp/docreview-story-claude-evidence.md` (completed). These are local supporting notes, not public manual assets. Do not copy raw conversation paths into the rendered story.

Current workers have stopped implementation. Reassign only unfinished verification/integration work; do not rebuild completed features. Read current Git status before continuing.

Update this status and the four existing reports before final handoff:
- `docs/2026-09-05-v2-ui-polish-portable-plan.md`
- `docs/2026-09-05-v2-ui-polish-qa.md`
- `docs/2026-09-05-v2-cleanup-ledger.md`
- `docs/2026-09-05-v2-verification.md`

Final response: concise Korean with actual completed behavior, commit hashes/subjects, passed/failed/not-run/blocked checks, Light bilingual screenshot examples, manual/manifest/report links, final local preview URLs and image IDs, protected-file preservation, and real remaining limitations. Do not call it fully complete while the60realLightcaptures or finalreleasebrowserchecks remain pending. Do not create a new task or push/deploy merely because this prompt is portable.
