import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AcquisitionForm } from "./build-pipeline";
import { PipelineReference, pipelineReferenceCommand } from "./pipeline-reference";

const ACQUISITION: AcquisitionForm = { registry: "sec", identifiers: "NVDA AMD", years: "2023 2024" };

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("Pipeline terminal reference", () => {
  it("expands SEC years into distinct commands and preserves all selected tickers", () => {
    expect(pipelineReferenceCommand("filings", { ...ACQUISITION, years: "2023,2024 2023" }, "", null, "")).toBe(
      "MODE=dev uv run python -m app.ingestion.edgar_api --ticker 'NVDA' 'AMD' --years '2023'\n" +
      "MODE=dev uv run python -m app.ingestion.edgar_api --ticker 'NVDA' 'AMD' --years '2024'",
    );
    expect(pipelineReferenceCommand("filings", { registry: "dart", identifiers: "005930,000660", years: "2023 2024" }, "", null, "")).toBe(
      "MODE=dev uv run python -m app.ingestion.dart_api --stock-codes '005930' '000660' --fiscal-year 2023 2024",
    );
  });

  it("requires complete inputs and a supported configured embedding provider", () => {
    for (const years of ["", "2024;exit", "24"]) {
      expect(pipelineReferenceCommand("filings", { ...ACQUISITION, years }, "", null, "")).toBeNull();
    }
    expect(pipelineReferenceCommand("filings", { ...ACQUISITION, identifiers: "" }, "", null, "")).toBeNull();
    expect(pipelineReferenceCommand("index", ACQUISITION, "", null, "")).toBeNull();
    for (const provider of [null, undefined, "unsupported"]) {
      expect(pipelineReferenceCommand("ask", ACQUISITION, "", provider, "revenue")).toBeNull();
    }
    expect(pipelineReferenceCommand("ask", ACQUISITION, "", "openai", "  ")).toBeNull();
    for (const stage of ["lexical", "answer_model", "evaluate"] as const) {
      expect(pipelineReferenceCommand(stage, ACQUISITION, "manifest.json", "openai", "revenue")).toBeNull();
    }
  });

  it("quotes shell metacharacters and distinguishes backfill from retrieval", () => {
    const query = "What's $(touch /tmp/never-run); revenue?";
    const quoted = "'What'\\''s $(touch /tmp/never-run); revenue?'";
    expect(pipelineReferenceCommand("ask", ACQUISITION, "", "deterministic", query)).toBe(
      `MODE=dev uv run python -m app.cli retrieve --provider 'deterministic' --query ${quoted}`,
    );
    expect(pipelineReferenceCommand("embeddings", ACQUISITION, "", "sbert", query)).toBe(
      `MODE=dev uv run python -m app.cli retrieve --provider 'sbert' --embed-missing --query ${quoted}`,
    );
    expect(pipelineReferenceCommand("index", ACQUISITION, "owner's manifest.json", null, "")).toBe(
      "MODE=dev uv run python -m app.cli ingest --manifest 'data/corpus/owner'\\''s manifest.json'",
    );
  });

  it("only offers valid discovered manifests and clears a reference when its source disappears", () => {
    const props = { stage: "index" as const, acquisition: ACQUISITION, manifests: [
      { name: "valid.json", registry: "sec", documents: 1, valid: true, sources_present: 1 },
      { name: "invalid.json", registry: "sec", documents: 1, valid: false, sources_present: 0 },
    ] };
    const { rerender } = render(<PipelineReference {...props} />);
    fireEvent.click(screen.getByText("Implementation and terminal reference"));
    expect(screen.queryByRole("option", { name: "invalid.json" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Copy code" })).toBeNull();
    fireEvent.change(screen.getByLabelText("CLI manifest reference"), { target: { value: "valid.json" } });
    expect(screen.getByRole("button", { name: "Copy code" })).toBeVisible();
    rerender(<PipelineReference {...props} manifests={[]} />);
    expect(screen.queryByRole("button", { name: "Copy code" })).toBeNull();
    expect(screen.getByLabelText("CLI manifest reference")).toHaveValue("");
  });

  it("copies the exact command without executing a server request", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    const fetch = vi.fn();
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    vi.stubGlobal("fetch", fetch);
    render(<PipelineReference stage="ask" acquisition={ACQUISITION} manifests={[]} provider="openai" />);
    fireEvent.click(screen.getByText("Implementation and terminal reference"));
    fireEvent.change(screen.getByRole("textbox", { name: /CLI question reference/ }), { target: { value: " revenue " } });
    fireEvent.click(screen.getByRole("button", { name: "Copy code" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Copied"));
    expect(writeText).toHaveBeenCalledExactlyOnceWith("MODE=dev uv run python -m app.cli retrieve --provider 'openai' --query 'revenue'");
    expect(fetch).not.toHaveBeenCalled();
    fireEvent.change(screen.getByRole("textbox", { name: /CLI question reference/ }), { target: { value: "profit" } });
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
  });

  it("reports clipboard failure without claiming a copy succeeded", async () => {
    vi.stubGlobal("navigator", { clipboard: { writeText: vi.fn().mockRejectedValue(new Error("denied")) } });
    render(<PipelineReference stage="filings" acquisition={ACQUISITION} manifests={[]} />);
    fireEvent.click(screen.getByText("Implementation and terminal reference"));
    fireEvent.click(screen.getByRole("button", { name: "Copy code" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Copy failed. Select the code and copy it manually."));
  });
});
