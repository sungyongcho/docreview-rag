# Acquire SEC and DART filings

## Reference acquisition scope

The initial selection uses the exact company/year pairs actually on disk, without inventing
cross-company combinations. With no sources it is empty; `rag-schema recreate --sample`
explicitly presets **NVDA, AMD**, FY**2023, 2024**, without downloading.

The compact matrix groups SEC and DART companies with single-line fiscal-year tokens. A check
icon and filled background mean all sources for that year are on disk; `!` and a dashed outline
mark missing sources. A stronger border marks selection. Row checkboxes support partial selection;
**Select everything on disk**, **Clear selection**, and **Show all companies** retain their scope.
Names come from the catalog or a consistent source-record name. Document IDs remain in chip details.

Use **Search/add company or year** to find a code or name, then select the company and check its
years. Company suggestions show the registry and on-disk year count. Arrow Down/Up move through
suggestions; Enter or Space toggles a focused year, and Escape closes the list. The same input
accepts unknown SEC tickers or six-digit DART codes, then years or ranges such as `2023-2025`.
Choose **Change company** to add another company to the same pending list.

On-disk choices join the shared selection immediately. Missing pairs enter **To be added**,
grouped by registry with the required source credentials. **Remove** or **Clear pending** drops
requests without deleting files. **Sync selection** applies all pending pairs and downloads only
missing sources, using that exact draft even on the first click. Matrix-selected missing years
appear in this same list. Invalid input stays visible; correct it before syncing. Simply leaving
the search field does not add its unfinished text.

Source acquisition can proceed while schema drift blocks indexing, provided source storage and
tracked-job storage are available. After downloading, Parse & chunk receives the same exact
company/year pairs. Companies with different selected years are submitted separately so no
extra combinations are processed.

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

The stable company code is always visible. Free entry supports comma-separated codes and
ascending ranges of up to 50 years. Ready years are selected immediately; missing years are
applied only when you sync. Parsing receives the same exact selected pairs.

<!-- capture:04-sec-inputs -->

![Valid SEC company and fiscal-year chips with the Download missing filings action.](../assets/04-sec-inputs.en.jpg)

*Historical screenshot of the previous separate company/year inputs. The new matrix still needs a verified capture; this image is not evidence of its layout.*

## 4. Download only missing filings {#step-4}

- **Goal:** make the required original files available for parsing.
- **Prerequisites:** valid selections from step 3 and the [source credentials](#sources).
- **Screen:** Build → Pipeline → Filings, selected-stage execution panel.
- **Inputs:** recheck **To be added**, grouped by SEC/DART. Only missing years are submitted.
  Credential notes appear only for registries with missing selections; the button is disabled when none are missing.
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
