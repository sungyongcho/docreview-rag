"use client";
import { useId } from "react";
import { RunLimitGuidance } from "./run-limit-guidance";
import { useI18n } from "@/lib/i18n";
import { DEFAULT_SESSION_PROFILE } from "@/lib/types";
import { suggestLocalLimits, LOCAL_CPU_STARTING_BUDGET, type RunBudget } from "@/lib/local-limit-suggestion";

/** Share bounded, labelled limit controls between conversation overrides and saved defaults. */
export function RunLimitFields({ budget, onChange, speed, onApplyCpuPreset, evidenceChars, onEvidenceChange }: { budget: RunBudget; onChange: (budget: RunBudget) => void; speed?: number | null; onApplyCpuPreset?: () => void; evidenceChars?: number; onEvidenceChange?: (value: number) => void }) {
  const { t, locale } = useI18n();
  const id = useId();
  const suggestion = speed ? suggestLocalLimits(budget, speed) : null;
  const changed = suggestion && (suggestion.budget.max_wall_clock_s !== budget.max_wall_clock_s || suggestion.budget.max_output_tokens !== budget.max_output_tokens);
  const fields = [["max_iterations", "Maximum iterations", 0, 20, "iterations"], ["max_input_tokens", "Maximum input tokens", 0, 100000, "tokens"], ["max_output_tokens", "Maximum output tokens", 0, 4000, "tokens"], ["max_wall_clock_s", "Maximum wall clock seconds", 1, 600, "seconds"]] as const;
  return <div className="run-limit-editor" data-help="review.run-limits">
    {changed && <div className="notice warning limit-recommendation"><h3>{t("Recommended limits")}</h3><p>{t("Generation estimates exclude retrieval and prompt processing. Actual provider limits may be lower; completing within this time is not guaranteed.")}</p><button type="button" className="button primary" onClick={() => onChange(suggestion.budget)}>{t("Apply recommended limits: {before}s → {after}s; output {oldTokens} → {newTokens}", { before: budget.max_wall_clock_s, after: suggestion.budget.max_wall_clock_s, oldTokens: budget.max_output_tokens, newTokens: suggestion.budget.max_output_tokens })}</button></div>}
    <label className="run-limit-preset">{t("Limit preset")}<select value="" onChange={event => {
      if (event.target.value === "cpu-start") { if (onApplyCpuPreset) onApplyCpuPreset(); else onChange({ ...LOCAL_CPU_STARTING_BUDGET }); }
      if (event.target.value === "fast") onChange({ max_iterations: 2, max_input_tokens: 20000, max_output_tokens: 800, max_wall_clock_s: 60 });
      if (event.target.value === "balanced") onChange(structuredClone(DEFAULT_SESSION_PROFILE.prompt_policy.workflow_budget));
      if (event.target.value === "extended") onChange({ ...budget, max_wall_clock_s: 600 });
      if (event.target.value === "cpu" && suggestion) onChange(suggestion.budget);
    }}><option value="">{t("Choose limits to apply…")}</option><option value="cpu-start">{t("Slow local model start")}</option><option value="fast">{t("Fast")}</option><option value="balanced">{t("Balanced")}</option><option value="extended">{t("More time")}</option><option value="cpu" disabled={!suggestion}>{t("From measured local speed")}</option></select></label>
    <div className="run-limit-grid">
      {fields.map(([key, label, min, max, unit]) => <label key={key}><span>{t(label)}</span><span className="run-limit-input"><input type="number" aria-label={t(label)} aria-describedby={`${id}-${key}`} min={min} max={max} step={key === "max_wall_clock_s" ? "any" : 1} value={budget[key]} onChange={event => onChange({ ...budget, [key]: Number(event.target.value) })} /><span aria-hidden="true">{t(unit)}</span></span><small id={`${id}-${key}`}>{min.toLocaleString(locale)}–{max.toLocaleString(locale)} {t(unit)}</small></label>)}
      {evidenceChars !== undefined && onEvidenceChange && <label><span>{t("Maximum evidence characters")}</span><span className="run-limit-input"><input type="number" aria-label={t("Maximum evidence characters")} aria-describedby={`${id}-evidence`} min={1000} max={100000} step={1} value={evidenceChars} onChange={event => onEvidenceChange(Number(event.target.value))} /><span aria-hidden="true">{t("characters")}</span></span><small id={`${id}-evidence`}>{(1000).toLocaleString(locale)}–{(100000).toLocaleString(locale)} {t("characters")}</small></label>}
    </div>
    <div className="run-limit-help">
      <RunLimitGuidance />
    {suggestion && <p className="helper">{t("Generation estimate: {seconds} seconds at {speed} tok/s. Retrieval and prompt processing take additional time; this is not a completion guarantee.", { seconds: Math.ceil(suggestion.estimatedSeconds), speed: speed! })}</p>}
    </div>
  </div>;
}
