"use client";

import { useEffect, useState, type ReactNode } from "react";

/** Mount a panel on its first visit and preserve its local state when navigating away. */
export function RetainedPanel({ active, className, workspace, children }: { active: boolean; className?: string; workspace?: string; children: ReactNode }) {
  const [visited, setVisited] = useState(active);
  useEffect(() => { if (active) setVisited(true); }, [active]);
  return active || visited ? <div className={className} data-workspace={workspace} hidden={!active}>{children}</div> : null;
}
