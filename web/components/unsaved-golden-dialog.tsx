"use client";
import { useRef } from "react";
import { createPortal } from "react-dom";

import { useI18n } from "@/lib/i18n";
import { useModalLifecycle } from "./use-modal-lifecycle";

interface UnsavedGoldenDialogProps {
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
export function UnsavedGoldenDialog({ busy, canSave, onContinueEditing, onDiscard, onSave }: UnsavedGoldenDialogProps) {
  const { t } = useI18n();
  const leaveDialog = useRef<HTMLElement>(null);
  const onModalKeyDown = useModalLifecycle(leaveDialog, { onDismiss: onContinueEditing, inertBackground: true });
  return createPortal(<div className="golden-leave-backdrop"><section ref={leaveDialog} onKeyDown={onModalKeyDown} tabIndex={-1} role="dialog" aria-modal="true" aria-label={t("Unsaved question changes")} className="golden-leave-dialog"><h2>{t("Unsaved question changes")}</h2><p>{t("Save this draft before leaving?")}</p><div className="action-row"><button type="button" className="button" onClick={onContinueEditing}>{t("Continue editing")}</button><button type="button" className="button" disabled={busy} onClick={onDiscard}>{t("Discard and leave")}</button><button type="button" className="button primary" disabled={busy || !canSave} onClick={onSave}>{t("Save draft and leave")}</button></div></section></div>, document.body);
}
