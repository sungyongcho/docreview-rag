"use client";

import { ArrowUpRight } from "lucide-react";
import { createContext, useContext, type ReactNode } from "react";
import { useI18n } from "@/lib/i18n";
import { DEV_ONLY_REASONS, SOURCE_REPOSITORY_LABEL, SOURCE_REPOSITORY_URL, type DevOnlyReason } from "@/lib/dev-mode";
import { HoverBubble } from "./hover-bubble";

/** True on a public surface, where a locked control should point at the repository instead of DEV settings. */
const DevPromotionContext = createContext(false);
export function DevPromotionProvider({ promote, children }: { promote: boolean; children: ReactNode }) {
  return <DevPromotionContext.Provider value={promote}>{children}</DevPromotionContext.Provider>;
}
export function useDevPromotion() { return useContext(DevPromotionContext); }

/** Hover copy for a DEV-only control: the reason, and on a public surface the invitation to run DEV mode. */
export function DevModeBubble({ reason, children, inline = false, placement }: { reason?: DevOnlyReason | string; children: ReactNode; inline?: boolean; placement?: "above" | "below" }) {
  const { t } = useI18n();
  const promote = useDevPromotion();
  const text = reason ? (reason in DEV_ONLY_REASONS ? DEV_ONLY_REASONS[reason as DevOnlyReason] : reason) : null;
  // Nothing to say on a DEV surface without a reason: keep the child bare instead of an empty bubble.
  if (!promote && !text) return <>{children}</>;
  return <HoverBubble pinnable={Boolean(text)} label={t("DEV only")} inline={inline} placement={placement} bubble={<div className="dev-bubble-content">
    {promote && <strong>{t(text ? "Not available on this website." : "Try 'DEV MODE' now!")}</strong>}
    {text && <p>{t(text)}</p>}
    {promote && <a className="dev-bubble-link" href={SOURCE_REPOSITORY_URL} target="_blank" rel="noreferrer">{text ? t("Open DEV project") : SOURCE_REPOSITORY_LABEL}<ArrowUpRight size={14} aria-hidden="true" /></a>}
  </div>}>{children}</HoverBubble>;
}
