import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SystemWorkspace, type SystemWorkspaceProps } from "./system-workspace";

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

describe("System workspace", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it("shows locally persisted usage only in live operator mode", async () => {
    renderSystem({ live: false });
    expect(screen.queryByRole("button", { name: "Usage" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "API inspector" })).not.toBeInTheDocument();
    cleanup();

    const fetchMock = vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      let payload: unknown = {};
      if (url.endsWith("/admin/usage")) payload = {
        runs: 2, requests: 3, input_tokens: 100, cached_input_tokens: 20,
        cache_write_input_tokens: 10, output_tokens: 30, reasoning_tokens: 5,
        estimated_cost_usd: "0.01", latest_run_at: null,
        models: [{ model_name: "gpt-5.6-terra", requests: 3, input_tokens: 100,
          cached_input_tokens: 20, cache_write_input_tokens: 10, output_tokens: 30,
          reasoning_tokens: 5, estimated_cost_usd: "0.01" }],
      };
      return new Response(JSON.stringify(payload), { status: 200, headers: { "content-type": "application/json" } });
    });
    vi.stubGlobal("fetch", fetchMock);
    renderSystem({ live: true, tab: "usage" });

    expect(screen.getByRole("button", { name: "Usage" })).toHaveAttribute("aria-pressed", "true");
    await waitFor(() => expect(screen.getByText("gpt-5.6-terra")).toBeInTheDocument());
    expect(screen.getAllByText("$0.01")).toHaveLength(2);
    expect(fetchMock.mock.calls.every(([value]) => String(value).endsWith("/admin/usage"))).toBe(true);
  });

  it("hides the Operations tab without a local operator and falls back to status", () => {
    const onTabChange = vi.fn();
    renderSystem({ operationsAvailable: false, tab: "operations", onTabChange });

    expect(screen.queryByRole("button", { name: "Operations" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "System status" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("heading", { name: "OpenAI model policy" })).toBeInTheDocument();
    cleanup();

    renderSystem({ live: true, operationsAvailable: true, onTabChange });
    // The tour's optional last step spotlights this tab button and nothing else in the strip.
    expect(screen.getByRole("button", { name: "Operations" })).toHaveAttribute("data-tour", "operations");
    expect(screen.getByRole("button", { name: "System status" })).not.toHaveAttribute("data-tour");
    fireEvent.click(screen.getByRole("button", { name: "Operations" }));
    expect(onTabChange).toHaveBeenCalledWith("operations");
  });

  it("links to the documentation in a new window", () => {
    // next.config.ts sets trailingSlash: true; next/link reads the same flag from this env at render time.
    vi.stubEnv("__NEXT_TRAILING_SLASH", "true");
    renderSystem();

    const documentation = screen.getByText("Documentation").closest("a");
    expect(documentation).toHaveAttribute("target", "_blank");
    expect(documentation).toHaveAttribute("rel", "noreferrer");
    expect(documentation?.getAttribute("href")?.endsWith("/docs/")).toBe(true);
  });
});
