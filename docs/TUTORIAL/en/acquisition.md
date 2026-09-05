# Acquire SEC and DART filings

> [!DEV]
> Editing acquisition inputs and downloading filings require DEV. The public pipeline can be inspected, but its acquisition controls cannot start work.

Acquisition downloads original reports and records their identities in a manifest. Parsing and database
storage happen later. Check [Documents](documents.md#step-2) first: a report already prepared in this
environment does not need another download.

## 3. Choose source, companies, and years {#step-3}

- **Goal:** define the source reports you intend to prepare.
- **Prerequisites:** [environment checks](environment.md#step-1) complete; know which reports are missing.
- **Screen:** Build → Pipeline → Filings → Change….
- **Inputs:** choose SEC EDGAR with `NVDA` and `2024`, or DART with `005930` and `2024` for a Korean report.
  The year is the report's fiscal year, not necessarily its publication year.
- **Primary action:** select the company and year chips. This configures the form without downloading.
- **Visible result:** each accepted identifier and year appears as a removable chip; the terminal
  reference reflects the same values.
- **Completion:** registry, companies, and years describe the intended source, with no invalid draft left.
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
- **Completion:** the job succeeds and the sources required by the manifest you will ingest are present.
  A global stage can remain incomplete because other manifest entries still lack sources.
- **Recovery:** inspect the job error and source identity before retrying. A cancelled job differs from a
  failed job or one interrupted by a restart; only supported states offer Retry. See [job diagnosis](troubleshooting.md).
- **Next:** [parse and create chunks](indexing.md#step-5).

The SEC web action uses the main `manifest.json`. Selecting a year controls discovery; existing entries
for the selected issuer in other years may also be downloaded if their files are missing. It is not a
guarantee of exactly one downloaded file. For a strictly bounded example, use the
[one-filing CLI procedure](cli.md#prepare-one-nvidia-filing), then inspect its result in the same UI.

## Source requirements {#sources}

| Source | Identifier | Required configuration | Typical manifest |
|---|---|---|---|
| SEC EDGAR | Ticker, for example `NVDA` | A real name and reachable email in `SEC_USER_AGENT` | `manifest.json` |
| DART | Six-digit stock code, for example `005930` | Valid `DART_API_KEY` | `dart-manifest.json` |

Keep credentials in local configuration. Do not place them in screenshots, copied request examples,
or Git. Follow [environment setup](environment.md) when configuration must be applied. Reading these
instructions does not start acquisition or a model call.

Downloaded sources are separate from database documents, chunks, embeddings, and published snapshots.
See [the implementation map](architecture.md) for those boundaries.
