"use client";

import { useEffect, useMemo, useState } from "react";

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
  AdminDocument,
  CorpusCounts,
  EvaluationJob,
  ExperimentDefaults,
  ManifestSummary,
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
  onNavigate: (target: BuildNavigationTarget) => void;
}

const TABS: Array<[BuildTab, string]> = [
  ["pipeline", "Pipeline"],
  ["documents", "Documents"],
  ["jobs", "Jobs"],
];

const DEFAULT_ACQUISITION: AcquisitionForm = { registry: "sec", identifiers: "NVDA AMD", years: "2023 2024" };

/** Read the `/admin/corpus` status object defensively; unknown fields become `null`. */
function toCorpusCounts(value: unknown): CorpusCounts {
  const source = (typeof value === "object" && value !== null ? value : {}) as Record<string, unknown>;
  const bool = (key: string) => (typeof source[key] === "boolean" ? source[key] as boolean : null);
  const num = (key: string) => (typeof source[key] === "number" ? source[key] as number : null);
  const str = (key: string) => (typeof source[key] === "string" ? source[key] as string : null);
  return {
    database_connected: bool("database_connected"),
    schema_status: str("schema_status"),
    schema_message: str("schema_message"),
    documents: num("documents"),
    chunks: num("chunks"),
    embedded_chunks: num("embedded_chunks"),
    pending_embeddings: num("pending_embeddings"),
    bm25_ready: bool("bm25_ready"),
    writable: bool("writable"),
    provider: str("provider"),
  };
}

function toManifests(value: unknown): ManifestSummary[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (typeof item !== "object" || item === null || typeof (item as Record<string, unknown>).name !== "string") return [];
    const row = item as Record<string, unknown>;
    return [{
      name: row.name as string,
      registry: typeof row.registry === "string" ? row.registry : null,
      documents: typeof row.documents === "number" ? row.documents : null,
      valid: row.valid === true,
      sources_present: typeof row.sources_present === "number" ? row.sources_present : null,
    }];
  });
}

/** `manifest.json` (SEC) first, then the registry manifests by name: the README ingest order. */
function ingestOrder(manifests: ManifestSummary[]): ManifestSummary[] {
  return manifests
    .filter((item) => item.valid)
    .toSorted((left, right) => left.name === "manifest.json" ? -1 : right.name === "manifest.json" ? 1 : left.name.localeCompare(right.name));
}

export function BuildWorkspace({ live, ready, readiness, healthKind, profile, jobBoard, jobsLoading, onRetryJob, onCancelJob, onRefreshJobs, onRecheck, operationsAvailable = false, onRunOperation, tab, onTabChange, onNavigate }: BuildWorkspaceProps) {
  const { notify } = useNotifications();
  const [environment, setEnvironment] = useState<"DEV" | "PROD">("PROD");
  const [experimentDefaults, setExperimentDefaults] = useState<ExperimentDefaults>(DEFAULT_EXPERIMENT_DEFAULTS);
  // Fixtures seed only the public build; a live build waits for the administrator API.
  const [corpus, setCorpus] = useState<Record<string, unknown>>(() => (live ? {} : { ...CANNED_CORPUS }));
  /** True once `/admin/corpus` replaced the portfolio fixture. */
  const [adminLoaded, setAdminLoaded] = useState(false);
  const [registryCounts, setRegistryCounts] = useState<Record<string, number>>({});
  const [jobs, setJobs] = useState<EvaluationJob[]>(() => (live ? [] : [CANNED_JOB]));
  const [snapshotCount, setSnapshotCount] = useState(0);
  const [busy, setBusy] = useState(false);
  const [acquisition, setAcquisition] = useState<AcquisitionForm>(DEFAULT_ACQUISITION);

  useEffect(() => {
    setEnvironment(deploymentLabel(window.location.hostname));
    setExperimentDefaults(loadExperimentDefaults());
  }, []);

  async function refresh() {
    if (!live) return;
    try {
      const [jobRows, corpusSnapshot, facets] = await Promise.all([
        getEvaluationJobs(), getCorpusSnapshot(), getDocumentFacets().catch(() => null),
      ]);
      setJobs(Array.isArray(jobRows) ? jobRows : []);
      setCorpus(typeof corpusSnapshot === "object" && corpusSnapshot !== null ? corpusSnapshot : {});
      setAdminLoaded(true);
      const registries = facets && Array.isArray(facets.registries) ? facets.registries : [];
      setRegistryCounts(Object.fromEntries(registries.filter((item) => typeof item.value === "string" && typeof item.count === "number").map((item) => [item.value, item.count])));
      const snapshotRows = await getAdminSnapshots();
      setSnapshotCount(Array.isArray(snapshotRows) ? snapshotRows.length : 0);
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Refresh failed.", "error", "build-refresh");
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
    if (live) return;
    void getPublishedSnapshots().then((rows) => setSnapshotCount(Array.isArray(rows) ? rows.length : 0)).catch(() => undefined);
  }, [live]);

  async function queueCorpus(body: Record<string, unknown>) {
    if (!live) return;
    setBusy(true);
    try {
      await queueCorpusOperation(body);
      onRefreshJobs();
      notify("Corpus operation queued.", "success", "corpus-operation");
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Corpus operation failed.", "error", "corpus-operation");
    } finally {
      setBusy(false);
    }
  }

  /** Queue one `ingest_manifest` job per valid manifest, in pipeline order, as a single operator action. */
  async function ingestAllManifests() {
    if (!live) return;
    const ordered = ingestOrder(manifests);
    if (!ordered.length) { notify("No valid manifest to ingest.", "warning", "corpus-operation"); return; }
    setBusy(true);
    try {
      for (const item of ordered) await queueCorpusOperation({ kind: "ingest_manifest", manifest: item.name });
      onRefreshJobs();
      notify(`Ingest queued for ${ordered.length} manifest${ordered.length === 1 ? "" : "s"}.`, "success", "corpus-operation");
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Corpus operation failed.", "error", "corpus-operation");
    } finally {
      setBusy(false);
    }
  }

  function downloadFilings() {
    void queueCorpus({
      kind: acquisition.registry === "sec" ? "acquire_edgar" : "acquire_dart",
      identifiers: splitList(acquisition.identifiers),
      years: splitList(acquisition.years).map(Number).filter(Number.isInteger),
    });
  }

  async function runQuickEvaluation() {
    if (!live) { notify("Production experiment controls are locked. Compare published snapshots instead.", "warning", "prod-eval"); return; }
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
        target_text_chars: [500, 1200],
        strategies: ["lexical", "vector", "hybrid"],
        lexical_rankers: ["ts_rank_cd", "bm25"],
      });
      setJobs((current) => [job, ...current]);
      onRefreshJobs();
      notify("Evaluation queued.", "success", "evaluation-queued");
      onTabChange("jobs");
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Evaluation failed.", "error", "evaluation");
    } finally {
      setBusy(false);
    }
  }

  const status = useMemo(() => toCorpusCounts(corpus.status), [corpus]);
  const manifests = useMemo(() => toManifests(corpus.manifests), [corpus]);
  const corpusDocuments = useMemo<AdminDocument[]>(() => {
    if (!live) return CANNED_CORPUS.documents;
    return Array.isArray(corpus.documents) ? corpus.documents as AdminDocument[] : [];
  }, [live, corpus]);
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
      <header className="page-heading">
        <div>
          <p className="eyebrow">Build</p>
          <h1>From filings to verified answers.</h1>
          <p>Each step feeds the next. Finish anything marked Action needed, then ask.</p>
        </div>
        <div className="page-badges">
          <span className="mode-badge">{environment}</span>
          <span className={`mode-badge ${live ? "live" : ""}`}>{live ? "Local operator" : "Read-only portfolio"}</span>
        </div>
      </header>
      <nav className="lab-tabs" aria-label="Build sections">
        {TABS.map(([id, label]) => (
          <button key={id} type="button" aria-pressed={tab === id} onClick={() => onTabChange(id)}>{label}</button>
        ))}
      </nav>

      {tab === "pipeline" && <BuildPipeline
        pipeline={pipeline}
        live={live}
        busy={busy}
        canOperateCorpus={canOperateCorpus}
        acquisition={acquisition}
        onAcquisitionChange={setAcquisition}
        manifests={manifests}
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
        onIngest={(name) => void queueCorpus({ kind: "ingest_manifest", manifest: name })}
        onBackfill={() => void queueCorpus({ kind: "backfill_embeddings" })}
        onRebuildBm25={() => void queueCorpus({ kind: "rebuild_bm25" })}
        onAsk={() => onNavigate({ view: "review" })}
        onRecheck={onRecheck}
        onEvaluate={() => void runQuickEvaluation()}
        onCompareSnapshots={() => onNavigate({ view: "measure", tab: "snapshots" })}
        onOpenDocuments={() => onTabChange("documents")}
        onOpenJobs={() => onTabChange("jobs")}
        onOpenStatus={() => onNavigate({ view: "system", tab: "status" })}
        onRefresh={() => void refresh()}
      />}

      {tab === "documents" && <DocumentInventory live={live} fallbackDocuments={corpusDocuments} />}

      {tab === "jobs" && (live
        ? <JobCenter
            board={jobBoard}
            loading={jobsLoading}
            onRetry={onRetryJob}
            onCancel={onCancelJob}
            onRefresh={onRefreshJobs}
            onOpenResult={(resultId) => onNavigate({ view: "measure", tab: "runs", resultId })}
          />
        : <div className="empty-state"><h2>Jobs</h2><p>Jobs run on the local operator build.</p></div>)}
    </section>
  );
}
