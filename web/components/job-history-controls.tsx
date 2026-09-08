"use client";
import { NotificationOutlet, useNotificationSurface } from "./notifications";

import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { getJobHistorySummary, jobHistoryBackupUrl, manageJobHistory } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useRetainedPanelActive } from "./retained-panel";

/** Manage terminal job records without changing their data products or active jobs. */
export function JobHistoryControls({ onChanged }: { onChanged: () => void }) {
  const { t } = useI18n();
  const active = useRetainedPanelActive();
  const titleId = useId();
  const trigger = useRef<HTMLButtonElement>(null);
  const dialog = useRef<HTMLElement>(null);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [summary, setSummary] = useState<Awaited<ReturnType<typeof getJobHistorySummary>> | null>(null);
  const [error, setError] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [backup, setBackup] = useState<string | null>(null);
  const [changed, setChanged] = useState<number | null>(null);
  const visible = open && active;
  useNotificationSurface("build-jobs", visible);
  const terminalCount = summary ? summary.visible + summary.archived : 0;

  useEffect(() => {
    if (!visible) return;
    dialog.current?.focus();
    return () => { if (!trigger.current?.closest("[hidden], [inert]")) trigger.current?.focus(); };
  }, [visible]);
  useEffect(() => {
    if (!visible) return;
    function key(event: KeyboardEvent) {
      if (event.key === "Escape" && !busy) { event.preventDefault(); setOpen(false); setConfirmation(""); }
      if (event.key !== "Tab" || !dialog.current) return;
      const controls = [...dialog.current.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled]), a[href]')];
      const first = controls[0], last = controls.at(-1);
      if (!controls.includes(document.activeElement as HTMLElement)) { event.preventDefault(); (event.shiftKey ? last : first)?.focus(); }
      else if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
      if (!controls.length) { event.preventDefault(); dialog.current.focus(); }
    }
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [visible, busy]);

  async function sync(notify = true) {
    setBusy(true); setError(""); setSummary(null); setConfirmation("");
    try { setSummary(await getJobHistorySummary()); if (notify) await onChanged(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { setBusy(false); }
  }
  async function manage(action: "archive" | "restore" | "delete") {
    if (busy || !summary) return;
    const count = action === "archive" ? summary.visible : action === "restore" ? summary.archived : terminalCount;
    if (!count || (action === "delete" && confirmation !== "DELETE JOB HISTORY")) return;
    setBusy(true); setError(""); setChanged(null);
    try {
      const result = await manageJobHistory({ action, expected_count: count, ...(action === "delete" ? { confirmation } : {}) });
      setSummary(result.summary); setChanged(result.changed_count); setConfirmation("");
      if (result.backup_id) setBackup(result.backup_id);
      try { await onChanged(); }
      catch (reason) { setError(`${t("History changed successfully, but the job list could not refresh.")} ${String(reason)}`); }
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); setSummary(null); setConfirmation(""); }
    finally { setBusy(false); }
  }

  return <>
    <button ref={trigger} className="button" type="button" aria-haspopup="dialog" aria-expanded={visible} onClick={() => { setOpen(true); void sync(false); }}>{t("Manage history")}</button>
    {visible && createPortal(<div className="wipe-scrim"><section ref={dialog} tabIndex={-1} className="wipe-dialog" role="dialog" aria-modal="true" aria-labelledby={titleId}>
      <header><h2 id={titleId}>{t("Manage job history")}</h2><button className="button" type="button" disabled={busy} onClick={() => { setOpen(false); setConfirmation(""); }}>{t("Close")}</button></header><NotificationOutlet priority={50} />
      <p>{t("Only finished job records are affected. Queued and running jobs, source files, embeddings, and evaluation results are preserved.")}</p>
      {busy && <p role="status">{t("Updating job history…")}</p>}
      {error && <p role="alert" className="notice error">{error}</p>}
      {summary && <p>{t("{visible} visible · {archived} archived · {active} active", { visible: summary.visible, archived: summary.archived, active: summary.active })}</p>}
      <div className="action-row">
        <button className="button" type="button" disabled={busy} onClick={() => void sync()}>{t("Sync history")}</button>
        <button className="button" type="button" disabled={busy || !summary?.visible} onClick={() => void manage("archive")}>{t("Archive finished jobs")}</button>
        <button className="button" type="button" disabled={busy || !summary?.archived} onClick={() => void manage("restore")}>{t("Restore archived jobs")}</button>
      </div>
      <p>{t("Archiving hides records from the job list. Restore makes them visible again.")}</p>
      <h3>{t("Permanently delete job history")}</h3>
      <p>{t("Delete {count} finished job records. A server backup is created before deletion.", { count: terminalCount })}</p>
      <label>{t("Type DELETE JOB HISTORY to confirm")}<input autoComplete="off" spellCheck={false} disabled={busy || !terminalCount} value={confirmation} onChange={(event) => setConfirmation(event.target.value)} /></label>
      <button className="button danger-button" type="button" disabled={busy || !terminalCount || confirmation !== "DELETE JOB HISTORY"} onClick={() => void manage("delete")}>{t("Delete job history")}</button>
      {changed !== null && <p role="status">{t("Updated {count} job records.", { count: changed })}</p>}
      {backup && <p><a className="button" href={jobHistoryBackupUrl(backup)} download>{t("Download job history backup")}</a></p>}
    </section></div>, document.body)}
  </>;
}
