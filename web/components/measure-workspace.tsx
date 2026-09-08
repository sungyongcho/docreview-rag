"use client";
import { NotificationOutlet } from "./notifications";
import { preparationErrorTarget, preparationTarget, type PreparationTarget } from "@/lib/preparation-navigation";
import type { Readiness } from "@/lib/types";
import { DEFAULT_PROFILE } from "@/lib/types";
import { createPortal } from "react-dom";
import { translate, useI18n, type Locale } from "@/lib/i18n";


import { RetainedPanel } from "@/components/retained-panel";
import { DevelopmentBadge } from "@/components/development-badge";
import { WorkflowHelp } from "@/components/workflow-help";

import "./evaluation-workspace.css";

import { Beaker, Play, Plus, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import {
  cancelOperatorJob,
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
import type {
  Capabilities,
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
import { RetrievalPresetManager } from "./retrieval-preset-manager";
import { ExperimentDefaultsForm } from "@/components/experiment-defaults";
import { Metric } from "@/components/metric";
import { Playground } from "@/components/playground";
import { ProfileFields } from "@/components/profile-fields";
import { useNotifications } from "@/components/notifications";

export type MeasureTab = "playground" | "golden" | "runs" | "compare" | "snapshots" | "defaults" | "presets";

export const MEASURE_TABS: Array<[MeasureTab, string]> = [
  ["playground", "Search trial"],
  ["golden", "Golden dataset"],
  ["runs", "Run evaluation"],
  ["compare", "Compare results"],
  ["snapshots", "Snapshots"],
  ["defaults", "Defaults"],
  ["presets", "Presets"],
];

export interface MeasureWorkspaceProps {
  capabilities?: Capabilities | null;
  publicPreview?: boolean;
  active?: boolean;
  environment?: "dev" | "prod";
  live: boolean;
  ready: boolean;
  readiness?: Readiness | null;
  onOpenPreparation?: (stage: PreparationTarget) => void;
  profile: RetrievalProfile;
  onProfileChange: (profile: RetrievalProfile) => void;
  onApplyProfile: (profile: RetrievalProfile, source?: string) => void;
  onApplySnapshot: (snapshot: PublishedSnapshot) => void;
  jobBoard: OperatorJobBoard;
  onRefreshJobs: () => void;
  onDirtyChange?: (dirty: boolean) => void;
  tab: MeasureTab;
  onTabChange: (tab: MeasureTab) => void;
  focusResultId?: number | null;
  onResultSelectionChange?: (resultId: number | null) => void;
  helpTarget?: string | null;
}

/** Short profile summary for the collapsed "Retrieval profile" disclosure, e.g. `hybrid · ts_rank_cd · k 5`. */
function profileSummary(profile: RetrievalProfile, locale: Locale): string {
  const parts: string[] = [translate(locale, profile.strategy)];
  if (profile.strategy !== "vector" && profile.lexical_ranker) parts.push(profile.lexical_ranker);
  parts.push(`k ${profile.k}`);
  if (profile.reranker) parts.push(translate(locale, profile.reranker.replaceAll("_", " ")));
  return parts.join(" · ");
}

function toCanonical(value: unknown): GoldenCanonical | null {
  if (typeof value !== "object" || value === null) return null;
  const row = value as Record<string, unknown>;
  return typeof row.sha256 === "string" && typeof row.filename === "string"
    ? { suite_id: row.suite_id as SuiteId, filename: row.filename, sha256: row.sha256, payload: Array.isArray(row.payload) ? row.payload as Array<Record<string, unknown>> : [] }
    : null;
}

export function MeasureWorkspace({ capabilities, publicPreview, active = true, live, ready, readiness, onOpenPreparation, profile, onProfileChange, onApplyProfile, onApplySnapshot, jobBoard, onRefreshJobs, tab, onTabChange, focusResultId = null, onResultSelectionChange, helpTarget = null, environment, onDirtyChange }: MeasureWorkspaceProps) {
  const { t, locale } = useI18n();
  const { notify } = useNotifications();
  const [experimentDefaults, setExperimentDefaults] = useState(loadExperimentDefaults);
  // Fixtures seed only the public build; a live build waits for the administrator API.
  const [suites, setSuites] = useState<GoldenSuite[]>([]);
  const [suiteId, setSuiteId] = useState<SuiteId>(experimentDefaults.suite_id);
  const [jobs, setJobs] = useState<EvaluationJob[]>([]);
  const [jobsLoading, setJobsLoading] = useState(live);
  const [jobsError, setJobsError] = useState("");
  const [submissionError, setSubmissionError] = useState("");
  const jobsRequestRef = useRef(0);
  const [comparison, setComparison] = useState<EvaluationComparison | null>(null);
  const [busy, setBusy] = useState(false);
  const [setupOpen, setSetupOpen] = useState(false);
  useEffect(() => {
    if (active && live && helpTarget?.startsWith("measure.runs.") && !["measure.runs.results", "measure.runs.result_detail", "measure.runs.use_selected"].includes(helpTarget)) setSetupOpen(true);
  }, [active, live, helpTarget]);
  const setupRef = useRef<HTMLElement>(null);
  const resultRequestRef = useRef(0);
  const comparisonRequestRef = useRef(0);
  const snapshotComparisonRequestRef = useRef(0);
  useEffect(() => {
    if (!active || tab !== "runs" || !setupOpen) return;
    const previousFocus = document.activeElement as HTMLElement | null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    setupRef.current?.querySelector<HTMLElement>("button, select, input")?.focus();
    function trapFocus(event: KeyboardEvent) {
      if (event.key !== "Tab") return;
      const controls = Array.from(setupRef.current?.querySelectorAll<HTMLElement>("button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), summary") ?? []).filter((element) => !element.closest("details:not([open])") || element.tagName === "SUMMARY");
      const first = controls[0]; const last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    }
    document.addEventListener("keydown", trapFocus);
    return () => { document.removeEventListener("keydown", trapFocus); document.body.style.overflow = previousOverflow; previousFocus?.focus(); };
  }, [active, tab, setupOpen]);
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [goldenBusy, setGoldenBusy] = useState(false);
  const [sourceJsonOpen, setSourceJsonOpen] = useState(false);
  const [mode, setMode] = useState<"quick" | "matrix">(experimentDefaults.mode);
  const [chunkTargets, setChunkTargets] = useState("1024 2048");
  const [selectedResultId, setSelectedResultId] = useState<number | null>(null);
  const [resultError, setResultError] = useState("");
  const [resultDetail, setResultDetail] = useState<EvaluationResultDetail | null>(null);
  const [snapshots, setSnapshots] = useState<PublishedSnapshot[]>([]);
  const [snapshotIds, setSnapshotIds] = useState<[number | null, number | null]>([experimentDefaults.baseline_snapshot_id, experimentDefaults.snapshot_id]);
  const [goldenRevisions, setGoldenRevisions] = useState<GoldenRevision[]>([]);
  const [goldenCanonical, setGoldenCanonical] = useState<GoldenCanonical | null>(null);
  const [selectedGoldenRevision, setSelectedGoldenRevision] = useState<number | null>(experimentDefaults.golden_revision_id);
  const [selectedGoldenCase, setSelectedGoldenCase] = useState("");
  const [goldenCaseJson, setGoldenCaseJson] = useState("");
  const [savedGoldenJson, setSavedGoldenJson] = useState("");
  const [goldenError, setGoldenError] = useState("");
  const [compareIds, setCompareIds] = useState<[number | null, number | null]>([null, null]);
  const goldenDirty = goldenCaseJson !== savedGoldenJson && savedGoldenJson !== "";
  useEffect(() => {
    onDirtyChange?.(goldenDirty);
    function beforeLeave(event: BeforeUnloadEvent) { if (goldenDirty) { event.preventDefault(); event.returnValue = ""; } }
    window.addEventListener("beforeunload", beforeLeave);
    return () => { window.removeEventListener("beforeunload", beforeLeave); onDirtyChange?.(false); };
  }, [goldenDirty, onDirtyChange]);
  function changeTab(next: MeasureTab) {
    if (goldenBusy || next === tab) return false;
    if (goldenDirty && !window.confirm(t("Discard unsaved question changes?"))) return false;
    if (goldenDirty) setGoldenCaseJson(savedGoldenJson);
    onTabChange(next);
    return true;
  }
  useEffect(() => {
    if ((!active || tab !== "golden") && goldenDirty) setGoldenCaseJson(savedGoldenJson);
  }, [active, tab, goldenDirty, savedGoldenJson]);
  function resetGoldenSelection() {
    setSelectedGoldenCase(""); setGoldenCaseJson(""); setSavedGoldenJson(""); setGoldenError("");
  }
  function selectSuite(next: SuiteId) {
    if (goldenDirty && !window.confirm(t("Discard unsaved question changes?"))) return;
    resetGoldenSelection(); setSelectedGoldenRevision(null); setGoldenRevisions([]); setGoldenCanonical(null); setSourceJsonOpen(false); setSuiteId(next);
  }
  function selectRevision(next: number | null) {
    if (goldenDirty && !window.confirm(t("Discard unsaved question changes?"))) return;
    resetGoldenSelection(); setSelectedGoldenRevision(next);
  }
  function prepareEvaluation() {
    if (changeTab("runs")) setSetupOpen(true);
  }
  const [goldenCaseQuery, setGoldenCaseQuery] = useState("");
  const [goldenCaseSort, setGoldenCaseSort] = useState("id");
  const [snapshotComparison, setSnapshotComparison] = useState<SnapshotComparison | null>(null);
  const [snapshotLabel, setSnapshotLabel] = useState("");

  const evaluationRequest = useMemo<EvaluationRequest>(() => ({
    suite_id: suiteId,
    golden_revision_id: selectedGoldenRevision,
    mode,
    profile,
    target_tokens: chunkTargets
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


  async function refreshJobs() {
    const requestId = ++jobsRequestRef.current;
    setJobsLoading(true); setJobsError("");
    try {
      const rows = await getEvaluationJobs();
      if (requestId === jobsRequestRef.current) setJobs(Array.isArray(rows) ? rows : []);
    } catch (reason) {
      if (requestId === jobsRequestRef.current) setJobsError(reason instanceof Error ? reason.message : t("Evaluations could not be loaded."));
    } finally {
      if (requestId === jobsRequestRef.current) setJobsLoading(false);
    }
  }

  async function refresh() {
    if (!live) return;
    void refreshJobs();
    try {
      const [suiteRows, snapshotRows] = await Promise.all([getGoldenSuites(), getAdminSnapshots()]);
      setSuites(Array.isArray(suiteRows) ? suiteRows : []);
      setSnapshots(Array.isArray(snapshotRows) ? snapshotRows : []);
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : t("Refresh failed."), "error", "measure-refresh");
    }
  }

  useEffect(() => {
    void refresh();
  }, [live]);
  // Refetch evaluation runs only when an evaluation job moves; corpus job progress ticks do not count.
  const evaluationSignature = useMemo(
    () => jobBoard.jobs.filter((job) => job.domain === "evaluation").map((job) => `${job.job_id}:${job.status}:${job.updated_at}`).join("|"),
    [jobBoard.jobs],
  );
  useEffect(() => {
    if (!live) return;
    void refreshJobs();
  }, [live, evaluationSignature]);
  useEffect(() => {
    if (!live) void getPublishedSnapshots().then((rows) => setSnapshots(Array.isArray(rows) ? rows : [])).catch(() => undefined);
  }, [live]);
  useEffect(() => {
    if (!live) return;
    let active = true;
    void Promise.all([getGoldenRevisions(suiteId), getGoldenCanonical(suiteId)]).then(([value, canonical]) => {
      if (!active) return;
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
      setSavedGoldenJson("");
    }).catch((reason) => { if (active) notify(String(reason), "error", "golden-revisions"); });
    return () => { active = false; };
  }, [live, suiteId, notify, experimentDefaults.golden_revision_id]);
  useEffect(() => {
    if (!live || focusResultId === selectedResultId) return;
    if (focusResultId === null) { resultRequestRef.current += 1; setSelectedResultId(null); setResultDetail(null); return; }
    const job = jobs.find((item) => item.result_ids.includes(focusResultId));
    setSelectedJobId(job?.job_id ?? null);
    void openResult(focusResultId);
  }, [live, focusResultId]);

  function selectResult(resultId: number | null) {
    setSelectedResultId(resultId);
    onResultSelectionChange?.(resultId);
  }

  async function runEvaluation() {
    if (!live) { notify(t("Production experiment controls are locked. Compare published snapshots instead."), "warning", "prod-eval"); return; }
    if (!canRun || busy) return;
    setBusy(true);
    setSubmissionError("");
    try {
      const job = await queueEvaluation(evaluationRequest);
      setJobs((current) => [job, ...current]);
      setSelectedJobId(job.job_id);
      selectResult(null); setResultDetail(null); setSetupOpen(false);
      onRefreshJobs();
      notify(t("Evaluation queued."), "success", "evaluation-queued");
    } catch (reason) {
      setSubmissionError(reason instanceof Error ? reason.message : t("Evaluation failed."));
      notify(reason instanceof Error ? reason.message : t("Evaluation failed."), "error", "evaluation");
    } finally {
      setBusy(false);
    }
  }

  async function loadComparison(candidate: number, baseline: number) {
    if (!live) return;
    const requestId = ++comparisonRequestRef.current;
    try {
      setComparison(null);
      setCompareIds([baseline, candidate]);
      const loaded = await compareEvaluations(candidate, baseline);
      if (requestId === comparisonRequestRef.current) { setComparison(loaded); changeTab("compare"); }
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : t("Comparison failed."), "error", "comparison");
    }
  }

  async function openResult(resultId: number) {
    if (!live) return;
    const requestId = ++resultRequestRef.current;
    selectResult(resultId);
    setResultDetail(null); setResultError("");
    try {
      const detail = await getEvaluationResult(resultId);
      if (requestId === resultRequestRef.current) setResultDetail(detail);
    } catch (reason) {
      if (requestId !== resultRequestRef.current) return;
      const message = reason instanceof Error ? reason.message : t("Evaluation detail could not be loaded.");
      setResultError(message);
      notify(message, "error", "evaluation-detail");
    }
  }

  function applySelectedResult() {
    const job = jobs.find((item) => item.result_ids.includes(selectedResultId ?? -1));
    if (!job || selectedResultId === null) return;
    onApplyProfile(job.request.profile ?? DEFAULT_PROFILE, `${job.request.suite_id}:${selectedResultId}`);
  }

  async function newGoldenDraft() {
    if (!live || goldenBusy) return;
    if (goldenDirty && !window.confirm(t("Discard unsaved question changes?"))) return;
    setGoldenBusy(true);
    try {
      const created = await createGoldenDraft(suiteId, selectedGoldenRevision);
      setGoldenRevisions((current) => [created, ...current]);
      setSelectedGoldenRevision(created.revision_id);
      resetGoldenSelection();
      notify(t("Golden draft v{p0} created.", { p0: created.version }), "success", "golden-draft");
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : t("Golden draft could not be created."), "error", "golden-draft");
    } finally { setGoldenBusy(false); }
  }

  function openGoldenCase(caseValue: Record<string, unknown>) {
    if (goldenDirty && !window.confirm(t("Discard unsaved question changes?"))) return;
    setSavedGoldenJson(JSON.stringify(caseValue, null, 2));
    setGoldenError("");
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
    if (!revision || revision.status === "published" || !selectedGoldenCase || goldenBusy) return;
    setGoldenBusy(true);
    try {
      const value = JSON.parse(goldenCaseJson) as Record<string, unknown>;
      const updated = await saveGoldenCase(revision.revision_id, selectedGoldenCase, revision.sha256, value);
      setGoldenRevisions((current) => current.map((item) => item.revision_id === updated.revision_id ? updated : item));
      setSavedGoldenJson(goldenCaseJson); setGoldenError("");
      notify(t("Golden case saved."), "success", "golden-save");
    } catch (reason) {
      setGoldenError(reason instanceof Error ? reason.message : t("Golden case could not be saved."));
      notify(reason instanceof Error ? reason.message : t("Golden case could not be saved."), "error", "golden-save");
    } finally { setGoldenBusy(false); }
  }

  async function changeGoldenStatus(action: "validate" | "publish") {
    const revision = goldenRevisions.find((item) => item.revision_id === selectedGoldenRevision);
    if (!revision || goldenDirty || goldenBusy) return;
    setGoldenBusy(true);
    try {
      const updated = await transitionGoldenRevision(revision.revision_id, action, revision.sha256);
      setGoldenRevisions((current) => current.map((item) => item.revision_id === updated.revision_id ? updated : item));
      notify(t(action === "validate" ? "Golden revision validated." : "Golden revision published."), "success", `golden-${action}`);
    } catch (reason) {
      setGoldenError(reason instanceof Error ? reason.message : String(reason));
      notify(reason instanceof Error ? reason.message : t(action === "validate" ? "Golden revision could not be validated." : "Golden revision could not be published."), "error", `golden-${action}`);
    } finally { setGoldenBusy(false); }
  }

  async function freezeSnapshot() {
    if (!live || selectedResultId === null || !snapshotLabel.trim()) return;
    try {
      const identity = resultDetail?.config.admin_identity;
      const goldenSha = typeof identity === "object" && identity !== null ? (identity as Record<string, unknown>).golden_sha256 : resultDetail?.config.golden_sha256;
      const revision = goldenRevisions.find((item) => item.status === "published" && item.sha256 === goldenSha);
      const created = await createSnapshot({ label: snapshotLabel.trim(), eval_result_id: selectedResultId, golden_revision_id: revision?.status === "published" ? revision.revision_id : null, public: false });
      setSnapshots((current) => [created, ...current]);
      setSnapshotLabel("");
      notify(t("Evaluation snapshot created."), "success", "snapshot-create");
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : t("Snapshot could not be created."), "error", "snapshot-create");
    }
  }

  async function loadSnapshotComparison() {
    if (!snapshotIds[0] || !snapshotIds[1] || snapshotIds[0] === snapshotIds[1]) return;
    setSnapshotComparison(null);
    const requestId = ++snapshotComparisonRequestRef.current;
    try {
      const loaded = await compareSnapshots(snapshotIds[0], snapshotIds[1], live);
      if (requestId === snapshotComparisonRequestRef.current) setSnapshotComparison(loaded);
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : t("Snapshots could not be compared."), "error", "snapshot-compare");
    }
  }

  async function toggleSnapshot(snapshot: PublishedSnapshot) {
    if (!live) return;
    try {
      const updated = await setSnapshotVisibility(snapshot.snapshot_id, !snapshot.public);
      setSnapshots((current) => current.map((item) => item.snapshot_id === updated.snapshot_id ? updated : item));
      notify(updated.public ? t("Snapshot published.") : t("Snapshot hidden."), "success", "snapshot-visibility");
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : t("Snapshot visibility could not change."), "error", "snapshot-visibility");
    }
  }

  const selectedSuite = suites.find((suite) => suite.suite_id === suiteId) ?? suites[0];
  const activeGoldenRevision = goldenRevisions.find((item) => item.revision_id === selectedGoldenRevision) ?? null;
  const activeGoldenCases = activeGoldenRevision?.payload ?? goldenCanonical?.payload ?? [];
  const visibleGoldenCases = activeGoldenCases.filter((item) => `${String(item.id)} ${String(item.question)} ${t(String(item.category))} ${t(String(item.facet))} ${Array.isArray(item.tags) ? item.tags.join(" ") : ""}`.toLowerCase().includes(goldenCaseQuery.toLowerCase())).toSorted((left, right) => String(left[goldenCaseSort] ?? "").localeCompare(String(right[goldenCaseSort] ?? ""), undefined, { numeric: true }));
  const goldenReadOnly = !activeGoldenRevision || activeGoldenRevision.status === "published";
  const goldenScoreResult = resultDetail?.suite === suiteId ? resultDetail : null;
  const canRun = live && ready && !!selectedSuite?.source_ready;
  const selectedJob = jobs.find((job) => job.job_id === selectedJobId) ?? jobs.find((job) => job.result_ids.includes(selectedResultId ?? -1)) ?? null;
  const selectedOperatorJob = jobBoard.jobs.find((job) => job.job_id === selectedJobId);
  const baselineJob = jobs.find((job) => job.result_ids.includes(compareIds[0] ?? -1));
  const candidateJob = jobs.find((job) => job.result_ids.includes(compareIds[1] ?? -1));
  const resultMismatch = baselineJob && candidateJob && baselineJob.request.suite_id !== candidateJob.request.suite_id;
  const baselineSnapshot = snapshots.find((snapshot) => snapshot.snapshot_id === snapshotIds[0]);
  const candidateSnapshot = snapshots.find((snapshot) => snapshot.snapshot_id === snapshotIds[1]);

  useEffect(() => {
    if (selectedJob?.status === "succeeded" && selectedJob.result_id && !selectedJob.result_ids.includes(selectedResultId ?? -1)) void openResult(selectedJob.result_id);
  }, [selectedJob?.job_id, selectedJob?.status, selectedJob?.result_id]);

  function chooseJob(job: EvaluationJob) {
    setSelectedJobId(job.job_id);
    if (job.job_id === selectedJobId && job.result_id) {
      if (resultDetail?.result_id !== job.result_id) void openResult(job.result_id);
    } else { resultRequestRef.current += 1; selectResult(null); setResultDetail(null); }
  }

  async function cancelSelectedJob() {
    if (!selectedOperatorJob?.can_cancel) return;
    try { await cancelOperatorJob(selectedOperatorJob.job_id); onRefreshJobs(); }
    catch (reason) { notify(String(reason), "error", "evaluation-cancel"); }
  }

  const suiteSelect = (helpId: string) => <label data-help={helpId}>{t("Golden suite")}<select disabled={goldenBusy} value={suiteId} onChange={(event) => selectSuite(event.target.value as SuiteId)}>{suites.map((suite) => <option key={suite.suite_id} value={suite.suite_id}>{suite.label}</option>)}</select></label>;
  const revisionSelect = (helpId: string) => <label data-help={helpId}>{t("Golden revision")}<select disabled={goldenBusy} value={selectedGoldenRevision ?? ""} onChange={(event) => selectRevision(event.target.value ? Number(event.target.value) : null)}><option value="">{t("Canonical JSON · read-only")}</option>{goldenRevisions.map((revision) => <option key={revision.revision_id} value={revision.revision_id}>{t("v")}{revision.version} · {t(revision.status)}</option>)}</select></label>;
  const lockedRuns = (message: string) => <div className="empty-state"><p>{t(message)}</p><button className="button" type="button" onClick={() => changeTab("snapshots")}>{t("Open Snapshots")}</button></div>;

  return (
    <section className="lab-shell measure-workspace">
      <header className="page-heading">
        <div><p className="eyebrow">{t("Measure")}</p><h1>{t("Measure retrieval before trusting it.")}</h1></div>
        <div className="page-badges">{environment && <span className="mode-badge">{deploymentLabel(environment)}</span>}<span className={`mode-badge ${live ? "live" : ""}`}>{live ? t("Local operator") : t("Read-only portfolio")}</span></div>
      </header>
      <nav className="lab-tabs workflow-tabs measure-tab-strip" aria-label={t("Measure sections")}>
        <div className="measure-tab-group measure-workflow-group" role="group" aria-label={t("Evaluation workflow")}>
          {([["playground", "Search trial"], ["golden", "Golden dataset"], ["runs", "Run evaluation"], ["compare", "Compare results"]] as const).map(([id, label], index) => <button key={id} type="button" aria-pressed={tab === id || (id === "compare" && tab === "snapshots")} onClick={() => changeTab(id)}><span className="measure-step-chip" aria-hidden="true">{index + 1}</span>{t(label)}</button>)}
        </div>
        <div className="measure-tab-group measure-management-group" role="group" aria-label={t("Manage")}>
          <span className="measure-management-caption" aria-hidden="true">{t("Manage")}</span>
          <button type="button" aria-pressed={tab === "presets"} onClick={() => changeTab("presets")}>{t("Presets")}</button>
          {live && <button type="button" aria-pressed={tab === "defaults"} title={locale === "ko" ? "개발 모드 전용" : "DEV only"} onClick={() => changeTab("defaults")}>{t("Defaults")}<span aria-hidden="true"><DevelopmentBadge locale={locale} compact /></span></button>}
        </div>
      </nav>
      <div className="workflow-section-heading" data-help={tab === "presets" ? "measure.presets.manage" : undefined}><h2>{tab === "presets" ? t("Retrieval presets") : tab === "playground" ? t("Search trial") : tab === "golden" ? t("Prepare a golden dataset") : tab === "runs" ? t("Run evaluation") : tab === "defaults" ? t("Evaluation settings") : tab === "snapshots" ? t("Saved search snapshots") : t("Compare evaluation results")}</h2>{live && ["golden", "runs", "defaults"].includes(tab) && <DevelopmentBadge locale={locale} compact />}<WorkflowHelp screen={`measure.${tab}`} capabilities={capabilities} publicPreview={publicPreview} /></div>
      <p className="data-origin">{t(live ? "Live workspace · results come from recorded runs" : "Read-only workspace · published snapshots come from the server")}</p>
      <p className="workflow-intro">{tab === "presets" ? t("Create reusable search settings, then select them in a conversation.") : tab === "playground" ? t("Try one question and inspect its evidence before evaluating a whole dataset.") : tab === "golden" ? t("Select a question to inspect it. Create a draft to edit, save your changes, then validate before publishing.") : tab === "runs" ? t("Choose the questions and search settings to measure. A run records what was tested and how well the evidence was retrieved.") : tab === "defaults" ? t("Defaults apply to the next new evaluation. Existing conversations and results are unchanged.") : tab === "snapshots" ? t("A snapshot preserves search data and an evaluation result so you can reuse a known configuration later.") : t("Choose a baseline and a candidate. Read how evidence hits, rank, and latency changed before saving a snapshot.")}</p>
      {(tab === "compare" || tab === "snapshots") && <nav className="result-tabs"><button type="button" aria-pressed={tab === "compare"} onClick={() => changeTab("compare")}>{t("Compare results")}</button><button type="button" aria-pressed={tab === "snapshots"} onClick={() => changeTab("snapshots")}>{t("Saved snapshots")}</button></nav>}


      {tab === "presets" && <RetrievalPresetManager profile={profile} onApply={onApplyProfile} canApply={capabilities?.can_change_custom_retrieval ?? live} />}
      {live && <RetainedPanel active={tab === "defaults"}><ExperimentDefaultsForm profile={profile} onSaved={(defaults) => { setExperimentDefaults(defaults); setSuiteId(defaults.suite_id); setMode(defaults.mode); setSelectedGoldenRevision(defaults.golden_revision_id); setSnapshotIds([defaults.baseline_snapshot_id, defaults.snapshot_id]); }} /></RetainedPanel>}

      <RetainedPanel active={tab === "playground"}><Playground live={live} profile={profile} onProfileChange={onProfileChange} onOpenSnapshots={() => changeTab("snapshots")} /></RetainedPanel>

      <RetainedPanel active={tab === "golden"} className="golden-workspace evaluation-golden">
        <section className="surface form-stack golden-controls evaluation-golden-controls">
          {live && suiteSelect("measure.golden.suite")}
          {selectedSuite && <div className="provenance"><strong>{t("{count} cases", { count: selectedSuite.case_count.toLocaleString(locale) })}</strong><span>{t(selectedSuite.curation_status)}</span><span>{t(selectedSuite.approval_status)}</span><span>{t("human_verified=false")}</span>{!selectedSuite.source_ready && <span className="danger">{t("Sources unavailable")}</span>}</div>}
          {live && <>
            {revisionSelect("measure.golden.revision")}
            <div className="golden-file"><span>{t("Canonical file")}</span><strong>{goldenCanonical?.filename ?? t("Loading…")}</strong><code>{goldenCanonical?.sha256.slice(0, 12) ?? "—"}</code><button className="button ghost" type="button" disabled={!goldenCanonical} aria-expanded={sourceJsonOpen} onClick={() => setSourceJsonOpen((open) => !open)}>{t("View source JSON")}</button></div>
            <div className="action-row golden-actions">
              <button className="button primary" type="button" disabled={goldenBusy || !goldenCanonical} onClick={() => void newGoldenDraft()}><Plus size={15} />{t("Create draft")}</button>
              <button className="button" type="button" disabled={!activeGoldenRevision || activeGoldenRevision.status === "published" || goldenDirty || goldenBusy} onClick={() => void changeGoldenStatus("validate")}>{t("Validate")}</button>
              <button className="button" type="button" disabled={activeGoldenRevision?.status !== "validated" || goldenDirty || goldenBusy} onClick={() => void changeGoldenStatus("publish")}>{t("Publish JSON")}</button>
              <button className="button ghost" type="button" onClick={prepareEvaluation}>{t("Prepare evaluation with this dataset")}</button>
            </div>
            <p className="helper">{goldenDirty ? t("Save question changes before validating or publishing.") : t("Canonical and published revisions are immutable. Create a draft before editing questions or source spans.")}</p>
            {sourceJsonOpen && goldenCanonical && <div className="source-json"><h3>{t("Source JSON · read-only")}</h3><pre>{JSON.stringify(goldenCanonical.payload, null, 2)}</pre></div>}
          </>}
          {!live && <p className="helper">{t("Golden suites are edited on the local operator build. Compare stored published snapshots instead.")}</p>}
        </section>
        <section className={`surface golden-manager ${selectedGoldenCase ? "has-selection" : ""}`} data-help="measure.golden.questions">
          <div className="surface-heading"><div><h2>{live ? t("Golden questions") : t("Latest comparison")}</h2>{live && <p className="helper">{activeGoldenRevision ? t("Revision v{p0} · {p1}", { p0: activeGoldenRevision.version, p1: t(activeGoldenRevision.status) }) : t("Canonical JSON · read-only")}{goldenScoreResult ? t(" · scores from result #{p0}", { p0: goldenScoreResult.result_id }) : t(" · no evaluation result selected")}</p>}</div></div>
          {live ? <><div className="golden-table-tools"><input aria-label={t("Search golden cases")} placeholder={t("Search ID, question, category, facet, or tag")} value={goldenCaseQuery} onChange={(event) => setGoldenCaseQuery(event.target.value)} /><select aria-label={t("Sort golden cases")} value={goldenCaseSort} onChange={(event) => setGoldenCaseSort(event.target.value)}><option value="id">{t("ID")}</option><option value="question">{t("Question")}</option><option value="category">{t("Category")}</option><option value="facet">{t("Facet")}</option></select></div><div className="golden-table-scroll"><table><thead><tr><th>{t("ID")}</th><th>{t("Question")}</th><th>{t("Category")}</th><th>{t("Facet")}</th><th>{t("Tags")}</th>{goldenScoreResult && <><th>{t("Eval")}</th><th>{t("First rank")}</th><th>{t("RR")}</th></>}</tr></thead><tbody>{visibleGoldenCases.map((item) => { const score = goldenScoreResult?.cases.find((value) => value.case_id === item.id); const rank = score?.first_relevant_rank ?? null; return <tr key={String(item.id)} tabIndex={0} onClick={() => openGoldenCase(item)} onKeyDown={(event) => { if (event.key === "Enter") openGoldenCase(item); }} className={selectedGoldenCase === String(item.id) ? "selected" : ""}><td><button type="button" className="row-detail" onClick={(event) => { event.stopPropagation(); openGoldenCase(item); }}>{String(item.id)}</button></td><td>{String(item.question)}</td><td>{t(String(item.category))}</td><td>{t(String(item.facet))}</td><td>{Array.isArray(item.tags) && item.tags.length ? item.tags.join(", ") : "—"}</td>{goldenScoreResult && <><td>{score ? rank ? t("hit") : t("miss") : t("not run")}</td><td>{rank ?? "—"}</td><td>{score ? (rank ? 1 / rank : 0).toLocaleString(locale, { minimumFractionDigits: 3, maximumFractionDigits: 3, useGrouping: false }) : "—"}</td></>}</tr>; })}</tbody></table></div>{!visibleGoldenCases.length && <p className="helper">{t("No questions match this filter.")}</p>}{selectedGoldenCase && <div className="golden-editor">{goldenDirty && <p role="status">{t("Unsaved question changes")}</p>}{goldenError && <div role="alert" className="notice error"><p>{t("The golden dataset could not be updated.")}</p><p>{goldenError}</p>{["question", "reference_answer", "source_sha256", "start_char", "end_char"].filter((field) => goldenError.includes(field)).map((field) => <button className="button ghost" type="button" key={field} onClick={() => document.querySelector<HTMLElement>(`[data-golden-field="${field}"]`)?.focus()}>{t("Check field")}: {field}</button>)}</div>}<div className="golden-editor-heading"><div><h3>{selectedGoldenCase}</h3><p>{goldenReadOnly ? t("Read-only source") : t("Editable draft")}</p></div><span className={`job-status ${goldenReadOnly ? "" : "running"}`}>{goldenReadOnly ? t("locked") : t("draft")}</span></div>{parsedGoldenCase && goldenReadOnly && <div className="golden-source-detail">
            <div><h4>{t("Question")}</h4><p>{String(parsedGoldenCase.question ?? "")}</p></div>
            <div><h4>{t("Reference answer")}</h4><p>{String(parsedGoldenCase.reference_answer ?? "—")}</p></div>
            <dl className="evaluation-metadata"><div><dt>{t("Category")}</dt><dd>{t(String(parsedGoldenCase.category ?? "—"))}</dd></div><div><dt>{t("Facet")}</dt><dd>{t(String(parsedGoldenCase.facet ?? "—"))}</dd></div><div><dt>{t("Expected label")}</dt><dd>{t(String(parsedGoldenCase.expected_label ?? "—"))}</dd></div><div><dt>{t("Tags")}</dt><dd>{Array.isArray(parsedGoldenCase.tags) ? parsedGoldenCase.tags.join(", ") || "—" : "—"}</dd></div></dl>
            {typeof parsedGoldenCase.note === "string" && parsedGoldenCase.note && <div><h4>{t("Reviewer note")}</h4><p>{parsedGoldenCase.note}</p></div>}
            <div><h4>{t("Answer source spans")}</h4>{goldenAnswers(parsedGoldenCase).map((answer, index) => <article className="golden-source-span" key={index}><strong>{String(answer.doc_id)}</strong><span>{t("Start char")}: {String(answer.start_char)} · {t("End char")}: {String(answer.end_char)}</span><code>{String(answer.source_sha256 ?? "")}</code></article>)}{!goldenAnswers(parsedGoldenCase).length && <p className="helper">{t("Absent cases intentionally have no source span.")}</p>}</div>
            <details><summary>{t("Single-case JSON")}</summary><pre>{savedGoldenJson}</pre></details>
          </div>}{parsedGoldenCase && !goldenReadOnly && <div className="form-stack"><label>{t("Question")}<textarea disabled={goldenReadOnly} data-golden-field="question" value={String(parsedGoldenCase.question ?? "")} onChange={(event) => patchGoldenCase("question", event.target.value)} /></label><label>{t("Reference answer")}<textarea disabled={goldenReadOnly} data-golden-field="reference_answer" value={String(parsedGoldenCase.reference_answer ?? "")} onChange={(event) => patchGoldenCase("reference_answer", event.target.value)} /></label><div className="profile-grid"><label>{t("Category")}<select disabled={goldenReadOnly} value={String(parsedGoldenCase.category ?? "simple_lookup")} onChange={(event) => patchGoldenCase("category", event.target.value)}><option value="simple_lookup">{t("Simple lookup")}</option><option value="exact_number">{t("Exact number")}</option><option value="multi_hop">{t("Multi-hop")}</option><option value="absent">{t("Absent")}</option></select></label><label>{t("Facet")}<select disabled={goldenReadOnly} value={String(parsedGoldenCase.facet ?? "factual")} onChange={(event) => patchGoldenCase("facet", event.target.value)}><option value="factual">{t("Factual")}</option><option value="comparison">{t("Comparison")}</option><option value="risk">{t("Risk")}</option><option value="policy">{t("Policy")}</option><option value="numeric">{t("Numeric")}</option></select></label><label>{t("Expected label")}<select disabled={goldenReadOnly} value={String(parsedGoldenCase.expected_label ?? "SUPPORTED")} onChange={(event) => patchGoldenCase("expected_label", event.target.value)}><option value="SUPPORTED">{t("SUPPORTED")}</option><option value="NOT_IN_DOCS">{t("NOT_IN_DOCS")}</option></select></label><label>{t("Tags")}<input disabled={goldenReadOnly} value={Array.isArray(parsedGoldenCase.tags) ? parsedGoldenCase.tags.join(" ") : ""} onChange={(event) => patchGoldenCase("tags", event.target.value.split(/[\s,]+/).filter(Boolean))} placeholder={t("demo-hero numeric")} /></label></div><label>{t("Reviewer note")}<textarea disabled={goldenReadOnly} value={String(parsedGoldenCase.note ?? "")} onChange={(event) => patchGoldenCase("note", event.target.value)} /></label><div className="golden-spans"><div className="surface-heading"><h3>{t("Answer source spans")}</h3><button className="button ghost" type="button" disabled={goldenReadOnly} onClick={addGoldenAnswer}>{t("Add span")}</button></div>{goldenAnswers(parsedGoldenCase).map((answer, index) => <article key={`${String(answer.doc_id)}:${index}`}><div className="golden-span-heading"><strong>{t("Span")}{" "}{index + 1}</strong><button className="button ghost" type="button" disabled={goldenReadOnly} onClick={() => removeGoldenAnswer(index)}>{t("Remove")}</button></div><div className="profile-grid"><label>{t("Document ID")}<input disabled={goldenReadOnly} value={String(answer.doc_id ?? "")} onChange={(event) => patchGoldenAnswer(index, "doc_id", event.target.value)} /></label><label>{t("Start char")}<input disabled={goldenReadOnly} type="number" min={0} data-golden-field="start_char" value={Number(answer.start_char ?? 0)} onChange={(event) => patchGoldenAnswer(index, "start_char", Number(event.target.value))} /></label><label>{t("End char")}<input disabled={goldenReadOnly} type="number" min={1} data-golden-field="end_char" value={Number(answer.end_char ?? 1)} onChange={(event) => patchGoldenAnswer(index, "end_char", Number(event.target.value))} /></label><label>{t("Source SHA-256")}<input disabled={goldenReadOnly} data-golden-field="source_sha256" value={String(answer.source_sha256 ?? "")} onChange={(event) => patchGoldenAnswer(index, "source_sha256", event.target.value)} /></label></div></article>)}{!goldenAnswers(parsedGoldenCase).length && <p className="helper">{t("Absent cases intentionally have no source span.")}</p>}</div></div>}{!goldenReadOnly && <div className="form-stack"><details><summary>{t("JSON and changes")}</summary><h4>{t("Saved version")}</h4><pre>{savedGoldenJson}</pre><h4>{t("Current draft")}</h4><label>{t("Single-case JSON")}<textarea disabled={goldenReadOnly} className="golden-json" value={goldenCaseJson} onChange={(event) => setGoldenCaseJson(event.target.value)} spellCheck={false} /></label></details><button className="button primary" type="button" disabled={goldenReadOnly || !parsedGoldenCase || !goldenDirty || goldenBusy} onClick={() => void saveSelectedGoldenCase()}>{t("Save case")}</button></div>}</div>}</> : (comparison?.metrics ?? []).map((metric) => <div className="metric-row" key={metric.name}><span>{metric.name}</span><strong>{metric.candidate.toLocaleString(locale, { minimumFractionDigits: 3, maximumFractionDigits: 3, useGrouping: false })}</strong><em className={metric.delta >= 0 ? "positive" : "negative"}>{metric.delta >= 0 ? "+" : ""}{metric.delta.toLocaleString(locale, { minimumFractionDigits: 3, maximumFractionDigits: 3, useGrouping: false })}</em></div>)}
          <p className="helper">{t("Hit, first rank, and reciprocal rank measure retrieval—not final-answer factuality.")}</p>
        </section>
      </RetainedPanel>

      <RetainedPanel active={tab === "runs"}>{live ? <div className="panel-stack run-workspace evaluation-runs">
        <section className="surface">
          <div className="surface-heading"><div><h2 data-help="measure.runs.results">{t("Evaluation runs")}</h2><p className="helper">{t("Select a run to inspect its progress, settings, and recorded results.")}</p></div><button className="button primary" type="button" onClick={() => setSetupOpen(true)}><Plus size={15} />{t("New evaluation")}</button></div>
          {selectedResultId !== null ? <button className="button" type="button" onClick={() => { resultRequestRef.current += 1; selectResult(null); setSelectedJobId(null); setResultDetail(null); setResultError(""); }}>{t("Back to evaluations")}</button> : <>
          {jobsLoading && <p role="status">{t("Loading evaluations…")}</p>}
          {jobsError && <div role="alert" className="notice error"><p>{t("Evaluations could not be loaded.")}</p><p>{jobsError}</p><button className="button" type="button" onClick={() => void refreshJobs()}>{t("Retry")}</button>{onOpenPreparation && <button className="button" type="button" onClick={() => onOpenPreparation("setup")}>{t("Open setup diagnosis")}</button>}</div>}
          <div className="evaluation-run-list">{jobs.map((job) => <article className={`job-row ${selectedJobId === job.job_id ? "selected" : ""}`} key={job.job_id}>
            <div className="job-select"><input type="radio" name="evaluation-result" aria-label={t("Select {p0}", { p0: job.job_id })} disabled={job.status !== "succeeded" || !job.result_id} checked={selectedResultId !== null && selectedResultId === job.result_id} onChange={() => chooseJob(job)} /><button className="row-detail" type="button" aria-pressed={selectedJobId === job.job_id} onClick={() => chooseJob(job)}><strong>{job.request.suite_id} · {t(job.request.mode)}</strong><p>{job.message}</p></button></div>
            <div className="evaluation-run-state"><span className={`job-status ${job.status}`}>{t(job.status)}</span><small>{job.total ? `${job.current} / ${job.total}` : t(job.stage)}</small><time dateTime={job.created_at}>{new Date(job.created_at).toLocaleString(locale)}</time></div>
          </article>)}</div>
          {!jobsLoading && !jobsError && !jobs.length && <div className="empty-state"><Beaker size={24} /><p>{t("No evaluations yet. Create a new evaluation when your dataset and index are ready.")}</p></div>}
          </>}
        </section>
        {selectedResultId !== null && !resultDetail && <section className="surface"><h2>{t("Result details")} · #{selectedResultId}</h2>{resultError ? <div role="alert" className="notice error"><p>{t("Evaluation detail could not be loaded.")}</p><p>{resultError}</p><button className="button" type="button" onClick={() => void openResult(selectedResultId)}>{t("Retry")}</button>{onOpenPreparation && <button className="button" type="button" onClick={() => onOpenPreparation("setup")}>{t("Open setup diagnosis")}</button>}</div> : <p role="status">{t("Loading evaluation result…")}</p>}</section>}
        {selectedJob && <section className="surface evaluation-job-detail" aria-live="polite"><div className="surface-heading"><div><p className="eyebrow">{t("Selected evaluation")}</p><h2>{selectedJob.request.suite_id}</h2></div><span className={`job-status ${selectedOperatorJob?.status ?? selectedJob.status}`}>{t(selectedOperatorJob?.status ?? selectedJob.status)}</span></div>
          <dl className="evaluation-metadata"><div><dt>{t("Job ID")}</dt><dd><code>{selectedJob.job_id}</code></dd></div><div><dt>{t("Golden revision")}</dt><dd>{selectedJob.request.golden_revision_id ? `#${selectedJob.request.golden_revision_id}` : t("Canonical JSON")}</dd></div><div><dt>{t("Retrieval profile")}</dt><dd>{profileSummary(selectedJob.request.profile ?? DEFAULT_PROFILE, locale)}</dd></div><div><dt>{t("Run mode")}</dt><dd>{t(selectedJob.request.mode)}</dd></div></dl>
          <p>{selectedOperatorJob?.message ?? selectedJob.message}</p>
          {(selectedJob.status === "running" || selectedJob.status === "queued") && <div className="evaluation-progress"><progress aria-label={t("Evaluation progress")} value={selectedJob.total ? selectedJob.current : undefined} max={selectedJob.total ?? undefined} /><span>{t(selectedJob.stage)}{selectedJob.total ? ` · ${selectedJob.current} / ${selectedJob.total}` : ""}</span></div>}
          {selectedOperatorJob?.error_code && <div className="notice error" role="alert"><p>{selectedOperatorJob.error_code}</p>{onOpenPreparation && <button className="button" type="button" onClick={() => onOpenPreparation(preparationErrorTarget(selectedOperatorJob.error_code))}>{t("Open preparation step")}</button>}</div>}
          {selectedOperatorJob?.can_cancel && <button className="button" type="button" onClick={() => void cancelSelectedJob()}>{t("Cancel job")}</button>}
          <details><summary>{t("Request settings")}</summary><pre>{JSON.stringify(selectedJob.request, null, 2)}</pre></details>
          {selectedJob.result_ids.length > 1 && <div className="job-arms">{selectedJob.result_ids.map((resultId) => <button key={resultId} className="button" type="button" aria-pressed={selectedResultId === resultId} onClick={() => void openResult(resultId)}>{t("Result")} #{resultId}</button>)}</div>}
        </section>}
        {resultDetail && <section className="surface detail-panel" data-help="measure.runs.result_detail">
          <div className="surface-heading"><h2>{t("Result details")} · #{resultDetail.result_id}</h2><div className="action-row"><button className="button" type="button" data-help="measure.runs.use_selected" disabled={selectedResultId === null} onClick={applySelectedResult}>{t("Use selected set")}</button>{selectedJob?.baseline_id && <button className="button" type="button" onClick={() => void loadComparison(resultDetail.result_id, selectedJob.baseline_id!)}>{t("Compare")}</button>}</div></div>
          <p className="helper">{resultDetail.suite} · <time dateTime={resultDetail.created_at}>{new Date(resultDetail.created_at).toLocaleString(locale)}</time></p>
          <div className="metric-grid compact">{Object.entries(resultDetail.metrics).map(([name, value]) => <Metric key={name} icon={<Beaker />} label={name} value={value.toLocaleString(locale, { minimumFractionDigits: 3, maximumFractionDigits: 3, useGrouping: false })} />)}</div>
          <details><summary>{t("Recorded configuration")}</summary><pre>{JSON.stringify(resultDetail.config, null, 2)}</pre></details><h3>{t("Cases")}</h3>{resultDetail.cases.slice(0, 10).map((item) => <article className="case-row" key={item.case_id}><div><strong>{item.case_id}</strong><p>{item.question}</p></div><span>{item.first_relevant_rank ? t("rank {p0}", { p0: item.first_relevant_rank }) : t("miss")}</span></article>)}
          <div className="evaluation-save"><label>{t("Snapshot label")}<input value={snapshotLabel} onChange={(event) => setSnapshotLabel(event.target.value)} placeholder={t("BM25 tuned baseline")} /></label><button className="button" type="button" data-help="measure.snapshots.freeze" title={locale === "ko" ? "개발 모드 전용" : "DEV only"} disabled={selectedResultId === null || !snapshotLabel.trim()} onClick={() => void freezeSnapshot()}>{t("Save result as snapshot")}<span aria-hidden="true"><DevelopmentBadge locale={locale} compact /></span></button></div>
        </section>}
        {active && tab === "runs" && setupOpen && createPortal(<div className="evaluation-setup-backdrop" onClick={(event) => { if (event.target === event.currentTarget && !busy) setSetupOpen(false); }}><section ref={setupRef} className="surface form-stack evaluation-setup" role="dialog" aria-modal="true" aria-labelledby="new-evaluation-heading" onKeyDown={(event) => { if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); if (!busy) setSetupOpen(false); } }}>
          <div className="surface-heading"><div><p className="eyebrow">{t("Evaluation setup")}</p><h2 id="new-evaluation-heading">{t("New evaluation")}</h2></div><button className="button icon" type="button" aria-label={t("Close evaluation setup")} disabled={busy} onClick={() => setSetupOpen(false)}><X size={18} /></button></div>
          <NotificationOutlet priority={50} />
          {suiteSelect("measure.runs.suite")}{revisionSelect("measure.runs.revision")}
          <dl className="evaluation-metadata"><div><dt>{t("Index")}</dt><dd>{t(mode === "quick" ? "Current index" : "Isolated corpus")}</dd></div><div><dt>{t("Readiness")}</dt><dd>{t(ready ? "Ready" : "Not ready")}</dd></div><div><dt>{t("Cases")}</dt><dd>{selectedSuite?.case_count ?? "—"}</dd></div><div><dt>{t("Golden revision")}</dt><dd>{activeGoldenRevision ? `v${activeGoldenRevision.version} · ${t(activeGoldenRevision.status)}` : t("Canonical JSON · read-only")}</dd></div></dl>
          <fieldset className="playground-core" data-help="measure.runs.profile"><legend>{t("Core search settings")}</legend><ProfileFields profile={profile} onChange={onProfileChange} helpPrefix="measure.runs" fields="core" /></fieldset>
          <details><summary>{t("Advanced evaluation options")}</summary><label data-help="measure.runs.mode">{t("Run mode")}<select value={mode} onChange={(event) => setMode(event.target.value as "quick" | "matrix")}><option value="quick">{t("Quick · current index")}</option><option value="matrix">{t("Matrix · isolated corpus")}</option></select></label>{mode === "matrix" && <label data-help="measure.runs.chunk_targets">{t("Chunk targets (tokens)")}<input value={chunkTargets} onChange={(event) => setChunkTargets(event.target.value)} placeholder="1024 2048" /></label>}<ProfileFields profile={profile} onChange={onProfileChange} helpPrefix="measure.runs" fields="advanced" /></details>
          <p className="helper">{t("Retrieval profile ·")} {profileSummary(profile, locale)}</p>
          {submissionError && <div className="notice error" role="alert"><p>{submissionError}</p><button className="button" type="button" disabled={busy || !canRun} onClick={() => void runEvaluation()}>{t("Retry")}</button>{onOpenPreparation && <button className="button" type="button" onClick={() => onOpenPreparation("setup")}>{t("Open setup diagnosis")}</button>}</div>}
          {!ready && <div className="notice"><p>{t("Corpus not ready. Inspect the earliest verified prerequisite.")}</p>{onOpenPreparation && <button className="button" type="button" onClick={() => onOpenPreparation(preparationTarget(readiness))}>{t("Open preparation step")}</button>}</div>}{selectedSuite && !selectedSuite.source_ready && <div className="notice error"><p>{t("Sources unavailable")}: {selectedSuite.source_error}</p>{onOpenPreparation && <button className="button" type="button" onClick={() => onOpenPreparation(preparationErrorTarget(selectedSuite.source_error_code))}>{t("Open preparation step")}</button>}</div>}
          <div className="action-row"><button className="button primary" type="button" data-help="measure.runs.queue" disabled={!canRun || busy} onClick={() => void runEvaluation()}><Play size={15} />{busy ? t("Queueing…") : t("Queue evaluation")}</button><button className="button" type="button" disabled={busy} onClick={() => setSetupOpen(false)}>{t("Cancel")}</button></div>
        </section></div>, document.body)}
      </div> : lockedRuns("Runs happen on the local operator build.")}</RetainedPanel>

      <RetainedPanel active={tab === "compare"}><div className="panel-stack" data-help="measure.compare.overview">
        {live && <section className="surface comparison-picker"><label>{t("Baseline")}<select value={compareIds[0] ?? ""} onChange={(event) => { comparisonRequestRef.current += 1; setComparison(null); setCompareIds([Number(event.target.value) || null, compareIds[1]]); }}><option value="">{t("Select result")}</option>{jobs.filter((job) => job.status === "succeeded").flatMap((job) => job.result_ids.map((id) => <option key={id} value={id}>#{id} · {job.request.suite_id}</option>))}</select></label><label>{t("Candidate")}<select value={compareIds[1] ?? ""} onChange={(event) => { comparisonRequestRef.current += 1; setComparison(null); setCompareIds([compareIds[0], Number(event.target.value) || null]); }}><option value="">{t("Select result")}</option>{jobs.filter((job) => job.status === "succeeded").flatMap((job) => job.result_ids.map((id) => <option key={id} value={id}>#{id} · {job.request.suite_id}</option>))}</select></label><button className="button primary" type="button" disabled={!compareIds[0] || !compareIds[1] || compareIds[0] === compareIds[1] || !!resultMismatch} onClick={() => void loadComparison(compareIds[1]!, compareIds[0]!)}>{t("Compare selected results")}</button></section>}
        {(baselineJob || candidateJob) && <div className="evaluation-comparison-metadata">{([["Baseline", baselineJob], ["Candidate", candidateJob]] as const).map(([label, job]) => <section className="surface" key={label}><p className="eyebrow">{t(label)}</p>{job ? <><h3>{job.request.suite_id}</h3><dl className="evaluation-metadata"><div><dt>{t("Golden revision")}</dt><dd>{job.request.golden_revision_id ? `#${job.request.golden_revision_id}` : t("Canonical JSON")}</dd></div><div><dt>{t("Run mode")}</dt><dd>{t(job.request.mode)}</dd></div><div><dt>{t("Retrieval profile")}</dt><dd>{profileSummary(job.request.profile ?? DEFAULT_PROFILE, locale)}</dd></div></dl><details><summary>{t("Request settings")}</summary><pre>{JSON.stringify(job.request, null, 2)}</pre></details></> : <p className="helper">{t("Select result")}</p>}</section>)}</div>}
        {resultMismatch && <p className="notice" role="status">{t("These results use different datasets. Select results from the same dataset to compare them.")}</p>}
        {compareIds[0] !== null && compareIds[0] === compareIds[1] && <p className="notice" role="status">{t("Choose two different results.")}</p>}
        <details className="surface"><summary>{t("See an example")}</summary><p>{t("Illustrative example only — not an evaluation result.")}</p><p>{t("Baseline: 2 of 3 questions found the right evidence. Candidate: 3 of 3. The candidate improves hit rate from 67% to 100%; check the changed question and latency before choosing it.")}</p></details>
        {comparison ? <>
          <div className="metric-grid">{comparison.metrics.map((metric) => <Metric key={metric.name} icon={<Beaker />} label={metric.name} value={`${metric.candidate.toLocaleString(locale, { minimumFractionDigits: 3, maximumFractionDigits: 3, useGrouping: false })} (${metric.delta >= 0 ? "+" : ""}${metric.delta.toLocaleString(locale, { minimumFractionDigits: 3, maximumFractionDigits: 3, useGrouping: false })})`} />)}</div>
          <section className="surface" data-help="measure.compare.cases"><h2>{t("Case changes")}</h2>{comparison.cases.map((item) => <article className="case-row" key={item.case_id}><div><strong>{item.case_id}</strong><p>{item.question}</p></div><span className={`transition ${item.transition}`}>{t(item.transition.replaceAll("_", " "))}</span></article>)}{!comparison.cases.length && <p className="helper">{t("No case-level changes were recorded for this comparison.")}</p>}</section>
        </> : <div className="empty-state"><p>{t("No comparison loaded yet. Queue a run, then click Compare on a succeeded result that has a baseline.")}</p><button className="button" type="button" onClick={() => changeTab("runs")}>{t("Open Runs")}</button></div>}
      </div></RetainedPanel>

      <RetainedPanel active={tab === "snapshots"} className="panel-stack evaluation-snapshots">
        <section className="surface form-stack"><div className="surface-heading"><h2>{live ? t("Evaluation snapshots") : t("Published snapshots")}</h2></div>
          <div className="comparison-picker"><label>{t("Baseline")}<select value={snapshotIds[0] ?? ""} onChange={(event) => { snapshotComparisonRequestRef.current += 1; setSnapshotComparison(null); setSnapshotIds([Number(event.target.value) || null, snapshotIds[1]]); }}><option value="">{t("Select")}</option>{snapshots.map((item) => <option key={item.snapshot_id} value={item.snapshot_id}>{item.label} · {item.eval_result.suite}</option>)}</select></label><label>{t("Candidate")}<select value={snapshotIds[1] ?? ""} onChange={(event) => { snapshotComparisonRequestRef.current += 1; setSnapshotComparison(null); setSnapshotIds([snapshotIds[0], Number(event.target.value) || null]); }}><option value="">{t("Select")}</option>{snapshots.map((item) => <option key={item.snapshot_id} value={item.snapshot_id}>{item.label} · {item.eval_result.suite}</option>)}</select></label><button className="button primary" type="button" data-help="measure.snapshots.compare" disabled={!snapshotIds[0] || !snapshotIds[1] || snapshotIds[0] === snapshotIds[1]} onClick={() => void loadSnapshotComparison()}>{t("Compare stored results")}</button></div>
          {snapshotIds[0] !== null && snapshotIds[0] === snapshotIds[1] && <p className="notice" role="status">{t("Choose two different snapshots.")}</p>}
          {(baselineSnapshot || candidateSnapshot) && <div className="evaluation-comparison-metadata">{([["Baseline", baselineSnapshot], ["Candidate", candidateSnapshot]] as const).map(([label, snapshot]) => <SnapshotMetadata key={label} label={label} snapshot={snapshot} />)}</div>}
          {baselineSnapshot && candidateSnapshot && baselineSnapshot.eval_result.suite !== candidateSnapshot.eval_result.suite && <p className="notice">{t("These snapshots use different datasets. The comparison will identify shared questions and explain metric limits.")}</p>}
          <p className="helper">{t("Stored artifacts only. Comparing snapshots does not run an evaluation or provider request.")}</p>
        </section>
        {snapshotComparison && <section className="surface snapshot-comparison" data-help="measure.snapshots.comparison"><div className="surface-heading"><h2>{t("Snapshot comparison")}</h2><span className="mode-badge">{t(snapshotComparison.directly_comparable ? "Directly comparable" : "Limited comparison")}</span></div>{snapshotComparison.warning && <p className="notice">{snapshotComparison.warning}</p>}
          <div className="table-wrap"><table><thead><tr><th>{t("Metric")}</th><th>{t("Baseline")}</th><th>{t("Candidate")}</th><th>{t("Change")}</th></tr></thead><tbody>{snapshotComparison.metrics.map((metric) => <tr key={metric.name}><th>{metric.name}</th><td>{metric.baseline.toLocaleString(locale, { maximumFractionDigits: 3 })}</td><td>{metric.candidate.toLocaleString(locale, { maximumFractionDigits: 3 })}</td><td>{metric.delta === null ? t("n/a") : `${metric.delta > 0 ? "+" : ""}${metric.delta.toLocaleString(locale, { maximumFractionDigits: 3 })}`}</td></tr>)}</tbody></table></div>
          <div className="snapshot-case-heading"><h3>{t("Common cases")}</h3><span>{snapshotComparison.common_case_count.toLocaleString(locale)}</span></div><div className="snapshot-case-list">{snapshotComparison.cases.map((item) => <article key={item.case_id}><div className="job-title"><strong>{item.case_id}</strong><span className={`transition ${item.transition}`}>{t(item.transition.replaceAll("_", " "))}</span></div><div className="snapshot-case-side"><div><span>{t("Baseline ·")} {item.baseline_rank ? t("rank {p0}", { p0: item.baseline_rank }) : t("miss")}</span><p>{item.baseline_question}</p></div><div><span>{t("Candidate ·")} {item.candidate_rank ? t("rank {p0}", { p0: item.candidate_rank }) : t("miss")}</span><p>{item.candidate_question}</p></div></div>{item.rank_delta !== null && <small>{t("Rank delta")} {item.rank_delta > 0 ? "+" : ""}{item.rank_delta}</small>}</article>)}</div>{!snapshotComparison.cases.length && <p className="helper">{t("The stored artifacts have no common cases.")}</p>}
        </section>}
        <section className="surface snapshot-list" data-help="measure.snapshots.list"><h2>{t("Saved snapshots")}</h2>{snapshots.map((item) => <article key={item.snapshot_id}><div><strong>{item.label}</strong><p>{t("{count} documents", { count: item.document_count.toLocaleString(locale) })} · {item.eval_result.suite} · #{item.eval_result.result_id}</p></div><div className="action-row">{live && <button className="button ghost" type="button" onClick={() => onApplySnapshot(item)}>{t("Use for review")}</button>}{live && <button className="button ghost" type="button" onClick={() => void toggleSnapshot(item)}>{item.public ? t("Hide") : t("Publish")}</button>}</div></article>)}{!snapshots.length && <p className="helper">{t("No saved snapshots are available.")}</p>}</section>
      </RetainedPanel>

    </section>
  );
}

function goldenAnswers(value: Record<string, unknown>): Array<Record<string, unknown>> {
  return Array.isArray(value.answers)
    ? value.answers.filter((answer): answer is Record<string, unknown> => typeof answer === "object" && answer !== null)
    : [];
}

/** Show each stored artifact's provenance before presenting metric changes. */
function SnapshotMetadata({ label, snapshot }: { label: string; snapshot?: PublishedSnapshot }) {
  const { t } = useI18n();
  return <article className="snapshot-metadata"><p className="eyebrow">{t(label)}</p>{snapshot ? <><h3>{snapshot.label}</h3><dl className="evaluation-metadata"><div><dt>{t("Golden suite")}</dt><dd>{snapshot.eval_result.suite}</dd></div><div><dt>{t("Golden revision")}</dt><dd>{snapshot.golden_revision_id ? `#${snapshot.golden_revision_id}` : t("Canonical JSON")}</dd></div><div><dt>{t("Result")}</dt><dd>#{snapshot.eval_result.result_id}</dd></div><div><dt>{t("Corpus fingerprint")}</dt><dd><code title={snapshot.corpus_fingerprint}>{snapshot.corpus_fingerprint.slice(0, 12)}</code></dd></div></dl><details><summary>{t("Recorded configuration")}</summary><pre>{JSON.stringify({ profile: snapshot.profile, evaluation: snapshot.eval_result.config }, null, 2)}</pre></details></> : <p className="helper">{t("Select")}</p>}</article>;
}
