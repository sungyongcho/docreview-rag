import { Wrench } from "lucide-react";
import "./development-badge.css";

/** Identify local development actions without changing their capability checks. */
export function DevelopmentBadge({ locale, compact = false }: { locale: "en" | "ko"; compact?: boolean }) {
  const label = locale === "ko" ? "개발 모드 전용" : "DEV only";
  return <span className="development-badge" title={label} aria-label={label}>
    <Wrench size={13} aria-hidden="true" /><span>{compact ? "DEV" : label}</span>
  </span>;
}
