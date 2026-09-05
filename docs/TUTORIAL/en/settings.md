# Settings for the next request

Conversation settings determine where to search, how to rank evidence, and how much work a review may do. They belong to the active conversation. Changing a control does not rewrite an existing answer or change the settings already submitted with a running request.

The composer follows **Corpus scope → answer engine/local model → retrieval preset → Filters / RAG settings**. Its secondary row opens corpus readiness and the request inspector. The corpus total describes the whole catalog, not the SEC or DART subset selected for your question; public mode describes published data.

## 10. Adjust filters, presets, and evidence choices {#step-10}

**Goal:** prepare one deliberate settings change and understand when it takes effect.

**Prerequisites:** an existing conversation and the documents needed for its question. A saved answer is useful for inspecting evidence choices; a new answer is not required merely to change settings.

**Screen path:** open the conversation → **Filters**, then the **Retrieval preset** control above the question.

| Input | Meaning for this exercise |
|---|---|
| Corpus scope | Choose SEC for an SEC question, DART for a DART question, or Auto for server routing. |
| Companies / Fiscal years | Select actual available entries, such as NVDA and 2024 when those filings exist. Empty selections leave that field unrestricted. |
| Retrieval preset | Select Accuracy to inspect a wider candidate pool and reranking. This is a setting to evaluate, not a promise of a better answer. |

**Primary action:** choose **Accuracy**. Open **Settings details / request preview** and check the effective retrieval settings and filters before another execution.

**Visible result:** the selected preset changes; its explanation includes `candidate_k: 50` and `reranker: cross_encoder`. The question and earlier answer stay unchanged. The inspector describes the next request; evidence remains unresolved until execution.

**Completion:** you can identify the intended corpus, selected filters, engine, and preset, with no invalid draft left in Filters. If an answer has selectable evidence, inspect the Pin/Exclude meanings below without rerunning unless you intend another model call.

**Common failure:** a typed company is not in the selected corpus, or an old selection becomes incompatible after changing scope. Keep the visible warning, correct the input or deliberately remove the selection, then check the inspector again. See [filter recovery](troubleshooting.md#retrieval).

**Next:** [11. Evaluate retrieval](evaluation.md#step-11). Evaluation can also be started directly after index preparation; it does not depend on generating an answer.

## Presets and effective values {#presets}

The following values come from the current preset definitions. All three built-in presets use hybrid retrieval and return `k=5` results.

| Preset | Candidates | Lexical ranking | Reranker | Language routing |
|---|---:|---|---|---|
| Balanced | 20 | `ts_rank_cd` | None | Off |
| Korean | 30 | BM25 | None | On |
| Accuracy | 50 | BM25 | Cross encoder | Off |
| Custom | Your saved values | Your saved values | Your saved values | Your saved values |

Balanced provides the default starting point. Korean changes the search configuration for language-aware retrieval; it does not translate stored filings or force the corpus scope to DART. Accuracy reranks a larger pool and can take more work. Custom opens the editor immediately when permitted, retaining existing custom values. Built-in preset selection clears the explicit custom profile, so inspect values before switching away from a configuration you want to keep.

`k` is the returned result count; `candidate_k` is the candidate count used before final selection. RRF combines component ranks. BM25 parameters affect lexical scoring. A reranker changes ordering, not the underlying filing text. Use [retrieval inspection](retrieval.md) to assess the change before attributing a quality improvement to it.

## Scoped filters and unfinished input {#filters}

Company, language, form, and fiscal-year choices come from the complete catalog available within the selected scope. The application does not construct these lists from the first page of documents. Public choices come from the public catalog.

Choose values as removable chips. Incompatible saved selections stay visible until you remove them. Invalid typed drafts block Send while the filter editor is open. Switching editor tabs or closing the editor discards unfinished text, as its notice explains; committed selections remain. Navigating to another workspace and using Back preserves the open editor and its local state.

The scope and preset **?** controls support hover, focus, touch, and Escape. **View corpus readiness** opens Build; use **Back to conversation** to return to your draft. The request inspector has its own scrolling, Escape/close controls, and focus return.

## Pin, Exclude, and reviewing again {#evidence}

- **Pin** includes the evidence first in the next evidence review. It does not guarantee that the answer will cite it.
- **Exclude** omits the evidence from that next review's evidence set.
- Selecting either action only updates the selection and its count. It does not change the displayed answer.
- **Review again with selected evidence** submits a new review and adds a new result. It may incur provider costs.

Click a selected Pin or Exclude again to deselect it. A chunk cannot be pinned and excluded at the same time. Retrieved candidate count and actual citation count describe different things. Older saved results without a usable selection token explain why their selection buttons are disabled; retrieve a fresh result if you need to change evidence.

## Evidence size and execution limits {#budgets}

Under **RAG settings → Evidence**, history turns and maximum evidence characters control prompt content; overfetch and the per-document hit cap control evidence selection. Under **Run limits**, iterations, input/output tokens, and wall-clock seconds limit the whole run. The default wall clock is 120 seconds, not a token budget. See [runtime limits](runtime.md#limits) before changing a value to address a failure.

## Defaults and permissions {#defaults}

**Measure → Evaluation settings** saves experiment defaults and the retrieval preset for new conversations. Existing conversations and recorded results keep their settings. Global **Settings → Prompt** applies to the current conversation's prompt policy; local-server connection settings are managed separately under **Local LLM**.

Public mode exposes permitted scope, preset, and filter choices but locks development-only editing and local-model configuration. A saved development profile that is incompatible with the current deployment is reported explicitly; it is not silently rewritten into a different experiment.

## Local server selection {#local-server}

In **Settings → Local LLM**, **Default** uses the address prepared for the current DocReview environment. Selecting a server alone does not change the active connection. **Run connection diagnostics** checks the selected candidate without saving settings, downloading/loading models, or generating answers. Inspect the named diagnostic result and checked time; active settings remain in **Connection status**.

Use **Connect** to apply an existing choice. **Add a server…** asks for a name, reachable URL, and protocol; **Add & connect** saves the new entry only after a successful check. Failed connection or save attempts preserve the previous working configuration. **Use Default** checks the default endpoint before switching and retains your added servers. **Disconnect** explicitly disables local answers.

The [Ollama setup guide](ollama.md) opens in a new tab from this screen. It covers macOS/Linux installation, Docker access, model preparation, and read-only `rag-ollama-check` diagnostics. Connecting a server does not change the conversation's engine or the corpus embedding provider.
