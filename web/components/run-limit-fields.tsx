"use client";
import { useI18n } from "@/lib/i18n";
import { DEFAULT_SESSION_PROFILE } from "@/lib/types";
import { suggestLocalLimits, LOCAL_CPU_STARTING_BUDGET, type RunBudget } from "@/lib/local-limit-suggestion";

/** Share bounded, labelled limit controls between conversation overrides and saved defaults. */
export function RunLimitFields({ budget, onChange, speed, onApplyCpuPreset }: { budget: RunBudget; onChange: (budget: RunBudget) => void; speed?: number | null; onApplyCpuPreset?: () => void }) {
  const { t } = useI18n();
  const suggestion = speed ? suggestLocalLimits(budget, speed) : null;
  const changed = suggestion && (suggestion.budget.max_wall_clock_s !== budget.max_wall_clock_s || suggestion.budget.max_output_tokens !== budget.max_output_tokens);
  const fields = [["max_iterations", "Maximum iterations", 0, 20, "iterations"], ["max_input_tokens", "Maximum input tokens", 0, 100000, "tokens"], ["max_output_tokens", "Maximum output tokens", 0, 4000, "tokens"], ["max_wall_clock_s", "Maximum wall clock seconds", 1, 600, "seconds"]] as const;
  return <div className="profile-grid" data-help="review.run-limits">
    {changed && <div className="notice warning limit-recommendation"><h3>{t("Recommended limits")}</h3><p>{t("Generation estimates exclude retrieval and prompt processing. Actual provider limits may be lower; completing within this time is not guaranteed.")}</p><button type="button" className="button primary" onClick={() => onChange(suggestion.budget)}>{t("Apply recommended limits: {before}s → {after}s; output {oldTokens} → {newTokens}", { before: budget.max_wall_clock_s, after: suggestion.budget.max_wall_clock_s, oldTokens: budget.max_output_tokens, newTokens: suggestion.budget.max_output_tokens })}</button></div>}
    <label>{t("Limit preset")}<select value="" onChange={event => {
      if (event.target.value === "cpu-start") { if (onApplyCpuPreset) onApplyCpuPreset(); else onChange({ ...LOCAL_CPU_STARTING_BUDGET }); }
      if (event.target.value === "fast") onChange({ max_iterations: 2, max_input_tokens: 20000, max_output_tokens: 800, max_wall_clock_s: 60 });
      if (event.target.value === "balanced") onChange(structuredClone(DEFAULT_SESSION_PROFILE.prompt_policy.workflow_budget));
      if (event.target.value === "extended") onChange({ ...budget, max_wall_clock_s: 600 });
      if (event.target.value === "cpu" && suggestion) onChange(suggestion.budget);
    }}><option value="">{t("Choose limits to apply…")}</option><option value="cpu-start">{t("Local CPU starting point")}</option><option value="fast">{t("Fast")}</option><option value="balanced">{t("Balanced")}</option><option value="extended">{t("More time")}</option><option value="cpu" disabled={!suggestion}>{t("Measured local CPU")}</option></select></label>
    {fields.map(([key, label, min, max, unit]) => <label key={key}>{t(label)}<input type="number" aria-label={t(label)} min={min} max={max} step={key === "max_wall_clock_s" ? "any" : 1} value={budget[key]} onChange={event => onChange({ ...budget, [key]: Number(event.target.value) })} /><small>{min.toLocaleString()}–{max.toLocaleString()} {t(unit)}</small></label>)}
    <p className="helper">{t("These limits cover the entire run across all model calls. Zero blocks a resource for failure-path experiments; the wall clock must be at least one second.")}</p>
    {suggestion && <p className="helper">{t("Generation estimate: {seconds} seconds at {speed} tok/s. Retrieval and prompt processing take additional time; this is not a completion guarantee.", { seconds: Math.ceil(suggestion.estimatedSeconds), speed: speed! })}</p>}
  </div>;
}
