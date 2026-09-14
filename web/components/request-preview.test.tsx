import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DEFAULT_SESSION_PROFILE, resolvedRetrievalProfile } from "@/lib/types";
import { RequestPreviewContent, RetrievalPresetComparison, presetChanges, presetDescription } from "./request-preview";
afterEach(cleanup);
describe("request preview", () => {
  it("updates next-request JSON without editing its profile and separates it from historical settings", () => {
    const profile = structuredClone(DEFAULT_SESSION_PROFILE);
    profile.prompt_policy.workflow_budget.max_wall_clock_s = 180;
    const original = JSON.stringify(profile);
    const { rerender } = render(<RequestPreviewContent profile={profile} query="First question" />);
    fireEvent.click(screen.getByText("Request payload"));
    const payload = screen.getByText(/"query": "First question"/);
    expect(payload).toBeVisible();
    expect(JSON.parse(payload.textContent!)).toEqual({ query: "First question", session_profile: profile });
    rerender(<RequestPreviewContent profile={profile} query="Revised question" />);
    expect(screen.getByText(/"query": "Revised question"/)).toBeVisible();
    expect(JSON.stringify(profile)).toBe(original);
    expect(screen.getByText("These are the next question’s settings, not the selected run’s recorded settings.")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Balanced" })).not.toBeInTheDocument();
    expect(screen.queryByText("Preset parameters and changes")).not.toBeInTheDocument();
  });
  it("keeps alternative preset descriptions in the search comparison", () => {
    render(<RetrievalPresetComparison profile={DEFAULT_SESSION_PROFILE} editable={false} />);
    fireEvent.click(screen.getByText("Compare retrieval presets"));
    expect(screen.queryByRole("button", { name: "Custom" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Balanced" }));
    expect(screen.getByRole("button", { name: "Balanced" })).toHaveAttribute("aria-expanded", "true");
    fireEvent.click(screen.getByRole("button", { name: "Balanced" }));
    expect(screen.getByRole("button", { name: "Balanced" })).toHaveAttribute("aria-expanded", "false");
  });
  it("navigates to editors without mutating the draft and omits inactive search settings", () => {
    const onOpenSection = vi.fn();
    const profile = structuredClone(DEFAULT_SESSION_PROFILE);
    profile.retrieval_preset = "custom";
    profile.custom_retrieval = { ...resolvedRetrievalProfile(profile), strategy: "vector" };
    const original = JSON.stringify(profile);
    render(<RequestPreviewContent profile={profile} query="Compare filings" onOpenSection={onOpenSection} />);
    fireEvent.click(screen.getByRole("button", { name: "Edit search settings" }));
    expect(onOpenSection).toHaveBeenCalledExactlyOnceWith("retrieval");
    expect(screen.queryByText("Keyword ranking")).not.toBeInTheDocument();
    expect(screen.queryByText("Rank fusion constant")).not.toBeInTheDocument();
    expect(screen.queryByText("Reranker")).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(JSON.stringify(profile)).toBe(original);
  });
  it("derives preset changes and visible settings from the effective retrieval profiles", () => {
    const baseline = resolvedRetrievalProfile(DEFAULT_SESSION_PROFILE);
    for (const preset of ["balanced", "korean", "accuracy"] as const) {
      const effective = resolvedRetrievalProfile({ ...DEFAULT_SESSION_PROFILE, retrieval_preset: preset });
      const changes = presetChanges(DEFAULT_SESSION_PROFILE, preset);
      expect(Object.fromEntries(changes)).toEqual(Object.fromEntries(Object.entries(effective).filter(([key, value]) => baseline[key as keyof typeof baseline] !== value)));
      for (const [key, value] of changes) expect(presetDescription(DEFAULT_SESSION_PROFILE, preset).settings).toContain(`${key}: ${String(value)}`);
    }
    expect(presetDescription(DEFAULT_SESSION_PROFILE, "balanced").settings).toContain(`candidate_k: ${baseline.candidate_k}`);
    expect(presetDescription(DEFAULT_SESSION_PROFILE, "korean").purpose).toBe("Uses language-aware retrieval across the selected filing corpus.");
  });

});
