# DocReview RAG v2 visual and interaction QA

## Final Light capture and interaction pass — 2026-09-05

All 60 final captures were individually inspected. 58 original JPEGs are 2880×2000 pixels; the two native reset crops are 1296×508(EN) and 1296×506(KO). The measured CSS viewport is 1440×1000 with DPR 2. Screenshot pixel size is not used to infer viewport size. Scene 29 uses the native viewport clip; scene 17 omits machine-specific remediation commands. No pixel translation, compositing, generated scene, English reuse, or fabricated execution result was used.

Retakes corrected capture-tool surface tiling/scaling, the visible SEC action in scene 04, the complete selected Golden source span/hash in scene 10, the unsaved server form/action in scene 25, tooltip reopening after language changes in 18/30, and a transient development rendering indicator in 06 KO. Final images show the requested controls and real translated chrome. Source text, issuer names, identifiers and stored diagnostics retain their original language.

Actual behavior checked during capture and final-image QA: Help Back and Go to control (focus returned to Auto), one settings drawer with Escape/background/focus restoration, metadata-only connection diagnostics, read-only public preview with DEV preference isolation, complete 15-link manual menus, DEV versus shared page labels, direct About/draft navigation, original-image modified click, bilingual viewer captions, zoom, independent scrolling, backdrop/Escape close, and 390 px header geometry. Final PROD captures show actual empty public lists/facets; the saved 119.6 s run and 31 ms failure remain explicitly historical.

A user-provided 4.32 s QueryTranslationError is separate from scene 20's 31 ms legacy failure and is queued asH 01 in the portable plan. The user subsequently approved the least-privilege access repair forH 04; the reset eligibility check and actual browser now pass, but reset was not executed. Scene 17 is explicitly captioned as the pre-repair blocked state. H05's early wiring-time hydration error did not recur in fresh DEV or final static-image sessions.

The final source, both image IDs, route/asset/API checks, unrun checks and runtime-command limitation are recorded in [verification](2026-09-05-v2-verification.md). Previous 37-image evidence below is superseded, retained only as checkpoint history.

### Verified product commit and approval history

Product commit `737b70b8fdba711f3c56543cd9c1eb659e9c4e36` (`feat(web): complete bilingual guides, themes, and image viewing`) contains exactly the 157 reviewed product paths. Its tree is `7d2f5f9c0fd3b49b210f4fe6ee8a419c04590bb1`; every product byte matches the frozen tested/image-built source. The five reports are recorded in a separate evidence-only commit. No push or external deployment was performed.

The first commit attempt was rejected by automatic approval review under AGENTS.md. The user then explicitly authorized all task commits as an exception and required commit-it staging. Execution resumed only after that direct approval; no rejection was bypassed. Exact paths and complete English messages were reviewed before staging/commit, and protected hashes were rechecked.

H01 (translation routing) and H06 (scrollbar UX) remain queued for their later implementation/investigation. H06 has not changed CSS or the frozen captures/images. H02–H04 are resolved; H05 did not recur on the final source.

## Historical QA checkpoints

Latest requirement: all 30 scenes must now be recaptured in **Light**, separately in English and
Korean (60 real captures). The 37-image/reuse set below is an earlier checkpoint, not final completion.
Theme controls, mode-aware Help, and the portfolio-style image viewer were added afterward.

Final application capture baseline: `3c83469`. Bilingual documentation functionality was checked
before capture. `TUTORIAL/captures.json` records 30 scenes: 37 actual captures (30 English and
7 Korean) and 23 explicitly identified English-image reuses in Korean documents. No placeholder
image or generated production outcome is used.

## Findings fixed before capture

| ID | Observed defect | Fix and evidence |
|---|---|---|
| I01 | A retained request inspector could remain visible and lock background interaction after its workspace hid. | Inherited activity gates the portal and handlers; failing regression now passes in be3d837. |
| I02 | A delayed interrupted-reset response could open a dialog over a different workspace. | Reset portal and keyboard/focus effects respect ancestor activity; regression passes in be3d837. |
| I03 | Pin guidance did not explicitly state that inclusion is not guaranteed citation. | Bilingual visible explanation and saved-result regression in be3d837. |

## Capture and polish record

| ID | Actual scene and defect | Fix | Retake |
|---|---|---|---|
| V01 |1440×1000 Korean connection diagnosis showed Passed and success used an error-details label. Before: `TUTORIAL/assets/qa/24-diagnostics-before.ko.png`.|a4d3d1b adds dynamic translation, neutral Diagnostic details, and a regression test.|`24-connection-diagnostics.ko.jpg` confirms 통과/진단 상세; heading and all three passed checks are visible.|
| V02 |Default setup link used browser blue against the restrained interface palette. Before: `TUTORIAL/assets/qa/13-default-before.ko.png`.|a4d3d1b keeps underlined links in the interface foreground color.|`13-local-model.ko.jpg` retaken.|
| V03 |Final contact-sheet review found clipped company/diagnostic headings and Add server form fields.|Adjusted only the real browser scroll/framing, without changing content.|Scenes 03 Korean, 24 Korean, and 25 English retaken and inspected.|
| V04 |Reset eligibility detail included machine-specific remediation paths.|Used a native screenshot crop of the blocked summary; no pixel editing or permission changes.|`17-reset-blocked.en.png` shows only the unavailable action and blocked state.|
| V05 |At390px the documentation monogram/name overlapped the language controls.|Narrow documentation headers retain the readable product name/version; larger widths retain the monogram.|DOM geometry confirmed the name ends before the language control. Final Light recapture pending.|
| V06 |A mixed Documents guide showed a DEV-only badge above its title, contradicting the unmarked navigation entry.|The page's registry classification now drives Shared guide versus DEV-only availability; section callouts retain specific restrictions.|Actual Documents shows Shared guide with all15links; Indexing shows DEV only with the same15links.|
| V07 |Manual Light selected under a dark OS setDOMtheme but compiledLight-dark colors remained dark.|LightningCSS had lowered colors to media-controlled fallback variables. Two explicit source color-scheme selectors let the compiler generate matching mode fallbacks.|Actual Light under a darkOS renders white; Dark under a lightOS renders dark; System follows lightOS.6focusedtheme/compiler tests andTypeScriptpassed; fullsuite/staticimagesafterthissmallfixnotrerun.|

Later user-requested hotfixes consolidated Help to two screens, removed persistent markers, unified settings, compacted request inspection, highlighted company/year, ordered EN first, and diversified documentation icons. These are bounded requested changes; no further aesthetic exploration follows the scope freeze.

## Matrix accounting

| Screen sample | Actual CSS widths | Result |
|---|---|---|
| English conversation, dark, sidebar closed |390, 768, 1280, 1440, 1920, 2560, 3440|No root horizontal overflow or visible control extending beyond the viewport.|
| English Ollama documentation, dark |390, 768, 1280, 1440, 1920, 2560, 3440|No root horizontal overflow. Wide tables retain their own scrolling.|
| Korean conversation, dark, reduced motion |390, 768, 1280, 1440, 1920, 2560, 3440|Confirmed Korean document language and reduced-motion media query; no root overflow.|
| English conversation, light, reduced motion |390×844|Visually checked composer, sidebar open/closed, and the single full-screen settings dialog (390×844). All settings tabs and close action remain available.|
| Document/detail and application capture set |1440×1000 and 1920×1080; English dark and Korean light samples|All 37 actual assets visually inspected; framing retakes listed above.|

Actual interaction evidence:

- Desktop Review settings: one 720px dialog at 1440px; composer remained 62px high. Escape
  closed the dialog, removed background inert state, and returned focus to its trigger.
- Document divider: Home selected 320px, End 600px, and double-click restored 360px.
- Help: home opens a topic directly; Back returns home. Persistent numbered markers are absent.
  The selected visible target receives one passive highlight, with an explicit Go to control action.
- Production UI preview: private question absent, Send disabled, read-only explanation present;
  observed requests were public GETs. Exit restored the original draft and scroll position.
- Documentation: exact command copy, locale switch retaining `ollama#connect`, mobile menu,
  contained table scrolling, original image in a separate tab, and automatic live editing all passed.

This is a measured sample, not every language/theme/sidebar/state combination. Loading, response races,
running, cancellation, and interrupted-state behavior also have component/contract test evidence;
they were not recreated with provider calls for photographs. Browser zoom, every drag/keyboard
combination, macOS execution, and an actual destructive reset were not run in this final visual pass.
Existing saved successful/failed runs and the actual empty evaluation comparison were captured as-is.
The 22,367 prepared embeddings are deterministic; screenshots do not establish OpenAI retrieval quality.

## Asset integrity

Actual screenshot bytes are preserved: 36 JPEG files use `.jpg`, and the native reset-summary PNG
uses `.png`. Captions distinguish unexecuted forms, existing historical results, empty comparisons,
and blocked reset eligibility. English reuse is declared in both Korean captions and the manifest.
Final static-image checks and image IDs are recorded in `2026-09-05-v2-verification.md`.
