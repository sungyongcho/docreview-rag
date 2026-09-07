import { cleanup, fireEvent, render, screen } from "@testing-library/react";
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
    expect(field("History turns considered")).toHaveTextContent("Not recorded for this run");
  });
  it("keeps candidate ranks, measured scores, zero candidates and repeated retrieval passes", () => {
    render(<ReviewStageDetails stage="retrieve" state={state} performance={performance} />);
    expect(screen.getByText("[NVDA c11]")).toBeVisible();
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
    expect(field("Model")).toHaveTextContent("grade-model");
    expect(field("Attempts")).toHaveTextContent("2");
    expect(field("Input tokens")).toHaveTextContent("100");
    expect(field("Error")).toHaveTextContent("Provider retry detail");
  });
  it("shows the recorded answer decision, citation chunk IDs and workflow reasons", () => {
    render(<ReviewStageDetails stage="check" state={state} performance={performance} />);
    expect(field("Verification decision")).toHaveTextContent('"citation_chunk_ids": [ 11 ]');
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
