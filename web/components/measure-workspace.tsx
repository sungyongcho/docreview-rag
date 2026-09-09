"use client";
import { useConfirmation } from "./use-confirmation";
import { DatasetLock } from "./dataset-lock";
import { ParameterHelp } from "./parameter-help";
import { GoldenQuestionEditor, type GoldenFieldError } from "./golden-question-editor";
import { useMasterDetail } from "./use-master-detail";
import { evaluationDataset, evaluationSettings } from "@/lib/evaluation-labels";
import { GoldenPreparation } from "./golden-preparation";
import { notificationErrorDetail, notificationErrorMessage } from "@/lib/notification-registry";
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

import { ArrowLeft, ArrowUpRight, Beaker, Check, ChevronDown, FileJson, LoaderCircle, Play, Plus, Trash2, TriangleAlert, X } from "lucide-react";
import { useEffect, useId, useMemo, useRef, useState } from "react";

import {
  ApiError,
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
  saveGoldenCase, deleteGoldenCase, deleteGoldenRevision,
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
import { loadExperimentDefaults, saveExperimentDefaults, resetExperimentDefaults } from "@/lib/storage";
import { RetrievalPresetManager } from "./retrieval-preset-manager";
import { Metric } from "@/components/metric";
import { Playground } from "@/components/playground";
import { ProfileFields } from "@/components/profile-fields";
import { useNotifications } from "@/components/notifications";

export type MeasureTab = "playground" | "golden" | "runs" | "compare" | "snapshots" | "presets";

export const MEASURE_TABS: Array<[MeasureTab, string]> = [
  ["playground", "Search trial"],
  ["golden", "Golden dataset"],
  ["runs", "Run evaluation"],
  ["compare", "Compare & snapshots"],
  ["snapshots", "Snapshot management"],
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
  onLeaveGuard?: (guard: ((action: () => void) => void) | null) => void;
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

export function MeasureWorkspace({ capabilities, publicPreview, active = true, live, ready, readiness, onOpenPreparation, profile, onProfileChange, onApplyProfile, onApplySnapshot, jobBoard, onRefreshJobs, tab, onTabChange, focusResultId = null, onResultSelectionChange, helpTarget = null, environment, onDirtyChange, onLeaveGuard }: MeasureWorkspaceProps) {
  const { confirm, confirmationDialog } = useConfirmation();
  const { t, locale } = useI18n();
  const sourceJsonId = useId();
  const goldenSplit = useMasterDetail({ storageKey: "docreview:layout:golden-list-width", defaultListWidth: 520, active: active && tab === "golden", minDetailWidth: 320, collapseBelow: 800 });
  const [goldenDetailOpen, setGoldenDetailOpen] = useState(false);
  const [draftFormOpen, setDraftFormOpen] = useState(false);
  const [draftFilename, setDraftFilename] = useState("");
  const [emptyDraft, setEmptyDraft] = useState(false);
  const [allGoldenFiles, setAllGoldenFiles] = useState<GoldenRevision[]>([]);
  const pendingFile = useRef<number | null>(null);
  const { notify, dismissNotice } = useNotifications();
  const [experimentDefaults] = useState(loadExperimentDefaults);
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
  const [evaluationDefaultNotice, setEvaluationDefaultNotice] = useState("");
  const [preparation, setPreparation] = useState<import("@/lib/types").EvaluationPreparation | null>(null);
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
  const [snapshotIds, setSnapshotIds] = useState<[number | null, number | null]>([null, null]);
  const [goldenRevisions, setGoldenRevisions] = useState<GoldenRevision[]>([]);
  const [goldenCanonical, setGoldenCanonical] = useState<GoldenCanonical | null>(null);
  const [selectedGoldenRevision, setSelectedGoldenRevision] = useState<number | null>(experimentDefaults.golden_revision_id);
  const [selectedGoldenCase, setSelectedGoldenCase] = useState("");
  const [goldenCaseJson, setGoldenCaseJson] = useState("");
  const [savedGoldenJson, setSavedGoldenJson] = useState("");
  const [goldenError, setGoldenError] = useState("");
  const [goldenIssues, setGoldenIssues] = useState<GoldenFieldError[]>([]);
  const [leaveAction, setLeaveAction] = useState<(() => void) | null>(null);
  const listScroll = useRef(0);
  const leaveDialog = useRef<HTMLElement>(null);
  useEffect(() => {
    if (!leaveAction) return;
    const previous = document.activeElement as HTMLElement | null;
    const overlay = leaveDialog.current?.parentElement;
    const background = [...document.body.children].filter(element => element !== overlay);
    const before = background.map(element => element.hasAttribute("inert"));
    background.forEach(element => element.setAttribute("inert", ""));
    function keys(event: KeyboardEvent) {
      if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); setLeaveAction(null); }
      if (event.key === "Tab") {
        const buttons = [...(leaveDialog.current?.querySelectorAll<HTMLButtonElement>("button:not(:disabled)") ?? [])];
        if (event.shiftKey && document.activeElement === buttons[0]) { event.preventDefault(); buttons.at(-1)?.focus(); }
        else if (!event.shiftKey && document.activeElement === buttons.at(-1)) { event.preventDefault(); buttons[0]?.focus(); }
      }
    }
    document.addEventListener("keydown", keys, true);
    return () => { document.removeEventListener("keydown", keys, true); background.forEach((element, i) => { if (!before[i]) element.removeAttribute("inert"); }); previous?.focus({ preventScroll: true }); };
  }, [leaveAction]);
  function requestGoldenLeave(action: () => void) {
    if (goldenDirty) setLeaveAction(() => action); else action();
  }
  useEffect(() => {
    if (!goldenDetailOpen && goldenSplit.listRef.current) goldenSplit.listRef.current.scrollTop = listScroll.current;
  }, [goldenDetailOpen]);
  useEffect(() => {
    if (goldenError) {
      const body = goldenSplit.workspaceRef.current?.querySelector<HTMLElement>(".golden-editor-content");
      if (body) body.scrollTop = 0;
    }
  }, [goldenError]);
  const [runFileFilter, setRunFileFilter] = useState("all");
  const [runSearch, setRunSearch] = useState("");
  const [runStatus, setRunStatus] = useState("all");
  const [runSort, setRunSort] = useState("newest");
  const [compareFile, setCompareFile] = useState("");
  const [compareSort, setCompareSort] = useState("newest");
  const [snapshotFileFilter, setSnapshotFileFilter] = useState("all");
  const [snapshotSearch, setSnapshotSearch] = useState("");
  const [snapshotSort, setSnapshotSort] = useState("newest");
  const [compareIds, setCompareIds] = useState<[number | null, number | null]>([null, null]);
  const goldenDirty = goldenCaseJson !== savedGoldenJson && savedGoldenJson !== "";
  useEffect(() => {
    onLeaveGuard?.(goldenDirty ? (action) => setLeaveAction(() => action) : null);
    return () => onLeaveGuard?.(null);
  }, [goldenDirty, onLeaveGuard]);
  useEffect(() => {
    onDirtyChange?.(goldenDirty);
    function beforeLeave(event: BeforeUnloadEvent) { if (goldenDirty) { event.preventDefault(); event.returnValue = ""; } }
    window.addEventListener("beforeunload", beforeLeave);
    return () => { window.removeEventListener("beforeunload", beforeLeave); onDirtyChange?.(false); };
  }, [goldenDirty, onDirtyChange]);
  function changeTab(next: MeasureTab) {
    if (goldenBusy || next === tab) return false;
    if (goldenDirty) { requestGoldenLeave(() => { setGoldenDetailOpen(false); onTabChange(next); }); return false; }
    onTabChange(next); return true;
  }
  function resetGoldenSelection() {
    setSelectedGoldenCase(""); setGoldenCaseJson(""); setSavedGoldenJson(""); setGoldenError(""); setGoldenIssues([]);
  }
  function prepareEvaluation() {
    setMode(loadExperimentDefaults().mode); setEvaluationDefaultNotice("");
    setRunFileFilter(selectedGoldenRevision ? `file:${selectedGoldenRevision}` : `builtin:${suiteId}`);
    if (changeTab("runs")) setSetupOpen(true);
  }
  const [goldenCaseQuery, setGoldenCaseQuery] = useState("");
  const [goldenCaseSort, setGoldenCaseSort] = useState("id");
  const [snapshotComparison, setSnapshotComparison] = useState<SnapshotComparison | null>(null);
  const [snapshotLabel, setSnapshotLabel] = useState("");
  const [focusedSnapshotId, setFocusedSnapshotId] = useState<number | null>(null);
  useEffect(() => {
    if (active && tab === "snapshots" && focusedSnapshotId !== null) {
      const row = document.getElementById(`managed-snapshot-${focusedSnapshotId}`);
      row?.scrollIntoView?.({ block: "nearest" });
      row?.focus({ preventScroll: true });
    }
  }, [active, tab, focusedSnapshotId]);
  function openSavedSnapshot(snapshot: PublishedSnapshot) {
    setSnapshotFileFilter("all"); setSnapshotSearch("");
    setFocusedSnapshotId(snapshot.snapshot_id);
    changeTab("snapshots");
  }
  const [savingSnapshot, setSavingSnapshot] = useState(false);
  const [savedSnapshotResult, setSavedSnapshotResult] = useState<number | null>(null);
  const [failedSnapshotResult, setFailedSnapshotResult] = useState<number | null>(null);
  const snapshotSaving = useRef(false);
  const snapshotResult = useRef(selectedResultId);
  snapshotResult.current = selectedResultId;
  useEffect(() => {
    if (savedSnapshotResult === null) return;
    const timer = window.setTimeout(() => setSavedSnapshotResult(null), 2500);
    return () => window.clearTimeout(timer);
  }, [savedSnapshotResult]);

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
      setAllGoldenFiles((await Promise.all(suiteRows.map(suite => getGoldenRevisions(suite.suite_id)))).flat());
    } catch (reason) {
      notify(reason instanceof Error ? notificationErrorMessage(reason) : t("Refresh failed."), "error", "measure-refresh", undefined, { event: "measure-refresh-error", detail: notificationErrorDetail(reason) });
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
      const preferredRevision = pendingFile.current ?? (suiteId === experimentDefaults.suite_id
        ? experimentDefaults.golden_revision_id
        : null);
      pendingFile.current = null;
      setSelectedGoldenRevision(
        rows.some((row) => row.revision_id === preferredRevision) ? preferredRevision : null,
      );
      setSelectedGoldenCase("");
      setGoldenCaseJson("");
      setSavedGoldenJson("");
    }).catch((reason) => { if (active) notify(reason instanceof Error ? notificationErrorMessage(reason) : String(reason), "error", "golden-revisions", undefined, { event: "golden-revisions-error", detail: notificationErrorDetail(reason) }); });
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
    if (!live) { notify(t("Production experiment controls are locked. Compare published snapshots instead."), "warning", "prod-eval", undefined, { event: "prod-eval-warning" }); return; }
    if (!canRun || busy) return;
    setBusy(true);
    setSubmissionError("");
    try {
      const job = await queueEvaluation(evaluationRequest);
      setJobs((current) => [job, ...current]);
      setSelectedJobId(job.job_id);
      selectResult(null); setResultDetail(null); setSetupOpen(false);
      onRefreshJobs();
      notify(t("Evaluation queued."), "success", "evaluation-queued", undefined, { event: "evaluation-queued-notice" });
    } catch (reason) {
      setSubmissionError(reason instanceof Error ? reason.message : t("Evaluation failed."));
      notify(reason instanceof Error ? notificationErrorMessage(reason) : t("Evaluation failed."), "error", "evaluation", undefined, { event: "evaluation-error", detail: notificationErrorDetail(reason) });
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
      const entry = resultEntries.find(item => item.id === baseline);
      if (entry) setCompareFile(entry.dataset.key);
      const loaded = await compareEvaluations(candidate, baseline);
      if (requestId === comparisonRequestRef.current) { setComparison(loaded); changeTab("compare"); notify(t("Evaluation comparison ready."), "success", `comparison:${baseline}:${candidate}`, undefined, { event: "evaluation-comparison", target: { view: "measure", tab: "compare", resultId: null }, revision: `${baseline}:${candidate}` }); }
    } catch (reason) {
      notify(reason instanceof Error ? notificationErrorMessage(reason) : t("Comparison failed."), "error", "comparison", undefined, { event: "comparison-error", detail: notificationErrorDetail(reason) });
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
      notify(message, "error", "evaluation-detail", undefined, { event: "evaluation-detail-error" });
    }
  }

  function applySelectedResult() {
    const job = jobs.find((item) => item.result_ids.includes(selectedResultId ?? -1));
    if (!job || selectedResultId === null) return;
    onApplyProfile(job.request.profile ?? DEFAULT_PROFILE, `${job.request.suite_id}:${selectedResultId}`);
  }

  async function newGoldenDraft() {
    if (!live || goldenBusy) return;
    if (goldenDirty && !await confirm(t("Discard unsaved question changes?"))) return;
    setGoldenBusy(true);
    try {
      const created = await createGoldenDraft(suiteId, selectedGoldenRevision, draftFilename.trim(), emptyDraft);
      setAllGoldenFiles(current => [...current, created]);
      window.dispatchEvent(new Event("docreview:golden-files-changed"));
      setDraftFormOpen(false); setDraftFilename("");
      setGoldenRevisions((current) => [created, ...current]);
      setSelectedGoldenRevision(created.revision_id);
      resetGoldenSelection();
      notify(t("Dataset file created."), "success", "golden-draft", undefined, { event: "golden-draft-notice" });
    } catch (reason) {
      notify(reason instanceof Error ? notificationErrorMessage(reason) : t("Golden draft could not be created."), "error", "golden-draft", undefined, { event: "golden-draft-error", detail: notificationErrorDetail(reason) });
    } finally { setGoldenBusy(false); }
  }

  function openGoldenCase(caseValue: Record<string, unknown>) {
    listScroll.current = goldenSplit.listRef.current?.scrollTop ?? 0;
    setGoldenDetailOpen(true);
    if (String(caseValue.id) === selectedGoldenCase) return;
    setSavedGoldenJson(JSON.stringify(caseValue, null, 2));
    setGoldenError(""); setGoldenIssues((activeGoldenRevision?.completion?.[String(caseValue.id)] ?? []) as unknown as GoldenFieldError[]);
    setSelectedGoldenCase(String(caseValue.id ?? ""));
    setGoldenCaseJson(JSON.stringify(caseValue, null, 2));
  }

  async function saveSelectedGoldenCase() {
    const revision = goldenRevisions.find((item) => item.revision_id === selectedGoldenRevision);
    if (!revision || !selectedGoldenCase || goldenBusy) return false;
    dismissNotice("golden-save");
    setGoldenBusy(true);
    try {
      let value: Record<string, unknown>;
      try { value = JSON.parse(goldenCaseJson) as Record<string, unknown>; }
      catch { setGoldenError(t("Enter valid question JSON.")); return false; }
      const updated = await saveGoldenCase(revision.revision_id, selectedGoldenCase, revision.sha256, value);
      setGoldenRevisions((current) => current.map((item) => item.revision_id === updated.revision_id ? updated : item));
      const saved = updated.payload.find(item => item.id === selectedGoldenCase);
      const savedJson = JSON.stringify(saved, null, 2);
      setSavedGoldenJson(savedJson); setGoldenCaseJson(savedJson); setGoldenError("");
      setGoldenIssues((updated.completion?.[selectedGoldenCase] ?? []) as unknown as GoldenFieldError[]);
      window.dispatchEvent(new Event("docreview:golden-files-changed"));
      return true;
    } catch (reason) {
      if (reason instanceof ApiError && reason.code === "golden_draft_conflict") { setGoldenError("Dataset changed; reload the saved question before retrying."); return false; }
      if (reason instanceof ApiError && (reason.status === 400 || reason.status === 422)) {
        const details = Array.isArray(reason.failure?.details) ? reason.failure.details as { location: (string | number)[]; message: string; error_type: string }[] : [];
        setGoldenIssues(details.map(item => ({ ...item, code: item.error_type })));
        setGoldenError(t("Check the indicated question fields."));
        return false;
      }
      setGoldenError(reason instanceof Error ? reason.message : t("Golden case could not be saved."));
      notify(reason instanceof Error ? notificationErrorMessage(reason) : t("Golden case could not be saved."), "error", "golden-save", undefined, { event: "golden-save-error", detail: notificationErrorDetail(reason) });
      return false;
    } finally { setGoldenBusy(false); }
  }

  async function deleteGoldenQuestion(caseId: string, { confirmed = false } = {}) {
    const revision = goldenRevisions.find((item) => item.revision_id === selectedGoldenRevision);
    if (!revision || goldenBusy) return;
    if (!confirmed && !await confirm(t("Delete this draft question?"), { confirm: "Yes", cancel: "No", danger: true })) return;
    const persisted = revision.payload.some((item) => item.id === caseId);
    setGoldenBusy(true);
    try {
      if (persisted) {
        const updated = await deleteGoldenCase(revision.revision_id, caseId, revision.sha256);
        setGoldenRevisions((current) => current.map((item) => item.revision_id === updated.revision_id ? updated : item));
        window.dispatchEvent(new Event("docreview:golden-files-changed"));
      }
      if (selectedGoldenCase === caseId) { setGoldenDetailOpen(false); setSelectedGoldenCase(""); setGoldenCaseJson("{}"); setSavedGoldenJson("{}"); setGoldenError(""); setGoldenIssues([]); }
      notify(t(persisted ? "Question deleted." : "Unsaved question discarded."), "success", "golden-delete", undefined, { event: "golden-delete-notice" });
    } catch (reason) {
      if (reason instanceof ApiError && reason.code === "golden_draft_conflict") { setGoldenError("Dataset changed; reload the saved question before retrying."); return; }
      notify(reason instanceof Error ? notificationErrorMessage(reason) : t("Question could not be deleted."), "error", "golden-delete", undefined, { event: "golden-delete-error", detail: notificationErrorDetail(reason) });
    } finally { setGoldenBusy(false); }
  }

  async function deleteGoldenFile() {
    const revision = activeGoldenRevision;
    if (!revision || goldenBusy) return;
    if (!await confirm(t("Delete dataset file {p0}? Its questions are removed from disk; built-in suites and evaluation results are kept.", { p0: revision.filename }), { confirm: "Yes", cancel: "No", danger: true })) return;
    setGoldenBusy(true);
    try {
      await deleteGoldenRevision(revision.revision_id, revision.sha256);
      setGoldenRevisions((current) => current.filter((item) => item.revision_id !== revision.revision_id));
      setAllGoldenFiles((current) => current.filter((item) => item.revision_id !== revision.revision_id));
      setSelectedGoldenRevision(null); setGoldenDetailOpen(false); resetGoldenSelection(); setSourceJsonOpen(false);
      window.dispatchEvent(new Event("docreview:golden-files-changed"));
      notify(t("Dataset file deleted."), "success", "golden-delete", undefined, { event: "golden-delete-notice" });
    } catch (reason) {
      notify(reason instanceof Error ? notificationErrorMessage(reason) : t("Dataset file could not be deleted."), "error", "golden-delete", undefined, { event: "golden-delete-error", detail: notificationErrorDetail(reason) });
    } finally { setGoldenBusy(false); }
  }

  async function reloadGoldenQuestion() {
    if (!selectedGoldenRevision || !await confirm(t("Reload the saved question and discard local edits?"))) return;
    try {
      const rows = await getGoldenRevisions(suiteId);
      const revision = rows.find(item => item.revision_id === selectedGoldenRevision);
      const saved = revision?.payload.find(item => item.id === selectedGoldenCase);
      if (!revision || !saved) { setGoldenError("The saved question could not be found. Your draft is retained."); return; }
      setGoldenRevisions(rows); setGoldenCaseJson(JSON.stringify(saved, null, 2)); setSavedGoldenJson(JSON.stringify(saved, null, 2)); setGoldenError(""); setGoldenIssues((revision.completion?.[selectedGoldenCase] ?? []) as unknown as GoldenFieldError[]);
    } catch { setGoldenError("The saved question could not be loaded. Your draft is retained."); }
  }

  async function changeGoldenStatus(action: "validate") {
    const revision = goldenRevisions.find((item) => item.revision_id === selectedGoldenRevision);
    if (!revision || goldenDirty || goldenBusy) return;
    setGoldenBusy(true);
    try {
      const updated = await transitionGoldenRevision(revision.revision_id, action, revision.sha256);
      setGoldenRevisions((current) => current.map((item) => item.revision_id === updated.revision_id ? updated : item));
      notify(t(action === "validate" ? "Golden revision validated." : "Golden revision published."), "success", `golden-${action}`, undefined, { event: "golden-action-notice" });
    } catch (reason) {
      if (reason instanceof ApiError && reason.code === "golden_input_invalid") {
        const details = Array.isArray(reason.failure?.details) ? reason.failure.details as { location: (string | number)[]; message: string; error_type: string }[] : [];
        const index = details[0]?.location[0] === "cases" ? Number(details[0].location[1]) : -1;
        if (index >= 0 && activeGoldenCases[index]) openGoldenCase(activeGoldenCases[index]);
        setGoldenIssues(details.filter(item => index < 0 || Number(item.location[1]) === index).map(item => ({ location: index < 0 ? item.location : item.location.slice(2), message: item.message, code: item.error_type })));
        setGoldenError("Complete the indicated fields before evaluation. Draft saving remains available.");
        return;
      }
      setGoldenError(reason instanceof Error ? reason.message : String(reason));
      notify(reason instanceof Error ? notificationErrorMessage(reason) : t(action === "validate" ? "Golden revision could not be validated." : "Golden revision could not be published."), "error", `golden-${action}`, undefined, { event: "golden-action-error", detail: notificationErrorDetail(reason) });
    } finally { setGoldenBusy(false); }
  }

  async function freezeSnapshot() {
    if (existingSnapshot) { openSavedSnapshot(existingSnapshot); return; }
    if (!live || selectedResultId === null || !snapshotLabel.trim() || snapshotSaving.current) return;
    const resultId = selectedResultId;
    snapshotSaving.current = true;
    setSavingSnapshot(true); setSavedSnapshotResult(null); setFailedSnapshotResult(null);
    try {
      const identity = resultDetail?.config.admin_identity;
      const goldenSha = typeof identity === "object" && identity !== null ? (identity as Record<string, unknown>).golden_sha256 : resultDetail?.config.golden_sha256;
      const revision = goldenRevisions.find((item) => item.status === "published" && item.sha256 === goldenSha);
      const created = await createSnapshot({ label: snapshotLabel.trim(), eval_result_id: selectedResultId, golden_revision_id: revision?.status === "published" ? revision.revision_id : null, public: false });
      setSnapshots((current) => [created, ...current.filter(item => item.snapshot_id !== created.snapshot_id)]);
      if (snapshotResult.current === resultId) setSnapshotLabel("");
      setSavedSnapshotResult(resultId);
      notify(t("Evaluation snapshot created."), "success", "snapshot-create", undefined, { event: "snapshot-create-notice" });
    } catch (reason) {
      setFailedSnapshotResult(resultId);
      notify(reason instanceof Error ? notificationErrorMessage(reason) : t("Snapshot could not be created."), "error", "snapshot-create", undefined, { event: "snapshot-create-error", detail: notificationErrorDetail(reason) });
    } finally { snapshotSaving.current = false; setSavingSnapshot(false); }
  }

  async function loadSnapshotComparison() {
    if (!snapshotIds[0] || !snapshotIds[1] || snapshotIds[0] === snapshotIds[1]) return;
    setSnapshotComparison(null);
    const requestId = ++snapshotComparisonRequestRef.current;
    try {
      const loaded = await compareSnapshots(snapshotIds[0], snapshotIds[1], live);
      if (requestId === snapshotComparisonRequestRef.current) { setSnapshotComparison(loaded); notify(t("Snapshot comparison ready."), "success", `snapshot-comparison:${snapshotIds.join(":")}`, undefined, { event: "snapshot-comparison-result", revision: JSON.stringify(loaded) }); }
    } catch (reason) {
      notify(reason instanceof Error ? notificationErrorMessage(reason) : t("Snapshots could not be compared."), "error", "snapshot-compare", undefined, { event: "snapshot-compare-error", detail: notificationErrorDetail(reason) });
    }
  }

  async function toggleSnapshot(snapshot: PublishedSnapshot) {
    if (!live) return;
    try {
      const updated = await setSnapshotVisibility(snapshot.snapshot_id, !snapshot.public);
      setSnapshots((current) => current.map((item) => item.snapshot_id === updated.snapshot_id ? updated : item));
      notify(updated.public ? t("Snapshot published.") : t("Snapshot hidden."), "success", "snapshot-visibility", undefined, { event: "snapshot-visibility-notice" });
    } catch (reason) {
      notify(reason instanceof Error ? notificationErrorMessage(reason) : t("Snapshot visibility could not change."), "error", "snapshot-visibility", undefined, { event: "snapshot-visibility-error", detail: notificationErrorDetail(reason) });
    }
  }

  const selectedSuite = suites.find((suite) => suite.suite_id === suiteId) ?? suites[0];
  const activeGoldenRevision = goldenRevisions.find((item) => item.revision_id === selectedGoldenRevision) ?? null;
  const activeGoldenCases = activeGoldenRevision?.payload ?? goldenCanonical?.payload ?? [];
  const visibleGoldenCases = activeGoldenCases.filter((item) => `${String(item.id)} ${String(item.question)} ${t(String(item.category))} ${t(String(item.facet))} ${Array.isArray(item.tags) ? item.tags.join(" ") : ""}`.toLowerCase().includes(goldenCaseQuery.toLowerCase())).toSorted((left, right) => String(left[goldenCaseSort] ?? "").localeCompare(String(right[goldenCaseSort] ?? ""), undefined, { numeric: true }));
  const goldenReadOnly = !activeGoldenRevision;
  const selectedFile = activeGoldenRevision ?? goldenCanonical;
  const fileRegistry = String(activeGoldenRevision?.file_content?.registry ?? selectedSuite?.registry ?? "");
  const fileLanguage = String(activeGoldenRevision?.file_content?.question_language ?? selectedSuite?.question_language ?? "");
  function selectDataset(value: string) {
    if (goldenDirty) { requestGoldenLeave(() => selectDatasetConfirmed(value)); return; }
    selectDatasetConfirmed(value);
  }
  function selectDatasetConfirmed(value: string) {
    const file = allGoldenFiles.find(item => `file:${item.revision_id}` === value);
    const nextSuite = file?.suite_id ?? value as SuiteId;
    resetGoldenSelection(); setGoldenDetailOpen(false);
    if (nextSuite !== suiteId) { pendingFile.current = file?.revision_id ?? null; setGoldenRevisions([]); setGoldenCanonical(null); setSuiteId(nextSuite); }
    setSelectedGoldenRevision(file?.revision_id ?? null);
  }
  function closeGoldenDetails() {
    requestGoldenLeave(() => setGoldenDetailOpen(false));
  }
  function addGoldenQuestion() {
    if (goldenBusy || !activeGoldenRevision) return;
    listScroll.current = goldenSplit.listRef.current?.scrollTop ?? 0;
    const value = { id: `q-${crypto.randomUUID()}`, question: "", category: null, facet: "factual", tags: [], answers: [], expected_label: null, reference_answer: "", note: "", curation_status: "user-authored", approval_status: "pending-author-approval", human_verified: false };
    setGoldenDetailOpen(true); setSelectedGoldenCase(value.id); setGoldenCaseJson(JSON.stringify(value, null, 2)); setSavedGoldenJson("{}"); setGoldenError(""); setGoldenIssues([]);
  }
  const scoreIdentity = resultDetail ? evaluationDataset(resultDetail.suite, undefined, resultDetail.config, suites, allGoldenFiles) : null;
  const selectedDatasetKey = selectedGoldenRevision ? `file:${selectedGoldenRevision}` : `builtin:${suiteId}`;
  const goldenScoreResult = resultDetail && scoreIdentity?.key === selectedDatasetKey && scoreIdentity.hash === selectedFile?.sha256 ? resultDetail : null;
  const canRun = live && preparation?.state === "ready";
  const selectedJob = jobs.find((job) => job.job_id === selectedJobId) ?? jobs.find((job) => job.result_ids.includes(selectedResultId ?? -1)) ?? null;
  const selectedOperatorJob = jobBoard.jobs.find((job) => job.job_id === selectedJobId);
  const datasetOf = (suite: string, fileId: number | null | undefined, config: unknown) => evaluationDataset(suite, fileId, config, suites, allGoldenFiles);
  const filename = (identity: ReturnType<typeof evaluationDataset>) => identity.filename ?? t("Dataset filename unavailable");
  const jobDataset = (job: EvaluationJob) => datasetOf(job.request.suite_id, job.request.golden_revision_id, job.result_summaries?.[0]?.config);
  const resultEntries = jobs.flatMap(job => job.result_ids.map(id => {
    const summary = job.result_summaries?.find(item => item.result_id === id);
    const config = summary?.config;
    const dataset = datasetOf(job.request.suite_id, job.request.golden_revision_id, config);
    const settings = evaluationSettings(config, locale, job.request.mode === "quick" ? job.request.profile ?? DEFAULT_PROFILE : undefined);
    const time = summary?.created_at ?? job.started_at ?? job.created_at;
    return { id, job, config, dataset, settings, time, label: `${settings} · ${new Date(time).toLocaleString(locale)}` };
  }));
  const datasetOptions = new Map<string, ReturnType<typeof evaluationDataset>>();
  suites.forEach(suite => { const value = datasetOf(suite.suite_id, null, null); datasetOptions.set(value.key, value); });
  allGoldenFiles.forEach(file => { const value = datasetOf(file.suite_id, file.revision_id, null); datasetOptions.set(value.key, value); });
  resultEntries.forEach(entry => datasetOptions.set(entry.dataset.key, entry.dataset));
  snapshots.forEach(item => { const value = datasetOf(item.eval_result.suite, null, item.eval_result.config); datasetOptions.set(value.key, value); });
  const fileOptions = [...datasetOptions.values()].sort((a, b) => filename(a).localeCompare(filename(b), locale));
  const jobSearchSettings = (job: EvaluationJob) => job.result_summaries?.length ? job.result_summaries.map(item => evaluationSettings(item.config, locale)).join(" ") : job.request.mode === "quick" ? evaluationSettings(null, locale, job.request.profile ?? DEFAULT_PROFILE) : t("Multiple search configurations");
  const filteredJobs = jobs.filter(job => (runFileFilter === "all" || jobDataset(job).key === runFileFilter) && (runStatus === "all" || job.status === runStatus) && `${filename(jobDataset(job))} ${jobSearchSettings(job)} ${job.message}`.toLowerCase().includes(runSearch.toLowerCase())).toSorted((a, b) => runSort === "filename" ? filename(jobDataset(a)).localeCompare(filename(jobDataset(b)), locale) : runSort === "duration" ? (Date.parse(b.finished_at ?? b.started_at ?? b.created_at) - Date.parse(b.started_at ?? b.created_at)) - (Date.parse(a.finished_at ?? a.started_at ?? a.created_at) - Date.parse(a.started_at ?? a.created_at)) : (runSort === "oldest" ? 1 : -1) * (Date.parse(a.created_at) - Date.parse(b.created_at)));
  const comparableEntries = resultEntries.filter(entry => entry.job.status === "succeeded" && entry.dataset.key === compareFile).toSorted((a, b) => (compareSort === "oldest" ? 1 : -1) * (Date.parse(a.time) - Date.parse(b.time)));
  const beforeEntry = resultEntries.find(entry => entry.id === compareIds[0]);
  const afterEntry = resultEntries.find(entry => entry.id === compareIds[1]);
  const resultMismatch = beforeEntry && afterEntry && beforeEntry.dataset.key !== afterEntry.dataset.key;
  const datasetChanged = beforeEntry?.dataset.hash && afterEntry?.dataset.hash && beforeEntry.dataset.hash !== afterEntry.dataset.hash;
  const visibleSnapshots = snapshots.filter(item => { const data = datasetOf(item.eval_result.suite, null, item.eval_result.config); return (snapshotFileFilter === "all" || data.key === snapshotFileFilter) && `${item.label} ${filename(data)} ${snapshotSettings(item, locale)}`.toLowerCase().includes(snapshotSearch.toLowerCase()); }).toSorted((a, b) => snapshotSort === "name" ? a.label.localeCompare(b.label, locale) : snapshotSort === "filename" ? filename(datasetOf(a.eval_result.suite, null, a.eval_result.config)).localeCompare(filename(datasetOf(b.eval_result.suite, null, b.eval_result.config)), locale) : (snapshotSort === "oldest" ? 1 : -1) * (Date.parse(a.created_at) - Date.parse(b.created_at)));
  const resultLabel = (id: number) => resultEntries.find(entry => entry.id === id)?.label ?? t("Recorded evaluation");
  function startResultComparison() {
    if (!resultDetail) return;
    setCompareFile(datasetOf(resultDetail.suite, selectedJob?.request.golden_revision_id, resultDetail.config).key);
    comparisonRequestRef.current += 1; setComparison(null); setCompareIds([resultDetail.result_id, null]); changeTab("compare");
  }
  function changeCompareFile(value: string) {
    comparisonRequestRef.current += 1; setCompareFile(value); setCompareIds([null, null]); setComparison(null);
  }
  function openNewEvaluation() {
    const saved = loadExperimentDefaults();
    setMode(saved.mode); setEvaluationDefaultNotice("");
    if (runFileFilter === "all") {
      if (saved.golden_revision_id && !allGoldenFiles.some(file => file.revision_id === saved.golden_revision_id)) {
        notify(t("Dataset filename unavailable"), "error", "evaluation", undefined, { event: "evaluation-error" });
        return;
      }
      selectDataset(saved.golden_revision_id ? `file:${saved.golden_revision_id}` : saved.suite_id);
    }
    if (runFileFilter.startsWith("builtin:")) selectDataset(runFileFilter.slice(8));
    else if (runFileFilter.startsWith("file:")) {
      if (!allGoldenFiles.some(file => `file:${file.revision_id}` === runFileFilter)) {
        notify(t("Dataset filename unavailable"), "error", "evaluation", undefined, { event: "evaluation-error" });
        return;
      }
      selectDataset(runFileFilter);
    }
    setSetupOpen(true);
  }
  function viewDatasetRuns() {
    setRunFileFilter(compareFile || "all");
    if (compareFile.startsWith("builtin:")) selectDataset(compareFile.slice(8));
    else if (allGoldenFiles.some(file => `file:${file.revision_id}` === compareFile)) selectDataset(compareFile);
    changeTab("runs");
  }
  function datasetExists(identity: ReturnType<typeof evaluationDataset>) {
    return identity.builtin ? suites.some(item => `builtin:${item.suite_id}` === identity.key) : allGoldenFiles.some(item => `file:${item.revision_id}` === identity.key);
  }
  function datasetLink(identity: ReturnType<typeof evaluationDataset>) {
    const value = identity.key.startsWith("builtin:") ? identity.key.slice(8) : identity.key;
    if (datasetExists(identity)) return <button className="inline-link" type="button" title={t("Open the current dataset file")} onClick={() => { selectDataset(value); changeTab("golden"); }}>{filename(identity)}</button>;
    return <>{filename(identity)}{!identity.builtin && <span className="dataset-deleted"> ({t("deleted")})</span>}</>;
  }
  const filterOptions = <>{fileOptions.map(item => <option key={item.key} value={item.key}>{filename(item)}{item.builtin ? ` (${t("Built-in")})` : datasetExists(item) ? "" : ` (${t("deleted")})`}</option>)}</>;

  const existingSnapshot = snapshots.find(snapshot => snapshot.eval_result.result_id === selectedResultId);
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
    catch (reason) { notify(reason instanceof Error ? notificationErrorMessage(reason) : String(reason), "error", "evaluation-cancel", undefined, { event: "evaluation-cancel-error", detail: notificationErrorDetail(reason) }); }
  }

  const datasetSelect = (helpId: string) => <label data-help={helpId}>{t("Golden suite")}<select disabled={goldenBusy} value={selectedGoldenRevision ? `file:${selectedGoldenRevision}` : suiteId} onChange={event => selectDataset(event.target.value)}>{suites.map(suite => <option key={suite.suite_id} value={suite.suite_id}>{suite.filename} ({t("Built-in")})</option>)}{allGoldenFiles.map(file => <option key={file.revision_id} value={`file:${file.revision_id}`}>{file.filename}</option>)}</select></label>;
  const lockedRuns = (message: string) => <div className="empty-state"><p>{t(message)}</p><button className="button" type="button" onClick={() => changeTab("snapshots")}>{t("Open Snapshots")}</button></div>;

  return (
    <section className={`lab-shell measure-workspace${tab === "golden" && goldenDetailOpen ? " golden-editing" : ""}`}>{confirmationDialog}
      <header hidden={tab === "golden" && goldenDetailOpen} className="page-heading">
        <div><p className="eyebrow">{t("Measure")}</p><h1>{t("Measure retrieval before trusting it.")}</h1></div>
        <div className="page-badges">{environment && <span className="mode-badge">{deploymentLabel(environment)}</span>}<span className={`mode-badge ${live ? "live" : ""}`}>{live ? t("Local operator") : t("Read-only portfolio")}</span></div>
      </header>
      <nav hidden={tab === "golden" && goldenDetailOpen} className="lab-tabs workflow-tabs measure-tab-strip" aria-label={t("Measure sections")}>
        <div className="measure-tab-group measure-workflow-group" role="group" aria-label={t("Evaluation workflow")}>
          {([["playground", "Search trial"], ["golden", "Golden dataset"], ["runs", "Run evaluation"], ["compare", "Compare & snapshots"]] as const).map(([id, label], index) => <button key={id} type="button" aria-pressed={tab === id || (id === "compare" && tab === "snapshots")} onClick={() => changeTab(id)}><span className="measure-step-chip" aria-hidden="true">{index + 1}</span>{t(label)}</button>)}
        </div>
        <div className="measure-tab-group measure-management-group" role="group" aria-label={t("Manage")}>
          <span className="measure-management-caption" aria-hidden="true">{t("Manage")}</span>
          <button type="button" aria-pressed={tab === "presets"} onClick={() => changeTab("presets")}>{t("Presets")}</button>
        </div>
      </nav>
      <div className="workflow-section-heading" data-help={tab === "presets" ? "measure.presets.manage" : undefined}><h2>{tab === "presets" ? t("Retrieval presets") : tab === "playground" ? t("Search trial") : tab === "golden" ? t("Prepare a golden dataset") : tab === "runs" ? t("Run evaluation") : tab === "snapshots" ? t(live ? "Snapshot management" : "Published snapshots") : t("Compare evaluation results")}</h2>{live && ["golden", "runs"].includes(tab) && <DevelopmentBadge locale={locale} compact />}<WorkflowHelp active={active} screen={`measure.${tab}`} capabilities={capabilities} publicPreview={publicPreview} /></div>
      <p className="data-origin">{t(live ? "Live workspace · results come from recorded runs" : "Read-only workspace · published snapshots come from the server")}</p>
      <p className="workflow-intro">{tab === "presets" ? t("Create reusable search settings, then select them in a conversation.") : tab === "playground" ? t("Try one question and inspect its evidence before evaluating a whole dataset.") : tab === "golden" ? t("Select a JSON dataset and inspect its questions. Create a separate file to edit, save changes, then check format and sources.") : tab === "runs" ? t("Choose the questions and search settings to measure. A run records what was tested and how well the evidence was retrieved.") : tab === "snapshots" ? t("A snapshot preserves search data and an evaluation result so you can reuse a known configuration later.") : t("Choose a baseline and a candidate. Compare evidence hits, rank, and latency. Saving a snapshot is optional.")}</p>
      {(tab === "compare" || tab === "snapshots") && <nav className="result-tabs"><button type="button" aria-pressed={tab === "compare"} onClick={() => changeTab("compare")}>{t("Compare results")}</button><button type="button" aria-pressed={tab === "snapshots"} onClick={() => changeTab("snapshots")}>{t(live ? "Snapshot management" : "Published snapshots")}</button></nav>}


      {leaveAction && createPortal(<div className="golden-leave-backdrop"><section ref={leaveDialog} role="dialog" aria-modal="true" aria-label={t("Unsaved question changes")} className="golden-leave-dialog"><h2>{t("Unsaved question changes")}</h2><p>{t("Save this draft before leaving?")}</p><div className="action-row"><button autoFocus type="button" className="button" onClick={() => setLeaveAction(null)}>{t("Continue editing")}</button><button type="button" className="button" disabled={goldenBusy} onClick={() => { const action = leaveAction; setGoldenCaseJson(savedGoldenJson); setGoldenIssues([]); setGoldenError(""); setLeaveAction(null); onLeaveGuard?.(null); action(); }}>{t("Discard and leave")}</button><button type="button" className="button primary" disabled={goldenBusy || !parsedGoldenCase} onClick={async () => { const action = leaveAction; if (await saveSelectedGoldenCase()) { setLeaveAction(null); onLeaveGuard?.(null); action(); } else { setLeaveAction(null); } }}>{t("Save draft and leave")}</button></div></section></div>, document.body)}
      {tab === "presets" && <RetrievalPresetManager profile={profile} onApply={onApplyProfile} canApply={capabilities?.can_change_custom_retrieval ?? live} />}

      <RetainedPanel active={tab === "playground"}><Playground live={live} profile={profile} onProfileChange={onProfileChange} onOpenSnapshots={() => changeTab("snapshots")} /></RetainedPanel>

      <RetainedPanel active={tab === "golden"} className="golden-workspace evaluation-golden">
        {goldenDetailOpen && <GoldenQuestionEditor filename={selectedFile?.filename ?? ""} registry={fileRegistry} onDelete={goldenReadOnly || !selectedGoldenCase ? undefined : () => void deleteGoldenQuestion(selectedGoldenCase, { confirmed: true })} json={goldenCaseJson} readOnly={goldenReadOnly} dirty={goldenDirty} busy={goldenBusy} error={goldenError} issues={goldenIssues} onChange={json => { setGoldenCaseJson(json); setGoldenError(""); setGoldenIssues([]); }} onReload={() => void reloadGoldenQuestion()} onSave={() => void saveSelectedGoldenCase()} onBack={closeGoldenDetails} onParsing={onOpenPreparation ? () => requestGoldenLeave(() => { setGoldenDetailOpen(false); onOpenPreparation(2); }) : undefined} />}

        <section hidden={goldenDetailOpen} className="surface form-stack golden-controls evaluation-golden-controls">
          {live && <div className="golden-dataset-selector">{datasetSelect("measure.golden.suite")}<button type="button" className="button" disabled={goldenBusy || goldenDirty} onClick={() => setDraftFormOpen(value => !value)}><Plus size={15} />{t("Create draft")}</button></div>}
          {draftFormOpen && <div className="golden-draft-form"><label>{t("JSON filename")}<input value={draftFilename} placeholder="my-evaluation.json" onChange={event => setDraftFilename(event.target.value)} /></label><label>{t("Starting content")}<select value={emptyDraft ? "empty" : "copy"} onChange={event => setEmptyDraft(event.target.value === "empty")}><option value="copy">{t("Copy selected dataset")}</option><option value="empty">{t("Empty dataset")}</option></select></label><button type="button" className="button primary" disabled={goldenBusy || !draftFilename.trim().endsWith(".json")} onClick={() => void newGoldenDraft()}>{t("Create file")}</button><button type="button" className="button ghost" onClick={() => setDraftFormOpen(false)}>{t("Cancel")}</button></div>}
          {live && <div className="golden-file golden-file-inline" data-help="measure.golden.revision"><div className="golden-file-header"><FileJson size={18} aria-hidden="true" /><div className="golden-file-identity"><strong className="golden-file-title">{selectedFile?.filename ?? t("Loading…")}{!activeGoldenRevision && <DatasetLock />}</strong><div className="golden-file-traits">{fileRegistry.toUpperCase()} · {t(fileLanguage === "en" ? "English" : fileLanguage === "ko" ? "Korean" : fileLanguage === "mixed" ? "English / Korean" : fileLanguage)} · {t("Question count: {count}", { count: activeGoldenCases.length })}{!activeGoldenRevision && <span className="golden-builtin-badge">{t("Built-in")}</span>}</div></div><button className="button ghost" type="button" disabled={!selectedFile} aria-expanded={sourceJsonOpen} aria-controls={sourceJsonOpen ? sourceJsonId : undefined} onClick={() => setSourceJsonOpen(value => !value)}>{t("View source JSON")}<ChevronDown size={15} aria-hidden="true" /></button>{activeGoldenRevision && <button className="button ghost golden-file-delete" type="button" disabled={goldenBusy || goldenDirty} aria-label={t("Delete dataset file")} title={t("Delete dataset file")} onClick={() => void deleteGoldenFile()}><Trash2 size={15} aria-hidden="true" /></button>}</div>{sourceJsonOpen && selectedFile && <div id={sourceJsonId} className="source-json"><h3>{t("Source JSON · read-only")}</h3><code>SHA-256 · {selectedFile.sha256}</code><pre>{JSON.stringify("file_content" in selectedFile ? selectedFile.file_content : selectedFile.payload, null, 2)}</pre></div>}</div>}
          {live && active && tab === "golden" && <GoldenPreparation request={evaluationRequest} onOpenSources={onOpenPreparation ? () => onOpenPreparation(1) : undefined} />}
          {!live && <p className="helper">{t("Golden suites are edited on the local operator build. Compare stored published snapshots instead.")}</p>}
        </section>
        <section hidden={goldenDetailOpen} ref={goldenSplit.workspaceRef} className="surface golden-manager" data-help="measure.golden.questions">
          <div className="surface-heading"><div><h2>{live ? t("Golden questions") : t("Latest comparison")}</h2>{live && <p className="helper">{activeGoldenRevision ? t(activeGoldenRevision.status === "validated" ? "Source checks passed" : "Editable draft") : t("Built-in golden set")}{goldenScoreResult ? ` · ${evaluationSettings(goldenScoreResult.config, locale)} · ${new Date(goldenScoreResult.created_at).toLocaleString(locale)}` : t(" · no evaluation result selected")}</p>}</div>{live && <div className="action-row golden-question-actions">{!goldenReadOnly && <><button className="button" type="button" disabled={goldenBusy || goldenDirty} onClick={addGoldenQuestion}><Plus size={14} />{t("Add question")}</button><button className="button" type="button" disabled={goldenBusy || goldenDirty || !activeGoldenCases.length} onClick={() => void changeGoldenStatus("validate")}>{t("Check format and sources")}</button></>}<button className="button primary" type="button" disabled={goldenBusy || goldenDirty} onClick={prepareEvaluation}>{t("Evaluate this dataset")}</button></div>}</div>
          {live ? <><div className="golden-table-tools"><input aria-label={t("Search golden cases")} placeholder={t("Search ID, question, category, facet, or tag")} value={goldenCaseQuery} onChange={(event) => setGoldenCaseQuery(event.target.value)} /><select aria-label={t("Sort golden cases")} value={goldenCaseSort} onChange={(event) => setGoldenCaseSort(event.target.value)}><option value="id">{t("ID")}</option><option value="question">{t("Question")}</option><option value="category">{t("Category")}</option><option value="facet">{t("Facet")}</option></select></div><div id={goldenSplit.listPanelId} ref={goldenSplit.listRef} className="golden-table-scroll"><table><thead><tr><th>{t("ID")}</th><th>{t("Question")}</th><th>{t("Category")}</th><th>{t("Facet")}</th><th>{t("Tags")}</th>{goldenScoreResult && <><th>{t("Eval")}</th><th>{t("First rank")}</th><th>{t("RR")}</th></>}{!goldenReadOnly && <th className="golden-row-actions"><span className="sr-only">{t("Actions")}</span></th>}</tr></thead><tbody>{visibleGoldenCases.map((item) => { const score = goldenScoreResult?.cases.find((value) => value.case_id === item.id); const rank = score?.first_relevant_rank ?? null; return <tr key={String(item.id)} tabIndex={0} onClick={() => openGoldenCase(item)} onKeyDown={(event) => { if (event.key === "Enter") openGoldenCase(item); }} className={selectedGoldenCase === String(item.id) ? "selected" : ""}><td><span className="golden-id-cell"><button type="button" className="row-detail" onClick={(event) => { event.stopPropagation(); openGoldenCase(item); }}>{String(item.id)}</button>{activeGoldenRevision && ((activeGoldenRevision.completion?.[String(item.id)]?.length ?? 0) > 0 ? <span className="golden-case-flag incomplete"><TriangleAlert size={11} aria-hidden="true" />{t("Incomplete")}</span> : <span className="golden-case-flag" title={t("Input complete")}><Check size={11} aria-hidden="true" />{t("Input complete")}</span>)}</span></td><td>{String(item.question) || t("Untitled question")}</td><td>{item.category == null ? "—" : t(String(item.category))}</td><td>{t(String(item.facet))}</td><td>{Array.isArray(item.tags) && item.tags.length ? item.tags.join(", ") : "—"}</td>{goldenScoreResult && <><td>{score ? rank ? t("hit") : t("miss") : t("not run")}</td><td>{rank ?? "—"}</td><td>{score ? (rank ? 1 / rank : 0).toLocaleString(locale, { minimumFractionDigits: 3, maximumFractionDigits: 3, useGrouping: false }) : "—"}</td></>}{!goldenReadOnly && <td className="golden-row-actions"><button type="button" className="golden-row-delete" aria-label={t("Delete question {p0}", { p0: String(item.id) })} title={t("Delete question")} disabled={goldenBusy} onClick={(event) => { event.stopPropagation(); void deleteGoldenQuestion(String(item.id)); }}><Trash2 size={13} aria-hidden="true" /></button></td>}</tr>; })}</tbody></table></div>{!visibleGoldenCases.length && <p className="helper">{t("No questions match this filter.")}</p>}</> : (comparison?.metrics ?? []).map((metric) => <div className="metric-row" key={metric.name}><span>{metric.name}</span><strong>{metric.candidate.toLocaleString(locale, { minimumFractionDigits: 3, maximumFractionDigits: 3, useGrouping: false })}</strong><em className={metric.delta >= 0 ? "positive" : "negative"}>{metric.delta >= 0 ? "+" : ""}{metric.delta.toLocaleString(locale, { minimumFractionDigits: 3, maximumFractionDigits: 3, useGrouping: false })}</em></div>)}
          <p className="helper">{t("Hit, first rank, and reciprocal rank measure retrieval—not final-answer factuality.")}</p>
        </section>
      </RetainedPanel>

      <RetainedPanel active={tab === "runs"}>{live ? <div className="panel-stack run-workspace evaluation-runs">
        <section className="surface evaluation-run-overview" data-help="measure.runs.results">
          <div className="surface-heading">{selectedResultId !== null ? <button className="button ghost evaluation-back-button" type="button" onClick={() => { resultRequestRef.current += 1; selectResult(null); setSelectedJobId(null); setResultDetail(null); setResultError(""); }}><ArrowLeft size={16} aria-hidden="true" />{t("Back to evaluations")}</button> : <div><h2>{t("Evaluation runs")}</h2><p className="helper">{t("Select a run to inspect its progress, settings, and recorded results.")}</p></div>}<button className="button primary" type="button" onClick={openNewEvaluation}><Plus size={15} />{t("New evaluation")}</button></div>
          {selectedResultId === null && <>
          <div className="evaluation-list-tools"><label>{t("Dataset file")}<select value={runFileFilter} onChange={event => setRunFileFilter(event.target.value)}><option value="all">{t("All datasets")}</option>{filterOptions}</select></label><label>{t("Search")}<input value={runSearch} onChange={event => setRunSearch(event.target.value)} placeholder={t("Search filename or settings")} /></label><label>{t("Status")}<select value={runStatus} onChange={event => setRunStatus(event.target.value)}><option value="all">{t("All statuses")}</option>{["queued", "running", "succeeded", "failed", "interrupted", "cancelled"].map(status => <option key={status} value={status}>{t(status)}</option>)}</select></label><label>{t("Sort by")}<select value={runSort} onChange={event => setRunSort(event.target.value)}><option value="newest">{t("Newest first")}</option><option value="oldest">{t("Oldest first")}</option><option value="filename">{t("Filename")}</option><option value="duration">{t("Longest duration")}</option></select></label></div>
          {jobsLoading && <p role="status">{t("Loading evaluations…")}</p>}
          {jobsError && <div role="alert" className="notice error"><p>{t("Evaluations could not be loaded.")}</p><p>{jobsError}</p><button className="button" type="button" onClick={() => void refreshJobs()}>{t("Retry")}</button>{onOpenPreparation && <button className="button" type="button" onClick={() => onOpenPreparation("setup")}>{t("Open setup diagnosis")}</button>}</div>}
          <div className="evaluation-run-list">{filteredJobs.map((job) => <article className={`job-row ${selectedJobId === job.job_id ? "selected" : ""}`} key={job.job_id}>
            <div className="job-select"><input type="radio" name="evaluation-result" aria-label={t("Select {p0}", { p0: job.job_id })} disabled={job.status !== "succeeded" || !job.result_id} checked={selectedResultId !== null && selectedResultId === job.result_id} onChange={() => chooseJob(job)} /><button className="row-detail" type="button" aria-pressed={selectedJobId === job.job_id} onClick={() => chooseJob(job)}><strong>{filename(jobDataset(job))} · {t(job.request.mode)}</strong><p>{job.request.mode === "matrix" ? t("Multiple search configurations") : evaluationSettings(job.result_summaries?.[0]?.config, locale, job.request.profile ?? DEFAULT_PROFILE)}</p><p>{job.message}</p></button></div>
            <div className="evaluation-run-state"><span className={`job-status ${job.status}`}>{t(job.status)}</span><small>{job.total ? `${job.current} / ${job.total}` : t(job.stage)}</small><time dateTime={job.created_at}>{new Date(job.created_at).toLocaleString(locale)}</time></div>
          </article>)}</div>
          {!jobsLoading && !jobsError && jobs.length > 0 && !filteredJobs.length && <p className="helper">{t("No evaluations match these filters.")}</p>}
          {!jobsLoading && !jobsError && !jobs.length && <div className="empty-state"><Beaker size={24} /><p>{t("No evaluations yet. Create a new evaluation when your dataset and index are ready.")}</p></div>}
          </>}
        </section>
        {selectedResultId !== null && !resultDetail && <section className="surface"><h2>{t("Result details")}</h2>{resultError ? <div role="alert" className="notice error"><p>{t("Evaluation detail could not be loaded.")}</p><p>{resultError}</p><button className="button" type="button" onClick={() => void openResult(selectedResultId)}>{t("Retry")}</button>{onOpenPreparation && <button className="button" type="button" onClick={() => onOpenPreparation("setup")}>{t("Open setup diagnosis")}</button>}</div> : <p role="status">{t("Loading evaluation result…")}</p>}</section>}
        {selectedJob && <section className="surface evaluation-job-detail" aria-live="polite"><div className="surface-heading"><div><p className="eyebrow">{t("Selected evaluation")}</p><h2>{filename(jobDataset(selectedJob))}</h2></div><span className={`job-status ${selectedOperatorJob?.status ?? selectedJob.status}`}>{t(selectedOperatorJob?.status ?? selectedJob.status)}</span></div>
          <dl className="evaluation-metadata"><div><dt>{t("Created")}</dt><dd>{new Date(selectedJob.created_at).toLocaleString(locale)}</dd></div><div><dt>{t("Dataset file")}</dt><dd>{filename(jobDataset(selectedJob))}</dd></div><div><dt>{t("Retrieval profile")}</dt><dd>{profileSummary(selectedJob.request.profile ?? DEFAULT_PROFILE, locale)}</dd></div><div><dt>{t("Run mode")}</dt><dd>{t(selectedJob.request.mode)}</dd></div></dl>
          <p>{selectedOperatorJob?.message ?? selectedJob.message}</p>
          {(selectedJob.status === "running" || selectedJob.status === "queued") && <div className="evaluation-progress"><progress aria-label={t("Evaluation progress")} value={selectedJob.total ? selectedJob.current : undefined} max={selectedJob.total ?? undefined} /><span>{t(selectedJob.stage)}{selectedJob.total ? ` · ${selectedJob.current} / ${selectedJob.total}` : ""}</span></div>}
          {selectedOperatorJob?.error_code && <div className="notice error" role="alert"><p>{selectedOperatorJob.error_code}</p>{onOpenPreparation && <button className="button" type="button" onClick={() => onOpenPreparation(preparationErrorTarget(selectedOperatorJob.error_code))}>{t("Open preparation step")}</button>}</div>}
          {selectedOperatorJob?.can_cancel && <button className="button" type="button" onClick={() => void cancelSelectedJob()}>{t("Cancel job")}</button>}
          <details><summary>{t("Request settings")}</summary><pre>{JSON.stringify({ job_id: selectedJob.job_id, request: selectedJob.request, results: selectedJob.result_summaries }, null, 2)}</pre></details>
          {selectedJob.result_ids.length > 1 && <div className="job-arms">{selectedJob.result_ids.map((resultId) => <button key={resultId} className="button" type="button" aria-pressed={selectedResultId === resultId} onClick={() => void openResult(resultId)}>{resultLabel(resultId)}</button>)}</div>}
        </section>}
        {resultDetail && <section className="surface detail-panel" data-help="measure.runs.result_detail">
          <div className="surface-heading"><h2>{t("Result details")}</h2><div className="action-row"><button className="button" type="button" data-help="measure.runs.use_selected" disabled={selectedResultId === null} onClick={applySelectedResult}>{t("Use selected set")}</button><button className="button" type="button" onClick={startResultComparison}>{t("Compare")}</button></div></div>
          <p className="helper">{resultDetail.suite} · <time dateTime={resultDetail.created_at}>{new Date(resultDetail.created_at).toLocaleString(locale)}</time></p>
          <p className="helper">{filename(datasetOf(resultDetail.suite, selectedJob?.request.golden_revision_id, resultDetail.config))} · {evaluationSettings(resultDetail.config, locale)} · {new Date(resultDetail.created_at).toLocaleString(locale)}</p><div className="metric-grid compact">{Object.entries(resultDetail.metrics).map(([name, value]) => <Metric key={name} icon={<Beaker />} label={name} value={value.toLocaleString(locale, { minimumFractionDigits: 3, maximumFractionDigits: 3, useGrouping: false })} />)}</div>
          <details className="evaluation-recorded-config"><summary>{t("Recorded configuration")}</summary><pre>{JSON.stringify({ result_id: resultDetail.result_id, ...resultDetail.config }, null, 2)}</pre></details><h3>{t("Cases")}</h3>{resultDetail.cases.slice(0, 10).map((item) => <article className="case-row" key={item.case_id}><div><strong>{item.case_id}</strong><p>{item.question}</p></div><span>{item.first_relevant_rank ? t("rank {p0}", { p0: item.first_relevant_rank }) : t("miss")}</span></article>)}
          <div className="evaluation-save">{existingSnapshot && savedSnapshotResult !== selectedResultId ? <><span className="helper">{t("Search state already saved")}: <strong>{existingSnapshot.label}</strong></span><button type="button" className="button" onClick={() => openSavedSnapshot(existingSnapshot)}>{t("View saved snapshot")}<ArrowUpRight size={15} aria-hidden="true" /></button></> : <><label>{t("Snapshot label")}<input disabled={savingSnapshot} value={snapshotLabel} onChange={(event) => { setSnapshotLabel(event.target.value); setSavedSnapshotResult(null); setFailedSnapshotResult(null); }} placeholder={t("BM25 tuned baseline")} /></label><button className={`button snapshot-save-button${savedSnapshotResult === selectedResultId && selectedResultId !== null ? " saved" : ""}`} aria-busy={savingSnapshot} type="button" data-help="measure.snapshots.freeze" title={locale === "ko" ? "개발 모드 전용" : "DEV only"} disabled={savingSnapshot || selectedResultId === null || !snapshotLabel.trim()} onClick={() => void freezeSnapshot()}>{savingSnapshot ? <LoaderCircle size={16} className="snapshot-save-spinner" aria-hidden="true" /> : savedSnapshotResult === selectedResultId && selectedResultId !== null ? <Check size={16} aria-hidden="true" /> : null}<span aria-live="polite">{t(savingSnapshot ? "Saving snapshot…" : savedSnapshotResult === selectedResultId && selectedResultId !== null ? "Snapshot saved" : failedSnapshotResult === selectedResultId && selectedResultId !== null ? "Retry snapshot save" : "Save result as snapshot")}</span><span aria-hidden="true"><DevelopmentBadge locale={locale} compact /></span></button></>}</div>
        </section>}
        {active && tab === "runs" && setupOpen && createPortal(<div className="evaluation-setup-backdrop" onClick={(event) => { if (event.target === event.currentTarget && !busy) setSetupOpen(false); }}><section ref={setupRef} className="surface evaluation-setup" role="dialog" aria-modal="true" aria-labelledby="new-evaluation-heading" onKeyDown={(event) => { if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); if (!busy) setSetupOpen(false); } }}>
          <div className="surface-heading"><div><p className="eyebrow">{t("Evaluation setup")}</p><h2 id="new-evaluation-heading">{t("New evaluation")}</h2></div><button className="button icon" type="button" aria-label={t("Close evaluation setup")} disabled={busy} onClick={() => setSetupOpen(false)}><X size={18} /></button></div>
          <div className="form-stack evaluation-setup-body"><NotificationOutlet priority={50} />
          {datasetSelect("measure.runs.suite")}
          <GoldenPreparation request={evaluationRequest} onChecked={setPreparation} onOpenSources={onOpenPreparation ? () => { setSetupOpen(false); onOpenPreparation(1); } : undefined} />
          <dl className="evaluation-metadata"><div><dt>{t("Index")}</dt><dd>{t(mode === "quick" ? "Current index" : "Isolated corpus")}</dd></div><div><dt>{t("Readiness")}</dt><dd>{t(preparation?.state === "ready" ? "Ready to evaluate" : "Preparation required")}</dd></div><div><dt>{t("Cases")}</dt><dd>{selectedFile ? activeGoldenCases.length : "—"}</dd></div><div data-help="measure.runs.revision"><dt>{t("Golden revision")}</dt><dd>{activeGoldenRevision?.filename ?? goldenCanonical?.filename ?? "—"}</dd></div></dl>
          <fieldset className="playground-core" data-help="measure.runs.profile"><legend>{t("Core search settings")}</legend><ProfileFields profile={profile} onChange={onProfileChange} helpPrefix="measure.runs" fields="core" /></fieldset>
          <details><summary>{t("Advanced evaluation options")}</summary><div className="parameter-field" data-help="measure.runs.mode"><span className="parameter-label"><label htmlFor={`${sourceJsonId}-mode`}>{t("Run mode")}</label><ParameterHelp label="Run mode" text="Quick evaluates the current index. Matrix builds isolated indexes for multiple chunk and search settings." /></span><select id={`${sourceJsonId}-mode`} value={mode} onChange={(event) => setMode(event.target.value as "quick" | "matrix")}><option value="quick">{t("Quick · current index")}</option><option value="matrix">{t("Matrix · isolated corpus")}</option></select></div>{mode === "matrix" && <div className="parameter-field" data-help="measure.runs.chunk_targets"><span className="parameter-label"><label htmlFor={`${sourceJsonId}-targets`}>{t("Chunk targets (tokens)")}</label><ParameterHelp label="Chunk targets (tokens)" text="Space-separated chunk sizes for matrix evaluation. Compare smaller precise chunks with larger context windows." /></span><input id={`${sourceJsonId}-targets`} value={chunkTargets} onChange={(event) => setChunkTargets(event.target.value)} placeholder="1024 2048" /></div>}<ProfileFields profile={profile} onChange={onProfileChange} helpPrefix="measure.runs" fields="advanced" /></details>
          <p className="helper">{t("Retrieval profile ·")} {profileSummary(profile, locale)}</p>
          <section className="evaluation-inline-defaults"><p className="helper">{t("Save this dataset and evaluation mode for future evaluations.")}</p><div className="action-row"><button className="button" type="button" disabled={busy} onClick={() => { saveExperimentDefaults({ suite_id: suiteId, golden_revision_id: selectedGoldenRevision, mode }); setEvaluationDefaultNotice("Evaluation defaults saved."); }}>{t("Save as evaluation defaults")}</button><button className="button ghost" type="button" disabled={busy} onClick={() => { resetExperimentDefaults(); setEvaluationDefaultNotice("Evaluation defaults reset. Current inputs are unchanged."); }}>{t("Reset evaluation defaults")}</button></div>{evaluationDefaultNotice && <p className="helper" role="status">{t(evaluationDefaultNotice)}</p>}</section>
          {submissionError && <div className="notice error" role="alert"><p>{submissionError}</p><button className="button" type="button" disabled={busy || !canRun} onClick={() => void runEvaluation()}>{t("Retry")}</button>{onOpenPreparation && <button className="button" type="button" onClick={() => onOpenPreparation("setup")}>{t("Open setup diagnosis")}</button>}</div>}
          {preparation && preparation.state !== "ready" && onOpenPreparation && <button type="button" className="button" onClick={() => onOpenPreparation(preparation.next_step === "filings" ? 1 : preparation.next_step === "index" ? 2 : preparation.next_step === "embeddings" ? 3 : preparation.next_step === "lexical" ? 4 : "setup")}>{t("Open preparation step")}</button>}
          </div><div className="action-row evaluation-setup-footer"><button className="button" type="button" disabled={busy} onClick={() => setSetupOpen(false)}>{t("Cancel")}</button><button className="button primary" type="button" data-help="measure.runs.queue" disabled={!canRun || busy} onClick={() => void runEvaluation()}><Play size={15} />{busy ? t("Queueing…") : t("Queue evaluation")}</button></div>
        </section></div>, document.body)}
      </div> : lockedRuns("Runs happen on the local operator build.")}</RetainedPanel>

      <RetainedPanel active={tab === "compare"}><div className="panel-stack" data-help="measure.compare.overview">
        {live && <section className="surface evaluation-comparison-setup"><div className="evaluation-compare-filters"><label>{t("Evaluation dataset")}<select value={compareFile} onChange={event => changeCompareFile(event.target.value)}><option value="">{t("Select a dataset first")}</option>{filterOptions}</select></label><label>{t("Sort by")}<select value={compareSort} onChange={event => setCompareSort(event.target.value)}><option value="newest">{t("Newest first")}</option><option value="oldest">{t("Oldest first")}</option></select></label></div><div className="comparison-picker"><label>{t("Baseline")}<select disabled={!compareFile} value={compareIds[0] ?? ""} onChange={event => { comparisonRequestRef.current += 1; setComparison(null); setCompareIds([Number(event.target.value) || null, compareIds[1]]); }}><option value="">{t("Select result")}</option>{comparableEntries.map(entry => <option key={entry.id} value={entry.id}>{entry.label}</option>)}</select></label><label>{t("Candidate")}<select disabled={!compareFile} value={compareIds[1] ?? ""} onChange={event => { comparisonRequestRef.current += 1; setComparison(null); setCompareIds([compareIds[0], Number(event.target.value) || null]); }}><option value="">{t("Select result")}</option>{comparableEntries.map(entry => <option key={entry.id} value={entry.id}>{entry.label}</option>)}</select></label><button className="button primary" type="button" disabled={!compareFile || !compareIds[0] || !compareIds[1] || compareIds[0] === compareIds[1] || !!resultMismatch || !!datasetChanged} onClick={() => void loadComparison(compareIds[1]!, compareIds[0]!)}>{t("Compare selected results")}</button></div>{compareFile && comparableEntries.length < 2 && <p className="helper">{t("This dataset needs two completed evaluations to compare.")} <button className="inline-link" type="button" onClick={viewDatasetRuns}>{t("Open Runs")}</button></p>}</section>}

        {(beforeEntry || afterEntry) && <div className="evaluation-comparison-metadata">{([["Baseline", beforeEntry], ["Candidate", afterEntry]] as const).map(([label, entry]) => <section className="surface" key={label}><p className="eyebrow">{t(label)}</p>{entry ? <><h3>{filename(entry.dataset)}</h3><p>{entry.settings}</p><p className="helper">{new Date(entry.time).toLocaleString(locale)}</p><details><summary>{t("Recorded configuration")}</summary><pre>{JSON.stringify({ result_id: entry.id, dataset_sha256: entry.dataset.hash, config: entry.config ?? entry.job.request }, null, 2)}</pre></details></> : <p className="helper">{t("Select result")}</p>}</section>)}</div>}
        {datasetChanged && <p className="notice" role="status">{t("Dataset contents changed between these evaluations. Choose runs with matching dataset contents.")}</p>}

        {resultMismatch && <p className="notice" role="status">{t("These results use different datasets. Select results from the same dataset to compare them.")}</p>}
        {compareIds[0] !== null && compareIds[0] === compareIds[1] && <p className="notice" role="status">{t("Choose two different results.")}</p>}
        <details className="surface"><summary>{t("See an example")}</summary><p>{t("Illustrative example only — not an evaluation result.")}</p><p>{t("Baseline: 2 of 3 questions found the right evidence. Candidate: 3 of 3. The candidate improves hit rate from 67% to 100%; check the changed question and latency before choosing it.")}</p></details>
        {comparison ? <>
          <div className="metric-grid">{comparison.metrics.map((metric) => <Metric key={metric.name} icon={<Beaker />} label={metric.name} value={`${metric.candidate.toLocaleString(locale, { minimumFractionDigits: 3, maximumFractionDigits: 3, useGrouping: false })} (${metric.delta >= 0 ? "+" : ""}${metric.delta.toLocaleString(locale, { minimumFractionDigits: 3, maximumFractionDigits: 3, useGrouping: false })})`} />)}</div>
          <section className="surface" data-help="measure.compare.cases"><h2>{t("Case changes")}</h2>{comparison.cases.map((item) => <article className="case-row" key={item.case_id}><div><strong>{item.case_id}</strong><p>{item.question}</p></div><span className={`transition ${item.transition}`}>{t(item.transition.replaceAll("_", " "))}</span></article>)}{!comparison.cases.length && <p className="helper">{t("No case-level changes were recorded for this comparison.")}</p>}</section>
        </> : <div className="empty-state"><p>{t("No comparison loaded yet. Queue a run, then click Compare on a succeeded result that has a baseline.")}</p><button className="button" type="button" onClick={() => changeTab("runs")}>{t("Open Runs")}</button></div>}
      </div></RetainedPanel>

      <RetainedPanel active={tab === "snapshots"} className="panel-stack evaluation-snapshots">
        <div className="evaluation-list-tools snapshot-list-tools"><label>{t("Dataset file")}<select value={snapshotFileFilter} onChange={event => { setSnapshotFileFilter(event.target.value); setSnapshotIds([null, null]); snapshotComparisonRequestRef.current += 1; setSnapshotComparison(null); }}><option value="all">{t("All datasets")}</option>{filterOptions}</select></label><label>{t("Search")}<input value={snapshotSearch} onChange={event => setSnapshotSearch(event.target.value)} placeholder={t("Search filename or snapshot name")} /></label><label>{t("Sort by")}<select value={snapshotSort} onChange={event => setSnapshotSort(event.target.value)}><option value="newest">{t("Newest first")}</option><option value="oldest">{t("Oldest first")}</option><option value="name">{t("Name")}</option><option value="filename">{t("Filename")}</option></select></label></div>
        <section className="surface form-stack"><div className="surface-heading"><h2>{t("Compare snapshots")}</h2></div>
          <div className="comparison-picker"><label>{t("Baseline")}<select value={snapshotIds[0] ?? ""} onChange={(event) => { snapshotComparisonRequestRef.current += 1; setSnapshotComparison(null); setSnapshotIds([Number(event.target.value) || null, snapshotIds[1]]); }}><option value="">{t("Select")}</option>{visibleSnapshots.map((item) => <option key={item.snapshot_id} value={item.snapshot_id}>{item.label} · {filename(datasetOf(item.eval_result.suite, null, item.eval_result.config))}</option>)}</select></label><label>{t("Candidate")}<select value={snapshotIds[1] ?? ""} onChange={(event) => { snapshotComparisonRequestRef.current += 1; setSnapshotComparison(null); setSnapshotIds([snapshotIds[0], Number(event.target.value) || null]); }}><option value="">{t("Select")}</option>{visibleSnapshots.map((item) => <option key={item.snapshot_id} value={item.snapshot_id}>{item.label} · {filename(datasetOf(item.eval_result.suite, null, item.eval_result.config))}</option>)}</select></label><button className="button primary" type="button" data-help="measure.snapshots.compare" disabled={!snapshotIds[0] || !snapshotIds[1] || snapshotIds[0] === snapshotIds[1]} onClick={() => void loadSnapshotComparison()}>{t("Compare stored results")}</button></div>
          {snapshotIds[0] !== null && snapshotIds[0] === snapshotIds[1] && <p className="notice" role="status">{t("Choose two different snapshots.")}</p>}
          {(baselineSnapshot || candidateSnapshot) && <div className="evaluation-comparison-metadata">{([["Baseline", baselineSnapshot], ["Candidate", candidateSnapshot]] as const).map(([label, snapshot]) => <SnapshotMetadata key={label} label={label} snapshot={snapshot} datasetLabel={snapshot ? filename(datasetOf(snapshot.eval_result.suite, null, snapshot.eval_result.config)) : undefined} />)}</div>}
          {baselineSnapshot && candidateSnapshot && baselineSnapshot.eval_result.suite !== candidateSnapshot.eval_result.suite && <p className="notice">{t("These snapshots use different datasets. The comparison will identify shared questions and explain metric limits.")}</p>}
          <p className="helper">{t("Stored artifacts only. Comparing snapshots does not run an evaluation or provider request.")}</p>
        </section>
        <section className="surface snapshot-manager" data-help="measure.snapshots.list">
          <div className="surface-heading"><h2>{t("Saved snapshots")}</h2><span className="helper">{visibleSnapshots.length} / {snapshots.length}</span></div>
          {live && <p className="snapshot-storage-note">{t("Stored in this database. Execution data reset deletes these snapshots.")}</p>}
          {visibleSnapshots.map(item => <article className="snapshot-manager-row" id={`managed-snapshot-${item.snapshot_id}`} tabIndex={-1} data-selected={focusedSnapshotId === item.snapshot_id} key={item.snapshot_id}>
            <div className="snapshot-manager-identity"><strong>{item.label}</strong><span className="helper">{t(item.public ? "Public" : "Private")}</span></div>
            <div className="action-row">{live && <button className="button" type="button" disabled={item.status !== "ready"} onClick={() => onApplySnapshot(item)}>{t("Use for review")}</button>}{live && <button className="button ghost" type="button" onClick={() => void toggleSnapshot(item)}>{item.public ? t("Hide") : t("Publish")}</button>}</div>
            <dl className="snapshot-manager-fields"><div><dt>{t("Dataset file")}</dt><dd>{datasetLink(datasetOf(item.eval_result.suite, null, item.eval_result.config))}</dd></div><div><dt>{t("Retrieval profile")}</dt><dd>{snapshotSettings(item, locale)}</dd></div><div><dt>{t("Evaluation result")}</dt><dd>{live ? <button type="button" className="inline-link" onClick={() => { setSelectedJobId(null); void openResult(item.eval_result.result_id); changeTab("runs"); }}>{t("View source evaluation")}</button> : new Date(item.eval_result.created_at).toLocaleString(locale)}</dd></div><div><dt>{t("Documents")}</dt><dd>{item.document_count.toLocaleString(locale)}</dd></div><div><dt>{t("Created")}</dt><dd><time dateTime={item.created_at}>{new Date(item.created_at).toLocaleString(locale)}</time></dd></div></dl>
            <details><summary>{t("Snapshot details")}</summary><p className="helper">{t("Corpus fingerprint")}: <code>{item.corpus_fingerprint}</code></p><pre>{JSON.stringify({ snapshot_id: item.snapshot_id, result_id: item.eval_result.result_id, profile: item.profile, evaluation: item.eval_result.config }, null, 2)}</pre></details>
          </article>)}
          {snapshots.length > 0 && !visibleSnapshots.length && <p className="helper">{t("No snapshots match these filters.")}</p>}{!snapshots.length && <p className="helper">{t("No saved snapshots are available.")}</p>}
        </section>
        {snapshotComparison && <section className="surface snapshot-comparison" data-help="measure.snapshots.comparison"><div className="surface-heading"><h2>{t("Snapshot comparison")}</h2><span className="mode-badge">{t(snapshotComparison.directly_comparable ? "Directly comparable" : "Limited comparison")}</span></div>{snapshotComparison.warning && <p className="notice">{snapshotComparison.warning}</p>}
          <div className="table-wrap"><table><thead><tr><th>{t("Metric")}</th><th>{t("Baseline")}</th><th>{t("Candidate")}</th><th>{t("Change")}</th></tr></thead><tbody>{snapshotComparison.metrics.map((metric) => <tr key={metric.name}><th>{metric.name}</th><td>{metric.baseline.toLocaleString(locale, { maximumFractionDigits: 3 })}</td><td>{metric.candidate.toLocaleString(locale, { maximumFractionDigits: 3 })}</td><td>{metric.delta === null ? t("n/a") : `${metric.delta > 0 ? "+" : ""}${metric.delta.toLocaleString(locale, { maximumFractionDigits: 3 })}`}</td></tr>)}</tbody></table></div>
          <div className="snapshot-case-heading"><h3>{t("Common cases")}</h3><span>{snapshotComparison.common_case_count.toLocaleString(locale)}</span></div><div className="snapshot-case-list">{snapshotComparison.cases.map((item) => <article key={item.case_id}><div className="job-title"><strong>{item.case_id}</strong><span className={`transition ${item.transition}`}>{t(item.transition.replaceAll("_", " "))}</span></div><div className="snapshot-case-side"><div><span>{t("Baseline ·")} {item.baseline_rank ? t("rank {p0}", { p0: item.baseline_rank }) : t("miss")}</span><p>{item.baseline_question}</p></div><div><span>{t("Candidate ·")} {item.candidate_rank ? t("rank {p0}", { p0: item.candidate_rank }) : t("miss")}</span><p>{item.candidate_question}</p></div></div>{item.rank_delta !== null && <small>{t("Rank delta")} {item.rank_delta > 0 ? "+" : ""}{item.rank_delta}</small>}</article>)}</div>{!snapshotComparison.cases.length && <p className="helper">{t("The stored artifacts have no common cases.")}</p>}
        </section>}

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
function SnapshotMetadata({ label, snapshot, datasetLabel }: { label: string; snapshot?: PublishedSnapshot; datasetLabel?: string }) {
  const { t, locale } = useI18n();
  return <article className="snapshot-metadata"><p className="eyebrow">{t(label)}</p>{snapshot ? <><h3>{snapshot.label}</h3><dl className="evaluation-metadata"><div><dt>{t("Golden suite")}</dt><dd>{datasetLabel ?? t("Dataset filename unavailable")}</dd></div><div><dt>{t("Retrieval profile")}</dt><dd>{snapshotSettings(snapshot, locale)}</dd></div><div><dt>{t("Created")}</dt><dd>{new Date(snapshot.eval_result.created_at).toLocaleString(locale)}</dd></div><div><dt>{t("Corpus fingerprint")}</dt><dd><code title={snapshot.corpus_fingerprint}>{snapshot.corpus_fingerprint.slice(0, 12)}</code></dd></div></dl><details><summary>{t("Recorded configuration")}</summary><pre>{JSON.stringify({ profile: snapshot.profile, evaluation: snapshot.eval_result.config }, null, 2)}</pre></details></> : <p className="helper">{t("Select")}</p>}</article>;
}

/** Use the same recorded settings label in snapshot and evaluation views. */
function snapshotSettings(snapshot: PublishedSnapshot, locale: Locale): string {
  return evaluationSettings(snapshot.eval_result.config.retrieval_profile ? snapshot.eval_result.config : snapshot.profile, locale);
}
