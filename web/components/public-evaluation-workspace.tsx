"use client";
import { NotificationOutlet, useNotifications } from "./notifications";
import { closeSidePanel } from "./side-panel-motion";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Beaker, Plus, Info, X } from "lucide-react";
import { useI18n } from "@/lib/i18n";
import { publishedDatasetLabel } from "@/lib/evaluation-labels";
import { presetError } from "@/lib/saved-presets";
import { browserStorage, subscribeStorageRestored } from "@/lib/storage";
import { snapshotDatasetIdentity } from "@/lib/comparison-example";
import { compareSnapshots, getPublicSnapshotDataset, getPublicSnapshotEvaluation } from "@/lib/api";
import { DEFAULT_PROFILE, type PublishedSnapshot, type PublicSnapshotDataset, type PublicSnapshotEvaluation, type RetrievalProfile, type SnapshotComparison } from "@/lib/types";
import { DevLockedButton } from "./dev-locked-button";
import { ProfileFields } from "./profile-fields";
import "./public-evaluation-workspace.css";
import { GoldenQuestionEditor } from "./golden-question-editor";
import { PublicGoldenDataset } from "./public-golden-dataset";
import { Metric } from "./metric";

const PAGE_SIZE = 25;
const EXPERIMENT_KEY = "docreview:public-evaluation-experiment:v1";
interface Experiment { mode: "quick" | "matrix"; targets: string; profile: RetrievalProfile; }
const DEFAULT_EXPERIMENT: Experiment = { mode: "quick", targets: "1024 2048", profile: DEFAULT_PROFILE };

/** Accept only bounded form state; saved experiments never become API execution requests. */
function loadExperiment(): Experiment {
  try {
    let saved: unknown = JSON.parse(browserStorage().getItem(EXPERIMENT_KEY) ?? "null");
    if (saved && typeof saved === "object" && "version" in saved && "value" in saved) {
      if (saved.version !== 1 || typeof saved.value !== "string") return DEFAULT_EXPERIMENT;
      saved = JSON.parse(saved.value);
    }
    if (!saved || typeof saved !== "object") return DEFAULT_EXPERIMENT;
    const row = saved as Experiment;
    if (!["quick", "matrix"].includes(row.mode) || typeof row.targets !== "string" || row.targets.length > 100 || !row.profile || !["vector", "lexical", "hybrid"].includes(row.profile.strategy)) return DEFAULT_EXPERIMENT;
    if (Object.keys(DEFAULT_PROFILE).some((key) => !(key in row.profile))) return DEFAULT_EXPERIMENT;
    if (Object.values(row.profile).some((value) => typeof value === "number" && !Number.isFinite(value))) return DEFAULT_EXPERIMENT;
    if (presetError({ id: "exploration", name: "Exploration", retrieval: row.profile })) return DEFAULT_EXPERIMENT;
    return row;
  } catch { return DEFAULT_EXPERIMENT; }
}

/** Shared public dataset/run browser using the same form and table classes as the operator view. */
export function PublicEvaluationWorkspace({ tab, snapshots, loading, error, onRefresh, onGoldenDetailChange, active = true }: {
  active?: boolean;
  onGoldenDetailChange?: (open: boolean) => void;
  tab: "golden" | "runs" | "compare"; snapshots: PublishedSnapshot[]; loading: boolean; error: boolean; onRefresh: () => void;
}) {
  const { t, locale } = useI18n();
  const [chosen, setChosen] = useState<number | null>(null);
  const snapshotId = chosen ?? snapshots[0]?.snapshot_id ?? null;
  const selected = snapshots.find((row) => row.snapshot_id === snapshotId);
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState("id");
  const [offset, setOffset] = useState(0);
  const [revision, setRevision] = useState(0);
  const [dataset, setDataset] = useState<PublicSnapshotDataset | null>(null);
  const [evaluation, setEvaluation] = useState<PublicSnapshotEvaluation | null>(null);
  const [busy, setBusy] = useState(false);
  const [detailError, setDetailError] = useState(false);
  const [openCase, setOpenCase] = useState<string | null>(null);
  const [setupOpen, setSetupOpen] = useState(false);
  const [experiment, setExperiment] = useState(loadExperiment);
  const { notify } = useNotifications();
  const setupRef = useRef<HTMLElement>(null);
  useEffect(() => {
    if (!active || tab !== "runs" || !setupOpen) return;
    const previousFocus = document.activeElement as HTMLElement | null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    setupRef.current?.querySelector<HTMLElement>("button")?.focus();
    /** Keep keyboard navigation inside the active settings drawer. */
    function trapFocus(event: KeyboardEvent) {
      if (event.key !== "Tab") return;
      const controls = Array.from(setupRef.current?.querySelectorAll<HTMLElement>("button:not(:disabled), input:not(:disabled), select:not(:disabled), summary, a[href]") ?? []).filter(element => !element.closest("details:not([open])") || element.tagName === "SUMMARY");
      const first = controls[0]; const last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    }
    document.addEventListener("keydown", trapFocus);
    return () => { document.removeEventListener("keydown", trapFocus); document.body.style.overflow = previousOverflow; previousFocus?.focus(); };
  }, [active, tab, setupOpen]);
  useEffect(() => subscribeStorageRestored(() => { setExperiment(loadExperiment()); }), []);
  useEffect(() => {
    if (tab === "compare" || snapshotId === null || !selected) return;
    let current = true;
    setBusy(true); setDetailError(false); if (tab !== "golden" || offset === 0) setDataset(null); if (offset === 0) setEvaluation(null); setOpenCase(null);
    const timer = setTimeout(() => {
      const params = new URLSearchParams({ offset: String(offset), limit: String(PAGE_SIZE), query, sort });
      const work = tab === "golden" ? getPublicSnapshotDataset(snapshotId, params) : getPublicSnapshotEvaluation(snapshotId, params);
      void work.then((page) => {
        if (!current) return;
        if ("golden_sha256" in page) setDataset(previous => offset === 0 || !previous ? page : {
          ...page, cases: [...new Map([...previous.cases, ...page.cases].map(row => [row.id, row])).values()],
        }); else setEvaluation(previous => offset === 0 || !previous ? page : { ...page, cases: [...new Map([...previous.cases, ...page.cases].map(row => [row.case_id, row])).values()] });
      }).catch(() => { if (current) setDetailError(true); }).finally(() => { if (current) setBusy(false); });
    }, 200);
    return () => { current = false; clearTimeout(timer); };
  }, [tab, snapshotId, Boolean(selected), query, sort, offset, revision]);
  if (tab === "compare") return <PublicComparison snapshots={snapshots} />;
  if (tab === "golden") return <PublicGoldenDataset onDetailChange={onGoldenDetailChange} snapshots={snapshots} selected={selected} dataset={dataset} loading={loading} error={error} busy={busy} detailError={detailError} query={query} sort={sort} offset={offset} pageSize={PAGE_SIZE} onSelect={id => { setChosen(id); setOffset(0); }} onQuery={value => { setQuery(value); setOffset(0); }} onSort={value => { setSort(value); setOffset(0); }} onPage={setOffset} onRefresh={onRefresh} onRetry={() => setRevision(value => value + 1)} />;
  const experimentError = presetError({ id: "exploration", name: "Exploration", retrieval: experiment.profile }) || (experiment.mode === "matrix" && (!experiment.targets.trim() || experiment.targets.trim().split(/\s+/).some((value) => !Number.isInteger(Number(value)) || Number(value) <= 0)) ? "Enter positive integer chunk sizes." : null);
  const provenance = selected?.eval_result.config.golden_provenance as { filename?: string; kind?: string; verification_status?: string } | undefined;
  const total = evaluation?.total ?? 0;
  const record = evaluation;
  return <div className={tab === "runs" ? "panel-stack run-workspace evaluation-runs" : "panel-stack evaluation-golden"}>
    <section className="surface evaluation-run-overview">
      <div className="surface-heading"><div><h2>{t("Evaluation runs")}</h2><p className="helper">{t("Explore published records. Reading and filtering do not run an evaluation.")}</p></div>{tab === "runs" && <button type="button" className="button primary" aria-expanded={setupOpen} onClick={() => setSetupOpen((open) => !open)}><Plus size={15} />{t("Explore evaluation settings")}</button>}</div>
      {loading ? <p role="status">{t("Loading published snapshots…")}</p> : error ? <p role="alert">{t("Published snapshots could not be loaded.")} <button className="button" onClick={onRefresh}>{t("Retry")}</button></p> : !snapshots.length ? <p role="status">{t("No published evaluations yet. Settings exploration is still available.")}</p> : <div className="evaluation-list-tools">
        <label>{t("Evaluation dataset")}<select value={snapshotId ?? ""} onChange={(event) => { setChosen(Number(event.target.value)); setOffset(0); }}>
          {snapshots.map((row) => <option key={row.snapshot_id} value={row.snapshot_id}>{publishedDatasetLabel(row, locale)}</option>)}
        </select></label>
        <label>{t("Search")}<input value={query} onChange={(event) => { setQuery(event.target.value); setOffset(0); }} placeholder={t("Search ID or question")} /></label>
        <label>{t("Sort by")}<select value={sort} onChange={(event) => { setSort(event.target.value); setOffset(0); }}><option value="id">{t("ID")}</option><option value="question">{t("Question")}</option></select></label>
      </div>}

    {active && setupOpen && tab === "runs" && createPortal(<div className="evaluation-setup-backdrop" onClick={event => { if (event.target === event.currentTarget) closeSidePanel(setupRef.current, () => setSetupOpen(false)); }}><section ref={setupRef} className="surface evaluation-setup evaluation-setup-experiment" role="dialog" aria-modal="true" aria-label={t("Explore evaluation settings")} onKeyDown={event => { if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); closeSidePanel(setupRef.current, () => setSetupOpen(false)); } }}>
      <div className="surface-heading"><div><p className="eyebrow">{t("Evaluation setup")}</p><h2>{t("Explore evaluation settings")}</h2></div><button type="button" className="button icon" aria-label={t("Close evaluation settings")} onClick={() => closeSidePanel(setupRef.current, () => setSetupOpen(false))}><X size={18} aria-hidden="true" /></button></div>
      <div className="form-stack evaluation-setup-body"><NotificationOutlet priority={50} placement="overlay" />
      <p className="evaluation-experiment-note" role="note"><Info size={16} aria-hidden="true" /><span>{t("Settings exploration only. These changes do not execute on the server or change recorded results.")}</span></p>
      <label>{t("Evaluation dataset")}<select value={snapshotId ?? ""} disabled={!snapshots.length} onChange={(event) => { setChosen(Number(event.target.value)); setOffset(0); }}>{!snapshots.length && <option value="">{t("No published dataset")}</option>}{snapshots.map((row) => <option key={row.snapshot_id} value={row.snapshot_id}>{publishedDatasetLabel(row, locale)}</option>)}</select></label>
      {selected && <section className="golden-preparation" aria-label={t("Golden set readiness")}><div className="golden-status-fields"><span>{t("Type")}: <strong>{t(provenance?.kind === "builtin" ? "Built-in golden set" : "Published")}</strong></span><span>{t("Source")}: <strong>{selected.eval_result.suite.startsWith("dart") ? "DART" : "SEC"}</strong></span><span>{t("Verification")}: <strong>{t(provenance?.verification_status === "verified" ? "Verified" : "Pending review")}</strong></span><span>{t("Run readiness")}: <strong>{t("DEV only")}</strong></span></div><p className="helper">{t("Published questions and expected evidence are read-only. Evaluation runs in DEV mode.")}</p></section>}
      <dl className="evaluation-metadata"><div><dt>{t("Index")}</dt><dd>{t(experiment.mode === "quick" ? "Current index" : "Isolated corpus")}</dd></div><div><dt>{t("Run readiness")}</dt><dd>{t("DEV only")}</dd></div><div><dt>{t("Cases")}</dt><dd>{selected?.eval_result.metrics.query_count ?? "—"}</dd></div><div><dt>{t("Golden revision")}</dt><dd>{provenance?.filename ?? "—"}</dd></div></dl>
      <fieldset className="playground-core"><legend>{t("Core search settings")}</legend><ProfileFields fields="core" profile={experiment.profile} onChange={profile => { setExperiment({ ...experiment, profile }); }} /></fieldset>
      <details><summary>{t("Advanced evaluation options")}</summary>
      <label>{t("Evaluation mode")}<select value={experiment.mode} onChange={(event) => { setExperiment({ ...experiment, mode: event.target.value as Experiment["mode"] }); }}><option value="quick">{t("Quick · current index")}</option><option value="matrix">{t("Matrix · isolated corpus")}</option></select></label>
      {experiment.mode === "matrix" && <label>{t("Chunk targets (tokens)")}<input value={experiment.targets} maxLength={100} onChange={(event) => { setExperiment({ ...experiment, targets: event.target.value }); }} /></label>}
      <ProfileFields fields="advanced" profile={experiment.profile} onChange={(profile) => { setExperiment({ ...experiment, profile }); }} />
      </details>
      <p className="helper">{t("Retrieval profile ·")} {t(experiment.profile.strategy)} · {experiment.profile.lexical_ranker} · k {experiment.profile.k}{experiment.profile.reranker ? ` · ${t(experiment.profile.reranker.replaceAll("_", " "))}` : ""}</p>
      {experimentError && <p role="alert">{t(experimentError)}</p>}<details><summary>{t("Request preview · not submitted")}</summary><pre>{JSON.stringify({ suite_id: selected?.eval_result.suite ?? null, mode: experiment.mode, target_tokens: experiment.mode === "matrix" ? experiment.targets.trim().split(/\s+/).filter(Boolean).map(Number) : [], profile: experiment.profile }, null, 2)}</pre></details>
      <section className="evaluation-inline-defaults"><div className="action-row"><button className="button" disabled={Boolean(experimentError)} onClick={() => { browserStorage().setItem(EXPERIMENT_KEY, JSON.stringify(experiment)); notify(t("Exploration saved in this browser. No evaluation was run."), "success", "evaluation-exploration-saved", undefined, { event: "evaluation-exploration-saved" }); }}>{t("Save exploration in this browser")}</button><button className="button ghost" onClick={() => { setExperiment(DEFAULT_EXPERIMENT); browserStorage().setItem(EXPERIMENT_KEY, JSON.stringify(DEFAULT_EXPERIMENT)); }}>{t("Reset exploration settings")}</button></div></section>

      </div><div className="action-row evaluation-setup-footer"><button className="button" onClick={() => closeSidePanel(setupRef.current, () => setSetupOpen(false))}>{t("Cancel")}</button><DevLockedButton reason="evaluation" className="button primary">{t("Queue evaluation")}</DevLockedButton></div>
    </section></div>, document.body)}
    {selected && <section className="public-evaluation-result">
      <div className="surface-heading"><div><h2>{selected.label}</h2><p className="helper">{selected.suite_title ?? selected.eval_result.suite} · {new Date(selected.eval_result.created_at).toLocaleString(locale)}</p></div></div>
      {busy && !record ? <p role="status">{t("Loading recorded evidence…")}</p> : detailError ? <div role="alert"><p>{t("This published record could not be verified or loaded. The current editable dataset is not used as a replacement.")}</p><button className="button" onClick={() => setRevision((value) => value + 1)}>{t("Retry")}</button></div> : record && <>
        {dataset && <p className="helper">{t("Dataset version")}: {dataset.version ?? "—"} · SHA-256 <code>{dataset.golden_sha256}</code></p>}
        {evaluation && <>
          <p className="public-evaluation-purpose">{t("Can retrieval find the evidence? This recorded run checks ranked search results against a fixed set of questions and expected sources.")}</p>
          <p className="helper">{t("Retrieval profile ·")} {t(String(evaluation.config.strategy ?? "—"))} · {String(evaluation.config.lexical_ranker ?? "—")} · k {String(evaluation.config.k ?? "—")}</p>
          <div className="public-evaluation-metrics">{([
            ["hit_rate_at_k", "Evidence hit rate", "Questions with a relevant source in the top-k results.", "percent"],
            ["mrr", "Ranking quality · MRR", "Rewards relevant evidence appearing earlier. Higher is better; maximum 1.", "score"],
            ["mean_latency_ms", "Mean search time", "Recorded retrieval latency per question, not answer generation time.", "time"],
            ["query_count", "Evaluated questions", "Size of the recorded evaluation, independent of the current filter.", "count"],
          ] as const).map(([key, label, description, format]) => {
            const value = evaluation.metrics[key];
            const display = typeof value !== "number" || !Number.isFinite(value) ? "—" : format === "percent" ? value.toLocaleString(locale, { style: "percent", maximumFractionDigits: 1 }) : `${value.toLocaleString(locale, { maximumFractionDigits: format === "score" ? 3 : format === "time" ? 0 : 0 })}${format === "time" ? " ms" : ""}`;
            return <div key={key}><Metric icon={<Beaker />} label={t(label)} value={display} /><p className="helper">{t(description)}</p></div>;
          })}</div>
          <p className="helper">{t("Measured on this dataset and recorded search configuration. Retrieval scores do not measure final-answer accuracy.")}</p>
          <details className="public-evaluation-technical"><summary>{t("Recorded configuration")}</summary><dl className="evaluation-metadata">{Object.entries(evaluation.config).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{typeof value === "object" && value !== null ? JSON.stringify(value) : String(value ?? "—")}</dd></div>)}</dl><div className="metric-grid compact">{Object.entries(evaluation.metrics).map(([name, value]) => <Metric key={name} icon={<Beaker />} label={name} value={value.toLocaleString(locale, { maximumFractionDigits: 3 })} />)}</div></details>
        </>}
        <h3>{t("Inspect question-level results")}</h3><p className="helper">{t("Select a question ID to inspect its recorded rank and scores. A dash means no relevant source was found in the returned results.")}</p>
        <div className="golden-table-tools"><span>{t("Questions")}: {total}</span></div>
        <div className="golden-table-scroll" onScroll={event => { const list = event.currentTarget; if (!busy && !detailError && offset + PAGE_SIZE < total && list.scrollTop + list.clientHeight >= list.scrollHeight - 64) setOffset(offset + PAGE_SIZE); }}><table><thead><tr><th>{t("ID")}</th><th>{t("Question")}</th><th>{t("First rank")}</th></tr></thead><tbody>
          {dataset?.cases.map((row) => <tr key={row.id} className={openCase === row.id ? "selected" : ""}><td><button className="row-detail" onClick={() => setOpenCase(openCase === row.id ? null : row.id)}>{row.id}</button></td><td>{row.question}{openCase === row.id && <div className="golden-source-detail"><p>{row.reference_answer}</p><p>{row.expected_label} · {row.category} · {row.facet}</p>{row.answers.map((answer, index) => <div key={index} className="golden-source-span"><code>{JSON.stringify(answer)}</code></div>)}</div>}</td><td>{row.answers.length}</td></tr>)}
          {evaluation?.cases.map((row) => <tr key={row.case_id} className={openCase === row.case_id ? "selected" : ""}><td><button className="row-detail" onClick={() => setOpenCase(openCase === row.case_id ? null : row.case_id)}>{row.case_id}</button></td><td>{row.question}{openCase === row.case_id && <dl className="evaluation-metadata"><div><dt>{t("Latency (ms)")}</dt><dd>{row.latency_ms}</dd></div><div><dt>Recall@k</dt><dd>{row.recall_at_k ?? "—"}</dd></div><div><dt>Hit@k</dt><dd>{row.hit_at_k ?? "—"}</dd></div><div><dt>RR</dt><dd>{row.reciprocal_rank ?? "—"}</dd></div></dl>}</td><td>{row.first_relevant_rank ?? "—"}</td></tr>)}
        </tbody></table></div>
        {!total && <p>{t("No questions match this filter.")}</p>}
        {busy && record && <p className="helper" role="status">{t("Loading recorded evidence…")}</p>}
      </>}
    </section>}
    </section>
  </div>;
}

/** Show two published, measured runs without executing retrieval from the public UI. */
function PublicComparison({ snapshots }: { snapshots: PublishedSnapshot[] }) {
  const { t, locale } = useI18n();
  const [comparison, setComparison] = useState<SnapshotComparison | null>(null);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const baseline = snapshots.find(row => row.label === "DART Korean comparison example — baseline — bm25 k5");
  const candidate = snapshots.find(row => row.label === "DART Korean comparison example — candidate — ts_rank_cd k5");
  const compatible = Boolean(baseline && candidate && baseline.eval_result.suite === candidate.eval_result.suite && snapshotDatasetIdentity(baseline) && snapshotDatasetIdentity(baseline) === snapshotDatasetIdentity(candidate) && baseline.corpus_fingerprint === candidate.corpus_fingerprint);
  /** Fetch only the registered pair's stored measurements. */
  async function openExample() {
    if (!compatible || !baseline || !candidate || busy || comparison) return;
    setBusy(true); setFailed(false);
    try {
      const result = await compareSnapshots(baseline.snapshot_id, candidate.snapshot_id, false);
      if (!result.directly_comparable) throw new Error("Registered datasets do not match");
      setComparison(result);
    } catch { setFailed(true); }
    finally { setBusy(false); }
  }
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState("id");
  const [selectedCase, setSelectedCase] = useState<string | null>(null);
  const [caseDetail, setCaseDetail] = useState<PublicSnapshotDataset["cases"][number] | null>(null);
  const [caseError, setCaseError] = useState(false);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    if (!selectedCase || !baseline) return;
    let current = true;
    setCaseDetail(null); setCaseError(false);
    void getPublicSnapshotDataset(baseline.snapshot_id, new URLSearchParams({ query: selectedCase, limit: "25", offset: "0", sort: "id" })).then(page => {
      const exact = page.cases.find(row => row.id === selectedCase);
      if (!exact) throw new Error("Published question is missing");
      if (current) setCaseDetail(exact);
    }).catch(() => { if (current) setCaseError(true); });
    return () => { current = false; };
  }, [selectedCase, baseline?.snapshot_id, retry]);
  const cases = (comparison?.cases ?? []).filter(row => `${row.case_id} ${t(row.candidate_question)}`.toLowerCase().includes(query.toLowerCase())).sort((a, b) => (sort === "question" ? a.candidate_question.localeCompare(b.candidate_question, locale) : a.case_id.localeCompare(b.case_id, locale)));
  if (selectedCase) return caseDetail ? <GoldenQuestionEditor filename="dart_retrieval_ko.json" registry="dart" json={JSON.stringify(caseDetail)} readOnly dirty={false} busy={false} error="" issues={[]} onChange={() => {}} onSave={() => {}} onBack={() => setSelectedCase(null)} /> : <section className="surface"><button className="button ghost" onClick={() => setSelectedCase(null)}>{t("Question list")}</button>{caseError ? <p role="alert">{t("This published record could not be verified or loaded. The current editable dataset is not used as a replacement.")} <button className="button" onClick={() => setRetry(value => value + 1)}>{t("Retry")}</button></p> : <p role="status">{t("Loading recorded evidence…")}</p>}</section>;
  return <div className="panel-stack">
    <section className="surface evaluation-comparison-setup public-comparison-example">
      <div className="evaluation-compare-filters">
        <label>{t("Evaluation dataset")}<select disabled value="dart-ko"><option value="dart-ko">DART retrieval · Korean · dart_retrieval_ko.json ({t("Recorded results")})</option></select></label>
        <label>{t("Sort by")}<select disabled value="newest"><option value="newest">{t("Newest first")}</option></select></label>
      </div>
      <div className="comparison-picker">
        <label>{t("Baseline")}<select disabled value="baseline"><option value="baseline">BM25 · k 5</option></select></label>
        <label>{t("Candidate")}<select disabled value="candidate"><option value="candidate">ts_rank_cd · k 5</option></select></label>
        <button className="button primary" aria-expanded={Boolean(comparison)} disabled={!compatible || busy} onClick={() => void openExample()}>{t("Explore an example")}</button>
      </div>
      <p className="helper">{t("The gray fields are fixed example selections. Explore the example without running an evaluation or model.")}</p>
    </section>
    {!compatible && <p className="helper" role="status">{t("The recorded comparison pair is not available yet.")}</p>}
    {failed && <p role="alert">{t("Comparison could not be loaded.")} <button className="button" onClick={() => void openExample()}>{t("Retry")}</button></p>}
    <details className="surface"><summary>{t("See an example")}</summary><p>{t("Two real runs on the same DART Korean dataset and corpus: BM25 versus ts_rank_cd, both with k=5. The button reads saved results; it does not run another evaluation.")}</p></details>
    {comparison && <section className="surface"><h3>{t("Recorded results")}</h3><p className="helper">{baseline?.label} → {candidate?.label}</p>
      <div className="golden-table-scroll"><table className="evaluation-comparison-table"><thead><tr>{["Metric", "Baseline", "Candidate", "Change"].map(label => <th key={label}>{t(label)}</th>)}</tr></thead><tbody>{comparison.metrics.map(row => <tr key={row.name}><td>{row.name}</td><td>{row.baseline.toLocaleString(locale, { maximumFractionDigits: 3 })}</td><td>{row.candidate.toLocaleString(locale, { maximumFractionDigits: 3 })}</td><td>{row.delta == null ? "—" : row.delta.toLocaleString(locale, { maximumFractionDigits: 3, signDisplay: "always" })}</td></tr>)}</tbody></table></div>
      <h3>{t("Question-level comparison")}</h3>
      <div className="golden-table-tools"><input aria-label={t("Search ID or question")} placeholder={t("Search ID or question")} value={query} onChange={event => setQuery(event.target.value)} /><select aria-label={t("Sort questions")} value={sort} onChange={event => setSort(event.target.value)}><option value="id">{t("ID")}</option><option value="question">{t("Question")}</option></select></div>
      <p className="helper">{t("Ranks show where the first relevant source appeared in the top 5 results. Lower is better; — means not found. Select an ID to inspect the reference answer and expected sources.")}</p>
      <div className="golden-table-scroll"><table className="public-case-comparison"><thead><tr><th>{t("ID")}</th><th>{t("Question")}</th><th>{t("Baseline rank")}<br />BM25</th><th>{t("Candidate rank")}<br />ts_rank_cd</th><th>{t("Change")}</th></tr></thead><tbody>{cases.map(row => {
        const outcome = row.baseline_rank === row.candidate_rank ? "Unchanged" : row.candidate_rank != null && (row.baseline_rank == null || row.candidate_rank < row.baseline_rank) ? "Improved" : "Regressed";
        return <tr key={row.case_id}><td><button className="row-detail" onClick={() => setSelectedCase(row.case_id)}>{row.case_id}</button></td><td>{row.candidate_question}</td><td>{row.baseline_rank ?? "—"}</td><td>{row.candidate_rank ?? "—"}</td><td>{t(outcome)}</td></tr>;
      })}</tbody></table></div>
      {!cases.length && <p>{t("No case-level changes were recorded for this comparison.")}</p>}
    </section>}
  </div>;
}
