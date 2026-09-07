import type { components } from "./api-generated";
import { DEFAULT_SESSION_PROFILE } from "./types";
import { presentationFetch, type PresentationInit } from "./production-preview";
import type {
  EvaluationComparison,
  CorpusSnapshot,
  CorpusOperationRequest,
  EvaluationJob,
  EvaluationRequest,
  EvaluationResultDetail,
  EvidenceHit,
  GoldenSuite,
  GoldenCanonical,
  ProviderUsage,
  PublishedSnapshot,
  GoldenRevision,
  SnapshotComparison,
  DocumentDetail,
  DocumentFacets,
  AdminDocumentPage,
  OperatorJob,
  OperatorJobBoard,
  Readiness,
  Capabilities,
  LocalLLMConnection,
  LocalLLMDiagnostics,
  LocalLLMDiagnosticTarget,
  ReleaseLimits,
  RetrievalProfile,
  ReviewSessionProfile,
  SuiteId,
  ReviewPathDecision,
} from "./types";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "/docreview-rag-agent/api";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
    public readonly pathDecision?: ReviewPathDecision,
  ) {
    super(message);
  }
}

/** Deadline for read requests; writes and streams keep none because they may legitimately wait on a busy worker. */
export const REQUEST_TIMEOUT_MS = 15_000;

async function request<T>(path: string, init?: PresentationInit): Promise<T> {
  const method = (init?.method ?? "GET").toUpperCase();
  const read = method === "GET" || method === "HEAD";
  let response: Response;
  try {
    response = await presentationFetch(`${API_BASE}${path}`, {
      timeoutMs: read ? REQUEST_TIMEOUT_MS : undefined,
      ...init,
      headers: { "content-type": "application/json", ...init?.headers },
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "TimeoutError") {
      throw new ApiError(408, "request_timeout", "The request timed out; the API may be busy.");
    }
    throw error;
  }
  const text = await response.text();
  let payload: Record<string, unknown>;
  try {
    payload = JSON.parse(text) as Record<string, unknown>;
  } catch {
    throw new ApiError(response.status, "invalid_response", `The API returned an unexpected response (HTTP ${response.status}).`);
  }
  if (!response.ok) {
    const error = (payload.error ?? {}) as Record<string, unknown>;
    const details = Array.isArray(error.details) ? error.details.map(String) : [];
    const message = String(error.message ?? "The request failed.");
    throw new ApiError(
      response.status,
      String(error.code ?? "request_failed"),
      details.length ? `${message} ${details.join(" · ")}` : message,
      error.path_decision as ReviewPathDecision | undefined,
    );
  }
  return payload as T;
}

export interface RetrievePayload {
  path_decision?: ReviewPathDecision | null;
  results: EvidenceHit[];
  candidates: EvidenceHit[];
  candidate_token: string | null;
  candidate_expires_at: number;
  resolved_scope: Record<string, unknown> | null;
}

export async function retrieveEvidence(query: string, sessionProfile: ReviewSessionProfile): Promise<RetrievePayload> {
  return request<RetrievePayload>("/retrieve", {
    method: "POST",
    body: JSON.stringify({ query, session_profile: sessionProfile }),
  });
}

export interface ReviewProgress {
  path_decision?: ReviewPathDecision | null;
  node: "gate" | "route" | "retrieve" | "chat" | "grade" | "check" | "report";
  evidence_count: number;
  relevant_count: number;
  step_count: number;
  phase?: "start" | "end";
  status?: "running" | "completed" | "failed";
  started_at?: string;
  elapsed_ms?: number | null;
  total_elapsed_ms?: number;
  resolved_scope?: Record<string, unknown> | null;
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
  sessionProfile: ReviewSessionProfile,
  evidenceSelection: { candidateToken: string; pinned: number[]; excluded: number[] } | null,
  history: Array<{ role: "user" | "assistant"; text: string }>,
  onProgress: (progress: ReviewProgress) => void,
  signal?: AbortSignal,
  onCandidates?: (payload: RetrievePayload) => void,
): Promise<Record<string, unknown>> {
  const historyTurns = sessionProfile.prompt_policy?.history_turns ?? DEFAULT_SESSION_PROFILE.prompt_policy.history_turns;
  const response = await presentationFetch(`${API_BASE}/review/stream`, {
    method: "POST",
    headers: { "content-type": "application/json", "X-DocReview-Telemetry": "stages" },
    body: JSON.stringify({
      query,
      session_profile: sessionProfile,
      evidence_selection: evidenceSelection ? {
        candidate_token: evidenceSelection.candidateToken,
        pinned_chunk_ids: evidenceSelection.pinned,
        excluded_chunk_ids: evidenceSelection.excluded,
      } : null,
      conversation_history: historyTurns > 0 ? history.slice(-historyTurns) : [],
    }),
    signal,
  });
  if (!response.ok || !response.body) {
    const payload = await response.json().catch(() => ({})) as Record<string, unknown>;
    const error = (payload.error ?? {}) as Record<string, unknown>;
    const details = Array.isArray(error.details)
      ? error.details.map((item) => {
          const detail = item as Record<string, unknown>;
          const location = Array.isArray(detail.location) ? detail.location.join(".") : "request";
          return `${location}: ${String(detail.message ?? "invalid value")}`;
        })
      : [];
    const message = String(error.message ?? "Review stream failed.");
    throw new ApiError(
      response.status,
      String(error.code ?? "stream_failed"),
      details.length ? `${message} ${details.join(" · ")}` : message,
      error.path_decision as ReviewPathDecision | undefined,
    );
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
    if (frame.event === "node" || frame.event === "stage") {
      onProgress(payload as unknown as ReviewProgress);
      return;
    }
    if (frame.event === "candidates") {
      onCandidates?.(payload as unknown as RetrievePayload);
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
      throw new ApiError(503, String(error.code ?? "stream_error"), String(error.message ?? "Review failed."), error.path_decision as ReviewPathDecision | undefined);
    }
    if (frame.event === "done") {
      done = true;
      return;
    }
    throw new Error(`Review stream emitted an unknown event: ${frame.event}`);
  }

  // The fetch wrapper releases its signal bridge when headers arrive; retain cancellation
  // for the response body's full lifetime here, including an already-aborted request.
  const abort = () => { void reader.cancel().catch(() => undefined); };
  signal?.addEventListener("abort", abort, { once: true });
  if (signal?.aborted) abort();
  try {
    if (signal?.aborted) throw new DOMException("Request cancelled", "AbortError");
    while (true) {
      const { done: streamDone, value } = await reader.read();
      if (signal?.aborted) throw new DOMException("Request cancelled", "AbortError");
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
  } finally {
    signal?.removeEventListener("abort", abort);
    reader.releaseLock();
  }

}

export interface HealthResponse {
  status: "ok";
  mode?: "canned" | "runtime";
}

export async function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  const response = await presentationFetch(`${API_BASE}/health`, { signal });
  if (!response.ok) {
    throw new ApiError(response.status, "health_failed", "DocReview API health check failed.");
  }
  return response.json() as Promise<HealthResponse>;
}

export async function getReadiness(signal?: AbortSignal): Promise<Readiness> {
  const response = await presentationFetch(`${API_BASE}/ready`, { signal });
  const payload = await response.json() as Readiness;
  if (response.status !== 200 && response.status !== 503) {
    throw new ApiError(response.status, "readiness_failed", "Runtime readiness could not be loaded.");
  }
  return payload;
}

export function getCapabilities(): Promise<Capabilities> {
  return request<Capabilities>("/capabilities");
}

/** A preview knows only published catalog facts; uncollected runtime fields stay unknown. */
export async function getProductionPreviewReadiness(signal?: AbortSignal): Promise<Readiness> {
  const page = await request<AdminDocumentPage>("/public/documents?limit=1", { signal });
  if (!Number.isInteger(page.total) || page.total < 0) throw new Error("Invalid public catalog count.");
  return {
    status: "ready", mode: "runtime", admin_mode: "readonly", policy_revision: "—",
    models: {}, review_enabled: false, active_review_model: null,
    review_engines: { openai: { enabled: false, reason: "preview_read_only" }, local: { enabled: false, reason: "public_surface" } },
    corpus: {
      availability: "not_applicable", database_connected: null, schema_status: null,
      schema_message: null, documents: page.total, chunks: null, embedded_chunks: null,
      pending_embeddings: null, bm25_ready: null, writable: false,
    },
  };
}

export function getLocalLLMConnection(signal?: AbortSignal): Promise<LocalLLMConnection> {
  return request<LocalLLMConnection>("/admin/local-llm/connection", { signal });
}

export function saveLocalLLMConnection(base_url: string, protocol: LocalLLMConnection["protocol"]): Promise<LocalLLMConnection> {
  return request<LocalLLMConnection>("/admin/local-llm/connection", {
    method: "POST", body: JSON.stringify({ base_url, protocol }),
  });
}

export function addLocalLLMServer(name: string, base_url: string, protocol: LocalLLMConnection["protocol"]): Promise<LocalLLMConnection> {
  return request<LocalLLMConnection>("/admin/local-llm/servers", {
    method: "POST", body: JSON.stringify({ name, base_url, protocol }),
  });
}

export function selectLocalLLMServer(server_id: string): Promise<LocalLLMConnection> {
  return request<LocalLLMConnection>("/admin/local-llm/select", {
    method: "POST", body: JSON.stringify({ server_id }),
  });
}

export function diagnoseLocalLLM(target: LocalLLMDiagnosticTarget = {}, signal?: AbortSignal): Promise<LocalLLMDiagnostics> {
  return request<LocalLLMDiagnostics>("/admin/local-llm/diagnostics", {
    method: "POST", body: JSON.stringify(target), signal,
  });
}

export function disconnectLocalLLM(): Promise<LocalLLMConnection> {
  return request<LocalLLMConnection>("/admin/local-llm/disconnect", { method: "POST" });
}

export function resetLocalLLMConnection(): Promise<LocalLLMConnection> {
  return request<LocalLLMConnection>("/admin/local-llm/reset", { method: "POST" });
}

export function getReleaseLimits(): Promise<ReleaseLimits> {
  return request<ReleaseLimits>("/limits");
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

export function getEvaluationResult(resultId: number): Promise<EvaluationResultDetail> {
  return request<EvaluationResultDetail>(`/admin/evaluations/results/${resultId}`);
}

export function getCorpusSnapshot(): Promise<CorpusSnapshot> {
  return request<CorpusSnapshot>("/admin/corpus");
}

export function queueCorpusOperation(body: CorpusOperationRequest): Promise<Record<string, unknown>> {
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

export async function getPublishedSnapshots(): Promise<PublishedSnapshot[]> {
  const payload = await request<{ snapshots: PublishedSnapshot[] }>("/snapshots");
  return payload.snapshots;
}

export function getAdminSnapshots(): Promise<PublishedSnapshot[]> {
  return request<PublishedSnapshot[]>("/admin/snapshots");
}

export function createSnapshot(body: { label: string; eval_result_id: number; golden_revision_id: number | null; public: boolean }): Promise<PublishedSnapshot> {
  return request<PublishedSnapshot>("/admin/snapshots", { method: "POST", body: JSON.stringify(body) });
}

export function setSnapshotVisibility(snapshotId: number, value: boolean): Promise<PublishedSnapshot> {
  return request<PublishedSnapshot>(`/admin/snapshots/${snapshotId}/visibility`, { method: "PUT", body: JSON.stringify({ public: value }) });
}

export function compareSnapshots(baselineId: number, candidateId: number, live: boolean): Promise<SnapshotComparison> {
  const prefix = live ? "/admin" : "";
  return request<SnapshotComparison>(`${prefix}/snapshots/compare?baseline_id=${baselineId}&candidate_id=${candidateId}`);
}

export function getGoldenRevisions(suiteId: SuiteId): Promise<GoldenRevision[]> {
  return request<GoldenRevision[]>(`/admin/golden/${suiteId}/revisions`);
}

export function getGoldenCanonical(suiteId: SuiteId): Promise<GoldenCanonical> {
  return request<GoldenCanonical>(`/admin/golden/${suiteId}/canonical`);
}

export function createGoldenDraft(suiteId: SuiteId, parentId: number | null): Promise<GoldenRevision> {
  return request<GoldenRevision>(`/admin/golden/${suiteId}/drafts`, { method: "POST", body: JSON.stringify({ parent_id: parentId }) });
}

export function saveGoldenCase(revisionId: number, caseId: string, expectedSha256: string, value: Record<string, unknown>): Promise<GoldenRevision> {
  return request<GoldenRevision>(`/admin/golden/revisions/${revisionId}/cases/${caseId}`, { method: "PUT", body: JSON.stringify({ expected_sha256: expectedSha256, case: value }) });
}

export function transitionGoldenRevision(revisionId: number, action: "validate" | "publish", expectedSha256: string): Promise<GoldenRevision> {
  return request<GoldenRevision>(`/admin/golden/revisions/${revisionId}/${action}`, { method: "POST", body: JSON.stringify({ expected_sha256: expectedSha256 }) });
}

export function getAdminDocuments(params: URLSearchParams): Promise<AdminDocumentPage> {
  return request<AdminDocumentPage>(`/admin/documents?${params.toString()}`);
}

export function getDocumentFacets(registry = "", signal?: AbortSignal): Promise<DocumentFacets> {
  return request<DocumentFacets>(`/admin/documents/facets${registry ? `?registry=${encodeURIComponent(registry)}` : ""}`, { signal }).then(facets => ({ ...facets, sections: facets.sections ?? [] }));
}

export function getPublishedDocuments(params: URLSearchParams): Promise<AdminDocumentPage> {
  return request<AdminDocumentPage>(`/public/documents?${params.toString()}`);
}

export function getPublishedDocumentFacets(registry = "", signal?: AbortSignal): Promise<DocumentFacets> {
  return request<DocumentFacets>(`/public/documents/facets${registry ? `?registry=${encodeURIComponent(registry)}` : ""}`, { signal }).then(facets => ({ ...facets, sections: facets.sections ?? [] }));
}

export function getPublishedDocumentDetail(docId: string): Promise<DocumentDetail> {
  return request<DocumentDetail>(`/public/documents/${encodeURIComponent(docId)}`);
}

export function getOperatorJobs(signal?: AbortSignal): Promise<OperatorJobBoard> {
  return request<OperatorJobBoard>("/admin/jobs", { signal });
}

export function retryOperatorJob(jobId: string): Promise<OperatorJob> {
  return request<OperatorJob>(`/admin/jobs/${encodeURIComponent(jobId)}/retry`, {
    method: "POST",
  });
}

export function cancelOperatorJob(jobId: string): Promise<OperatorJob> {
  return request<OperatorJob>(`/admin/jobs/${encodeURIComponent(jobId)}/cancel`, {
    method: "POST",
  });
}

export function getDocumentDetail(docId: string): Promise<DocumentDetail> {
  return request<DocumentDetail>(`/admin/documents/${encodeURIComponent(docId)}`);
}

export function apiBase(): string {
  return API_BASE;
}

export function getJobHistorySummary() {
  return request<components["schemas"]["JobHistorySummaryResource"]>("/admin/jobs/history");
}

export function manageJobHistory(payload: Omit<components["schemas"]["JobHistoryRequest"], "confirmation"> & { confirmation?: string }) {
  return request<components["schemas"]["JobHistoryResultResource"]>("/admin/jobs/history", { method: "POST", body: JSON.stringify(payload) });
}

export function jobHistoryBackupUrl(id: string): string {
  return `${API_BASE}/admin/jobs/history/backups/${encodeURIComponent(id)}`;
}
