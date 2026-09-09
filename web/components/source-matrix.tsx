"use client";

import { useEffect, useId, useState } from "react";
import { Info, ListChecks, ListX, MousePointer2 } from "lucide-react";
import type { AcquisitionForm, AcquisitionPair } from "@/components/build-pipeline";
import { type AcquisitionCompany } from "@/lib/acquisition-catalog";
import { acquisitionDraft, acquisitionPairs, pairKey, selectedSourceState, sourceSelectionRows, type SourceInventory } from "@/lib/source-selection";
import { useI18n } from "@/lib/i18n";
import { TokenSelect, type TokenOption } from "./token-select";
import { SourceDeleteDialog } from "./source-delete-dialog";
import { SourceSelectionGrid } from "./source-selection-grid";
import "./source-matrix.css";

interface SourceMatrixProps {
  sources: SourceInventory[];
  companies: AcquisitionCompany[];
  acquisition: AcquisitionForm;
  onChange: (next: AcquisitionForm) => void;
  disabled?: boolean;
  onValidityChange?: (valid: boolean) => void;
  onDownload: (next: AcquisitionForm) => void;
  downloadDisabled: boolean;
  onDeleteSources?: (token: string) => Promise<void>;
  deleteDisabled?: boolean;
  onOpenJobs?: () => void;
}

/** Stage missing or recoverable pairs and submit the exact synchronized draft atomically. */
export function SourceMatrix({ sources, companies, acquisition, onChange, disabled = false, onValidityChange, onDownload, downloadDisabled, onDeleteSources, deleteDisabled = false, onOpenJobs }: SourceMatrixProps) {
  const { t } = useI18n();
  const scopeId = useId();
  const [scopeOpen, setScopeOpen] = useState(false);
  const latestYear = new Date().getFullYear() - 1;
  const [chosen, setChosen] = useState<Array<{ registry: "sec" | "dart"; issuer: string }>>([]);
  const [basket, setBasket] = useState<Array<{ registry: "sec" | "dart"; issuer: string }>>([]);
  const [hiddenCompanies, setHiddenCompanies] = useState<string[]>([]);
  const [staged, setStaged] = useState<AcquisitionPair[]>([]);
  const [pickerValid, setPickerValid] = useState(true);
  const pairs = acquisitionPairs(acquisition);
  const state = selectedSourceState(sources, acquisition);
  const merged = acquisitionPairs(acquisitionDraft([...pairs, ...staged]));
  const pending = selectedSourceState(sources, acquisitionDraft(merged)).downloadPairs;
  const valid = merged.length > 0 && pickerValid;
  useEffect(() => { onValidityChange?.(valid); }, [valid, onValidityChange]);
  const rows = sourceSelectionRows(sources, pairs, companies);
  const catalog = new Map<string, TokenOption>();
  for (const company of companies) {
    const issuer = company.issuer.toUpperCase();
    const selectedYears = merged.filter((pair) => pair.registry === company.registry && pair.issuer === issuer).map((pair) => pair.year);
    const availableYears = new Set([
      ...sources.filter((source) => source.registry === company.registry && source.issuer.toUpperCase() === issuer).map((source) => source.fiscal_year),
      ...selectedYears,
      ...Array.from({ length: 6 }, (_, index) => new Date().getFullYear() - 1 - index),
    ]);
    catalog.set(`${company.registry}:${issuer}`, {
      value: `${company.registry}:${issuer}`,
      label: company.name && company.name !== issuer ? `${company.name} · ${issuer}` : issuer,
      meta: t("Basket {selected} / {total} years", { selected: new Set(selectedYears).size, total: availableYears.size }),
      badge: { label: company.registry.toUpperCase(), tone: company.registry === "sec" ? "blue" : "amber" },
    });
  }
  const yearChoices = [...new Set([
    ...sources.filter((source) => chosen.some((company) => source.registry === company.registry && source.issuer.toUpperCase() === company.issuer)).map((source) => source.fiscal_year),
    ...merged.filter((pair) => chosen.some((company) => pair.registry === company.registry && pair.issuer === company.issuer)).map((pair) => pair.year),
    ...Array.from({ length: 6 }, (_, index) => new Date().getFullYear() - 1 - index),
  ])].sort((a, b) => a - b);
  const checkedYears = yearChoices.filter((year) => chosen.every((company) => merged.some((pair) => pairKey(pair) === pairKey({ ...company, year })))).map(String);

  /** Toggle exact sparse pairs without deriving a company/year cross product. */
  function toggle(changed: AcquisitionPair[], include: boolean) {
    const next = new Map(pairs.map((pair) => [pairKey(pair), pair]));
    for (const pair of changed) if (include) next.set(pairKey(pair), pair); else next.delete(pairKey(pair));
    const keys = new Set(changed.map(pairKey));
    setStaged((current) => current.filter((pair) => !keys.has(pairKey(pair))));
    onChange(acquisitionDraft([...next.values()]));
  }
  /** Accept only catalog identities, including pasted exact supported codes. */
  function chooseCompanies(values: string[]) {
    const added = values.flatMap((value) => {
      const company = companies.find((item) => `${item.registry}:${item.issuer.toUpperCase()}` === value);
      return company ? [{ registry: company.registry, issuer: company.issuer.toUpperCase() }] : [];
    });
    setHiddenCompanies((current) => current.filter((key) => !added.some((company) => `${company.registry}:${company.issuer}` === key)));
    setChosen(added.slice(0, 1));
    setBasket((current) => [...new Map([...current, ...added].map((company) => [`${company.registry}:${company.issuer}`, company])).values()]);
    setPickerValid(true);
  }
  /** Resolve known issuer codes without opening a free-form acquisition route. */
  function knownCodes(value: string): string[] | null {
    const tokens = value.toUpperCase().split(/[\s,]+/).filter(Boolean);
    const matched = tokens.map((token) => companies.find((company) => company.issuer.toUpperCase() === token));
    return matched.length && matched.every(Boolean) ? matched.map((company) => `${company!.registry}:${company!.issuer.toUpperCase()}`) : null;
  }
  /** On-disk choices select immediately; absent or partial years await explicit synchronization. */
  function chooseYears(values: string[]) {
    const removed = chosen.flatMap((company) => checkedYears.filter((year) => !values.includes(year)).map((year) => ({ ...company, year: Number(year) })));
    const added = chosen.flatMap((company) => values.filter((year) => !checkedYears.includes(year)).map((year) => ({ ...company, year: Number(year) })));
    const ready = added.filter((pair) => selectedSourceState(sources, acquisitionDraft([pair])).complete);
    const removedKeys = new Set(removed.map(pairKey));
    const next = pairs.filter((pair) => !removedKeys.has(pairKey(pair)));
    if (removed.length || ready.length) onChange(acquisitionDraft([...next, ...ready]));
    setStaged((current) => acquisitionPairs(acquisitionDraft([...current.filter((pair) => !removedKeys.has(pairKey(pair))), ...added.filter((pair) => !ready.includes(pair))])));
  }
  /** Remove the company's selection and card, retaining all downloaded source files. */
  function removeCompany(company: { registry: "sec" | "dart"; issuer: string }) {
    const matches = (item: { registry: string; issuer: string }) => item.registry === company.registry && item.issuer === company.issuer;
    setHiddenCompanies((current) => [...current, `${company.registry}:${company.issuer}`]);
    setBasket((current) => current.filter((item) => !matches(item)));
    setChosen((current) => current.filter((item) => !matches(item)));
    setStaged((current) => current.filter((item) => !matches(item)));
    onChange(acquisitionDraft(pairs.filter((item) => !matches(item))));
    setPickerValid(true);
  }
  /** Pass the next draft to the request instead of reading stale React state after onChange. */
  function sync() {
    if (disabled || downloadDisabled || !valid || !pending.length) return;
    const next = acquisitionDraft(merged);
    onChange(next);
    setStaged([]);
    onDownload(next);
  }

  return <section className="source-matrix" aria-label={t("Company and fiscal-year selection")}>
    <div className="source-company-search">
      <TokenSelect label={t("Search/add company or year")} placeholder={t("Search company name, SEC ticker or DART code")}
        values={[]} options={[...catalog.values()].sort((a, b) => a.value.localeCompare(b.value))}
        onChange={chooseCompanies} parseCustom={knownCodes} invalidMessage={t("Choose a company from the supported catalog.")}
        hint={t("Basket counts show selected years / available years. Choose a company to edit its scope.")} disabled={disabled}
        hideValues commitOnBlur={false} integratedAdd overlayOptions />
    </div>
    <p className="helper">{t("Clearing a selection keeps the downloaded originals. Delete originals separately to remove them from disk.")}</p>
    {!rows.some((group) => group.rows.length) && <p>{t("No sources yet. Add a company and fiscal year below.")}</p>}
    <section className="source-basket" aria-label={t("Company basket")}><header><div className="source-basket-title"><h4>{t("Company basket")}</h4><span className="source-scope-trigger" onMouseEnter={() => setScopeOpen(true)} onMouseLeave={() => setScopeOpen(false)} onKeyDown={(event) => { if (event.key === "Escape") setScopeOpen(false); }}>
      <button type="button" aria-label={t("Supported document scope")} aria-describedby={scopeOpen ? scopeId : undefined} onFocus={() => setScopeOpen(true)} onBlur={() => setScopeOpen(false)} onClick={() => setScopeOpen((open) => !open)}><Info size={14} aria-hidden="true" /></button>
      {scopeOpen && <div id={scopeId} role="tooltip" className="source-scope-tooltip"><strong>DocReview RAG v2.0</strong><p>{t("Supported documents: SEC 10-K filings and DART annual business reports.")}</p><dl>{(["dart", "sec"] as const).map((registry) => <div key={registry}><dt>{registry.toUpperCase()}</dt><dd>{companies.filter((company) => company.registry === registry).map((company) => `${company.name} (${company.issuer})`).join(", ") || t("Checking status")}</dd></div>)}<div><dt>{t("Fiscal years")}</dt><dd>{t("Default: {first}–{last}", { first: latestYear - 5, last: latestYear })}</dd></div></dl><p>{t("Existing source and selected years are also available. Actual filing availability varies by company and year.")}</p></div>}
    </span></div><div className="source-basket-tools">
      <span className="source-basket-tool"><button type="button" aria-label={t("Select everything on disk")} disabled={disabled} onClick={() => { setHiddenCompanies([]); onChange(acquisitionDraft(rows.flatMap((group) => group.rows.flatMap((row) => row.cells.filter((cell) => cell.documents.some((source) => source.on_disk)).map((cell) => cell.pair))))); }}><ListChecks size={16} aria-hidden="true" /></button><span role="tooltip">{t("Select everything on disk")}</span></span>
      <span className="source-basket-tool"><button type="button" aria-label={t("Clear selection")} disabled={disabled || !merged.length} onClick={() => { setStaged([]); onChange(acquisitionDraft([])); }}><ListX size={16} aria-hidden="true" /></button><span role="tooltip">{t("Clear selection")}</span></span>
    {onDeleteSources && <SourceDeleteDialog documentIds={sources.map((source) => source.document_id)} disabled={disabled || deleteDisabled} onConfirm={onDeleteSources} onOpenJobs={onOpenJobs} />}
    </div></header>
    <p className="source-matrix-summary" role="status"><span>{t("Selected on disk: {count}", { count: state.present.length })}</span> · <span>{t("To download: {count}", { count: state.downloadPairs.length })}</span> · <span>{t("On disk not selected: {count}", { count: state.excluded.length })}</span></p>
    <div className="source-year-legend"><span><span className="year-downloaded-mark" aria-hidden="true">✓</span>{t("Downloaded")}</span><span><span className="source-year-pending" aria-hidden="true">✓</span>{t("Awaiting download")}</span><span><MousePointer2 size={11} aria-hidden="true" />{t("Click to select or deselect")}</span></div>
    <SourceSelectionGrid sources={sources.filter((source) => !hiddenCompanies.includes(`${source.registry}:${source.issuer}`))} pairs={merged} companies={companies} disabled={disabled} onToggle={toggle}
      addedCompanies={basket} onRemoveCompany={removeCompany}
      onEditCompany={(company) => { setChosen((current) => current.length === 1 && current[0].registry === company.registry && current[0].issuer === company.issuer ? [] : [company]); setPickerValid(true); }}
      renderYearEditor={(company) => chosen[0]?.registry === company.registry && chosen[0]?.issuer === company.issuer && <div className="source-matrix-add">
      <div className="source-year-candidates" role="group" aria-label={t("Available years")}>
        {yearChoices.filter((year) => !checkedYears.includes(String(year))).map((year) => {
          const downloaded = chosen.every((item) => selectedSourceState(sources, acquisitionDraft([{ ...item, year }])).complete);
          return <button type="button" key={year} disabled={disabled} aria-label={`FY${year}`} aria-description={downloaded ? t("Downloaded") : t("Missing source")} onClick={() => chooseYears([...checkedYears, String(year)])}>{downloaded && <span className="year-downloaded-mark" aria-hidden="true">✓</span>}FY{year}</button>;
        })}
        {yearChoices.every((year) => checkedYears.includes(String(year))) && <span className="helper">{t("All available years are selected.")}</span>}
      </div>
    </div>} />
    <section className="source-matrix-plan" aria-label={t("To be added")}>
      {(["sec", "dart"] as const).map((registry) => {
        const missing = pending.filter((pair) => pair.registry === registry);
        return missing.length ? <div key={registry}><p className="helper">{t(registry === "sec" ? "EDGAR downloads need SEC_USER_AGENT in .env." : "DART downloads need DART_API_KEY in .env.")}</p></div> : null;
      })}
      <div className="source-sync-actions">
      {!pending.length && <p>{t("No missing sources selected.")}</p>}
      <button type="button" className="button primary" disabled={disabled || downloadDisabled || !valid || !pending.length} onClick={sync}>{t("Sync selection")}</button>
      </div>
    </section>
    </section>
  </section>;
}
