# Read runtime state and measured execution

Three different views answer different questions: **System → System status** checks service prerequisites; **Build → Jobs** follows background work; a conversation's **Execution summary**, **Execution performance**, and **Run trace** explain an individual review. A healthy API does not establish ready vectors, a working answer model, or a successful evaluation.

## Status and job lifecycle {#states}

> [!DEV]
> Starting, cancelling, and retrying corpus or evaluation jobs requires DEV. Reading a public review result is not an administrator job action.

| State | Meaning and next action |
|---|---|
| `queued` | Accepted and waiting. Inspect queue position and request scope. |
| `running` | Actual work is executing. Read current progress; cancel only when supported. |
| `succeeded` | The operation finished successfully. Verify the resulting documents, index, or evaluation result. |
| `failed` | The operation failed. Inspect its error and completed work before retrying. |
| `cancelled` | Cancellation ended the job. It is distinct from a failure and has no automatic retry action. |
| `interrupted` | An application restart cut the job short. It does not resume automatically. |

Failed and interrupted jobs offer **Retry as new job** when the server supports it. Retry creates new work; it does not prove that earlier partial work will be skipped. Review the scope, especially before embedding costs. CLI work performed directly against the same database appears in corpus state but need not have a web job record.

Selecting a historical job shows its actual target, progress and result; it is not work started for the guide.

<!-- details: status-visuals | Reading status colors and motion -->
Green completion marks require confirmed readiness or completion. A pulse/spinner indicates actual execution, red indicates failure, amber identifies a missing prerequisite, and neutral means unknown or uncollected. Reduced-motion preferences stop repetitive animation without removing the status text.
<!-- /details -->

<!-- screenshot: jobs-status-and-retry -->

![The Job Center listing a completed BM25 rebuild with its request options, progress and timings.](../assets/jobs-status-and-retry.en.png)

## Execution summary and real timing {#timings}

Open a completed or failed answer's **Execution summary** for the stages actually reached. Auto scope preserves the user's Auto choice while separately showing the registry, companies, years, and reason reported by the server. Before routing resolves, the interface waits; it does not infer a confirmed decision from the question in the browser.

Open **Run details → Performance** beside the answer. **Execution performance** separates request time measured by the browser from server execution time. Its ASCII bars scale to the longest measured stage in that result. They are elapsed-duration comparisons, not progress percentages or estimated completion times. Stage and model-call rows remain in recorded order, including repeated stages and retries.

| Measurement | Interpretation |
|---|---|
| Not collected | No usable measurement was recorded. It is not zero and not one attempt. |
| `0ms` | A measured zero duration. |
| `<1ms` | A positive duration below one millisecond. |
| Calls / attempts | Calls and provider attempts when collected; retries may make them different, and a call refused before it started counts zero attempts. |
| Loading / input processing / generation | Separate local-provider timings when that provider returned them. |
| Tokens per second | Calculated only when generated-token count and generation duration exist. |

The accessible table supplies exact values beside the visual bars. Original node IDs, model names, and logs stay intact even when the surrounding labels are translated. A saved run records its original ID, iteration and provider-request counts, token counts and elapsed time.

<!-- details: missing-telemetry | Uncollected and missing measurements -->
CPU/GPU placement remains uncollected unless supported by actual evidence; a long duration alone does not establish a hardware bottleneck. A failed request can collect only browser request time, with routing, stage timings and model calls left explicitly uncollected. Older saved runs can lack telemetry without being corrupt.
<!-- /details -->

<!-- screenshot: execution-performance-and-run-trace -->

![The run trace of an evaluation with measured stage durations and request totals.](../assets/execution-performance-and-run-trace.en.png)

## Run limits versus provider limits {#limits}

> [!DEV]
> Changing run budgets requires DEV. Recorded failure fields and collected timings can still be read wherever the result is available.

The default conversation budget is 6 iterations, 60,000 input tokens, 4,000 output tokens, and **120 wall-clock seconds**. These are cumulative run limits across model calls and retries. Inspect the submitted profile because existing conversations can have different values.

The failure field tells you what to change:

- `budget_exceeded`: read `resource`, `limit`, `observed`, and `blocked_node`.
- `provider_failure`: read `status`, `attempts`, `details`, and `node`. When its `budget` carries `projected_input_tokens`, the call was refused before it started because the estimated prompt did not fit the remaining input allowance; nothing was sent, so the record keeps the projection with zero requests and no usage; when the refused prompt was the repair after a first response, exactly that one request stays counted. Lower **Review settings → Evidence** max context or raise the input limit named by `budget_source`.
- `node_error`: read `error_type`, `message`, and `node`.

Adjust a run budget under **Review settings → Run limits**. Prompt/evidence size is under **Review settings → Evidence**; it is a separate control. A provider timeout or authentication error is not fixed by raising the run token limit. Each OpenAI call is separately capped by the server ceiling described in [OpenAI per-call caps](settings.md#openai-call-caps); the smaller of the run limit and that cap applies. Public request-rate and monetary allowances are another boundary, shown under System's limits. See [execution troubleshooting](troubleshooting.md#execution).

<!-- details: trace-api | Trace and API inspection -->
**Run details → Trace** exposes the recorded run ID and failure fields. For API inspection, the resources are `GET /runs/{run_id}` and `GET /runs/{run_id}/traces`; there is no run-list route. Opt-in stream stage telemetry uses `X-DocReview-Telemetry: stages`. Existing clients without that header retain the default event contract.
<!-- /details -->

## Local-model facts {#local-models}

> [!DEV]
> Local-server configuration and model selection controls require DEV. Public requests use the release configuration; they do not expose local-server controls.

**System → System status** distinguishes role configuration from installed models. The **Local model policy** and **Local runtime** panels carry a **DEV** badge because they exist only in a development runtime. **Settings → Local LLM** offers **Default**, saved servers, and **Add a server…**. Use **Run connection diagnostics** to inspect a candidate before explicitly connecting, then choose the answer engine and discovered model in the conversation. Saving a connection does not switch the engine automatically.

If replacement discovery or saving fails, the working connection is preserved. Resolve the reported endpoint or model-capability error before trying again. A server responding to health checks can still fail an actual generation request. Changing the answer engine also does not replace the embedding identity already stored in the corpus.

Installed, loaded, and answer-capable are separate facts. An installed model can be unloaded during normal standby; an unavailable inventory is unconfirmed, not a count of zero. DocReview only displays metadata actually returned by the server. It does not collect maximum/loaded context values or infer execution hardware from a model name. The [Ollama guide](ollama.md#models) explains independent model inspection. `rag-dev doctor` provides read-only connection diagnostics; [CLI reference](cli.md#diagnose-local-model-connectivity) defines its options.

## Local operations {#operations}

> [!DEV]
> The Operations tab appears only when the local operator started by `rag-dev` is configured for this build. Visitors never see it.

**System → Operations** lists the registered local commands as cards grouped by category. **Inspect** reads state (Git status), **Verify** runs lint, tests, typecheck and the production build without changing files, and **Service** starts or stops PostgreSQL and the app or prepares an empty schema. Inside a group read-only commands come first and commands that ask for confirmation come last, each marked with a **Confirmation required** badge in its header. The **All · Inspect · Verify · Service** filter above the cards narrows the view and is remembered per browser. **Run** starts one command at a time; **Latest run** streams its output and offers **Cancel** while it is running.

The **Command target** filter narrows each category to **Python**, **Web**, **Database** or **App**; **All targets** restores every target. It combines with the category filter and is remembered independently in this browser. App includes checkout and app-service operations; PostgreSQL checks and schema operations target Database. Target badges come from the operator registry, not from command-name guesses. An older running operator without this field is marked **Target not reported**. Selecting filters does not execute commands.

## Stop and continue later {#resume}

> [!DEV]
> The commands below stop and start the operator's local stack. Visitors should simply use the deployed application rather than manage its services.

Normal shutdown preserves the database volume and files:

```bash
rag-dev compose down
```

In a later terminal, from the repository root:

```bash
source ./rag-alias.sh
rag-dev start
```

Reuse services that are already running. Refresh System, inspect Documents and Jobs, then return to the saved conversation. Do not repeat download, ingestion, embedding, or evaluation when the required result is already present. Inspect interrupted jobs explicitly before retrying; they are not resumed automatically.

Saved conversations and their profiles remain in that browser. In-page workspace navigation preserves open editors, selections, and scroll; an unfinished question draft is not a promise of persistence across a page reload or browser-data deletion. Ordinary shutdown does not require [runtime reset](troubleshooting.md#reset). **Data & help** separates browser conversations and preference resets from server documents and job history; no cleanup or reset action is required for an ordinary shutdown.

The embedded **Production preview** inside DEV is deferred to [issue #211](https://github.com/sungyongcho/docreview-rag/issues/211) and is not available in this release. See [environment boundaries](environment.md#environment-boundaries).

<!-- heading-alias: recorded-provider-usage -->
## Recorded provider usage {#provider-usage}

Open **System → Usage** in DEV to inspect recorded review calls and embedding backfills. Groups identify the provider, local/external execution and the credential slot name; no credential value is exposed. Each group contains model/role rows and request, token and cost subtotals. Header totals sum the same rows. The latest review-run footer stays available. Historical traces are classified from their recorded API URL; their credential slot remains **unknown** instead of being guessed from the current configuration.

New review records include gate and routing calls as well as answer, grading and checking. The recorder uses complete per-call evidence when available and falls back to older trace records without counting the same call twice. OpenAI embedding backfills record the actual response token count and the pinned estimated price for every API batch before vector validation/storage. A later failed or cancelled job retains earlier usage. The direct CLI backfill path also records terminal, archived `embedding_usage` ledger entries; these entries are accounting evidence and cannot be executed or retried. Archiving history preserves usage, while explicitly deleting its ledger removes that accounting evidence.

Local embedding token counts are tokenizer estimates, shown separately from provider-reported input; local API cost is zero. A response without token or cost evidence is explicitly marked **Not reported** or **Incomplete estimate**, never presented as free external usage. Numeric totals exclude unavailable amounts. Counts represent observed SDK requests; hidden SDK/network retries and query-only embeddings outside a backfill are not reconstructed. This is local accounting, not a provider billing statement. No model call is started by opening the page.

After an explicitly requested backfill, revisit Usage and find its embedding model, provider/slot and role. If persistence fails after a provider response, the job fails instead of silently claiming complete accounting; inspect that error before retrying because a repeated call may cost money. Usage metadata lives in the existing Run request-context and OperatorJob result JSONB fields, so this feature requires no schema reset or new ORM columns.

## Notification center {#notification-center}

Open the bell in the top bar, next to the language and theme controls. Its badge counts unread entries. The panel groups entries into **In progress** (live corpus jobs), **New notifications** (unread) and a collapsed **Past notifications · N** section; marking an entry read moves it into the past section instead of dimming it in place. The newest 100 entries remain in this browser: closing the panel or letting a toast expire does not delete them. Dismissing a toast marks that entry read. **Mark all read** keeps the history; **Delete** and **Clear all notifications** remove notification records only, not conversations, source files or job results.

Select an entry to mark it read and open its related job, evaluation result, conversation, settings category or System status. An entry without a destination only changes its read state. Escape closes the panel and returns focus to the bell; arrow keys move between entries. Long messages expand without discarding text. Error pictograms and accents identify failures; when the API supplies a cause, file and fix action, expand **Technical details** to inspect them. Server-originated messages remain exactly as received.

<!-- details: notification-behavior | Toast and alert details -->
Transient toasts float at the top right under the top bar, fade in and out, and never push the page down; at most three show at once and a hovered or focused toast pauses its timer. A queued or running job updates its entry silently, so the top-bar status pill and the Job Center carry live progress and only a finished, failed or cancelled job raises a toast. A job's progress updates one entry, while distinct successful actions keep their own records. Identical repeated errors share a count. Existing decision dialogs and visible result cards remain authoritative; their matching banner is suppressed, and the center closes when a modal opens. Desktop job notifications remain optional under **System → Operations**, mirroring the same job entry. Clicking an alert navigates only: it does not retry, reset or start another model request.

The center also records actual connection transitions, local-model changes and slow-CPU measurements, preset content changes, comparison outcomes and available reset/fresh-start receipts. A preset poll with unchanged contents or an intermediate adapter-loading state does not create an alert. A fresh-start receipt describes recorded cleanup, not proof that every restarted service is ready; inspect System status before continuing.
<!-- /details -->

<!-- screenshot: notification-center -->

![The notification center open with unread counts and the All/Jobs/Errors tabs.](../assets/captures/notification-center.en.png)

*1. Notification list · 2. detail*
