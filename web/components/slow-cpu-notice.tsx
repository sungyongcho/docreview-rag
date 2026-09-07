"use client";
import { useI18n } from "@/lib/i18n";
import { SLOW_LOCAL_CPU_TOKENS_PER_SECOND } from "@/lib/local-models";
import { suggestLocalLimits } from "@/lib/local-limit-suggestion";
import type { ReviewSessionDraft } from "@/lib/types";

/** Keep slow-model guidance inline; all changes are reviewed and applied in the settings editor. */
export function SlowCpuNotice({ profile, model, speed, onOpenLimits, onOpenEvidence }: { profile: ReviewSessionDraft; model: string; speed: number; onOpenLimits: () => void; onOpenEvidence: () => void }) {
  const { t, locale } = useI18n();
  const policy = profile.prompt_policy;
  const current = policy.workflow_budget;
  const suggestion = suggestLocalLimits(current, speed);
  const changed = suggestion && (suggestion.budget.max_wall_clock_s !== current.max_wall_clock_s || suggestion.budget.max_output_tokens !== current.max_output_tokens);
  return <div className="notice warning slow-cpu-notice" role="status" aria-label={t("Slow local CPU model")}>
    <p>{t("{model} is running on CPU. Its recent generation speed was {speed} tok/s, below the {threshold} tok/s warning threshold. Before sending, allow more time in Run limits or reduce Evidence. Sending remains available.", { model, speed: speed.toLocaleString(locale, { maximumFractionDigits: 1 }), threshold: SLOW_LOCAL_CPU_TOKENS_PER_SECOND })}</p>
    {suggestion && <p>{t("Output ceiling: {tokens} tokens ≈ {seconds} seconds; current run time: {limit} seconds.", { tokens: current.max_output_tokens, seconds: Math.ceil(suggestion.estimatedSeconds), limit: current.max_wall_clock_s })}</p>}
    <p className="helper">{t("Generation estimates exclude retrieval and prompt processing. Actual provider limits may be lower; completing within this time is not guaranteed.")}</p>
    {changed && <button className="button" type="button" onClick={onOpenLimits}>{t("Review recommended limits in settings")}</button>}
    <p className="helper">{t("Open settings to compare and apply changes. Opening the editor does not change values or send the question.")}</p>
    <button className="inline-link" type="button" onClick={onOpenLimits}>{t("Run limits")}</button>{" · "}<button className="inline-link" type="button" onClick={onOpenEvidence}>{t("Evidence")}</button>
  </div>;
}
