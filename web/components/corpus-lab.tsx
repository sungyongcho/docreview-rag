"use client";

import { Activity, Beaker, Braces, Database, FileSearch, Play, RefreshCw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import {
  apiBase,
  compareEvaluations,
  compareSnapshots,
  createGoldenDraft,
  createSnapshot,
  getAdminDocuments,
  getAdminSnapshots,
  getCorpusSnapshot,
  getEvaluationJobs,
  getEvaluationResult,
  getGoldenSuites,
  getGoldenCanonical,
  getGoldenRevisions,
  getProviderUsage,
  getPublishedSnapshots,
  getDocumentDetail,
  getDocumentFacets,
  queueEvaluation,
  queueCorpusOperation,
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
  GoldenSuite,
  RetrievalProfile,
  ProviderUsage,
  SuiteId,
  PublishedSnapshot,
  GoldenRevision,
  GoldenCanonical,
  OperatorJob,
  OperatorJobBoard,
  SnapshotComparison,
  AdminDocument,
  DocumentDetail,
  DocumentEmbeddingStatus,
  DocumentFacets,
} from "@/lib/types";
import { useNotifications } from "@/components/notifications";
import { loadExperimentDefaults } from "@/lib/storage";

type LabTab = "overview" | "documents" | "golden" | "experiments" | "snapshots" | "jobs" | "api" | "usage";

const TABS: Array<[LabTab, string]> = [
  ["overview", "Overview"],
  ["documents", "Documents"],
  ["golden", "Golden Tests"],
  ["experiments", "Experiments"],
  ["snapshots", "Snapshots"],
  ["jobs", "Jobs"],
  ["api", "API Inspector"],
];

const EMPTY_USAGE: ProviderUsage = {
  runs: 0,
  requests: 0,
  input_tokens: 0,
  cached_input_tokens: 0,
  cache_write_input_tokens: 0,
  output_tokens: 0,
  reasoning_tokens: 0,
  estimated_cost_usd: "0",
  latest_run_at: null,
  models: [],
};

const EMPTY_DOCUMENT_FACETS: DocumentFacets = {
  registries: [],
  issuers: [],
  years: [],
  languages: [],
  forms: [],
  parse_statuses: [],
  embedding_statuses: [],
  snapshots: [],
};

type DocumentGroup = "none" | "registry" | "issuer" | "fiscal_year";

export function deploymentLabel(hostname: string): "DEV" | "PROD" {
  const normalized = hostname.toLowerCase().replace(/^\[|\]$/g, "");
  return normalized === "localhost"
    || normalized === "127.0.0.1"
    || normalized === "::1"
    || normalized.endsWith(".localhost")
    ? "DEV"
    : "PROD";
}

interface CorpusLabProps {
  live: boolean;
  ready?: boolean;
  profile: RetrievalProfile;
  onProfileChange: (profile: RetrievalProfile) => void;
  onApplyProfile: (profile: RetrievalProfile, source?: string) => void;
  onApplySnapshot: (snapshot: PublishedSnapshot) => void;
  jobBoard: OperatorJobBoard;
  jobsLoading: boolean;
  onRetryJob: (jobId: string) => void;
  onCancelJob: (jobId: string) => void;
  onRefreshJobs: () => void;
}

export function CorpusLab({ live, ready = true, profile, onProfileChange, onApplyProfile, onApplySnapshot, jobBoard, jobsLoading, onRetryJob, onCancelJob, onRefreshJobs }: CorpusLabProps) {
  const { notify } = useNotifications();
  const [experimentDefaults] = useState(loadExperimentDefaults);
  const [tab, setTab] = useState<LabTab>("overview");
  const [suites, setSuites] = useState<GoldenSuite[]>(CANNED_SUITES);
  const [suiteId, setSuiteId] = useState<SuiteId>(experimentDefaults.suite_id);
  const [jobs, setJobs] = useState<EvaluationJob[]>([CANNED_JOB]);
  const [comparison, setComparison] = useState<EvaluationComparison>(CANNED_COMPARISON);
  const [corpus, setCorpus] = useState<Record<string, unknown>>({
    status: { documents: 22, chunks: 10452, embedded_chunks: 10452, bm25_ready: true },
    documents: [
      { doc_id: "NVDA-FY2024", registry: "sec", issuer: "NVDA", fiscal_year: 2024, language: "en", chunk_count: 612, parse_status: "parsed" },
      { doc_id: "005930-FY2024", registry: "dart", issuer: "005930", fiscal_year: 2024, language: "ko", chunk_count: 668, parse_status: "parsed" },
    ],
  });
  const [busy, setBusy] = useState(false);
  const [mode, setMode] = useState<"quick" | "matrix">(experimentDefaults.mode);
  const [chunkTargets, setChunkTargets] = useState("500 1200");
  const [rawRequest, setRawRequest] = useState("");
  const [rawResponse, setRawResponse] = useState("");
  const [registry, setRegistry] = useState<"sec" | "dart">("sec");
  const [identifiers, setIdentifiers] = useState("NVDA AMD");
  const [years, setYears] = useState("2023 2024");
  const [manifest, setManifest] = useState("manifest.json");
  const [usage, setUsage] = useState<ProviderUsage>(EMPTY_USAGE);
  const [usageError, setUsageError] = useState("");
  const [environment, setEnvironment] = useState<"DEV" | "PROD">("PROD");
  const [selectedResultId, setSelectedResultId] = useState<number | null>(null);
  const [resultDetail, setResultDetail] = useState<EvaluationResultDetail | null>(null);
  const [snapshots, setSnapshots] = useState<PublishedSnapshot[]>([]);
  const [snapshotIds, setSnapshotIds] = useState<[number | null, number | null]>([experimentDefaults.baseline_snapshot_id, experimentDefaults.snapshot_id]);
  const [documentQuery, setDocumentQuery] = useState("");
  const [documentRegistry, setDocumentRegistry] = useState("all");
  const [documentIssuer, setDocumentIssuer] = useState("all");
  const [documentYear, setDocumentYear] = useState("all");
  const [documentLanguage, setDocumentLanguage] = useState("all");
  const [documentForm, setDocumentForm] = useState("all");
  const [documentParseStatus, setDocumentParseStatus] = useState("all");
  const [documentEmbeddingStatus, setDocumentEmbeddingStatus] = useState<"all" | DocumentEmbeddingStatus>("all");
  const [documentSnapshot, setDocumentSnapshot] = useState("all");
  const [documentSort, setDocumentSort] = useState("doc_id");
  const [documentDescending, setDocumentDescending] = useState(false);
  const [documentGroup, setDocumentGroup] = useState<DocumentGroup>("none");
  const [documentDetail, setDocumentDetail] = useState<DocumentDetail | null>(null);
  const [documentFacets, setDocumentFacets] = useState<DocumentFacets>(EMPTY_DOCUMENT_FACETS);
  const [documentTotal, setDocumentTotal] = useState(0);
  const [documentNextCursor, setDocumentNextCursor] = useState<string | null>(null);
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

  useEffect(() => {
    setRawRequest(JSON.stringify(evaluationRequest, null, 2));
  }, [evaluationRequest]);

  async function refresh() {
    if (!live) return;
    try {
      const [suiteRows, jobRows, corpusSnapshot] = await Promise.all([
        getGoldenSuites(), getEvaluationJobs(), getCorpusSnapshot(),
      ]);
      setSuites(suiteRows);
      setJobs(jobRows);
      setCorpus(corpusSnapshot);
      const documentPage = await getAdminDocuments(new URLSearchParams({ limit: "100" }));
      setCorpus((current) => ({ ...current, documents: documentPage.documents }));
      const snapshotRows = await getAdminSnapshots();
      setSnapshots(Array.isArray(snapshotRows) ? snapshotRows : []);
      setUsageError("");
      try {
        setUsage(await getProviderUsage());
      } catch (reason) {
        setUsageError(reason instanceof Error ? reason.message : "Usage could not be loaded.");
      }
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Refresh failed.", "error", "lab-refresh");
    }
  }

  useEffect(() => {
    void refresh();
  }, [live]);
  useEffect(() => {
    if (!live) return;
    void getEvaluationJobs().then(setJobs).catch(() => undefined);
  }, [live, jobBoard]);
  useEffect(() => { if (!live) void getPublishedSnapshots().then(setSnapshots).catch(() => undefined); }, [live]);
  useEffect(() => {
    if (!live) return;
    void Promise.all([getGoldenRevisions(suiteId), getGoldenCanonical(suiteId)]).then(([value, canonical]) => {
      const rows = Array.isArray(value) ? value : [];
      setGoldenRevisions(rows);
      setGoldenCanonical(canonical);
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
    if (!live) return;
    const timer = window.setTimeout(() => {
      const params = documentParams();
      void getAdminDocuments(params).then((page) => {
        setCorpus((current) => ({ ...current, documents: page.documents }));
        setDocumentTotal(page.total);
        setDocumentNextCursor(page.next_cursor);
      }).catch((reason) => notify(String(reason), "error", "documents"));
    }, 200);
    return () => window.clearTimeout(timer);
  }, [live, documentQuery, documentRegistry, documentIssuer, documentYear, documentLanguage, documentForm, documentParseStatus, documentEmbeddingStatus, documentSnapshot, documentSort, documentDescending, notify]);
  useEffect(() => {
    if (live) void getDocumentFacets().then(setDocumentFacets).catch((reason) => notify(String(reason), "error", "document-facets"));
  }, [live, notify]);

  function documentParams(cursor?: string) {
    const params = new URLSearchParams({
      query: documentQuery,
      sort: documentSort,
      descending: String(documentDescending),
      limit: "50",
    });
    for (const [key, value] of [
      ["registry", documentRegistry],
      ["issuer", documentIssuer],
      ["fiscal_year", documentYear],
      ["language", documentLanguage],
      ["form", documentForm],
      ["parse_status", documentParseStatus],
      ["embedding_status", documentEmbeddingStatus],
      ["snapshot_id", documentSnapshot],
    ]) {
      if (value !== "all") params.set(key, value);
    }
    if (cursor) params.set("cursor", cursor);
    return params;
  }

  async function loadMoreDocuments() {
    if (!documentNextCursor) return;
    const params = documentParams(documentNextCursor);
    try {
      const page = await getAdminDocuments(params);
      setCorpus((current) => ({ ...current, documents: [...(Array.isArray(current.documents) ? current.documents : []), ...page.documents] }));
      setDocumentNextCursor(page.next_cursor);
    } catch (reason) {
      notify(String(reason), "error", "documents-more");
    }
  }

  function resetDocumentFilters() {
    setDocumentQuery("");
    setDocumentRegistry("all");
    setDocumentIssuer("all");
    setDocumentYear("all");
    setDocumentLanguage("all");
    setDocumentForm("all");
    setDocumentParseStatus("all");
    setDocumentEmbeddingStatus("all");
    setDocumentSnapshot("all");
    setDocumentSort("doc_id");
    setDocumentDescending(false);
    setDocumentGroup("none");
  }

  async function runEvaluation() {
    if (!live) { notify("Production experiment controls are locked. Compare published snapshots instead.", "warning", "prod-eval"); return; }
    if (!ready) return;
    setBusy(true);
    try {
      const job = await queueEvaluation(evaluationRequest);
      setJobs((current) => [job, ...current]);
      onRefreshJobs();
      setTab("jobs");
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
      setTab("experiments");
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

  function useSelectedResult() {
    const job = jobs.find((item) => item.result_ids.includes(selectedResultId ?? -1));
    if (!job || selectedResultId === null) return;
    onApplyProfile(job.request.profile, `${job.request.suite_id}:${selectedResultId}`);
  }

  async function sendRawRequest() {
    if (!live) return;
    try {
      const body = JSON.parse(rawRequest) as Record<string, unknown>;
      const response = await fetch(`${apiBase()}/admin/evaluations/runs`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      });
      const payload = await response.json();
      setRawResponse(JSON.stringify(payload, null, 2));
      if (!response.ok) notify("The API rejected this request.", "error", "raw-request");
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Invalid JSON request.", "error", "raw-request");
    }
  }

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

  const status = (corpus.status ?? {}) as Record<string, unknown>;
  const selectedSuite = suites.find((suite) => suite.suite_id === suiteId) ?? suites[0];
  const corpusDocuments = Array.isArray(corpus.documents)
    ? (corpus.documents as AdminDocument[])
    : [];
  const visibleDocuments = live ? corpusDocuments : corpusDocuments.filter((document) => (documentRegistry === "all" || document.registry === documentRegistry) && `${document.doc_id} ${document.issuer}`.toLowerCase().includes(documentQuery.toLowerCase())).toSorted((left, right) => String(left[documentSort as keyof AdminDocument] ?? "").localeCompare(String(right[documentSort as keyof AdminDocument] ?? ""), undefined, { numeric: true }));
  const documentGroups = groupDocuments(visibleDocuments, documentGroup);
  const activeGoldenRevision = goldenRevisions.find((item) => item.revision_id === selectedGoldenRevision) ?? null;
  const activeGoldenCases = activeGoldenRevision?.payload ?? goldenCanonical?.payload ?? [];
  const visibleGoldenCases = activeGoldenCases.filter((item) => `${String(item.id)} ${String(item.question)} ${String(item.category)} ${String(item.facet)} ${Array.isArray(item.tags) ? item.tags.join(" ") : ""}`.toLowerCase().includes(goldenCaseQuery.toLowerCase())).toSorted((left, right) => String(left[goldenCaseSort] ?? "").localeCompare(String(right[goldenCaseSort] ?? ""), undefined, { numeric: true }));
  const goldenReadOnly = !activeGoldenRevision || activeGoldenRevision.status === "published";
  const goldenScoreResult = resultDetail?.suite === suiteId ? resultDetail : null;
  const tabs = live ? [...TABS, ["usage", "Usage"] as [LabTab, string]] : TABS;
  const canRun = live && ready;
  const canOperateCorpus = live && status.writable !== false;

  return (
    <section className="lab-shell">
      <header className="page-heading">
        <div><p className="eyebrow">Corpus Lab</p><h1>Measure retrieval before trusting it.</h1></div>
        <div className="page-badges"><span className="mode-badge">{environment}</span><span className={`mode-badge ${live ? "live" : ""}`}>{live ? "Local operator" : "Read-only portfolio"}</span></div>
      </header>
      <nav className="lab-tabs" aria-label="Corpus Lab sections">
        {tabs.map(([id, label]) => (
          <button key={id} type="button" aria-pressed={tab === id} onClick={() => setTab(id)}>{label}</button>
        ))}
      </nav>

      {tab === "overview" && <div className="panel-stack">
        <div className="metric-grid">
          <Metric icon={<Database />} label="Documents" value={String(status.documents ?? 22)} />
          <Metric icon={<FileSearch />} label="Chunks" value={String(status.chunks ?? 10452)} />
          <Metric icon={<Activity />} label="Embeddings" value={String(status.embedded_chunks ?? 10452)} />
          <Metric icon={<Beaker />} label="BM25" value={status.bm25_ready === false ? "Not ready" : "Ready"} />
        </div>
        <button className="button" type="button" onClick={() => void refresh()}><RefreshCw size={15} /> Refresh status</button>
        {live && <JobActivityPanel board={jobBoard} loading={jobsLoading} onOpenJobs={() => setTab("jobs")} />}
        <section className="surface form-stack">
          <h2>Safe corpus operations</h2>
          <div className="profile-grid">
            <label>Registry<select value={registry} onChange={(event) => setRegistry(event.target.value as "sec" | "dart")}><option value="sec">SEC EDGAR</option><option value="dart">DART</option></select></label>
            <label>Tickers / stock codes<input value={identifiers} onChange={(event) => setIdentifiers(event.target.value)} /></label>
            <label>Fiscal years<input value={years} onChange={(event) => setYears(event.target.value)} /></label>
            <label>Manifest<select value={manifest} onChange={(event) => setManifest(event.target.value)}><option value="manifest.json">manifest.json</option><option value="dart-manifest.json">dart-manifest.json</option></select></label>
          </div>
          <div className="action-row">
            <button className="button" type="button" disabled={!canOperateCorpus || busy} onClick={() => void queueCorpus({ kind: registry === "sec" ? "acquire_edgar" : "acquire_dart", identifiers: identifiers.split(/[\s,]+/).filter(Boolean), years: years.split(/[\s,]+/).map(Number).filter(Number.isInteger) })}>Acquire missing filings</button>
            <button className="button" type="button" disabled={!canOperateCorpus || busy} onClick={() => void queueCorpus({ kind: "ingest_manifest", manifest })}>Ingest manifest</button>
            <button className="button" type="button" disabled={!canOperateCorpus || busy} onClick={() => void queueCorpus({ kind: "backfill_embeddings" })}>Backfill embeddings</button>
            <button className="button" type="button" disabled={!canOperateCorpus || busy} onClick={() => void queueCorpus({ kind: "rebuild_bm25" })}>Rebuild BM25</button>
          </div>
          {!live && <p className="helper">Actual acquisition and indexing are available only through the SSH operator tunnel.</p>}
        </section>
      </div>}

      {tab === "documents" && <div className="document-workspace">
        <section className="surface document-inventory">
          <div className="document-inventory-heading">
            <div><h2>Document inventory</h2><p className="helper">Showing {visibleDocuments.length.toLocaleString()} of {(live ? documentTotal : visibleDocuments.length).toLocaleString()} filings</p></div>
            <button className="button ghost" type="button" onClick={resetDocumentFilters}>Reset filters</button>
          </div>
          <div className="document-filters">
            <label className="document-search">Search<input aria-label="Search documents" placeholder="Document, issuer, or stock code" value={documentQuery} onChange={(event) => setDocumentQuery(event.target.value)} /></label>
            <FacetSelect label="Registry" value={documentRegistry} allLabel="All registries" facets={documentFacets.registries} onChange={setDocumentRegistry} />
            <FacetSelect label="Company" value={documentIssuer} allLabel="All companies" facets={documentFacets.issuers} onChange={setDocumentIssuer} />
            <FacetSelect label="Fiscal year" value={documentYear} allLabel="All years" facets={documentFacets.years} onChange={setDocumentYear} />
            <FacetSelect label="Language" value={documentLanguage} allLabel="All languages" facets={documentFacets.languages} onChange={setDocumentLanguage} />
            <FacetSelect label="Form" value={documentForm} allLabel="All forms" facets={documentFacets.forms} onChange={setDocumentForm} />
            <FacetSelect label="Parse status" value={documentParseStatus} allLabel="All parse states" facets={documentFacets.parse_statuses} onChange={setDocumentParseStatus} />
            <FacetSelect label="Embedding" value={documentEmbeddingStatus} allLabel="All embedding states" facets={documentFacets.embedding_statuses} onChange={(value) => setDocumentEmbeddingStatus(value as "all" | DocumentEmbeddingStatus)} />
            <FacetSelect label="Snapshot membership" value={documentSnapshot} allLabel="All snapshots" facets={documentFacets.snapshots} onChange={setDocumentSnapshot} />
            <label>Group by<select aria-label="Group documents" value={documentGroup} onChange={(event) => setDocumentGroup(event.target.value as DocumentGroup)}><option value="none">No grouping</option><option value="registry">Registry</option><option value="issuer">Company</option><option value="fiscal_year">Fiscal year</option></select></label>
            <label>Sort by<select aria-label="Sort documents" value={documentSort} onChange={(event) => setDocumentSort(event.target.value)}><option value="doc_id">Document</option><option value="issuer">Issuer</option><option value="fiscal_year">Year</option><option value="filing_date">Filing date</option><option value="chunk_count">Chunks</option><option value="embedding_coverage">Embedding coverage</option></select></label>
            <label>Direction<select aria-label="Sort direction" value={documentDescending ? "descending" : "ascending"} onChange={(event) => setDocumentDescending(event.target.value === "descending")}><option value="ascending">Ascending</option><option value="descending">Descending</option></select></label>
          </div>
          <div className="document-table-scroll"><table><thead><tr><th>Document</th><th>Registry</th><th>Issuer</th><th>Year</th><th>Filed</th><th>Form</th><th>Language</th><th>Chunks</th><th>Embedding</th><th>Snapshots</th><th>Status</th></tr></thead>{documentGroups.map(([groupLabel, rows]) => <tbody key={groupLabel || "all"}>{groupLabel && <tr className="document-group-row"><th colSpan={11}>{groupLabel}<span>{rows.length} filings</span></th></tr>}{rows.map((document) => { const embedded = document.embedded_chunks ?? 0; const chunks = document.chunk_count ?? 0; const coverage = chunks > 0 ? Math.round(embedded / chunks * 100) : 0; return <tr key={document.doc_id} className={documentDetail?.document.doc_id === document.doc_id ? "selected" : ""}><td><button className="row-detail" type="button" disabled={!live} onClick={() => live && void getDocumentDetail(document.doc_id).then(setDocumentDetail).catch((reason) => notify(String(reason), "error", "document-detail"))}>{document.doc_id}</button></td><td>{document.registry.toUpperCase()}</td><td>{document.issuer}</td><td>{document.fiscal_year}</td><td>{document.filing_date || "—"}</td><td>{document.form || "—"}</td><td>{document.language}</td><td>{chunks.toLocaleString()}</td><td><span className={`coverage-badge ${document.embedding_status ?? "missing"}`}>{coverage}%</span><small>{embedded.toLocaleString()}/{chunks.toLocaleString()}</small></td><td>{(document.snapshot_count ?? 0).toLocaleString()}</td><td>{document.parse_status}</td></tr>; })}</tbody>)}</table></div>
          {!visibleDocuments.length && <p className="helper document-empty">No documents match these filters.</p>}
          {documentNextCursor && <button className="button document-load-more" type="button" onClick={() => void loadMoreDocuments()}>Load next 50</button>}
        </section>
        <DocumentDetailPanel detail={documentDetail} />
      </div>}

      {tab === "golden" && <div className="golden-workspace">
        <section className="surface form-stack golden-controls">
          <label>Golden suite<select value={suiteId} onChange={(event) => setSuiteId(event.target.value as SuiteId)}>{suites.map((suite) => <option key={suite.suite_id} value={suite.suite_id}>{suite.label}</option>)}</select></label>
          {selectedSuite && <div className="provenance"><strong>{selectedSuite.case_count} cases</strong><span>{selectedSuite.curation_status}</span><span>{selectedSuite.approval_status}</span><span>human_verified=false</span>{!selectedSuite.source_ready && <span className="danger">Sources unavailable</span>}</div>}
          {live && <><div className="golden-file"><span>Canonical file</span><strong>{goldenCanonical?.filename ?? "Loading…"}</strong><code>{goldenCanonical?.sha256.slice(0, 12) ?? "—"}</code></div><label>Golden revision<select value={selectedGoldenRevision ?? ""} onChange={(event) => { setSelectedGoldenRevision(event.target.value ? Number(event.target.value) : null); setSelectedGoldenCase(""); setGoldenCaseJson(""); }}><option value="">Canonical JSON · read-only</option>{goldenRevisions.map((revision) => <option key={revision.revision_id} value={revision.revision_id}>v{revision.version} · {revision.status}</option>)}</select></label><div className="action-row"><button className="button" type="button" onClick={() => void newGoldenDraft()}>Create draft</button><button className="button" type="button" disabled={!activeGoldenRevision || activeGoldenRevision.status === "published"} onClick={() => void changeGoldenStatus("validate")}>Validate</button><button className="button" type="button" disabled={activeGoldenRevision?.status !== "validated"} onClick={() => void changeGoldenStatus("publish")}>Publish JSON</button></div><p className="helper">Canonical and published revisions are immutable. Create a draft before editing questions or source spans.</p></>}
          <label>Run mode<select value={mode} onChange={(event) => setMode(event.target.value as "quick" | "matrix")}><option value="quick">Quick · current index</option><option value="matrix">Matrix · isolated corpus</option></select></label>
          {mode === "matrix" && <label>Chunk targets<input value={chunkTargets} onChange={(event) => setChunkTargets(event.target.value)} placeholder="500 1200" /></label>}
          <ProfileFields profile={profile} onChange={onProfileChange} />
          <button className="button primary" type="button" aria-disabled={!canRun || busy} onClick={() => void runEvaluation()}><Play size={15} /> {busy ? "Queueing…" : "Queue evaluation"}</button>
          {!live && <p className="helper">Production experiments are locked. Compare stored published snapshots instead.</p>}
        </section>
        <section className="surface golden-manager">
          <div className="surface-heading"><div><h2>{live ? "Golden questions" : "Latest comparison"}</h2>{live && <p className="helper">{activeGoldenRevision ? `Revision v${activeGoldenRevision.version} · ${activeGoldenRevision.status}` : "Canonical JSON · read-only"}{goldenScoreResult ? ` · scores from result #${goldenScoreResult.result_id}` : " · no evaluation result selected"}</p>}</div></div>
          {live ? <><div className="golden-table-tools"><input aria-label="Search golden cases" placeholder="Search ID, question, category, facet, or tag" value={goldenCaseQuery} onChange={(event) => setGoldenCaseQuery(event.target.value)} /><select aria-label="Sort golden cases" value={goldenCaseSort} onChange={(event) => setGoldenCaseSort(event.target.value)}><option value="id">ID</option><option value="question">Question</option><option value="category">Category</option><option value="facet">Facet</option></select></div><div className="golden-table-scroll"><table><thead><tr><th>ID</th><th>Question</th><th>Category</th><th>Facet</th><th>Tags</th><th>Eval</th><th>First rank</th><th>RR</th></tr></thead><tbody>{visibleGoldenCases.map((item) => { const score = goldenScoreResult?.cases.find((value) => value.case_id === item.id); const rank = score?.first_relevant_rank ?? null; return <tr key={String(item.id)} className={selectedGoldenCase === String(item.id) ? "selected" : ""}><td><button type="button" className="row-detail" onClick={() => openGoldenCase(item)}>{String(item.id)}</button></td><td>{String(item.question)}</td><td>{String(item.category)}</td><td>{String(item.facet)}</td><td>{Array.isArray(item.tags) && item.tags.length ? item.tags.join(", ") : "—"}</td><td>{score ? rank ? "hit" : "miss" : "not run"}</td><td>{rank ?? "—"}</td><td>{score ? (rank ? 1 / rank : 0).toFixed(3) : "—"}</td></tr>; })}</tbody></table></div>{!visibleGoldenCases.length && <p className="helper">No questions match this filter.</p>}{selectedGoldenCase && <div className="golden-editor"><div className="golden-editor-heading"><div><h3>{selectedGoldenCase}</h3><p>{goldenReadOnly ? "Read-only source" : "Editable draft"}</p></div><span className={`job-status ${goldenReadOnly ? "" : "running"}`}>{goldenReadOnly ? "locked" : "draft"}</span></div>{parsedGoldenCase && <div className="form-stack"><label>Question<textarea disabled={goldenReadOnly} value={String(parsedGoldenCase.question ?? "")} onChange={(event) => patchGoldenCase("question", event.target.value)} /></label><label>Reference answer<textarea disabled={goldenReadOnly} value={String(parsedGoldenCase.reference_answer ?? "")} onChange={(event) => patchGoldenCase("reference_answer", event.target.value)} /></label><div className="profile-grid"><label>Category<select disabled={goldenReadOnly} value={String(parsedGoldenCase.category ?? "simple_lookup")} onChange={(event) => patchGoldenCase("category", event.target.value)}><option value="simple_lookup">Simple lookup</option><option value="exact_number">Exact number</option><option value="multi_hop">Multi-hop</option><option value="absent">Absent</option></select></label><label>Facet<select disabled={goldenReadOnly} value={String(parsedGoldenCase.facet ?? "factual")} onChange={(event) => patchGoldenCase("facet", event.target.value)}><option value="factual">Factual</option><option value="comparison">Comparison</option><option value="risk">Risk</option><option value="policy">Policy</option><option value="numeric">Numeric</option></select></label><label>Expected label<select disabled={goldenReadOnly} value={String(parsedGoldenCase.expected_label ?? "SUPPORTED")} onChange={(event) => patchGoldenCase("expected_label", event.target.value)}><option value="SUPPORTED">SUPPORTED</option><option value="NOT_IN_DOCS">NOT_IN_DOCS</option></select></label><label>Tags<input disabled={goldenReadOnly} value={Array.isArray(parsedGoldenCase.tags) ? parsedGoldenCase.tags.join(" ") : ""} onChange={(event) => patchGoldenCase("tags", event.target.value.split(/[\s,]+/).filter(Boolean))} placeholder="demo-hero numeric" /></label></div><label>Reviewer note<textarea disabled={goldenReadOnly} value={String(parsedGoldenCase.note ?? "")} onChange={(event) => patchGoldenCase("note", event.target.value)} /></label><div className="golden-spans"><div className="surface-heading"><h3>Answer source spans</h3><button className="button ghost" type="button" disabled={goldenReadOnly} onClick={addGoldenAnswer}>Add span</button></div>{goldenAnswers(parsedGoldenCase).map((answer, index) => <article key={`${String(answer.doc_id)}:${index}`}><div className="golden-span-heading"><strong>Span {index + 1}</strong><button className="button ghost" type="button" disabled={goldenReadOnly} onClick={() => removeGoldenAnswer(index)}>Remove</button></div><div className="profile-grid"><label>Document ID<input disabled={goldenReadOnly} value={String(answer.doc_id ?? "")} onChange={(event) => patchGoldenAnswer(index, "doc_id", event.target.value)} /></label><label>Start char<input disabled={goldenReadOnly} type="number" min={0} value={Number(answer.start_char ?? 0)} onChange={(event) => patchGoldenAnswer(index, "start_char", Number(event.target.value))} /></label><label>End char<input disabled={goldenReadOnly} type="number" min={1} value={Number(answer.end_char ?? 1)} onChange={(event) => patchGoldenAnswer(index, "end_char", Number(event.target.value))} /></label><label>Source SHA-256<input disabled={goldenReadOnly} value={String(answer.source_sha256 ?? "")} onChange={(event) => patchGoldenAnswer(index, "source_sha256", event.target.value)} /></label></div></article>)}{!goldenAnswers(parsedGoldenCase).length && <p className="helper">Absent cases intentionally have no source span.</p>}</div><label>Single-case JSON<textarea disabled={goldenReadOnly} className="golden-json" value={goldenCaseJson} onChange={(event) => setGoldenCaseJson(event.target.value)} spellCheck={false} /></label><button className="button primary" type="button" disabled={goldenReadOnly || !parsedGoldenCase} onClick={() => void saveSelectedGoldenCase()}>Save case</button></div>}</div>}</> : comparison.metrics.map((metric) => <div className="metric-row" key={metric.name}><span>{metric.name}</span><strong>{metric.candidate.toFixed(3)}</strong><em className={metric.delta >= 0 ? "positive" : "negative"}>{metric.delta >= 0 ? "+" : ""}{metric.delta.toFixed(3)}</em></div>)}
          <p className="helper">Hit, first rank, and reciprocal rank measure retrieval—not final-answer factuality.</p>
        </section>
      </div>}

      {tab === "experiments" && <div className="panel-stack">
        <div className="metric-grid">{comparison.metrics.map((metric) => <Metric key={metric.name} icon={<Beaker />} label={metric.name} value={`${metric.candidate.toFixed(3)} (${metric.delta >= 0 ? "+" : ""}${metric.delta.toFixed(3)})`} />)}</div>
        <section className="surface"><h2>Case changes</h2>{comparison.cases.map((item) => <article className="case-row" key={item.case_id}><div><strong>{item.case_id}</strong><p>{item.question}</p></div><span className={`transition ${item.transition}`}>{item.transition.replaceAll("_", " ")}</span></article>)}</section>
      </div>}

      {tab === "snapshots" && <div className="two-column"><section className="surface form-stack"><h2>{live ? "Evaluation snapshots" : "Published snapshots"}</h2>{live && <><label>Snapshot label<input value={snapshotLabel} onChange={(event) => setSnapshotLabel(event.target.value)} placeholder="BM25 tuned baseline" /></label><button className="button" type="button" disabled={selectedResultId === null || !snapshotLabel.trim()} onClick={() => void freezeSnapshot()}>Freeze selected eval result</button></>}<label>Baseline<select value={snapshotIds[0] ?? ""} onChange={(event) => setSnapshotIds([Number(event.target.value) || null, snapshotIds[1]])}><option value="">Select</option>{snapshots.map((item) => <option key={item.snapshot_id} value={item.snapshot_id}>{item.label} · {item.eval_result.suite}</option>)}</select></label><label>Candidate<select value={snapshotIds[1] ?? ""} onChange={(event) => setSnapshotIds([snapshotIds[0], Number(event.target.value) || null])}><option value="">Select</option>{snapshots.map((item) => <option key={item.snapshot_id} value={item.snapshot_id}>{item.label} · {item.eval_result.suite}</option>)}</select></label><button className="button primary" type="button" disabled={!snapshotIds[0] || !snapshotIds[1]} onClick={() => void loadSnapshotComparison()}>Compare stored results</button><div className="snapshot-list">{snapshots.map((item) => <article key={item.snapshot_id}><div><strong>{item.label}</strong><p>{item.document_count} documents · {item.eval_result.suite} · #{item.eval_result.result_id}</p></div><div className="action-row">{live && <button className="button ghost" type="button" onClick={() => onApplySnapshot(item)}>Use for review</button>}{live && <button className="button ghost" type="button" onClick={() => void toggleSnapshot(item)}>{item.public ? "Hide" : "Publish"}</button>}</div></article>)}</div><p className="helper">Stored artifacts only. Comparing snapshots does not run an evaluation or provider request.</p></section><section className="surface snapshot-comparison"><h2>Snapshot comparison</h2>{snapshotComparison?.warning && <p className="notice error">{snapshotComparison.warning}</p>}{snapshotComparison ? <><div className="metric-table">{snapshotComparison.metrics.map((metric) => <div key={metric.name}><span>{metric.name}</span><strong>{metric.candidate.toFixed(3)}</strong><em className={metric.delta === null ? "" : metric.delta >= 0 ? "positive" : "negative"}>{metric.delta === null ? "n/a" : `${metric.delta >= 0 ? "+" : ""}${metric.delta.toFixed(3)}`}</em></div>)}</div><div className="snapshot-case-heading"><h3>Common cases</h3><span>{snapshotComparison.common_case_count}</span></div><div className="snapshot-case-list">{snapshotComparison.cases.map((item) => <article key={item.case_id}><div className="job-title"><strong>{item.case_id}</strong><span className={`transition ${item.transition}`}>{item.transition.replaceAll("_", " ")}</span></div><div className="snapshot-case-side"><div><span>Baseline · {item.baseline_rank ? `rank ${item.baseline_rank}` : "miss"}</span><p>{item.baseline_question}</p></div><div><span>Candidate · {item.candidate_rank ? `rank ${item.candidate_rank}` : "miss"}</span><p>{item.candidate_question}</p></div></div>{item.rank_delta !== null && <small>Rank delta {item.rank_delta > 0 ? "+" : ""}{item.rank_delta}</small>}</article>)}</div>{!snapshotComparison.cases.length && <p className="helper">The stored artifacts have no common cases.</p>}</> : <p className="helper">Select two snapshots and compare them.</p>}</section></div>}

      {tab === "jobs" && <div className="panel-stack">{live && <JobCenter board={jobBoard} loading={jobsLoading} onRetry={onRetryJob} onCancel={onCancelJob} onRefresh={onRefreshJobs} onOpenResult={(resultId) => void openResult(resultId)} />}<div className="two-column"><section className="surface"><div className="surface-heading"><h2>Evaluation results</h2><button className="button primary" type="button" disabled={!live || selectedResultId === null} onClick={useSelectedResult}>Use selected set</button></div>{jobs.map((job) => <article className="job-row" key={job.job_id}><div className="job-select"><input type="radio" name="evaluation-result" aria-label={`Select ${job.job_id}`} disabled={job.status !== "succeeded" || !job.result_id} checked={selectedResultId === job.result_id} onChange={() => setSelectedResultId(job.result_id)} /><button className="row-detail" type="button" disabled={!job.result_id} onClick={() => job.result_id && void openResult(job.result_id)}><strong>{job.request.suite_id} · {job.request.mode}</strong><p>{job.message}</p></button></div><span>{job.status}</span>{job.status === "succeeded" && job.result_id && job.baseline_id && <button className="button ghost" type="button" onClick={() => void loadComparison(job.result_id!, job.baseline_id!)}>Compare</button>}{job.result_ids.length > 1 && <div className="job-arms">{job.result_ids.map((resultId) => <label key={resultId}><input type="radio" name="evaluation-result" checked={selectedResultId === resultId} onChange={() => setSelectedResultId(resultId)} /> Result {resultId}</label>)}</div>}</article>)}</section><section className="surface detail-panel"><h2>Result details</h2>{resultDetail ? <><div className="metric-grid compact">{Object.entries(resultDetail.metrics).map(([name, value]) => <Metric key={name} icon={<Beaker />} label={name} value={value.toFixed(3)} />)}</div><pre>{JSON.stringify(resultDetail.config, null, 2)}</pre><h3>Cases</h3>{resultDetail.cases.slice(0, 10).map((item) => <article className="case-row" key={item.case_id}><div><strong>{item.case_id}</strong><p>{item.question}</p></div><span>{item.first_relevant_rank ? `rank ${item.first_relevant_rank}` : "miss"}</span></article>)}</> : <p className="helper">Select a succeeded result, then click its row to inspect metrics and cases.</p>}</section></div></div>}

      {tab === "api" && <div className="api-inspector"><section><h2>Request</h2><textarea value={rawRequest} onChange={(event) => setRawRequest(event.target.value)} spellCheck={false} /><button className="button primary" type="button" disabled={!canRun} onClick={() => void sendRawRequest()}><Braces size={15} /> Send to API</button></section><section><h2>Response</h2><pre>{rawResponse || "The typed API response will appear here."}</pre></section></div>}

      {tab === "usage" && live && <div className="panel-stack">
        {usageError && <div className="notice error" role="alert">{usageError}</div>}
        <div className="metric-grid">
          <Metric icon={<Activity />} label="Runs" value={String(usage.runs)} />
          <Metric icon={<Braces />} label="Requests" value={String(usage.requests)} />
          <Metric icon={<Database />} label="Input tokens" value={usage.input_tokens.toLocaleString()} />
          <Metric icon={<Beaker />} label="Estimated cost" value={`$${usage.estimated_cost_usd}`} />
        </div>
        <section className="surface table-wrap usage-table">
          <h2>Recorded model usage</h2>
          <p className="helper">Local application traces only. This does not query OpenAI account billing.</p>
          <table><thead><tr><th>Model</th><th>Requests</th><th>Input</th><th>Cached</th><th>Cache write</th><th>Output</th><th>Reasoning</th><th>Estimated USD</th></tr></thead><tbody>
            {usage.models.map((model) => <tr key={model.model_name}><td>{model.model_name}</td><td>{model.requests}</td><td>{model.input_tokens.toLocaleString()}</td><td>{model.cached_input_tokens.toLocaleString()}</td><td>{model.cache_write_input_tokens.toLocaleString()}</td><td>{model.output_tokens.toLocaleString()}</td><td>{model.reasoning_tokens.toLocaleString()}</td><td>${model.estimated_cost_usd}</td></tr>)}
          </tbody></table>
          {!usage.models.length && <p className="helper">No persisted provider traces yet.</p>}
          {usage.latest_run_at && <p className="helper">Latest run: {new Date(usage.latest_run_at).toLocaleString()}</p>}
        </section>
      </div>}
    </section>
  );
}

function FacetSelect({ label, value, allLabel, facets, onChange }: { label: string; value: string; allLabel: string; facets: DocumentFacets["registries"]; onChange: (value: string) => void }) {
  return <label>{label}<select aria-label={`Filter ${label.toLowerCase()}`} value={value} onChange={(event) => onChange(event.target.value)}><option value="all">{allLabel}</option>{facets.map((facet) => <option key={facet.value} value={facet.value}>{facet.label ?? facet.value} ({facet.count})</option>)}</select></label>;
}

function goldenAnswers(value: Record<string, unknown>): Array<Record<string, unknown>> {
  return Array.isArray(value.answers)
    ? value.answers.filter((answer): answer is Record<string, unknown> => typeof answer === "object" && answer !== null)
    : [];
}

function groupDocuments(documents: AdminDocument[], group: DocumentGroup): Array<[string, AdminDocument[]]> {
  if (group === "none") return [["", documents]];
  const grouped = new Map<string, AdminDocument[]>();
  for (const document of documents) {
    const value = String(document[group]);
    const label = group === "registry"
      ? `Registry · ${value.toUpperCase()}`
      : group === "issuer"
      ? `Company · ${value}`
      : `Fiscal year · ${value}`;
    grouped.set(label, [...(grouped.get(label) ?? []), document]);
  }
  return [...grouped.entries()].toSorted(([left], [right]) => left.localeCompare(right, undefined, { numeric: true }));
}

function formatBytes(value: number): string {
  if (value < 1_000) return `${value} B`;
  if (value < 1_000_000) return `${(value / 1_000).toFixed(1)} KB`;
  return `${(value / 1_000_000).toFixed(1)} MB`;
}

function DocumentDetailPanel({ detail }: { detail: DocumentDetail | null }) {
  if (!detail) return <section className="surface document-detail"><h2>Document details</h2><p className="helper">Select a document to inspect filing identity, section distribution, embedding coverage, snapshot revisions, and source-cited chunks.</p></section>;
  const { document } = detail;
  const missing = Math.max(document.chunk_count - detail.embedded_chunks, 0);
  const coverage = document.chunk_count > 0 ? Math.round(detail.embedded_chunks / document.chunk_count * 100) : 0;
  return <section className="surface document-detail">
    <header className="document-detail-heading"><div><p className="eyebrow">{document.registry.toUpperCase()} · {document.language.toUpperCase()}</p><h2>{document.doc_id}</h2><p>{document.issuer} · FY{document.fiscal_year} · {document.form}</p></div><span className={`coverage-badge ${missing === 0 ? "complete" : detail.embedded_chunks > 0 ? "partial" : "missing"}`}>{coverage}% embedded</span></header>
    <section className="document-detail-section"><h3>Filing identity</h3><dl className="document-meta-grid"><div><dt>Issuer identity</dt><dd>{document.issuer_id}</dd></div><div><dt>Filing identity</dt><dd>{document.filing_id}</dd></div><div><dt>Filed</dt><dd>{document.filing_date}</dd></div><div><dt>Report period</dt><dd>{document.report_period}</dd></div><div><dt>Source size</dt><dd>{formatBytes(document.source_length)}</dd></div><div><dt>Parse status</dt><dd>{document.parse_status}</dd></div><div className="wide"><dt>Source</dt><dd><a href={document.source_url} target="_blank" rel="noreferrer">{document.source_url}</a></dd></div><div className="wide"><dt>Source SHA-256</dt><dd><code>{document.source_sha256}</code></dd></div></dl></section>
    <section className="document-detail-section"><h3>Chunk & index coverage</h3><div className="document-stat-grid"><div><span>Total chunks</span><strong>{document.chunk_count.toLocaleString()}</strong></div><div><span>Text / table</span><strong>{detail.text_chunks.toLocaleString()} / {detail.table_chunks.toLocaleString()}</strong></div><div><span>Embedded</span><strong>{detail.embedded_chunks.toLocaleString()}</strong></div><div><span>Missing vectors</span><strong className={missing > 0 ? "negative" : "positive"}>{missing.toLocaleString()}</strong></div></div></section>
    <section className="document-detail-section"><h3>Section distribution</h3>{detail.item_counts.length ? <div className="document-section-list">{detail.item_counts.map((item) => <div key={item.item}><span>{item.item}</span><strong>{item.count.toLocaleString()}</strong><progress max={document.chunk_count || 1} value={item.count} /></div>)}</div> : <p className="helper">No section identities were recorded.</p>}</section>
    <section className="document-detail-section"><h3>Embedding identities</h3>{detail.embedding_identities.length ? <div className="embedding-list">{detail.embedding_identities.map((identity) => <article key={`${identity.provider}:${identity.model}:${identity.dimensions}`}><strong>{identity.provider} · {identity.model}</strong><p>{identity.dimensions} dimensions · {identity.count.toLocaleString()} chunks</p></article>)}</div> : <p className="helper">No persisted embedding identity is available.</p>}</section>
    <section className="document-detail-section"><h3>Index revisions & snapshot membership</h3>{detail.snapshot_memberships.length ? <div className="snapshot-memberships">{detail.snapshot_memberships.map((snapshot) => <article key={snapshot.snapshot_id}><div><strong>Revision #{snapshot.snapshot_id} · {snapshot.label}</strong><p>{snapshot.status} · {snapshot.public ? "published" : "private"} · {new Date(snapshot.created_at).toLocaleString()}</p></div></article>)}</div> : <p className="helper">This filing is not frozen in an evaluation snapshot yet.</p>}</section>
    <section className="document-detail-section"><h3>Source-cited chunk previews</h3><div className="chunk-preview-list">{detail.chunks.map((chunk) => <article key={chunk.chunk_id}><header><strong>Chunk {chunk.chunk_id} · ordinal {chunk.ordinal}</strong><span>{chunk.span}</span></header><p className="chunk-citation">{chunk.citation}</p><p>{chunk.body}</p><code>{chunk.source_sha256}</code></article>)}</div></section>
  </section>;
}

const JOB_COPY: Record<string, { label: string; purpose: string }> = {
  acquire_edgar: { label: "Acquire SEC filings", purpose: "Download missing EDGAR filings into the corpus." },
  acquire_dart: { label: "Acquire DART filings", purpose: "Download missing Korean business reports." },
  ingest_manifest: { label: "Ingest manifest", purpose: "Parse filings and replace the active retrieval corpus." },
  backfill_embeddings: { label: "Backfill embeddings", purpose: "Persist missing vectors for semantic retrieval." },
  rebuild_bm25: { label: "Rebuild BM25", purpose: "Recompute lexical term and document statistics." },
  quick: { label: "Quick evaluation", purpose: "Measure one profile against the current live index." },
  matrix: { label: "Matrix evaluation", purpose: "Compare isolated chunking and retrieval arms." },
};

function jobCopy(job: OperatorJob) {
  return JOB_COPY[job.kind] ?? {
    label: job.kind.replaceAll("_", " "),
    purpose: "Run one persisted operator task.",
  };
}

function elapsedLabel(job: OperatorJob): string {
  if (!job.started_at) return "Not started";
  const end = job.finished_at ? new Date(job.finished_at).getTime() : Date.now();
  const seconds = Math.max(0, Math.floor((end - new Date(job.started_at).getTime()) / 1000));
  const minutes = Math.floor(seconds / 60);
  return minutes > 0 ? `${minutes}m ${seconds % 60}s` : `${seconds}s`;
}

function JobProgress({ job }: { job: OperatorJob }) {
  const percent = job.total && job.total > 0
    ? Math.min(100, Math.round((job.current / job.total) * 100))
    : null;
  return <div className="job-progress"><div><span>{job.stage}</span><strong>{job.total === null ? job.current : `${job.current.toLocaleString()} / ${job.total.toLocaleString()}${percent === null ? "" : ` · ${percent}%`}`}</strong></div>{job.total !== null && <progress max={Math.max(job.total, 1)} value={Math.min(job.current, job.total)} />}{job.detail_total !== null && <><div><span>Current item</span><strong>{job.detail_current ?? 0} / {job.detail_total}</strong></div><progress max={Math.max(job.detail_total, 1)} value={Math.min(job.detail_current ?? 0, job.detail_total)} /></>}</div>;
}

function JobActivityPanel({ board, loading, onOpenJobs }: { board: OperatorJobBoard; loading: boolean; onOpenJobs: () => void }) {
  const active = board.jobs.find((job) => job.status === "running") ?? null;
  const queued = board.jobs.filter((job) => job.status === "queued").toSorted((left, right) => (left.queue_position ?? 0) - (right.queue_position ?? 0));
  const latest = board.jobs.find((job) => ["succeeded", "failed", "interrupted", "cancelled"].includes(job.status)) ?? null;
  return <section className="surface job-activity"><div className="surface-heading"><div><h2>Job activity</h2><p className="helper">Persistent corpus and evaluation queue</p></div><button className="button" type="button" onClick={onOpenJobs}>View all jobs</button></div>{loading && !board.jobs.length ? <p className="helper">Loading job activity…</p> : active ? <article className="active-job"><div className="job-title"><div><strong>{jobCopy(active).label}</strong><p>{jobCopy(active).purpose}</p></div><span className={`job-status ${active.status}`}>{active.status}</span></div><JobProgress job={active} /><p className="helper">{active.message}</p><p className="helper">Started {active.started_at ? new Date(active.started_at).toLocaleTimeString() : "—"} · elapsed {elapsedLabel(active)}</p></article> : <p className="helper">No job is running.{latest ? ` Latest: ${jobCopy(latest).label} · ${latest.status}.` : ""}</p>}{queued.length > 0 && <div className="queued-jobs"><strong>Queued · {queued.length}</strong>{queued.slice(0, 3).map((job) => <span key={job.job_id}>#{job.queue_position} {jobCopy(job).label}</span>)}</div>}</section>;
}

function JobCenter({ board, loading, onRetry, onCancel, onRefresh, onOpenResult }: { board: OperatorJobBoard; loading: boolean; onRetry: (jobId: string) => void; onCancel: (jobId: string) => void; onRefresh: () => void; onOpenResult: (resultId: number) => void }) {
  const [domain, setDomain] = useState<"all" | OperatorJob["domain"]>("all");
  const [group, setGroup] = useState<"all" | "active" | "queued" | "history">("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const visible = board.jobs.filter((job) => {
    if (domain !== "all" && job.domain !== domain) return false;
    if (group === "active" && job.status !== "running") return false;
    if (group === "queued" && job.status !== "queued") return false;
    if (group === "history" && ["queued", "running"].includes(job.status)) return false;
    return true;
  });
  const selected = board.jobs.find((job) => job.job_id === selectedId) ?? visible[0] ?? null;
  const resultId = typeof selected?.result_refs.result_id === "number" ? selected.result_refs.result_id : null;
  return <div className="job-center"><section className="surface"><div className="surface-heading"><div><h2>Job Center</h2><p className="helper">{board.active_count} active · {board.queued_count} queued</p></div><button className="button" type="button" disabled={loading} onClick={onRefresh}><RefreshCw size={14} /> Refresh</button></div><div className="job-filters"><div>{(["all", "corpus", "evaluation"] as const).map((value) => <button key={value} type="button" aria-pressed={domain === value} onClick={() => setDomain(value)}>{value}</button>)}</div><div>{(["all", "active", "queued", "history"] as const).map((value) => <button key={value} type="button" aria-pressed={group === value} onClick={() => setGroup(value)}>{value}</button>)}</div></div><div className="job-list">{visible.map((job) => <button className="job-list-row" type="button" key={job.job_id} aria-pressed={selected?.job_id === job.job_id} onClick={() => setSelectedId(job.job_id)}><span className={`job-status ${job.status}`}>{job.status}</span><div><strong>{jobCopy(job).label}</strong><p>{job.queue_position ? `Queue #${job.queue_position} · ` : ""}{job.message}</p></div><span>{job.total === null ? job.stage : `${Math.min(100, Math.round(job.current / Math.max(job.total, 1) * 100))}%`}</span></button>)}</div>{!visible.length && <p className="helper">No jobs match this filter.</p>}</section><section className="surface job-detail"><h2>Job details</h2>{selected ? <><div className="job-title"><div><strong>{jobCopy(selected).label}</strong><p>{jobCopy(selected).purpose}</p></div><span className={`job-status ${selected.status}`}>{selected.status}</span></div><JobProgress job={selected} /><dl className="status-list"><div><dt>Domain</dt><dd>{selected.domain}</dd></div><div><dt>Created</dt><dd>{new Date(selected.created_at).toLocaleString()}</dd></div><div><dt>Started</dt><dd>{selected.started_at ? new Date(selected.started_at).toLocaleString() : "—"}</dd></div><div><dt>Finished</dt><dd>{selected.finished_at ? new Date(selected.finished_at).toLocaleString() : "—"}</dd></div><div><dt>Elapsed</dt><dd>{elapsedLabel(selected)}</dd></div><div><dt>Error</dt><dd>{selected.error_code ?? "—"}</dd></div></dl><p>{selected.message}</p><div className="action-row">{resultId !== null && <button className="button" type="button" onClick={() => onOpenResult(resultId)}>View result #{resultId}</button>}{selected.can_retry && <button className="button" type="button" onClick={() => onRetry(selected.job_id)}>Retry as new job</button>}{selected.can_cancel && <button className="button danger-button" type="button" onClick={() => onCancel(selected.job_id)}>Cancel job</button>}</div><details><summary>Request and results</summary><pre>{JSON.stringify({ request: selected.request, result_refs: selected.result_refs }, null, 2)}</pre></details></> : <p className="helper">Select a job to inspect its progress and provenance.</p>}</section></div>;
}

function Metric({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return <div className="metric"><span>{icon}{label}</span><strong>{value}</strong></div>;
}

function ProfileFields({ profile, onChange }: { profile: RetrievalProfile; onChange: (profile: RetrievalProfile) => void }) {
  function patch(update: Partial<RetrievalProfile>) { onChange({ ...profile, ...update }); }
  return <div className="profile-grid">
    <label>Strategy<select value={profile.strategy} onChange={(event) => patch({ strategy: event.target.value as RetrievalProfile["strategy"], lexical_ranker: event.target.value === "vector" ? null : profile.lexical_ranker ?? "ts_rank_cd" })}><option value="hybrid">Hybrid</option><option value="vector">Vector</option><option value="lexical">Lexical</option></select></label>
    <label>Lexical<select disabled={profile.strategy === "vector"} value={profile.lexical_ranker ?? "ts_rank_cd"} onChange={(event) => patch({ lexical_ranker: event.target.value as RetrievalProfile["lexical_ranker"] })}><option value="ts_rank_cd">ts_rank_cd</option><option value="bm25">BM25</option></select></label>
    <label>k<input type="number" min={1} max={100} value={profile.k} onChange={(event) => patch({ k: Number(event.target.value) })} /></label>
    <label>candidate_k<input type="number" min={profile.k} max={500} value={profile.candidate_k} onChange={(event) => patch({ candidate_k: Number(event.target.value) })} /></label>
    <label>RRF k<input type="number" min={1} value={profile.rrf_k} onChange={(event) => patch({ rrf_k: Number(event.target.value) })} /></label>
    <label>BM25 k1<input type="number" step="0.1" min="0.1" value={profile.bm25_k1} onChange={(event) => patch({ bm25_k1: Number(event.target.value) })} /></label>
    <label>BM25 b<input type="number" step="0.05" min="0" max="1" value={profile.bm25_b} onChange={(event) => patch({ bm25_b: Number(event.target.value) })} /></label>
    <label>BM25 IDF<select value={profile.bm25_idf} onChange={(event) => patch({ bm25_idf: event.target.value as RetrievalProfile["bm25_idf"] })}><option value="lucene">Lucene</option><option value="robertson">Robertson</option></select></label>
    <label>Reranker<select disabled={profile.strategy !== "hybrid"} value={profile.reranker ?? "none"} onChange={(event) => patch({ reranker: event.target.value === "none" ? null : "cross_encoder" })}><option value="none">None</option><option value="cross_encoder">Cross encoder</option></select></label>
    <label className="checkbox"><input type="checkbox" checked={profile.route_by_language} disabled={profile.strategy !== "hybrid"} onChange={(event) => patch({ route_by_language: event.target.checked })} /> Route by language</label>
  </div>;
}
