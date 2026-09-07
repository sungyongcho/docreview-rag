"use client";

import { useEffect, useId, useRef, useState } from "react";
import type { AcquisitionForm, AcquisitionPair } from "@/components/build-pipeline";
import type { AcquisitionCompany } from "@/lib/acquisition-catalog";
import { acquisitionDraft, acquisitionPairs, selectedSourceState, type SourceInventory } from "@/lib/source-selection";
import { useI18n } from "@/lib/i18n";
import "./source-matrix.css";

interface SourceMatrixProps {
  sources: SourceInventory[];
  companies: AcquisitionCompany[];
  acquisition: AcquisitionForm;
  onChange: (next: AcquisitionForm) => void;
  disabled?: boolean;
  onValidityChange?: (valid: boolean) => void;
  onDownload: () => void;
  downloadDisabled: boolean;
}
interface Cell { pair: AcquisitionPair; documents: SourceInventory[] }
const VISIBLE_COMPANIES = 8;

/** Keep registry identity explicit even when two adapters use the same issuer spelling. */
function pairKey(pair: AcquisitionPair): string { return `${pair.registry}:${pair.issuer}:${pair.year}`; }

/** Use the acquisition form's existing company-code syntax for add-only controls. */
function companyCodes(input: string): string[] | null {
  const codes = [...new Set(input.toUpperCase().split(/[\s,]+/).filter(Boolean))];
  return codes.length && codes.every((code) => /^[A-Z][A-Z0-9]*(?:[.-][A-Z0-9]+)*$/.test(code) || /^\d{6}$/.test(code)) ? codes : null;
}

/** Expand explicit years and bounded ascending ranges without changing invalid text. */
function fiscalYears(input: string): number[] | null {
  const years: number[] = [];
  for (const token of input.split(/[\s,]+/).filter(Boolean)) {
    if (/^\d{4}$/.test(token) && Number(token) > 0) years.push(Number(token));
    else {
      const range = token.match(/^(\d{4})-(\d{4})$/);
      if (!range) return null;
      const first = Number(range[1]); const last = Number(range[2]);
      if (first <= 0 || last < first || last - first >= 50) return null;
      years.push(...Array.from({ length: last - first + 1 }, (_, index) => first + index));
    }
  }
  return years.length ? [...new Set(years)].sort((a, b) => a - b) : null;
}

/** One controlled company/year draft shared by downloads and downstream indexing. */
export function SourceMatrix({ sources, companies, acquisition, onChange, disabled = false, onValidityChange, onDownload, downloadDisabled }: SourceMatrixProps) {
  const { t } = useI18n();
  const id = useId();
  const [codesText, setCodesText] = useState("");
  const [yearsText, setYearsText] = useState("");
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [focusKey, setFocusKey] = useState<string | null>(null);
  const chips = useRef(new Map<string, HTMLButtonElement>());
  const pairs = acquisitionPairs(acquisition, sources);
  const selected = new Set(pairs.map(pairKey));
  const state = selectedSourceState(sources, acquisition);
  const uniqueSources = [...new Map(sources.map((source) => [`${source.registry}:${source.document_id}`, source])).values()];
  const cells = new Map<string, Cell>();
  for (const source of uniqueSources) {
    if (source.registry !== "sec" && source.registry !== "dart") continue;
    const pair: AcquisitionPair = { registry: source.registry, issuer: source.issuer.toUpperCase(), year: source.fiscal_year };
    const key = pairKey(pair);
    if (!cells.has(key)) cells.set(key, { pair, documents: [] });
    cells.get(key)!.documents.push(source);
  }
  for (const pair of pairs) if (!cells.has(pairKey(pair))) cells.set(pairKey(pair), { pair, documents: [] });
  const codes = companyCodes(codesText); const years = fiscalYears(yearsText);
  const adding = Boolean(codesText.trim() || yearsText.trim());
  const existingCompany = codes?.length === 1 && !yearsText.trim() ? [...cells.values()].filter((cell) => cell.pair.issuer === codes[0]).sort((a, b) => a.pair.year - b.pair.year)[0] : undefined;
  const addValid = codes !== null && (years !== null || existingCompany !== undefined);
  const valid = pairs.length > 0 && (!adding || addValid);
  useEffect(() => { onValidityChange?.(valid); }, [valid, onValidityChange]);
  useEffect(() => {
    if (!focusKey) return;
    const chip = chips.current.get(focusKey);
    if (chip) { chip.focus(); setFocusKey(null); }
  }, [focusKey, acquisition, expanded]);

  /** Select the catalog spelling, otherwise the most frequent name across unique documents. */
  function displayName(registry: string, issuer: string): string {
    const catalog = companies.find((company) => company.registry === registry && company.issuer.toUpperCase() === issuer)?.name?.trim();
    if (catalog) return catalog;
    const counts = new Map<string, number>();
    for (const source of uniqueSources) if (source.registry === registry && source.issuer.toUpperCase() === issuer && source.name?.trim()) counts.set(source.name.trim(), (counts.get(source.name.trim()) ?? 0) + 1);
    return [...counts.entries()].sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]))[0]?.[0] ?? "";
  }
  /** Toggle only the requested sparse pairs, never recreate a company/year cross product. */
  function toggle(changed: AcquisitionPair[], include: boolean) {
    const next = new Map(pairs.map((pair) => [pairKey(pair), pair]));
    for (const pair of changed) if (include) next.set(pairKey(pair), pair); else next.delete(pairKey(pair));
    onChange(acquisitionDraft([...next.values()]));
  }
  /** Reuse the shared parser for new combinations; existing matrix entries only receive focus. */
  function addPairs() {
    if (disabled || !codes) return;
    if (existingCompany && !years) {
      setExpanded((current) => ({ ...current, [existingCompany.pair.registry]: true }));
      setFocusKey(pairKey(existingCompany.pair));
      setCodesText("");
      return;
    }
    if (!years) return;
    const requested = acquisitionPairs({ identifiers: codes.join(" "), years: years.join(" ") }, sources);
    const fresh = requested.filter((pair) => !cells.has(pairKey(pair)));
    if (fresh.length) toggle(fresh, true);
    if (requested[0]) {
      setExpanded((current) => ({ ...current, [requested[0].registry]: true }));
      setFocusKey(pairKey(requested[0]));
    }
    setCodesText(""); setYearsText("");
  }

  return <section className="source-matrix" aria-label={t("Company and fiscal-year selection")}>
    <p className="source-matrix-summary" role="status">{t("Selected on disk: {count}", { count: state.present.length })} · {t("To download: {count}", { count: state.missingPairs.length })} · {t("On disk not selected: {count}", { count: state.excluded.length })}</p>
    <div className="source-matrix-actions">
      <button type="button" disabled={disabled} onClick={() => onChange(acquisitionDraft([...cells.values()].filter((cell) => cell.documents.some((source) => source.on_disk)).map((cell) => cell.pair)))}>{t("Select everything on disk")}</button>
      <button type="button" disabled={disabled || !pairs.length} onClick={() => onChange(acquisitionDraft([]))}>{t("Clear selection")}</button>
    </div>
    {!cells.size && <p>{t("No sources yet. Add a company and fiscal year below.")}</p>}
    {(["sec", "dart"] as const).map((registry) => {
      const registryCells = [...cells.values()].filter((cell) => cell.pair.registry === registry);
      const issuers = [...new Set(registryCells.map((cell) => cell.pair.issuer))].sort();
      if (!issuers.length) return null;
      const visible = expanded[registry] ? issuers : issuers.slice(0, VISIBLE_COMPANIES);
      return <section key={registry} className="source-matrix-registry" aria-label={registry.toUpperCase()}>
        <h4>{registry.toUpperCase()}</h4>
        {visible.map((issuer) => {
          const row = registryCells.filter((cell) => cell.pair.issuer === issuer).sort((left, right) => left.pair.year - right.pair.year);
          const selectedCount = row.filter((cell) => selected.has(pairKey(cell.pair))).length;
          const ready = row.filter((cell) => cell.documents.length > 0 && cell.documents.every((source) => source.on_disk));
          const missing = row.filter((cell) => !ready.includes(cell));
          const name = displayName(registry, issuer);
          const label = `${issuer}${name && name !== issuer ? ` · ${name}` : ""}`;
          return <div key={issuer} className="source-matrix-row" role="group" aria-label={label}>
            <label className="source-matrix-company"><input type="checkbox" disabled={disabled} checked={selectedCount === row.length} ref={(node) => { if (node) node.indeterminate = selectedCount > 0 && selectedCount < row.length; }} aria-label={t("Select all years for {company}", { company: label })} onChange={(event) => toggle(row.map((cell) => cell.pair), event.target.checked)} /><span>{label}</span></label>
            <div className="source-matrix-years">{row.map((cell) => {
              const key = pairKey(cell.pair); const onDisk = ready.includes(cell); const included = selected.has(key);
              const status = t(onDisk ? "On disk" : "Missing source");
              return <button key={key} ref={(node) => { if (node) chips.current.set(key, node); else chips.current.delete(key); }} type="button" disabled={disabled} aria-pressed={included} aria-label={`${issuer} FY${cell.pair.year} · ${status}`} className={`source-matrix-year ${onDisk ? "on-disk" : "missing"}${included ? " selected" : ""}`} onClick={() => toggle([cell.pair], !included)}><span>FY{cell.pair.year}</span><span className="source-matrix-state">{status}</span>{cell.documents.length > 1 && <small>{cell.documents.filter((source) => source.on_disk).length} / {cell.documents.length}</small>}</button>;
            })}</div>
            <p className="source-matrix-row-summary">{ready.length} / {row.length}{missing.length > 0 && <> · {t("Missing years")}: {missing.map((cell) => `FY${cell.pair.year}`).join(", ")}</>}</p>
          </div>;
        })}
        {issuers.length > VISIBLE_COMPANIES && <button className="source-matrix-expand" type="button" aria-expanded={Boolean(expanded[registry])} onClick={() => setExpanded((current) => ({ ...current, [registry]: !current[registry] }))}>{t(expanded[registry] ? "Show fewer companies" : "Show all companies")} ({issuers.length})</button>}
      </section>;
    })}
    <div className="source-matrix-add" onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); if (addValid) addPairs(); } }}>
      <h4>{t("Add a company or fiscal year")}</h4>
      <label htmlFor={`${id}-company`}>{t("Tickers / stock codes")}</label>
      <input id={`${id}-company`} value={codesText} disabled={disabled} placeholder={t("Enter SEC tickers or DART stock codes")} aria-invalid={Boolean(codesText.trim() && !codes)} aria-describedby={codesText.trim() && !codes ? `${id}-company-error` : undefined} onChange={(event) => setCodesText(event.target.value)} />
      {codesText.trim() && !codes && <p id={`${id}-company-error`} role="alert">{t("Use a SEC ticker such as NVDA or a six-digit DART stock code such as 005930.")}</p>}
      <label htmlFor={`${id}-years`}>{t("Fiscal years")}</label>
      <input id={`${id}-years`} value={yearsText} disabled={disabled} placeholder={t("Add a year or range, for example 2023-2025")} aria-invalid={Boolean(yearsText.trim() && !years)} aria-describedby={yearsText.trim() && !years ? `${id}-year-error` : undefined} onChange={(event) => setYearsText(event.target.value)} />
      {yearsText.trim() && !years && <p id={`${id}-year-error`} role="alert">{t("Use a four-digit year or an ascending range of up to 50 years.")}</p>}
      <button type="button" disabled={disabled || !addValid} onClick={addPairs}>{t(existingCompany && !years ? "Find company" : "Add to selection")}</button>
      <p className="helper">{t("Existing company-years are focused; only new pairs are added.")}</p>
    </div>
    <section className="source-matrix-plan" aria-label={t("Download plan")}>
      <h4>{t("Download plan")}</h4>
      {state.missingPairs.length ? (["sec", "dart"] as const).map((registry) => {
        const missing = state.missingPairs.filter((pair) => pair.registry === registry);
        return missing.length ? <div key={registry}><p><strong>{registry.toUpperCase()}</strong>: {missing.map((pair) => `${pair.issuer} FY${pair.year}`).join(", ")}</p><p className="helper">{t(registry === "sec" ? "EDGAR downloads need SEC_USER_AGENT in .env." : "DART downloads need DART_API_KEY in .env.")}</p></div> : null;
      }) : <p>{t("No missing sources selected.")}</p>}
      <button type="button" className="button" disabled={disabled || downloadDisabled || !valid || !state.missingPairs.length} onClick={onDownload}>{t("Download missing filings")}</button>
    </section>
  </section>;
}
