import type { AdminDocument, CorpusSnapshot, EvaluationComparison, EvaluationJob, GoldenSuite, ManifestSummary } from "./types";
import { DEFAULT_PROFILE } from "./types";

export const CANNED_SUITES: GoldenSuite[] = [
  ["sec-en", "SEC 10-K · English", "sec", "en", "en"],
  ["sec-ko", "SEC 10-K · Korean questions", "sec", "ko", "en"],
  ["dart-en", "DART · English questions", "dart", "en", "ko"],
  ["dart-ko", "DART · Korean", "dart", "ko", "ko"],
].map(([suite_id, label, registry, question_language, corpus_language]) => ({
  suite_id: suite_id as GoldenSuite["suite_id"],
  label,
  registry: registry as GoldenSuite["registry"],
  question_language: question_language as GoldenSuite["question_language"],
  corpus_language: corpus_language as GoldenSuite["corpus_language"],
  case_count: 28,
  scored_positive_cases: 24,
  absent_cases: 4,
  curation_status: "agent-curated",
  approval_status: "pending-author-approval",
  human_verified: false,
  golden_sha256: "0".repeat(64),
  source_ready: true,
  source_error: null,
}));

/** Stored portfolio numbers shown when no administrator API is reachable. */
export const CANNED_CORPUS: { status: CorpusSnapshot["status"]; manifests: ManifestSummary[]; documents: AdminDocument[] } = {
  status: {
    database_connected: false,
    schema_status: "compatible",
    schema_message: "Portfolio fixture; no database access.",
    documents: 22,
    chunks: 10452,
    embedded_chunks: 10452,
    pending_embeddings: 0,
    bm25_ready: true,
    writable: false,
    provider: "deterministic",
  },
  manifests: [{
    name: "manifest.json", corpus_id: "demo", issuers: [], registries: ["sec", "dart"], documents: 22, valid: true, sources_present: 22,
    selections: [
      { selection_id: "sec-evaluation", document_ids: Array.from({ length: 20 }, (_, i) => `sec-${i}`), artifact_ids: Array.from({ length: 20 }, (_, i) => `sec-source-${i}`), sources_present: 20 },
      { selection_id: "dart-evaluation", document_ids: ["dart-0", "dart-1"], artifact_ids: ["dart-source-0", "dart-source-1"], sources_present: 2 },
    ],
  }],
  documents: [
    {
      doc_id: "NVDA-FY2024", registry: "sec", language: "en", issuer: "NVDA", issuer_id: "0001045810",
      fiscal_year: 2024, form: "10-K", filing_date: "2024-02-21", report_period: "2024-01-28",
      filing_id: "0001045810-24-000029", source_url: "https://www.sec.gov/Archives/edgar/data/1045810/000104581024000029/",
      parse_status: "parsed", source_length: 1_248_000, source_sha256: "0".repeat(64), chunk_count: 612,
      embedded_chunks: 612, text_chunks: 560, table_chunks: 52, embedding_status: "complete", snapshot_count: 0,
    },
    {
      doc_id: "005930-FY2024", registry: "dart", language: "ko", issuer: "005930", issuer_id: "00126380",
      fiscal_year: 2024, form: "사업보고서", filing_date: "2025-03-11", report_period: "2024-12-31",
      filing_id: "20250311000000", source_url: "https://dart.fss.or.kr/",
      parse_status: "parsed", source_length: 2_030_000, source_sha256: "0".repeat(64), chunk_count: 668,
      embedded_chunks: 668, text_chunks: 600, table_chunks: 68, embedding_status: "complete", snapshot_count: 0,
    },
  ],
};

export const CANNED_JOB: EvaluationJob = {
  job_id: "archived-crosslingual-vector-ko",
  request: {
    suite_id: "sec-ko",
    golden_revision_id: null,
    mode: "quick",
    profile: { ...DEFAULT_PROFILE, strategy: "vector", lexical_ranker: null },
    target_tokens: [1024, 2048],
    strategies: ["lexical", "vector", "hybrid"],
    lexical_rankers: ["ts_rank_cd", "bm25"],
  },
  status: "succeeded",
  stage: "complete",
  message: "Archived measured result",
  current: 4,
  total: 4,
  result_id: 16,
  result_ids: [16],
  baseline_id: 15,
  artifact_paths: [],
  created_at: "2026-09-01T00:00:00Z",
  started_at: "2026-09-01T00:00:00Z",
  finished_at: "2026-09-01T00:00:01Z",
};

export const CANNED_COMPARISON: EvaluationComparison = {
  baseline_id: 15,
  candidate_id: 16,
  suite: "m8-crosslingual-v1",
  metrics: [
    { name: "recall_at_k", baseline: 0.4166666667, candidate: 0.125, delta: -0.2916666667 },
    { name: "hit_rate_at_k", baseline: 0.4166666667, candidate: 0.125, delta: -0.2916666667 },
    { name: "mrr", baseline: 0.2777777778, candidate: 0.0638888889, delta: -0.2138888889 },
    { name: "mean_latency_ms", baseline: 35.35722075, candidate: 37.69624275, delta: 2.339022 },
  ],
  cases: [],
};
