# Settings for the next request

## Preset explanations and server limits

Preset parameters show their names, purpose, current values and differences from Balanced. The canonical preset files remain unchanged. A setting that is not used by the selected strategy is identified explicitly. Wider candidate pools and reranking may cost more time; Accuracy is a configuration name, not an accuracy guarantee.

Question execution limits are separate from search presets. PROD reads actual server-owned question budgets and per-model-call ceilings; browser defaults are not presented as applied policy when that read fails. DEV retains its local-model guidance.


Conversation settings determine where to search, how to rank evidence, and how much work a review may do. They belong to the active conversation. Changing a control does not rewrite an existing answer or change the settings already submitted with a running request.

The primary composer row follows **Corpus scope → answer engine/local model → retrieval preset → Settings and preview**. The last action opens one drawer with **Basic**, **Advanced** (DEV) and **Preview** views. Switching views preserves configured values. The secondary row shows corpus readiness for the whole catalog, not the selected SEC/DART subset.

<!-- capture:18-scope-presets -->

![Corpus-scope help explains Auto, SEC and DART beside the actual controls.](../assets/18-scope-presets.en.jpg)

*Corpus-scope help explains Auto, SEC and DART beside the actual controls. Scope selection and the server-confirmed routing result are distinct.*

## 10. Adjust filters, presets, and evidence choices {#step-10}

**Goal:** prepare one deliberate settings change and understand when it takes effect.

**Prerequisites:** an existing conversation and the documents needed for its question. A saved answer is useful for inspecting evidence choices; a new answer is not required merely to change settings.

**Screen path:** conversation → **Retrieval preset** above the question. Open **Settings and preview → Basic** for document filters and the current limits summary.

| Input | Meaning for this exercise |
|---|---|
| Corpus scope | Choose SEC for an SEC question, DART for a DART question, or Auto for server routing. |
| Companies / Fiscal years | Select actual available entries, such as NVDA and 2024 when those filings exist. Empty selections leave that field unrestricted. |
| Retrieval preset | Select Accuracy to inspect a wider candidate pool and reranking. This is a setting to evaluate, not a promise of a better answer. |

**Primary action:** choose **Accuracy**, then open **Settings and preview → Preview** to inspect the next question’s settings. Existing answers and in-flight requests retain their submitted values.

**Visible result:** the selected preset changes; its explanation includes `candidate_k: 50` and `reranker: cross_encoder`. The question and earlier answer stay unchanged. The inspector describes the next request; evidence remains unresolved until execution.

**Completion:** you can identify the intended corpus, selected filters, engine, and preset, with no invalid draft left in Filters. If an answer has selectable evidence, inspect the Pin/Exclude meanings below without rerunning unless you intend another model call.

**Common failure:** a typed company is not in the selected corpus, or an old selection becomes incompatible after changing scope. Keep the visible warning, correct the input or deliberately remove the selection, then check the inspector again. See [filter recovery](troubleshooting.md#retrieval).

**Next:** [11. Evaluate retrieval](evaluation.md#step-11). Evaluation can also be started directly after index preparation; it does not depend on generating an answer.

### SCREENSHOT NEEDED

<!-- Settings and preview: Basic, Advanced and Preview tabs; light mode; en; show preserved values and integrated navigation. Existing asset below is historical. -->

<!-- capture:19-request-inspector -->

![Inspect request opens an independent drawer for effective presets, retrieval, engine, filters, prompt composition and the outgoing payload.](../assets/19-request-inspector.en.jpg)

*Historical capture of the previous separate inspector/settings layout. Use the Basic / Advanced / Preview flow described above.*

## Presets and effective values {#presets}

> [!DEV]
> Saving presets as server files runs in DEV mode only. The public build keeps the Balanced, Korean, and Accuracy presets, allows custom retrieval values within the server's bounds (`k` ≤ 10, `candidate_k` ≤ 50, `max_context_chars` ≤ 12000), and saves custom presets in this browser.

The following values come from the current preset definitions. All three built-in presets use hybrid retrieval and return `k=5` results.

| Preset | Candidates | Lexical ranking | Reranker | Language routing |
|---|---:|---|---|---|
| Balanced | 20 | `ts_rank_cd` | None | Off |
| Korean | 30 | BM25 | None | On |
| Accuracy | 50 | BM25 | Cross encoder | Off |
| Custom | Your saved values | Your saved values | Your saved values | Your saved values |

Balanced provides the default starting point. Korean enables language-aware retrieval without forcing the corpus scope to DART. Accuracy reranks a larger pool. In DEV, **Manage presets…** opens **Measure → Retrieval presets**. Expand a built-in row and choose **Copy and edit**, or save the current search settings. In DEV, named presets are stored as JSON files in `data/presets/` and appear in the composer selector; PROD management stores them in the browser. Saving or editing a preset does not change existing conversations; selecting it copies only retrieval values. Custom remains the label for unsaved values. Advanced search settings remain editable in the conversation drawer.

<!-- capture:30-preset-help -->

![The preset explanation describes the selected Balanced definition beside the actual control.](../assets/30-preset-help.en.jpg)

*The preset explanation describes the selected Balanced definition beside the actual control. Effective preset differences can also be compared in Settings and preview → Preview; opening help does not run a review.*

`k` is the returned result count; `candidate_k` is the candidate count used before final selection. RRF combines component ranks. BM25 parameters affect lexical scoring. A reranker changes ordering, not the underlying filing text. Use [retrieval inspection](retrieval.md) to assess the change before attributing a quality improvement to it.

## Scoped filters and unfinished input {#filters}

**Settings and preview** opens a right-side drawer on desktop and a full-screen dialog on mobile. **Basic** shows preset selection, document filters, limits and the count of settings differing from defaults. **Advanced** exposes the existing search/evidence/run-limit sections and additional instructions, plus an explicit defaults reset. **Preview** shows the next question, readable policy values and expandable request JSON. The execution-details panel also has a **Preview** tab; its **Server settings** tab continues to describe the selected historical run. Public mode hides Advanced; **Measure → Retrieval presets** manages browser presets subject to server application permissions. Keyboard focus stays inside the settings dialog and Escape returns it to the opener.

### SCREENSHOT NEEDED

<!-- Settings and preview: Basic, Advanced and Preview tabs; light mode; en; show preserved values and integrated navigation. Existing asset below is historical. -->

<!-- capture:27-review-settings -->

![One Review settings entry opens a single drawer with Filters, Search, Evidence and Run limits.](../assets/27-review-settings.en.jpg)

*Historical capture of the previous separate inspector/settings layout. Use the Basic / Advanced / Preview flow described above.*

Company, language, form, and fiscal-year choices come from the complete catalog available within the selected scope. The application does not construct these lists from the first page of documents. Public choices come from the public catalog.

Choose values as removable chips. Incompatible saved selections stay visible until you remove them. Invalid typed drafts block Send while the filter editor is open. Switching editor tabs or closing the editor discards unfinished text, as its notice explains; committed selections remain. Workspace navigation and Back preserve committed settings and the question; close the editor before using background controls.

The scope and preset **?** controls support hover, focus, touch and Escape. The corpus status line above the input opens Build; use **Back** to return to the draft. Preview uses the settings drawer’s scrolling and focus behavior. Invalid committed advanced values remain visible as an error and block sending even after closing the drawer.

## Pin, Exclude, and reviewing again {#evidence}

- **Pin** includes the evidence first in the next evidence review. It does not guarantee that the answer will cite it.
- **Exclude** omits the evidence from that next review's evidence set.
- Selecting either action only updates the selection and its count. It does not change the displayed answer.
- **Review again with selected evidence** submits a new review and adds a new result. It may incur provider costs.

Click a selected Pin or Exclude again to deselect it. Both buttons sit in each card header, so they work while a card is collapsed and the selection survives paging; pinned cards open by default when the list renders. A chunk cannot be pinned and excluded at the same time. Retrieved candidate count and actual citation count describe different things. Older saved results without a usable selection token explain why their selection buttons are disabled; retrieve a fresh result if you need to change evidence.

## Evidence size and execution limits {#budgets}

> [!DEV]
> Editing Search, Evidence, and Run limits in the conversation drawer runs in DEV mode only. Public users can still use permitted scope, preset, and filter choices, plus custom presets within the server's public bounds.

Under **Settings and preview → Advanced → Evidence**, history turns and maximum evidence characters control prompt content; overfetch and the per-document hit cap control evidence selection. Under **Run limits**, iterations, input/output tokens, and wall-clock seconds limit the whole run of one question, whichever answer engine (OpenAI or local) is selected. The default wall clock is 120 seconds, not a token budget. See [runtime limits](runtime.md#limits) before changing a value to address a failure.

For CPU-only local models, use the optional [CPU starting preset and hardware guidance](ollama.md#cpu-starting-preset). Existing defaults remain unchanged; apply a preset explicitly and inspect the next run’s timings.

### OpenAI per-call caps {#openai-call-caps}

Each OpenAI call is also capped by the server: `DOCREVIEW_OPENAI_MAX_INPUT_TOKENS` (default 12,000), `DOCREVIEW_OPENAI_MAX_OUTPUT_TOKENS` (default 600) and `DOCREVIEW_OPENAI_MAX_COST_USD` (default 0.04) in `.env` form the **ceiling**. A run limit above the ceiling does not raise it; the smaller value applies to every call. **System → System status** shows the caps in force under **OpenAI model policy**, and **Settings → Run limits** repeats them under **OpenAI per-call caps**.

In DEV the editor saves lower working values on the server in `data/local-settings/openai-limits.json`; **Restore ceiling** deletes that file. The web cannot raise a cap above the ceiling: change the `.env` keys and restart with `rag-dev down` / `rag-dev up`. Public PROD always uses the ceiling and never reads the file.

### SCREENSHOT NEEDED
<!-- Feature: OpenAI per-call caps block under Settings → Run limits; locale=en; theme=light; state=DEV with ceiling facts, three editable inputs bounded by the ceiling and the .env guidance; preserve existing assets. -->

## Defaults and permissions {#defaults}

> [!DEV]
> Saving experiment defaults and editing the prompt policy run in DEV mode only. **Settings → Prompt** and **Settings → Run limits** stay listed on the public build as read-only pages: the guard text and final prompt preview are visible, while **Additional operator instructions** and the save buttons are locked with a bubble that says the control runs in DEV mode only and links to the source repository. Browser language and permitted conversation choices remain separate.

**Measure → Evaluation settings** saves experiment defaults and the retrieval preset for new conversations. Existing conversations and recorded results keep their settings. Global **Settings → Prompt** applies to the current conversation's prompt policy; local-server connection settings are managed separately under **Local LLM**.

Public mode exposes permitted scope, preset, and filter choices and the read-only Prompt and Run limits pages, but locks DEV-only editing and local-model configuration. A saved development profile that is incompatible with the current deployment is reported explicitly; it is not silently rewritten into a different experiment.

## Local server selection {#local-server}

> [!DEV]
> Adding, connecting, disconnecting, or diagnosing a local model server runs in DEV mode only. This guide stays readable in the public manual.

In **Settings → Local LLM**, **Default** uses the address prepared for the current DocReview environment. Selecting a server alone does not change the active connection. **Run connection diagnostics** checks the selected candidate without saving settings, downloading/loading models, or generating answers. Inspect the named diagnostic result and checked time; active settings remain in **Connection status**.

Use **Connect** to apply an existing choice. **Add a server…** asks for a name, reachable URL, and protocol; **Add & connect** saves the new entry only after a successful check. Failed connection or save attempts preserve the previous working configuration. **Use Default** checks the default endpoint before switching and retains your added servers. **Disconnect** explicitly disables local answers.

The [Ollama setup guide](ollama.md) opens in a new tab from this screen. It covers macOS/Linux installation, Docker access, model preparation, and read-only `rag-ollama-check` diagnostics. Connecting a server does not change the conversation's engine or the corpus embedding provider.

## Inspect usage after changing providers

**System → Usage** groups recorded model/role rows by provider, local/external execution and credential slot name. A key value is never shown. Historical slots stay unknown; provider identity follows the recorded call, not today's settings. Reported tokens, tokenizer estimates and missing usage are distinguished, with matching subtotals. Local API cost is zero. See [recorded provider usage](runtime.md#recorded-provider-usage) for backfill coverage, failure accounting and the limits of these local estimates. Opening Usage does not call a model or reset data.

### SCREENSHOT NEEDED
<!-- Feature: provider and credential usage groups after a settings change; locale=en; theme=light; show role and reported/estimated usage distinction; preserve existing assets. -->

### Saved execution defaults

Open **Settings → Run limits** to edit and explicitly save the default budget and evidence size. System status shows a summary and a link to this editor. Existing conversations keep their own values and Basic shows their differences from saved defaults. **Restore setting defaults** in the conversation copies the saved search/prompt/evidence/limits while preserving document filters. The defaults editor’s **Restore limit defaults** prepares the original application values; save them explicitly to use them for future conversations.

### SCREENSHOT NEEDED
<!-- Default limits editor and System status summary; en; light mode; show saved values and a conversation override. Preserve existing assets. -->

Company, language, fiscal-year, form and section fields support both typed search and a visible dropdown button. Section suggestions come from the actual scoped corpus; manual section identifiers remain supported. Preset previews use full-width expandable rows, and JSON retains its code-block background and monospace formatting.

## Browser storage {#browser-storage}

On the real deployed **PROD** screen, conversations and user preferences are saved in this browser's `localStorage`, per origin (scheme, host and port). They are not synchronized to another browser or device. Clearing browser/site data removes them. Review requests still send the question and applicable settings to the API for processing; there is no server-side user-settings store.

The inventory includes conversations and their filters, evidence/run-limit overrides and prompt text; the active conversation; new-conversation profile/prompt/run-limit defaults; named retrieval presets when available; experiment defaults; language and theme; onboarding, help and storage-notice dismissal; desktop job notifications; Operations filters; and document/job pane widths. A saved value does not unlock a control that the current server permissions prohibit. Conversation retention remains 30 conversations with 100 messages each.

Open **Settings → Data & help → Browser storage** to see the estimated total and **Storage by key**. The warning begins at a conservative 4 MiB estimate; the actual shared origin quota depends on the browser and other site data. **Export browser settings** downloads one versioned JSON file, including conversations and prompt text: keep it private. **Import browser settings** validates the whole file first, then asks before replacing this browser's DocReview data. Finish any running request first. Unrelated website keys are preserved.

Use **Clear conversations** to clear only conversations, **Reset saved defaults** for defaults, or the browser's site-data controls to remove all local data. These actions do not delete the server's filing corpus or PostgreSQL records. Before clearing or switching browsers, export and verify a backup.

Valid old records migrate once in PROD. Unreadable or future records are retained in a recovery entry in the export, with a notice and safe defaults. Quota or private-mode failures keep changes usable in the current tab and report that they are not durably saved: export before closing. Private browsing may discard its data when the session ends.

The first PROD visit displays **⚠️ Settings and conversations are saved only in this browser**. **Got it** remembers dismissal. The ⚠️ button in **Data & help → Browser storage** reopens it; **Learn more** opens this section. DEV keeps its existing storage behavior.

### SCREENSHOT NEEDED
<!-- Feature: PROD browser-storage notice, Data & help per-key usage, export/import confirmation and reminder; locale=en; light mode; show real deployed state. Preserve existing assets. -->

The defaults editor and **Conversation settings → Advanced → Run limits** share the preset row, aligned budget/evidence fields and guidance. The editor uses two columns on desktop and one at 720 px or below. Save feedback stays beside the save/restore actions. Composer default-limit links and the System status summary open **Settings → Run limits**; CPU recommendations still open the current conversation override.

### SCREENSHOT NEEDED
<!-- Feature: Run limits category, shared conversation limits and System summary; locale=en; theme=light; widths=1440,720; show aligned units, hints, save feedback and keyboard focus. -->

### Retrieval preset files and JSON editing

Open **Measure → Retrieval presets**. DEV uses `data/presets/<id>.json`, next to other runtime data and included in the existing Compose data mount. The three shipped files (`balanced`, `korean`, `accuracy`) are the canonical source for both server and web; copy them to edit. Custom preset files are ignored by Git. A visible selector shares a lightweight version refresh every three seconds; the server scans metadata, debounces changes and rereads only changed files. A corrupt file appears with its filename and error while valid presets remain usable. Fix the file to restore it without restarting.

Use **Save current search as a preset** or **Register new preset** (Balanced defaults). The same editor supports a name, description, search fields, and a **JSON** view with inline validation and **Copy JSON**. Import one JSON file to edit a new copy; export a saved row with **Export preset JSON**. Each saved row offers explicit selection, copy, edit and confirmed deletion. Saving or deleting does not change existing conversations. Selection remains subject to the current server's custom-retrieval permission.

PROD stores presets through the versioned browser settings module; it exposes no file API. Browser settings export/import includes these presets.

### SCREENSHOT NEEDED
<!-- Retrieval presets: actual light-mode DEV file rows, JSON editor with validation error, and PROD browser-storage notice; locale en. Capture after implementation. -->

### Default search settings for new chats

In Conversation settings, the Basic preset section and Advanced Search provide **Save as new-chat search defaults** and **Reset new-chat search defaults**. These affect only the search preset of subsequently created conversations. Existing conversations, prompts, filters, and run-limit defaults are preserved. Evaluation defaults live in New evaluation; snapshot comparison selections are not global defaults.

Confirmations for draft changes, settings resets, backup imports, and operator commands appear inside the app. Cancel or Escape preserves the current state; Continue performs the requested action. Browser-controlled tab-close warnings and notification permission requests remain native.
