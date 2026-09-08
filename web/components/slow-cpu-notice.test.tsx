import { useState } from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { DEFAULT_SESSION_PROFILE } from "@/lib/types";
import { loadDefaultProfile, newConversation, saveDefaultProfile } from "@/lib/storage";
import { RunLimitFields } from "./run-limit-fields";
import { SlowCpuNotice } from "./slow-cpu-notice";
import { DefaultRunLimits } from "./default-run-limits";
beforeEach(() => localStorage.clear());
afterEach(cleanup);

it("opens the settings editor without changing values or saving defaults", () => {
  const limits = vi.fn(), evidence = vi.fn();
  const original = structuredClone(DEFAULT_SESSION_PROFILE);
  render(<SlowCpuNotice profile={original} model="gemma4:e4b" speed={11.7} onOpenLimits={limits} onOpenEvidence={evidence} />);
  fireEvent.click(screen.getByRole("button", { name: "Review recommended limits in settings" }));
  expect(limits).toHaveBeenCalledOnce();
  expect(screen.queryByRole("button", { name: /Apply recommended/ })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Evidence" }));
  expect(evidence).toHaveBeenCalledOnce();
  expect(original).toEqual(DEFAULT_SESSION_PROFILE);
  expect(loadDefaultProfile().prompt_policy.workflow_budget.max_wall_clock_s).toBe(120);
});

/** Keep recommendation application inside the real editor's controlled fields. */
function Limits() {
  const [budget, setBudget] = useState(structuredClone(DEFAULT_SESSION_PROFILE.prompt_policy.workflow_budget));
  return <RunLimitFields budget={budget} speed={11.7} onChange={setBudget} />;
}
it("shows the exact recommendation and changes the value only when applied inside settings", () => {
  render(<Limits />);
  expect(screen.getByLabelText("Maximum wall clock seconds")).toHaveValue(120);
  fireEvent.click(screen.getByRole("button", { name: "Apply recommended limits: 120s → 445s; output 4000 → 4000" }));
  expect(screen.getByLabelText("Maximum wall clock seconds")).toHaveValue(445);
  expect(screen.queryByRole("button", { name: /Apply recommended/ })).toBeNull();
  expect(loadDefaultProfile().prompt_policy.workflow_budget.max_wall_clock_s).toBe(120);
});
it("saves new-conversation limits without modifying an existing conversation or prompt defaults", () => {
  const original = structuredClone(DEFAULT_SESSION_PROFILE);
  original.prompt_policy.additional_instructions = "Keep this instruction";
  saveDefaultProfile(original);
  const existing = newConversation();
  render(<DefaultRunLimits />);
  fireEvent.change(screen.getByLabelText("Maximum wall clock seconds"), { target: { value: "300" } });
  expect(loadDefaultProfile().prompt_policy.workflow_budget.max_wall_clock_s).toBe(120);
  fireEvent.click(screen.getByRole("button", { name: "Save default limits" }));
  expect(newConversation().profile).toMatchObject({ prompt_policy: { workflow_budget: { max_wall_clock_s: 300 } } });
  expect(existing.profile).toMatchObject({ prompt_policy: { workflow_budget: { max_wall_clock_s: 120 } } });
  expect(loadDefaultProfile().prompt_policy.additional_instructions).toBe("Keep this instruction");
  fireEvent.change(screen.getByLabelText("Maximum wall clock seconds"), { target: { value: "0" } });
  expect(screen.getByRole("button", { name: "Save default limits" })).toBeDisabled();
});

it("applies the optional CPU starting point only to the defaults draft until saved", () => {
  render(<DefaultRunLimits />);
  fireEvent.change(screen.getByRole("combobox", { name: "Limit preset" }), { target: { value: "cpu-start" } });
  expect(screen.getByLabelText("Maximum input tokens")).toHaveValue(24000);
  expect(screen.getByLabelText("Maximum output tokens")).toHaveValue(2000);
  expect(screen.getByLabelText("Maximum wall clock seconds")).toHaveValue(300);
  expect(screen.getByLabelText("Maximum evidence characters")).toHaveValue(8000);
  expect(loadDefaultProfile().prompt_policy).toEqual(DEFAULT_SESSION_PROFILE.prompt_policy);
  fireEvent.click(screen.getByRole("button", { name: "Save default limits" }));
  expect(loadDefaultProfile().prompt_policy).toMatchObject({ max_context_chars: 8000, workflow_budget: { max_input_tokens: 24000, max_output_tokens: 2000, max_wall_clock_s: 300 } });
  expect(DEFAULT_SESSION_PROFILE.prompt_policy.workflow_budget.max_wall_clock_s).toBe(120);
});

/** Restoring is a draft action; saving changes only future conversations. */
it("restores limits explicitly and clears saved feedback after edits", () => {
  render(<DefaultRunLimits />);
  fireEvent.change(screen.getByLabelText("Maximum wall clock seconds"), { target: { value: "300" } });
  fireEvent.click(screen.getByRole("button", { name: "Save default limits" }));
  expect(screen.getByRole("status")).toHaveTextContent("Default limits saved");
  fireEvent.click(screen.getByRole("button", { name: "Restore limit defaults" }));
  expect(screen.queryByRole("status")).toBeNull();
  expect(screen.getByLabelText("Maximum wall clock seconds")).toHaveValue(120);
  expect(loadDefaultProfile().prompt_policy.workflow_budget.max_wall_clock_s).toBe(300);
  fireEvent.click(screen.getByRole("button", { name: "Save default limits" }));
  expect(loadDefaultProfile().prompt_policy.workflow_budget.max_wall_clock_s).toBe(120);
  fireEvent.change(screen.getByLabelText("Maximum evidence characters"), { target: { value: "9000" } });
  expect(screen.queryByRole("status")).toBeNull();
});

/** CPU preset changes invalidate saved feedback without persisting an unsaved draft. */
it("clears saved feedback when the CPU starting preset changes the draft", () => {
  render(<DefaultRunLimits />);
  fireEvent.click(screen.getByRole("button", { name: "Save default limits" }));
  expect(screen.getByRole("status")).toHaveTextContent("Default limits saved");
  fireEvent.change(screen.getByLabelText("Limit preset"), { target: { value: "cpu-start" } });
  expect(screen.getByLabelText("Maximum wall clock seconds")).toHaveValue(300);
  expect(loadDefaultProfile().prompt_policy.workflow_budget.max_wall_clock_s).toBe(120);
  expect(screen.queryByRole("status")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Save default limits" }));
  expect(loadDefaultProfile().prompt_policy.workflow_budget.max_wall_clock_s).toBe(300);
  expect(screen.getByRole("status")).toHaveTextContent("Default limits saved");
});
