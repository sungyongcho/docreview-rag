/** Labels shared by recorded stage tables without inferring unrecorded execution. */
export const STAGE_LABELS: Record<string, string> = {
  gate: "Understand the question", route: "Resolve filing scope", retrieve: "Retrieve evidence",
  candidates: "Collect candidate evidence", grade: "Select relevant evidence",
  check: "Verify answer and citations", report: "Prepare the result", chat: "Reply to the conversation",
};

/** Reject absent and invalid measurements without conflating a measured zero. */
export function collectedNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0;
}

/** Keep measured durations legible, preserving the inspector's established units. */
export function formatDuration(value: unknown, locale: string, missing: string): string {
  if (!collectedNumber(value)) return missing;
  if (value > 0 && value < 1) return "<1ms";
  if (value < 1000) return `${value.toLocaleString(locale, { maximumFractionDigits: 2 })}ms`;
  return `${(value / 1000).toLocaleString(locale, { maximumFractionDigits: 2 })}s`;
}
