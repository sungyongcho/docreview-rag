"use client";

import { useEffect, useState } from "react";
import type { AcquisitionForm, AcquisitionPair } from "@/components/build-pipeline";
import { acquisitionRegistry, type AcquisitionCompany } from "@/lib/acquisition-catalog";
import { acquisitionDraft, acquisitionPairs, pairKey, selectedSourceState, sourceSelectionRows, type SourceInventory } from "@/lib/source-selection";
import { useI18n } from "@/lib/i18n";
import { TokenSelect, type TokenOption } from "./token-select";
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
}

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

/** Stage missing pairs separately and submit the exact synchronized draft atomically. */
export function SourceMatrix({ sources, companies, acquisition, onChange, disabled = false, onValidityChange, onDownload, downloadDisabled }: SourceMatrixProps) {
  const { t } = useI18n();
  const [chosen, setChosen] = useState<Array<{ registry: "sec" | "dart"; issuer: string }>>([]);
  const [staged, setStaged] = useState<AcquisitionPair[]>([]);
  const [pickerValid, setPickerValid] = useState(true);
  const pairs = acquisitionPairs(acquisition, sources);
  const state = selectedSourceState(sources, acquisition);
  const merged = acquisitionPairs(acquisitionDraft([...pairs, ...staged]));
  const pending = acquisitionPairs(acquisitionDraft([...state.missingPairs, ...staged]));
  const valid = merged.length > 0 && pickerValid;
  useEffect(() => { onValidityChange?.(valid); }, [valid, onValidityChange]);
  const rows = sourceSelectionRows(sources, pairs, companies);
  const catalog = new Map<string, TokenOption>();
  for (const company of companies) catalog.set(`${company.registry}:${company.issuer.toUpperCase()}`, { value: `${company.registry}:${company.issuer.toUpperCase()}`, label: `${company.issuer.toUpperCase()}${company.name ? ` · ${company.name}` : ""} · ${t("{count} years on disk", { count: 0 })}`, badge: { label: company.registry.toUpperCase(), tone: company.registry === "sec" ? "blue" : "amber" } });
  for (const { registry, rows: group } of rows) for (const row of group) catalog.set(`${registry}:${row.issuer}`, { value: `${registry}:${row.issuer}`, label: `${row.label} · ${t("{count} years on disk", { count: row.cells.filter((cell) => cell.documents.length && cell.documents.every((source) => source.on_disk)).length })}`, badge: { label: registry.toUpperCase(), tone: registry === "sec" ? "blue" : "amber" } });
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
    onChange(acquisitionDraft([...next.values()]));
  }
  /** Known choices preserve their registry; free entries use the existing code convention. */
  function chooseCompanies(values: string[]) {
    setChosen(values.map((value) => {
      const [registry, issuer] = value.split(":");
      return issuer ? { registry: registry as "sec" | "dart", issuer } : { registry: acquisitionRegistry(value, companies), issuer: value };
    }));
    setPickerValid(true);
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
  /** Remove pending requests only, preserving every other selected pair and all files. */
  function removePending(removing: AcquisitionPair[]) {
    const keys = new Set(removing.map(pairKey));
    setStaged((current) => current.filter((pair) => !keys.has(pairKey(pair))));
    onChange(acquisitionDraft(pairs.filter((pair) => !keys.has(pairKey(pair)))));
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
    <p className="source-matrix-summary" role="status">{t("Selected on disk: {count}", { count: state.present.length })} · {t("To download: {count}", { count: state.missingPairs.length })} · {t("On disk not selected: {count}", { count: state.excluded.length })}</p>
    <div className="source-matrix-actions">
      <button type="button" disabled={disabled} onClick={() => onChange(acquisitionDraft(rows.flatMap((group) => group.rows.flatMap((row) => row.cells.filter((cell) => cell.documents.some((source) => source.on_disk)).map((cell) => cell.pair)))))}>{t("Select everything on disk")}</button>
      <button type="button" disabled={disabled || !pairs.length} onClick={() => onChange(acquisitionDraft([]))}>{t("Clear selection")}</button>
    </div>
    {!rows.some((group) => group.rows.length) && <p>{t("No sources yet. Add a company and fiscal year below.")}</p>}
    <SourceSelectionGrid sources={sources} pairs={pairs} companies={companies} disabled={disabled} onToggle={toggle} />
    <div className="source-matrix-add">
      {chosen.length > 0 && <div className="source-picker-context"><strong>{chosen.map((company) => `${company.registry.toUpperCase()} · ${company.issuer}`).join(", ")}</strong><button type="button" disabled={disabled} onClick={() => { setChosen([]); setPickerValid(true); }}>{t("Change company")}</button></div>}
      <TokenSelect key={chosen.map((company) => `${company.registry}:${company.issuer}`).join(",") || "companies"}
        label={t("Search/add company or year")} placeholder={t(chosen.length ? "Add a year or range, for example 2023-2025" : "Enter SEC tickers or DART stock codes")}
        values={chosen.length ? checkedYears : []} options={chosen.length ? yearChoices.map((year) => ({ value: String(year), label: `FY${year}` })) : [...catalog.values()].sort((a, b) => a.value.localeCompare(b.value))}
        onChange={chosen.length ? chooseYears : chooseCompanies} parseCustom={chosen.length ? (value) => fiscalYears(value)?.map(String) ?? null : companyCodes}
        invalidMessage={t(chosen.length ? "Use a four-digit year or an ascending range of up to 50 years." : "Use a SEC ticker such as NVDA or a six-digit DART stock code such as 005930.")}
        hint={t(chosen.length ? "Check years to stage missing sources. On-disk years join the selection immediately." : "Search a company, then check its fiscal years. Unknown codes can be entered directly.")}
        disabled={disabled} onValidityChange={setPickerValid} checkable={chosen.length > 0} hideValues commitOnBlur={false} autoFocus={chosen.length > 0} overlayOptions />
    </div>
    <section className="source-matrix-plan" aria-label={t("To be added")}>
      <header><h4>{t("To be added")} <span className="source-pending-count">{pending.length}</span></h4><button type="button" disabled={disabled || !pending.length} onClick={() => removePending(pending)}>{t("Clear pending")}</button></header>
      {(["sec", "dart"] as const).map((registry) => {
        const missing = pending.filter((pair) => pair.registry === registry);
        return missing.length ? <div key={registry}><h5>{registry.toUpperCase()}</h5><ul className="source-pending-list">{missing.map((pair) => <li key={pairKey(pair)}><span>{pair.issuer} FY{pair.year}</span><button type="button" disabled={disabled} aria-label={t("Remove {value}", { value: `${pair.issuer} FY${pair.year}` })} onClick={() => removePending([pair])}>{t("Remove")}</button></li>)}</ul><p className="helper">{t(registry === "sec" ? "EDGAR downloads need SEC_USER_AGENT in .env." : "DART downloads need DART_API_KEY in .env.")}</p></div> : null;
      })}
      {!pending.length && <p>{t("No missing sources selected.")}</p>}
      <button type="button" className="button" disabled={disabled || downloadDisabled || !valid || !pending.length} onClick={sync}>{t("Sync selection")}</button>
    </section>
  </section>;
}
