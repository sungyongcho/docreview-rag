"use client";

import type { ReviewProgress } from "@/lib/api";

export type ReviewNode = "gate" | "route" | "retrieve" | "chat" | "grade" | "check" | "report" | "candidates";

export interface ReviewProgressState {
  node: ReviewNode;
  evidence: number;
  relevant: number;
  steps: number;
  /** A "Use selected evidence" run: the stepper carries the re-check prefix but follows the real nodes. */
  revalidating?: boolean;
}

export const REVIEW_STEPS: ReadonlyArray<{ node: ReviewNode; label: string }> = [
  { node: "gate", label: "Classify" },
  { node: "route", label: "Scope" },
  { node: "retrieve", label: "Retrieve" },
  { node: "grade", label: "Grade" },
  { node: "check", label: "Check citations" },
  { node: "report", label: "Report" },
];

/** Maps a `/review/stream` progress event onto the stepper state. */
export function reviewProgressFromEvent(event: ReviewProgress): ReviewProgressState {
  return { node: event.node, evidence: event.evidence_count, relevant: event.relevant_count, steps: event.step_count };
}

/** Index of the highlighted step; `candidates` lands on Grade (Retrieve done). */
export function currentStepIndex(node: ReviewNode): number {
  if (node === "candidates") return REVIEW_STEPS.findIndex((step) => step.node === "grade");
  return REVIEW_STEPS.findIndex((step) => step.node === node);
}

/** "{n} candidates · {n} relevant · {n} model steps", always in that shape. */
export function progressCountsLabel({ evidence, relevant, steps }: ReviewProgressState): string {
  return `${evidence} candidates · ${relevant} relevant · ${steps} model steps`;
}

/** A decorative two-character indicator; progress still comes only from server events. */
export function WaitingGlyph() {
  return <span className="waiting-glyph" aria-hidden="true">◐</span>;
}

export function ReviewProgressSteps({ state }: { state: ReviewProgressState }) {
  const current = currentStepIndex(state.node);
  const step = REVIEW_STEPS[current];
  return (
    <div className="review-progress" role="status" aria-live="polite"><WaitingGlyph />
      {state.revalidating && <p className="review-progress-prefix">Re-checking selected evidence</p>}
      {state.node === "chat" ? (
        <p className="review-progress-label">Replying…</p>
      ) : (
        <>
          {/* Live regions announce text changes, not class changes, so the current step is also spelled out. */}
          {step && <span className="sr-only">Step {current + 1} of {REVIEW_STEPS.length}: {step.label}</span>}
          <ol className="review-progress-steps" aria-hidden="true">
            {REVIEW_STEPS.map((item, index) => (
              <li key={item.node} className={index < current ? "done" : index === current ? "current" : undefined} aria-current={index === current ? "step" : undefined}>
                {item.label}
              </li>
            ))}
          </ol>
        </>
      )}
      <p className="review-progress-counts">{progressCountsLabel(state)}</p>
    </div>
  );
}
