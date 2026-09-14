import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ReviewProgressSteps } from "./review-progress";
import { ReviewStageDetails, type DisclosureStage } from "./review-stage-details";
import type { ReviewExecution } from "@/lib/types";

afterEach(cleanup);
const state: ReviewExecution = { node: "report", evidence: 2, relevant: 1, steps: 2, outcome: "completed", selectedScope: "auto", resolvedScope: { source: "alias", filters: { registries: ["sec"], issuers: ["NVDA"], fiscal_years: [2024] } } };
const performance = {
  effective_settings: { retrieval: { preset: "balanced", k: 5 } }, routing_queries: { sec: "NVIDIA data center" },
  stages: [{ node: "retrieve", status: "completed", elapsed_ms: 12 }, { node: "retrieve", status: "completed", elapsed_ms: 8 }],
  stage_results: [
    { node: "retrieve", candidates: [{ chunk_id: 11, doc_id: "NVDA-2024", rank: 1, citation: "[NVDA c11]", score: 0.75 }] },
    { node: "retrieve", candidates: [] },
    { node: "grade", kept_chunk_ids: [11], rejected_chunk_ids: [12], failure: null },
    { node: "check", decision: { label: "SUPPORTED", answer: "The filing supports the answer.", citation_chunk_ids: [11], reason: "Chunk 11 supports the claim." }, reasons: [{ code: "grade_references_filtered", removed_chunk_ids: [99] }] },
    { node: "report", decision: { label: "SUPPORTED", answer: "The filing supports the answer.", citation_chunk_ids: [11], reason: "Chunk 11 supports the claim." }, reasons: [] },
  ],
  model_calls: [{ node: "grade", model: "grade-model", attempts: 2, elapsed_ms: 18, input_tokens: 100, output_tokens: 5, error: "Provider retry detail" }],
};

/** Locate a field value by its visible definition label. */
function field(label: string) { return screen.getByText(label, { selector: "dt" }).parentElement!.querySelector("dd")!; }

describe("recorded stage detail data", () => {
  it.each(["document_review", "service_help", "out_of_scope"])("shows the recorded %s branch in stage 0 without repeating stage 1 scope fields", (intent) => {
    const path = { intent, source: "classifier", matched_rule: "structured_classifier", history_turns: 0, rationale: "Recorded classification reason", stopping_stage: intent === "document_review" ? "gate" : "path", stopping_reason: intent === "document_review" ? "unknown_issuer" : "unsupported_request", resolved_scope: state.resolvedScope };
    const { container, rerender } = render(<ReviewStageDetails stage="path" state={state} performance={{ path_decision: path }} />);
    expect(container.querySelectorAll(".review-path-option")).toHaveLength(3);
    expect(container.querySelectorAll('.review-path-option[aria-current="step"]')).toHaveLength(1);
    const selected = container.querySelector('.review-path-option[aria-current="step"]')!;
    expect(selected).toHaveTextContent(intent === "document_review" ? "Continue to stage 1" : intent === "service_help" ? "Fixed guidance, then stop" : "Scope notice, then stop");
    expect(screen.getByText("Recorded classification reason")).toBeInTheDocument();
    expect(screen.queryByText("Company", { selector: "dt" })).toBeNull();
    expect(screen.queryByText("Fiscal year", { selector: "dt" })).toBeNull();
    expect(screen.queryByText("Retrieval query", { selector: "dt" })).toBeNull();
    if (intent === "document_review") expect(screen.queryByText("Stopping reason", { selector: "dt" })).toBeNull();
    rerender(<ReviewStageDetails stage="gate" state={state} performance={{ path_decision: path }} />);
    expect(container.querySelector(".review-path-options")).toBeNull();
    expect(field("Company")).toHaveTextContent("NVDA");
    expect(field("Fiscal year")).toHaveTextContent("FY2024");
  });

  it("does not infer stage 0 from resolved scope and does not reclassify historical conversation routes", () => {
    const { container, rerender } = render(<ReviewStageDetails stage="path" state={state} performance={{ model_calls: [] }} />);
    expect(container.querySelector('[aria-current="step"]')).toBeNull();
    expect(screen.getByText("No service path was recorded. A later scope or result does not establish this decision.")).toBeInTheDocument();
    rerender(<ReviewStageDetails stage="path" state={state} performance={{ path_decision: { intent: "casual_chat", rationale: "Original conversation decision" } }} />);
    expect(container.querySelector('[aria-current="step"]')).toBeNull();
    expect(screen.getByText("This historical run used a conversation route. Its recorded classification is preserved.")).toBeInTheDocument();
    expect(screen.getByText("Original conversation decision")).toBeInTheDocument();
  });
  it("shows actual scope and routing without deriving them from the question", () => {
    render(<ReviewStageDetails stage="gate" state={state} performance={performance} />);
    expect(field("Company")).toHaveTextContent("NVDA");
    expect(field("Fiscal year")).toHaveTextContent("2024");
    expect(field("Routing queries")).toHaveTextContent("NVIDIA data center");
    expect(document.querySelector(".review-unrecorded")).toHaveTextContent("History turns considered");
    expect(screen.queryByText("History turns considered", { selector: "dt" })).toBeNull();
  });
  it("keeps candidate ranks, measured scores, zero candidates and repeated retrieval passes", () => {
    render(<ReviewStageDetails stage="retrieve" state={state} performance={performance} />);
    expect(screen.getByText("Ranked candidates (1)").closest("details")).not.toHaveAttribute("open");
    fireEvent.click(screen.getByText("Ranked candidates (1)"));
    expect(screen.getByText("NVDA c11")).toBeVisible();
    expect(screen.getByText("0.7500")).toBeVisible();
    expect(screen.getByText("Recorded pass 2")).toBeVisible();
    expect(field("Search preset")).toHaveTextContent("balanced");
    expect(field("Retrieval k")).toHaveTextContent("5");
    expect(screen.getAllByText("Candidate count").map((item) => item.parentElement!.querySelector("dd")!.textContent)).toEqual(["1", "0"]);
  });
  it("shows kept/rejected identities and the actual grade call including retry and failure evidence", () => {
    render(<ReviewStageDetails stage="grade" state={state} performance={performance} />);
    expect(field("Kept candidate IDs")).toHaveTextContent("1 · 11");
    expect(field("Rejected candidate IDs")).toHaveTextContent("1 · 12");
    const calls = screen.getByRole("table", { name: "Model calls / attempts" });
    expect(within(calls).getAllByRole("cell").map((cell) => cell.textContent)).toEqual(["1", "Select relevant evidencegrade", "grade-model", "2", "18ms", "100", "5", "Provider retry detail"]);
  });
  it("shows the recorded answer decision, citation chunk IDs and workflow reasons", () => {
    render(<ReviewStageDetails stage="check" state={state} performance={performance} />);
    expect(field("Verification decision")).toHaveTextContent(/^SUPPORTED$/);
    expect(screen.queryByText("Final label")).toBeNull();
    expect(field("Citation chunk IDs")).toHaveTextContent("11");
    expect(field("Reason")).toHaveTextContent("Chunk 11 supports the claim.");
    expect(field("Answer")).toHaveTextContent("The filing supports the answer.");
    expect(field("Answer").parentElement).toHaveClass("review-field-wide");
    expect(field("Reasons")).toHaveTextContent("grade_references_filtered");
  });
  it("preserves empty reasons, unknown decision fields and the lower tables", () => {
    render(<ReviewStageDetails stage="check" state={state} performance={{
      stage_results: [{ node: "check", decision: { label: "SUPPORTED", answer: "Recorded answer", reason: "Recorded justification", citation_chunk_ids: [4336, 5301], audit_detail: "Retained extension" }, reasons: [] }],
      stages: [{ node: "check", status: "completed", elapsed_ms: 3410 }],
      model_calls: [{ node: "check", model: "recorded-model", attempts: 1 }],
    }} />);
    expect(field("Reasons").querySelector(".review-value-empty")).toHaveTextContent("None");
    expect(field("audit detail")).toHaveTextContent("Retained extension");
    expect(field("Citation chunk IDs")).toHaveTextContent("43365301");
    expect(screen.getByRole("table", { name: "Stage timings" })).toHaveTextContent("3.41s");
    expect(screen.getByRole("table", { name: "Model calls / attempts" })).toHaveTextContent("recorded-model");
  });
  it("links the final label to evidence and the run details without a fetch", () => {
    const evidence = vi.fn(); const details = vi.fn();
    render(<ReviewProgressSteps state={state} performance={performance} onShowEvidence={evidence} onOpenDetails={details} />);
    expect(screen.queryByRole("region")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Show evidence" }));
    fireEvent.click(screen.getByRole("button", { name: "Open run details" }));
    expect(evidence).toHaveBeenCalledOnce(); expect(details).toHaveBeenCalledOnce();
  });
  it("uses the explicit chat or failure label when no decision was produced", () => {
    const { rerender } = render(<ReviewStageDetails stage="report" state={state} finalLabel="Conversation reply" />);
    expect(field("Final label")).toHaveTextContent("Conversation reply");
    rerender(<ReviewStageDetails stage="report" state={state} finalLabel="Answer not generated" />);
    expect(field("Final label")).toHaveTextContent("Answer not generated");
  });
  it.each<DisclosureStage>(["path", "gate", "retrieve", "grade", "check", "report"])("uses one empty-state note when no fields were recorded in %s", (stage) => {
    render(<ReviewStageDetails stage={stage} state={{ node: "report", evidence: 0, relevant: 0, steps: 0 }} />);
    expect(screen.getByText("This stage was not recorded for this run.")).toBeVisible();
    expect(document.querySelectorAll("dd")).toHaveLength(0);
  });
});

it("uses registry-specific catalog names with code-only fallback and year/registry chips", () => {
  const scope = { source: "alias", filters: { registries: ["sec", "dart"], issuers: ["NVDA", "005930", "UNKNOWN"], fiscal_years: [2024] } };
  render(<ReviewStageDetails stage="gate" state={{ ...state, resolvedScope: scope }} companyLabels={{ "sec:NVDA": "NVDA · NVIDIA", "dart:005930": "삼성전자" }} />);
  expect(field("Company")).toHaveTextContent("NVDA · NVIDIA");
  expect(field("Company")).toHaveTextContent("005930 · 삼성전자");
  expect(field("Company")).toHaveTextContent("UNKNOWN");
  expect(field("Source").querySelectorAll(".registry")).toHaveLength(2);
  expect(field("Fiscal year")).toHaveTextContent("FY2024");
  for (const chip of document.querySelectorAll(".review-value-chip")) { expect(chip.tagName).toBe("SPAN"); expect(chip).not.toHaveAttribute("tabindex"); }
});

it("distinguishes recorded empty arrays/objects and zero from consolidated missing fields", () => {
  render(<ReviewStageDetails stage="gate" state={{ ...state, resolvedScope: { filters: { registries: [], issuers: [], fiscal_years: [] } } }} performance={{ path_decision: { history_turns: 0, routing_queries: {} }, model_calls: [] }} />);
  for (const label of ["Source", "Company", "Fiscal year", "Routing queries"]) expect(field(label)).toHaveTextContent("None");
  expect(field("History turns considered")).toHaveTextContent("0");
  expect(document.querySelectorAll(".review-unrecorded")).toHaveLength(1);
  expect(document.querySelector(".review-unrecorded")).toHaveTextContent("Retrieval query");
  expect(document.querySelector(".review-unrecorded")).not.toHaveTextContent("History turns considered");
  expect(document.querySelector(".review-stage-details")!.textContent).not.toMatch(/[\[\]{}]/);
});

it("renders stage timings as rounded table cells without dropping repeated passes", () => {
  render(<ReviewStageDetails stage="gate" state={state} performance={{ stages: [{ node: "gate", status: "completed", elapsed_ms: 1.8702349625527859 }, { node: "route", status: "failed", elapsed_ms: 0 }] }} />);
  const table = screen.getByRole("table", { name: "Stage timings" });
  expect(within(table).getByText("1.87ms")).toHaveAttribute("title", "1.8702349625527859ms");
  expect(within(table).getByText("0ms")).toBeVisible();
  expect(within(table).getByText("failed", { selector: "span" }).closest(".review-recorded-status")).toHaveClass("is-failed");

});

it("collapses ranked candidates and pages five readable rows while retaining every identity", () => {
  const candidates = Array.from({ length: 12 }, (_, index) => ({ rank: index + 1, citation: `[NVDA FY2024 · Item ${index}]`, doc_id: `document-${index}`, chunk_id: index, score: 0.03200204813108039 }));
  render(<ReviewStageDetails stage="retrieve" state={state} performance={{ stage_results: [{ node: "retrieve", candidates }] }} />);
  expect(field("Candidate count")).toHaveTextContent("12");
  const summary = screen.getByText("Ranked candidates (12)");
  expect(summary.closest("details")).not.toHaveAttribute("open");
  expect(screen.getByRole("table", { name: "Ranked candidates" })).not.toBeVisible();
  fireEvent.click(summary);
  const table = screen.getByRole("table", { name: "Ranked candidates" });
  expect(within(table).getAllByRole("row")).toHaveLength(6);
  expect(screen.getAllByText("0.03200")).toHaveLength(5);
  expect(screen.getAllByText("0.03200")[0]).toHaveAttribute("title", "0.03200204813108039");
  expect(screen.getByText("NVDA FY2024 · Item 0")).toHaveClass("citation");
  expect(screen.getByText("document-0").tagName).toBe("CODE");
  fireEvent.click(screen.getByRole("button", { name: "Next page" }));
  expect(screen.getByText("document-5")).toBeVisible();
  expect(screen.queryByText("document-0")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Next page" }));
  expect(screen.getByText("document-11")).toBeVisible();
  expect(screen.getByText("3/3")).toBeVisible();
  expect(screen.getByRole("button", { name: "Next page" })).toBeDisabled();
});

it("groups repeated routing and retrieval passes with ordered details and measured totals", () => {
  const stages = [{ node: "gate", status: "completed", elapsed_ms: 0.1 }, { node: "route", status: "completed", elapsed_ms: 1000 }, { node: "retrieve", status: "completed", elapsed_ms: 234.66 }, { node: "route", status: "failed", elapsed_ms: 580 }, { node: "retrieve", status: "completed", elapsed_ms: 2 }];
  const { rerender } = render(<ReviewStageDetails stage="gate" state={state} performance={{ stages }} />);
  expect(screen.getByText(/1. Understand the question/)).toHaveTextContent("gate, route");
  const table = screen.getByRole("table", { name: "Stage timings" });
  expect(table.querySelectorAll(":scope > tbody > tr")).toHaveLength(2);
  expect(within(table).getByText("1.58s")).toBeVisible();
  fireEvent.click(screen.getByText("Recorded passes ×2"));
  const passes = screen.getByRole("table", { name: "Recorded passes" });
  expect(within(passes).getAllByRole("row").slice(1).map((row) => within(row).getAllByRole("cell")[0].textContent)).toEqual(["2", "4"]);
  expect(within(passes).getByText("1s")).toBeVisible();
  expect(within(passes).getByText("580ms")).toBeVisible();
  rerender(<ReviewStageDetails stage="retrieve" state={state} performance={{ stages }} />);
  expect(screen.getByText("236.66ms")).toBeVisible();
  expect(screen.getByText("Recorded passes ×2")).toBeVisible();
});

it("keeps unknown elapsed measurements unknown instead of showing a partial total", () => {
  render(<ReviewStageDetails stage="gate" state={state} performance={{ stages: [{ node: "route", status: "completed", elapsed_ms: 12 }, { node: "route", status: "completed" }] }} />);
  const row = screen.getByRole("table", { name: "Stage timings" }).querySelector("tbody > tr")!;
  expect(within(row as HTMLElement).getAllByRole("cell")[3]).toHaveTextContent("—");
});

it("opens run details from the heading with the selected stage, even after panels are closed", () => {
  const details = vi.fn();
  render(<ReviewProgressSteps state={{ ...state, observed: ["gate", "retrieve", "report"] }} performance={performance} onOpenDetails={details} />);
  const action = screen.getByRole("button", { name: "Open run details" });
  expect(action.closest(".review-progress-heading")).not.toBeNull();
  fireEvent.click(action);
  expect(details).toHaveBeenLastCalledWith(undefined);
  fireEvent.click(screen.getByRole("button", { name: "Retrieve evidence" }));
  fireEvent.click(action);
  expect(details).toHaveBeenLastCalledWith("retrieve");
  fireEvent.click(screen.getByRole("button", { name: "Retrieve evidence" }));
  expect(action).toBeVisible();
});


it.each(["failed", "cancelled"] as const)("keeps heading actions visible for a %s run without an open stage", (outcome) => {
  const details = vi.fn();
  render(<ReviewProgressSteps state={{ ...state, outcome }} onOpenDetails={details} />);
  const action = screen.getByRole("button", { name: "Open run details" });
  expect(action).toBeVisible();
  expect(action.closest(".review-progress-heading")).not.toBeNull();
  fireEvent.click(action);
  expect(details).toHaveBeenCalledExactlyOnceWith(undefined);
});
