"use client";

import { useEffect, useId, useState } from "react";
import { Info, ListChecks, ListX, MousePointer2, MessageSquare } from "lucide-react";
import type { AcquisitionForm, AcquisitionPair } from "@/components/build-pipeline";
import { type AcquisitionCompany } from "@/lib/acquisition-catalog";
import { acquisitionDraft, acquisitionPairs, pairKey, selectedSourceState, sourceSelectionRows, type SourceInventory } from "@/lib/source-selection";
import { useI18n } from "@/lib/i18n";
import { PORTFOLIO_FILINGS } from "@/lib/published-scope";
import { DevModeBubble } from "./dev-mode-bubble";
import { HoverBubble } from "./hover-bubble";
import { DevLockedButton } from "./dev-locked-button";
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
  /** Read-only servers: the grid is a question scope and the download action is locked in place. */
  locked?: boolean;
  corpusScope?: string;
  askDisabled?: boolean;
  onAskScope?: (filters: { registries: string[]; issuers: string[]; fiscal_years: number[] }) => void;
}

/** Stage missing or recoverable pairs and submit the exact synchronized draft atomically. */
export function SourceMatrix({ sources, companies, acquisition, onChange, disabled = false, onValidityChange, onDownload, downloadDisabled, onDeleteSources, deleteDisabled = false, onOpenJobs, locked = false, corpusScope = "auto", askDisabled = false, onAskScope }: SourceMatrixProps) {
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

  if (locked) {
    const names: Record<string, string> = { NVDA: "NVIDIA · 엔비디아", AMD: "Advanced Micro Devices", "005930": "Samsung Electronics · 삼성전자", "000660": "SK hynix · SK하이닉스" };
    const publicCompanies = PORTFOLIO_FILINGS.map((target) => ({ registry: target.registry, issuer: target.issuer, name: names[target.issuer] }));
    const visible = sources.filter((source) => !hiddenCompanies.includes(`${source.registry}:${source.issuer}`));
    /** Add a target company to the browser basket; only published years become query filters. */
    function choosePublicCompanies(values: string[]) {
      const added = publicCompanies.filter((company) => values.includes(`${company.registry}:${company.issuer}`));
      setBasket((current) => [...new Map([...current, ...added].map((company) => [`${company.registry}:${company.issuer}`, company])).values()]);
      setHiddenCompanies((current) => current.filter((key) => !values.includes(key)));
      setChosen(added.slice(0, 1));
      const available = sources.filter((source) => added.some((company) => company.registry === source.registry && company.issuer === source.issuer));
      if (available.length) onChange(acquisitionDraft([...pairs, ...available.map((source) => ({ registry: source.registry, issuer: source.issuer, year: source.fiscal_year }))]));
    }
    const allPairs = acquisitionPairs(acquisitionDraft(sources.map((source) => ({ registry: source.registry, issuer: source.issuer, year: source.fiscal_year }))));
    const effective = pairs.filter((pair) => corpusScope === "auto" || pair.registry === corpusScope);
    return <section className="source-matrix" aria-label={t("Company and fiscal-year selection")}>
      <div className="source-company-search"><TokenSelect label={t("Search/add company or year")} placeholder={t("Search company name, SEC ticker or DART code")} values={[]} options={publicCompanies.map((company) => {
        const target = PORTFOLIO_FILINGS.find((row) => row.issuer === company.issuer)!;
        const published = new Set(sources.filter((source) => source.issuer === company.issuer).map((source) => source.fiscal_year)).size;
        return { value: `${company.registry}:${company.issuer}`, label: `${company.name} · ${company.issuer}`, meta: t("Published years: {published} / {total}", { published, total: target.last - target.first + 1 }), badge: { label: company.registry.toUpperCase(), tone: company.registry === "sec" ? "blue" as const : "amber" as const } };
      })} onChange={choosePublicCompanies} disabled={disabled} hideValues commitOnBlur={false} integratedAdd overlayOptions hint={t("Add a portfolio company to inspect its years. Only published filings can be selected for search.")} /></div>
      <section className="source-basket" aria-label={t("Company basket")}>
        <header><div className="source-basket-title"><h4>{t("Company basket")}</h4><HoverBubble pinnable width={360} label={t("Published corpus")} bubble={<><strong>{t("Published corpus")}</strong><p>NVDA / AMD · FY2019–2024<br />005930 / 000660 · FY2022–2024</p><p>{t("Keyword statistics use the server corpus, grouped by language.")}</p><p>{t("Unpublished years are preparation targets, not searchable documents.")}</p></>}><span className="source-scope-trigger"><button type="button" aria-label={t("Published corpus")}><Info size={14} /></button></span></HoverBubble></div><div className="source-basket-tools">
          <span className="source-basket-tool"><button type="button" disabled={disabled || !allPairs.length} aria-label={t("Select the whole corpus")} onClick={() => onChange(acquisitionDraft(allPairs))}><ListChecks size={16} /></button><span role="tooltip">{t("Select the whole corpus")}</span></span>
          <span className="source-basket-tool"><button type="button" disabled={disabled || !pairs.length} aria-label={t("Clear selection")} onClick={() => onChange(acquisitionDraft([]))}><ListX size={16} /></button><span role="tooltip">{t("Clear selection")}</span></span>
        </div></header>
        <p className="source-matrix-summary" role="status">{t("In scope: {count}", { count: effective.length })} · {t("Published company-years: {count}", { count: allPairs.length })}</p>
        <div className="source-year-legend"><span>{t("In scope")}</span><span>{t("Not in scope")}</span><span><MousePointer2 size={11} />{t("Click to select or deselect")}</span></div>
        <SourceSelectionGrid sources={visible} pairs={pairs.filter((pair) => visible.some((source) => source.registry === pair.registry && source.issuer === pair.issuer && source.fiscal_year === pair.year))} companies={publicCompanies} disabled={disabled} scopeMode corpusScope={corpusScope} onToggle={toggle}
          addedCompanies={basket.filter((company) => !hiddenCompanies.includes(`${company.registry}:${company.issuer}`))}
          onRemoveCompany={(company) => {
            setHiddenCompanies((current) => [...current, `${company.registry}:${company.issuer}`]);
            setBasket((current) => current.filter((item) => item.registry !== company.registry || item.issuer !== company.issuer));
            onChange(acquisitionDraft(pairs.filter((pair) => pair.registry !== company.registry || pair.issuer !== company.issuer)));
          }}
          onEditCompany={(company) => setChosen((current) => current[0]?.issuer === company.issuer ? [] : [company])}
          renderYearEditor={(company) => {
            if (chosen[0]?.issuer !== company.issuer) return null;
            const target = PORTFOLIO_FILINGS.find((row) => row.issuer === company.issuer);
            if (!target) return null;
            const missing = Array.from({ length: target.last - target.first + 1 }, (_, index) => target.first + index).filter((year) => !sources.some((source) => source.issuer === company.issuer && source.fiscal_year === year));
            return <div className="source-matrix-add"><div className="source-year-candidates" role="group" aria-label={t("Available years")}>{missing.map((year) => <DevModeBubble inline reason="This filing is not published. Prepare and publish it in DEV to enable search." key={year}><button type="button" aria-disabled="true" aria-label={`${company.issuer} FY${year} · ${t("Not published")}`} onClick={(event) => event.preventDefault()}>FY{year} · {t("Not published")}</button></DevModeBubble>)}</div>{missing.length > 0 && <p className="helper">{t("Unpublished years are preparation targets, not searchable documents.")}</p>}</div>;
          }} />
        {!visible.length && !basket.length && <p className="helper">{t("Choose a company above to explore the portfolio scope. Published documents will enable search.")}</p>}
        <div className="source-sync-actions"><button type="button" className="button primary" disabled={disabled || askDisabled || !effective.length} onClick={() => onAskScope?.({ registries: [], issuers: [], fiscal_years: [] })}><MessageSquare size={15} />{t("Ask about this scope")}</button><DevLockedButton reason="corpus">{t("Sync selection")}</DevLockedButton></div>
      </section>
    </section>;
  }

  return <section className="source-matrix" aria-label={t("Company and fiscal-year selection")}>
    <div className="source-company-search">
      <TokenSelect label={t("Search/add company or year")} placeholder={t("Search company name, SEC ticker or DART code")}
        values={[]} options={[...catalog.values()].sort((a, b) => a.value.localeCompare(b.value))}
        onChange={chooseCompanies} parseCustom={knownCodes} invalidMessage={t("Choose a company from the supported catalog.")}
        hint={t("Basket counts show selected years / available years. Choose a company to edit its scope.")} disabled={disabled}
        hideValues commitOnBlur={false} integratedAdd overlayOptions />
    </div>
    <p className="helper">{t(locked ? "Pick companies and years to scope your next question. Downloading more filings runs in DEV mode." : "Clearing a selection keeps the downloaded originals. Delete originals separately to remove them from disk.")}</p>
    {!rows.some((group) => group.rows.length) && <p>{t(locked ? "No published filings yet. They appear here once the operator publishes a snapshot." : "No sources yet. Add a company and fiscal year below.")}</p>}
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
        return missing.length && !locked ? <div key={registry}><p className="helper">{t(registry === "sec" ? "EDGAR downloads need SEC_USER_AGENT in .env." : "DART downloads need DART_API_KEY in .env.")}</p></div> : null;
      })}
      <div className="source-sync-actions">
      {!pending.length && !locked && <p>{t("No missing sources selected.")}</p>}
      {locked
        ? <>
          {onAskScope && <button type="button" className="button primary" onClick={() => onAskScope({ registries: [...new Set(merged.map((pair) => pair.registry))], issuers: [...new Set(merged.map((pair) => pair.issuer))], fiscal_years: [...new Set(merged.map((pair) => pair.year))].sort() })}><MessageSquare size={15} aria-hidden="true" />{merged.length ? t("Ask about {count} selected filings", { count: merged.length.toLocaleString() }) : t("Ask about the whole corpus")}</button>}
          <DevLockedButton reason="corpus">{t("Sync selection")}</DevLockedButton>
        </>
        : <button type="button" className="button primary" disabled={disabled || downloadDisabled || !valid || !pending.length} onClick={sync}>{t("Sync selection")}</button>}
      </div>
    </section>
    </section>
  </section>;
}
