"use client";
import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";

import { useI18n } from "@/lib/i18n";

interface UnsavedGoldenDialogProps {
  /** The navigation waiting on the answer; a new one re-arms the focus trap like the first. */
  leaveAction: () => void;
  busy: boolean;
  canSave: boolean;
  onContinueEditing: () => void;
  onDiscard: () => void;
  onSave: () => void;
}

/**
 * Ask whether to keep editing, discard, or save an unsaved golden question before leaving it.
 *
 * Everything outside the dialog is made inert and Tab cycles through its buttons, so the choice
 * cannot be skipped by clicking or tabbing past it.
 */
export function UnsavedGoldenDialog({ leaveAction, busy, canSave, onContinueEditing, onDiscard, onSave }: UnsavedGoldenDialogProps) {
  const { t } = useI18n();
  const leaveDialog = useRef<HTMLElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const overlay = leaveDialog.current?.parentElement;
    const background = [...document.body.children].filter(element => element !== overlay);
    const before = background.map(element => element.hasAttribute("inert"));
    background.forEach(element => element.setAttribute("inert", ""));
    function keys(event: KeyboardEvent) {
      if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); onContinueEditing(); }
      if (event.key === "Tab") {
        const buttons = [...(leaveDialog.current?.querySelectorAll<HTMLButtonElement>("button:not(:disabled)") ?? [])];
        if (event.shiftKey && document.activeElement === buttons[0]) { event.preventDefault(); buttons.at(-1)?.focus(); }
        else if (!event.shiftKey && document.activeElement === buttons.at(-1)) { event.preventDefault(); buttons[0]?.focus(); }
      }
    }
    document.addEventListener("keydown", keys, true);
    return () => { document.removeEventListener("keydown", keys, true); background.forEach((element, i) => { if (!before[i]) element.removeAttribute("inert"); }); previous?.focus({ preventScroll: true }); };
  }, [leaveAction]);
  return createPortal(<div className="golden-leave-backdrop"><section ref={leaveDialog} role="dialog" aria-modal="true" aria-label={t("Unsaved question changes")} className="golden-leave-dialog"><h2>{t("Unsaved question changes")}</h2><p>{t("Save this draft before leaving?")}</p><div className="action-row"><button autoFocus type="button" className="button" onClick={onContinueEditing}>{t("Continue editing")}</button><button type="button" className="button" disabled={busy} onClick={onDiscard}>{t("Discard and leave")}</button><button type="button" className="button primary" disabled={busy || !canSave} onClick={onSave}>{t("Save draft and leave")}</button></div></section></div>, document.body);
}
