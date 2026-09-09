"use client";
import { useState } from "react";
import { ChevronDown, X } from "lucide-react";
import { useI18n } from "@/lib/i18n";
import { SLOW_LOCAL_CPU_TOKENS_PER_SECOND } from "@/lib/local-models";
import { suggestLocalLimits } from "@/lib/local-limit-suggestion";
import type { ReviewSessionDraft } from "@/lib/types";
import "./slow-cpu-notice.css";

/** A translucent one-line bar floating above the composer; every change is applied in the settings editor. */
export function SlowCpuNotice({ profile, model, speed, onOpenLimits, onOpenEvidence }: { profile: ReviewSessionDraft; model: string; speed: number; onOpenLimits: () => void; onOpenEvidence: () => void }) {
  const { t, locale } = useI18n();
  const [expanded, setExpanded] = useState(false);
  const [closed, setClosed] = useState(false);
  const policy = profile.prompt_policy;
  const current = policy.workflow_budget;
  const suggestion = suggestLocalLimits(current, speed);
  const changed = suggestion && (suggestion.budget.max_wall_clock_s !== current.max_wall_clock_s || suggestion.budget.max_output_tokens !== current.max_output_tokens);
  if (closed) return null;
  return <div className="slow-cpu-notice" role="status" aria-label={t("Slow local CPU model")}>
    <div className="slow-cpu-bar">
      <span className="slow-cpu-light" aria-hidden="true" />
      <span className="slow-cpu-summary">{t("{model} on CPU · {speed} tok/s (threshold {threshold} tok/s)", { model, speed: speed.toLocaleString(locale, { maximumFractionDigits: 1 }), threshold: SLOW_LOCAL_CPU_TOKENS_PER_SECOND })}</span>
      {suggestion && <span className="slow-cpu-estimate">{t("Output {tokens} tokens ≈ {seconds} s · limit {limit} s", { tokens: current.max_output_tokens, seconds: Math.ceil(suggestion.estimatedSeconds), limit: current.max_wall_clock_s })}</span>}
      <span className="slow-cpu-actions">
        {changed && <button className="button" type="button" onClick={onOpenLimits}>{t("Review recommended limits in settings")}</button>}
        <button className="inline-link" type="button" onClick={onOpenLimits}>{t("Run limits")}</button>
        <button className="inline-link" type="button" onClick={onOpenEvidence}>{t("Evidence")}</button>
        <button className="inline-link slow-cpu-more" type="button" aria-expanded={expanded} onClick={() => setExpanded(value => !value)}>{t("Details")}<ChevronDown size={13} aria-hidden="true" className={expanded ? "expanded" : undefined} /></button>
        <button className="icon-button slow-cpu-close" type="button" aria-label={t("Dismiss slow CPU notice")} onClick={() => setClosed(true)}><X size={15} aria-hidden="true" /></button>
      </span>
    </div>
    {expanded && <div className="slow-cpu-details">
      <p>{t("Before sending, allow more time in Run limits or reduce Evidence. Sending remains available.")}</p>
      <p className="helper">{t("Generation estimates exclude retrieval and prompt processing. Actual provider limits may be lower; completing within this time is not guaranteed.")}</p>
      <p className="helper">{t("Open settings to compare and apply changes. Opening the editor does not change values or send the question.")}</p>
    </div>}
  </div>;
}
