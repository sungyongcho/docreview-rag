import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { REVIEW_STEPS, ReviewProgressSteps, candidateProgress, currentStepIndex, finishReviewProgress, initialReviewProgress, phaseStatus, progressCountsLabel, reviewProgressFromEvent } from "./review-progress";
import type { ReviewProgress } from "@/lib/api";

afterEach(cleanup);

function event(node: ReviewProgress["node"], steps = 1): ReviewProgress {
  return { node, evidence_count: 20, relevant_count: 6, step_count: steps };
}

describe("Five real-event review phases", () => {
  it("shows five waiting phases immediately without inventing completed work", () => {
    const state = initialReviewProgress();
    render(<ReviewProgressSteps state={state} />);
    expect(screen.getAllByRole("listitem")).toHaveLength(5);
    expect(screen.getByText("Waiting for the server")).toBeVisible();
    expect(REVIEW_STEPS.map((_, i) => phaseStatus(state, i))).toEqual(["waiting", "pending", "pending", "pending", "pending"]);
  });

  it("groups gate and route and completes only phases actually observed", () => {
    let state = initialReviewProgress();
    for (const node of ["gate", "route", "retrieve"] as const) state = reviewProgressFromEvent(event(node), state);
    state = reviewProgressFromEvent({ ...event("grade"), phase: "start", status: "running" }, state);
    render(<ReviewProgressSteps state={state} />);
    expect(REVIEW_STEPS.map((_, i) => phaseStatus(state, i))).toEqual(["done", "done", "current", "pending", "pending"]);
    expect(screen.getAllByRole("listitem")[2]).toHaveAttribute("aria-current", "step");
    expect(currentStepIndex("route")).toBe(0);
    expect(currentStepIndex("report")).toBe(4);
  });

  it("reopens earlier phases on real retries and leaves later phases pending", () => {
    let state = initialReviewProgress();
    for (const node of ["gate", "retrieve", "grade", "check"] as const) state = reviewProgressFromEvent(event(node), state);
    state = reviewProgressFromEvent({ ...event("retrieve"), phase: "start", status: "running" }, state);
    expect(state.retries).toBe(1);
    expect(REVIEW_STEPS.map((_, i) => phaseStatus(state, i))).toEqual(["done", "current", "pending", "pending", "pending"]);
  });

  it("retains failure or cancellation at the last reported phase", () => {
    const state = reviewProgressFromEvent(event("retrieve"), initialReviewProgress());
    for (const outcome of ["failed", "cancelled"] as const) {
      const result = finishReviewProgress(state, outcome, 1250);
      expect(result.elapsedMs).toBe(1250);
      expect(REVIEW_STEPS.map((_, i) => phaseStatus(result, i))).toEqual(["pending", outcome, "pending", "pending", "pending"]);
    }
  });

  it("does not restore stale downstream completion after a retry skips those phases", () => {
    let state = initialReviewProgress();
    for (const node of ["gate", "retrieve", "grade", "check", "retrieve", "report"] as const) state = reviewProgressFromEvent(event(node), state);
    state = finishReviewProgress(state, "completed", 800);
    expect(REVIEW_STEPS.map((_, i) => phaseStatus(state, i))).toEqual(["done", "done", "not-run", "not-run", "done"]);
  });

  it("resets downstream phases and relevance when fresh candidates arrive during a retry", () => {
    let state = initialReviewProgress();
    for (const node of ["gate", "retrieve", "grade", "check"] as const) state = reviewProgressFromEvent(event(node, 3), state);
    state = candidateProgress(state, 8);
    expect(state).toMatchObject({ evidence: 8, relevant: 0, steps: 3, retries: 1 });
    state = finishReviewProgress(state, "completed", 800);
    expect(REVIEW_STEPS.map((_, i) => phaseStatus(state, i))).toEqual(["done", "done", "not-run", "not-run", "done"]);
  });

  it("does not mark skipped phases complete for reused evidence", () => {
    let state = candidateProgress(initialReviewProgress(true, 4), 4);
    state = reviewProgressFromEvent(event("check"), state);
    state = finishReviewProgress(state, "completed", 500);
    render(<ReviewProgressSteps state={state} />);
    expect(screen.getByText("Re-checking selected evidence")).toBeVisible();
    expect(REVIEW_STEPS.map((_, i) => phaseStatus(state, i))).toEqual(["not-run", "done", "not-run", "done", "done"]);
    expect(screen.getAllByText("Not performed in this request")).toHaveLength(2);
  });

  it("does not fabricate RAG phases for a conversation reply", () => {
    const state = finishReviewProgress(reviewProgressFromEvent(event("chat"), initialReviewProgress()), "completed", 200);
    render(<ReviewProgressSteps state={state} />);
    expect(screen.queryByRole("list")).toBeNull();
    expect(screen.getByText("Execution complete")).toBeVisible();
  });

  it("waits after a legacy completion and spins only between actual start and end events", () => {
    let state = reviewProgressFromEvent(event("gate"), initialReviewProgress());
    expect(REVIEW_STEPS.map((_, i) => phaseStatus(state, i))).not.toContain("current");
    state = reviewProgressFromEvent({ ...event("retrieve"), phase: "start" }, state);
    expect(phaseStatus(state, 1)).toBe("current");
    state = reviewProgressFromEvent({ ...event("retrieve"), phase: "end", status: "completed", elapsed_ms: 125 }, state);
    expect(phaseStatus(state, 1)).toBe("done");
    expect(state.stageTimings).toEqual([{ node: "retrieve", elapsed_ms: 125, status: "completed" }]);
    expect(REVIEW_STEPS.map((_, i) => phaseStatus(state, i))).not.toContain("current");
  });

  it("keeps the three real count segments", () => {
    expect(progressCountsLabel({ node: "check", evidence: 20, relevant: 6, steps: 3 })).toBe("20 candidates · 6 relevant · 3 model steps");
  });

  it("waits for server routing and displays actual scope independently of the selected mode", () => {
    let state = initialReviewProgress(false, 0, "auto");
    const { rerender } = render(<ReviewProgressSteps state={state} />);
    expect(screen.getByText("Auto")).toBeVisible();
    expect(screen.getByText("Waiting for server-confirmed routing")).toBeVisible();
    state = reviewProgressFromEvent({ ...event("route"), phase: "end", resolved_scope: { source: "alias", filters: { registries: ["dart"], issuers: ["005930"], fiscal_years: [2024] } } }, state);
    rerender(<ReviewProgressSteps state={state} />);
    expect(screen.getByText(/Source: DART · Company: 005930 · Fiscal year: 2024/)).toBeVisible();
    expect(screen.getByText(/Company alias matched in the question/)).toBeVisible();
    expect(screen.getByText("Auto")).toBeVisible();
    expect(screen.queryByText("Waiting for server-confirmed routing")).toBeNull();
    state = reviewProgressFromEvent({ ...event("route"), phase: "start" }, state);
    expect(state.resolvedScope?.filters.issuers).toEqual(["005930"]);
  });

  it("persists candidate and terminal scopes without guessing from missing data", () => {
    const scope = { source: "explicit", filters: { registries: ["sec"], issuers: ["NVDA"], fiscal_years: [] } };
    let state = candidateProgress(initialReviewProgress(false, 0, "sec"), 3, scope);
    state = finishReviewProgress(state, "completed", 100);
    expect(JSON.parse(JSON.stringify(state)).resolvedScope).toEqual(scope);
    render(<ReviewProgressSteps state={state} />);
    expect(screen.getByText(/No year restriction/)).toBeVisible();
    cleanup();
    const terminal = finishReviewProgress(initialReviewProgress(false, 0, "auto"), "completed", 100, { effective_settings: { resolved_scope: scope } });
    expect(terminal.resolvedScope).toEqual(scope);
    const missing = finishReviewProgress(candidateProgress(initialReviewProgress(false, 0, "sec"), 2, {}), "completed", 100);
    render(<ReviewProgressSteps state={missing} />);
    expect(screen.getByText("Routing details not collected")).toBeVisible();
    expect(screen.queryByText("Server-confirmed scope")).toBeNull();
  });
});
