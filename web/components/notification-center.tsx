"use client";

import { ArrowUpRight, Bell, Check, CheckCheck, Trash2, X } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { useI18n } from "@/lib/i18n";
import type { NotificationEntry } from "@/lib/notification-store";
import type { NotificationTarget } from "@/lib/notification-registry";
import { relativeTime } from "@/lib/time-labels";
import { useNotificationCenter } from "./notifications";
import { SEARCH_UPDATE_KINDS, searchUpdateProgress } from "./search-update-status";
import type { OperatorJob } from "@/lib/types";
import { NotificationIcon } from "./notification-icon";

const CAUSES: Record<string, string> = { missing_file: "The corpus manifest file is missing.", invalid_json: "The corpus manifest is not valid JSON.", invalid_manifest: "The corpus manifest does not satisfy its data contract.", schema_mismatch: "The database schema does not match this release." };

/** A history panel collapses without discarding entries and activates only typed app destinations. */
export function NotificationCenter({ onNavigate, developer = false, blocked = false, jobs = [], jobsStale = false }: { jobs?: OperatorJob[]; jobsStale?: boolean; onNavigate: (target: NotificationTarget) => void; developer?: boolean; blocked?: boolean }) {
  const { t, locale } = useI18n();
  const { entries, markRead, remove, setPanelOpen, bindNavigation, modalActive } = useNotificationCenter();
  const [open, setOpen] = useState(false);
  const [pastOpen, setPastOpen] = useState(false);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [filter, setFilter] = useState<"all" | "jobs" | "errors">("all");
  const root = useRef<HTMLDivElement>(null);const bell = useRef<HTMLButtonElement>(null);const panel = useRef<HTMLDivElement>(null);const id = useId();
  const liveJobs = jobs.filter(job => SEARCH_UPDATE_KINDS.has(job.kind) && ["running", "queued"].includes(job.status) && !entries.some(entry => entry.jobId === job.job_id));
  const unread = entries.filter(entry => !entry.readAt).length;
  const matches = (entry: NotificationEntry) => filter === "all" || (filter === "jobs" ? Boolean(entry.jobId) : entry.kind === "error");
  const ordered = [...entries].reverse().filter(matches);
  const fresh = ordered.filter(entry => !entry.readAt);
  const past = ordered.filter(entry => Boolean(entry.readAt));
  useEffect(() => { if (blocked || modalActive) setOpen(false); }, [blocked, modalActive]);
  useEffect(() => bindNavigation(onNavigate), [bindNavigation, onNavigate]);
  useEffect(() => { setPanelOpen(open);return () => setPanelOpen(false); }, [open, setPanelOpen]);
  useEffect(() => {
    if (!open) return;
    panel.current?.focus();
    const outside = (event: PointerEvent) => { if (!root.current?.contains(event.target as Node)) setOpen(false); };
    document.addEventListener("pointerdown", outside);return () => document.removeEventListener("pointerdown", outside);
  }, [open]);
  /** Read and navigate are one click; an entry without a target only changes its read state. */
  function activate(entry: NotificationEntry) {
    markRead(entry.id);if (entry.target) onNavigate(entry.target);setOpen(false);bell.current?.focus();
  }
  function renderEntry(entry: NotificationEntry) {
    const liveJob = jobs.find(job => job.job_id === entry.jobId && SEARCH_UPDATE_KINDS.has(job.kind) && ["queued", "running"].includes(job.status));
    const long = entry.body.length > 240;
    return <li className={`notification-history-entry ${entry.kind}${entry.readAt ? " read" : ""}`} key={entry.id}>
      <button type="button" className="notification-entry-open" onClick={() => activate(entry)}><NotificationIcon kind={entry.kind} /><span>
        <span className="notification-entry-head"><strong>{t(entry.title)}{entry.count > 1 && <span className="notification-repeat"> ×{entry.count}</span>}</strong><time dateTime={entry.updatedAt} title={new Date(entry.updatedAt).toLocaleString(locale)}>{relativeTime(entry.updatedAt, locale)}</time></span>
        <span className={`notification-history-body${long && !expanded[entry.id] ? " notification-body-collapsed" : ""}`}>{entry.body}</span>
        {liveJob && <span className="notification-job-progress">{jobsStale ? t("Checking current job progress…") : searchUpdateProgress(liveJob, t)}</span>}
      </span></button>
      {long && <button type="button" className="notification-expand" aria-expanded={Boolean(expanded[entry.id])} onClick={() => setExpanded(current => ({ ...current, [entry.id]: !current[entry.id] }))}>{t(expanded[entry.id] ? "Collapse notification" : "Expand notification")}</button>}
      {developer && entry.detail && <details className="notification-detail"><summary>{t(entry.kind === "error" ? "Technical details" : "Notification details")}</summary>{entry.detail.cause && <p>{t("Cause")}: {t(CAUSES[entry.detail.cause] ?? entry.detail.cause)}</p>}{entry.detail.path && <p>{t("Path")}: <code>{entry.detail.path}</code></p>}{entry.detail.text && <pre>{entry.detail.text}</pre>}</details>}
      <div className="notification-entry-actions">
        {entry.target && <button type="button" className="icon-button" title={t("Open")} aria-label={t("Open notification: {title}", { title: t(entry.title) })} onClick={() => activate(entry)}><ArrowUpRight size={15} aria-hidden="true" /></button>}
        {!entry.readAt && <button type="button" className="icon-button" title={t("Mark read")} onClick={() => { markRead(entry.id);panel.current?.focus(); }}><Check size={15} aria-hidden="true" /><span>{t("Mark read")}</span></button>}
        <button type="button" className="icon-button" title={t("Delete")} aria-label={t("Delete notification: {title}", { title: t(entry.title) })} onClick={() => { remove(entry.id);panel.current?.focus(); }}><Trash2 size={15} aria-hidden="true" /><span>{t("Delete")}</span></button>
      </div>
    </li>;
  }
  return <div className="notification-center" ref={root}>
    <button ref={bell} type="button" className="icon-button notification-bell" disabled={blocked || modalActive} aria-label={t("Notifications · {count} unread", { count: unread })} aria-expanded={open} aria-controls={open ? id : undefined} onClick={() => setOpen(current => !current)}><Bell size={18} aria-hidden="true" />{unread > 0 && <span className="notification-unread-badge" aria-hidden="true">{unread > 99 ? "99+" : unread}</span>}</button>
    {open && <div id={id} ref={panel} className="notification-center-panel surface" role="dialog" aria-modal="false" aria-label={t("Notification center")} tabIndex={-1} onKeyDown={event => {
      if (event.key === "Escape") { event.preventDefault();event.stopPropagation();setOpen(false);bell.current?.focus(); }
      if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
      const buttons = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>(".notification-entry-open")).filter(button => button.offsetParent !== null || !button.closest("details") || button.closest("details")?.hasAttribute("open"));
      if (!buttons.length) return;event.preventDefault();
      const focused = document.activeElement?.closest(".notification-history-entry")?.querySelector<HTMLButtonElement>(".notification-entry-open") ?? document.activeElement;
      const current = buttons.indexOf(focused as HTMLButtonElement);
      const index = event.key === "Home" ? 0 : event.key === "End" ? buttons.length - 1 : current < 0 ? event.key === "ArrowUp" ? buttons.length - 1 : 0 : (current + (event.key === "ArrowUp" ? -1 : 1) + buttons.length) % buttons.length;
      buttons[index].focus();
    }}>
      <header className="surface-heading notification-center-heading"><div><h2>{t("Notifications")}</h2><p className="helper">{unread ? t("{count} unread", { count: unread }) : t("All caught up")}</p></div>
        <div className="notification-center-controls"><button type="button" className="button ghost" disabled={!unread} onClick={() => markRead(null)}><CheckCheck size={15} aria-hidden="true" />{t("Mark all read")}</button><button type="button" className="button ghost" disabled={!entries.length} onClick={() => remove(null)}><Trash2 size={15} aria-hidden="true" />{t("Clear all notifications")}</button><button type="button" className="icon-button" aria-label={t("Close notification center")} onClick={() => { setOpen(false);bell.current?.focus(); }}><X size={17} aria-hidden="true" /></button></div>
      </header>
      <nav className="lab-tabs workflow-tabs measure-tab-strip notification-center-filters" aria-label={t("Notification filters")}><div className="measure-tab-group" role="group" aria-label={t("Notification filters")}>{(["all", "jobs", "errors"] as const).map(value => <button key={value} type="button" aria-pressed={filter === value} onClick={() => setFilter(value)}>{t(value === "all" ? "All" : value === "jobs" ? "Jobs" : "Errors")}</button>)}</div></nav>
      <div className="notification-center-body">
      {filter !== "errors" && liveJobs.length > 0 && <section className="notification-section" aria-label={t("In progress")}><h3>{t("In progress")}</h3><ul className="notification-history">{liveJobs.map(job => <li className="notification-history-entry job live" key={job.job_id}><button type="button" className="notification-entry-open" onClick={() => { onNavigate({ view: "build", tab: "jobs", jobId: job.job_id }); setOpen(false); }}><NotificationIcon kind="job" /><span><span className="notification-entry-head"><strong>{t(job.status === "queued" ? "Job queued" : "Job running")}</strong><span className={`job-status ${job.status}`}>{t(job.status)}</span></span><span className="notification-history-body">{jobsStale ? t("Checking current job progress…") : searchUpdateProgress(job, t)}</span></span></button></li>)}</ul></section>}
      <section className="notification-section" aria-label={t("New notifications")}><h3>{t("New notifications")}</h3>
        {fresh.length ? <ul className="notification-history">{fresh.map(renderEntry)}</ul> : <p className="notification-empty">{t(past.length || liveJobs.length ? "Nothing new." : "No notifications here.")}</p>}
      </section>
      {past.length > 0 && <details className="notification-section notification-past" open={pastOpen} onToggle={event => setPastOpen(event.currentTarget.open)}><summary><h3>{t("Past notifications · {count}", { count: past.length })}</h3></summary><ul className="notification-history">{past.map(renderEntry)}</ul></details>}
      </div>
    </div>}
  </div>;
}
