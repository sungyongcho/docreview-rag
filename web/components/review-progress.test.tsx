import { readFileSync } from "node:fs";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
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
    expect(screen.getAllByRole("listitem")).toHaveLength(6);
    expect(screen.getByText("Waiting for the server")).toBeVisible();
    expect(REVIEW_STEPS.map((_, i) => phaseStatus(state, i))).toEqual(["waiting", "pending", "pending", "pending", "pending"]);
  });

  it("groups gate and route and completes only phases actually observed", () => {
    let state = initialReviewProgress();
    for (const node of ["gate", "route", "retrieve"] as const) state = reviewProgressFromEvent(event(node), state);
    state = reviewProgressFromEvent({ ...event("grade"), phase: "start", status: "running" }, state);
    render(<ReviewProgressSteps state={state} />);
    expect(REVIEW_STEPS.map((_, i) => phaseStatus(state, i))).toEqual(["done", "done", "current", "pending", "pending"]);
    expect(screen.getAllByRole("listitem")[3]).toHaveAttribute("aria-current", "step");
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
      expect(REVIEW_STEPS.map((_, i) => phaseStatus(result, i))).toEqual(["not-run", outcome, "not-run", "not-run", "not-run"]);
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
    expect(screen.getAllByRole("listitem")).toHaveLength(6);
    expect(screen.getAllByText("Skipped: conversation reply without retrieval")).toHaveLength(3);
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


describe("intentional verification skips", () => {
  const threshold = { code: "relevance_below_threshold", candidate_count: 3, relevant_count: 0, minimum_required: 1 };
  const performance = { stages: ["gate", "retrieve", "grade", "report"].map((node) => ({ node, phase: "end", status: "completed" })), stage_results: [{ node: "grade", reasons: [threshold] }] };

  it("marks only an evidenced NOT_IN_DOCS threshold bypass as a warning", () => {
    const state = finishReviewProgress(initialReviewProgress(), "completed", 6900, performance, { label: "NOT_IN_DOCS", reasons: [threshold] });
    render(<ReviewProgressSteps state={state} />);
    expect(REVIEW_STEPS.map((_, index) => phaseStatus(state, index))).toEqual(["done", "done", "done", "skipped", "done"]);
    expect(screen.getByText("Skipped: relevance threshold not met")).toHaveClass("review-phase-reason");
    expect(screen.getByText(/3 candidates · 0 relevant/)).toBeInTheDocument();
  });

  it("does not infer a skip from an unsupported verdict, zero counts or missing old metadata", () => {
    for (const report of [{ label: "NOT_IN_DOCS" }, { label: "NOT_IN_DOCS", reasons: [{ code: "support_downgraded" }] }, { label: "SUPPORTED", reasons: [threshold] }]) {
      const state = finishReviewProgress(initialReviewProgress(), "completed", 100, undefined, report);
      expect(phaseStatus(state, 3)).toBe("not-run");
    }
  });

  it("keeps executed verification green and never applies skips to failure or cancellation", () => {
    const completed = { ...performance, stages: ["gate", "retrieve", "grade", "check", "report"].map((node) => ({ node, phase: "end", status: "completed" })) };
    const success = finishReviewProgress(initialReviewProgress(), "completed", 100, completed, { label: "SUPPORTED" });
    expect(REVIEW_STEPS.map((_, index) => phaseStatus(success, index))).toEqual(["done", "done", "done", "done", "done"]);
    const downgraded = finishReviewProgress(initialReviewProgress(), "completed", 100, completed, { label: "NOT_IN_DOCS", reasons: [threshold] });
    expect(phaseStatus(downgraded, 3)).toBe("done");
    for (const outcome of ["failed", "cancelled"] as const) {
      const stopped = finishReviewProgress(reviewProgressFromEvent({ ...event("grade"), phase: "start" }, initialReviewProgress()), outcome, 100, undefined, { label: "NOT_IN_DOCS", reasons: [threshold] });
      expect(REVIEW_STEPS.map((_, index) => phaseStatus(stopped, index))).toEqual(["not-run", "not-run", outcome, "not-run", "not-run"]);
    }
  });

  it("uses the last actual pass instead of reviving completion from before a retrieval retry", () => {
    const state = finishReviewProgress(initialReviewProgress(), "completed", 100, { stages: ["gate", "retrieve", "grade", "check", "retrieve", "grade", "report"].map((node) => ({ node, phase: "end", status: "completed" })), stage_results: [{ node: "report", decision: { label: "NOT_IN_DOCS" }, reasons: [threshold] }] });
    expect(REVIEW_STEPS.map((_, index) => phaseStatus(state, index))).toEqual(["done", "done", "done", "skipped", "done"]);
    expect(state.retries).toBe(1);
  });
});


it("keeps warning text readable in both actual themes and visible in the compact stylesheet", () => {
  const styles = readFileSync("app/styles.css", "utf8");
  const compact = readFileSync("app/v2.css", "utf8");
  const warning = styles.match(/--phase-warning:\s*light-dark\((#[0-9a-f]+),\s*(#[0-9a-f]+)\)/i)!;
  const backgrounds = [...compact.matchAll(/--(?:bg|surface|surface-2):\s*light-dark\((#[0-9a-f]+),\s*(#[0-9a-f]+)\)/gi)];
  function luminance(hex: string) {
    const channels = [1, 3, 5].map((offset) => parseInt(hex.slice(offset, offset + 2), 16) / 255).map((value) => value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4);
    return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722;
  }
  expect(backgrounds.length).toBeGreaterThan(0);
  for (const background of backgrounds) for (const theme of [1, 2]) {
    const foreground = luminance(warning[theme]);
    const backdrop = luminance(background[theme]);
    expect((Math.max(foreground, backdrop) + 0.05) / (Math.min(foreground, backdrop) + 0.05)).toBeGreaterThanOrEqual(4.5);
  }
  expect(compact).toContain(".review-progress-steps small.review-phase-reason { display: block;");
});


describe("recorded path decisions", () => {
  const chatDecision = { intent: "casual_chat" as const, source: "classifier" as const, matched_rule: "classifier_chat", rationale: "Greeting", history_turns: 2, selected_scope: "auto" as const, resolved_scope: null, routing_queries: {}, retrieval_query: "Hi", scope_outcome: "not_applicable" as const, stopping_reason: null, suggested_scope: null };
  it("shows the first decision and counts recorded classifier and chat calls", () => {
    const state = finishReviewProgress(initialReviewProgress(), "completed", 200, { path_decision: chatDecision, model_calls: [{ node: "gate" }, { node: "chat" }], stages: ["gate", "chat", "report"].map((node) => ({ node, phase: "end", status: "completed" })) });
    render(<ReviewProgressSteps state={state} />);
    expect(screen.getByText("0. Path decision")).toBeVisible();
    expect(screen.getByText("classifier_chat")).toBeVisible();
    expect(screen.getByText(/0 candidates · 0 relevant · 2 model steps/)).toBeVisible();
    expect(screen.getAllByText("Skipped: conversation reply without retrieval")).toHaveLength(3);
    expect(state.pathDecision?.history_turns).toBe(2);
  });
  it("preserves scope stops and their corrective action from stream events", () => {
    const decision = { ...chatDecision, intent: "document_review" as const, selected_scope: "dart" as const, scope_outcome: "conflict" as const, stopping_reason: "NVDA is outside DART", suggested_scope: "auto" as const };
    const state = finishReviewProgress(reviewProgressFromEvent({ ...event("gate"), status: "failed", path_decision: decision }, initialReviewProgress()), "failed", 200);
    const restore = vi.fn();
    render(<ReviewProgressSteps state={state} onSwitchScope={restore} />);
    fireEvent.click(screen.getByRole("button", { name: "Switch to Auto and restore question" }));
    expect(restore).toHaveBeenCalledOnce();
    expect(screen.getByText(/Scope conflict/)).toBeVisible();
    expect(screen.getByText(/NVDA is outside DART/)).toBeVisible();
    expect(screen.getByText("Switch the document scope to Auto above the composer and send the question again.")).toBeVisible();
    expect(phaseStatus(state, 1)).toBe("not-run");
  });
});
