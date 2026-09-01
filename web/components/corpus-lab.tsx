"use client";

import { Activity, Beaker, Braces, Database, FileSearch, Play, RefreshCw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import {
  apiBase,
  compareEvaluations,
  getCorpusSnapshot,
  getCorpusJobs,
  getEvaluationJobs,
  getEvaluationResult,
  getGoldenSuites,
  getProviderUsage,
  queueEvaluation,
  queueCorpusOperation,
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
} from "@/lib/types";

type LabTab = "overview" | "documents" | "golden" | "experiments" | "jobs" | "api" | "usage";

const TABS: Array<[LabTab, string]> = [
  ["overview", "Overview"],
  ["documents", "Documents"],
  ["golden", "Golden Tests"],
  ["experiments", "Experiments"],
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
}

export function CorpusLab({ live, ready = true, profile, onProfileChange, onApplyProfile }: CorpusLabProps) {
  const [tab, setTab] = useState<LabTab>("overview");
  const [suites, setSuites] = useState<GoldenSuite[]>(CANNED_SUITES);
  const [suiteId, setSuiteId] = useState<SuiteId>("sec-en");
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
  const [error, setError] = useState("");
  const [mode, setMode] = useState<"quick" | "matrix">("quick");
  const [chunkTargets, setChunkTargets] = useState("500 1200");
  const [rawRequest, setRawRequest] = useState("");
  const [rawResponse, setRawResponse] = useState("");
  const [registry, setRegistry] = useState<"sec" | "dart">("sec");
  const [identifiers, setIdentifiers] = useState("NVDA AMD");
  const [years, setYears] = useState("2023 2024");
  const [manifest, setManifest] = useState("manifest.json");
  const [corpusJobs, setCorpusJobs] = useState<Record<string, unknown>>({ history: [] });
  const [usage, setUsage] = useState<ProviderUsage>(EMPTY_USAGE);
  const [usageError, setUsageError] = useState("");
  const [environment, setEnvironment] = useState<"DEV" | "PROD">("PROD");
  const [selectedResultId, setSelectedResultId] = useState<number | null>(null);
  const [resultDetail, setResultDetail] = useState<EvaluationResultDetail | null>(null);

  const evaluationRequest = useMemo<EvaluationRequest>(() => ({
    suite_id: suiteId,
    mode,
    profile,
    target_text_chars: chunkTargets
      .split(/[\s,]+/)
      .map(Number)
      .filter((value) => Number.isInteger(value) && value > 0),
    strategies: ["lexical", "vector", "hybrid"],
    lexical_rankers: ["ts_rank_cd", "bm25"],
  }), [chunkTargets, mode, profile, suiteId]);

  useEffect(() => {
    setEnvironment(deploymentLabel(window.location.hostname));
  }, []);

  useEffect(() => {
    setRawRequest(JSON.stringify(evaluationRequest, null, 2));
  }, [evaluationRequest]);

  async function refresh() {
    if (!live) return;
    setError("");
    try {
      const [suiteRows, jobRows, corpusSnapshot, corpusJobRows] = await Promise.all([
        getGoldenSuites(), getEvaluationJobs(), getCorpusSnapshot(), getCorpusJobs(),
      ]);
      setSuites(suiteRows);
      setJobs(jobRows);
      setCorpus(corpusSnapshot);
      setCorpusJobs(corpusJobRows);
      setUsageError("");
      try {
        setUsage(await getProviderUsage());
      } catch (reason) {
        setUsageError(reason instanceof Error ? reason.message : "Usage could not be loaded.");
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Refresh failed.");
    }
  }

  useEffect(() => {
    void refresh();
    if (!live) return;
    const timer = window.setInterval(() => void getEvaluationJobs().then(setJobs), 1500);
    return () => window.clearInterval(timer);
  }, [live]);

  async function runEvaluation() {
    if (!live || !ready) return;
    setBusy(true);
    setError("");
    try {
      const job = await queueEvaluation(evaluationRequest);
      setJobs((current) => [job, ...current]);
      setTab("jobs");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Evaluation failed.");
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
      setError(reason instanceof Error ? reason.message : "Comparison failed.");
    }
  }

  async function openResult(resultId: number) {
    if (!live) return;
    setError("");
    try {
      setResultDetail(await getEvaluationResult(resultId));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Evaluation detail could not be loaded.");
    }
  }

  function useSelectedResult() {
    const job = jobs.find((item) => item.result_ids.includes(selectedResultId ?? -1));
    if (!job || selectedResultId === null) return;
    onApplyProfile(job.request.profile, `${job.request.suite_id}:${selectedResultId}`);
  }

  async function sendRawRequest() {
    if (!live) return;
    setError("");
    try {
      const body = JSON.parse(rawRequest) as Record<string, unknown>;
      const response = await fetch(`${apiBase()}/admin/evaluations/runs`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      });
      const payload = await response.json();
      setRawResponse(JSON.stringify(payload, null, 2));
      if (!response.ok) setError("The API rejected this request.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Invalid JSON request.");
    }
  }

  async function queueCorpus(body: Record<string, unknown>) {
    if (!live || !ready) return;
    setBusy(true);
    setError("");
    try {
      await queueCorpusOperation(body);
      setCorpusJobs(await getCorpusJobs());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Corpus operation failed.");
    } finally {
      setBusy(false);
    }
  }

  const status = (corpus.status ?? {}) as Record<string, unknown>;
  const selectedSuite = suites.find((suite) => suite.suite_id === suiteId) ?? suites[0];
  const corpusDocuments = Array.isArray(corpus.documents)
    ? (corpus.documents as Array<Record<string, unknown>>)
    : [];
  const corpusHistory = Array.isArray(corpusJobs.history)
    ? (corpusJobs.history as Array<Record<string, unknown>>)
    : [];
  const tabs = live ? [...TABS, ["usage", "Usage"] as [LabTab, string]] : TABS;
  const canRun = live && ready;

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
      {error && <div className="notice error" role="alert">{error}</div>}

      {tab === "overview" && <div className="panel-stack">
        <div className="metric-grid">
          <Metric icon={<Database />} label="Documents" value={String(status.documents ?? 22)} />
          <Metric icon={<FileSearch />} label="Chunks" value={String(status.chunks ?? 10452)} />
          <Metric icon={<Activity />} label="Embeddings" value={String(status.embedded_chunks ?? 10452)} />
          <Metric icon={<Beaker />} label="BM25" value={status.bm25_ready === false ? "Not ready" : "Ready"} />
        </div>
        <button className="button" type="button" onClick={() => void refresh()}><RefreshCw size={15} /> Refresh status</button>
        <section className="surface form-stack">
          <h2>Safe corpus operations</h2>
          <div className="profile-grid">
            <label>Registry<select value={registry} onChange={(event) => setRegistry(event.target.value as "sec" | "dart")}><option value="sec">SEC EDGAR</option><option value="dart">DART</option></select></label>
            <label>Tickers / stock codes<input value={identifiers} onChange={(event) => setIdentifiers(event.target.value)} /></label>
            <label>Fiscal years<input value={years} onChange={(event) => setYears(event.target.value)} /></label>
            <label>Manifest<select value={manifest} onChange={(event) => setManifest(event.target.value)}><option value="manifest.json">manifest.json</option><option value="dart-manifest.json">dart-manifest.json</option></select></label>
          </div>
          <div className="action-row">
            <button className="button" type="button" disabled={!canRun || busy} onClick={() => void queueCorpus({ kind: registry === "sec" ? "acquire_edgar" : "acquire_dart", identifiers: identifiers.split(/[\s,]+/).filter(Boolean), years: years.split(/[\s,]+/).map(Number).filter(Number.isInteger) })}>Acquire missing filings</button>
            <button className="button" type="button" disabled={!canRun || busy} onClick={() => void queueCorpus({ kind: "ingest_manifest", manifest })}>Ingest manifest</button>
            <button className="button" type="button" disabled={!canRun || busy} onClick={() => void queueCorpus({ kind: "backfill_embeddings" })}>Backfill embeddings</button>
            <button className="button" type="button" disabled={!canRun || busy} onClick={() => void queueCorpus({ kind: "rebuild_bm25" })}>Rebuild BM25</button>
          </div>
          {!live && <p className="helper">Actual acquisition and indexing are available only through the SSH operator tunnel.</p>}
          {corpusHistory.slice(0, 3).map((job) => <p className="helper" key={String(job.job_id)}>{String(job.status)} · {String(job.message)}</p>)}
        </section>
      </div>}

      {tab === "documents" && <section className="surface table-wrap"><h2>Document inventory</h2><table><thead><tr><th>Document</th><th>Registry</th><th>Issuer</th><th>Year</th><th>Language</th><th>Chunks</th><th>Status</th></tr></thead><tbody>{corpusDocuments.map((document) => <tr key={String(document.doc_id)}><td>{String(document.doc_id)}</td><td>{String(document.registry)}</td><td>{String(document.issuer)}</td><td>{String(document.fiscal_year)}</td><td>{String(document.language)}</td><td>{String(document.chunk_count)}</td><td>{String(document.parse_status)}</td></tr>)}</tbody></table>{!corpusDocuments.length && <p className="helper">No compatible live document rows are available.</p>}</section>}

      {tab === "golden" && <div className="two-column">
        <section className="surface form-stack">
          <label>Golden suite<select value={suiteId} onChange={(event) => setSuiteId(event.target.value as SuiteId)}>{suites.map((suite) => <option key={suite.suite_id} value={suite.suite_id}>{suite.label}</option>)}</select></label>
          {selectedSuite && <div className="provenance">
            <strong>{selectedSuite.case_count} cases</strong>
            <span>{selectedSuite.curation_status}</span><span>{selectedSuite.approval_status}</span>
            <span>human_verified=false</span>
            {!selectedSuite.source_ready && <span className="danger">Sources unavailable</span>}
          </div>}
          <label>Run mode<select value={mode} onChange={(event) => setMode(event.target.value as "quick" | "matrix")}><option value="quick">Quick · current index</option><option value="matrix">Matrix · isolated corpus</option></select></label>
          {mode === "matrix" && <label>Chunk targets<input value={chunkTargets} onChange={(event) => setChunkTargets(event.target.value)} placeholder="500 1200" /></label>}
          <ProfileFields profile={profile} onChange={onProfileChange} />
          <button className="button primary" type="button" disabled={!canRun || busy} onClick={() => void runEvaluation()}><Play size={15} /> {busy ? "Queueing…" : "Queue evaluation"}</button>
          {!live && <p className="helper">Public mode shows verified canned comparison data. Actual execution requires the SSH operator tunnel.</p>}
        </section>
        <section className="surface metric-table">
          <h2>Latest comparison</h2>
          {comparison.metrics.map((metric) => <div key={metric.name}><span>{metric.name}</span><strong>{metric.candidate.toFixed(3)}</strong><em className={metric.delta >= 0 ? "positive" : "negative"}>{metric.delta >= 0 ? "+" : ""}{metric.delta.toFixed(3)}</em></div>)}
          <p className="helper">Recall, Hit Rate, and MRR measure retrieval—not final-answer factuality.</p>
        </section>
      </div>}

      {tab === "experiments" && <div className="panel-stack">
        <div className="metric-grid">{comparison.metrics.map((metric) => <Metric key={metric.name} icon={<Beaker />} label={metric.name} value={`${metric.candidate.toFixed(3)} (${metric.delta >= 0 ? "+" : ""}${metric.delta.toFixed(3)})`} />)}</div>
        <section className="surface"><h2>Case changes</h2>{comparison.cases.map((item) => <article className="case-row" key={item.case_id}><div><strong>{item.case_id}</strong><p>{item.question}</p></div><span className={`transition ${item.transition}`}>{item.transition.replaceAll("_", " ")}</span></article>)}</section>
      </div>}

      {tab === "jobs" && <div className="two-column"><section className="surface"><div className="surface-heading"><h2>Evaluation jobs</h2><button className="button primary" type="button" disabled={!live || selectedResultId === null} onClick={useSelectedResult}>Use selected set</button></div>{jobs.map((job) => <article className="job-row" key={job.job_id}><div className="job-select"><input type="radio" name="evaluation-result" aria-label={`Select ${job.job_id}`} disabled={job.status !== "succeeded" || !job.result_id} checked={selectedResultId === job.result_id} onChange={() => setSelectedResultId(job.result_id)} /><button className="row-detail" type="button" disabled={!job.result_id} onClick={() => job.result_id && void openResult(job.result_id)}><strong>{job.request.suite_id} · {job.request.mode}</strong><p>{job.message}</p></button></div><span>{job.status}</span>{job.status === "succeeded" && job.result_id && job.baseline_id && <button className="button ghost" type="button" onClick={() => void loadComparison(job.result_id!, job.baseline_id!)}>Compare</button>}{job.result_ids.length > 1 && <div className="job-arms">{job.result_ids.map((resultId) => <label key={resultId}><input type="radio" name="evaluation-result" checked={selectedResultId === resultId} onChange={() => setSelectedResultId(resultId)} /> Result {resultId}</label>)}</div>}</article>)}</section><section className="surface detail-panel"><h2>Result details</h2>{resultDetail ? <><div className="metric-grid compact">{Object.entries(resultDetail.metrics).map(([name, value]) => <Metric key={name} icon={<Beaker />} label={name} value={value.toFixed(3)} />)}</div><pre>{JSON.stringify(resultDetail.config, null, 2)}</pre><h3>Cases</h3>{resultDetail.cases.slice(0, 10).map((item) => <article className="case-row" key={item.case_id}><div><strong>{item.case_id}</strong><p>{item.question}</p></div><span>{item.first_relevant_rank ? `rank ${item.first_relevant_rank}` : "miss"}</span></article>)}</> : <p className="helper">Select a succeeded result, then click its row to inspect metrics and cases.</p>}</section></div>}

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
