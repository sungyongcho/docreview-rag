import type { EvaluationComparison, EvaluationJob, GoldenSuite } from "./types";
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

export const CANNED_JOB: EvaluationJob = {
  job_id: "archived-crosslingual-vector-ko",
  request: {
    suite_id: "sec-ko",
    mode: "quick",
    profile: { ...DEFAULT_PROFILE, strategy: "vector", lexical_ranker: null },
    target_text_chars: [500, 1200],
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
