import { ApiError } from "./api";
import { failureReport } from "./pipeline";
import type { ChatMessage, ReviewExecution, ReviewPathDecision } from "./types";

const LIMIT_REASONS = new Set(["unsupported_request", "unknown_issuer", "ambiguous_issuer", "query_scope_empty", "query_scope_conflict", "profile_scope_conflict", "service_guidance"]);

/** Only explicit server policy outcomes qualify as expected early stops. */
export function isReviewLimitation(decision?: ReviewPathDecision): boolean {
  return Boolean(decision?.stopping_stage && decision.stopping_reason && LIMIT_REASONS.has(decision.stopping_reason));
}

/** Localize policy results from stable reason codes, retaining server-identified companies. */
export function reviewLimitationMessage(decision: ReviewPathDecision, t: (key: string, values?: Record<string, string | number>) => string): string {
  if (decision.stopping_reason === "unsupported_request") return t("Please ask a question about company filings or financial information.");
  if (decision.stopping_reason === "unknown_issuer") return t("The available filings do not cover {companies}. Please choose a company in the provided corpus.", { companies: (decision.missing_issuers ?? decision.requested_issuers ?? []).join(", ") });
  if (decision.stopping_reason === "ambiguous_issuer") return t("Please specify which company you want to analyze.");
  if (decision.stopping_reason === "service_guidance") return t("Ask a question about the available company filings. Choose a company and fiscal year, then inspect the cited evidence.");
  if (decision.stopping_reason === "query_scope_empty") return t("No filings match the requested company, year, and document scope. Adjust the filters.");
  if (decision.stopping_reason === "query_scope_conflict" || decision.stopping_reason === "profile_scope_conflict") return t("The requested company is outside the selected document scope.");
  return t(decision.stopping_message ?? "The requested filing scope is unavailable.");
}

/** Preserve the original error while providing one existing failure-card action in DEV. */
export function scopeFailurePatch(error: unknown, developer: boolean): Partial<ChatMessage> | null {
  if (error instanceof ApiError && isReviewLimitation(error.pathDecision)) return { text: error.message, evidence: [], evidenceLabel: undefined, citations: undefined };
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
  if (isReviewLimitation(error.pathDecision)) return { ...state, pathDecision: error.pathDecision, pathStatus: "done", node: error.pathDecision?.stopping_stage === "gate" ? "route" : "gate", activeNode: null };
  const pathStatus = error.failure?.failed_stage === "path" ? "failed" as const : state.pathStatus;
  return { ...state, pathStatus, pathDecision: error.pathDecision ?? state.pathDecision, ...(error.failure?.failed_stage === "gate" ? { node: "route" as const } : {}) };
}

/** A saved DEV failure remains recoverable without exposing its details in the public preview. */
export function publicScopeFailure(message: ChatMessage | null, developer: boolean): ChatMessage | null {
  return message?.scopeFailure && !developer ? { ...message, trace: undefined, diagnostics: undefined, failureFix: undefined, scopeFailure: { causeText: "Corpus metadata is unavailable. Try again later." } } : message;
}
