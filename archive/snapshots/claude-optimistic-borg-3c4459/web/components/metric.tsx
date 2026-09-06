import type { ReactNode } from "react";

export function Metric({ icon, label, value }: { icon: ReactNode; label: string; value: string }) {
  return <div className="metric"><span>{icon}{label}</span><strong>{value}</strong></div>;
}
