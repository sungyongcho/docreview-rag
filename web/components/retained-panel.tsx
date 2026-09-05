"use client";

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

const RetainedPanelActivity = createContext(true);

/** Portals and document-level handlers must also respect hidden ancestor panels. */
export function useRetainedPanelActive() {
  return useContext(RetainedPanelActivity);
}

/** Mount a panel on its first visit and preserve its local state when navigating away. */
export function RetainedPanel({ active, className, workspace, children }: { active: boolean; className?: string; workspace?: string; children: ReactNode }) {
  const parentActive = useRetainedPanelActive();
  const visible = parentActive && active;
  const [visited, setVisited] = useState(visible);
  useEffect(() => { if (visible) setVisited(true); }, [visible]);
  return visible || visited ? <RetainedPanelActivity.Provider value={visible}><div className={className} data-workspace={workspace} hidden={!visible}>{children}</div></RetainedPanelActivity.Provider> : null;
}
