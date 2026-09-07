import type { ReviewSessionDraft } from "./types";
export type RunBudget = ReviewSessionDraft["prompt_policy"]["workflow_budget"];

/** Reserve 30% over measured generation time; prefill and retrieval remain unmeasured. */
export function suggestLocalLimits(budget: RunBudget, speed: number) {
  if (!Number.isFinite(speed) || speed <= 0 || !Number.isInteger(budget.max_output_tokens) || budget.max_output_tokens <= 0 || budget.max_output_tokens > 4000 || !Number.isFinite(budget.max_wall_clock_s) || budget.max_wall_clock_s < 1 || budget.max_wall_clock_s > 600) return null;
  const estimatedSeconds = budget.max_output_tokens / speed;
  const time = Math.min(600, Math.max(budget.max_wall_clock_s, Math.ceil(estimatedSeconds * 1.3)));
  const output = Math.min(budget.max_output_tokens, Math.floor(speed * time / 1.3));
  if (output < 1) return null;
  return { estimatedSeconds, budget: { ...budget, max_wall_clock_s: time, max_output_tokens: output } };
}
