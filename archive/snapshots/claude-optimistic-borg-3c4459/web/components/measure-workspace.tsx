"use client";

import { Beaker, Play } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import {
  compareEvaluations,
  compareSnapshots,
  createGoldenDraft,
  createSnapshot,
  getAdminSnapshots,
  getEvaluationJobs,
  getEvaluationResult,
  getGoldenSuites,
  getGoldenCanonical,
  getGoldenRevisions,
  getPublishedSnapshots,
  queueEvaluation,
  saveGoldenCase,
  setSnapshotVisibility,
  transitionGoldenRevision,
} from "@/lib/api";
import { CANNED_COMPARISON, CANNED_JOB, CANNED_SUITES } from "@/lib/canned";
import type {
  EvaluationComparison,
  EvaluationJob,
  EvaluationRequest,
  EvaluationResultDetail,
  GoldenCanonical,
  GoldenRevision,
  GoldenSuite,
  OperatorJobBoard,
  PublishedSnapshot,
  RetrievalProfile,
  SnapshotComparison,
  SuiteId,
} from "@/lib/types";
import { deploymentLabel } from "@/lib/deployment";
import { loadExperimentDefaults } from "@/lib/storage";
import { Metric } from "@/components/metric";
import { Playground } from "@/components/playground";
import { ProfileFields } from "@/components/profile-fields";
import { useNotifications } from "@/components/notifications";

export type MeasureTab = "playground" | "golden" | "runs" | "compare" | "snapshots";

export const MEASURE_TABS: Array<[MeasureTab, string]> = [
  ["playground", "Playground"],
  ["golden", "Golden Tests"],
  ["runs", "Runs"],
  ["compare", "Compare"],
  ["snapshots", "Snapshots"],
];

export interface MeasureWorkspaceProps {
  live: boolean;
  ready: boolean;
  profile: RetrievalProfile;
  onProfileChange: (profile: RetrievalProfile) => void;
  onApplyProfile: (profile: RetrievalProfile, source?: string) => void;
  onApplySnapshot: (snapshot: PublishedSnapshot) => void;
  jobBoard: OperatorJobBoard;
  onRefreshJobs: () => void;
  tab: MeasureTab;
  onTabChange: (tab: MeasureTab) => void;
  onOpenSettings: (category: "experiments" | "review") => void;
  focusResultId?: number | null;
}

/** Short profile summary for the collapsed "Retrieval profile" disclosure, e.g. `hybrid · ts_rank_cd · k 5`. */
function profileSummary(profile: RetrievalProfile): string {
  const parts: string[] = [profile.strategy];
  if (profile.strategy !== "vector" && profile.lexical_ranker) parts.push(profile.lexical_ranker);
  parts.push(`k ${profile.k}`);
  if (profile.reranker) parts.push(profile.reranker.replaceAll("_", " "));
  return parts.join(" · ");
}

function toCanonical(value: unknown): GoldenCanonical | null {
  if (typeof value !== "object" || value === null) return null;
  const row = value as Record<string, unknown>;
  return typeof row.sha256 === "string" && typeof row.filename === "string"
    ? { suite_id: row.suite_id as SuiteId, filename: row.filename, sha256: row.sha256, payload: Array.isArray(row.payload) ? row.payload as Array<Record<string, unknown>> : [] }
    : null;
}

export function MeasureWorkspace({ live, ready, profile, onProfileChange, onApplyProfile, onApplySnapshot, jobBoard, onRefreshJobs, tab, onTabChange, onOpenSettings, focusResultId = null }: MeasureWorkspaceProps) {
  const { notify } = useNotifications();
  const [experimentDefaults] = useState(loadExperimentDefaults);
  // Fixtures seed only the public build; a live build waits for the administrator API.
  const [suites, setSuites] = useState<GoldenSuite[]>(() => (live ? [] : CANNED_SUITES));
  const [suiteId, setSuiteId] = useState<SuiteId>(experimentDefaults.suite_id);
  const [jobs, setJobs] = useState<EvaluationJob[]>(() => (live ? [] : [CANNED_JOB]));
  const [comparison, setComparison] = useState<EvaluationComparison | null>(() => (live ? null : CANNED_COMPARISON));
  const [busy, setBusy] = useState(false);
  const [mode, setMode] = useState<"quick" | "matrix">(experimentDefaults.mode);
  const [chunkTargets, setChunkTargets] = useState("500 1200");
  const [environment, setEnvironment] = useState<"DEV" | "PROD">("PROD");
  const [selectedResultId, setSelectedResultId] = useState<number | null>(null);
  const [resultDetail, setResultDetail] = useState<EvaluationResultDetail | null>(null);
  const [snapshots, setSnapshots] = useState<PublishedSnapshot[]>([]);
  const [snapshotIds, setSnapshotIds] = useState<[number | null, number | null]>([experimentDefaults.baseline_snapshot_id, experimentDefaults.snapshot_id]);
  const [goldenRevisions, setGoldenRevisions] = useState<GoldenRevision[]>([]);
  const [goldenCanonical, setGoldenCanonical] = useState<GoldenCanonical | null>(null);
  const [selectedGoldenRevision, setSelectedGoldenRevision] = useState<number | null>(experimentDefaults.golden_revision_id);
  const [selectedGoldenCase, setSelectedGoldenCase] = useState("");
  const [goldenCaseJson, setGoldenCaseJson] = useState("");
  const [goldenCaseQuery, setGoldenCaseQuery] = useState("");
  const [goldenCaseSort, setGoldenCaseSort] = useState("id");
  const [snapshotComparison, setSnapshotComparison] = useState<SnapshotComparison | null>(null);
  const [snapshotLabel, setSnapshotLabel] = useState("");

  const evaluationRequest = useMemo<EvaluationRequest>(() => ({
    suite_id: suiteId,
    golden_revision_id: selectedGoldenRevision,
    mode,
    profile,
    target_text_chars: chunkTargets
      .split(/[\s,]+/)
      .map(Number)
      .filter((value) => Number.isInteger(value) && value > 0),
    strategies: ["lexical", "vector", "hybrid"],
    lexical_rankers: ["ts_rank_cd", "bm25"],
  }), [chunkTargets, mode, profile, selectedGoldenRevision, suiteId]);
  const parsedGoldenCase = useMemo<Record<string, unknown> | null>(() => {
    try { return goldenCaseJson ? JSON.parse(goldenCaseJson) as Record<string, unknown> : null; }
    catch { return null; }
  }, [goldenCaseJson]);

  useEffect(() => {
    setEnvironment(deploymentLabel(window.location.hostname));
  }, []);

  async function refresh() {
    if (!live) return;
    try {
      const [suiteRows, jobRows, snapshotRows] = await Promise.all([getGoldenSuites(), getEvaluationJobs(), getAdminSnapshots()]);
      setSuites(Array.isArray(suiteRows) ? suiteRows : []);
      setJobs(Array.isArray(jobRows) ? jobRows : []);
      setSnapshots(Array.isArray(snapshotRows) ? snapshotRows : []);
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Refresh failed.", "error", "measure-refresh");
    }
  }

  useEffect(() => {
    void refresh();
  }, [live]);
  useEffect(() => {
    if (!live) return;
    void getEvaluationJobs().then((rows) => setJobs(Array.isArray(rows) ? rows : [])).catch(() => undefined);
  }, [live, jobBoard]);
  useEffect(() => {
    if (!live) void getPublishedSnapshots().then((rows) => setSnapshots(Array.isArray(rows) ? rows : [])).catch(() => undefined);
  }, [live]);
  useEffect(() => {
    if (!live) return;
    void Promise.all([getGoldenRevisions(suiteId), getGoldenCanonical(suiteId)]).then(([value, canonical]) => {
      const rows = Array.isArray(value) ? value : [];
      setGoldenRevisions(rows);
      setGoldenCanonical(toCanonical(canonical));
      const preferredRevision = suiteId === experimentDefaults.suite_id
        ? experimentDefaults.golden_revision_id
        : null;
      setSelectedGoldenRevision(
        rows.some((row) => row.revision_id === preferredRevision) ? preferredRevision : null,
      );
      setSelectedGoldenCase("");
      setGoldenCaseJson("");
    }).catch((reason) => notify(String(reason), "error", "golden-revisions"));
  }, [live, suiteId, notify, experimentDefaults.golden_revision_id]);
  useEffect(() => {
    if (!live || focusResultId === null) return;
    setSelectedResultId(focusResultId);
    void openResult(focusResultId);
  }, [live, focusResultId]);

  async function runEvaluation() {
    if (!live) { notify("Production experiment controls are locked. Compare published snapshots instead.", "warning", "prod-eval"); return; }
    if (!ready || busy) return;
    setBusy(true);
    try {
      const job = await queueEvaluation(evaluationRequest);
      setJobs((current) => [job, ...current]);
      onRefreshJobs();
      notify("Evaluation queued.", "success", "evaluation-queued");
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Evaluation failed.", "error", "evaluation");
    } finally {
      setBusy(false);
    }
  }

  async function loadComparison(candidate: number, baseline: number) {
    if (!live) return;
    try {
      setComparison(await compareEvaluations(candidate, baseline));
      onTabChange("compare");
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Comparison failed.", "error", "comparison");
    }
  }

  async function openResult(resultId: number) {
    if (!live) return;
    try {
      setResultDetail(await getEvaluationResult(resultId));
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Evaluation detail could not be loaded.", "error", "evaluation-detail");
    }
  }

  function applySelectedResult() {
    const job = jobs.find((item) => item.result_ids.includes(selectedResultId ?? -1));
    if (!job || selectedResultId === null) return;
    onApplyProfile(job.request.profile, `${job.request.suite_id}:${selectedResultId}`);
  }

  async function newGoldenDraft() {
    if (!live) return;
    try {
      const created = await createGoldenDraft(suiteId, selectedGoldenRevision);
      setGoldenRevisions((current) => [created, ...current]);
      setSelectedGoldenRevision(created.revision_id);
      notify(`Golden draft v${created.version} created.`, "success", "golden-draft");
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Golden draft could not be created.", "error", "golden-draft");
    }
  }

  function openGoldenCase(caseValue: Record<string, unknown>) {
    setSelectedGoldenCase(String(caseValue.id ?? ""));
    setGoldenCaseJson(JSON.stringify(caseValue, null, 2));
  }

  function patchGoldenCase(field: string, value: unknown) {
    if (!parsedGoldenCase) return;
    setGoldenCaseJson(JSON.stringify({ ...parsedGoldenCase, [field]: value }, null, 2));
  }

  function patchGoldenAnswer(index: number, field: string, value: string | number) {
    if (!parsedGoldenCase || !Array.isArray(parsedGoldenCase.answers)) return;
    const answers = parsedGoldenCase.answers.map((answer, answerIndex) => answerIndex === index && typeof answer === "object" && answer !== null ? { ...answer, [field]: value } : answer);
    patchGoldenCase("answers", answers);
  }

  function addGoldenAnswer() {
    if (!parsedGoldenCase) return;
    const answers = Array.isArray(parsedGoldenCase.answers) ? parsedGoldenCase.answers : [];
    patchGoldenCase("answers", [...answers, { doc_id: "", source_sha256: "", start_char: 0, end_char: 1 }]);
  }

  function removeGoldenAnswer(index: number) {
    if (!parsedGoldenCase || !Array.isArray(parsedGoldenCase.answers)) return;
    patchGoldenCase("answers", parsedGoldenCase.answers.filter((_answer, answerIndex) => answerIndex !== index));
  }

  async function saveSelectedGoldenCase() {
    const revision = goldenRevisions.find((item) => item.revision_id === selectedGoldenRevision);
    if (!revision || !selectedGoldenCase) return;
    try {
      const value = JSON.parse(goldenCaseJson) as Record<string, unknown>;
      const updated = await saveGoldenCase(revision.revision_id, selectedGoldenCase, revision.sha256, value);
      setGoldenRevisions((current) => current.map((item) => item.revision_id === updated.revision_id ? updated : item));
      notify("Golden case saved.", "success", "golden-save");
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Golden case could not be saved.", "error", "golden-save");
    }
  }

  async function changeGoldenStatus(action: "validate" | "publish") {
    const revision = goldenRevisions.find((item) => item.revision_id === selectedGoldenRevision);
    if (!revision) return;
    try {
      const updated = await transitionGoldenRevision(revision.revision_id, action, revision.sha256);
      setGoldenRevisions((current) => current.map((item) => item.revision_id === updated.revision_id ? updated : item));
      notify(`Golden revision ${action}d.`, "success", `golden-${action}`);
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : `Golden revision could not be ${action}d.`, "error", `golden-${action}`);
    }
  }

  async function freezeSnapshot() {
    if (!live || selectedResultId === null || !snapshotLabel.trim()) return;
    try {
      const revision = goldenRevisions.find((item) => item.revision_id === selectedGoldenRevision);
      const created = await createSnapshot({ label: snapshotLabel.trim(), eval_result_id: selectedResultId, golden_revision_id: revision?.status === "published" ? revision.revision_id : null, public: false });
      setSnapshots((current) => [created, ...current]);
      setSnapshotLabel("");
      notify("Evaluation snapshot created.", "success", "snapshot-create");
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Snapshot could not be created.", "error", "snapshot-create");
    }
  }

  async function loadSnapshotComparison() {
    if (!snapshotIds[0] || !snapshotIds[1]) return;
    try {
      setSnapshotComparison(await compareSnapshots(snapshotIds[0], snapshotIds[1], live));
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Snapshots could not be compared.", "error", "snapshot-compare");
    }
  }

  async function toggleSnapshot(snapshot: PublishedSnapshot) {
    if (!live) return;
    try {
      const updated = await setSnapshotVisibility(snapshot.snapshot_id, !snapshot.public);
      setSnapshots((current) => current.map((item) => item.snapshot_id === updated.snapshot_id ? updated : item));
      notify(updated.public ? "Snapshot published." : "Snapshot hidden.", "success", "snapshot-visibility");
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Snapshot visibility could not change.", "error", "snapshot-visibility");
    }
  }

  const selectedSuite = suites.find((suite) => suite.suite_id === suiteId) ?? suites[0];
  const activeGoldenRevision = goldenRevisions.find((item) => item.revision_id === selectedGoldenRevision) ?? null;
  const activeGoldenCases = activeGoldenRevision?.payload ?? goldenCanonical?.payload ?? [];
  const visibleGoldenCases = activeGoldenCases.filter((item) => `${String(item.id)} ${String(item.question)} ${String(item.category)} ${String(item.facet)} ${Array.isArray(item.tags) ? item.tags.join(" ") : ""}`.toLowerCase().includes(goldenCaseQuery.toLowerCase())).toSorted((left, right) => String(left[goldenCaseSort] ?? "").localeCompare(String(right[goldenCaseSort] ?? ""), undefined, { numeric: true }));
  const goldenReadOnly = !activeGoldenRevision || activeGoldenRevision.status === "published";
  const goldenScoreResult = resultDetail?.suite === suiteId ? resultDetail : null;
  const canRun = live && ready;

  const suiteSelect = (helpId: string) => <label data-help={helpId}>Golden suite<select value={suiteId} onChange={(event) => setSuiteId(event.target.value as SuiteId)}>{suites.map((suite) => <option key={suite.suite_id} value={suite.suite_id}>{suite.label}</option>)}</select></label>;
  const revisionSelect = (helpId: string) => <label data-help={helpId}>Golden revision<select value={selectedGoldenRevision ?? ""} onChange={(event) => { setSelectedGoldenRevision(event.target.value ? Number(event.target.value) : null); setSelectedGoldenCase(""); setGoldenCaseJson(""); }}><option value="">Canonical JSON · read-only</option>{goldenRevisions.map((revision) => <option key={revision.revision_id} value={revision.revision_id}>v{revision.version} · {revision.status}</option>)}</select></label>;
  const lockedRuns = (message: string) => <div className="empty-state"><p>{message}</p><button className="button" type="button" onClick={() => onTabChange("snapshots")}>Open Snapshots</button></div>;

  return (
    <section className="lab-shell measure-workspace">
      <header className="page-heading">
        <div><p className="eyebrow">Measure</p><h1>Measure retrieval before trusting it.</h1></div>
        <div className="page-badges"><span className="mode-badge">{environment}</span><span className={`mode-badge ${live ? "live" : ""}`}>{live ? "Local operator" : "Read-only portfolio"}</span></div>
      </header>
      <nav className="lab-tabs" aria-label="Measure sections">
        {MEASURE_TABS.map(([id, label]) => (
          <button key={id} type="button" aria-pressed={tab === id} onClick={() => onTabChange(id)}>{label}</button>
        ))}
      </nav>

      {tab === "playground" && <Playground live={live} profile={profile} onProfileChange={onProfileChange} onOpenSnapshots={() => onTabChange("snapshots")} />}

      {tab === "golden" && <div className="golden-workspace">
        <section className="surface form-stack golden-controls">
          {suiteSelect("measure.golden.suite")}
          {selectedSuite && <div className="provenance"><strong>{selectedSuite.case_count} cases</strong><span>{selectedSuite.curation_status}</span><span>{selectedSuite.approval_status}</span><span>human_verified=false</span>{!selectedSuite.source_ready && <span className="danger">Sources unavailable</span>}</div>}
          {live && <><div className="golden-file"><span>Canonical file</span><strong>{goldenCanonical?.filename ?? "Loading…"}</strong><code>{goldenCanonical?.sha256.slice(0, 12) ?? "—"}</code></div>{revisionSelect("measure.golden.revision")}<div className="action-row"><button className="button" type="button" onClick={() => void newGoldenDraft()}>Create draft</button><button className="button" type="button" disabled={!activeGoldenRevision || activeGoldenRevision.status === "published"} onClick={() => void changeGoldenStatus("validate")}>Validate</button><button className="button" type="button" disabled={activeGoldenRevision?.status !== "validated"} onClick={() => void changeGoldenStatus("publish")}>Publish JSON</button></div><p className="helper">Canonical and published revisions are immutable. Create a draft before editing questions or source spans.</p><button className="button ghost" type="button" onClick={() => onTabChange("runs")}>Queue a run with this suite</button></>}
          {!live && <p className="helper">Golden suites are edited on the local operator build. Compare stored published snapshots instead.</p>}
        </section>
        <section className="surface golden-manager" data-help="measure.golden.questions">
          <div className="surface-heading"><div><h2>{live ? "Golden questions" : "Latest comparison"}</h2>{live && <p className="helper">{activeGoldenRevision ? `Revision v${activeGoldenRevision.version} · ${activeGoldenRevision.status}` : "Canonical JSON · read-only"}{goldenScoreResult ? ` · scores from result #${goldenScoreResult.result_id}` : " · no evaluation result selected"}</p>}</div></div>
          {live ? <><div className="golden-table-tools"><input aria-label="Search golden cases" placeholder="Search ID, question, category, facet, or tag" value={goldenCaseQuery} onChange={(event) => setGoldenCaseQuery(event.target.value)} /><select aria-label="Sort golden cases" value={goldenCaseSort} onChange={(event) => setGoldenCaseSort(event.target.value)}><option value="id">ID</option><option value="question">Question</option><option value="category">Category</option><option value="facet">Facet</option></select></div><div className="golden-table-scroll"><table><thead><tr><th>ID</th><th>Question</th><th>Category</th><th>Facet</th><th>Tags</th><th>Eval</th><th>First rank</th><th>RR</th></tr></thead><tbody>{visibleGoldenCases.map((item) => { const score = goldenScoreResult?.cases.find((value) => value.case_id === item.id); const rank = score?.first_relevant_rank ?? null; return <tr key={String(item.id)} className={selectedGoldenCase === String(item.id) ? "selected" : ""}><td><button type="button" className="row-detail" onClick={() => openGoldenCase(item)}>{String(item.id)}</button></td><td>{String(item.question)}</td><td>{String(item.category)}</td><td>{String(item.facet)}</td><td>{Array.isArray(item.tags) && item.tags.length ? item.tags.join(", ") : "—"}</td><td>{score ? rank ? "hit" : "miss" : "not run"}</td><td>{rank ?? "—"}</td><td>{score ? (rank ? 1 / rank : 0).toFixed(3) : "—"}</td></tr>; })}</tbody></table></div>{!visibleGoldenCases.length && <p className="helper">No questions match this filter.</p>}{selectedGoldenCase && <div className="golden-editor"><div className="golden-editor-heading"><div><h3>{selectedGoldenCase}</h3><p>{goldenReadOnly ? "Read-only source" : "Editable draft"}</p></div><span className={`job-status ${goldenReadOnly ? "" : "running"}`}>{goldenReadOnly ? "locked" : "draft"}</span></div>{parsedGoldenCase && <div className="form-stack"><label>Question<textarea disabled={goldenReadOnly} value={String(parsedGoldenCase.question ?? "")} onChange={(event) => patchGoldenCase("question", event.target.value)} /></label><label>Reference answer<textarea disabled={goldenReadOnly} value={String(parsedGoldenCase.reference_answer ?? "")} onChange={(event) => patchGoldenCase("reference_answer", event.target.value)} /></label><div className="profile-grid"><label>Category<select disabled={goldenReadOnly} value={String(parsedGoldenCase.category ?? "simple_lookup")} onChange={(event) => patchGoldenCase("category", event.target.value)}><option value="simple_lookup">Simple lookup</option><option value="exact_number">Exact number</option><option value="multi_hop">Multi-hop</option><option value="absent">Absent</option></select></label><label>Facet<select disabled={goldenReadOnly} value={String(parsedGoldenCase.facet ?? "factual")} onChange={(event) => patchGoldenCase("facet", event.target.value)}><option value="factual">Factual</option><option value="comparison">Comparison</option><option value="risk">Risk</option><option value="policy">Policy</option><option value="numeric">Numeric</option></select></label><label>Expected label<select disabled={goldenReadOnly} value={String(parsedGoldenCase.expected_label ?? "SUPPORTED")} onChange={(event) => patchGoldenCase("expected_label", event.target.value)}><option value="SUPPORTED">SUPPORTED</option><option value="NOT_IN_DOCS">NOT_IN_DOCS</option></select></label><label>Tags<input disabled={goldenReadOnly} value={Array.isArray(parsedGoldenCase.tags) ? parsedGoldenCase.tags.join(" ") : ""} onChange={(event) => patchGoldenCase("tags", event.target.value.split(/[\s,]+/).filter(Boolean))} placeholder="demo-hero numeric" /></label></div><label>Reviewer note<textarea disabled={goldenReadOnly} value={String(parsedGoldenCase.note ?? "")} onChange={(event) => patchGoldenCase("note", event.target.value)} /></label><div className="golden-spans"><div className="surface-heading"><h3>Answer source spans</h3><button className="button ghost" type="button" disabled={goldenReadOnly} onClick={addGoldenAnswer}>Add span</button></div>{goldenAnswers(parsedGoldenCase).map((answer, index) => <article key={`${String(answer.doc_id)}:${index}`}><div className="golden-span-heading"><strong>Span {index + 1}</strong><button className="button ghost" type="button" disabled={goldenReadOnly} onClick={() => removeGoldenAnswer(index)}>Remove</button></div><div className="profile-grid"><label>Document ID<input disabled={goldenReadOnly} value={String(answer.doc_id ?? "")} onChange={(event) => patchGoldenAnswer(index, "doc_id", event.target.value)} /></label><label>Start char<input disabled={goldenReadOnly} type="number" min={0} value={Number(answer.start_char ?? 0)} onChange={(event) => patchGoldenAnswer(index, "start_char", Number(event.target.value))} /></label><label>End char<input disabled={goldenReadOnly} type="number" min={1} value={Number(answer.end_char ?? 1)} onChange={(event) => patchGoldenAnswer(index, "end_char", Number(event.target.value))} /></label><label>Source SHA-256<input disabled={goldenReadOnly} value={String(answer.source_sha256 ?? "")} onChange={(event) => patchGoldenAnswer(index, "source_sha256", event.target.value)} /></label></div></article>)}{!goldenAnswers(parsedGoldenCase).length && <p className="helper">Absent cases intentionally have no source span.</p>}</div><label>Single-case JSON<textarea disabled={goldenReadOnly} className="golden-json" value={goldenCaseJson} onChange={(event) => setGoldenCaseJson(event.target.value)} spellCheck={false} /></label><button className="button primary" type="button" disabled={goldenReadOnly || !parsedGoldenCase} onClick={() => void saveSelectedGoldenCase()}>Save case</button></div>}</div>}</> : (comparison?.metrics ?? []).map((metric) => <div className="metric-row" key={metric.name}><span>{metric.name}</span><strong>{metric.candidate.toFixed(3)}</strong><em className={metric.delta >= 0 ? "positive" : "negative"}>{metric.delta >= 0 ? "+" : ""}{metric.delta.toFixed(3)}</em></div>)}
          <p className="helper">Hit, first rank, and reciprocal rank measure retrieval—not final-answer factuality.</p>
        </section>
      </div>}

      {tab === "runs" && (live ? <div className="two-column run-workspace">
        <section className="surface form-stack">
          <div className="surface-heading"><div><h2>New run</h2><p className="helper">Queue one evaluation against the selected golden suite.</p></div></div>
          {suiteSelect("measure.runs.suite")}
          {revisionSelect("measure.runs.revision")}
          <label data-help="measure.runs.mode">Run mode<select value={mode} onChange={(event) => setMode(event.target.value as "quick" | "matrix")}><option value="quick">Quick · current index</option><option value="matrix">Matrix · isolated corpus</option></select></label>
          {mode === "matrix" && <label data-help="measure.runs.chunk_targets">Chunk targets<input value={chunkTargets} onChange={(event) => setChunkTargets(event.target.value)} placeholder="500 1200" /></label>}
          <details data-help="measure.runs.profile"><summary>Retrieval profile · {profileSummary(profile)}</summary><ProfileFields profile={profile} onChange={onProfileChange} helpPrefix="measure.runs" /></details>
          <button className="button primary" type="button" data-help="measure.runs.queue" aria-disabled={!canRun || busy} onClick={() => void runEvaluation()}><Play size={15} /> {busy ? "Queueing…" : "Queue evaluation"}</button>
          {!ready && <p className="helper">Corpus not ready. Finish Build steps 2–4.</p>}
          <p className="helper">Uses the current review&apos;s retrieval profile. Change presets in Settings › Review session.</p>
          <button className="button ghost" type="button" onClick={() => onOpenSettings("experiments")}>Defaults</button>
        </section>
        <div className="panel-stack run-results">
          <section className="surface">
            <div className="surface-heading"><h2 data-help="measure.runs.results">Results</h2><button className="button primary" type="button" data-help="measure.runs.use_selected" disabled={selectedResultId === null} onClick={applySelectedResult}>Use selected set</button></div>
            {jobs.map((job) => <article className="job-row" key={job.job_id}><div className="job-select"><input type="radio" name="evaluation-result" aria-label={`Select ${job.job_id}`} disabled={job.status !== "succeeded" || !job.result_id} checked={selectedResultId === job.result_id} onChange={() => setSelectedResultId(job.result_id)} /><button className="row-detail" type="button" disabled={!job.result_id} onClick={() => job.result_id && void openResult(job.result_id)}><strong>{job.request.suite_id} · {job.request.mode}</strong><p>{job.message}</p></button></div><span>{job.status}</span>{job.status === "succeeded" && job.result_id && job.baseline_id && <button className="button ghost" type="button" onClick={() => void loadComparison(job.result_id!, job.baseline_id!)}>Compare</button>}{job.result_ids.length > 1 && <div className="job-arms">{job.result_ids.map((resultId) => <label key={resultId}><input type="radio" name="evaluation-result" checked={selectedResultId === resultId} onChange={() => setSelectedResultId(resultId)} /> Result {resultId}</label>)}</div>}</article>)}
            {!jobs.length && <p className="helper">No evaluation has run yet. Queue one on the left.</p>}
          </section>
          <section className="surface detail-panel" data-help="measure.runs.result_detail">
            <h2>Result details</h2>
            {resultDetail ? <><div className="metric-grid compact">{Object.entries(resultDetail.metrics).map(([name, value]) => <Metric key={name} icon={<Beaker />} label={name} value={value.toFixed(3)} />)}</div><pre>{JSON.stringify(resultDetail.config, null, 2)}</pre><h3>Cases</h3>{resultDetail.cases.slice(0, 10).map((item) => <article className="case-row" key={item.case_id}><div><strong>{item.case_id}</strong><p>{item.question}</p></div><span>{item.first_relevant_rank ? `rank ${item.first_relevant_rank}` : "miss"}</span></article>)}</> : <p className="helper">Select a succeeded result, then click its row to inspect metrics and cases.</p>}
          </section>
        </div>
      </div> : lockedRuns("Runs happen on the local operator build."))}

      {tab === "compare" && <div className="panel-stack" data-help="measure.compare.overview">
        {comparison ? <>
          <div className="metric-grid">{comparison.metrics.map((metric) => <Metric key={metric.name} icon={<Beaker />} label={metric.name} value={`${metric.candidate.toFixed(3)} (${metric.delta >= 0 ? "+" : ""}${metric.delta.toFixed(3)})`} />)}</div>
          <section className="surface" data-help="measure.compare.cases"><h2>Case changes</h2>{comparison.cases.map((item) => <article className="case-row" key={item.case_id}><div><strong>{item.case_id}</strong><p>{item.question}</p></div><span className={`transition ${item.transition}`}>{item.transition.replaceAll("_", " ")}</span></article>)}{!comparison.cases.length && <p className="helper">No case-level changes were recorded for this comparison.</p>}</section>
        </> : <div className="empty-state"><p>No comparison loaded yet. Queue a run, then click Compare on a succeeded result that has a baseline.</p><button className="button" type="button" onClick={() => onTabChange("runs")}>Open Runs</button></div>}
      </div>}

      {tab === "snapshots" && <div className="two-column"><section className="surface form-stack"><h2>{live ? "Evaluation snapshots" : "Published snapshots"}</h2>{live && <><label>Snapshot label<input value={snapshotLabel} onChange={(event) => setSnapshotLabel(event.target.value)} placeholder="BM25 tuned baseline" /></label><button className="button" type="button" data-help="measure.snapshots.freeze" disabled={selectedResultId === null || !snapshotLabel.trim()} onClick={() => void freezeSnapshot()}>Freeze selected eval result</button></>}<label>Baseline<select value={snapshotIds[0] ?? ""} onChange={(event) => setSnapshotIds([Number(event.target.value) || null, snapshotIds[1]])}><option value="">Select</option>{snapshots.map((item) => <option key={item.snapshot_id} value={item.snapshot_id}>{item.label} · {item.eval_result.suite}</option>)}</select></label><label>Candidate<select value={snapshotIds[1] ?? ""} onChange={(event) => setSnapshotIds([snapshotIds[0], Number(event.target.value) || null])}><option value="">Select</option>{snapshots.map((item) => <option key={item.snapshot_id} value={item.snapshot_id}>{item.label} · {item.eval_result.suite}</option>)}</select></label><button className="button primary" type="button" data-help="measure.snapshots.compare" disabled={!snapshotIds[0] || !snapshotIds[1]} onClick={() => void loadSnapshotComparison()}>Compare stored results</button><div className="snapshot-list" data-help="measure.snapshots.list">{snapshots.map((item) => <article key={item.snapshot_id}><div><strong>{item.label}</strong><p>{item.document_count} documents · {item.eval_result.suite} · #{item.eval_result.result_id}</p></div><div className="action-row">{live && <button className="button ghost" type="button" onClick={() => onApplySnapshot(item)}>Use for review</button>}{live && <button className="button ghost" type="button" onClick={() => void toggleSnapshot(item)}>{item.public ? "Hide" : "Publish"}</button>}</div></article>)}</div><p className="helper">Stored artifacts only. Comparing snapshots does not run an evaluation or provider request.</p></section><section className="surface snapshot-comparison" data-help="measure.snapshots.comparison"><h2>Snapshot comparison</h2>{snapshotComparison?.warning && <p className="notice error">{snapshotComparison.warning}</p>}{snapshotComparison ? <><div className="metric-table">{snapshotComparison.metrics.map((metric) => <div key={metric.name}><span>{metric.name}</span><strong>{metric.candidate.toFixed(3)}</strong><em className={metric.delta === null ? "" : metric.delta >= 0 ? "positive" : "negative"}>{metric.delta === null ? "n/a" : `${metric.delta >= 0 ? "+" : ""}${metric.delta.toFixed(3)}`}</em></div>)}</div><div className="snapshot-case-heading"><h3>Common cases</h3><span>{snapshotComparison.common_case_count}</span></div><div className="snapshot-case-list">{snapshotComparison.cases.map((item) => <article key={item.case_id}><div className="job-title"><strong>{item.case_id}</strong><span className={`transition ${item.transition}`}>{item.transition.replaceAll("_", " ")}</span></div><div className="snapshot-case-side"><div><span>Baseline · {item.baseline_rank ? `rank ${item.baseline_rank}` : "miss"}</span><p>{item.baseline_question}</p></div><div><span>Candidate · {item.candidate_rank ? `rank ${item.candidate_rank}` : "miss"}</span><p>{item.candidate_question}</p></div></div>{item.rank_delta !== null && <small>Rank delta {item.rank_delta > 0 ? "+" : ""}{item.rank_delta}</small>}</article>)}</div>{!snapshotComparison.cases.length && <p className="helper">The stored artifacts have no common cases.</p>}</> : <p className="helper">Select two snapshots and compare them.</p>}</section></div>}
    </section>
  );
}

function goldenAnswers(value: Record<string, unknown>): Array<Record<string, unknown>> {
  return Array.isArray(value.answers)
    ? value.answers.filter((answer): answer is Record<string, unknown> => typeof answer === "object" && answer !== null)
    : [];
}
