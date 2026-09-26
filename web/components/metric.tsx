import type { ReactNode } from "react";

/** A labelled value; the `setting` variant keeps the compact settings-panel styling. */
export function Metric({ icon, label, value, variant }: { icon?: ReactNode; label: string; value: string; variant?: "setting" }) {
  return <div className={variant === "setting" ? "setting-metric" : "metric"}><span>{icon}{label}</span><strong>{value}</strong></div>;
}
