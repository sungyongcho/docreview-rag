"use client";
import { useI18n } from "@/lib/i18n";


import { useEffect, useMemo, useRef, useState } from "react";

import { RetainedPanel } from "@/components/retained-panel";
import { DevelopmentBadge } from "@/components/development-badge";
import { acquisitionGroups } from "@/lib/acquisition-catalog";
import { BuildPipeline, splitList, type AcquisitionForm } from "@/components/build-pipeline";
import { DocumentInventory } from "@/components/document-inventory";
import { JobCenter } from "@/components/job-center";
import { useNotifications } from "@/components/notifications";
import {
  getAdminSnapshots,
  getCorpusSnapshot,
  getDocumentFacets,
  getEvaluationJobs,
  getGoldenRevisions,
  getPublishedSnapshots,
  queueCorpusOperation,
  queueEvaluation,
} from "@/lib/api";
import { CANNED_CORPUS, CANNED_JOB } from "@/lib/canned";
import { deploymentLabel } from "@/lib/deployment";
import { derivePipeline } from "@/lib/pipeline";
import { loadExperimentDefaults } from "@/lib/storage";
import type {
  CorpusDocument,
  CorpusCounts,
  EvaluationJob,
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
  | { view: "measure"; tab: "snapshots" | "runs"; resultId?: number };

export interface BuildWorkspaceProps {
  live: boolean;
  ready: boolean;
  readiness: Readiness | null;
  healthKind: RuntimeHealthKind;
  profile: RetrievalProfile;
  jobBoard: OperatorJobBoard;
  jobsLoading: boolean;
  onRetryJob: (jobId: string) => void;
  onCancelJob: (jobId: string) => void;
  onRefreshJobs: () => void;
  onRecheck: () => void;
  /** Local Operations reachable from this build; enables the runtime strip's service buttons. */
  operationsAvailable?: boolean;
  onRunOperation?: (commandId: string) => void;
  tab: BuildTab;
  onTabChange: (tab: BuildTab) => void;
  focusStep?: number | null;
  onNavigate: (target: BuildNavigationTarget) => void;
}

const TABS: Array<[BuildTab, string]> = [
  ["pipeline", "Pipeline"],
  ["documents", "Documents"],
  ["jobs", "Jobs"],
];

const DEFAULT_ACQUISITION: AcquisitionForm = { identifiers: "NVDA AMD", years: "2023 2024" };

const UNKNOWN_CORPUS: CorpusCounts = { database_connected: null, schema_status: null, schema_message: null, documents: null, chunks: null, embedded_chunks: null, pending_embeddings: null, bm25_ready: null, writable: null, provider: null };

export function BuildWorkspace({ live, ready, readiness, healthKind, profile, jobBoard, jobsLoading, onRetryJob, onCancelJob, onRefreshJobs, onRecheck, operationsAvailable = false, onRunOperation, tab, onTabChange, onNavigate, focusStep }: BuildWorkspaceProps) {
  const { t, locale } = useI18n();
  const [focusStage, setFocusStage] = useState<string | null>(null);
  useEffect(() => { if (focusStep != null) setFocusStage(String(focusStep)); }, [focusStep]);
  const { notify } = useNotifications();
  const environment = deploymentLabel(readiness?.environment);
  const [experimentDefaults, setExperimentDefaults] = useState<ExperimentDefaults>(DEFAULT_EXPERIMENT_DEFAULTS);
  // Fixtures seed only the public build; a live build waits for the administrator API.
  const [corpus, setCorpus] = useState<CorpusSnapshot | null>(() => (live ? null : { mode: "canned", ...CANNED_CORPUS }));
  /** True once `/admin/corpus` replaced the portfolio fixture. */
  const [adminLoaded, setAdminLoaded] = useState(false);
  const [registryCounts, setRegistryCounts] = useState<Record<string, number>>({});
  const [jobs, setJobs] = useState<EvaluationJob[]>(() => (live ? [] : [CANNED_JOB]));
  const [snapshotCount, setSnapshotCount] = useState(0);
  const [selectedSources, setSelectedSources] = useState<string[]>([]);
  const completedJobs = useRef(new Set<string>());
  const [busy, setBusy] = useState(false);
  const [historyWarning, setHistoryWarning] = useState("");
  const [acquisition, setAcquisition] = useState<AcquisitionForm>(DEFAULT_ACQUISITION);

  useEffect(() => {
    setExperimentDefaults(loadExperimentDefaults());
  }, []);

  async function refresh() {
    if (!live) return;
    setHistoryWarning("");
    const historyUnavailable = () => { setHistoryWarning(t("Some history could not be loaded. Corpus status is shown separately.")); return []; };
    try {
      const [jobRows, corpusSnapshot, facets] = await Promise.all([
        getEvaluationJobs().catch(historyUnavailable), getCorpusSnapshot(), getDocumentFacets().catch(() => null),
      ]);
      setJobs(Array.isArray(jobRows) ? jobRows : []);
      setCorpus(corpusSnapshot);
      setAdminLoaded(true);
      const registries = facets && Array.isArray(facets.registries) ? facets.registries : [];
      setRegistryCounts(Object.fromEntries(registries.filter((item) => typeof item.value === "string" && typeof item.count === "number").map((item) => [item.value, item.count])));
      const snapshotRows = await getAdminSnapshots().catch(historyUnavailable);
      setSnapshotCount(Array.isArray(snapshotRows) ? snapshotRows.length : 0);
      return true;
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : t("Refresh failed."), "error", "build-refresh");
      return false;
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
      notify(t("Corpus operation queued."), "success", "corpus-operation");
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : t("Corpus operation failed."), "error", "corpus-operation");
    } finally {
      setBusy(false);
    }
  }

  /** Queue the exact selected manifest and selection pairs through the shared job API. */
  async function ingestAllManifests() {
    if (!live) return;
    const ordered = manifests.flatMap((manifest) => manifest.valid ? manifest.selections.filter((selection) => selectedSources.includes(`${manifest.name}:${selection.selection_id}`)).map((selection) => ({ manifest: manifest.name, selection_id: selection.selection_id })) : []);
    if (!ordered.length) { notify(t("Select processing sources first."), "warning", "corpus-operation"); return; }
    setBusy(true);
    try {
      for (const item of ordered) await queueCorpusOperation({ kind: "ingest_manifest", ...item, identifiers: [], years: [] });
      onRefreshJobs();
      notify(t("Selections queued for ingest: {count}.", { count: ordered.length.toLocaleString(locale) }), "success", "corpus-operation");
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : t("Corpus operation failed."), "error", "corpus-operation");
    } finally {
      setBusy(false);
    }
  }

  async function downloadFilings() {
    if (!live) return;
    setBusy(true);
    let queued = 0;
    try {
      const years = splitList(acquisition.years).map(Number).filter(Number.isInteger);
      for (const group of acquisitionGroups(splitList(acquisition.identifiers), referenceCompanies)) {
        await queueCorpusOperation({ kind: group.registry === "sec" ? "acquire_edgar" : "acquire_dart", identifiers: group.identifiers, years });
        queued += 1;
        onRefreshJobs();
      }
      notify(t("Acquisition jobs queued: {count}.", { count: queued }), "success", "corpus-operation");
    } catch (reason) {
      notify(t("Acquisition stopped after {count} queued jobs. Check Jobs before retrying.", { count: queued }) + " " + (reason instanceof Error ? reason.message : t("Corpus operation failed.")), "error", "corpus-operation");
    } finally { setBusy(false); }
  }

  async function runQuickEvaluation() {
    if (!live) { notify(t("Production experiment controls are locked. Compare published snapshots instead."), "warning", "prod-eval"); return; }
    if (!ready) return;
    setBusy(true);
    try {
      // The saved default revision applies only when it still exists for the suite;
      // otherwise the canonical JSON is measured, as Measure › Runs does.
      const revisions = await getGoldenRevisions(experimentDefaults.suite_id).catch(() => []);
      const defaultRevision = experimentDefaults.golden_revision_id;
      const goldenRevisionId = Array.isArray(revisions) && revisions.some((row) => row.revision_id === defaultRevision) ? defaultRevision : null;
      const job = await queueEvaluation({
        suite_id: experimentDefaults.suite_id,
        golden_revision_id: goldenRevisionId,
        mode: "quick",
        profile,
        target_tokens: [1024, 2048],
        strategies: ["lexical", "vector", "hybrid"],
        lexical_rankers: ["ts_rank_cd", "bm25"],
      });
      setJobs((current) => [job, ...current]);
      onRefreshJobs();
      notify(t("Evaluation queued."), "success", "evaluation-queued");
      onTabChange("jobs");
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : t("Evaluation failed."), "error", "evaluation");
    } finally {
      setBusy(false);
    }
  }

  const status = useMemo(() => corpus?.status ?? UNKNOWN_CORPUS, [corpus]);
  const manifests = useMemo(() => corpus?.manifests ?? [], [corpus]);
  const corpusDocuments = useMemo<CorpusDocument[]>(() => {
    if (!live) return CANNED_CORPUS.documents;
    return corpus?.documents ?? [];
  }, [live, corpus]);
  const referenceCompanies = manifests.flatMap((manifest) => manifest.issuers ?? []);
  const selectedDocumentCount = new Set(manifests.flatMap((manifest) => manifest.selections.filter((selection) => selectedSources.includes(`${manifest.name}:${selection.selection_id}`)).flatMap((selection) => selection.document_ids))).size;
  const evaluationResults = jobs.filter((job) => job.status === "succeeded" && job.result_id !== null).length;
  const pipeline = useMemo(() => derivePipeline({
    live,
    healthKind,
    readiness,
    corpus: live && adminLoaded ? status : null,
    manifests,
    registryCounts,
    jobs: Array.isArray(jobBoard.jobs) ? jobBoard.jobs : [],
    evaluationResults,
    snapshots: snapshotCount,
  }), [live, healthKind, readiness, adminLoaded, status, manifests, registryCounts, jobBoard.jobs, evaluationResults, snapshotCount]);
  /** Runtime flags for the strip: the administrator snapshot once loaded, otherwise `/ready`. */
  const runtimeCounts: CorpusCounts | null = live && adminLoaded ? status : readiness?.corpus ?? null;
  const answerModelLabel = readiness === null
    ? null
    : !readiness.review_enabled
      ? "off"
      : readiness.review_engines?.openai?.enabled
        ? `${readiness.review_engines.openai.key_slot ?? "explicit"} key`
        : "local";
  const canOperateCorpus = live && status.writable !== false;

  return (
    <section className="lab-shell build-workspace">
      {historyWarning && <p className="notice" role="status">{historyWarning}</p>}
      <header className="page-heading">
        <div>
          <h1>{t("From filings to verified answers.")}</h1>
          <p>{t("Complete corpus setup to ask questions. Evaluation measures retrieval quality separately.")}</p>
        </div>
        <div className="page-badges">
          <span className="mode-badge">{environment}</span>
          <span className={`mode-badge ${live ? "live" : ""}`}>{live ? t("Local operator") : t("Read-only portfolio")}</span>
        </div>
      </header>
      <nav className="lab-tabs" aria-label={t("Build sections")}>
        {TABS.map(([id, label]) => (
          <button key={id} type="button" aria-pressed={tab === id} title={live && id === "jobs" ? locale === "ko" ? "개발 모드 전용" : "DEV only" : undefined} onClick={() => onTabChange(id)}>{t(label)}{live && id === "jobs" && <span aria-hidden="true"><DevelopmentBadge locale={locale} compact /></span>}</button>
        ))}
      </nav>

      <RetainedPanel active={tab === "pipeline"}><BuildPipeline
        pipeline={pipeline}
        documents={corpusDocuments}
        embeddingProvider={runtimeCounts?.provider ?? null}
        focusStage={focusStage}
        live={live}
        busy={busy}
        canOperateCorpus={canOperateCorpus}
        acquisition={acquisition}
        companies={referenceCompanies}
        onAcquisitionChange={setAcquisition}
        manifests={manifests}
        selectedSources={selectedSources}
        selectedDocumentCount={selectedDocumentCount}
        onToggleSource={(key) => setSelectedSources((current) => current.includes(key) ? current.filter((item) => item !== key) : [...current, key])}
        registryCounts={registryCounts}
        answerModel={answerModelLabel}
        onCancelJob={onCancelJob}
        operationsAvailable={operationsAvailable}
        onRunOperation={onRunOperation}
        databaseConnected={runtimeCounts?.database_connected ?? null}
        schemaStatus={runtimeCounts?.schema_status ?? null}
        schemaMessage={runtimeCounts?.schema_message ?? null}
        writable={runtimeCounts?.writable ?? null}
        onDownload={downloadFilings}
        onIngestAll={() => void ingestAllManifests()}
        onIngest={(name, selectionId) => void queueCorpus({ kind: "ingest_manifest", manifest: name, selection_id: selectionId, identifiers: [], years: [] })}
        onBackfill={() => void queueCorpus({ kind: "backfill_embeddings", identifiers: [], years: [] })}
        onRebuildBm25={() => void queueCorpus({ kind: "rebuild_bm25", identifiers: [], years: [] })}
        onAsk={() => onNavigate({ view: "review" })}
        onRecheck={onRecheck}
        onEvaluate={() => void runQuickEvaluation()}
        onCompareSnapshots={() => onNavigate({ view: "measure", tab: "snapshots" })}
        onOpenDocuments={() => onTabChange("documents")}
        onOpenJobs={() => onTabChange("jobs")}
        onOpenStatus={() => onNavigate({ view: "system", tab: "status" })}
        onRefresh={refresh}
      /></RetainedPanel>

      <RetainedPanel active={tab === "documents"}><DocumentInventory onInspectPipeline={() => { setFocusStage("index"); onTabChange("pipeline"); }} live={live} fallbackDocuments={live ? [] : CANNED_CORPUS.documents} onOpenPipeline={(stage = "index") => { setFocusStage(stage); onTabChange("pipeline"); }} onOpenJobs={() => onTabChange("jobs")} /></RetainedPanel>

      <RetainedPanel active={tab === "jobs"}>{(live
        ? <JobCenter
            historyEnabled={live}
            onOpenPipeline={(stage) => { setFocusStage(stage); onTabChange("pipeline"); }}
            board={jobBoard}
            loading={jobsLoading}
            onRetry={onRetryJob}
            onCancel={onCancelJob}
            onRefresh={onRefreshJobs}
            onOpenResult={(resultId) => onNavigate({ view: "measure", tab: "runs", resultId })}
          />
        : <div className="empty-state"><h2>{t("Jobs")}</h2><p>{t("Jobs run on the local operator build.")}</p></div>)}</RetainedPanel>
    </section>
  );
}
