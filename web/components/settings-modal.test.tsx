import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Capabilities } from "@/lib/types";
import { DEFAULT_SESSION_PROFILE } from "@/lib/types";
import { loadExperimentDefaults } from "@/lib/storage";
import { SettingsModal } from "./settings-modal";

const DEV: Capabilities = {
  can_edit_prompt_policy: true,
  can_edit_run_limits: true,
  can_edit_golden: true,
  can_build_snapshot: true,
  can_run_evaluation: true,
  can_change_custom_retrieval: true,
  can_query_snapshot: true,
  can_use_operations: true,
  can_compare_published_snapshots: true,
};

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

function renderSettings(capabilities: Capabilities, onClose = vi.fn()) {
  return render(<SettingsModal open profile={DEFAULT_SESSION_PROFILE} capabilities={capabilities} readiness={null} onChange={vi.fn()} onClose={onClose} onOpenMeasure={vi.fn()} onOpenSystem={vi.fn()} onOpenTour={vi.fn()} onClear={vi.fn()} />);
}

describe("Settings modal", () => {
  it("shows developer prompt policy while preserving the immutable guard", () => {
    renderSettings(DEV);
    fireEvent.click(screen.getByRole("button", { name: "Prompt & evidence" }));

    expect(screen.getByLabelText("Immutable evidence guard")).toHaveAttribute("readonly");
    expect(screen.getByLabelText("Additional operator instructions")).toHaveAttribute("maxlength", "8000");
  });

  it("uses a distinct production menu and closes with Escape", () => {
    const onClose = vi.fn();
    renderSettings({ ...DEV, can_edit_prompt_policy: false }, onClose);

    expect(screen.queryByRole("button", { name: "Prompt & evidence" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Limits & availability" })).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledOnce();
  });

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
    renderSettings({ ...DEV, can_edit_prompt_policy: false });
    fireEvent.click(screen.getByRole("button", { name: "Limits & availability" }));

    expect(await screen.findByText("12,000")).toBeInTheDocument();
    expect(screen.getByText("600")).toBeInTheDocument();
    expect(screen.getAllByText("42s").length).toBeGreaterThan(0);
    expect(screen.getByText(/reset 1h 0m/)).toBeInTheDocument();
  });

  it("enables desktop completion notifications only after browser permission", async () => {
    const requestPermission = vi.fn().mockResolvedValue("granted");
    vi.stubGlobal("Notification", { permission: "default", requestPermission });
    renderSettings(DEV);
    fireEvent.click(screen.getByRole("button", { name: "Local runtime" }));
    fireEvent.click(screen.getByRole("button", { name: "Enable desktop job notifications" }));

    await waitFor(() => expect(requestPermission).toHaveBeenCalledOnce());
    expect(screen.getByText("Enabled")).toBeInTheDocument();
  });

  it("stores suite, revision, snapshot, mode, and baseline experiment defaults", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      const payload = url.endsWith("/admin/snapshots")
        ? [{ snapshot_id: 4, label: "Ready baseline", status: "ready", public: false, corpus_fingerprint: "a".repeat(64), profile: {}, golden_revision_id: 7, eval_result: { result_id: 3, suite: "sec-en", config: {}, metrics: {}, created_at: "2026-09-01T00:00:00Z" }, document_count: 29, created_at: "2026-09-01T00:00:00Z" }]
        : url.includes("/admin/golden/")
        ? [{ revision_id: 7, suite_id: "sec-en", version: 2, status: "validated", payload: [], sha256: "b".repeat(64), parent_id: null, created_at: "2026-09-01T00:00:00Z", updated_at: "2026-09-01T00:00:00Z" }]
        : { per_minute: 5, per_day: 25, remaining_minute: 5, remaining_day: 25, max_input_tokens: 12000, max_output_tokens: 600, max_cost_usd: "0.04", daily_cost_usd: "1.00", remaining_daily_cost_usd: "1.00", retry_after_seconds: 0, minute_reset_seconds: 0, day_reset_seconds: 0, daily_cost_reset_at_utc: "2026-09-02T00:00:00Z", scope: "single_process" };
      return new Response(JSON.stringify(payload), { status: 200, headers: { "content-type": "application/json" } });
    }));
    renderSettings(DEV);
    fireEvent.click(screen.getByRole("button", { name: "Experiment defaults" }));

    expect(await screen.findAllByRole("option", { name: "#4 · Ready baseline" })).toHaveLength(2);
    fireEvent.change(screen.getByLabelText("Default golden revision"), { target: { value: "7" } });
    fireEvent.change(screen.getByLabelText("Default run mode"), { target: { value: "matrix" } });
    fireEvent.change(screen.getByLabelText("Default ready snapshot"), { target: { value: "4" } });
    fireEvent.change(screen.getByLabelText("Comparison baseline"), { target: { value: "4" } });
    fireEvent.change(screen.getByLabelText("New conversation retrieval preset"), { target: { value: "accuracy" } });
    fireEvent.click(screen.getByRole("button", { name: "Save experiment defaults" }));

    expect(loadExperimentDefaults()).toMatchObject({
      golden_revision_id: 7,
      snapshot_id: 4,
      mode: "matrix",
      baseline_snapshot_id: 4,
      retrieval_preset: "accuracy",
    });
  });
});
