import type {
  EvaluationComparison,
  EvaluationJob,
  EvaluationRequest,
  EvidenceHit,
  GoldenSuite,
  ProviderUsage,
  Readiness,
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
    const details = Array.isArray(error.details) ? error.details.map(String) : [];
    const message = String(error.message ?? "The request failed.");
    throw new ApiError(
      response.status,
      String(error.code ?? "request_failed"),
      details.length ? `${message} ${details.join(" · ")}` : message,
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

export interface ReviewProgress {
  node: "retrieve" | "grade" | "check" | "report";
  evidence_count: number;
  relevant_count: number;
  step_count: number;
}

function parseSseFrame(frame: string): { event: string; data: string } | null {
  let event = "";
  const data: string[] = [];
  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
  }
  return event && data.length ? { event, data: data.join("\n") } : null;
}

export async function streamReview(
  query: string,
  k: number,
  onProgress: (progress: ReviewProgress) => void,
  signal?: AbortSignal,
): Promise<Record<string, unknown>> {
  const response = await fetch(`${API_BASE}/review/stream`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ query, k, filters: {} }),
    signal,
  });
  if (!response.ok || !response.body) {
    const payload = await response.json().catch(() => ({})) as Record<string, unknown>;
    const error = (payload.error ?? {}) as Record<string, unknown>;
    throw new ApiError(response.status, String(error.code ?? "stream_failed"), String(error.message ?? "Review stream failed."));
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let terminal: Record<string, unknown> | null = null;
  let done = false;

  async function consume(frameText: string) {
    const frame = parseSseFrame(frameText);
    if (!frame) return;
    const payload = JSON.parse(frame.data) as Record<string, unknown>;
    if (frame.event === "node") {
      onProgress(payload as unknown as ReviewProgress);
      return;
    }
    if (frame.event === "report") {
      if (terminal) throw new Error("Review stream emitted more than one terminal event.");
      terminal = payload;
      return;
    }
    if (frame.event === "error") {
      if (terminal) throw new Error("Review stream emitted more than one terminal event.");
      const error = (payload.error ?? {}) as Record<string, unknown>;
      throw new ApiError(503, String(error.code ?? "stream_error"), String(error.message ?? "Review failed."));
    }
    if (frame.event === "done") {
      done = true;
      return;
    }
    throw new Error(`Review stream emitted an unknown event: ${frame.event}`);
  }

  while (true) {
    const { done: streamDone, value } = await reader.read();
    buffer += decoder.decode(value ?? new Uint8Array(), { stream: !streamDone }).replaceAll("\r\n", "\n");
    let boundary = buffer.indexOf("\n\n");
    while (boundary >= 0) {
      const frame = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      await consume(frame);
      boundary = buffer.indexOf("\n\n");
    }
    if (streamDone) break;
  }
  if (buffer.trim()) await consume(buffer);
  if (!done || !terminal) throw new Error("Review stream ended without a terminal report and done event.");
  return terminal;
}

export interface HealthResponse {
  status: "ok";
  mode?: "canned" | "runtime";
}

export async function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  const response = await fetch(`${API_BASE}/health`, { signal });
  if (!response.ok) {
    throw new ApiError(response.status, "health_failed", "DocReview API health check failed.");
  }
  return response.json() as Promise<HealthResponse>;
}

export async function getReadiness(signal?: AbortSignal): Promise<Readiness> {
  const response = await fetch(`${API_BASE}/ready`, { signal });
  const payload = await response.json() as Readiness;
  if (response.status !== 200 && response.status !== 503) {
    throw new ApiError(response.status, "readiness_failed", "Runtime readiness could not be loaded.");
  }
  return payload;
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

export function getProviderUsage(): Promise<ProviderUsage> {
  return request<ProviderUsage>("/admin/usage");
}

export function apiBase(): string {
  return API_BASE;
}
