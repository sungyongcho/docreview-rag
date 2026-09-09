"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Beaker, Plus } from "lucide-react";
import { useI18n } from "@/lib/i18n";
import { presetError } from "@/lib/saved-presets";
import { browserStorage, subscribeStorageRestored } from "@/lib/storage";
import { COMPARISON_EXAMPLE, snapshotDatasetIdentity } from "@/lib/comparison-example";
import { compareSnapshots, getPublicSnapshotDataset, getPublicSnapshotEvaluation } from "@/lib/api";
import { DEFAULT_PROFILE, type PublishedSnapshot, type PublicSnapshotDataset, type PublicSnapshotEvaluation, type RetrievalProfile, type SnapshotComparison } from "@/lib/types";
import { DevLockedButton } from "./dev-locked-button";
import { ProfileFields } from "./profile-fields";
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
export function PublicEvaluationWorkspace({ tab, snapshots, loading, error, onRefresh }: {
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
  const [saved, setSaved] = useState(false);
  useEffect(() => subscribeStorageRestored(() => { setExperiment(loadExperiment()); setSaved(false); }), []);
  useEffect(() => {
    if (tab === "compare" || snapshotId === null || !selected) return;
    let current = true;
    setBusy(true); setDetailError(false); setDataset(null); setEvaluation(null); setOpenCase(null);
    const timer = setTimeout(() => {
      const params = new URLSearchParams({ offset: String(offset), limit: String(PAGE_SIZE), query, sort });
      const work = tab === "golden" ? getPublicSnapshotDataset(snapshotId, params) : getPublicSnapshotEvaluation(snapshotId, params);
      void work.then((page) => {
        if (!current) return;
        if ("golden_sha256" in page) setDataset(page); else setEvaluation(page);
      }).catch(() => { if (current) setDetailError(true); }).finally(() => { if (current) setBusy(false); });
    }, 200);
    return () => { current = false; clearTimeout(timer); };
  }, [tab, snapshotId, Boolean(selected), query, sort, offset, revision]);
  if (tab === "compare") return <PublicComparison snapshots={snapshots} loading={loading} error={error} onRefresh={onRefresh} />;
  const experimentError = presetError({ id: "exploration", name: "Exploration", retrieval: experiment.profile }) || (experiment.mode === "matrix" && (!experiment.targets.trim() || experiment.targets.trim().split(/\s+/).some((value) => !Number.isInteger(Number(value)) || Number(value) <= 0)) ? "Enter positive integer chunk sizes." : null);
  const total = (tab === "golden" ? dataset?.total : evaluation?.total) ?? 0;
  const record = tab === "golden" ? dataset : evaluation;
  return <div className={tab === "runs" ? "panel-stack run-workspace evaluation-runs" : "panel-stack evaluation-golden"}>
    <section className="surface evaluation-run-overview">
      <div className="surface-heading"><div><h2>{t(tab === "golden" ? "Golden questions" : "Evaluation runs")}</h2><p className="helper">{t("Explore published records. Reading and filtering do not run an evaluation.")}</p></div>{tab === "runs" && <button type="button" className="button primary" aria-expanded={setupOpen} onClick={() => setSetupOpen((open) => !open)}><Plus size={15} />{t("Explore evaluation settings")}</button>}</div>
      {loading ? <p role="status">{t("Loading published snapshots…")}</p> : error ? <p role="alert">{t("Published snapshots could not be loaded.")} <button className="button" onClick={onRefresh}>{t("Retry")}</button></p> : !snapshots.length ? <p role="status">{t("No published evaluations yet. Settings exploration is still available.")}</p> : <div className="evaluation-list-tools">
        <label>{t("Evaluation dataset")}<select value={snapshotId ?? ""} onChange={(event) => { setChosen(Number(event.target.value)); setOffset(0); }}>
          {snapshots.map((row) => <option key={row.snapshot_id} value={row.snapshot_id}>{row.suite_title ?? row.eval_result.suite} · {row.label} · #{row.eval_result.result_id}</option>)}
        </select></label>
        <label>{t("Search")}<input value={query} onChange={(event) => { setQuery(event.target.value); setOffset(0); }} placeholder={t("Search ID or question")} /></label>
        <label>{t("Sort by")}<select value={sort} onChange={(event) => { setSort(event.target.value); setOffset(0); }}><option value="id">{t("ID")}</option><option value="question">{t("Question")}</option></select></label>
      </div>}
      {tab === "golden" && <div className="action-row"><DevLockedButton reason="golden">{t("Create draft")}</DevLockedButton><DevLockedButton reason="evaluation">{t("Evaluate this dataset")}</DevLockedButton></div>}
    </section>
    {setupOpen && tab === "runs" && <section className="surface form-stack evaluation-setup-experiment">
      <div className="surface-heading"><h2>{t("Explore evaluation settings")}</h2><button className="button ghost" onClick={() => setSetupOpen(false)}>{t("Close")}</button></div>
      <p className="notice" role="note">{t("Settings exploration only. These changes do not execute on the server or change recorded results.")}</p>
      <label>{t("Evaluation dataset")}<select value={snapshotId ?? ""} disabled={!snapshots.length} onChange={(event) => { setChosen(Number(event.target.value)); setOffset(0); }}>{!snapshots.length && <option value="">{t("No published dataset")}</option>}{snapshots.map((row) => <option key={row.snapshot_id} value={row.snapshot_id}>{row.suite_title ?? row.eval_result.suite} · {row.label}</option>)}</select></label>
      <label>{t("Evaluation mode")}<select value={experiment.mode} onChange={(event) => { setExperiment({ ...experiment, mode: event.target.value as Experiment["mode"] }); setSaved(false); }}><option value="quick">{t("Quick · current index")}</option><option value="matrix">{t("Matrix · isolated corpus")}</option></select></label>
      {experiment.mode === "matrix" && <label>{t("Chunk targets (tokens)")}<input value={experiment.targets} maxLength={100} onChange={(event) => { setExperiment({ ...experiment, targets: event.target.value }); setSaved(false); }} /></label>}
      <ProfileFields profile={experiment.profile} onChange={(profile) => { setExperiment({ ...experiment, profile }); setSaved(false); }} />
      {experimentError && <p role="alert">{t(experimentError)}</p>}<details><summary>{t("Request preview · not submitted")}</summary><pre>{JSON.stringify({ suite_id: selected?.eval_result.suite ?? null, mode: experiment.mode, target_tokens: experiment.mode === "matrix" ? experiment.targets.trim().split(/\s+/).filter(Boolean).map(Number) : [], profile: experiment.profile }, null, 2)}</pre></details>
      <div className="action-row"><button className="button" disabled={Boolean(experimentError)} onClick={() => { browserStorage().setItem(EXPERIMENT_KEY, JSON.stringify(experiment)); setSaved(true); }}>{t("Save exploration in this browser")}</button><DevLockedButton reason="evaluation" className="button primary">{t("Queue evaluation")}</DevLockedButton><DevLockedButton reason="snapshot">{t("Save result as snapshot")}</DevLockedButton></div>
      {saved && <p role="status">{t("Exploration saved in this browser. No evaluation was run.")}</p>}
    </section>}
    {selected && <section className="surface">
      <div className="surface-heading"><div><h2>{selected.label}</h2><p className="helper">{selected.suite_title ?? selected.eval_result.suite} · {new Date(selected.eval_result.created_at).toLocaleString(locale)}</p></div></div>
      {busy ? <p role="status">{t("Loading recorded evidence…")}</p> : detailError ? <div role="alert"><p>{t("This published record could not be verified or loaded. The current editable dataset is not used as a replacement.")}</p><button className="button" onClick={() => setRevision((value) => value + 1)}>{t("Retry")}</button></div> : record && <>
        {dataset && <p className="helper">{t("Dataset version")}: {dataset.version ?? "—"} · SHA-256 <code>{dataset.golden_sha256}</code></p>}
        {evaluation && <><h3>{t("Recorded configuration")}</h3><dl className="evaluation-metadata">{Object.entries(evaluation.config).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{String(value ?? "—")}</dd></div>)}</dl><div className="metric-grid compact">{Object.entries(evaluation.metrics).map(([name, value]) => <Metric key={name} icon={<Beaker />} label={name} value={value.toLocaleString(locale, { maximumFractionDigits: 3 })} />)}</div></>}
        <div className="golden-table-tools"><span>{t("Questions")}: {total}</span></div>
        <div className="golden-table-scroll"><table><thead><tr><th>{t("ID")}</th><th>{t("Question")}</th><th>{t(tab === "golden" ? "Expected evidence" : "First rank")}</th></tr></thead><tbody>
          {dataset?.cases.map((row) => <tr key={row.id} className={openCase === row.id ? "selected" : ""}><td><button className="row-detail" onClick={() => setOpenCase(openCase === row.id ? null : row.id)}>{row.id}</button></td><td>{row.question}{openCase === row.id && <div className="golden-source-detail"><p>{row.reference_answer}</p><p>{row.expected_label} · {row.category} · {row.facet}</p>{row.answers.map((answer, index) => <div key={index} className="golden-source-span"><code>{JSON.stringify(answer)}</code></div>)}</div>}</td><td>{row.answers.length}</td></tr>)}
          {evaluation?.cases.map((row) => <tr key={row.case_id} className={openCase === row.case_id ? "selected" : ""}><td><button className="row-detail" onClick={() => setOpenCase(openCase === row.case_id ? null : row.case_id)}>{row.case_id}</button></td><td>{row.question}{openCase === row.case_id && <dl className="evaluation-metadata"><div><dt>{t("Latency (ms)")}</dt><dd>{row.latency_ms}</dd></div><div><dt>Recall@k</dt><dd>{row.recall_at_k ?? "—"}</dd></div><div><dt>Hit@k</dt><dd>{row.hit_at_k ?? "—"}</dd></div><div><dt>RR</dt><dd>{row.reciprocal_rank ?? "—"}</dd></div></dl>}</td><td>{row.first_relevant_rank ?? "—"}</td></tr>)}
        </tbody></table></div>
        {!total && <p>{t("No questions match this filter.")}</p>}
        <div className="action-row"><button className="button" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>{t("Previous")}</button><span>{total ? offset + 1 : 0}–{Math.min(offset + PAGE_SIZE, total)} / {total}</span><button className="button" disabled={offset + PAGE_SIZE >= total} onClick={() => setOffset(offset + PAGE_SIZE)}>{t("Next")}</button></div>
      </>}
    </section>}
  </div>;
}

/** Compare stored measurements on demand; example mode never reaches an API. */
function PublicComparison({ snapshots, loading, error, onRefresh }: { snapshots: PublishedSnapshot[]; loading: boolean; error: boolean; onRefresh: () => void }) {
  const { t, locale } = useI18n();
  const [example, setExample] = useState(false);
  const [suite, setSuite] = useState("");
  const available = snapshots.filter((row) => !suite || row.eval_result.suite === suite);
  const [baseline, setBaseline] = useState(""); const [candidate, setCandidate] = useState("");
  const [comparison, setComparison] = useState<SnapshotComparison | null>(null);
  const [busy, setBusy] = useState(false); const [failed, setFailed] = useState(false);
  const [query, setQuery] = useState(""); const [page, setPage] = useState(0);
  const cache = useRef(new Map<string, SnapshotComparison>());
  const request = useRef(0);
  useEffect(() => () => { request.current += 1; }, []);
  function reset() { request.current += 1; setComparison(null); setFailed(false); setBusy(false); setPage(0); }
  const before = snapshots.find((row) => String(row.snapshot_id) === baseline);
  const after = snapshots.find((row) => String(row.snapshot_id) === candidate);
  const mismatch = before && after && (before.eval_result.suite !== after.eval_result.suite || before.golden_revision_id !== after.golden_revision_id || !snapshotDatasetIdentity(before) || snapshotDatasetIdentity(before) !== snapshotDatasetIdentity(after));
  async function compare() {
    if (loading || error || !before || !after || baseline === candidate || mismatch) return;
    const key = `${baseline}:${candidate}:${before.corpus_fingerprint}:${after.corpus_fingerprint}`;
    const cached = cache.current.get(key); if (cached) { setComparison(cached); return; }
    const generation = ++request.current; setBusy(true); setFailed(false);
    try { const result = await compareSnapshots(Number(baseline), Number(candidate), false); if (generation === request.current) { cache.current.set(key, result); setComparison(result); } }
    catch { if (generation === request.current) setFailed(true); }
    finally { if (generation === request.current) setBusy(false); }
  }
  const exampleMetrics = useMemo(() => COMPARISON_EXAMPLE.metrics.map((row) => baseline === "candidate" ? { ...row, baseline: row.candidate, candidate: row.baseline, delta: row.delta === null ? null : -row.delta } : row), [baseline]);
  const metrics = example ? exampleMetrics : comparison?.metrics ?? [];
  const exampleCases = COMPARISON_EXAMPLE.cases.map((row) => baseline === "candidate" ? { ...row, baseline_rank: row.candidate_rank, candidate_rank: row.baseline_rank, rank_delta: row.rank_delta === null ? null : -row.rank_delta, transition: row.transition === "miss_to_hit" ? "hit_to_miss" as const : row.transition } : row);
  const cases = (example ? exampleCases : comparison?.cases ?? []).filter((row) => `${row.case_id} ${row.baseline_question} ${row.candidate_question}`.toLowerCase().includes(query.toLowerCase()));
  return <div className="panel-stack">
    <section className="surface evaluation-comparison-setup">
      <div className="surface-heading"><h2>{t("Compare stored results")}</h2><button className="button" aria-pressed={example} onClick={() => { reset(); setExample(!example); setBaseline(""); setCandidate(""); }}>{t(example ? "Return to published results" : "Explore an example")}</button></div>
      <p className="helper">{t(example ? "Illustrative example only — not an evaluation result." : "Stored artifacts only. Comparing snapshots does not run an evaluation or provider request.")}</p>
      {example ? <div className="comparison-picker"><label>{t("Baseline")}<select value={baseline || "baseline"} onChange={(event) => setBaseline(event.target.value)}><option value="baseline">{t("Example baseline")}</option><option value="candidate">{t("Example candidate")}</option></select></label><p>{t("Switch the baseline to inspect the same stored example in the opposite direction.")}</p></div> : <>
        {loading && <p role="status">{t("Loading published snapshots…")}</p>}{error && <p role="alert">{t("Published snapshots could not be loaded.")} <button className="button" onClick={onRefresh}>{t("Retry")}</button></p>}
        <label>{t("Evaluation dataset")}<select value={suite} onChange={(event) => { reset(); setSuite(event.target.value); setBaseline(""); setCandidate(""); }}><option value="">{t("All datasets")}</option>{[...new Set(snapshots.map((row) => row.eval_result.suite))].map((id) => <option key={id} value={id}>{snapshots.find((row) => row.eval_result.suite === id)?.suite_title ?? id}</option>)}</select></label><div className="comparison-picker">{(["Baseline", "Candidate"] as const).map((label) => <label key={label}>{t(label)}<select disabled={loading || error || !snapshots.length} value={label === "Baseline" ? baseline : candidate} onChange={(event) => { reset(); if (label === "Baseline") setBaseline(event.target.value); else setCandidate(event.target.value); }}><option value="">{t("Select result")}</option>{available.map((row) => <option key={row.snapshot_id} value={row.snapshot_id}>{row.suite_title ?? row.eval_result.suite} · {row.label}</option>)}</select></label>)}<button className="button primary" disabled={loading || error || busy || !before || !after || baseline === candidate || Boolean(mismatch)} onClick={() => void compare()}>{t("Compare selected results")}</button></div>
        {!loading && !error && available.length < 2 && <p role="status">{t("Publish two compatible evaluations to compare real results, or explore the example.")}</p>}
        {mismatch && <p role="status">{t("These results use different dataset versions. Choose matching versions.")}</p>}
        {failed && <p role="alert">{t("Comparison could not be loaded.")} <button className="button" onClick={() => void compare()}>{t("Retry")}</button></p>}
      </>}
      <details><summary>{t("How to read comparison metrics")}</summary><p>{t("Compare evidence hits, rank and recorded latency together. Higher retrieval scores do not guarantee a factual final answer.")}</p></details>
    </section>
    {(example || comparison) && <section className="surface"><h3>{t(example ? "Illustrative example only — not an evaluation result." : "Recorded results")}</h3><div className="golden-table-scroll"><table className="evaluation-comparison-table"><thead><tr><th>{t("Metric")}</th><th>{t("Baseline")}</th><th>{t("Candidate")}</th><th>{t("Change")}</th></tr></thead><tbody>{metrics.map((row) => <tr key={row.name}><td>{row.name}</td><td>{row.baseline.toLocaleString(locale, { maximumFractionDigits: 3 })}</td><td>{row.candidate.toLocaleString(locale, { maximumFractionDigits: 3 })}</td><td>{row.delta == null ? "—" : row.delta.toLocaleString(locale, { maximumFractionDigits: 3, signDisplay: "always" })}</td></tr>)}</tbody></table></div>
      {comparison?.warning && !example && <p className="notice">{comparison.warning}</p>}
      <><div className="evaluation-list-tools"><label>{t("Search ID or question")}<input value={query} onChange={(event) => { setQuery(event.target.value); setPage(0); }} /></label></div>{cases.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE).map((row) => <details className="case-row" key={row.case_id}><summary>{row.case_id} · {example ? t(row.candidate_question) : row.candidate_question}</summary><p>{t("First rank")}: {row.baseline_rank ?? "—"} → {row.candidate_rank ?? "—"}</p><p>{t(row.transition.replaceAll("_", " "))}</p></details>)}{!cases.length && <p>{t("No case-level changes were recorded for this comparison.")}</p>}<div className="action-row"><button className="button" disabled={!page} onClick={() => setPage(page - 1)}>{t("Previous")}</button><span>{cases.length ? page + 1 : 0} / {Math.ceil(cases.length / PAGE_SIZE)}</span><button className="button" disabled={(page + 1) * PAGE_SIZE >= cases.length} onClick={() => setPage(page + 1)}>{t("Next")}</button></div></>
    </section>}
  </div>;
}
