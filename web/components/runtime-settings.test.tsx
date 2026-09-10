import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Readiness } from "@/lib/types";
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.unstubAllEnvs(); vi.resetModules(); window.localStorage.clear(); });
import { RuntimeSettings, DesktopJobNotifications } from "./runtime-settings";

const READINESS: Readiness = {
  environment: "dev",
  status: "ready",
  mode: "runtime",
  admin_mode: "live",
  policy_revision: "2026-09-01",
  models: {
    review: { default: "gpt-5.6-terra", allowed: ["gpt-5.6-terra"], reasoning_effort: "medium", dimensions: null },
    embedding: { default: "text-embedding-3-large", allowed: ["text-embedding-3-large"], reasoning_effort: null, dimensions: 384 },
  },
  review_enabled: true,
  active_review_model: "gpt-5.6-terra",
  corpus: {
    availability: "ready", database_connected: true, schema_status: "compatible", schema_message: "ok",
    documents: 30, chunks: 22367, embedded_chunks: 22367, pending_embeddings: 0, bm25_ready: true, writable: true,
  },
};
  it("shows production token ceilings and non-consuming reset estimates", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      per_minute: 5,
      per_day: 25,
      remaining_minute: 0,
      remaining_day: 20,
      max_input_tokens: 12000,
      max_output_tokens: 600,
      max_cost_usd: "0.04",
      daily_cost_usd: "1.00",
      remaining_daily_cost_usd: "0.80",
      retry_after_seconds: 42,
      minute_reset_seconds: 42,
      day_reset_seconds: 3600,
      daily_cost_reset_at_utc: "2026-09-02T00:00:00Z",
      scope: "single_process",
    }), { status: 200, headers: { "content-type": "application/json" } })));
    render(<RuntimeSettings live={false} readiness={null} />);

    expect(await screen.findByText("12,000")).toBeInTheDocument();
    expect(screen.getByText("600")).toBeInTheDocument();
    expect(screen.getByText(/Next recovery: 42s/)).toBeInTheDocument();
    expect(screen.getByText(/Next recovery: 1h 0m/)).toBeInTheDocument();
    expect(screen.getByText("80%")).toBeInTheDocument();
    expect(screen.queryByText(/\$/)).not.toBeInTheDocument();
    expect(screen.getByText(/12:00:00 AM UTC$/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Limits & availability" })).toBeInTheDocument();
    expect(document.querySelector(".development-badge")).toBeNull();
  });

  it("marks the local runtime panel as DEV without requesting release limits", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    render(<RuntimeSettings live readiness={READINESS} />);

    const panel = screen.getByRole("heading", { name: "Local runtime" }).closest("section")!;
    // The Mode metric also reads "DEV", so look at the badge itself.
    const badge = panel.querySelector(".development-badge");
    expect(badge).toHaveAttribute("aria-label", "DEV only");
    expect(badge).toHaveTextContent("DEV");
    expect(within(panel).getByText("Operations URL")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("enables desktop completion notifications only after browser permission", async () => {
    const requestPermission = vi.fn().mockResolvedValue("granted");
    vi.stubGlobal("Notification", { permission: "default", requestPermission });
    render(<DesktopJobNotifications />);
    fireEvent.click(screen.getByRole("button", { name: "Enable desktop job notifications" }));

    await waitFor(() => expect(requestPermission).toHaveBeenCalledOnce());
    expect(screen.getByText("Enabled")).toBeInTheDocument();
  });
