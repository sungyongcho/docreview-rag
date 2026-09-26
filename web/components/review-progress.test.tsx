import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PathDecisionBadge, REVIEW_STEPS, ReviewProgressSteps, candidateProgress, currentStepIndex, finishReviewProgress, initialReviewProgress, phaseStatus, reviewProgressFromEvent } from "./review-progress";
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

  it("waits after a committed-node event and spins only between stage start and end events", () => {
    let state = reviewProgressFromEvent(event("gate"), initialReviewProgress());
    expect(REVIEW_STEPS.map((_, i) => phaseStatus(state, i))).not.toContain("current");
    state = reviewProgressFromEvent({ ...event("retrieve"), phase: "start" }, state);
    expect(phaseStatus(state, 1)).toBe("current");
    state = reviewProgressFromEvent({ ...event("retrieve"), phase: "end", status: "completed", elapsed_ms: 125 }, state);
    expect(phaseStatus(state, 1)).toBe("done");
    expect(state.stageTimings).toEqual([{ node: "retrieve", elapsed_ms: 125, status: "completed" }]);
    expect(REVIEW_STEPS.map((_, i) => phaseStatus(state, i))).not.toContain("current");
  });

  it("waits for server routing and displays actual scope independently of the selected mode", () => {
    let state = initialReviewProgress(false, 0, "auto");
    const { rerender } = render(<ReviewProgressSteps state={state} />);
    expect(screen.getByText("Auto")).toBeVisible();
    expect(screen.getByText("Waiting for server-confirmed routing")).toBeVisible();
    state = reviewProgressFromEvent({ ...event("route"), phase: "end", resolved_scope: { source: "alias", filters: { registries: ["dart"], issuers: ["005930"], fiscal_years: [2024] } } }, state);
    rerender(<ReviewProgressSteps state={state} />);
    expect(screen.getByText("Source").nextElementSibling).toHaveTextContent("DART");
    expect(screen.getByText("Company").nextElementSibling).toHaveTextContent("005930");
    expect(screen.getByText("Fiscal year").nextElementSibling).toHaveTextContent("2024");
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
    expect(screen.getByText("Skipped: relevance threshold not met")).toBeVisible();
    expect(screen.getByText("Candidates").nextElementSibling).toHaveTextContent("3");
    expect(screen.getByText("Relevant evidence").nextElementSibling).toHaveTextContent("0");
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


describe("recorded path decisions", () => {
  const reviewDecision = { intent: "document_review" as const, source: "classifier" as const, matched_rule: "classifier_document_review", rationale: "Filing question", history_turns: 2, selected_scope: "auto" as const, resolved_scope: null, routing_queries: {}, retrieval_query: "Revenue growth", scope_outcome: "resolved" as const, stopping_reason: null, suggested_scope: null };
  it.each([
    { stage: "gate" as const, reason: "unknown_issuer", count: 1, calls: undefined, expected: 1 },
    { stage: "path" as const, reason: "service_guidance", count: 0, calls: undefined, expected: 0 },
    { stage: "path" as const, reason: "unsupported_request", count: 1, calls: [{ node: "gate" }, { node: "route" }], expected: 2 },
    { stage: "path" as const, reason: "service_guidance", count: 1, calls: [], expected: 0 },
    { stage: "gate" as const, reason: "unknown_issuer", count: undefined, calls: undefined, expected: 3 },
  ])("uses recorded terminal call counts for $reason (expected $expected)", ({ stage, reason, count, calls, expected }) => {
    const decision = { ...reviewDecision, stopping_stage: stage, stopping_reason: reason, model_call_count: count };
    const state = finishReviewProgress({ ...initialReviewProgress(), pathDecision: decision, steps: 3 }, reason === "service_guidance" ? "completed" : "failed", 10, calls === undefined ? undefined : { model_calls: calls });
    expect(state.steps).toBe(expected);
    expect(state.outcome).toBe("limited");
    render(<ReviewProgressSteps state={state} />);
    expect(screen.getByText("Model steps").nextElementSibling).toHaveTextContent(String(expected));
  });
  it.each(["path", "gate"] as const)("renders an expected stop at %s without failed or verified stages", (stage) => {
    const decision = { ...reviewDecision, intent: "out_of_scope" as const, stopping_stage: stage, stopping_reason: stage === "path" ? "unsupported_request" : "unknown_issuer", missing_issuers: ["SanDisk"] };
    const state = finishReviewProgress({ ...initialReviewProgress(), pathDecision: decision }, "failed", 10);
    render(<ReviewProgressSteps state={state} />);
    expect(screen.getAllByText("Not performed in this request")).toHaveLength(stage === "path" ? 5 : 4);
    expect(screen.queryByText("Execution complete")).toBeNull();
    expect(screen.getByRole("button", { name: stage === "path" ? "Path decision" : "Understand the question" })).toBeEnabled();
  });
  it("enables path details only after the server starts path selection", () => {
    const initial = initialReviewProgress();
    const { rerender } = render(<ReviewProgressSteps state={initial} />);
    expect(screen.queryByRole("button", { name: "Path decision" })).toBeNull();
    const state = reviewProgressFromEvent({ ...event("gate", 0), display_stage: "path", phase: "start", status: "running" }, initial);
    rerender(<ReviewProgressSteps state={state} />);
    const path = screen.getByRole("button", { name: "Path decision" });
    fireEvent.click(path);
    expect(path).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("region", { name: "Path decision" })).toBeVisible();
    expect(state.pathStatus).toBe("current");
  });
  it("shows the first decision and counts recorded classifier and verification calls", () => {
    const state = finishReviewProgress(initialReviewProgress(), "completed", 200, { path_decision: reviewDecision, model_calls: [{ node: "gate" }, { node: "check" }], stages: ["gate", "check", "report"].map((node) => ({ node, phase: "end", status: "completed" })) });
    render(<ReviewProgressSteps state={state} />);
    expect(screen.getByText("0. Path decision")).toBeVisible();
    expect(screen.getByText("classifier_document_review")).toBeVisible();
    expect(screen.getByText("Candidates").nextElementSibling).toHaveTextContent("0");
    expect(screen.getByText("Relevant evidence").nextElementSibling).toHaveTextContent("0");
    expect(screen.getByText("Model steps").nextElementSibling).toHaveTextContent("2");
    expect(state.pathDecision?.history_turns).toBe(2);
  });
  it("preserves scope stops and their corrective action from stream events", () => {
    const decision = { ...reviewDecision, intent: "document_review" as const, selected_scope: "dart" as const, scope_outcome: "conflict" as const, stopping_reason: "NVDA is outside DART", suggested_scope: "auto" as const };
    const selected = reviewProgressFromEvent({ ...event("gate"), display_stage: "path", phase: "end", status: "completed", path_decision: { ...decision, stopping_reason: null, scope_outcome: "resolved" } }, initialReviewProgress());
    const state = finishReviewProgress(reviewProgressFromEvent({ ...event("route"), phase: "end", status: "failed", path_decision: decision }, selected), "failed", 200);
    const restore = vi.fn();
    render(<ReviewProgressSteps state={state} onSwitchScope={restore} />);
    expect(state.pathStatus).toBe("done");
    expect(phaseStatus(state, 0)).toBe("failed");
    fireEvent.click(screen.getByRole("button", { name: "Switch to Auto and restore question" }));
    expect(restore).toHaveBeenCalledOnce();
    expect(screen.getByText(/Scope conflict/)).toBeVisible();
    expect(screen.getByText(/NVDA is outside DART/)).toBeVisible();
    expect(screen.getByText("Switch the document scope to Auto above the composer and send the question again.")).toBeVisible();
    expect(phaseStatus(state, 1)).toBe("not-run");
  });
  it("shows recorded rationale, retrieval query, scope facts and history count", () => {
    const decision = { ...reviewDecision, intent: "document_review" as const, scope_outcome: "resolved" as const, rationale: "Company filing analysis", retrieval_query: "NVDA FY2024 revenue", resolved_scope: { source: "explicit" as const, filters: { registries: ["sec"], issuers: ["NVDA"], fiscal_years: [2024] } } };
    const state = finishReviewProgress({ ...initialReviewProgress(), pathDecision: decision }, "completed", 100);
    render(<ReviewProgressSteps state={state} />);
    expect(screen.getByText("Company filing analysis")).toBeVisible();
    expect(screen.getByText("NVDA FY2024 revenue")).toBeVisible();
    expect(screen.getByText("History turns considered").nextElementSibling).toHaveTextContent("2");
    expect(screen.getByText("Scope resolved")).toBeVisible();
    expect(screen.getByText("Server-confirmed scope")).toBeVisible();
    expect(screen.getByText("Routing reason")).toBeVisible();
  });
  it("does not repeat the unsupported label in the badge the verdict pill already carries", () => {
    const decision = { ...reviewDecision, intent: "out_of_scope" as const, scope_outcome: "unsupported" as const, stopping_stage: "path" as const, stopping_reason: "unsupported_request" };
    const view = render(<PathDecisionBadge decision={decision} />);
    expect(screen.queryByText("Unsupported request")).not.toBeInTheDocument();
    view.rerender(<PathDecisionBadge decision={{ ...reviewDecision, intent: "service_help", scope_outcome: "not_applicable", stopping_reason: "service_guidance" }} />);
    expect(screen.getByText("No retrieval")).toBeVisible();
  });
  it("renders empty scope as a distinct verdict pill", () => {
    render(<PathDecisionBadge decision={{ ...reviewDecision, scope_outcome: "empty" }} />);
    expect(screen.getByText("Empty scope")).toBeVisible();
    expect(screen.queryByText("Not in documents")).not.toBeInTheDocument();
  });
});


describe("stage disclosures", () => {
  it("keeps recorded panels collapsed and marks only the currently expanded native button", () => {
    render(<ReviewProgressSteps state={{ node: "report", evidence: 0, relevant: 0, steps: 0, outcome: "completed", completedNodes: ["gate", "retrieve", "grade", "check", "report"], observed: ["gate", "retrieve", "grade", "check", "report"], pathDecision: { intent: "document_review", source: "deterministic", matched_rule: "filing", rationale: "Filing question", selected_scope: "auto", history_turns: 0, routing_queries: {}, retrieval_query: "Question", scope_outcome: "resolved", stopping_reason: null, resolved_scope: null, suggested_scope: null } }} />);
    const labels = ["Path decision", ...REVIEW_STEPS.map((step) => step.label)];
    expect(screen.queryByRole("region")).toBeNull();
    for (const label of labels) {
      const button = screen.getByRole("button", { name: label });
      expect(button).toHaveAttribute("type", "button");
      expect(button).toHaveAttribute("aria-expanded", "false");
      button.focus();
      expect(button).toHaveFocus();
      fireEvent.click(button);
      expect(button).toHaveAttribute("aria-expanded", "true");
      expect(button).toHaveAttribute("aria-current", "true");
      const panel = screen.getByRole("region", { name: label });
      expect(button).toHaveAttribute("aria-controls", panel.id);
      expect(panel).toBeVisible();
      fireEvent.click(button);
      expect(screen.queryByRole("region")).toBeNull();
      expect(button).not.toHaveAttribute("aria-current");
    }
  });
  it("switches disclosures without changing the recorded skipped status", () => {
    const state = finishReviewProgress(initialReviewProgress(), "completed", 100, { stages: ["gate", "retrieve", "grade", "report"].map((node) => ({ node, status: "completed" })), stage_results: [{ node: "grade", reasons: [{ code: "relevance_below_threshold", candidate_count: 2, relevant_count: 0 }] }] }, { label: "NOT_IN_DOCS" });
    render(<ReviewProgressSteps state={state} />);
    fireEvent.click(screen.getByRole("button", { name: "Verify answer and citations" }));
    expect(screen.getAllByText("Skipped: relevance threshold not met")).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "Retrieve evidence" }));
    expect(screen.getByRole("button", { name: "Verify answer and citations" })).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByRole("region", { name: "Retrieve evidence" })).toBeVisible();
  });
});

it("keeps waiting/pending and unreached failed-run stages inert while preserving the failing stage", () => {
  const { rerender } = render(<ReviewProgressSteps state={initialReviewProgress()} />);
  expect(screen.queryByRole("button")).toBeNull();
  for (const row of screen.getAllByRole("listitem")) fireEvent.click(row);
  expect(screen.queryByRole("region")).toBeNull();
  const state = finishReviewProgress(reviewProgressFromEvent({ ...event("gate"), phase: "start" }, initialReviewProgress()), "failed", 30);
  rerender(<ReviewProgressSteps state={state} />);
  expect(screen.getAllByRole("button")).toHaveLength(1);
  const failing = screen.getByRole("button", { name: "Understand the question" });
  expect(phaseStatus(state, 0)).toBe("failed");
  fireEvent.click(failing);
  expect(screen.getByRole("region", { name: "Understand the question" })).toHaveTextContent("This stage was not recorded for this run.");
  for (const step of REVIEW_STEPS.slice(1)) expect(screen.queryByRole("button", { name: step.label })).toBeNull();
});

it("closes an open panel if a new pass makes that stage unreached", () => {
  const completed = { node: "report" as const, evidence: 1, relevant: 1, steps: 1, outcome: "completed" as const, completedNodes: ["gate", "retrieve", "grade", "check", "report"] as const, observed: ["gate", "retrieve", "grade", "check", "report"] as const };
  const { rerender } = render(<ReviewProgressSteps state={{ ...completed, observed: [...completed.observed], completedNodes: [...completed.completedNodes] }} />);
  fireEvent.click(screen.getByRole("button", { name: "Verify answer and citations" }));
  rerender(<ReviewProgressSteps state={initialReviewProgress()} />);
  expect(screen.queryByRole("region")).toBeNull();
  rerender(<ReviewProgressSteps state={{ ...completed, observed: [...completed.observed], completedNodes: [...completed.completedNodes] }} />);
  expect(screen.queryByRole("region")).toBeNull();
});
