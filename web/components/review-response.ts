import { failureMessage, failureReport } from "@/lib/pipeline";
import type { ChatMessage } from "@/lib/types";

export function terminalAnswer(payload: Record<string, unknown>): string {
  const root = (payload.run ?? payload) as Record<string, unknown>;
  const report = root.report as Record<string, unknown> | null;
  if (report?.report_kind === "conversation" && typeof report.answer === "string") return report.answer;
  if (report?.label === "SUPPORTED" && typeof report.answer === "string") return report.answer;
  if (report?.label === "NOT_IN_DOCS") {
    // The card adds the "related evidence" notice itself, so the text carries only the rationale.
    return typeof report.rationale === "string" ? report.rationale : "The filings do not contain direct support for this question.";
  }
  const failure = root.failure as Record<string, unknown> | null;
  if (failure) return failureMessage(failure);
  throw new Error("Review completed without a valid terminal report or failure.");
}

/** Evidence label for a terminal report; conversation replies and other unlabelled reports get none. */
export function terminalEvidenceLabel(payload: Record<string, unknown>): ChatMessage["evidenceLabel"] {
  const root = (payload.run ?? payload) as Record<string, unknown>;
  const report = root.report as Record<string, unknown> | null;
  if (report?.label === "SUPPORTED") return "Cited evidence";
  if (report?.label === "NOT_IN_DOCS") return "Related evidence — not direct support";
  if (report) return undefined;
  return "Retrieved candidates — answer not generated";
}

/** Citations the report made, as opposed to the candidate pool the stream sent earlier. */
export function terminalCitationCount(payload: Record<string, unknown>): number | undefined {
  const root = (payload.run ?? payload) as Record<string, unknown>;
  const report = root.report as Record<string, unknown> | null;
  return Array.isArray(report?.citations) ? report.citations.length : undefined;
}

export function extractTrace(payload: Record<string, unknown>): string {
  const root = (payload.run ?? payload) as Record<string, unknown>;
  const values = ["status", "total_requests", "total_input_tokens", "total_output_tokens", "total_time_seconds"];
  return values.filter((key) => root[key] !== undefined).map((key) => `${key}=${String(root[key])}`).join(" · ");
}

export const RUN_FACTS: ReadonlyArray<readonly [string, string]> = [
  ["status", "Status"],
  ["run_id", "Run id"],
  ["iterations", "Iterations"],
  ["total_requests", "Provider requests"],
  ["total_input_tokens", "Input tokens"],
  ["total_output_tokens", "Output tokens"],
  ["total_estimated_cost_usd", "Estimated cost"],
  ["total_time_seconds", "Elapsed seconds"],
];

/** Failure fields worth naming, keyed by the shape that carries them. */
export const FAILURE_FACTS: ReadonlyArray<readonly [string, string]> = [
  ["code", "Failure"],
  ["resource", "Exhausted resource"],
  ["limit", "Limit"],
  ["observed", "Observed"],
  ["blocked_node", "Blocked at"],
  ["status", "Provider status"],
  ["node", "Node"],
  ["attempts", "Attempts"],
  ["error_type", "Error type"],
  ["message", "Message"],
];

/** The settings destination for a terminal failure, when the failure names one. */
export function terminalFailureFix(payload: Record<string, unknown>): ChatMessage["failureFix"] {
  const root = (payload.run ?? payload) as Record<string, unknown>;
  const failure = root.failure as Record<string, unknown> | null;
  return failure ? failureReport(failure).fix : undefined;
}

/**
 * Flatten one terminal response into labelled rows.
 *
 * The run identifier is included deliberately: it is the only handle a reader has for
 * correlating a failure with `/runs/{id}` and its step traces, and the browser was
 * discarding it. Node paths are joined rather than dropped so the route a run took
 * before failing is visible.
 */
export function runDiagnostics(payload: Record<string, unknown>): Array<{ label: string; value: string }> {
  const root = (payload.run ?? payload) as Record<string, unknown>;
  const rows: Array<{ label: string; value: string }> = [];
  for (const [key, label] of RUN_FACTS) {
    if (root[key] !== undefined && root[key] !== null) rows.push({ label, value: String(root[key]) });
  }
  if (Array.isArray(root.node_path) && root.node_path.length) {
    rows.push({ label: "Node path", value: root.node_path.join(" → ") });
  }
  const failure = root.failure as Record<string, unknown> | null;
  if (failure) {
    for (const [key, label] of FAILURE_FACTS) {
      if (failure[key] !== undefined && failure[key] !== null) rows.push({ label, value: String(failure[key]) });
    }
    if (Array.isArray(failure.details) && failure.details.length) {
      rows.push({ label: "Details", value: failure.details.map(String).join(" · ") });
    }
  }
  return rows;
}
