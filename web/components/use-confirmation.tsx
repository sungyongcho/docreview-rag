"use client";

import { useCallback, useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useI18n } from "@/lib/i18n";
import { useModalLifecycle } from "./use-modal-lifecycle";
import "./confirmation.css";

/** Optional button copy for a confirmation; defaults stay Cancel / Continue. */
interface ConfirmationLabels { confirm?: string; cancel?: string; danger?: boolean }

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
  const onModalKeyDown = useModalLifecycle(ref, { onDismiss: () => onAnswer(false) });
  return createPortal(<dialog ref={ref} onKeyDown={onModalKeyDown} tabIndex={-1} className="app-confirmation" aria-modal="true" aria-labelledby={titleId} aria-describedby={messageId} onCancel={event => { event.preventDefault(); onAnswer(false); }} onClick={event => event.stopPropagation()}><h2 id={titleId}>{t("Confirm action")}</h2><p id={messageId}>{t(message)}</p><div className="action-row"><button type="button" className="button" onClick={() => onAnswer(false)}>{t(labels?.cancel ?? "Cancel")}</button><button type="button" className={`button ${labels?.danger ? "danger-button" : "primary"}`} onClick={() => onAnswer(true)}>{t(labels?.confirm ?? "Continue")}</button></div></dialog>, document.body);
}
