import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { PublicRunLimits } from "./public-run-limits";
import { DEFAULT_SESSION_PROFILE } from "@/lib/types";
const api = vi.hoisted(() => ({ getReleaseLimits: vi.fn() }));
vi.mock("@/lib/api", () => api);
afterEach(() => { cleanup(); vi.resetAllMocks(); });
it("keeps failed policy unknown and retries with actual server values", async () => {
  api.getReleaseLimits.mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce({ prompt_policy: { ...DEFAULT_SESSION_PROFILE.prompt_policy, max_context_chars: 4321 }, per_call: { max_input_tokens: 1234, max_output_tokens: 432, max_cost_usd: "0.02" } });
  render(<PublicRunLimits />);
  expect(screen.getByText("Loading server execution limits…")).toBeVisible();
  expect(await screen.findByText(/Server execution limits could not be loaded/)).toBeVisible();
  expect(screen.queryByText("12,000")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", {name: "Retry"}));
  expect(await screen.findByText("4,321")).toBeVisible();
  expect(screen.getByText("1,234")).toBeVisible();
});
