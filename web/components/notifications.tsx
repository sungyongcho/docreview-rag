"use client";
import { useI18n } from "@/lib/i18n";
import { createContext, useCallback, useContext, useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import { desktopJobNotificationsEnabled, subscribeStorageRestored } from "@/lib/storage";
import { appendNotification, loadNotifications, readNotification, saveNotifications, type NotificationEntry } from "@/lib/notification-store";
import { NOTIFICATION_EVENTS, type NotificationKind, type NotificationTarget, type NotifyOptions } from "@/lib/notification-registry";
import { NotificationIcon } from "./notification-icon";
import "./notification-center.css";
import "./notification-toasts.css";

type Tone = NotificationKind;
interface Timing { remaining: number; runningSince: number | null; }
interface Notice { actionLabel?: string; onAction?: () => void; id: string; key: string; tone: Tone; message: string; duration: number; timing: Timing; entryId?: string; surface?: string; }
interface Notifications {
  notify: (message: string, tone?: Tone | NotifyOptions, key?: string, duration?: number, options?: NotifyOptions) => void;
  dismissNotice: (key: string) => void;
}
interface OutletContext extends Notifications {
  items: Notice[];
  entries: NotificationEntry[];
  selected: string | null;
  register: (id: string, priority: number) => () => void;
  dismiss: (id: string) => void;
  expire: (id: string) => void;
  markRead: (id: string | null) => void;
  remove: (id: string | null) => void;
  setPanelOpen: (open: boolean) => void;
  registerSurface: (id: string, surface: string, modal?: boolean) => () => void;
  modalActive: boolean;
  bindNavigation: (navigate: (target: NotificationTarget) => void) => () => void;
}
const Context = createContext<OutletContext>({ notify: () => undefined, dismissNotice: () => undefined, items: [], entries: [], selected: null, register: () => () => undefined, dismiss: () => undefined, expire: () => undefined, markRead: () => undefined, remove: () => undefined, setPanelOpen: () => undefined, registerSurface: () => () => undefined, modalActive: false, bindNavigation: () => () => undefined });

/** One event source feeds durable history, the reserved banner outlet and optional desktop mirroring. */
export function NotificationProvider({ children }: { children: React.ReactNode }) {
  const { t } = useI18n();const translator = useRef(t);translator.current = t;
  const [items, setItems] = useState<Notice[]>([]);
  const [entries, setEntries] = useState<NotificationEntry[]>([]);
  const history = useRef<NotificationEntry[]>([]);
  const [outlets, setOutlets] = useState<Array<{ id: string; priority: number }>>([]);
  const [surfaces, setSurfaces] = useState<Array<{ id: string; surface: string; modal: boolean }>>([]);
  const [panelOpen, setPanelOpen] = useState(false);
  const navigator = useRef<((target: NotificationTarget) => void) | null>(null);
  const commitHistory = useCallback((next: NotificationEntry[]) => { history.current = next;setEntries(next);saveNotifications(next); }, []);
  useLayoutEffect(() => { const saved = loadNotifications();history.current = saved;setEntries(saved); }, []);
  useEffect(() => {
    const restore = () => { const saved = loadNotifications();history.current = saved;setEntries(saved); };
    const restored = subscribeStorageRestored(restore);
    const changed = (event: StorageEvent) => { if (event.key?.startsWith("docreview:notifications:")) restore(); };
    window.addEventListener("storage", changed);
    return () => { restored();window.removeEventListener("storage", changed); };
  }, []);
  const markRead = useCallback((id: string | null) => {
    commitHistory(readNotification(history.current, id, new Date().toISOString()));
    setItems(current => current.filter(item => id === null ? !item.entryId : item.entryId !== id));
  }, [commitHistory]);
  const remove = useCallback((id: string | null) => {
    commitHistory(id === null ? [] : history.current.filter(entry => entry.id !== id));
    setItems(current => current.filter(item => id === null ? !item.entryId : item.entryId !== id));
  }, [commitHistory]);
  const expire = useCallback((id: string) => setItems(current => current.filter(item => item.id !== id)), []);
  const dismissNotice = useCallback((key: string) => setItems(current => current.filter(item => item.key !== key)), []);
  const dismiss = useCallback((id: string) => {
    const entry = history.current.find(item => item.id === id);
    if (entry) markRead(entry.id);else expire(id);
  }, [markRead, expire]);
  const bindNavigation = useCallback((navigate: (target: NotificationTarget) => void) => {
    navigator.current = navigate;return () => { if (navigator.current === navigate) navigator.current = null; };
  }, []);
  const notify = useCallback((message: string, toneOrOptions: Tone | NotifyOptions = "info", suppliedKey?: string, requestedDuration?: number, extra?: NotifyOptions) => {
    const options = typeof toneOrOptions === "object" ? toneOrOptions : extra;
    const tone = options?.kind ?? (typeof toneOrOptions === "string" ? toneOrOptions : "info");
    const spec = options ? NOTIFICATION_EVENTS[options.event] : undefined;
    if (options && !spec) throw new Error("Unclassified notification event.");
    if (spec?.classification === "inline-replaced") return;
    const key = options?.key ?? suppliedKey ?? message;
    const duration = options?.duration ?? requestedDuration ?? (tone === "info" || tone === "success" || tone === "job" ? 5000 : 8000);
    const persist = options?.persist ?? spec?.classification === "persistent";
    const now = new Date().toISOString();
    const candidate: NotificationEntry = { id: crypto.randomUUID(), key, kind: tone, title: options?.title ?? spec?.title ?? "Notification", body: message, target: options?.target ?? spec?.target ?? undefined, detail: options?.detail, revision: options?.revision, jobId: options?.jobId, surface: options?.surface ?? spec?.surface ?? undefined, createdAt: now, updatedAt: now, count: 1 };
    let entry = candidate;
    if (persist) {
      const prior = history.current.findLast(item => item.key === key);
      if (prior && options?.revision !== undefined && prior.revision === candidate.revision) return;
      if (prior && options?.update && tone !== "error" && prior.body === message && prior.kind === tone && JSON.stringify(prior.target) === JSON.stringify(candidate.target) && JSON.stringify(prior.detail) === JSON.stringify(candidate.detail)) return;
      const next = appendNotification(history.current, candidate, options?.update);entry = next[next.length - 1];commitHistory(next);
    }
    if (options?.silent) return;
    setItems(current => {
      const existing = current.find(item => item.key === key);
      if (!persist && existing?.message === message && existing.tone === tone && existing.duration === duration) return current;
      const next = [...current.filter(item => item.key !== key && !options?.supersedes?.includes(item.key)), { id: persist ? entry.id : existing?.id ?? entry.id, key, tone, message, duration, timing: { remaining: duration, runningSince: null }, entryId: persist ? entry.id : undefined, surface: entry.surface, actionLabel: options?.actionLabel, onAction: options?.actionLabel && entry.target ? () => { navigator.current?.(entry.target!); } : undefined }];
      const pinned = next.filter(item => item.duration === 0).slice(-3);
      const slots = 3 - pinned.length;
      return [...pinned, ...(slots ? next.filter(item => item.duration !== 0).slice(-slots) : [])];
    });
    if (persist && options?.desktop && desktopJobNotificationsEnabled() && typeof Notification !== "undefined" && Notification.permission === "granted") {
      const mirror = new Notification(`DocReview · ${translator.current(entry.title)}`, { body: entry.body, tag: entry.key });
      mirror.onclick = () => { markRead(entry.id);if (entry.target) navigator.current?.(entry.target);window.focus();mirror.close(); };
    }
  }, [commitHistory, markRead]);
  const register = useCallback((id: string, priority: number) => {
    setOutlets(current => [...current.filter(item => item.id !== id), { id, priority }]);
    return () => setOutlets(current => current.filter(item => item.id !== id));
  }, []);
  const registerSurface = useCallback((id: string, surface: string, modal = false) => {
    setSurfaces(current => [...current.filter(item => item.id !== id), { id, surface, modal }]);
    return () => setSurfaces(current => current.filter(item => item.id !== id));
  }, []);
  const selected = [...outlets].sort((a, b) => a.priority - b.priority).at(-1)?.id ?? null;
  const modalActive = surfaces.some(surface => surface.modal);
  const visible = useMemo(() => panelOpen ? [] : items.filter(item => !item.surface || !surfaces.some(owner => owner.surface === item.surface)), [items, surfaces, panelOpen]);
  const value = useMemo(() => ({ notify, dismissNotice, dismiss, expire, markRead, remove, register, registerSurface, modalActive, bindNavigation, setPanelOpen, selected, items: visible, entries }), [notify, dismissNotice, dismiss, expire, markRead, remove, register, registerSurface, modalActive, bindNavigation, selected, visible, entries]);
  return <Context.Provider value={value}>{children}{!selected && visible.length > 0 && <NotificationTray items={visible} onDismiss={dismiss} onExpire={expire} placement="overlay" />}{panelOpen && <span className="visually-hidden" role="status" aria-live="polite">{entries.at(-1)?.body}</span>}</Context.Provider>;
}

export function useNotifications(): Notifications { return useContext(Context); }
/** Read history and actions from the active presentation's notification provider. */
export function useNotificationCenter() { return useContext(Context); }

/** Let an already-visible card or dialog own its event while preserving its notification history. */
export function useNotificationSurface(surface: string, active = true, modal = false): void {
  const id = useId();const { registerSurface } = useContext(Context);
  useEffect(() => active ? registerSurface(id, surface, modal) : undefined, [active, id, surface, modal, registerSurface]);
}

/** A dialog or inspector reserves feedback space without covering controls. */
export function NotificationOutlet({ priority = 0, active = true }: { priority?: number; active?: boolean }) {
  const id = useId();const { register, selected, items, dismiss, expire } = useContext(Context);
  useEffect(() => active ? register(id, priority) : undefined, [active, id, priority, register]);
  return <div className="notification-outlet">{selected === id && items.length > 0 && <NotificationTray items={items} onDismiss={dismiss} onExpire={expire} />}</div>;
}

/** Bound the rail by the visual viewport as well as dynamic viewport units and safe areas. */
function NotificationTray({ items, onDismiss, onExpire, placement = "inline" }: { items: Notice[]; onDismiss: (id: string) => void; onExpire: (id: string) => void; placement?: "overlay" | "inline" }) {
  const { t } = useI18n();
  const [viewportHeight, setViewportHeight] = useState<number | undefined>();
  useEffect(() => {
    const viewport = window.visualViewport;
    const measure = () => setViewportHeight(viewport?.height ?? window.innerHeight);
    measure(); viewport?.addEventListener("resize", measure); window.addEventListener("resize", measure);
    return () => { viewport?.removeEventListener("resize", measure); window.removeEventListener("resize", measure); };
  }, []);
  return <section className="notification-stack" data-placement={placement} aria-label={t("Notifications")} style={viewportHeight && placement === "inline" ? { maxHeight: Math.min(180, viewportHeight * 0.28) } : undefined}>
    {items.map(item => <NotificationCard key={item.id} item={item} onDismiss={onDismiss} onExpire={onExpire} />)}
  </section>;
}

/** Pause once for combined hover, focus and explicit expansion; preserve time across outlets. */
function NotificationCard({ item, onDismiss, onExpire }: { item: Notice; onDismiss: (id: string) => void; onExpire: (id: string) => void }) {
  const { t } = useI18n();
  const [expanded, setExpanded] = useState(false);
  const [truncated, setTruncated] = useState(false);
  const [leaving, setLeaving] = useState(false);
  const message = useRef<HTMLSpanElement>(null);
  /** Animate out only where motion is allowed; test runtimes and reduced-motion users get the immediate removal. */
  function leave(done: () => void) {
    const animate = typeof window.matchMedia === "function" && !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (!animate || leaving) { done(); return; }
    setLeaving(true); window.setTimeout(done, 160);
  }
  const pauses = useRef(new Set<string>());
  const timer = useRef<number | null>(null);
  /** Account for elapsed active time only when a timer was actually running. */
  function stop() {
    if (timer.current === null) return;
    window.clearTimeout(timer.current); timer.current = null;
    if (item.timing.runningSince !== null) item.timing.remaining = Math.max(0, item.timing.remaining - (Date.now() - item.timing.runningSince));
    item.timing.runningSince = null;
  }
  /** Resume only after every reason for keeping the current notice visible is gone. */
  function start() {
    if (item.duration === 0 || pauses.current.size || timer.current !== null) return;
    item.timing.runningSince = Date.now();
    timer.current = window.setTimeout(() => leave(() => onExpire(item.id)), item.timing.remaining);
  }
  function pause(reason: string) { pauses.current.add(reason); stop(); }
  function resume(reason: string) { pauses.current.delete(reason); start(); }
  useEffect(() => { start(); return stop; }, [item.id, item.timing]);
  useLayoutEffect(() => {
    const element = message.current; if (!element) return;
    const measure = () => { if (!expanded) setTruncated(element.scrollHeight > element.clientHeight + 1); };
    measure(); const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
    observer?.observe(element); return () => observer?.disconnect();
  }, [item.message, expanded]);
  return <div className={`notification ${item.tone}${expanded ? " is-expanded" : ""}`} data-leaving={leaving || undefined} role={item.tone === "error" || item.tone === "warning" ? "alert" : "status"}
    onMouseEnter={() => pause("hover")} onMouseLeave={() => resume("hover")} onFocus={() => pause("focus")} onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) resume("focus"); }}>
    <NotificationIcon kind={item.tone} /><span ref={message} className="notification-message">{item.message}</span><div className="notification-actions">
      {item.actionLabel && item.onAction && <button className="notification-recovery" type="button" onClick={item.onAction}>{t(item.actionLabel)} <span aria-hidden="true">→</span></button>}
      {(truncated || expanded) && <button type="button" aria-label={t(expanded ? "Collapse notification" : "Expand notification")} aria-expanded={expanded} onClick={() => { const next = !expanded; setExpanded(next); if (next) pause("expanded"); else resume("expanded"); }}>{expanded ? "−" : "+"}</button>}
      <button type="button" aria-label={t("Dismiss notification")} onClick={() => leave(() => onDismiss(item.id))}>×</button>
    </div>
  </div>;
}
