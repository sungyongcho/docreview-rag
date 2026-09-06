import type { components } from "./api-generated";

export type Strategy = "vector" | "lexical" | "hybrid";
export type LexicalRanker = "ts_rank_cd" | "bm25";
export type SuiteId = "sec-en" | "sec-ko" | "dart-en" | "dart-ko" | "sec-en_v2_astra" | "sec-ko_v2_astra" | "sec-mixed_v2_astra";

export type RetrievalProfile = components["schemas"]["RetrievalProfile"];

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

export type PromptPolicy = components["schemas"]["PromptPolicy"];

export type ReviewSessionProfile = components["schemas"]["ReviewSessionProfile"];
/** Fully initialized form state; wire requests may omit fields with server defaults. */
export type ReviewSessionDraft = Required<Omit<ReviewSessionProfile, "prompt_policy">> & {
  prompt_policy: Required<PromptPolicy>;
};

export type EvidenceHit = components["schemas"]["EvidenceHit"];

export type ReviewEventNode = "waiting" | "gate" | "route" | "retrieve" | "chat" | "grade" | "check" | "report" | "candidates";
/** Actual scope resolved by the server; absent on older conversation records. */
export interface ReviewResolvedScope {
  source?: string;
  filters: { registries: string[]; issuers: string[]; fiscal_years: number[] };
}
export interface ReviewExecution {
  node: ReviewEventNode;
  evidence: number;
  relevant: number;
  steps: number;
  observed?: ReviewEventNode[];
  outcome?: "running" | "completed" | "failed" | "cancelled";
  revalidating?: boolean;
  retries?: number;
  elapsedMs?: number;
  startedAt?: number;
  lastEventAt?: number;
  activeNode?: ReviewEventNode | null;
  completedNodes?: ReviewEventNode[];
  selectedScope?: CorpusScope;
  resolvedScope?: ReviewResolvedScope;
  stageTimings?: Array<{ node: ReviewEventNode; elapsed_ms: number; status: string }>;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  evidence?: EvidenceHit[];
  evidenceLabel?: "Cited evidence" | "Related evidence — not direct support" | "Retrieved candidates — answer not generated";
  /** Citations the report actually made; the evidence list above is the wider candidate pool. */
  citations?: number;
  trace?: string;
  /** Only events observed for this request; absent for older conversations. */
  execution?: ReviewExecution;
  performance?: Record<string, unknown>;
  /** Run and failure facts for the diagnostic table, in display order. */
  diagnostics?: Array<{ label: string; value: string }>;
  /** Settings destination that would change the outcome, when one exists. */
  failureFix?: { label: string; category: "limits" | "runtime" };
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

export interface LocalModelInfo {
  name: string;
  selectable: boolean;
  size_bytes: number | null;
  family: string | null;
  parameter_size: string | null;
  quantization_level: string | null;
  capabilities: string[] | null;
  loaded: boolean | null;
}

/** One entry of `/ready.review_engines`: what an engine is, and why it is not serving. */
export interface ReviewEngineState {
  enabled?: boolean;
  model?: string | null;
  protocol?: string;
  reason?: string | null;
  key_slot?: string | null;
  models?: LocalModelInfo[];
  checked_at?: string;
}

export interface Readiness {
  environment?: "dev" | "prod";
  status: "ready" | "degraded";
  mode: "canned" | "runtime";
  admin_mode: "off" | "readonly" | "live";
  policy_revision: string;
  models: Record<string, ModelPolicyRole>;
  review_enabled: boolean;
  active_review_model: string | null;
  review_engines?: Record<string, ReviewEngineState>;
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

export type UsageModel = components["schemas"]["UsageModelResource"];

export type ProviderUsage = components["schemas"]["UsageResponse"];

export interface Conversation {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  messages: ChatMessage[];
  profile: ReviewSessionDraft | null;
}

export type GoldenSuite = components["schemas"]["GoldenSuiteResource"];

export type EvaluationRequest = components["schemas"]["EvaluationRunRequest"] & Required<Pick<components["schemas"]["EvaluationRunRequest"], "profile">>;

export type EvaluationJob = components["schemas"]["EvaluationJobResource"];

export type EvaluationComparison = components["schemas"]["EvaluationComparisonResponse"];

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

export type GoldenRevision = components["schemas"]["GoldenRevisionResource"];

export type GoldenCanonical = components["schemas"]["GoldenCanonicalResource"];

export type SnapshotComparison = components["schemas"]["SnapshotComparisonResponse"];

/** One selectable corpus manifest as reported by `/admin/corpus`. */
export type ManifestSummary = components["schemas"]["ManifestResource"];
export type ProcessingSelection = components["schemas"]["ProcessingSelectionResource"];
export type CorpusDocument = components["schemas"]["CorpusDocumentResource"];
export type CorpusSnapshot = components["schemas"]["CorpusSnapshotResource"];
export type CorpusOperationRequest = components["schemas"]["CorpusOperationRequest"];


/** Field subset shared by `/ready`.corpus and `/admin/corpus`.status. */
export interface CorpusCounts {
  database_connected: boolean | null;
  schema_status: string | null;
  schema_message: string | null;
  documents: number | null;
  chunks: number | null;
  embedded_chunks: number | null;
  pending_embeddings: number | null;
  bm25_ready: boolean | null;
  writable: boolean | null;
  provider?: string | null;
}

export type DocumentEmbeddingStatus = "complete" | "partial" | "missing";

export type AdminDocument = components["schemas"]["AdminDocumentResource"];

export type DocumentFacetValue = components["schemas"]["DocumentFacetValue"];

export type DocumentFacets = components["schemas"]["DocumentFacetsResponse"];

export type DocumentDetail = components["schemas"]["DocumentDetailResponse"];

export type AdminDocumentPage = components["schemas"]["DocumentInventoryResponse"];

export type OperatorJobStatus = "queued" | "running" | "succeeded" | "failed" | "interrupted" | "cancelled";

export type OperatorJob = components["schemas"]["OperatorJobResource"];

export type OperatorJobBoard = components["schemas"]["OperatorJobsResponse"];


export type EvaluationResultDetail = components["schemas"]["EvaluationResultDetailResponse"];

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

export const DEFAULT_SESSION_PROFILE: ReviewSessionDraft = {
  engine: "openai",
  local_model: null,
  corpus_scope: "auto",
  doc_ids: [],
  registries: [],
  kinds: [],
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
  environment: "dev" | "prod";
  can_configure_local_llm: boolean;
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

export interface LocalLLMConnection {
  base_url: string | null;
  initial_base_url: string;
  protocol: "auto" | "ollama" | "openai_responses";
  source: "saved" | "environment" | "dotenv" | "default" | "disabled" | "invalid";
  error: string | null;
  local: ReviewEngineState;
  servers?: LocalLLMServer[];
  selected_server_id?: string | null;
}

export interface LocalLLMServer {
  id: string;
  name: string;
  base_url: string;
  protocol: LocalLLMConnection["protocol"];
  is_default: boolean;
}

export type LocalLLMDiagnosticTarget = { server_id: string } | { base_url: string; protocol: LocalLLMConnection["protocol"] } | Record<string, never>;

export interface LocalLLMDiagnostics {
  checked_at: string;
  server_id: string | null;
  server_name: string;
  protocol: string;
  reachable: boolean | null;
  available: boolean;
  model_count: number | null;
  answer_model_count: number | null;
  models: LocalModelInfo[];
  checks: Array<{ id: "configuration" | "connection" | "models"; status: "passed" | "failed" | "blocked" | "unknown"; code: string; remediation: string[] }>;
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

/** Session fields for choosing a preset: only Custom keeps an explicit retrieval profile. */
export function applyRetrievalPreset(profile: ReviewSessionProfile, preset: RetrievalPreset): Pick<ReviewSessionProfile, "retrieval_preset" | "custom_retrieval"> {
  return { retrieval_preset: preset, custom_retrieval: preset === "custom" ? profile.custom_retrieval ?? DEFAULT_PROFILE : null };
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
