"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { closeSidePanel } from "./side-panel-motion";
import { X } from "lucide-react";
import { useI18n } from "@/lib/i18n";

/** Reuse the evaluation drawer shell for both public and operator snapshot details. */
export function SnapshotDetailDrawer({ children, onClose }: { children: ReactNode; onClose: () => void }) {
  const { t } = useI18n();
  const panel = useRef<HTMLElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    panel.current?.querySelector<HTMLButtonElement>("button")?.focus();
    return () => { document.body.style.overflow = overflow; previous?.focus(); };
  }, []);
  return createPortal(<div className="evaluation-setup-backdrop" onClick={event => { if (event.target === event.currentTarget) closeSidePanel(panel.current, onClose); }}><section ref={panel} role="dialog" aria-modal="true" aria-label={t("Snapshot details")} className="surface evaluation-setup snapshot-detail-drawer" onKeyDown={event => {
    if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); closeSidePanel(panel.current, onClose); }
    if (event.key !== "Tab") return;
    const controls = Array.from(panel.current?.querySelectorAll<HTMLElement>("button:not(:disabled), a[href], summary, input:not(:disabled), select:not(:disabled)") ?? []).filter(element => !element.closest("details:not([open])") || element.tagName === "SUMMARY");
    const first = controls[0]; const last = controls[controls.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
    if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
  }}><div className="surface-heading"><h2>{t("Snapshot details")}</h2><button className="button icon" aria-label={t("Close")} onClick={() => closeSidePanel(panel.current, onClose)}><X size={18} /></button></div><div className="form-stack evaluation-setup-body">{children}</div><div className="action-row evaluation-setup-footer"><button className="button" onClick={() => closeSidePanel(panel.current, onClose)}>{t("Close")}</button></div></section></div>, document.body);
}
