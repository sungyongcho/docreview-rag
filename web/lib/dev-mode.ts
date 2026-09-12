/** Copy shared by every control that a public surface cannot operate. */
export const SOURCE_REPOSITORY_URL = "https://github.com/sungyongcho/docreview-rag";
export const SOURCE_REPOSITORY_LABEL = SOURCE_REPOSITORY_URL.replace(/^https?:\/\//, "");

/** The one lock sentence; the server returns the same text for a refused public request. */
export const DEV_ONLY_NOTE = "This control runs in DEV mode only.";

/** Short reasons for the hover bubble, keyed by the kind of work a locked control would start. */
export const DEV_ONLY_REASONS = {
  corpus: "Changing the server corpus runs in DEV mode only.",
  jobs: "Jobs run in DEV mode only.",
  golden: "Editing evaluation datasets runs in DEV mode only.",
  evaluation: "Evaluation runs happen in DEV mode only.",
  preview: "Answer previews run in DEV mode only.",
  settings: "Prompt and run-limit edits run in DEV mode only.",
  operations: "Operations run in DEV mode only.",
  snapshot: "Snapshot queries run in DEV mode only.",
} as const;
export type DevOnlyReason = keyof typeof DEV_ONLY_REASONS;
