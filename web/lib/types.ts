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

export interface ExperimentDefaults {
  suite_id: SuiteId;
  golden_revision_id: number | null;
  snapshot_id: number | null;
  mode: "quick" | "matrix";
  baseline_snapshot_id: number | null;
  retrieval_preset: RetrievalPreset;
}

export interface WorkflowBudget {
  max_iterations: number;
  max_input_tokens: number;
  max_output_tokens: number;
  max_wall_clock_s: number;
}

export interface PromptPolicy {
  additional_instructions: string;
  history_turns: number;
  max_context_chars: number;
  evidence_overfetch: number;
  max_hits_per_document: number;
  workflow_budget: WorkflowBudget;
}

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
  snapshot_id: number | null;
  prompt_policy: PromptPolicy;
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
  golden_revision_id: number | null;
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

export interface PublishedSnapshot {
  snapshot_id: number;
  label: string;
  status: "ready" | "archived";
  public: boolean;
  corpus_fingerprint: string;
  profile: Record<string, unknown>;
  golden_revision_id: number | null;
  eval_result: {
    result_id: number;
    suite: string;
    config: Record<string, unknown>;
    metrics: Record<string, number>;
    created_at: string;
  };
  document_count: number;
  created_at: string;
}

export interface GoldenRevision {
  revision_id: number;
  suite_id: SuiteId;
  version: number;
  status: "draft" | "validated" | "published";
  payload: Array<Record<string, unknown>>;
  sha256: string;
  parent_id: number | null;
  created_at: string;
  updated_at: string;
}

export interface GoldenCanonical {
  suite_id: SuiteId;
  filename: string;
  payload: Array<Record<string, unknown>>;
  sha256: string;
}

export interface SnapshotComparison {
  baseline_id: number;
  candidate_id: number;
  directly_comparable: boolean;
  warning: string | null;
  metrics: Array<{ name: string; baseline: number; candidate: number; delta: number | null }>;
  common_case_count: number;
  cases: Array<{
    case_id: string;
    baseline_question: string;
    candidate_question: string;
    baseline_rank: number | null;
    candidate_rank: number | null;
    transition: "stable_hit" | "stable_miss" | "miss_to_hit" | "hit_to_miss";
    rank_delta: number | null;
  }>;
}

export type DocumentEmbeddingStatus = "complete" | "partial" | "missing";

export interface AdminDocument {
  doc_id: string;
  registry: string;
  language: string;
  issuer: string;
  issuer_id: string;
  fiscal_year: number;
  form: string;
  filing_date: string;
  report_period: string;
  filing_id: string;
  source_url: string;
  parse_status: string;
  source_length: number;
  source_sha256: string;
  chunk_count: number;
  embedded_chunks: number;
  text_chunks: number;
  table_chunks: number;
  embedding_status: DocumentEmbeddingStatus;
  snapshot_count: number;
}

export interface DocumentFacetValue {
  value: string;
  count: number;
  label: string | null;
}

export interface DocumentFacets {
  registries: DocumentFacetValue[];
  issuers: DocumentFacetValue[];
  years: DocumentFacetValue[];
  languages: DocumentFacetValue[];
  forms: DocumentFacetValue[];
  parse_statuses: DocumentFacetValue[];
  embedding_statuses: DocumentFacetValue[];
  snapshots: DocumentFacetValue[];
}

export interface DocumentDetail {
  document: Omit<AdminDocument, "embedded_chunks" | "text_chunks" | "table_chunks" | "embedding_status" | "snapshot_count">;
  chunks: Array<{
    chunk_id: number;
    ordinal: number;
    citation: string;
    span: string;
    source_sha256: string;
    body: string;
  }>;
  text_chunks: number;
  table_chunks: number;
  embedded_chunks: number;
  item_counts: Array<{ item: string; count: number }>;
  embedding_identities: Array<{
    provider: string;
    model: string;
    dimensions: number;
    count: number;
  }>;
  snapshot_memberships: Array<{
    snapshot_id: number;
    label: string;
    status: "ready" | "archived";
    public: boolean;
    created_at: string;
  }>;
}

export interface AdminDocumentPage {
  documents: AdminDocument[];
  total: number;
  next_cursor: string | null;
}

export type OperatorJobStatus = "queued" | "running" | "succeeded" | "failed" | "interrupted" | "cancelled";

export interface OperatorJob {
  job_id: string;
  domain: "corpus" | "evaluation";
  kind: string;
  request: Record<string, unknown>;
  status: OperatorJobStatus;
  stage: string;
  current: number;
  total: number | null;
  detail_current: number | null;
  detail_total: number | null;
  message: string;
  error_code: string | null;
  result_refs: Record<string, unknown>;
  queue_position: number | null;
  can_cancel: boolean;
  can_retry: boolean;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  updated_at: string;
}

export interface OperatorJobBoard {
  jobs: OperatorJob[];
  active_count: number;
  queued_count: number;
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

export const DEFAULT_EXPERIMENT_DEFAULTS: ExperimentDefaults = {
  suite_id: "sec-en",
  golden_revision_id: null,
  snapshot_id: null,
  mode: "quick",
  baseline_snapshot_id: null,
  retrieval_preset: "balanced",
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
  snapshot_id: null,
  prompt_policy: {
    additional_instructions: "",
    history_turns: 6,
    max_context_chars: 12000,
    evidence_overfetch: 3,
    max_hits_per_document: 2,
    workflow_budget: {
      max_iterations: 6,
      max_input_tokens: 60000,
      max_output_tokens: 4000,
      max_wall_clock_s: 120,
    },
  },
};

export interface Capabilities {
  can_edit_prompt_policy: boolean;
  can_edit_run_limits: boolean;
  can_edit_golden: boolean;
  can_build_snapshot: boolean;
  can_run_evaluation: boolean;
  can_change_custom_retrieval: boolean;
  can_query_snapshot: boolean;
  can_use_operations: boolean;
  can_compare_published_snapshots: boolean;
}

export interface ReleaseLimits {
  per_minute: number;
  per_day: number;
  remaining_minute: number;
  remaining_day: number;
  max_input_tokens: number;
  max_output_tokens: number;
  max_cost_usd: string;
  daily_cost_usd: string;
  remaining_daily_cost_usd: string;
  retry_after_seconds: number;
  minute_reset_seconds: number;
  day_reset_seconds: number;
  daily_cost_reset_at_utc: string;
  scope: "single_process";
}

export function resolvedRetrievalProfile(profile: ReviewSessionProfile): RetrievalProfile {
  if (profile.retrieval_preset === "custom" && profile.custom_retrieval) {
    return profile.custom_retrieval;
  }
  if (profile.retrieval_preset === "korean") {
    return { ...DEFAULT_PROFILE, candidate_k: 30, lexical_ranker: "bm25", route_by_language: true };
  }
  if (profile.retrieval_preset === "accuracy") {
    return { ...DEFAULT_PROFILE, candidate_k: 50, lexical_ranker: "bm25", reranker: "cross_encoder" };
  }
  return DEFAULT_PROFILE;
}
