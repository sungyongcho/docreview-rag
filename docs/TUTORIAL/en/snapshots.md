# Compare results and preserve search data

An evaluation result records measured outcomes and settings. A snapshot preserves search data together with a selected evaluation result so that a known setup can be reused. Comparing stored snapshots reads existing artifacts; it does not run another evaluation or call a model provider.

## 12. Compare results and save a suitable snapshot {#step-12}

> [!DEV]
> Comparing private evaluation results and saving new snapshots runs in DEV mode only. Comparing snapshots already published for visitors remains a separate public feature.

**Goal:** choose a result using its evidence and experiment conditions, then preserve it for later use.

**Prerequisites:** at least one successful **Quick · current index** result whose source corpus still matches the current index. Comparison requires two different results; if only one exists, inspect it and keep the comparison honestly unavailable. Do not queue another paid evaluation merely to fill the screen.

**Screen path:** **Measure → 4. Compare & snapshots → Compare results**. After comparing, return to **3. Run evaluation**, select the suitable result, and open **Result details**.

| Input | Meaning |
|---|---|
| Baseline | The result you want to improve on. |
| Candidate | A different result to assess against the baseline. |
| Dataset and revision | Identify the questions and ground truth behind the scores. |
| Snapshot label | A recognizable name, such as `SEC hybrid k5 baseline`. The label does not establish compatibility. |

Read the metadata before **Compare selected results**. Inspect changed cases and latency alongside metrics. **Primary action:** in the chosen Result details, enter the snapshot label and click **Save result as snapshot**.

**Visible result:** a creation notice confirms the saved snapshot. Open **4. Compare & snapshots → Snapshot management** to find its label, document count, suite, and result ID. It starts private; saving does not publish it.

**Completion:** the saved identity matches the intended result, you understand its comparison limits, and it appears in Saved snapshots. **Use for review** can apply the snapshot to a conversation when permitted. This does not send a question.

**Common failure:** the source corpus changed after evaluation, or a matrix result cannot become a queryable current-index snapshot. Read the error; select a matching quick result or deliberately evaluate the desired current corpus. See [evaluation and snapshot recovery](troubleshooting.md#evaluation).

**Next:** [stop and continue later](runtime.md#resume), or return to [Answers](answers.md) and inspect the applied snapshot before another request.

<!-- capture:12-compare -->

![The actual comparison workspace has no selectable results yet, so comparison stays unavailable and no metrics are fabricated.](../assets/12-compare.en.jpg)

*The actual comparison workspace has no selectable results yet, so comparison stays unavailable and no metrics are fabricated. Saving a snapshot requires a suitable recorded result.*

## Read conditions before metric differences {#comparison}

Result comparison requires different results from the same dataset. Snapshot comparison can also explain limited comparisons across different datasets or golden identities. Its **Directly comparable / Limited comparison** status and warning appear before the metric table.

The snapshot comparison's direct-comparability flag checks the suite and golden identity. You must still inspect corpus, embedding identity, retrieval settings, and `k` before attributing a difference to one setting. Matching dataset labels alone do not establish a controlled experiment.

| Inspect | Why it matters |
|---|---|
| Suite and golden revision/hash | Different questions or source spans change what the scores measure. |
| Corpus identity and document count | A larger or changed evidence collection may explain better coverage. |
| Embedding provider/model/dimensions | Vector identities determine which search configuration the data supports. |
| Strategy, `k`, candidates, reranker | More returned evidence or work can change both quality and latency. |
| Case-level changes | An aggregate gain can conceal important regressions. |

In a limited comparison, unavailable metric deltas appear as `n/a`. Read the number of common cases and each side's question. No common cases means there is no shared case-level basis to inspect. The expandable example is explicitly illustrative, not a recorded result.

## What saving and applying do {#save}

Saving binds an existing result to current document, chunk, vector, and lexical-index data. The server checks that the evaluation's recorded source fingerprint matches the current index. Only live-index quick evaluations provide the required identity. Where a golden revision is linked, it must be published and match the evaluation's golden hash.

**Use selected set** in Result details applies search settings. **Use for review** on a saved snapshot applies the stored search configuration and snapshot selection. Both prepare a conversation; neither executes a review. Use the request inspector to see the next request, and deliberately clear a snapshot chip when returning to the live corpus.

A snapshot is not a full backup of the application, browser conversations, or credentials. Keep the original sources and normal backups according to your own retention needs.

## Private storage and public visibility {#visibility}

> [!DEV]
> Publish and Hide change snapshot visibility and run in DEV mode only. Reading an already published snapshot or its eligible documents does not change visibility.

The Save result as snapshot action creates a private snapshot. **Publish** and **Hide** are separate operator actions. Publishing allows the ready snapshot and its eligible document catalog to be read by visitors; hiding removes that snapshot from the public list.

Public document lists, facets, counts, and details follow ready, published membership and matching source identity. A document may remain public through another published snapshot even after one snapshot is hidden. Company metadata must follow the same visibility boundary. A populated development corpus with no published snapshots can correctly show an empty public catalog.

Inspect the scope before changing visibility. You do not need to publish a snapshot to complete local evaluation, save an experiment, or read its results.


## Snapshot management

**Compare & snapshots** separates **Compare results** from **Snapshot management**.
Result comparison does not require a snapshot. Management lists each saved name,
dataset file, recorded search settings, source evaluation, document count, and
creation time. Select two snapshots above the list to compare their stored results;
expand a row to inspect its recorded configuration. **Use for review** applies the
saved search state without sending a question.

A result has at most one snapshot. Its result page shows **View saved snapshot** once
saved, and repeat API requests return the existing snapshot without changing its
name or visibility. Snapshots are stored in this database and are deleted by an
execution data reset; they are not standalone backup files. Golden dataset files
have a separate preservation policy. This screen does not add deletion or renaming.

Snapshot management uses the same dataset filenames as evaluation history. Filter by file,
search snapshot names or filenames, and sort by creation time, filename, or snapshot name.
The source-evaluation link opens the exact recorded result without exposing its numeric ID
as the link label. Internal identifiers remain available in the expanded snapshot details.
