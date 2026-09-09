"use client";

import { useState, type ReactNode, type CSSProperties } from "react";
import { Plus, X } from "lucide-react";
import type { AcquisitionPair } from "./build-pipeline";
import type { AcquisitionCompany } from "@/lib/acquisition-catalog";
import { pairKey, sourceSelectionRows, type SourceInventory } from "@/lib/source-selection";
import { useI18n } from "@/lib/i18n";
import "./source-matrix.css";

interface Props {
  sources: SourceInventory[];
  pairs: AcquisitionPair[];
  companies: AcquisitionCompany[];
  disabled?: boolean;
  scopeMode?: boolean;
  corpusScope?: string;
  selectedOnly?: boolean;
  eligibleOnly?: boolean;
  addedCompanies?: Array<{ registry: "sec" | "dart"; issuer: string }>;
  onEditCompany?: (company: { registry: "sec" | "dart"; issuer: string }) => void;
  onRemoveCompany?: (company: { registry: "sec" | "dart"; issuer: string }) => void;
  renderYearEditor?: (company: { registry: "sec" | "dart"; issuer: string }) => ReactNode;
  onToggle?: (pairs: AcquisitionPair[], included: boolean) => void;
}

/** Render a compact, accessible company/year grid for selection or a read-only summary. */
export function SourceSelectionGrid({ sources, pairs, companies, disabled, scopeMode = false, corpusScope = "auto", selectedOnly = false, eligibleOnly = false, onToggle, addedCompanies = [], onEditCompany, onRemoveCompany, renderYearEditor }: Props) {
  const { t } = useI18n();
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const selected = new Set(pairs.map(pairKey));
  const groups = sourceSelectionRows(sources, pairs, companies, selectedOnly);
  for (const company of addedCompanies) {
    const group = groups.find((group) => group.registry === company.registry)!;
    if (!group.rows.some((row) => row.issuer === company.issuer)) {
      const name = companies.find((item) => item.registry === company.registry && item.issuer === company.issuer)?.name;
      group.rows.push({ issuer: company.issuer, label: `${company.issuer}${name && name !== company.issuer ? ` · ${name}` : ""}`, cells: [] });
    }
  }
  return <div className="source-selection-grid">{groups.map(({ registry, rows: allRows }) => {
    const rows = eligibleOnly ? allRows.map((row) => ({ ...row, cells: row.cells.filter((cell) => cell.documents.length > 0 && cell.documents.every((source) => source.on_disk && source.ready === true)) })).filter((row) => row.cells.length > 0) : allRows;
    if (!rows.length) return null;
    const outsideScope = scopeMode && corpusScope !== "auto" && corpusScope !== registry;
    const years = [...new Set(rows.flatMap((row) => row.cells.map((cell) => cell.pair.year)))].sort((a, b) => a - b);
    const columns = years.length <= 6;
    return <section key={registry} className="source-matrix-registry" aria-label={registry.toUpperCase()}>
      <h4>{registry.toUpperCase()}</h4>
      {(expanded[registry] ? rows : rows.slice(0, 8)).map((row) => {
        const count = row.cells.filter((cell) => selected.has(pairKey(cell.pair))).length;
        const ready = row.cells.filter((cell) => cell.documents.length > 0 && cell.documents.every((source) => source.on_disk));
        return <div className="source-matrix-row" key={row.issuer} role="group" aria-label={row.label}>
          <label className="source-matrix-company">
            {onToggle && !selectedOnly && !onRemoveCompany && <input type="checkbox" disabled={disabled || outsideScope} checked={count === row.cells.length} ref={(node) => { if (node) node.indeterminate = count > 0 && count < row.cells.length; }} aria-label={t("Select all years for {company}", { company: row.label })} onChange={(event) => onToggle(row.cells.map((cell) => cell.pair), event.target.checked)} />}
            <span>{row.label}</span>
          </label>
          <div className={`source-matrix-years${columns ? " aligned" : ""}`} style={{ "--year-columns": years.length } as CSSProperties}>{row.cells.map((cell) => {
            const key = pairKey(cell.pair); const onDisk = ready.includes(cell); const included = selected.has(key);
            const blocked = cell.documents.some((source) => source.on_disk && source.ready === false);
            const label = `${row.issuer} FY${cell.pair.year} · ${t(scopeMode ? outsideScope ? "Outside current scope" : included ? "In scope" : "Not in scope" : blocked ? "Source blocked" : onDisk ? "On disk" : "Missing source")}`;
            const title = `${cell.documents.find((source) => source.blocker)?.blocker ?? label}${cell.documents.length ? ` · ${cell.documents.map((source) => source.document_id).join(", ")}` : ""}`;
            const style = columns ? { gridColumn: years.indexOf(cell.pair.year) + 1 } : undefined;
            const content = <><span className={onDisk && !blocked ? "year-downloaded-mark" : "year-missing-mark"} aria-hidden="true">{onDisk && !blocked ? "✓" : "!"}</span><span>FY{cell.pair.year}</span>{cell.documents.length > 1 && <small>{cell.documents.filter((source) => source.on_disk).length}/{cell.documents.length}</small>}</>;
            const className = `source-matrix-year ${onDisk ? "on-disk" : "missing"}${included ? " selected" : ""}${blocked ? " source-blocked" : ""}`;
            return onToggle ? <button key={key} type="button" disabled={disabled || outsideScope} style={style} title={title} className={className} aria-pressed={included} aria-label={label} onClick={() => onToggle([cell.pair], !included)}>{content}</button> : <span key={key} style={style} title={title} className={className} aria-label={label}>{content}</span>;
          })}</div>
          {(onEditCompany || onRemoveCompany) && <div className="source-company-controls">
            {onEditCompany && <button type="button" disabled={disabled || outsideScope} aria-label={t("Add years for {company}", { company: row.label })} onClick={() => onEditCompany({ registry, issuer: row.issuer })}><Plus size={14} aria-hidden="true" /></button>}
            {onRemoveCompany && <button type="button" disabled={disabled || outsideScope} aria-label={t("Remove {company} from basket", { company: row.label })} onClick={() => onRemoveCompany({ registry, issuer: row.issuer })}><X size={14} aria-hidden="true" /></button>}
          </div>}
          {renderYearEditor?.({ registry, issuer: row.issuer })}
          <span className="source-matrix-row-summary" aria-label={t(scopeMode ? "{ready} of {total} years in scope" : "{ready} of {total} years on disk", { ready: scopeMode ? outsideScope ? 0 : count : ready.length, total: row.cells.length })}>{scopeMode ? outsideScope ? 0 : count : ready.length}/{row.cells.length}</span>
        </div>;
      })}
      {rows.length > 8 && <button type="button" className="source-matrix-expand" aria-expanded={Boolean(expanded[registry])} onClick={() => setExpanded((current) => ({ ...current, [registry]: !current[registry] }))}>{t(expanded[registry] ? "Show fewer companies" : "Show all companies")} ({rows.length})</button>}
    </section>;
  })}</div>;
}
