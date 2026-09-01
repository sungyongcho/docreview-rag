export type Strategy = "vector" | "lexical" | "hybrid";
export type LexicalRanker = "ts_rank_cd" | "bm25";
export type SuiteId = "sec-en" | "sec-ko" | "dart-en" | "dart-ko";

export interface RetrievalProfile {
  strategy: Strategy;
  k: number;
  candidate_k: number;
  rrf_k: number;
  lexical_ranker: LexicalRanker | null;
  bm25_k1: number;
  bm25_b: number;
  bm25_idf: "lucene" | "robertson";
  route_by_language: boolean;
  reranker: "cross_encoder" | null;
}

export type ReviewEngine = "openai" | "local";
export type CorpusScope = "auto" | "sec" | "dart";
export type RetrievalPreset = "balanced" | "korean" | "accuracy" | "custom";

export interface ReviewSessionProfile {
  engine: ReviewEngine;
  corpus_scope: CorpusScope;
  issuers: string[];
  languages: Array<"en" | "ko">;
  fiscal_years: number[];
  forms: string[];
  sections: Array<string | null>;
  retrieval_preset: RetrievalPreset;
  custom_retrieval: RetrievalProfile | null;
  applied_from_evaluation?: string | null;
}

export interface EvidenceHit {
  chunk_id: number;
  doc_id: string;
  item: string | null;
  kind: "text" | "table";
  citation: string;
  start_char: number;
  end_char: number;
  source_sha256: string;
  body: string;
  context_header: string;
  score: number;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  evidence?: EvidenceHit[];
  evidenceLabel?: "Cited evidence" | "Related evidence — not direct support" | "Retrieved candidates — answer not generated";
  trace?: string;
  question?: string;
  candidateToken?: string;
  pinnedChunkIds?: number[];
  excludedChunkIds?: number[];
}

export interface ModelPolicyRole {
  default: string;
  allowed: string[];
  reasoning_effort: "low" | "medium" | null;
  dimensions: number | null;
}

export interface Readiness {
  status: "ready" | "degraded";
  mode: "canned" | "runtime";
  admin_mode: "off" | "readonly" | "live";
  policy_revision: string;
  models: Record<string, ModelPolicyRole>;
  review_enabled: boolean;
  active_review_model: string | null;
  review_engines?: Record<string, { enabled?: boolean; model?: string | null; protocol?: string; reason?: string }>;
  corpus: {
    availability: "ready" | "degraded" | "not_applicable" | "unavailable";
    database_connected: boolean | null;
    schema_status: string | null;
    schema_message: string | null;
    documents: number | null;
    chunks: number | null;
    embedded_chunks: number | null;
    pending_embeddings: number | null;
    bm25_ready: boolean | null;
    writable: boolean | null;
  };
}

export interface UsageModel {
  model_name: string;
  requests: number;
  input_tokens: number;
  cached_input_tokens: number;
  cache_write_input_tokens: number;
  output_tokens: number;
  reasoning_tokens: number;
  estimated_cost_usd: string;
}

export interface ProviderUsage {
  runs: number;
  requests: number;
  input_tokens: number;
  cached_input_tokens: number;
  cache_write_input_tokens: number;
  output_tokens: number;
  reasoning_tokens: number;
  estimated_cost_usd: string;
  latest_run_at: string | null;
  models: UsageModel[];
}

export interface Conversation {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  messages: ChatMessage[];
  profile: ReviewSessionProfile | null;
}

export interface GoldenSuite {
  suite_id: SuiteId;
  label: string;
  registry: "sec" | "dart";
  question_language: "en" | "ko";
  corpus_language: "en" | "ko";
  case_count: number;
  scored_positive_cases: number;
  absent_cases: number;
  curation_status: "agent-curated";
  approval_status: "pending-author-approval";
  human_verified: false;
  golden_sha256: string;
  source_ready: boolean;
  source_error: string | null;
}

export interface EvaluationRequest {
  suite_id: SuiteId;
  mode: "quick" | "matrix";
  profile: RetrievalProfile;
  target_text_chars: number[];
  strategies: Strategy[];
  lexical_rankers: LexicalRanker[];
}

export interface EvaluationJob {
  job_id: string;
  request: EvaluationRequest;
  status: "queued" | "running" | "succeeded" | "failed";
  stage: string;
  message: string;
  current: number;
  total: number | null;
  result_id: number | null;
  result_ids: number[];
  baseline_id: number | null;
  artifact_paths: string[];
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface EvaluationComparison {
  baseline_id: number;
  candidate_id: number;
  suite: string;
  metrics: Array<{ name: string; baseline: number; candidate: number; delta: number }>;
  cases: Array<{
    case_id: string;
    question: string;
    baseline_rank: number | null;
    candidate_rank: number | null;
    transition: "stable_hit" | "stable_miss" | "miss_to_hit" | "hit_to_miss";
    rank_delta: number | null;
    baseline_citations: string[];
    candidate_citations: string[];
  }>;
}

export interface EvaluationResultDetail {
  result_id: number;
  suite: string;
  config: Record<string, unknown>;
  metrics: Record<string, number>;
  cases: Array<{
    case_id: string;
    question: string;
    first_relevant_rank: number | null;
    citations: string[];
  }>;
  raw_artifact_path: string;
  created_at: string;
}

export const DEFAULT_PROFILE: RetrievalProfile = {
  strategy: "hybrid",
  k: 5,
  candidate_k: 20,
  rrf_k: 60,
  lexical_ranker: "ts_rank_cd",
  bm25_k1: 1.2,
  bm25_b: 0.75,
  bm25_idf: "lucene",
  route_by_language: false,
  reranker: null,
};

export const DEFAULT_SESSION_PROFILE: ReviewSessionProfile = {
  engine: "openai",
  corpus_scope: "auto",
  issuers: [],
  languages: [],
  fiscal_years: [],
  forms: [],
  sections: [],
  retrieval_preset: "balanced",
  custom_retrieval: null,
  applied_from_evaluation: null,
};

export function resolvedRetrievalProfile(profile: ReviewSessionProfile): RetrievalProfile {
  if (profile.retrieval_preset === "custom" && profile.custom_retrieval) {
    return profile.custom_retrieval;
  }
  if (profile.retrieval_preset === "korean") {
    return { ...DEFAULT_PROFILE, candidate_k: 30, lexical_ranker: "bm25" };
  }
  if (profile.retrieval_preset === "accuracy") {
    return { ...DEFAULT_PROFILE, candidate_k: 50, lexical_ranker: "bm25", reranker: "cross_encoder" };
  }
  return DEFAULT_PROFILE;
}
