import { ApiError } from "./api";
import { failureReport } from "./pipeline";
import type { ChatMessage, ReviewExecution } from "./types";

/** Preserve the original error while providing one existing failure-card action in DEV. */
export function scopeFailurePatch(error: unknown, developer: boolean): Partial<ChatMessage> | null {
  if (!(error instanceof ApiError) || error.code !== "query_scope_unavailable") return null;
  const failure = { ...error.failure, code: error.code };
  const report = failureReport(failure, developer);
  const job = error.failure?.corpus_job as Record<string, unknown> | undefined;
  return {
    text: "Query scope metadata is unavailable.",
    evidenceLabel: "Retrieved candidates — answer not generated",
    scopeFailure: {
      causeText: report.text,
      ...(developer && typeof error.failure?.path === "string" ? { path: error.failure.path } : {}),
      ...(developer && typeof job?.job_id === "string" ? { jobId: job.job_id, jobRunning: ["running", "queued"].includes(String(job.status)) } : {}),
    },
    failureFix: developer ? report.fix : undefined,
    trace: developer ? `${error.message}${typeof error.failure?.detail === "string" ? ` ${error.failure.detail}` : ""}` : undefined,
  };
}

/** A typed server failure identifies whether the decision or later scope resolution failed. */
export function scopeFailureProgress(error: unknown, state: ReviewExecution): ReviewExecution {
  if (!(error instanceof ApiError)) return state;
  const pathStatus = error.failure?.failed_stage === "path" ? "failed" as const : state.pathStatus;
  return { ...state, pathStatus, pathDecision: error.pathDecision ?? state.pathDecision, ...(error.failure?.failed_stage === "gate" ? { node: "route" as const } : {}) };
}

/** A saved DEV failure remains recoverable without exposing its details in the public preview. */
export function publicScopeFailure(message: ChatMessage | null, developer: boolean): ChatMessage | null {
  return message?.scopeFailure && !developer ? { ...message, trace: undefined, diagnostics: undefined, failureFix: undefined, scopeFailure: { causeText: "Corpus metadata is unavailable. Try again later." } } : message;
}
