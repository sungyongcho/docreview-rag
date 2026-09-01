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
  trace?: string;
}

export interface Conversation {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  messages: ChatMessage[];
  profile: RetrievalProfile | null;
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
