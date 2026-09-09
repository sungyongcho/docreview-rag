"use client";

import { useCallback, useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useI18n } from "@/lib/i18n";
import "./confirmation.css";

/** Optional button copy for a confirmation; defaults stay Cancel / Continue. */
export interface ConfirmationLabels { confirm?: string; cancel?: string; danger?: boolean }

/** Resolve user consent inside the app; unmounting always cancels pending work. */
export function useConfirmation() {
  const [message, setMessage] = useState<{ text: string; labels?: ConfirmationLabels } | null>(null);
  const pending = useRef<((approved: boolean) => void) | null>(null);
  const confirm = useCallback((text: string, labels?: ConfirmationLabels) => new Promise<boolean>(resolve => {
    if (pending.current) { resolve(false); return; }
    pending.current = resolve;
    setMessage({ text, labels });
  }), []);
  const settle = useCallback((approved: boolean) => {
    const resolve = pending.current; pending.current = null; setMessage(null); resolve?.(approved);
  }, []);
  useEffect(() => () => { pending.current?.(false); pending.current = null; }, []);
  return { confirm, confirmationDialog: message === null ? null : <Confirmation message={message.text} labels={message.labels} onAnswer={settle} /> };
}

/** Modal HTML dialog retains focus, has safe cancellation, and matches the app theme. */
function Confirmation({ message, labels, onAnswer }: { message: string; labels?: ConfirmationLabels; onAnswer: (approved: boolean) => void }) {
  const { t } = useI18n();
  const titleId = useId(); const messageId = useId();
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    const previous = document.activeElement as HTMLElement | null;
    if (dialog?.showModal) dialog.showModal(); else dialog?.setAttribute("open", "");
    dialog?.querySelector<HTMLButtonElement>("button")?.focus();
    const key = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); event.stopImmediatePropagation(); onAnswer(false); }
      if (event.key === "Tab") {
        const buttons = dialog?.querySelectorAll<HTMLButtonElement>("button");
        if (!buttons?.length) return;
        if (event.shiftKey && document.activeElement === buttons[0]) { event.preventDefault(); buttons[buttons.length - 1].focus(); }
        else if (!event.shiftKey && document.activeElement === buttons[buttons.length - 1]) { event.preventDefault(); buttons[0].focus(); }
      }
    };
    window.addEventListener("keydown", key, true);
    return () => { window.removeEventListener("keydown", key, true); dialog?.close?.(); if (previous?.isConnected) previous.focus(); };
  }, [onAnswer]);
  return createPortal(<dialog ref={ref} className="app-confirmation" aria-modal="true" aria-labelledby={titleId} aria-describedby={messageId} onCancel={event => { event.preventDefault(); onAnswer(false); }} onClick={event => event.stopPropagation()}><h2 id={titleId}>{t("Confirm action")}</h2><p id={messageId}>{t(message)}</p><div className="action-row"><button type="button" className="button" onClick={() => onAnswer(false)}>{t(labels?.cancel ?? "Cancel")}</button><button type="button" className={`button ${labels?.danger ? "danger-button" : "primary"}`} onClick={() => onAnswer(true)}>{t(labels?.confirm ?? "Continue")}</button></div></dialog>, document.body);
}
