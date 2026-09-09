"use client";
import { Lightbulb } from "lucide-react";
import { useI18n } from "@/lib/i18n";

/** Explain whole-run settings without implying that public clients can override server limits. */
export function RunLimitGuidance() {
  const { t } = useI18n();
  return <div className="helper run-limit-guidance">
    <p className="run-limit-guidance-title"><Lightbulb size={15} aria-hidden="true" />{t("How run limits work")}</p>
    <ul>
      <li>{t("Applies to the whole run of one question, whichever engine answers. For local models, start with Slow local model start, then check an actual run.")}</li>
      <li>{t("Defaults: 60,000 input / 4,000 output tokens, 120 s. CPU start: 24,000 / 2,000 tokens, 300 s, 8,000 evidence characters. Budgets, not guarantees.")}</li>
      <li>{t("DEV sends these limits with the question; the OpenAI per-call caps below can only be lowered here. PROD uses server policy. Run details shows the applied values.")}</li>
      <li>{t("Counted across every model call. Zero blocks a resource for failure tests; the wall clock needs at least one second.")}</li>
    </ul>
  </div>;
}
