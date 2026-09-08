# Evaluate retrieval against known evidence

> [!DEV]
> The live evaluation workspace, Golden source/draft tools, and evaluation jobs require DEV. Visitors can use the separately published snapshot comparison.

An evaluation asks whether the search system can find the evidence specified by a golden dataset. It records a dataset, retrieval configuration, progress, and results. It does not require a generated answer first, and its retrieval scores do not certify the factual accuracy of an answer model.

## 11. Run a retrieval evaluation {#step-11}

**Goal:** obtain one recorded retrieval result whose dataset and search conditions you understand.

**Prerequisites:** a local development environment with evaluation permission, a working index, and the source filings required by your chosen suite. A corpus containing only one tutorial filing is insufficient for a suite covering several companies. Reuse a matching existing result if the required evaluation was already completed.

**Screen path:** **Measure → 2. Golden dataset**, then **3. Run evaluation → New evaluation**.

| Input | What to verify |
|---|---|
| Golden suite | The company coverage and question language match what you intend to measure. |
| Golden revision | Choose Canonical JSON for the source dataset, or the intended saved revision. |
| Core search settings | Strategy, lexical ranker, and `k` identify the experiment. |
| Advanced evaluation options → Run mode | Start with **Quick · current index**. It measures the current prepared index. |

Select and read a question in Golden dataset, including its source spans. Open New evaluation and verify readiness and case count. **Primary action:** click **Queue evaluation** once. Query embedding and configured search components may incur provider costs.

**Visible result:** the setup closes and a queued job appears in Evaluation runs. Select its row to inspect request settings and actual progress. A successful run exposes Result details, recorded configuration, metrics, and case ranks. No result means no measured scores yet.

Selecting an evaluation opens its focused details. While the list is intentionally hidden, this is a detail view, not an empty-history state. Return to the runs list to inspect other jobs.

**Completion:** the selected run succeeded, the result ID and dataset are correct, and you inspected at least one hit/miss against its source evidence. Do not treat a successful job from another suite as the result of this setup.

**Common failure:** Sources unavailable or Corpus not ready. Read the named source error, then return to [Documents](documents.md) and [Indexing](indexing.md). For a failed or interrupted job, use [evaluation recovery](troubleshooting.md#evaluation) before retrying.

**Next:** [12. Compare results and save a snapshot](snapshots.md#step-12).

### SCREENSHOT NEEDED

<!-- SCREENSHOT NEEDED: feature=focused-evaluation-detail; locale=en; theme=light; capture=selected-evaluation-with-result-details-and-back-to-list-without-empty-history-message; issue=21; preserve-existing-assets=true -->

**Screenshot pending for the focused evaluation detail and return-to-list state. Existing screenshots remain unchanged.**

<!-- capture:11-evaluation-inputs -->

![New evaluation setup uses the real mixed-language canonical suite: 20 cases and a ready current index.](../assets/11-evaluation-inputs.en.jpg)

*New evaluation setup uses the real mixed-language canonical suite: 20 cases and a ready current index. Hybrid/BM25/k=5 is visible; Queue evaluation was not pressed.*

## Choose among seven suites {#suites}

Suite IDs are stable dataset identifiers. The `_v2_astra` suffix does not rename the product or imply that Astra is the model used to run an evaluation.

| Suite ID | Questions | Filing corpus |
|---|---|---|
| `sec-en` | English | English SEC filings |
| `sec-ko` | Korean | English SEC filings |
| `dart-en` | English | Korean DART filings |
| `dart-ko` | Korean | Korean DART filings |
| `sec-en_v2_astra` | English | English SEC filings |
| `sec-ko_v2_astra` | Korean | English SEC filings |
| `sec-mixed_v2_astra` | Mixed English/Korean | English SEC filings |

The three additional SEC suites each contain 20 curated questions. Check the displayed curation and approval status; an automatically curated dataset is not evidence of human approval. When comparing question languages, inspect company, fiscal-year, and scope clues as well as the source spans. Shared evidence alone does not make two questions equivalent.

The same suite catalog is used by Golden, new evaluation setup, and Evaluation settings. Saved defaults choose the starting suite for later work; they do not change existing results.

## Source JSON and editable drafts {#golden}

**Canonical JSON · read-only** selects the checked-in source dataset. **View source JSON** explicitly opens its payload and hash. Selecting a question shows its question, reference answer, classification, and source spans without making the source editable.

When an edit is actually needed, use **Create draft**, select a question, change its fields, and choose **Save case**. Validate the saved revision before **Publish JSON**. Published revisions are immutable; create another draft for further edits. Dataset publication is separate from making a search snapshot public.

Source spans identify a document, character start/end, and SHA-256. A plausible reference answer cannot replace a valid source identity. Fix validation errors in the named field and validate again. An intentionally absent-evidence case can have no source span.

Unsaved question edits block silent navigation: cancelling the discard prompt retains the question and the original Back destination. Save deliberately before changing suites, revisions, or workspaces. Validation confirms the dataset contract; it does not imply human review.

<!-- capture:10-golden-question -->

![The mixed-language SEC suite is selected with an actual canonical question open.](../assets/10-golden-question.en.jpg)

*The mixed-language SEC suite is selected with an actual canonical question open. Canonical JSON is read-only; viewing a source question is separate from creating or editing a draft.*

## Modes, results, and interpretation {#metrics}

Quick uses the current index. **Matrix · isolated corpus** tests configured chunk targets and retrieval combinations in an isolated corpus; it can involve substantially more preparation and work. Inspect its scope and provider costs before using it as a comparison experiment.

| Result | How to read it |
|---|---|
| Hit / miss | Whether the selected result found relevant evidence within its returned set. |
| First relevant rank | Where the first relevant hit appears; lower is better. |
| Reciprocal rank / MRR | Rank-sensitive retrieval quality, giving more credit to an early relevant result. |
| Recall@k / hit rate | Coverage within the stated cutoff and evaluated cases. Compare like-for-like conditions. |
| Latency | Recorded search time; judge it alongside quality and the effective configuration. |

Follow per-case changes rather than only the aggregate score. **Use selected set** applies a selected result's search settings to the conversation; it does not generate a new answer. [Snapshots](snapshots.md) explain how to preserve and compare the result with its search data.

## Workflow and management tabs

The four steps are **Search trial → Golden dataset → Run evaluation → Compare results**, each with a small numbered chip. The separate **Manage** group contains **Presets** and **Defaults DEV**. Defaults apply to future evaluations and do not start a run. Both groups stay visible; at 720 px and below they use separate rows. Existing links including `?view=measure&tab=presets`, `tab=defaults` and `tab=snapshots` preserve browser history. Each management tab has its own page help.

### SCREENSHOT NEEDED
<!-- Feature: Measure workflow and Manage groups, active presets/defaults and page help; locale=en; theme=light; widths=1440,720; show numbered chips, divider, caption and DEV badge. Preserve existing assets. -->
