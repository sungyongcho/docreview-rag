"use client";

import { useEffect, useState } from "react";
import { ChevronDown, FileJson, Plus, RefreshCw } from "lucide-react";
import { useI18n } from "@/lib/i18n";
import type { PublishedSnapshot, PublicSnapshotDataset } from "@/lib/types";
import { GoldenQuestionEditor } from "./golden-question-editor";
import { publishedDatasetLabel } from "@/lib/evaluation-labels";
import { DatasetLock } from "./dataset-lock";
import { DevLockedButton } from "./dev-locked-button";
import "./golden-preparation.css";

interface Props {
  snapshots: PublishedSnapshot[]; selected?: PublishedSnapshot; dataset: PublicSnapshotDataset | null;
  loading: boolean; error: boolean; busy: boolean; detailError: boolean;
  query: string; sort: string; offset: number; pageSize: number;
  onSelect: (id: number) => void; onQuery: (value: string) => void; onSort: (value: string) => void;
  onDetailChange?: (open: boolean) => void;
  onPage: (offset: number) => void; onRefresh: () => void; onRetry: () => void;
}

/** Match the DEV dataset layout using only verified public data and read-only actions. */
export function PublicGoldenDataset(props: Props) {
  const { t, locale } = useI18n();
  const [sourceOpen, setSourceOpen] = useState(false);
  const [openCase, setOpenCase] = useState<string | null>(null);
  const provenance = props.selected?.eval_result.config.golden_provenance as { filename?: string; kind?: string; verification_status?: string } | undefined;
  const filename = typeof provenance?.filename === "string" ? provenance.filename : props.selected?.suite_title ?? props.selected?.eval_result.suite ?? t("No published dataset");
  const registry = props.selected?.eval_result.suite.startsWith("dart") ? "DART" : "SEC";
  const language = props.selected?.eval_result.suite.endsWith("ko") ? "Korean" : "English";
  const total = props.dataset?.total ?? 0;
  const count = props.selected?.eval_result.metrics.query_count ?? total;
  const activeCase = props.dataset?.cases.find(row => row.id === openCase);
  useEffect(() => { props.onDetailChange?.(Boolean(activeCase)); }, [Boolean(activeCase), props.onDetailChange]);
  useEffect(() => () => props.onDetailChange?.(false), [props.onDetailChange]);
  return <>
    {activeCase && <GoldenQuestionEditor filename={filename} registry={registry.toLowerCase()} json={JSON.stringify(activeCase, null, 2)} readOnly dirty={false} busy={false} error="" issues={[]} onChange={() => {}} onSave={() => {}} onBack={() => setOpenCase(null)} />}
    <section hidden={Boolean(activeCase)} className="surface form-stack golden-controls evaluation-golden-controls">
      <div className="golden-dataset-selector"><label>{t("Evaluation dataset")}<select value={props.selected?.snapshot_id ?? ""} disabled={props.loading || !props.snapshots.length} onChange={event => { props.onSelect(Number(event.target.value)); setSourceOpen(false); setOpenCase(null); }}>
        {!props.snapshots.length && <option value="">{t("No published dataset")}</option>}
        {props.snapshots.map(row => <option key={row.snapshot_id} value={row.snapshot_id}>{publishedDatasetLabel(row, locale)}</option>)}
      </select></label><DevLockedButton reason="golden"><Plus size={15} />{t("Create draft")}</DevLockedButton></div>
      {props.loading && <p role="status">{t("Loading published snapshots…")}</p>}
      {props.error && <p role="alert">{t("Published snapshots could not be loaded.")} <button className="button" onClick={props.onRefresh}>{t("Retry")}</button></p>}
      {!props.loading && !props.error && !props.selected && <p>{t("No published snapshot names a dataset yet.")}</p>}
      {props.selected && <>
        <div className="golden-file golden-file-inline"><div className="golden-file-header"><FileJson size={18} aria-hidden="true" /><div className="golden-file-identity"><strong className="golden-file-title">{filename}<DatasetLock /></strong><div className="golden-file-traits">{registry} · {t(language)} · {t("Question count: {count}", { count })}<span className="golden-builtin-badge">{t(provenance?.kind === "builtin" ? "Built-in" : "Published")}</span></div></div><button className="button ghost" type="button" disabled={!props.dataset} aria-expanded={sourceOpen} onClick={() => setSourceOpen(value => !value)}>{t("View source JSON")}<ChevronDown size={15} aria-hidden="true" /></button></div>
        {sourceOpen && props.dataset && <div className="source-json"><h3>{t("Loaded published questions · read-only")}</h3><code>SHA-256 · {props.dataset.golden_sha256}</code><pre>{JSON.stringify(props.dataset.cases, null, 2)}</pre></div>}</div>
        <section className="golden-preparation" aria-label={t("Golden set readiness")}><div className="golden-status-fields"><span>{t("Type")}: <strong>{t(provenance?.kind === "builtin" ? "Built-in golden set" : "Published")}</strong></span><span>{t("Source")}: <strong>{registry}</strong></span><span>{t("Verification")}: <strong>{t(provenance?.verification_status === "verified" ? "Verified" : "Pending review")}</strong></span><span>{t("Run readiness")}: <strong>{t("DEV only")}</strong></span><button type="button" className="button" aria-label={t("Check updated status")} onClick={props.onRetry}><RefreshCw size={14} /></button></div><p className="helper">{t("Published questions and expected evidence are read-only. Evaluation runs in DEV mode.")}</p></section>
      </>}
    </section>
    <section hidden={Boolean(activeCase)} className="surface golden-manager" data-help="measure.golden.questions">
      <div className="surface-heading"><div><h2>{t("Golden questions")}</h2><p className="helper">{t(provenance?.kind === "builtin" ? "Built-in golden set" : "Published")} · {t("Questions")}: {total}</p></div><div className="action-row golden-question-actions"><DevLockedButton reason="evaluation" className="button primary">{t("Evaluate this dataset")}</DevLockedButton></div></div>
      <div className="golden-table-tools"><input aria-label={t("Search")} placeholder={t("Search ID or question")} value={props.query} onChange={event => props.onQuery(event.target.value)} /><select aria-label={t("Sort by")} value={props.sort} onChange={event => props.onSort(event.target.value)}><option value="id">{t("ID")}</option><option value="question">{t("Question")}</option></select></div>
      {props.busy && !props.dataset ? <p role="status">{t("Loading recorded evidence…")}</p> : props.detailError ? <div role="alert"><p>{t("This published record could not be verified or loaded. The current editable dataset is not used as a replacement.")}</p><button className="button" onClick={props.onRetry}>{t("Retry")}</button></div> : <>
        <div className="golden-table-scroll" aria-label={t("Golden questions")} onScroll={event => { const list = event.currentTarget; if (!props.busy && !props.detailError && props.dataset && props.offset + props.pageSize < total && list.scrollTop + list.clientHeight >= list.scrollHeight - 64) props.onPage(props.offset + props.pageSize); }}><table><thead><tr>{["ID", "Question", "Category", "Facet", "Tags"].map(label => <th key={label}>{t(label)}</th>)}</tr></thead><tbody>{props.dataset?.cases.map(row => <tr key={row.id} tabIndex={0} className={openCase === row.id ? "selected" : ""} onClick={() => setOpenCase(openCase === row.id ? null : row.id)} onKeyDown={event => { if (event.key === "Enter") setOpenCase(openCase === row.id ? null : row.id); }}><td><span className="golden-id-cell"><button className="row-detail" type="button" onClick={event => { event.stopPropagation(); setOpenCase(openCase === row.id ? null : row.id); }}>{row.id}</button></span></td><td>{row.question}</td><td>{t(row.category ?? "—")}</td><td>{t(row.facet)}</td><td>{row.tags.length ? row.tags.join(", ") : "—"}</td></tr>)}</tbody></table></div>
        {!total && <p className="helper">{t("No questions match this filter.")}</p>}
        {props.busy && props.dataset && <p role="status" className="helper">{t("Loading recorded evidence…")}</p>}
      </>}
      <p className="helper">{t("Hit, first rank, and reciprocal rank measure retrieval—not final-answer factuality.")}</p>
    </section>
  </>;
}
