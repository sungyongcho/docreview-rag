import { Wrench } from "lucide-react";
import { DEV_ONLY_NOTE, type DevOnlyReason } from "@/lib/dev-mode";
import { DevModeBubble } from "./dev-mode-bubble";
import "./development-badge.css";

/** Identify local development actions without changing their capability checks; hovering explains why. */
export function DevelopmentBadge({ locale, compact = false, reason, tooltip = true }: { locale: "en" | "ko"; compact?: boolean; reason?: DevOnlyReason | string; tooltip?: boolean }) {
  const label = locale === "ko" ? "개발 모드 전용" : "DEV only";
  const badge = <span className="development-badge" aria-label={label}>
    <Wrench size={13} aria-hidden="true" /><span>{compact ? "DEV" : label}</span>
  </span>;
  return tooltip ? <DevModeBubble inline reason={reason ?? DEV_ONLY_NOTE}>{badge}</DevModeBubble> : badge;
}
