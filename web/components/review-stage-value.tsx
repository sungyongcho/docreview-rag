"use client";

import type { ReactNode } from "react";
import { useI18n } from "@/lib/i18n";

export type CompanyLabels = Record<string, string>;
export type ValueKind = "plain" | "registry" | "issuer" | "year" | "duration" | "status" | "citation";

/** Preserve the code and accept only an unambiguous name from the resolved registries. */
export function stageCompanyLabel(issuer: string, registries: string[], labels: CompanyLabels): string {
  const allowed = new Set(registries.map((registry) => registry.toLowerCase()));
  const matches = Object.entries(labels).filter(([key]) => {
    const separator = key.indexOf(":");
    return key.slice(separator + 1).toUpperCase() === issuer.toUpperCase() && (!allowed.size || allowed.has(key.slice(0, separator)));
  }).map(([, label]) => label.trim()).filter(Boolean);
  const unique = [...new Set(matches)];
  if (unique.length !== 1) return issuer;
  return unique[0].toUpperCase() === issuer.toUpperCase() || unique[0].toUpperCase().startsWith(`${issuer.toUpperCase()} · `) ? unique[0] : `${issuer} · ${unique[0]}`;
}

/** Use readable labels for known record keys while retaining every other recorded key. */
export function recordedFieldLabel(key: string): string {
  const labels: Record<string, string> = { node: "Stage", status: "Status", elapsed_ms: "Elapsed (ms)", model: "Model", attempts: "Attempts", input_tokens: "Input tokens", output_tokens: "Output tokens", error: "Error", label: "Final label", answer: "Answer", citation_chunk_ids: "Citation chunk IDs", reason: "Reason", code: "Code", removed_chunk_ids: "Removed chunk IDs", message: "Message" };
  return labels[key] ?? key.replaceAll("_", " ");
}

/** Map nested field identities to the same compact presentation as top-level fields. */
function kindForKey(key: string): ValueKind {
  if (["registry", "registries"].includes(key)) return "registry";
  if (["issuer", "issuers"].includes(key)) return "issuer";
  if (["fiscal_year", "fiscal_years"].includes(key)) return "year";
  if (key.endsWith("elapsed_ms")) return "duration";
  if (key === "status") return "status";
  if (key === "citation") return "citation";
  return "plain";
}

/** Render structured facts without JSON punctuation and distinguish empty values from missing data. */
export function RecordedValue({ value, kind = "plain", companyLabels = {}, registries = [] }: { value: unknown; kind?: ValueKind; companyLabels?: CompanyLabels; registries?: string[] }) {
  const { t } = useI18n();
  if (value === null || value === undefined) return <span className="review-value-missing" aria-label={t("Not recorded for this run")}>—</span>;
  if (Array.isArray(value)) return value.length ? <ul className="review-value-list">{value.map((item, index) => <li key={index}><span className={kind === "plain" && (typeof item !== "object" || item === null) ? "review-value-chip" : undefined}><RecordedValue value={item} kind={kind} companyLabels={companyLabels} registries={registries} /></span></li>)}</ul> : <span className="review-value-empty">{t("None")}</span>;
  if (typeof value === "object") {
    const entries = Object.entries(value);
    return entries.length ? <dl className="review-value-record">{entries.map(([key, item]) => <div key={key}><dt>{t(recordedFieldLabel(key))}</dt><dd><RecordedValue value={item} kind={kindForKey(key)} companyLabels={companyLabels} registries={registries} /></dd></div>)}</dl> : <span className="review-value-empty">{t("None")}</span>;
  }
  let text = String(value);
  if (kind === "issuer") text = stageCompanyLabel(text, registries, companyLabels);
  if (kind === "registry") text = text.toUpperCase();
  if (kind === "year") text = `FY${text}`;
  if (kind === "duration" && typeof value === "number" && Number.isFinite(value)) text = value.toFixed(1);
  if (kind === "status") text = t(text);
  if (kind === "citation") text = text.replace(/^\[(.*)\]$/, "$1");
  return ["registry", "issuer", "year"].includes(kind) ? <span className={`review-value-chip ${kind}`}>{text}</span> : <>{text}</>;
}

export interface RecordedColumn { key: string; label: string; kind?: ValueKind }

/** Bound long recorded collections with an explicit disclosure while retaining every row. */
export function RecordedTable({ label, rows, columns, companyLabels = {}, registries = [] }: { label: string; rows: Record<string, unknown>[]; columns: RecordedColumn[]; companyLabels?: CompanyLabels; registries?: string[] }) {
  const { t } = useI18n();
  /** Repeat semantic column headers for the optional continuation table. */
  function table(items: Record<string, unknown>[], caption: ReactNode) {
    return <table className="review-recorded-table"><caption>{caption}</caption><thead><tr>{columns.map((column) => <th key={column.key} scope="col">{t(column.label)}</th>)}</tr></thead><tbody>{items.map((row, index) => <tr key={index}>{columns.map((column) => <td key={column.key}><RecordedValue value={row[column.key]} kind={column.kind} companyLabels={companyLabels} registries={registries} /></td>)}</tr>)}</tbody></table>;
  }
  if (!rows.length) return <p className="review-value-empty">{t(label)}: {t("None")}</p>;
  return <>{table(rows.slice(0, 8), t(label))}{rows.length > 8 && <details className="review-recorded-more"><summary>{t("Show more recorded rows ({count})", { count: rows.length - 8 })}</summary>{table(rows.slice(8), t(label))}</details>}</>;
}
