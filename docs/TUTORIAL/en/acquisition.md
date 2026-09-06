# Acquire SEC and DART filings

## Reference acquisition scope

The initial draft reflects primary sources actually on disk. With no sources it is empty; `schema_status recreate --sample` explicitly presets **NVDA, AMD**, FY**2023, 2024**, without downloading. Company choices come from the current manifest and remain available before ingestion; the reference manifest includes: SEC offers NVDA, AMD, INTC and MU; DART offers Samsung Electronics (005930), SK hynix (000660) and NAVER (035420). Choose companies from one combined list. SEC and DART use distinct colored text badges; there is no registry tab. A mixed selection queues one source-specific acquisition job per registry and retains their explicit selections in the common manifest.

The suggested five-year test range is **2020–2024**. Suggestions do not add years automatically, and a year being selectable does not guarantee that the provider has published the requested filing. The displayed filing count counts available primary documents, not archive files or overlapping processing selections.

Source acquisition can proceed while corpus schema drift blocks indexing, provided source storage and tracked-job storage are available. Read the separate schema diagnosis rather than changing HOST_GID for a schema problem. After acquisition completes, Parse & chunk automatically continues from these companies and fiscal years.

Company and year suggestions open directly below the active input, above nearby hints and quick-add controls. Select SEC and DART companies together in that same list; source badges identify each selection.

### SCREENSHOT NEEDED

<!-- SCREENSHOT NEEDED: feature=mixed-company-picker-and-input-anchored-overlays; locale=en; theme=light; capture=seven-company-options-source-badges-and-year-overlay; issue=17; preserve-existing-assets=true -->

**Screenshot pending for the updated controls and resulting state. Existing screenshots are unchanged.**


> [!DEV]
> Editing acquisition inputs and downloading filings require DEV. The public pipeline can be inspected, but its acquisition controls cannot start work.

Acquisition downloads original reports and records their identities in the common `manifest.json`. Parsing and database
storage happen later. Check [Documents](documents.md#step-2) first: a report already prepared in this
environment does not need another download.

## 3. Choose companies and years {#step-3}

- **Goal:** define the source reports you intend to prepare.
- **Prerequisites:** [environment checks](environment.md#step-1) complete; know which reports are missing.
- **Screen:** Build → Pipeline → Filings → Change….
- **Inputs:** choose `NVDA` and `2024`, or `005930` and `2024` for a Korean report. Both sources can be selected together.
  The year is the report's fiscal year, not necessarily its publication year.
- **Primary action:** select the company and year chips. This configures the form without downloading.
- **Visible result:** each accepted identifier and year appears as a removable chip; the terminal
  reference reflects the same values.
- **Completion:** companies and years describe the intended source, with no invalid draft left.
- **Recovery:** keep an invalid draft visible, correct the highlighted token, and press Enter. For source
  credentials or unavailable reports, see [acquisition failures](troubleshooting.md).
- **Next:** [download missing sources](#step-4), or [parse existing sources](indexing.md#step-5).

Search existing companies by identifier or name. Labels use names supplied by actual source metadata;
missing or conflicting names fall back to the identifier. Selecting a name still submits its stable code.
Multiple identifiers can be pasted together. Remove an unwanted chip individually.

Years must have four digits. An ascending range such as `2023-2025` expands to individual years;
the input accepts at most 50 years and removes duplicates. Invalid text remains visible and disables
acquisition. Finish or correct it before pressing the action button, including after leaving the field.

<!-- capture:04-sec-inputs -->

![Valid SEC company and fiscal-year chips with the Download missing filings action.](../assets/04-sec-inputs.en.jpg)

*Valid SEC company and fiscal-year chips with the Download missing filings action. Existing NVDA/AMD and FY2023/FY2024 inputs are shown; no download was started. Used for steps 3 and 4.*

## 4. Download only missing filings {#step-4}

- **Goal:** make the required original files available for parsing.
- **Prerequisites:** valid selections from step 3 and the [source credentials](#sources).
- **Screen:** Build → Pipeline → Filings, selected-stage execution panel.
- **Inputs:** recheck the source, identifiers, years, and manifest scope shown above the action.
- **Primary action:** **Download missing filings**.
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

**Downloaded sources** lists registry → company → fiscal year and on-disk counts, separately from **Change…**. The draft shows selected sources already on disk, missing company/year pairs, and downloaded sources excluded by the draft. Editing the draft never removes downloaded files. A step is done only when the current nonempty selection is fully present; an empty draft or missing source remains actionable.

After Download finishes, the inventory refreshes. An untouched draft automatically reconciles with the new disk inventory. If you have edited it, your choice stays and **Sync draft with downloaded sources** explicitly replaces it with the downloaded company/year scope when inventory changes. Return from Parse & chunk with **Change selection in Filings**. A clean start uses `uv run python -m scripts.schema_status recreate`; `--sample` presets the sample, while `--keep-sources` preserves sources. Compare its scope with the broader `rag-fresh-start` in the [CLI guide](cli.md).

### SCREENSHOT NEEDED
<!-- Feature: downloaded sources grouped by registry/company/year, separate draft and missing/excluded delta; locale=en; light mode; capture empty and completed current selection. Preserve existing assets. -->

Existing screenshots show the previous draft summary, not proof of the new downloaded-state list.
