import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
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
    expect(screen.getByText("NVDA c11")).toBeVisible();
    expect(screen.getByText("0.75")).toBeVisible();
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
    expect(within(calls).getAllByRole("cell").map((cell) => cell.textContent)).toEqual(["grade-model", "2", "18.0", "100", "5", "Provider retry detail"]);
  });
  it("shows the recorded answer decision, citation chunk IDs and workflow reasons", () => {
    render(<ReviewStageDetails stage="check" state={state} performance={performance} />);
    expect(field("Verification decision")).toHaveTextContent("Citation chunk IDs11");
    expect(field("Verification decision").querySelector("pre")).toBeNull();
    expect(field("Verification decision")).toHaveTextContent("Chunk 11 supports the claim.");
    expect(field("Reasons")).toHaveTextContent("grade_references_filtered");
  });
  it("links the final label to evidence and the run details without a fetch", () => {
    const evidence = vi.fn(); const details = vi.fn();
    render(<ReviewStageDetails stage="report" state={state} performance={performance} onShowEvidence={evidence} onOpenDetails={details} />);
    expect(field("Final label")).toHaveTextContent("SUPPORTED");
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
  expect(within(table).getAllByRole("cell").map((cell) => cell.textContent)).toEqual(["gate", "completed", "1.9", "route", "failed", "0.0"]);
});

it("collapses long candidate tables behind Show more while retaining all ranks and identities", () => {
  const candidates = Array.from({ length: 30 }, (_, index) => ({ rank: index + 1, citation: `[C${index}]`, doc_id: `document-${index}`, chunk_id: index, score: index / 100 }));
  render(<ReviewStageDetails stage="retrieve" state={state} performance={{ stage_results: [{ node: "retrieve", candidates }] }} />);
  expect(field("Candidate count")).toHaveTextContent("30");
  expect(within(screen.getAllByRole("table", { name: "Ranked candidates" })[0]).getAllByRole("row")).toHaveLength(9);
  const more = screen.getByText("Show more recorded rows (22)");
  expect(more.closest("details")).not.toHaveAttribute("open");
  fireEvent.click(more);
  expect(screen.getByText("document-29")).toBeVisible();
  expect(screen.getAllByRole("table", { name: "Ranked candidates" })).toHaveLength(2);
});

it("opens the complete raw run record from any recorded stage without formatting its payload inline", () => {
  const details = vi.fn(); render(<ReviewStageDetails stage="gate" state={state} performance={performance} onOpenDetails={details} />);
  fireEvent.click(screen.getByRole("button", { name: "Open run details" }));
  expect(details).toHaveBeenCalledOnce();
  expect(document.querySelector(".review-stage-details pre")).toBeNull();
});
