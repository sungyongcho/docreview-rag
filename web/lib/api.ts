import type {
  EvaluationComparison,
  EvaluationJob,
  EvaluationRequest,
  EvidenceHit,
  GoldenSuite,
  RetrievalProfile,
} from "./types";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "/docreview-rag-agent/api";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "content-type": "application/json", ...init?.headers },
  });
  const payload = (await response.json()) as Record<string, unknown>;
  if (!response.ok) {
    const error = (payload.error ?? {}) as Record<string, unknown>;
    throw new ApiError(
      response.status,
      String(error.code ?? "request_failed"),
      String(error.message ?? "The request failed."),
    );
  }
  return payload as T;
}

export async function retrieveEvidence(query: string, k = 5): Promise<EvidenceHit[]> {
  const payload = await request<{ results: EvidenceHit[] }>("/retrieve", {
    method: "POST",
    body: JSON.stringify({ query, k, filters: {} }),
  });
  return payload.results;
}

export async function reviewQuestion(query: string, k = 5): Promise<Record<string, unknown>> {
  return request<Record<string, unknown>>("/review", {
    method: "POST",
    body: JSON.stringify({ query, k, filters: {} }),
  });
}

export async function previewRetrieval(query: string, profile: RetrievalProfile) {
  return request<{
    query: string;
    profile: RetrievalProfile;
    score_stage: string;
    component_rankings: Record<string, number[]>;
    results: EvidenceHit[];
  }>("/admin/retrieval/preview", {
    method: "POST",
    body: JSON.stringify({ query, profile, filters: {} }),
  });
}

export async function previewReview(query: string, profile: RetrievalProfile) {
  return request<Record<string, unknown>>("/admin/review/preview", {
    method: "POST",
    body: JSON.stringify({ query, profile, filters: {} }),
  });
}

export function getGoldenSuites(): Promise<GoldenSuite[]> {
  return request<GoldenSuite[]>("/admin/evaluations/suites");
}

export function queueEvaluation(body: EvaluationRequest): Promise<EvaluationJob> {
  return request<EvaluationJob>("/admin/evaluations/runs", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function getEvaluationJobs(): Promise<EvaluationJob[]> {
  const payload = await request<{ jobs: EvaluationJob[] }>("/admin/evaluations/runs");
  return payload.jobs;
}

export function compareEvaluations(candidateId: number, baselineId: number) {
  return request<EvaluationComparison>(
    `/admin/evaluations/compare?candidate_id=${candidateId}&baseline_id=${baselineId}`,
  );
}

export function getCorpusSnapshot(): Promise<Record<string, unknown>> {
  return request<Record<string, unknown>>("/admin/corpus");
}

export function queueCorpusOperation(body: Record<string, unknown>): Promise<Record<string, unknown>> {
  return request<Record<string, unknown>>("/admin/corpus/jobs", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function getCorpusJobs(): Promise<Record<string, unknown>> {
  return request<Record<string, unknown>>("/admin/corpus/jobs");
}

export function apiBase(): string {
  return API_BASE;
}
