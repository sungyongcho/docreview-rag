"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { RefreshCw, ArrowUpRight, Check, AlertCircle } from "lucide-react";
import { checkEvaluationPreparation, getGoldenSuites, getGoldenRevisions } from "@/lib/api";
import type { EvaluationRequest, EvaluationPreparation, GoldenSuite, GoldenRevision, SuiteId } from "@/lib/types";
import { useI18n } from "@/lib/i18n";
import "./golden-preparation.css";

/** Show source matching independently from author review and index readiness. */
export function GoldenPreparation({ request, onChecked, onOpenSources }: { onOpenSources?: () => void; request: EvaluationRequest; onChecked?: (result: EvaluationPreparation | null) => void }) {
  const { t } = useI18n();
  const [result, setResult] = useState<EvaluationPreparation | null>(null);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const callback = useRef(onChecked); callback.current = onChecked;
  useEffect(() => { const refresh = () => setRevision(value => value + 1); window.addEventListener("docreview:golden-files-changed", refresh); return () => window.removeEventListener("docreview:golden-files-changed", refresh); }, []);
  const key = JSON.stringify(request);
  useEffect(() => {
    const controller = new AbortController();
    setResult(null); setError(""); callback.current?.(null);
    void checkEvaluationPreparation(JSON.parse(key), controller.signal).then((value) => {
      if (!controller.signal.aborted) { setResult(value); callback.current?.(value); }
    }).catch((reason) => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : String(reason)); });
    return () => controller.abort();
  }, [key, revision]);
  const states = { draft_incomplete: "Complete the unfinished questions first", ready: "Ready to evaluate", source_missing: "Originals required", source_invalid: "Source verification required", parsing_required: "Parsing required", index_update_required: "Index update required", unavailable: "Preparation check unavailable" };
  return <section className="golden-preparation" aria-label={t("Golden set readiness")}>
    <div className="golden-status-fields"><span>{t("Type")}: <strong>{t(request.golden_revision_id == null ? "Built-in golden set" : "User golden set")}</strong></span><span>{t("Source")}: <strong>{request.suite_id.startsWith("dart") ? "DART" : "SEC"}</strong></span><span>{t("Verification")}: <strong>{t(result?.verification_status === "verified" ? "Verified" : "Pending review")}</strong></span>{result && result.source_checks.length > 0 && <span>{t("Required evaluation sources")}: <strong>{result.source_checks.filter((source) => source.state === "ready").length}/{result.source_checks.length}</strong></span>}<span>{t("Run readiness")}: <strong>{t(result ? states[result.state] : error ? "Preparation check unavailable" : "Checking status")}</strong></span><button type="button" className="button" aria-label={t("Check updated status")} onClick={() => setRevision((value) => value + 1)}><RefreshCw size={14} aria-hidden="true" /></button></div>
    {error && <p role="alert">{error}</p>}
    {result && result.state !== "ready" && <p className="helper" role="status">{t(result.state === "draft_incomplete" ? "Save and complete every draft question before evaluating this dataset." : "Prepare the required originals and indexes before evaluating. Review status is separate from run readiness.")}</p>}
    {result && (result.source_checks.length > 0 || result.blockers.length > 0) && <details><summary>{t("Required originals and preparation details")}</summary><div className="golden-source-groups">{[...new Set(result.source_checks.map((source) => `${source.registry}:${source.issuer}`))].map((key) => {
      const sources = result.source_checks.filter((source) => `${source.registry}:${source.issuer}` === key);
      const company = t(sources[0].company_name || sources[0].issuer);
      return <div key={key} className="golden-company-row" role="group" aria-label={company}><strong>{company}<small>{sources[0].registry.toUpperCase()}</small></strong><div className="golden-year-chips">{sources.map((source) => {
        const label = `${source.fiscal_year ? `FY${source.fiscal_year}` : source.golden_document_id}: ${t(source.state === "ready" ? "Ready" : source.state === "source_missing" ? "Originals required" : "Source verification required")}`;
        const content = <>{source.state === "ready" ? <Check size={12} aria-hidden="true" /> : <AlertCircle size={12} aria-hidden="true" />}<span>{source.fiscal_year ? `FY${source.fiscal_year}` : t("Source verification required")}</span></>;
        return source.state !== "ready" && onOpenSources ? <button type="button" key={source.golden_document_id} className={`golden-year-chip ${source.state}`} aria-label={label} onClick={onOpenSources}>{content}</button> : <span key={source.golden_document_id} className={`golden-year-chip ${source.state}`} aria-label={label}>{content}</span>;
      })}</div>{sources.filter((source) => source.state === "source_invalid" && source.detail).map((source) => <p className="helper" key={source.golden_document_id}>{source.detail}</p>)}</div>;
    })}</div>{(!result.source_checks.length || !["source_missing", "source_invalid"].includes(result.state)) && result.blockers.map((blocker) => <p className="helper" key={blocker}>{blocker}</p>)}</details>}

  </section>;
}

/** Select a bundled suite or an explicit user revision for the pipeline quick evaluation. */
export function PipelineGoldenPicker({ request, onSelect, onChecked, onOpenSources, onManage, action }: { action?: ReactNode; onManage?: () => void; onOpenSources?: () => void; onChecked?: (result: EvaluationPreparation | null) => void; request: EvaluationRequest; onSelect: (suite: SuiteId, revision: number | null) => void }) {
  const { t } = useI18n();
  const [suites, setSuites] = useState<GoldenSuite[]>([]);
  const [revisions, setRevisions] = useState<GoldenRevision[]>([]);
  const [error, setError] = useState("");
  useEffect(() => { let active = true; const refresh = () => { void getGoldenSuites().then(async rows => { const files = (await Promise.all(rows.map(suite => getGoldenRevisions(suite.suite_id)))).flat(); if (active) { setSuites(rows); setRevisions(files); } }).catch(reason => { if (active) setError(String(reason)); }); }; refresh(); window.addEventListener("docreview:golden-files-changed", refresh); return () => { active = false; window.removeEventListener("docreview:golden-files-changed", refresh); }; }, []);
  function selectFile(value: string) {
    const file = revisions.find(item => `file:${item.revision_id}` === value);
    onSelect(file?.suite_id ?? value as SuiteId, file?.revision_id ?? null);
  }
  const selected = suites.find(suite => suite.suite_id === request.suite_id);
  return <div className="pipeline-golden-picker"><div className="golden-picker-controls"><label>{t("Golden suite")}<select value={request.golden_revision_id ? `file:${request.golden_revision_id}` : request.suite_id} onChange={event => selectFile(event.target.value)}>{suites.map(suite => <option value={suite.suite_id} key={suite.suite_id}>{suite.filename} ({t("Built-in")})</option>)}{revisions.map(file => <option value={`file:${file.revision_id}`} key={file.revision_id}>{file.filename}</option>)}</select></label>{onManage && <button type="button" className="button golden-manage-button" onClick={onManage}>{t("Manage golden sets")}<ArrowUpRight size={14} aria-hidden="true" /></button>}{action}</div><p className="helper">{selected?.registry.toUpperCase()} · {selected?.question_language}{!request.golden_revision_id && <> · {t("Built-in")}</>}</p>{error && <p role="alert">{error}</p>}<GoldenPreparation request={request} onChecked={onChecked} onOpenSources={onOpenSources} /></div>;
}
