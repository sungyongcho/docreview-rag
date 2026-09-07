"use client";

import { useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { evidencePage } from "@/lib/evidence";
import { STAGE_LABELS, collectedNumber, formatDuration } from "@/lib/execution-format";
import { useI18n } from "@/lib/i18n";

export type CompanyLabels = Record<string, string>;
export type ValueKind = "plain" | "registry" | "issuer" | "year" | "duration" | "status" | "citation" | "score" | "code" | "stage";

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
  if (key === "score") return "score";
  if (key === "node") return "stage";
  if (key.endsWith("_id") || key.endsWith("_ids") || key === "code") return "code";
  return "plain";
}

/** Render structured facts without JSON punctuation and distinguish empty values from missing data. */
export function RecordedValue({ value, kind = "plain", companyLabels = {}, registries = [] }: { value: unknown; kind?: ValueKind; companyLabels?: CompanyLabels; registries?: string[] }) {
  const { t, locale } = useI18n();
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
  if (kind === "duration") return <span className="review-number" title={collectedNumber(value) ? `${value}ms` : undefined}>{formatDuration(value, locale, t("Not collected"))}</span>;
  if (kind === "score" && typeof value === "number" && Number.isFinite(value)) return <span className="review-number" title={String(value)}>{value.toPrecision(4)}</span>;
  if (kind === "code") return <code>{text}</code>;
  if (kind === "stage") return <><span>{t(STAGE_LABELS[text] ?? "Unknown stage")}</span><code className="review-node-code">{text}</code></>;
  if (kind === "status") return <span className={`review-recorded-status ${["completed", "succeeded"].includes(text) ? "is-complete" : text === "failed" ? "is-failed" : ""}`}><span>{t(text)}</span><code className="review-node-code">{text}</code></span>;
  if (kind === "citation") text = text.replace(/^\[(.*)\]$/, "$1");
  return ["registry", "issuer", "year", "citation"].includes(kind) ? <span className={`review-value-chip ${kind}`}>{text}</span> : <>{text}</>;
}

export interface RecordedColumn { key: string; label: string; kind?: ValueKind }

/** Paginate recorded collections consistently without dropping ranks or collection order. */
export function RecordedTable({ label, rows, columns, companyLabels = {}, registries = [], collapsed = false }: { label: string; rows: Record<string, unknown>[]; columns: RecordedColumn[]; companyLabels?: CompanyLabels; registries?: string[]; collapsed?: boolean }) {
  const { t } = useI18n();
  const [pageIndex, setPageIndex] = useState(0);
  const { items, page, pages } = evidencePage(rows, pageIndex);
  const content = rows.length ? <>
    <div className="review-recorded-scroll"><table className="review-recorded-table"><caption>{t(label)}</caption><thead><tr>{columns.map((column) => <th key={column.key} scope="col">{t(column.label)}</th>)}</tr></thead><tbody>{items.map((row, index) => <tr key={index}>{columns.map((column) => <td key={column.key}><RecordedValue value={row[column.key]} kind={column.kind} companyLabels={companyLabels} registries={registries} /></td>)}</tr>)}</tbody></table></div>
    {pages > 1 && <nav className="review-recorded-pager" aria-label={t("{table} pages", { table: t(label) })}>
      <button type="button" aria-label={t("Previous page")} disabled={page === 0} onClick={() => setPageIndex(page - 1)}><ChevronLeft size={16} aria-hidden="true" /></button>
      <span>{page + 1}/{pages}</span>
      <button type="button" aria-label={t("Next page")} disabled={page === pages - 1} onClick={() => setPageIndex(page + 1)}><ChevronRight size={16} aria-hidden="true" /></button>
    </nav>}
  </> : <p className="review-value-empty">{t(label)}: {t("None")}</p>;
  return collapsed ? <details className="review-recorded-disclosure"><summary>{t(label)} ({rows.length})</summary>{content}</details> : content;
}

/** Group repeated nodes while preserving ordered passes and incomplete measurements. */
export function RecordedStageTimings({ rows }: { rows: Record<string, unknown>[] }) {
  const { t } = useI18n();
  const groups = new Map<string, Record<string, unknown>[]>();
  for (const row of rows) {
    const key = String(row.node ?? "");
    groups.set(key, [...(groups.get(key) ?? []), row]);
  }
  if (!rows.length) return <p className="review-value-empty">{t("Stage timings")}: {t("None")}</p>;
  return <div className="review-recorded-scroll"><table className="review-recorded-table review-timing-groups">
    <caption>{t("Stage timings")}</caption><thead><tr>{["Order", "Stage", "Status", "Total elapsed", "Recorded passes"].map((label) => <th key={label} scope="col">{t(label)}</th>)}</tr></thead>
    <tbody>{[...groups.entries()].map(([node, passes]) => {
      const total = passes.every((pass) => collectedNumber(pass.elapsed_ms)) ? passes.reduce((sum, pass) => sum + (pass.elapsed_ms as number), 0) : undefined;
      const statuses = [...new Set(passes.map((pass) => pass.status))];
      return <tr key={node}><td>{String(passes[0].order).padStart(2, "0")}</td><td><RecordedValue value={node || undefined} kind="stage" /></td><td>{statuses.map((status, index) => <RecordedValue key={index} value={status} kind="status" />)}</td><td><RecordedValue value={total} kind="duration" /></td><td>{passes.length > 1 ? <details><summary>{t("Recorded passes")} ×{passes.length}</summary><RecordedTable label="Recorded passes" rows={passes} columns={[{ key: "order", label: "Order" }, { key: "status", label: "Status", kind: "status" }, { key: "elapsed_ms", label: "Elapsed", kind: "duration" }]} /></details> : <span>×1</span>}</td></tr>;
    })}</tbody>
  </table></div>;
}
