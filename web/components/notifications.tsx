"use client";
import { useI18n } from "@/lib/i18n";
import { createContext, useCallback, useContext, useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from "react";

 type Tone = "info" | "success" | "warning" | "error";
interface Timing { remaining: number; runningSince: number | null; }
interface Notice { id: string; key: string; tone: Tone; message: string; duration: number; timing: Timing; }
interface Notifications { notify: (message: string, tone?: Tone, key?: string, duration?: number) => void; dismissNotice: (key: string) => void; }
interface OutletContext extends Notifications {
  items: Notice[];
  selected: string | null;
  register: (id: string, priority: number) => () => void;
  dismiss: (id: string) => void;
}
const Context = createContext<OutletContext>({ notify: () => undefined, dismissNotice: () => undefined, items: [], selected: null, register: () => () => undefined, dismiss: () => undefined });

/** Keep the original delivery API while displaying feedback in reserved layout space. */
export function NotificationProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<Notice[]>([]);
  const [outlets, setOutlets] = useState<Array<{ id: string; priority: number }>>([]);
  const notify = useCallback((message: string, tone: Tone = "info", key = message, requestedDuration?: number) => {
    const duration = requestedDuration ?? (tone === "info" || tone === "success" ? 5000 : 8000);
    setItems(current => {
      const existing = current.find(item => item.key === key);
      if (existing?.message === message && existing.tone === tone && existing.duration === duration) return current;
      const next = [...current.filter(item => item.key !== key), { id: existing?.id ?? crypto.randomUUID(), key, tone, message, duration, timing: { remaining: duration, runningSince: null } }];
      const persistent = next.filter(item => item.duration === 0).slice(-3);
      const slots = 3 - persistent.length;
      return [...persistent, ...(slots ? next.filter(item => item.duration !== 0).slice(-slots) : [])];
    });
  }, []);
  const dismissNotice = useCallback((key: string) => setItems(current => current.filter(item => item.key !== key)), []);
  const dismiss = useCallback((id: string) => setItems(current => current.filter(item => item.id !== id)), []);
  const register = useCallback((id: string, priority: number) => {
    setOutlets(current => [...current.filter(item => item.id !== id), { id, priority }]);
    return () => setOutlets(current => current.filter(item => item.id !== id));
  }, []);
  const selected = [...outlets].sort((a, b) => a.priority - b.priority).at(-1)?.id ?? null;
  const value = useMemo(() => ({ notify, dismissNotice, dismiss, register, selected, items }), [notify, dismissNotice, dismiss, register, selected, items]);
  return <Context.Provider value={value}>{children}{!selected && items.length > 0 && <NotificationTray items={items} onDismiss={dismiss} />}</Context.Provider>;
}

export function useNotifications(): Notifications { return useContext(Context); }

/** A dialog or inspector can reserve its own feedback space without covering controls. */
export function NotificationOutlet({ priority = 0, active = true }: { priority?: number; active?: boolean }) {
  const id = useId();
  const { register, selected, items, dismiss } = useContext(Context);
  useEffect(() => active ? register(id, priority) : undefined, [active, id, priority, register]);
  return <div className="notification-outlet">{selected === id && items.length > 0 && <NotificationTray items={items} onDismiss={dismiss} />}</div>;
}

/** Bound the rail by the visual viewport as well as dynamic viewport units and safe areas. */
function NotificationTray({ items, onDismiss }: { items: Notice[]; onDismiss: (id: string) => void }) {
  const { t } = useI18n();
  const [viewportHeight, setViewportHeight] = useState<number | undefined>();
  useEffect(() => {
    const viewport = window.visualViewport;
    const measure = () => setViewportHeight(viewport?.height ?? window.innerHeight);
    measure(); viewport?.addEventListener("resize", measure); window.addEventListener("resize", measure);
    return () => { viewport?.removeEventListener("resize", measure); window.removeEventListener("resize", measure); };
  }, []);
  return <section className="notification-stack" aria-label={t("Notifications")} style={viewportHeight ? { maxHeight: Math.min(180, viewportHeight * 0.28) } : undefined}>
    {items.map(item => <NotificationCard key={item.id} item={item} onDismiss={onDismiss} />)}
  </section>;
}

/** Pause once for combined hover, focus and explicit expansion; preserve time across outlets. */
function NotificationCard({ item, onDismiss }: { item: Notice; onDismiss: (id: string) => void }) {
  const { t } = useI18n();
  const [expanded, setExpanded] = useState(false);
  const [truncated, setTruncated] = useState(false);
  const message = useRef<HTMLSpanElement>(null);
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
    timer.current = window.setTimeout(() => onDismiss(item.id), item.timing.remaining);
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
  return <div className={`notification ${item.tone}${expanded ? " is-expanded" : ""}`} role={item.tone === "error" || item.tone === "warning" ? "alert" : "status"}
    onMouseEnter={() => pause("hover")} onMouseLeave={() => resume("hover")} onFocus={() => pause("focus")} onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) resume("focus"); }}>
    <span ref={message} className="notification-message">{item.message}</span><div className="notification-actions">
      {(truncated || expanded) && <button type="button" aria-label={t(expanded ? "Collapse notification" : "Expand notification")} aria-expanded={expanded} onClick={() => { const next = !expanded; setExpanded(next); if (next) pause("expanded"); else resume("expanded"); }}>{expanded ? "−" : "+"}</button>}
      <button type="button" aria-label={t("Dismiss notification")} onClick={() => onDismiss(item.id)}>×</button>
    </div>
  </div>;
}
