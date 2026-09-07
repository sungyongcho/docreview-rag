import { describe, expect, it } from "vitest";
import { DEFAULT_SESSION_PROFILE } from "./types";
import { suggestLocalLimits } from "./local-limit-suggestion";
const base = DEFAULT_SESSION_PROFILE.prompt_policy.workflow_budget;
describe("local CPU recommendations", () => {
  it("adds measured generation headroom without modifying the supplied budget", () => {
    const result = suggestLocalLimits(base, 11.7)!;
    expect(result.budget.max_wall_clock_s).toBe(445);
    expect(result.budget.max_output_tokens).toBe(4000);
    expect(result.budget.max_input_tokens).toBe(base.max_input_tokens);
    expect(base.max_wall_clock_s).toBe(120);
  });
  it("reduces output when the 600-second server ceiling cannot fit the current output cap", () => {
    const result = suggestLocalLimits(base, 1)!;
    expect(result.budget.max_wall_clock_s).toBe(600);
    expect(result.budget.max_output_tokens).toBe(461);
    expect(result.budget.max_output_tokens / 1 * 1.3).toBeLessThanOrEqual(600);
  });
  it.each([0, -1, NaN, Infinity, 0.0001])("does not invent a viable suggestion for speed %s", speed => {
    expect(suggestLocalLimits(base, speed)).toBeNull();
  });
  it("keeps deliberate zero-output experiments and invalid limits out of recommendations", () => {
    expect(suggestLocalLimits({ ...base, max_output_tokens: 0 }, 10)).toBeNull();
    expect(suggestLocalLimits({ ...base, max_wall_clock_s: 601 }, 10)).toBeNull();
  });
});
