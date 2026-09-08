"use client";

import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { previewSourceDeletion } from "@/lib/api";
import type { SourceDeletionPreview } from "@/lib/types";
import { useI18n } from "@/lib/i18n";
import { useRetainedPanelActive } from "./retained-panel";
import "./source-delete-dialog.css";

interface Props {
  documentIds: string[];
  disabled: boolean;
  onConfirm?: (token: string) => Promise<void>;
  onOpenJobs?: () => void;
}

/** Preview exact originals before queuing deletion, independently of the selected draft. */
export function SourceDeleteDialog({ documentIds, disabled, onConfirm, onOpenJobs }: Props) {
  const { t, locale } = useI18n();
  const active = useRetainedPanelActive();
  const titleId = useId();
  const warningId = useId();
  const trigger = useRef<HTMLButtonElement>(null);
  const dialog = useRef<HTMLElement>(null);
  const requestVersion = useRef(0);
  const submitting = useRef(false);
  const [open, setOpen] = useState(false);
  const [preview, setPreview] = useState<SourceDeletionPreview | null>(null);
  const [phase, setPhase] = useState<"preview" | "confirm" | null>(null);
  const [error, setError] = useState("");
  const [queued, setQueued] = useState(false);
  const visible = open && active;

  /** Discard a pending preview when cancelling; no mutation has been requested. */
  function close() {
    if (submitting.current) return;
    requestVersion.current += 1;
    setOpen(false); setPreview(null); setPhase(null); setError(""); setQueued(false);
  }

  useEffect(() => {
    if (!visible) return;
    dialog.current?.focus();
    return () => { if (!trigger.current?.closest("[hidden], [inert]") && !trigger.current?.disabled) trigger.current?.focus(); };
  }, [visible]);
  useEffect(() => {
    if (!visible) return;
    /** Keep keyboard focus inside the active portal and allow cancellation before confirmation. */
    function key(event: KeyboardEvent) {
      if (event.key === "Escape" && !submitting.current) { event.preventDefault(); close(); }
      if (event.key !== "Tab" || !dialog.current) return;
      const controls = [...dialog.current.querySelectorAll<HTMLElement>('button:not([disabled]), a[href]')];
      const first = controls[0], last = controls.at(-1);
      if (!controls.includes(document.activeElement as HTMLElement)) { event.preventDefault(); (event.shiftKey ? last : first)?.focus(); }
      else if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
      if (!controls.length) { event.preventDefault(); dialog.current.focus(); }
    }
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [visible]);
  useEffect(() => {
    if (!preview) return;
    const timer = window.setTimeout(() => {
      setPreview(null);
      setError(t("The deletion preview expired. Review a new preview before confirming."));
    }, Math.max(0, preview.expires_at * 1000 - Date.now()));
    return () => window.clearTimeout(timer);
  }, [preview, t]);
  useEffect(() => () => { requestVersion.current += 1; }, []);

  /** Ask the server for a read-only preview of the current exact on-disk document IDs. */
  async function inspect() {
    if (disabled || !documentIds.length || phase || submitting.current) return;
    const version = ++requestVersion.current;
    setOpen(true); setPhase("preview"); setError(""); setPreview(null); setQueued(false);
    try {
      const result = await previewSourceDeletion([...new Set(documentIds)]);
      if (requestVersion.current === version) setPreview(result);
    } catch (reason) {
      if (requestVersion.current === version) setError(reason instanceof Error ? reason.message : String(reason));
    } finally { if (requestVersion.current === version) setPhase(null); }
  }

  /** Submit only the reviewed unexpired token and leave inventory changes to the terminal job refresh. */
  async function confirm() {
    if (disabled || !onConfirm || !preview || phase || submitting.current || preview.expires_at * 1000 <= Date.now()) return;
    const token = preview.token;
    submitting.current = true;
    setPhase("confirm"); setPreview(null); setError("");
    try { await onConfirm(token); setQueued(true); }
    catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { submitting.current = false; setPhase(null); }
  }

  return <>
    <button ref={trigger} className="button danger-button" type="button" disabled={disabled || !documentIds.length || Boolean(phase)} aria-haspopup="dialog" aria-expanded={visible} onClick={() => void inspect()}>{t("Delete selected originals")}</button>
    {visible && createPortal(<div className="wipe-scrim"><section ref={dialog} tabIndex={-1} className="wipe-dialog source-delete-dialog" role="dialog" aria-modal="true" aria-labelledby={titleId} aria-describedby={warningId}>
      <header><h2 id={titleId}>{t("Delete selected originals?")}</h2></header>
      <p id={warningId} className="notice error">{t("Deleting originals removes acquired source files. Clearing a selection only deselects them. To use deleted originals again, download them again in Filings.")}</p>
      <p>{t("Database documents, chunks, embeddings, and past job inputs are preserved.")}</p>
      {phase && <p role="status">{t(phase === "preview" ? "Preparing deletion preview…" : "Queuing source deletion…")}</p>}
      {error && <p role="alert" className="notice error">{error}</p>}
      {preview && <>
        <h3>{t("Exact filing targets")}</h3>
        <ul className="source-delete-targets">{preview.documents.map((source) => <li key={source.document_id}><strong>{source.registry.toUpperCase()} · {source.issuer} FY{source.fiscal_year}</strong><span>{t("Filing ID")}: <code>{source.filing_id}</code></span><span>{t("Document ID")}: <code>{source.document_id}</code></span></li>)}</ul>
        <h3>{t("Exact source files")}</h3>
        <ul className="source-delete-targets">{preview.files.map((file) => <li key={file.path}><code>{file.path}</code><span>{t("{count} bytes", { count: file.byte_length.toLocaleString(locale) })} · <strong>{t(file.retained ? "Preserved shared or past input" : "Will be deleted")}</strong></span></li>)}</ul>
        {!preview.files.some((file) => !file.retained) && <p>{t("No physical files will be deleted. Only the selected acquisition records may be removed.")}</p>}
        <p>{t("Past job inputs preserved: {count}", { count: preview.retained_inputs })}</p>
        <p>{t("Nothing changes until you confirm. Cancel keeps the files and selection unchanged.")}</p>
      </>}
      {queued && <p role="status">{t("Source deletion queued. Files are not deleted yet; check Jobs for the result.")}</p>}
      <footer className="wipe-dialog-actions">
        <button className="button" type="button" disabled={phase === "confirm"} onClick={close}>{t(queued ? "Close" : "Cancel")}</button>
        {!preview && !phase && !queued && <button className="button" type="button" disabled={disabled || !documentIds.length} onClick={() => void inspect()}>{t("Review deletion preview")}</button>}
        {preview && <button className="button danger-button" type="button" disabled={disabled || Boolean(phase) || !preview.documents.length} onClick={() => void confirm()}>{t("Confirm deletion of originals")}</button>}
        {queued && onOpenJobs && <button className="button" type="button" onClick={() => { close(); onOpenJobs(); }}>{t("Open Jobs")}</button>}
      </footer>
    </section></div>, document.body)}
  </>;
}
