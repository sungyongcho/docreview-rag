"use client";
import { useEffect, useRef, useState } from "react";
import { useI18n } from "@/lib/i18n";
import { SLOW_LOCAL_CPU_TOKENS_PER_SECOND } from "@/lib/local-models";
import { suggestLocalLimits } from "@/lib/local-limit-suggestion";
import type { ReviewSessionDraft } from "@/lib/types";
import { useNotifications } from "./notifications";

export const SLOW_CPU_NOTICE_KEY = "slow-cpu";

/** Surface the slow-model measurement as one pinned overlay toast whose action opens the limits editor.
 *
 * The parent keys this component by conversation and model, so an explicit close stays closed until
 * either changes; speed refreshes and applied recommendations only update the visible text.
 */
export function SlowCpuNotice({ profile, model, speed, onOpenLimits }: { profile: ReviewSessionDraft; model: string; speed: number; onOpenLimits: () => void; onOpenEvidence?: () => void }) {
  const { t, locale } = useI18n();
  const { notify, dismissNotice } = useNotifications();
  const [closed, setClosed] = useState(false);
  const openLimits = useRef(onOpenLimits);
  openLimits.current = onOpenLimits;
  const current = profile.prompt_policy.workflow_budget;
  const suggestion = suggestLocalLimits(current, speed);
  const changed = Boolean(suggestion && (suggestion.budget.max_wall_clock_s !== current.max_wall_clock_s || suggestion.budget.max_output_tokens !== current.max_output_tokens));
  const summary = t("{model} on CPU · {speed} tok/s (threshold {threshold} tok/s)", { model, speed: speed.toLocaleString(locale, { maximumFractionDigits: 1 }), threshold: SLOW_LOCAL_CPU_TOKENS_PER_SECOND });
  const estimate = suggestion ? " · " + t("Output {tokens} tokens ≈ {seconds} s · limit {limit} s", { tokens: current.max_output_tokens, seconds: Math.ceil(suggestion.estimatedSeconds), limit: current.max_wall_clock_s }) : "";
  const message = summary + estimate;
  useEffect(() => {
    if (closed) return;
    notify(message, "warning", SLOW_CPU_NOTICE_KEY, 0, { event: "slow-cpu-notice", actionLabel: changed ? "Review recommended limits in settings" : "Run limits", onAction: () => openLimits.current(), onDismiss: () => setClosed(true) });
  }, [message, changed, closed, notify]);
  useEffect(() => () => dismissNotice(SLOW_CPU_NOTICE_KEY), [dismissNotice]);
  return null;
}
