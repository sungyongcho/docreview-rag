# Read runtime state and measured execution

Three different views answer different questions: **System → System status** checks service prerequisites; **Build → Jobs** follows background work; a conversation's **Execution summary**, **Execution performance**, and **Run trace** explain an individual review. A healthy API does not establish ready vectors, a working answer model, or a successful evaluation.

## Status and job lifecycle {#states}

| State | Meaning and next action |
|---|---|
| `queued` | Accepted and waiting. Inspect queue position and request scope. |
| `running` | Actual work is executing. Read current progress; cancel only when supported. |
| `succeeded` | The operation finished successfully. Verify the resulting documents, index, or evaluation result. |
| `failed` | The operation failed. Inspect its error and completed work before retrying. |
| `cancelled` | Cancellation ended the job. It is distinct from a failure and has no automatic retry action. |
| `interrupted` | An application restart cut the job short. It does not resume automatically. |

Failed and interrupted jobs offer **Retry as new job** when the server supports it. Retry creates new work; it does not prove that earlier partial work will be skipped. Review the scope, especially before embedding costs. CLI work performed directly against the same database appears in corpus state but need not have a web job record.

Green completion marks require confirmed readiness or completion. A pulse/spinner indicates actual execution, red indicates failure, amber identifies a missing prerequisite, and neutral means unknown or uncollected. Reduced-motion preferences stop repetitive animation without removing the status text.

## Execution summary and real timing {#timings}

Open a completed or failed answer's **Execution summary** for the stages actually reached. Auto scope preserves the user's Auto choice while separately showing the registry, companies, years, and reason reported by the server. Before routing resolves, the interface waits; it does not infer a confirmed decision from the question in the browser.

**Execution performance** separates request time measured by the browser from server execution time. Its ASCII bars scale to the longest measured stage in that result. They are elapsed-duration comparisons, not progress percentages or estimated completion times. Stage and model-call rows remain in recorded order, including repeated stages and retries.

| Measurement | Interpretation |
|---|---|
| `Not collected` | No usable measurement was recorded. It is not zero and not one attempt. |
| `0ms` | A measured zero duration. |
| `<1ms` | A positive duration below one millisecond. |
| Calls / attempts | Calls and provider attempts when collected; retries may make them different. |
| Loading / input processing / generation | Separate local-provider timings when that provider returned them. |
| Tokens per second | Calculated only when generated-token count and generation duration exist. |

The accessible table supplies exact values beside the visual bars. Original node IDs, model names, and logs stay intact even when the surrounding labels are translated. CPU/GPU placement remains uncollected unless supported by actual evidence; a long duration alone does not establish a hardware bottleneck. Older saved runs can lack telemetry without being corrupt.

## Run limits versus provider limits {#limits}

The default conversation budget is 6 iterations, 60,000 input tokens, 4,000 output tokens, and **120 wall-clock seconds**. These are cumulative run limits across model calls and retries. Inspect the submitted profile because existing conversations can have different values.

The failure field tells you what to change:

- `budget_exceeded`: read `resource`, `limit`, `observed`, and `blocked_node`.
- `provider_failure`: read `status`, `attempts`, `details`, and `node`.
- `node_error`: read `error_type`, `message`, and `node`.

Adjust a run budget under **RAG settings → Run limits**. Prompt/evidence size is under **Evidence**; it is a separate control. A provider timeout or authentication error is not fixed by raising the run token limit. Public request-rate and monetary allowances are another boundary, shown under System's limits. See [execution troubleshooting](troubleshooting.md#execution).

**Run trace** exposes the recorded run ID and failure fields. For API inspection, the resources are `GET /runs/{run_id}` and `GET /runs/{run_id}/traces`; there is no run-list route. Opt-in stream stage telemetry uses `X-DocReview-Telemetry: stages`. Existing clients without that header retain the default event contract.

## Local-model facts {#local-models}

**System → System status** distinguishes role configuration from installed models. **Settings → Local LLM** offers **Default**, saved servers, and **Add a server…**. Use **Run connection diagnostics** to inspect a candidate before explicitly connecting, then choose the answer engine and discovered model in the conversation. Saving a connection does not switch the engine automatically.

If replacement discovery or saving fails, the working connection is preserved. Resolve the reported endpoint or model-capability error before trying again. A server responding to health checks can still fail an actual generation request. Changing the answer engine also does not replace the embedding identity already stored in the corpus.

Installed, loaded, and answer-capable are separate facts. An installed model can be unloaded during normal standby; an unavailable inventory is unconfirmed, not a count of zero. DocReview only displays metadata actually returned by the server. It does not collect maximum/loaded context values or infer execution hardware from a model name. The [Ollama guide](ollama.md#models) explains independent model inspection. `rag-ollama-check` provides read-only connection diagnostics; [CLI reference](cli.md#diagnose-local-model-connectivity) defines its options.

## Stop and continue later {#resume}

Normal shutdown preserves the database volume and files:

```bash
rag-dev down
```

In a later terminal, from the repository root:

```bash
source ./rag_alias.sh
rag-dev up -d
```

Reuse services that are already running. Refresh System, inspect Documents and Jobs, then return to the saved conversation. Do not repeat download, ingestion, embedding, or evaluation when the required result is already present. Inspect interrupted jobs explicitly before retrying; they are not resumed automatically.

Saved conversations and their profiles remain in that browser. In-page workspace navigation preserves open editors, selections, and scroll; an unfinished question draft is not a promise of persistence across a page reload or browser-data deletion. Ordinary shutdown does not require [runtime reset](troubleshooting.md#reset).
