# Acquire SEC and DART filings

## Reference acquisition scope

The default draft contains **NVDA and AMD FY2019–2024**, plus **005930 and 000660
FY2022–2024**: exactly eighteen company/year pairs. It does not depend on existing files.
`rag-schema recreate --sample` selects NVDA and AMD FY2023–2024; neither preset downloads automatically.
Choose supported companies from the picker and add fiscal years. Edited selections, including
an empty selection, persist until the reset revision changes.

The company/year matrix shows downloaded, missing and invalid originals separately. Selection
changes describe what to prepare; they do not delete files. **Sync selection** downloads missing
or invalid originals for the selected pairs. Valid originals are reused. Multiple filings in one
year retain their distinct official receipt/accession IDs.

Step 1 manages downloads and current originals. Step 2 starts from the fully downloaded, valid
originals in that selection. Missing, changed or deleted intended sources remain explicit blockers;
parsing never silently drops them. Use **Change selection in Filings** to revise the scope.

### SCREENSHOT NEEDED

<!-- SCREENSHOT NEEDED: feature=company-year-inventory-selector; locale=en; theme=light; capture=32-document-compact-grid-search-year-checkboxes-staged-pairs-and-sync; issue=131; preserve-existing-assets=true -->

**Screenshot pending for the updated controls and resulting state. Existing screenshots are unchanged.**


> [!DEV]
> Editing acquisition inputs and downloading filings require DEV. The public pipeline can be inspected, but its acquisition controls cannot start work.

Acquisition downloads original reports and records their identities in the common `manifest.json`. Parsing and database
storage happen later. Check [Documents](documents.md#step-2) first: a report already prepared in this
environment does not need another download.

## 3. Choose companies and years {#step-3}

- **Goal:** define the source reports you intend to prepare.
- **Prerequisites:** [environment checks](environment.md#step-1) complete; know which reports are missing.
- **Screen:** Build → Pipeline → Filings → company/year matrix.
- **Inputs:** choose `NVDA` and `2024`, or `005930` and `2024` for a Korean report. Both sources can be selected together.
  The year is the report's fiscal year, not necessarily its publication year.
- **Primary action:** toggle year chips or company checkboxes; search a company and check years for absent pairs.
- **Visible result:** selected chips are highlighted, and **To be added** lists selected missing years and staged pairs.
- **Completion:** companies and years describe the intended source, with no invalid draft left.
- **Recovery:** correct invalid search text, press Enter, then **Sync selection**. For source
  credentials or unavailable reports, see [acquisition failures](troubleshooting.md).
- **Next:** [download missing sources](#step-4), or [parse existing sources](indexing.md#step-5).

The stable company code and filing identity remain visible. Parsing receives exact selected
document IDs, grouped by the selected company/year scope.

<!-- capture:04-sec-inputs -->

![Valid SEC company and fiscal-year chips with the Download missing filings action.](../assets/04-sec-inputs.en.jpg)

*Historical screenshot of the previous separate company/year inputs. The new matrix still needs a verified capture; this image is not evidence of its layout.*

## 4. Download only missing filings {#step-4}

- **Goal:** make the required original files available for parsing.
- **Prerequisites:** valid selections from step 3 and the [source credentials](#sources).
- **Screen:** Build → Pipeline → Filings, selected-stage execution panel.
- **Inputs:** recheck **To be added**, grouped by SEC/DART. Missing or invalid selected originals are submitted.
  Credential notes appear only for registries with missing selections; the button is disabled when every selected original is valid.
- **Primary action:** **Sync selection**.
- **Visible result:** a queued or running job appears. Open Build → Jobs to read progress and the actual result.
  Preparation status updates automatically when the job finishes; no manual refresh is needed.
- **Completion:** the job succeeds and the sources in the returned processing selection are present.
  A global stage can remain incomplete because other manifest entries still lack sources.
- **Recovery:** inspect the job error and source identity before retrying. A cancelled job differs from a
  failed job or one interrupted by a restart; only supported states offer Retry. See [job diagnosis](troubleshooting.md).
- **Next:** [parse and create chunks](indexing.md#step-5).

SEC and DART share `manifest.json`. The selected source, companies, and fiscal years define the
acquisition scope. The job result supplies a `selection_id` naming the exact acquired sources; use it
for ingestion and embedding preparation. Other catalog entries remain available without joining that
selection. The [one-filing CLI procedure](cli.md#prepare-one-nvidia-filing) uses the same contract.

## Source requirements {#sources}

| Source | Identifier | Required configuration | Typical manifest |
|---|---|---|---|
| SEC EDGAR | Ticker, for example `NVDA` | A real name and reachable email in `SEC_USER_AGENT` | `manifest.json` |
| DART | Six-digit stock code, for example `005930` | Valid `DART_API_KEY` | `manifest.json` |

Keep credentials in local configuration. Do not place them in screenshots, copied request examples,
or Git. Follow [environment setup](environment.md) when configuration must be applied. Reading these
instructions does not start acquisition or a model call.

Downloaded sources are separate from database documents, chunks, embeddings, and published snapshots.
See [the implementation map](architecture.md) for those boundaries.

## Downloaded state and the current selection

Inventory refreshes update disk status without overwriting an edited selection. Use **Select
everything on disk** to adopt the current downloaded set explicitly. **Clear selection** leaves
all files intact. Return from Parse & chunk with **Change selection in Filings**. A clean start uses
`uv run python -m scripts.schema recreate`; `--sample` presets the sample and
`--keep-sources` preserves files. Compare reset scopes in the [CLI guide](cli.md).

## Delete current originals from Filings

In step 1, select downloaded originals and choose **Delete selected originals**. The preview lists
exact registry, company, fiscal year, filing/document IDs, relative file paths and sizes. It marks
shared or past input files that will be preserved. Nothing is deleted until **Confirm deletion of
originals**. Cancel and **Clear selection** preserve both source bytes and recorded inputs.

Confirmation queues a job; it is not a completed deletion. Read the result in **Jobs**. The preview
expires after five minutes and is single-use. Changed files/catalogs, an expired confirmation or a
service restart require a new preview. Deletion jobs do not offer blind retry. Deleted originals
must be downloaded again before a new parse. Database documents, chunks, embeddings, snapshots
and past job inputs remain available; this action does not cascade into derived data.

### SCREENSHOT NEEDED

<!-- SCREENSHOT NEEDED: feature=source-deletion; state=exact-target-preview-and-queued-result; locale=en; theme=light; issue=200; preserve-existing-assets=true -->

## Current files and preserved inputs

Current originals use `sec/<accession>/primary.html`, or `dart/<receipt>/primary.xml` with
`original.zip`. Metadata retains the official URL and filename. A repeated download replaces the
same current path and registration. Equivalent legacy copies are consolidated only after verifying
identity and bytes; conflicting valid copies block automatic selection. Other catalogs and past jobs
keep referenced inputs. New parse jobs pin verified bytes under `inputs/` before queueing.

Inventory refreshes use file existence, size and modification metadata, rechecking content when a
file changes. Download completion and parse selection still verify the complete bytes. Downloads
publish through temporary files and a filesystem journal; a failed publication restores previous
bytes. An unresolved `.source-transaction` blocks selection, deletion and reset; retry acquisition
to recover a proven transaction. Foreign changes or damaged recovery evidence require inspection.

Clean start resets managed originals, pinned inputs, manifests and the draft together. It preserves
unrelated files and `--keep-sources` preserves the source set. The existing reset journal remains
available when the database or cleanup outcome is uncertain.
