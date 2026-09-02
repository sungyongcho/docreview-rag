"use client";

import { Activity, Beaker, Braces, Database, FileSearch, Play, RefreshCw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import {
  apiBase,
  compareEvaluations,
  compareSnapshots,
  createGoldenDraft,
  createSnapshot,
  getAdminSnapshots,
  getCorpusSnapshot,
  getEvaluationJobs,
  getEvaluationResult,
  getGoldenSuites,
  getGoldenCanonical,
  getGoldenRevisions,
  getProviderUsage,
  getPublishedSnapshots,
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
  OperatorJobBoard,
  SnapshotComparison,
  AdminDocument,
} from "@/lib/types";
import { DocumentInventory } from "@/components/document-inventory";
import { JobActivityPanel, JobCenter } from "@/components/job-center";
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

      {tab === "documents" && <DocumentInventory live={live} fallbackDocuments={corpusDocuments} />}

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

function goldenAnswers(value: Record<string, unknown>): Array<Record<string, unknown>> {
  return Array.isArray(value.answers)
    ? value.answers.filter((answer): answer is Record<string, unknown> => typeof answer === "object" && answer !== null)
    : [];
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
