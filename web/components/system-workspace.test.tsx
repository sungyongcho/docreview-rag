import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SystemWorkspace, type SystemWorkspaceProps } from "./system-workspace";
import { I18nProvider, LOCALE_KEY } from "@/lib/i18n";
import { expectNoUnexpectedRequests, jsonResponse, stubHttp } from "@/lib/http-test-support";

function renderSystem(overrides: Partial<SystemWorkspaceProps> = {}) {
  return render(
    <SystemWorkspace
      live={false}
      readiness={null}
      checking={false}
      onRefresh={() => undefined}
      operationsAvailable={false}
      tab="status"
      onTabChange={() => undefined}
      {...overrides}
    />,
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  localStorage.clear();
  expectNoUnexpectedRequests();
});

describe("System workspace", () => {
  it("explains why the raw API action is disabled while readiness is degraded", () => {
    renderSystem({ live: true, ready: false, tab: "api" });
    expect(screen.getByRole("button", { name: "Send to API" })).toBeDisabled();
    expect(screen.getByText("Corpus not ready. Inspect the earliest verified prerequisite.")).toBeInTheDocument();
  });


  it("shows locally persisted usage only in live operator mode", async () => {
    renderSystem({ live: false });
    expect(screen.queryByRole("button", { name: "Usage" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "API inspector" })).not.toBeInTheDocument();
    cleanup();

    stubHttp({ "GET /admin/usage": () => jsonResponse({
      runs: 2, requests: 3, input_tokens: 100, cached_input_tokens: 20,
      cache_write_input_tokens: 10, output_tokens: 30, reasoning_tokens: 5,
      estimated_cost_usd: "0.01", latest_run_at: null,
      models: [{ model_name: "gpt-5.6-terra", requests: 3, input_tokens: 100,
        cached_input_tokens: 20, cache_write_input_tokens: 10, output_tokens: 30,
        reasoning_tokens: 5, estimated_cost_usd: "0.01" }],
    }) });
    renderSystem({ live: true, tab: "usage" });

    expect(screen.getByRole("button", { name: "Usage" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Usage" })).toHaveAttribute("title", "DEV only");
    await waitFor(() => expect(screen.getByText("gpt-5.6-terra")).toBeInTheDocument());
    expect(screen.getAllByText("$0.01")).toHaveLength(3);
  });

  it("hides the Operations tab without a local operator and falls back to status", () => {
    const onTabChange = vi.fn();
    renderSystem({ operationsAvailable: false, tab: "operations", onTabChange });

    expect(screen.queryByRole("button", { name: "Operations" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "System status" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("heading", { name: "OpenAI model policy" })).toBeInTheDocument();
    cleanup();

    renderSystem({ live: true, operationsAvailable: true, onTabChange });
    fireEvent.click(screen.getByRole("button", { name: "Operations" }));
    expect(onTabChange).toHaveBeenCalledWith("operations");
  });

  it("links to the localized user guide in the same tab", () => {
    // next.config.ts sets trailingSlash: true; next/link reads the same flag from this env at render time.
    vi.stubEnv("__NEXT_TRAILING_SLASH", "true");
    renderSystem();

    const documentation = screen.getByRole("link", { name: "User guide" });
    expect(documentation).not.toHaveAttribute("target");
    expect(documentation?.getAttribute("href")?.endsWith("/docs/en/")).toBe(true);
  });

  it("formats recorded usage counts and timestamps in the selected language", async () => {
    localStorage.setItem(LOCALE_KEY, "ko");
    stubHttp({ "GET /admin/usage": () => jsonResponse({
      runs: 1200, requests: 2400, input_tokens: 12345, cached_input_tokens: 0,
      cache_write_input_tokens: 0, output_tokens: 0, reasoning_tokens: 0,
      estimated_cost_usd: "0.0100", latest_run_at: "2026-09-05T12:00:00Z", models: [],
    }) });
    render(<I18nProvider><SystemWorkspace live readiness={null} checking={false} onRefresh={vi.fn()} operationsAvailable={false} tab="usage" onTabChange={vi.fn()} /></I18nProvider>);
    expect(await screen.findByText("12,345")).toBeInTheDocument();
    expect(screen.getByText("1,200")).toBeInTheDocument();
    expect(screen.getByText("2,400")).toBeInTheDocument();
    expect(screen.getByText(/2026\. 9\. 5\./)).toBeInTheDocument();
    expect(screen.getByText("$0.0100")).toBeInTheDocument();
  });
});


it("groups external and local embedding usage with matching subtotals and explicit estimates", async () => {
  const common = { cached_input_tokens: 0, cache_write_input_tokens: 0, output_tokens: 0, reasoning_tokens: 0, estimated_input_tokens: 0, unreported_input_requests: 0, unreported_cost_requests: 0 };
  const external = { ...common, provider: "openai_embeddings", local: false, credential_slot: "OPENAI_API_KEY_LOCAL", model_name: "text-embedding-3-large", role: "embedding", requests: 2, input_tokens: 100, estimated_cost_usd: "0.000013" };
  const local = { ...common, provider: "sbert", local: true, credential_slot: "none", model_name: "local-model", role: "embedding", requests: 1, input_tokens: 0, estimated_input_tokens: 12, unreported_input_requests: 1, estimated_cost_usd: "0" };
  const payload = { ...common, runs: 0, requests: 3, input_tokens: 100, estimated_input_tokens: 12, unreported_input_requests: 1, estimated_cost_usd: "0.000013", latest_run_at: null, models: [external, local], providers: [{ ...external, models: [external] }, { ...local, models: [local] }] };
  stubHttp({ "GET /admin/usage": () => jsonResponse(payload) });
  renderSystem({ live: true, tab: "usage" });
  await screen.findByText("text-embedding-3-large");
  expect(screen.getByRole("region", { name: "openai_embeddings · OPENAI_API_KEY_LOCAL" })).toHaveTextContent("External API");
  expect(screen.getByRole("region", { name: "sbert · none" })).toHaveTextContent("Local · free");
  expect(screen.getByRole("region", { name: "sbert · none" })).toHaveTextContent("Not reported: 1");
  expect(screen.getAllByText("Provider subtotal")).toHaveLength(2);
  expect(screen.getAllByRole("columnheader", { name: "Reported input" })).toHaveLength(2);
  expect(screen.getAllByRole("columnheader", { name: "Estimated input" })).toHaveLength(2);
});
