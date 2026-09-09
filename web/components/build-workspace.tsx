"use client";
import { usePublishedCorpus, type PublishedCorpus } from "@/lib/use-published-corpus";
import { publicTargetIds, selectedPublishedDocuments, publishedScopeStats } from "@/lib/published-scope";
import { DEFAULT_SESSION_PROFILE, type ReviewSessionDraft } from "@/lib/types";

import { DEV_ONLY_REASONS } from "@/lib/dev-mode";
import type { ScopeFilters } from "@/lib/scope-filters";
import { notificationErrorDetail, notificationErrorMessage } from "@/lib/notification-registry";
import { useI18n } from "@/lib/i18n";


import { useEffect, useMemo, useRef, useState } from "react";

import { RetainedPanel } from "@/components/retained-panel";
import { DevelopmentBadge } from "@/components/development-badge";
import { PipelineGoldenPicker } from "./golden-preparation";
import { BuildPipeline, type AcquisitionForm } from "@/components/build-pipeline";
import { DocumentInventory } from "@/components/document-inventory";
import { JobCenter, jobCopy } from "@/components/job-center";
import { useNotifications } from "@/components/notifications";
import {
  ApiError,
  getAdminSnapshots,
  getCorpusSnapshot,
  getDocumentFacets,
  getEvaluationJobs,
  checkEvaluationPreparation,
  getPublishedSnapshots,
  queueCorpusOperation,
  queueEvaluation,
} from "@/lib/api";
import { deploymentLabel } from "@/lib/deployment";
import { derivePipeline } from "@/lib/pipeline";
import { acquisitionBatches, acquisitionDraft, acquisitionPairs, loadAcquisitionDraft, saveAcquisitionDraft, selectedSourceState } from "@/lib/source-selection";
import { loadExperimentDefaults } from "@/lib/storage";
import type {
  ReviewEngineState,
  CorpusDocument,
  CorpusCounts,
  EvaluationJob,
  EvaluationRequest,
  EvaluationPreparation,
  ExperimentDefaults,
  CorpusSnapshot,
  CorpusOperationRequest,
  OperatorJobBoard,
  Readiness,
  RetrievalProfile,
} from "@/lib/types";
import { DEFAULT_EXPERIMENT_DEFAULTS } from "@/lib/types";
import type { RuntimeHealthKind } from "@/lib/use-runtime-health";

export type BuildTab = "pipeline" | "documents" | "jobs";

/** Cross-workspace destinations the Build pipeline links to. */
export type BuildNavigationTarget =
  | { view: "review" }
  | { view: "system"; tab: "status" }
  | { view: "measure"; tab: "snapshots" | "runs" | "golden"; resultId?: number };

export interface BuildWorkspaceProps {
  publishedCorpus?: PublishedCorpus;
  publicProfile?: ReviewSessionDraft;
  publicSelection?: string[];
  publicTargets?: import("@/lib/types").PublicTarget[];
  onPublicSelectionChange?: (ids: string[], targets?: import("@/lib/types").PublicTarget[]) => void;
  live: boolean;
  ready: boolean;
  readiness: Readiness | null;
  localModel?: string | null;
  healthKind: RuntimeHealthKind;
  /** Retained readiness is unconfirmed while a failed connection check retries. */
  connectionPending?: boolean;
  profile: RetrievalProfile;
  jobBoard: OperatorJobBoard;
  jobsLoading: boolean;
  /** The newest board poll failed; the retained board may be out of date. */
  jobsStale?: boolean;
  onRetryJob: (jobId: string) => void;
  onCancelJob: (jobId: string) => void;
  onRefreshJobs: () => void;
  onRecheck: () => void;
  /** Local Operations reachable from this build; enables the runtime strip's service buttons. */
  operationsAvailable?: boolean;
  onRunOperation?: (commandId: string) => void;
  tab: BuildTab;
  onTabChange: (tab: BuildTab) => void;
  focusStep?: number | "setup" | null;
  focusJobId?: string;
  onOpenLocalSettings?: () => void;
  onLocalPrepared?: (local: ReviewEngineState) => void;
  onNavigate: (target: BuildNavigationTarget) => void;
  /** Read-only servers: scope the next question to the chosen published filings. */
  publicProgress?: { candidates?: import("@/lib/types").PublicTarget[]; stage: string; checked: string[] };
  onConfirmScope?: () => void;
  onPublicProgressChange?: (progress: { stage: string; checked: string[] }) => void;
  onAskScope?: (filters: ScopeFilters) => void;
}

const TABS: Array<[BuildTab, string]> = [
  ["pipeline", "Pipeline"],
  ["documents", "Documents"],
  ["jobs", "Jobs"],
];

const DEFAULT_ACQUISITION = acquisitionDraft([]);

const UNKNOWN_CORPUS: CorpusCounts = { database_connected: null, schema_status: null, schema_message: null, documents: null, chunks: null, embedded_chunks: null, pending_embeddings: null, bm25_ready: null, writable: null, provider: null };

/** Compare the submitted evaluation options without depending on object key order. */
function sameEvaluationRequest(left: unknown, right: unknown): boolean {
  /** Keep nested profile comparisons stable without changing array order. */
  const canonical = (value: unknown): string => {
    if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
    if (value && typeof value === "object") return "{" + Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([key, item]) => `${JSON.stringify(key)}:${canonical(item)}`).join(",") + "}";
    return JSON.stringify(value) ?? "null";
  };
  if (!left || typeof left !== "object" || !right || typeof right !== "object") return false;
  const submitted = Object.fromEntries(Object.keys(right).map((key) => [key, (left as Record<string, unknown>)[key]]));
  return canonical(submitted) === canonical(right);
}

export function BuildWorkspace({ publishedCorpus, publicProfile = DEFAULT_SESSION_PROFILE, publicSelection, publicTargets, publicProgress, onConfirmScope, onPublicProgressChange, onPublicSelectionChange, live, readiness, localModel, healthKind, connectionPending = false, profile, jobBoard, jobsLoading, jobsStale = false, onRetryJob, onCancelJob, onRefreshJobs, onRecheck, operationsAvailable = false, onRunOperation, tab, onTabChange, onNavigate, onAskScope, onOpenLocalSettings, onLocalPrepared, focusStep, focusJobId }: BuildWorkspaceProps) {
  const { t, locale } = useI18n();
  const fallbackPublicCorpus = usePublishedCorpus(!live && !publishedCorpus);
  const publicCorpus = publishedCorpus ?? fallbackPublicCorpus;
  const scopeStats = publishedScopeStats(publicCorpus.documents, publicTargetIds(publicCorpus.documents, publicTargets, publicSelection) ?? publicProfile.doc_ids);
  const publicDraft = acquisitionDraft(publicTargets ?? selectedPublishedDocuments(publicCorpus.documents, publicSelection).map((doc) => ({ registry: doc.registry as "sec" | "dart", issuer: doc.issuer, year: doc.fiscal_year })));
  /** Resolve selected pairs to exact published IDs; never update DEV acquisition storage. */
  function changePublicDraft(next: AcquisitionForm) {
    const pairs = acquisitionPairs(next);
    onPublicSelectionChange?.(publicCorpus.documents.filter((doc) => pairs.some((pair) => pair.registry === doc.registry && pair.issuer === doc.issuer && pair.year === doc.fiscal_year)).map((doc) => doc.doc_id), pairs);
  }
  const [focusStage, setFocusStage] = useState<string | null>(null);
  useEffect(() => { setFocusStage(focusStep == null ? null : String(focusStep)); }, [focusStep]);
  const { notify, dismissNotice } = useNotifications();
  // One toast per failing refresh source; repeats of the same message stay quiet until it changes or recovers.
  const refreshWarnings = useRef<Record<string, string>>({});
  function warnRefresh(key: string, message: string) {
    if (refreshWarnings.current[key] === message) return;
    refreshWarnings.current[key] = message;
    notify(message, "warning", `build-refresh-${key}`, undefined, { event: "build-refresh-error" });
  }
  function clearRefresh(key: string) { delete refreshWarnings.current[key]; }
  const environment = deploymentLabel(readiness?.environment);
  const connectionConfirmed = healthKind !== "checking" && healthKind !== "api_down" && !connectionPending;
  const [experimentDefaults, setExperimentDefaults] = useState<ExperimentDefaults>(DEFAULT_EXPERIMENT_DEFAULTS);
  const [evaluationPreparation, setEvaluationPreparation] = useState<EvaluationPreparation | null>(null);
  const quickRequest = useMemo<EvaluationRequest>(() => ({ suite_id: experimentDefaults.suite_id, golden_revision_id: experimentDefaults.golden_revision_id, mode: "quick", profile, target_tokens: [1024, 2048], strategies: ["lexical", "vector", "hybrid"], lexical_rankers: ["ts_rank_cd", "bm25"] }), [experimentDefaults.suite_id, experimentDefaults.golden_revision_id, profile]);
  // Neither mode invents inventory: public rows and administrator rows load separately.
  const [corpus, setCorpus] = useState<(Omit<CorpusSnapshot, "status"> & { status: CorpusCounts }) | null>(() => (live ? null : { mode: "live", status: UNKNOWN_CORPUS, documents: [], manifests: [], sources: [], acquisition_companies: [] }));
  /** True once the administrator inventory has loaded. */
  const [adminLoaded, setAdminLoaded] = useState(false);
  const [registryCounts, setRegistryCounts] = useState<Record<string, number>>({});
  const [jobs, setJobs] = useState<EvaluationJob[]>([]);
  const [snapshotCount, setSnapshotCount] = useState(0);
  const completedJobs = useRef(new Set<string>());
  const [busy, setBusy] = useState(false);
  const [acquisition, setAcquisition] = useState<AcquisitionForm>(DEFAULT_ACQUISITION);

  const draftRevision = useRef<string | null>(null);
  const serverDraft = useMemo<AcquisitionForm>(() => {
    const draft = corpus?.acquisition_draft;
    return draft ? acquisitionDraft(draft.pairs) : acquisitionDraft([]);
  }, [corpus]);
  const revision = corpus?.acquisition_draft?.revision ?? "default-v1";
  useEffect(() => {
    if (!live || !corpus || !adminLoaded || draftRevision.current === revision) return;
    setAcquisition(loadAcquisitionDraft(revision) ?? serverDraft);
    draftRevision.current = revision;
  }, [corpus, adminLoaded, live, revision, serverDraft]);

  /** Persist the exact edited pairs without treating a later inventory refresh as a new selection. */
  function changeAcquisition(next: AcquisitionForm) {
    setAcquisition(next);
    saveAcquisitionDraft(revision, next);
  }

  useEffect(() => {
    setExperimentDefaults(loadExperimentDefaults());
  }, []);

  /** A read-only server has no administrator inventory: rebuild the company grid from the published listing. */
  useEffect(() => {
    if (live) return;
    const documents = publicCorpus.documents;
    const companies = new Map<string, CorpusSnapshot["acquisition_companies"][number]>();
    for (const document of documents) {
      const key = `${document.registry}:${document.issuer}`;
      companies.set(key, { registry: document.registry as "sec" | "dart", issuer: document.issuer, name: document.issuer_name ?? document.issuer });
    }
    const sources = documents.map((document) => ({ registry: document.registry as "sec" | "dart", issuer: document.issuer, name: document.issuer_name ?? document.issuer, fiscal_year: document.fiscal_year, filing_id: document.filing_id, document_id: document.doc_id, manifest: "", on_disk: true, ready: true, can_redownload: false, blocker: null }));
    setCorpus({ mode: "live", status: UNKNOWN_CORPUS, manifests: [], documents, sources, acquisition_companies: [...companies.values()] });
  }, [live, publicCorpus.documents]);

  /**
   * Reload the four administrator reads independently: a failed read keeps the last known state and
   * leaves an inline notice, so one busy endpoint never blanks the others. Only a refresh the user
   * asked for (`manual`) raises a toast; automatic refreshes after jobs stay quiet.
   */
  async function refresh(mode: "auto" | "manual" = "auto") {
    if (!live) return;
    const [jobRows, corpusSnapshot, facets, snapshotRows] = await Promise.allSettled([
      getEvaluationJobs(), getCorpusSnapshot(), getDocumentFacets(), getAdminSnapshots(),
    ]);
    const failures: string[] = [];
    const reasonOf = (result: PromiseRejectedResult) => result.reason instanceof Error ? result.reason.message : t("Refresh failed.");
    if (jobRows.status === "fulfilled") setJobs(Array.isArray(jobRows.value) ? jobRows.value : []);
    else failures.push(reasonOf(jobRows));
    if (corpusSnapshot.status === "fulfilled") {
      setCorpus(corpusSnapshot.value);
      setAdminLoaded(true);
      clearRefresh("corpus");
    } else {
      warnRefresh("corpus", t("Corpus status could not be refreshed: {message}", { message: reasonOf(corpusSnapshot) }));
      failures.push(reasonOf(corpusSnapshot));
    }
    if (facets.status === "fulfilled") {
      const registries = Array.isArray(facets.value.registries) ? facets.value.registries : [];
      setRegistryCounts(Object.fromEntries(registries.filter((item) => typeof item.value === "string" && typeof item.count === "number").map((item) => [item.value, item.count])));
      clearRefresh("facets");
    } else {
      warnRefresh("facets", t("Document filters could not be loaded: {message}", { message: reasonOf(facets) }));
      failures.push(reasonOf(facets));
    }
    if (snapshotRows.status === "fulfilled") setSnapshotCount(Array.isArray(snapshotRows.value) ? snapshotRows.value.length : 0);
    else failures.push(reasonOf(snapshotRows));
    if (jobRows.status === "rejected" || snapshotRows.status === "rejected") warnRefresh("history", t("Some history could not be loaded. Corpus status is shown separately."));
    else clearRefresh("history");
    return failures.length === 0;
  }

  useEffect(() => {
    void refresh();
  }, [live]);
  // Evaluation runs change only when an evaluation job moves, so key the refetch on that signature
  // rather than on every board poll; a corpus job reporting progress each second must not refetch runs.
  const evaluationSignature = useMemo(
    () => jobBoard.jobs.filter((job) => job.domain === "evaluation").map((job) => `${job.job_id}:${job.status}:${job.updated_at}`).join("|"),
    [jobBoard.jobs],
  );
  useEffect(() => {
    if (!live) return;
    void getEvaluationJobs().then((rows) => setJobs(Array.isArray(rows) ? rows : [])).catch(() => undefined);
  }, [live, evaluationSignature]);
  useEffect(() => {
    if (!live) return;
    const terminal = jobBoard.jobs.filter((job) => job.domain === "corpus" && ["succeeded", "failed", "cancelled", "interrupted"].includes(job.status));
    const fresh = terminal.filter((job) => !completedJobs.current.has(`${job.job_id}:${job.status}`));
    if (!fresh.length) return;
    for (const job of fresh) completedJobs.current.add(`${job.job_id}:${job.status}`);
    void refresh();
  }, [live, jobBoard]);
  useEffect(() => {
    if (live) return;
    void getPublishedSnapshots().then((rows) => setSnapshotCount(Array.isArray(rows) ? rows.length : 0)).catch(() => undefined);
  }, [live]);

  async function queueCorpus(body: CorpusOperationRequest) {
    if (!live) return;
    setBusy(true);
    try {
      await queueCorpusOperation(body);
      onRefreshJobs();
      notify(t("Corpus operation queued."), "success", "corpus-operation", undefined, { event: "corpus-operation-notice" });
    } catch (reason) {
      notify(reason instanceof Error ? notificationErrorMessage(reason) : t("Corpus operation failed."), "error", "corpus-operation", undefined, { event: "corpus-operation-error", detail: notificationErrorDetail(reason) });
    } finally {
      setBusy(false);
    }
  }

  /** Queue the exact selected manifest and selection pairs through the shared job API. */
  async function ingestAllManifests() {
    if (!live) return;
    const selection = selectedSourceState(corpus?.sources ?? [], acquisition);
    if (!selection.complete) { notify(selection.blocked[0]?.blocker ?? t("Download missing sources in Filings first."), "warning", "corpus-operation", undefined, { event: "corpus-operation-warning" }); return; }
    const ordered = acquisitionBatches(selection.pairs);
    if (!ordered.length) { notify(t("Select processing sources first."), "warning", "corpus-operation", undefined, { event: "corpus-operation-warning" }); return; }
    setBusy(true);
    let queued = 0;
    try {
      for (const item of ordered) {
        const documentIds = selection.selected.filter((source) => source.registry === item.registry && item.identifiers.includes(source.issuer.toUpperCase()) && item.years.includes(source.fiscal_year)).map((source) => source.document_id);
        await queueCorpusOperation({ kind: "ingest_selected", identifiers: item.identifiers, years: item.years, document_ids: documentIds });
        queued += 1;
        onRefreshJobs();
      }
      notify(t("Selections queued for ingest: {count}.", { count: ordered.length.toLocaleString(locale) }), "success", "corpus-operation", undefined, { event: "corpus-operation-notice" });
    } catch (reason) {
      notify(t("Indexing stopped after {count} queued jobs. Check Jobs before retrying.", { count: queued }) + " " + (reason instanceof Error ? notificationErrorMessage(reason) : t("Corpus operation failed.")), "error", "corpus-operation", undefined, { event: "corpus-operation-error", detail: notificationErrorDetail(reason) });
    } finally {
      setBusy(false);
    }
  }

  /** Queue missing or recoverable sources from the exact draft submitted by the picker. */
  async function downloadFilings(next: AcquisitionForm = acquisition) {
    if (!live) return;
    setBusy(true);
    let queued = 0;
    try {
      const missing = selectedSourceState(corpus?.sources ?? [], next).downloadPairs;
      for (const group of acquisitionBatches(missing)) {
        await queueCorpusOperation({ kind: group.registry === "sec" ? "acquire_edgar" : "acquire_dart", identifiers: group.identifiers, years: group.years });
        queued += 1;
        onRefreshJobs();
      }
      notify(t("Acquisition jobs queued: {count}.", { count: queued }), "success", "corpus-operation", undefined, { event: "corpus-operation-notice" });
    } catch (reason) {
      notify(t("Acquisition stopped after {count} queued jobs. Check Jobs before retrying.", { count: queued }) + " " + (reason instanceof Error ? notificationErrorMessage(reason) : t("Corpus operation failed.")), "error", "corpus-operation", undefined, { event: "corpus-operation-error", detail: notificationErrorDetail(reason) });
    } finally { setBusy(false); }
  }

  /** Queue only the reviewed deletion token; the dialog owns inline request feedback. */
  async function deleteSources(token: string) {
    if (!canOperateCorpus || busy || activeCorpusJobs.length || jobsLoading || jobsStale) throw new Error(t("Source deletion is unavailable while corpus jobs or status checks are active."));
    setBusy(true);
    try {
      await queueCorpusOperation({ kind: "delete_sources", identifiers: [], years: [], deletion_token: token, confirm_delete: true });
      onRefreshJobs();
    } finally { setBusy(false); }
  }

  async function runQuickEvaluation() {
    if (!live) { notify(t(DEV_ONLY_REASONS.evaluation), "warning", "prod-eval", undefined, { event: "prod-eval-warning" }); return; }
    if (evaluationBlockedReason) { notify(t(evaluationBlockedReason), "warning", "evaluation", undefined, { event: "evaluation-warning" }); return; }
    dismissNotice("evaluation-duplicate");
    setBusy(true);
    try {
      const request = quickRequest;
      const prepared = await checkEvaluationPreparation(request);
      setEvaluationPreparation(prepared);
      if (prepared.state !== "ready") { notify(prepared.blockers.join("; ") || t("Evaluation prerequisites are not ready."), "warning", "evaluation", undefined, { event: "evaluation-warning" }); return; }
      const activeEvaluations = [...jobBoard.jobs.filter((job) => job.domain === "evaluation"), ...jobs];
      if (activeEvaluations.some((job) => ["queued", "running"].includes(job.status) && sameEvaluationRequest(job.request, request))) {
        notify(t("The same evaluation is already queued."), "info", "evaluation-duplicate", undefined, { event: "evaluation-duplicate-notice", actionLabel: "Open Jobs", onAction: () => onTabChange("jobs") });
        return;
      }
      const job = await queueEvaluation(request);
      setJobs((current) => [job, ...current]);
      onRefreshJobs();
      notify(waitingCorpusJob
        ? waitingCorpusJob.kind === "backfill_embeddings"
          ? t("Embedding is in progress. The evaluation was added to the job queue and starts when embedding finishes.")
          : t("{kind} is in progress. The evaluation was added to the job queue and starts when it finishes.", { kind: t(jobCopy(waitingCorpusJob).label) })
        : t("Evaluation queued."), "success", "evaluation-queued", undefined, { event: "evaluation-queued-notice" });
      onTabChange("jobs");
    } catch (reason) {
      if (reason instanceof ApiError && reason.code === "evaluation_already_queued") {
        notify(t("The same evaluation is already queued."), "info", "evaluation-duplicate", undefined, { event: "evaluation-duplicate-notice", actionLabel: "Open Jobs", onAction: () => onTabChange("jobs") });
        onRefreshJobs();
      } else notify(reason instanceof Error ? notificationErrorMessage(reason) : t("Evaluation failed."), "error", "evaluation", undefined, { event: "evaluation-error", detail: notificationErrorDetail(reason) });
    } finally {
      setBusy(false);
    }
  }

  const status = useMemo(() => corpus?.status ?? UNKNOWN_CORPUS, [corpus]);
  const manifests = useMemo(() => corpus?.manifests ?? [], [corpus]);
  const corpusDocuments = useMemo<CorpusDocument[]>(() => {
    if (!live) return publicCorpus.documents;
    return corpus?.documents ?? [];
  }, [live, corpus, publicCorpus.documents]);
  const referenceCompanies = corpus?.acquisition_companies ?? [];
  const evaluationResults = jobs.filter((job) => job.status === "succeeded" && job.result_id !== null).length;
  const pipeline = useMemo(() => derivePipeline({
    live,
    healthKind,
    connectionPending,
    readiness,
    corpus: live && adminLoaded ? status : null,
    manifests,
    publicScope: live ? undefined : { ...scopeStats, status: publicCorpus.status, confirmed: publicProgress?.checked.includes("index") ?? false },
    sourceSelection: selectedSourceState(corpus?.sources ?? [], live ? acquisition : publicDraft),
    sourceInventory: corpus?.sources,
    registryCounts,
    jobs: Array.isArray(jobBoard.jobs) ? jobBoard.jobs : [],
    evaluationResults,
    snapshots: snapshotCount,
    profile,
  }), [publicProgress, publicTargets, publicSelection, live, healthKind, connectionPending, readiness, adminLoaded, status, manifests, corpus, acquisition, registryCounts, jobBoard.jobs, evaluationResults, snapshotCount, profile, publicCorpus.status, scopeStats.filings, scopeStats.total, scopeStats.chunks, scopeStats.embedded, scopeStats.pending]);
  /** Runtime flags for the strip: the administrator snapshot once loaded, otherwise `/ready`. */
  const runtimeCounts: CorpusCounts | null = !connectionConfirmed ? null : live && adminLoaded ? status : readiness?.corpus ?? null;
  const answerModelLabel = !connectionConfirmed || readiness === null
    ? null
    : !readiness.review_enabled
      ? "off"
      : readiness.review_engines?.openai?.enabled
        ? `${readiness.review_engines.openai.key_slot ?? "explicit"} key`
        : "local";
  const canOperateCorpus = live && connectionConfirmed && status.writable !== false;
  const activeCorpusJobs = jobBoard.jobs.filter((job) => job.domain === "corpus" && ["queued", "running"].includes(job.status));
  const waitingCorpusJob = activeCorpusJobs.find((job) => job.status === "running") ?? activeCorpusJobs[0];
  const evaluationBlockedReason = !live ? null
    : healthKind === "api_down" ? "API unavailable"
    : !connectionConfirmed ? "Checking corpus…"
    : runtimeCounts?.database_connected === false ? "Database is unreachable"
    : runtimeCounts?.schema_status === "empty" ? "Database schema is empty"
    : runtimeCounts?.schema_status === "drifted" ? "Database schema is incompatible"
    : runtimeCounts?.schema_status === "unavailable" ? "Database schema is unavailable"
    : runtimeCounts?.writable === false ? "Source directory is not writable"
    : runtimeCounts?.database_connected !== true || !["ok", "compatible"].includes(runtimeCounts?.schema_status ?? "") ? "Readiness not confirmed"
    : !runtimeCounts?.chunks ? "Finish steps 1–2 to enable retrieval."
    : profile.strategy !== "lexical" && runtimeCounts.pending_embeddings !== 0 && !activeCorpusJobs.some((job) => job.kind === "backfill_embeddings") ? "Complete Embeddings (step 3) before evaluating."
    : profile.strategy !== "vector" && profile.lexical_ranker === "bm25" && runtimeCounts.bm25_ready !== true && !activeCorpusJobs.some((job) => job.kind === "rebuild_bm25") ? "Complete BM25 (step 4) before evaluating."
    : null;

  return (
    <section className="lab-shell build-workspace">
      <header className="page-heading">
        <div>
          <h1>{t("From filings to verified answers.")}</h1>
          <p>{t(live ? "Complete corpus setup to ask questions. Evaluation measures retrieval quality separately." : "Pick published filings to ask about, then explore how the corpus was prepared. Evaluation compares stored snapshots.")}</p>
        </div>
        <div className="page-badges">
          {environment && <span className="mode-badge">{environment}</span>}
          <span className={`mode-badge ${live ? "live" : ""}`}>{live ? t("Local operator") : t("Read-only portfolio")}</span>
        </div>
      </header>
      <nav className="lab-tabs" aria-label={t("Build sections")}>
        {TABS.filter(([id]) => live || id !== "jobs").map(([id, label]) => (
          <button key={id} type="button" aria-pressed={tab === id} title={live && id === "jobs" ? locale === "ko" ? "개발 모드 전용" : "DEV only" : undefined} onClick={() => onTabChange(id)}>{t(label)}{live && id === "jobs" && <span aria-hidden="true"><DevelopmentBadge locale={locale} compact /></span>}</button>
        ))}
      </nav>

      {!live && <p className="helper" role={publicCorpus.status === "error" ? "alert" : "status"}>{t(publicCorpus.status === "loading" ? "Loading published filings…" : publicCorpus.status === "error" ? "Published filings could not be loaded." : !publicCorpus.documents.length ? "No portfolio filings have been published yet." : "Choose from the published portfolio filings.")} <button type="button" className="button ghost" onClick={publicCorpus.refresh}>{t("Refresh")}</button></p>}
      <RetainedPanel active={tab === "pipeline"}><BuildPipeline
        pipeline={pipeline}
        documents={corpusDocuments}
        embeddingProvider={runtimeCounts?.provider ?? null}
        focusStage={focusStage}
        live={live}
        busy={busy}
        canOperateCorpus={canOperateCorpus}
        evaluationBlockedReason={evaluationBlockedReason}
        evaluationPreparationReady={!live || evaluationPreparation?.state === "ready"}
        evaluationSetup={live ? (action) => <PipelineGoldenPicker action={action} onManage={() => onNavigate({ view: "measure", tab: "golden" })} request={quickRequest} onOpenSources={() => { setFocusStage("filings"); onTabChange("pipeline"); }} onChecked={setEvaluationPreparation} onSelect={(suite_id, golden_revision_id) => { setEvaluationPreparation(null); setExperimentDefaults((current) => ({ ...current, suite_id, golden_revision_id })); }} /> : undefined}
        acquisition={live ? acquisition : publicDraft}
        corpusScope={publicProfile.corpus_scope}
        companies={referenceCompanies}
        onAcquisitionChange={live ? changeAcquisition : changePublicDraft}
        sources={corpus?.sources ?? []}
        manifests={manifests}
        answerModel={answerModelLabel}
        readiness={connectionConfirmed ? readiness : null}
        localModel={localModel}
        onOpenLocalSettings={onOpenLocalSettings}
        onLocalPrepared={onLocalPrepared}
        onCancelJob={onCancelJob}
        operationsAvailable={operationsAvailable}
        onRunOperation={onRunOperation}
        databaseConnected={runtimeCounts?.database_connected ?? null}
        schemaStatus={runtimeCounts?.schema_status ?? null}
        schemaMessage={runtimeCounts?.schema_message ?? null}
        writable={runtimeCounts?.writable ?? null}
        onDownload={downloadFilings}
        onDeleteSources={deleteSources}
        sourceDeletionDisabled={!canOperateCorpus || busy || activeCorpusJobs.length > 0 || jobsLoading || jobsStale}
        onIngestAll={() => void ingestAllManifests()}
        onBackfill={() => void queueCorpus({ kind: "backfill_embeddings", identifiers: [], years: [] })}
        onRebuildBm25={() => void queueCorpus({ kind: "rebuild_bm25", identifiers: [], years: [] })}
        onAsk={() => onNavigate({ view: "review" })}
        onAskScope={onAskScope}
        publicProgress={publicProgress}
        onConfirmScope={onConfirmScope}
        onPublicProgressChange={onPublicProgressChange}
        onRecheck={onRecheck}
        onEvaluate={() => void runQuickEvaluation()}
        onCompareSnapshots={() => onNavigate({ view: "measure", tab: live ? "snapshots" : "runs" })}
        onOpenDocuments={() => onTabChange("documents")}
        onOpenJobs={() => onTabChange("jobs")}
        onOpenStatus={() => onNavigate({ view: "system", tab: "status" })}
        onRefresh={() => live ? refresh("manual") : publicCorpus.refresh()}
      /></RetainedPanel>

      <RetainedPanel active={tab === "documents"}><DocumentInventory onInspectPipeline={() => { setFocusStage("index"); onTabChange("pipeline"); }} live={live} fallbackDocuments={[]} onOpenPipeline={(stage = "index") => { setFocusStage(stage); onTabChange("pipeline"); }} onOpenJobs={() => onTabChange("jobs")} /></RetainedPanel>

      <RetainedPanel active={tab === "jobs"}>{(live
        ? <JobCenter
        focusJobId={focusJobId}
            historyEnabled={live}
            onOpenPipeline={(stage) => { setFocusStage(stage); onTabChange("pipeline"); }}
            board={jobBoard}
            loading={jobsLoading}
            stale={jobsStale}
            onRetry={onRetryJob}
            onCancel={onCancelJob}
            onRefresh={onRefreshJobs}
            onOpenResult={(resultId) => onNavigate({ view: "measure", tab: "runs", resultId })}
          />
        : <div className="empty-state"><h2>{t("Jobs")}</h2><p>{t(DEV_ONLY_REASONS.jobs)}</p></div>)}</RetainedPanel>
    </section>
  );
}
