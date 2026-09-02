import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ONBOARDING_KEY } from "@/lib/storage";
import type { Readiness } from "@/lib/types";
import { ServiceShell, terminalAnswer } from "./service-shell";

const READY_RUNTIME: Readiness = {
  status: "ready",
  mode: "runtime",
  admin_mode: "readonly",
  policy_revision: "test",
  models: {},
  review_enabled: true,
  active_review_model: "gpt-5.6-terra",
  corpus: {
    availability: "ready",
    database_connected: true,
    schema_status: "compatible",
    schema_message: "ok",
    documents: 29,
    chunks: 21927,
    embedded_chunks: 21927,
    pending_embeddings: 0,
    bm25_ready: true,
    writable: false,
  },
};

/** Public-build API stub: runtime endpoints plus the public `/snapshots` list; everything else is `{}`. */
function stubPublicApi() {
  const fetchMock = vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
    const url = String(input);
    let payload: unknown = {};
    if (url.endsWith("/health")) payload = { status: "ok" };
    else if (url.endsWith("/ready")) payload = READY_RUNTIME;
    else if (url.endsWith("/capabilities")) payload = {
      can_edit_prompt_policy: false, can_edit_run_limits: false, can_edit_golden: false,
      can_build_snapshot: false, can_run_evaluation: false, can_change_custom_retrieval: false,
      can_query_snapshot: false, can_use_operations: false, can_compare_published_snapshots: true,
    };
    else if (url.endsWith("/limits")) payload = {
      per_minute: 5, per_day: 25, remaining_minute: 5, remaining_day: 25, max_input_tokens: 12000,
      max_output_tokens: 600, max_cost_usd: "0.04", daily_cost_usd: "1.00", remaining_daily_cost_usd: "1.00",
      retry_after_seconds: 0, minute_reset_seconds: 0, day_reset_seconds: 0,
      daily_cost_reset_at_utc: "2026-09-02T00:00:00Z", scope: "single_process",
    };
    else if (url.endsWith("/snapshots")) payload = { snapshots: [] };
    return new Response(JSON.stringify(payload), { status: 200, headers: { "content-type": "application/json" } });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("service shell", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.localStorage.setItem(ONBOARDING_KEY, "done");
    vi.stubGlobal("crypto", { randomUUID: () => "conversation-id" });
  });
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("navigates between Build, Measure and System from the sidebar", async () => {
    const fetchMock = stubPublicApi();
    render(<ServiceShell />);
    await waitFor(() => expect(screen.getByRole("button", { name: "healthy" })).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Build" }));
    expect(screen.getByRole("heading", { name: "From filings to verified answers." })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Build" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("Read-only portfolio")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Measure" }));
    expect(screen.getByRole("heading", { name: "Measure retrieval before trusting it." })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Playground" })).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(screen.getByRole("button", { name: "System" }));
    expect(screen.getByRole("heading", { name: "Runtime readiness" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "System status" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByRole("button", { name: "Operations" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Usage" })).not.toBeInTheDocument();

    // The sidebar action comes first in DOM order; the untitled conversation row shares its name.
    fireEvent.click(screen.getAllByRole("button", { name: "New review" })[0]);
    expect(screen.getByPlaceholderText("Ask a question about the filing corpus")).toBeInTheDocument();

    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(fetchMock.mock.calls.every(([value]) => !String(value).includes("/admin/"))).toBe(true);
  });

  it("renders the review shell and opens documentation in a new window", async () => {
    render(<ServiceShell />);

    await waitFor(() =>
      expect(screen.getByPlaceholderText("Ask a question about the filing corpus")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    fireEvent.click(screen.getByRole("button", { name: "Data & help" }));
    const documentation = screen.getByText("Documentation").closest("a");

    expect(screen.getByText("Review filings with verifiable evidence.")).toBeInTheDocument();
    expect(documentation).toHaveAttribute("target", "_blank");
    expect(documentation).toHaveAttribute("href", "/docreview-rag-agent/docs/");
  });

  it("shows invalidated provider authentication instead of an evidence fallback", () => {
    const answer = terminalAnswer({
      status: "error",
      report: null,
      failure: {
        code: "provider_failure",
        status: "provider_error",
        details: ["AuthenticationError: token_invalidated"],
      },
    });

    expect(answer).toBe(
      "OpenAI API authentication failed. Update the server-side API key and retry.",
    );
  });
});
