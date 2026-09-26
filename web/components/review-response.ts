import { failureReport } from "@/lib/pipeline";
import type { ChatMessage, ReviewRun } from "@/lib/types";

/** Decode the current terminal wire report once for both review request paths. */
export function terminalMessage(run: ReviewRun): Pick<ChatMessage, "pending" | "text" | "performance" | "evidenceLabel" | "citations" | "trace" | "diagnostics" | "failureFix"> {
  const report = run.report;
  const failure = run.failure ? failureReport(run.failure) : undefined;
  let text: string;
  let evidenceLabel: ChatMessage["evidenceLabel"];
  let citations: number | undefined;
  if (report && "label" in report) {
    text = report.label === "SUPPORTED" ? report.answer : report.rationale;
    evidenceLabel = report.label === "SUPPORTED" ? "Cited evidence" : "Related evidence — not direct support";
    citations = report.citations.length;
  } else if (report?.report_kind === "conversation") {
    text = report.answer;
  } else if (failure) {
    text = failure.text;
    evidenceLabel = "Retrieved candidates — answer not generated";
  } else {
    throw new Error("Review completed without a valid terminal report or failure.");
  }
  const traceFields = ["status", "total_requests", "total_input_tokens", "total_output_tokens", "total_time_seconds"] as const;
  return {
    pending: false, text, performance: run.execution ?? undefined, evidenceLabel, citations,
    trace: traceFields.filter(key => run[key] !== undefined).map(key => `${key}=${String(run[key])}`).join(" · "),
    diagnostics: runDiagnostics(run), failureFix: failure?.fix,
  };
}

export const RUN_FACTS: ReadonlyArray<readonly [keyof ReviewRun, string]> = [
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

/**
 * Flatten one terminal response into labelled rows.
 *
 * The run identifier is included deliberately: it is the only handle a reader has for
 * correlating a failure with `/runs/{id}` and its step traces, and the browser was
 * discarding it. Node paths are joined rather than dropped so the route a run took
 * before failing is visible.
 */
function runDiagnostics(root: ReviewRun): Array<{ label: string; value: string }> {
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
