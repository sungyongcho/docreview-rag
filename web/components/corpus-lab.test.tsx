import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CANNED_SUITES } from "@/lib/canned";
import { DEFAULT_PROFILE } from "@/lib/types";
import { CorpusLab, deploymentLabel } from "./corpus-lab";

describe("Corpus Lab", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("keeps real corpus operations disabled in the public read-only mode", () => {
    render(
      <CorpusLab
        live={false}
        profile={DEFAULT_PROFILE}
        onProfileChange={vi.fn()}
        onApplyProfile={vi.fn()}
      />,
    );

    expect(screen.getByText("Read-only portfolio")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Acquire missing filings" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Ingest manifest" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Usage" })).not.toBeInTheDocument();
  });

  it("shows locally persisted usage only in live operator mode", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      let payload: unknown = {};
      if (url.endsWith("/admin/evaluations/suites")) payload = CANNED_SUITES;
      else if (url.endsWith("/admin/evaluations/runs")) payload = { jobs: [] };
      else if (url.endsWith("/admin/corpus/jobs")) payload = { history: [] };
      else if (url.endsWith("/admin/corpus")) payload = { status: {}, documents: [] };
      else if (url.endsWith("/admin/usage")) payload = {
        runs: 2, requests: 3, input_tokens: 100, cached_input_tokens: 20,
        cache_write_input_tokens: 10, output_tokens: 30, reasoning_tokens: 5,
        estimated_cost_usd: "0.01", latest_run_at: null,
        models: [{ model_name: "gpt-5.6-terra", requests: 3, input_tokens: 100,
          cached_input_tokens: 20, cache_write_input_tokens: 10, output_tokens: 30,
          reasoning_tokens: 5, estimated_cost_usd: "0.01" }],
      };
      return new Response(JSON.stringify(payload), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }));
    render(
      <CorpusLab
        live
        profile={DEFAULT_PROFILE}
        onProfileChange={vi.fn()}
        onApplyProfile={vi.fn()}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: "Usage" }));

    await waitFor(() => expect(screen.getByText("gpt-5.6-terra")).toBeInTheDocument());
    expect(screen.getAllByText("$0.01")).toHaveLength(2);
  });
});
  it("derives a text-only deployment label from the current host", () => {
    expect(deploymentLabel("localhost")).toBe("DEV");
    expect(deploymentLabel("127.0.0.1")).toBe("DEV");
    expect(deploymentLabel("review.example.com")).toBe("PROD");
  });
