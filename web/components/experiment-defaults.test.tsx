import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.unstubAllEnvs(); vi.resetModules(); window.localStorage.clear(); });
import { DEFAULT_PROFILE } from "@/lib/types";
import { loadExperimentDefaults } from "@/lib/storage";
import { ExperimentDefaultsForm } from "./experiment-defaults";
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
    const onSaved = vi.fn();
    render(<ExperimentDefaultsForm profile={DEFAULT_PROFILE} onSaved={onSaved} />);

    expect(await screen.findAllByRole("option", { name: "#4 · Ready baseline" })).toHaveLength(2);
    fireEvent.change(screen.getByLabelText("Default golden revision"), { target: { value: "7" } });
    fireEvent.change(screen.getByLabelText("Default run mode"), { target: { value: "matrix" } });
    fireEvent.change(screen.getByLabelText("Default ready snapshot"), { target: { value: "4" } });
    fireEvent.change(screen.getByLabelText("Comparison baseline"), { target: { value: "4" } });
    fireEvent.change(screen.getByLabelText("New conversation retrieval preset"), { target: { value: "accuracy" } });
    fireEvent.click(screen.getByRole("button", { name: "Save experiment defaults" }));

    expect(onSaved).toHaveBeenCalledWith(expect.objectContaining({ mode: "matrix", golden_revision_id: 7 }));
    expect(loadExperimentDefaults()).toMatchObject({
      golden_revision_id: 7,
      snapshot_id: 4,
      mode: "matrix",
      baseline_snapshot_id: 4,
      retrieval_preset: "accuracy",
    });
  });
it("uses the same seven server-listed suites as evaluation setup and stores Astra defaults", async () => {
  const suiteIds = ["sec-en", "sec-ko", "dart-en", "dart-ko", "sec-en_v2_astra", "sec-ko_v2_astra", "sec-mixed_v2_astra"];
  vi.stubGlobal("fetch", vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
    const payload = String(input).endsWith("/admin/evaluations/suites") ? suiteIds.map((suite_id) => ({ suite_id, label: suite_id })) : [];
    return new Response(JSON.stringify(payload), { status: 200, headers: { "content-type": "application/json" } });
  }));
  render(<ExperimentDefaultsForm profile={DEFAULT_PROFILE} />);
  expect(await screen.findByRole("option", { name: "sec-mixed_v2_astra" })).toBeInTheDocument();
  expect(screen.getByLabelText("Default golden suite").querySelectorAll("option")).toHaveLength(7);
  fireEvent.change(screen.getByLabelText("Default golden suite"), { target: { value: "sec-mixed_v2_astra" } });
  fireEvent.click(screen.getByRole("button", { name: "Save experiment defaults" }));
  expect(loadExperimentDefaults().suite_id).toBe("sec-mixed_v2_astra");
});
