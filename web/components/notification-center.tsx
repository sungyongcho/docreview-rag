"use client";

import { Bell, CheckCheck, Trash2, X } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { useI18n } from "@/lib/i18n";
import type { NotificationEntry } from "@/lib/notification-store";
import type { NotificationTarget } from "@/lib/notification-registry";
import { useNotificationCenter } from "./notifications";
import { NotificationIcon } from "./notification-icon";

/** A history panel collapses without discarding entries and activates only typed app destinations. */
export function NotificationCenter({ onNavigate, developer = false }: { onNavigate: (target: NotificationTarget) => void; developer?: boolean }) {
  const { t, locale } = useI18n();
  const { entries, markRead, remove, setPanelOpen, bindNavigation } = useNotificationCenter();
  const [open, setOpen] = useState(false);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [filter, setFilter] = useState<"all" | "jobs" | "errors">("all");
  const root = useRef<HTMLDivElement>(null);const bell = useRef<HTMLButtonElement>(null);const panel = useRef<HTMLDivElement>(null);const id = useId();
  const unread = entries.filter(entry => !entry.readAt).length;
  const visible = [...entries].reverse().filter(entry => filter === "all" || (filter === "jobs" ? Boolean(entry.jobId) : entry.kind === "error"));
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
  return <div className="notification-center" ref={root}>
    <button ref={bell} type="button" className="icon-button notification-bell" aria-label={t("Notifications · {count} unread", { count: unread })} aria-expanded={open} aria-controls={open ? id : undefined} onClick={() => setOpen(current => !current)}><Bell size={18} aria-hidden="true" />{unread > 0 && <span className="notification-unread-badge" aria-hidden="true">{unread > 99 ? "99+" : unread}</span>}</button>
    {open && <div id={id} ref={panel} className="notification-center-panel" role="dialog" aria-modal="false" aria-label={t("Notification center")} tabIndex={-1} onKeyDown={event => {
      if (event.key === "Escape") { event.preventDefault();event.stopPropagation();setOpen(false);bell.current?.focus(); }
      if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
      const buttons = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>(".notification-entry-open"));
      if (!buttons.length) return;event.preventDefault();
      const current = buttons.indexOf(document.activeElement as HTMLButtonElement);
      const index = event.key === "Home" ? 0 : event.key === "End" ? buttons.length - 1 : (current + (event.key === "ArrowUp" ? -1 : 1) + buttons.length) % buttons.length;
      buttons[index].focus();
    }}>
      <header><h2>{t("Notifications")}</h2><button type="button" className="icon-button" aria-label={t("Close notification center")} onClick={() => { setOpen(false);bell.current?.focus(); }}><X size={17} /></button></header>
      <div className="notification-center-controls"><button type="button" disabled={!unread} onClick={() => markRead(null)}><CheckCheck size={15} />{t("Mark all read")}</button><button type="button" disabled={!entries.length} onClick={() => remove(null)}><Trash2 size={15} />{t("Clear all notifications")}</button></div>
      <div className="notification-center-filters" aria-label={t("Notification filters")}>{(["all", "jobs", "errors"] as const).map(value => <button key={value} type="button" aria-pressed={filter === value} onClick={() => setFilter(value)}>{t(value === "all" ? "All" : value === "jobs" ? "Jobs" : "Errors")}</button>)}</div>
      <ul className="notification-history">{visible.map(entry => <li className={`notification-history-entry ${entry.kind}${entry.readAt ? " read" : " unread"}`} key={entry.id}>
        <button type="button" className="notification-entry-open" onClick={() => activate(entry)}><NotificationIcon kind={entry.kind} /><span><strong>{t(entry.title)}{entry.count > 1 && <span className="notification-repeat"> ×{entry.count}</span>}</strong><span className={`notification-history-body${entry.body.length > 240 && !expanded[entry.id] ? " notification-body-collapsed" : ""}`}>{entry.body}</span><time dateTime={entry.updatedAt}>{new Date(entry.updatedAt).toLocaleString(locale)}</time></span></button>
        {entry.body.length > 240 && <button type="button" className="notification-expand" aria-expanded={Boolean(expanded[entry.id])} onClick={() => setExpanded(current => ({ ...current, [entry.id]: !current[entry.id] }))}>{t(expanded[entry.id] ? "Collapse notification" : "Expand notification")}</button>}
        {developer && entry.detail && <details className="notification-detail"><summary>{t("Technical details")}</summary>{entry.detail.cause && <p>{t("Cause")}: {entry.detail.cause}</p>}{entry.detail.path && <p>{t("Manifest file")}: <code>{entry.detail.path}</code></p>}{entry.detail.text && <pre>{entry.detail.text}</pre>}{entry.detail.fix && <button type="button" onClick={() => { markRead(entry.id);onNavigate(entry.detail!.fix!);setOpen(false); }}>{t("Open fix action")}</button>}</details>}
        <div className="notification-entry-actions">{!entry.readAt && <button type="button" onClick={() => markRead(entry.id)}>{t("Mark read")}</button>}<button type="button" aria-label={t("Delete notification: {title}", { title: t(entry.title) })} onClick={() => remove(entry.id)}><Trash2 size={14} />{t("Delete")}</button></div>
      </li>)}</ul>
      {!visible.length && <p className="notification-empty">{t("No notifications here.")}</p>}
    </div>}
  </div>;
}
