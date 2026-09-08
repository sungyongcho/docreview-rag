"use client";

import { useState, type CSSProperties } from "react";
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
  selectedOnly?: boolean;
  onToggle?: (pairs: AcquisitionPair[], included: boolean) => void;
}

/** Render a compact, accessible company/year grid for selection or a read-only summary. */
export function SourceSelectionGrid({ sources, pairs, companies, disabled, selectedOnly = false, onToggle }: Props) {
  const { t } = useI18n();
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const selected = new Set(pairs.map(pairKey));
  return <div className="source-selection-grid">{sourceSelectionRows(sources, pairs, companies, selectedOnly).map(({ registry, rows }) => {
    if (!rows.length) return null;
    const years = [...new Set(rows.flatMap((row) => row.cells.map((cell) => cell.pair.year)))].sort((a, b) => a - b);
    const columns = years.length <= 6;
    return <section key={registry} className="source-matrix-registry" aria-label={registry.toUpperCase()}>
      <h4>{registry.toUpperCase()}</h4>
      {(expanded[registry] ? rows : rows.slice(0, 8)).map((row) => {
        const count = row.cells.filter((cell) => selected.has(pairKey(cell.pair))).length;
        const ready = row.cells.filter((cell) => cell.documents.length > 0 && cell.documents.every((source) => source.on_disk));
        return <div className="source-matrix-row" key={row.issuer} role="group" aria-label={row.label}>
          <label className="source-matrix-company">
            {onToggle && !selectedOnly && <input type="checkbox" disabled={disabled} checked={count === row.cells.length} ref={(node) => { if (node) node.indeterminate = count > 0 && count < row.cells.length; }} aria-label={t("Select all years for {company}", { company: row.label })} onChange={(event) => onToggle(row.cells.map((cell) => cell.pair), event.target.checked)} />}
            <span>{row.label}</span>
          </label>
          <div className={`source-matrix-years${columns ? " aligned" : ""}`} style={{ "--year-columns": years.length } as CSSProperties}>{row.cells.map((cell) => {
            const key = pairKey(cell.pair); const onDisk = ready.includes(cell); const included = selected.has(key);
            const blocked = cell.documents.some((source) => source.on_disk && source.ready === false);
            const label = `${row.issuer} FY${cell.pair.year} · ${t(blocked ? "Source blocked" : onDisk ? "On disk" : "Missing source")}`;
            const title = `${cell.documents.find((source) => source.blocker)?.blocker ?? label}${cell.documents.length ? ` · ${cell.documents.map((source) => source.document_id).join(", ")}` : ""}`;
            const style = columns ? { gridColumn: years.indexOf(cell.pair.year) + 1 } : undefined;
            const content = <><span aria-hidden="true">{onDisk ? "✓" : "!"}</span><span>FY{cell.pair.year}</span>{cell.documents.length > 1 && <small>{cell.documents.filter((source) => source.on_disk).length}/{cell.documents.length}</small>}</>;
            const className = `source-matrix-year ${onDisk ? "on-disk" : "missing"}${included ? " selected" : ""}`;
            return onToggle ? <button key={key} type="button" disabled={disabled} style={style} title={title} className={className} aria-pressed={included} aria-label={label} onClick={() => onToggle([cell.pair], !included)}>{content}</button> : <span key={key} style={style} title={title} className={className} aria-label={label}>{content}</span>;
          })}</div>
          <span className="source-matrix-row-summary" aria-label={t("{ready} of {total} years on disk", { ready: ready.length, total: row.cells.length })}>{ready.length}/{row.cells.length}</span>
        </div>;
      })}
      {rows.length > 8 && <button type="button" className="source-matrix-expand" aria-expanded={Boolean(expanded[registry])} onClick={() => setExpanded((current) => ({ ...current, [registry]: !current[registry] }))}>{t(expanded[registry] ? "Show fewer companies" : "Show all companies")} ({rows.length})</button>}
    </section>;
  })}</div>;
}
