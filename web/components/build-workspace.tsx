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
import { selectedSourceState } from "@/lib/source-selection";
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
  onNavigate: (target: BuildNavigationTarget) => void;
}

const TABS: Array<[BuildTab, string]> = [
  ["pipeline", "Pipeline"],
  ["documents", "Documents"],
  ["jobs", "Jobs"],
];

const DEFAULT_ACQUISITION: AcquisitionForm = { identifiers: "", years: "" };

const UNKNOWN_CORPUS: CorpusCounts = { database_connected: null, schema_status: null, schema_message: null, documents: null, chunks: null, embedded_chunks: null, pending_embeddings: null, bm25_ready: null, writable: null, provider: null };

export function BuildWorkspace({ live, ready, readiness, healthKind, profile, jobBoard, jobsLoading, jobsStale = false, onRetryJob, onCancelJob, onRefreshJobs, onRecheck, operationsAvailable = false, onRunOperation, tab, onTabChange, onNavigate, focusStep }: BuildWorkspaceProps) {
  const { t, locale } = useI18n();
  const [focusStage, setFocusStage] = useState<string | null>(null);
  useEffect(() => { setFocusStage(focusStep == null ? null : String(focusStep)); }, [focusStep]);
  const { notify } = useNotifications();
  const environment = deploymentLabel(readiness?.environment);
  const [experimentDefaults, setExperimentDefaults] = useState<ExperimentDefaults>(DEFAULT_EXPERIMENT_DEFAULTS);
  // Fixtures seed only the public build; a live build waits for the administrator API.
  const [corpus, setCorpus] = useState<CorpusSnapshot | null>(() => (live ? null : { mode: "canned", ...CANNED_CORPUS, sources: [] }));
  /** True once `/admin/corpus` replaced the portfolio fixture. */
  const [adminLoaded, setAdminLoaded] = useState(false);
  const [registryCounts, setRegistryCounts] = useState<Record<string, number>>({});
  const [jobs, setJobs] = useState<EvaluationJob[]>(() => (live ? [] : [CANNED_JOB]));
  const [snapshotCount, setSnapshotCount] = useState(0);
  const [selectedSources, setSelectedSources] = useState<string[]>([]);
  const completedJobs = useRef(new Set<string>());
  const [busy, setBusy] = useState(false);
  const [historyWarning, setHistoryWarning] = useState("");
  const [corpusWarning, setCorpusWarning] = useState("");
  const [facetWarning, setFacetWarning] = useState("");
  const [acquisition, setAcquisition] = useState<AcquisitionForm>(DEFAULT_ACQUISITION);

  const draftInitialized = useRef(false);
  const draftDirty = useRef(false);
  const previousSources = useRef("");
  const [draftSyncAvailable, setDraftSyncAvailable] = useState(false);
  const serverDraft = useMemo<AcquisitionForm>(() => {
    const present = (corpus?.sources ?? []).filter((row) => row.on_disk);
    const draft = corpus?.acquisition_draft;
    return { identifiers: (draft?.identifiers ?? [...new Set(present.map((row) => row.issuer))]).join(" "), years: (draft?.years ?? [...new Set(present.map((row) => row.fiscal_year))]).join(" ") };
  }, [corpus]);
  useEffect(() => {
    if (!corpus) return;
    const signature = JSON.stringify([corpus.sources ?? [], serverDraft]);
    if (!draftInitialized.current || !draftDirty.current) {
      setAcquisition(serverDraft);
      setDraftSyncAvailable(false);
      draftInitialized.current = true;
    } else if (previousSources.current !== signature) {
      setDraftSyncAvailable(true);
    }
    previousSources.current = signature;
  }, [corpus, serverDraft]);

  useEffect(() => {
    setExperimentDefaults(loadExperimentDefaults());
  }, []);

  /**
   * Reload the four administrator reads independently: a failed read keeps the last known state and
   * leaves an inline notice, so one busy endpoint never blanks the others. Only a refresh the user
   * asked for (`manual`) raises a toast; automatic refreshes after jobs stay quiet.
   */
  async function refresh(mode: "auto" | "manual" = "auto") {
    if (!live) return;
    setHistoryWarning("");
    setCorpusWarning("");
    setFacetWarning("");
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
    } else {
      setCorpusWarning(t("Corpus status could not be refreshed: {message}", { message: reasonOf(corpusSnapshot) }));
      failures.push(reasonOf(corpusSnapshot));
    }
    if (facets.status === "fulfilled") {
      const registries = Array.isArray(facets.value.registries) ? facets.value.registries : [];
      setRegistryCounts(Object.fromEntries(registries.filter((item) => typeof item.value === "string" && typeof item.count === "number").map((item) => [item.value, item.count])));
    } else {
      setFacetWarning(t("Document filters could not be loaded: {message}", { message: reasonOf(facets) }));
      failures.push(reasonOf(facets));
    }
    if (snapshotRows.status === "fulfilled") setSnapshotCount(Array.isArray(snapshotRows.value) ? snapshotRows.value.length : 0);
    else failures.push(reasonOf(snapshotRows));
    if (jobRows.status === "rejected" || snapshotRows.status === "rejected") {
      setHistoryWarning(t("Some history could not be loaded. Corpus status is shown separately."));
    }
    if (mode === "manual" && failures.length) notify(failures[0], "error", "build-refresh");
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
    const selection = selectedSourceState(corpus?.sources ?? [], acquisition);
    if (!selection.complete) { notify(t("Download missing sources in Filings first."), "warning", "corpus-operation"); return; }
    const ordered = [{ identifiers: splitList(acquisition.identifiers), years: splitList(acquisition.years).map(Number) }];
    if (!ordered.length) { notify(t("Select processing sources first."), "warning", "corpus-operation"); return; }
    setBusy(true);
    try {
      for (const item of ordered) await queueCorpusOperation({ kind: "ingest_selected", ...item });
      onRefreshJobs();
      notify(t("Selections queued for ingest: {count}.", { count: ordered.length.toLocaleString(locale) }), "success", "corpus-operation");
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : t("Corpus operation failed."), "error", "corpus-operation");
    } finally {
      setBusy(false);
    }
  }

  /** Preserve explicit Advanced selection batching independently of the Filings draft. */
  async function ingestAdvanced() {
    if (!live) return;
    setBusy(true);
    try {
      for (const manifest of manifests.filter((row) => row.valid)) {
        for (const selection of manifest.selections.filter((row) => selectedSources.includes(`${manifest.name}:${row.selection_id}`))) {
          await queueCorpusOperation({ kind: "ingest_manifest", manifest: manifest.name, selection_id: selection.selection_id, identifiers: [], years: [] });
          onRefreshJobs();
        }
      }
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : t("Corpus operation failed."), "error", "corpus-operation");
    } finally { setBusy(false); }
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
    sourceSelection: selectedSourceState(corpus?.sources ?? [], acquisition),
    registryCounts,
    jobs: Array.isArray(jobBoard.jobs) ? jobBoard.jobs : [],
    evaluationResults,
    snapshots: snapshotCount,
  }), [live, healthKind, readiness, adminLoaded, status, manifests, corpus, acquisition, registryCounts, jobBoard.jobs, evaluationResults, snapshotCount]);
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
      {corpusWarning && <p className="notice" role="status">{corpusWarning}</p>}
      {facetWarning && <p className="notice" role="status">{facetWarning}</p>}
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
        onAcquisitionChange={(next) => { draftDirty.current = true; setAcquisition(next); }}
        onSyncAcquisition={draftSyncAvailable ? () => { draftDirty.current = false; setAcquisition(serverDraft); setDraftSyncAvailable(false); } : undefined}
        sources={corpus?.sources ?? []}
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
        onIngestAdvanced={() => void ingestAdvanced()}
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
        onRefresh={() => refresh("manual")}
      /></RetainedPanel>

      <RetainedPanel active={tab === "documents"}><DocumentInventory onInspectPipeline={() => { setFocusStage("index"); onTabChange("pipeline"); }} live={live} fallbackDocuments={live ? [] : CANNED_CORPUS.documents} onOpenPipeline={(stage = "index") => { setFocusStage(stage); onTabChange("pipeline"); }} onOpenJobs={() => onTabChange("jobs")} /></RetainedPanel>

      <RetainedPanel active={tab === "jobs"}>{(live
        ? <JobCenter
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
        : <div className="empty-state"><h2>{t("Jobs")}</h2><p>{t("Jobs run on the local operator build.")}</p></div>)}</RetainedPanel>
    </section>
  );
}
