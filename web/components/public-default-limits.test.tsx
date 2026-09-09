import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { PublicDefaultRunLimits } from "./default-run-limits";
import { DEFAULT_SESSION_PROFILE } from "@/lib/types";
const api = vi.hoisted(() => ({ getReleaseLimits: vi.fn() }));
vi.mock("@/lib/api", () => ({ ...api, getOpenAILimits: vi.fn(), resetOpenAILimits: vi.fn(), saveOpenAILimits: vi.fn() }));
afterEach(() => { cleanup(); vi.resetAllMocks(); });
it("shows the DEV field layout with actual public values and disabled controls", async () => {
  api.getReleaseLimits.mockResolvedValue({ prompt_policy: { ...DEFAULT_SESSION_PROFILE.prompt_policy, max_context_chars: 4321 }, per_call: { max_input_tokens: 1234, max_output_tokens: 432, max_cost_usd: "0.02" } });
  render(<PublicDefaultRunLimits />);
  expect(await screen.findByLabelText("Maximum evidence characters")).toHaveValue(4321);
  for (const control of screen.getAllByRole("spinbutton")) expect(control).toBeDisabled();
  expect(screen.getByRole("combobox", { name: "Limit preset" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Save default limits" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Save per-call caps" })).toBeDisabled();
  expect(screen.getByLabelText("Per-call input tokens")).toHaveValue(1234);
  expect(api.getReleaseLimits).toHaveBeenCalledTimes(1);
});
