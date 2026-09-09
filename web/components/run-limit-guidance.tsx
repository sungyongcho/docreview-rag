"use client";
import { useI18n } from "@/lib/i18n";

/** Explain whole-run settings without implying that public clients can override server limits. */
export function RunLimitGuidance() {
  const { t } = useI18n();
  return <div className="helper run-limit-guidance">
    <p>{t("These limits apply to the complete run of one question, whichever answer engine is selected. For smoother local use, adjust input/output tokens and evidence to your hardware: start with Slow local model start, then check an actual run.")}</p>
    <p>{t("Defaults: 60,000 input / 4,000 output tokens, 120 seconds. Optional CPU start: 24,000 / 2,000 tokens, 300 seconds, 8,000 evidence characters. These are whole-run budgets, not promised usage or completion times.")}</p>
    <p>{t("DEV sends the selected limits with the question. OpenAI per-call caps are shown below and can only be lowered from the web; public PROD uses server policy and does not enable local LLM editing. Check Run details for the limits actually applied.")}</p>
  </div>;
}
