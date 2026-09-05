"use client";
import { useI18n } from "@/lib/i18n";


import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";

type Tone = "info" | "success" | "warning" | "error";
interface Notice { id: string; key: string; tone: Tone; message: string; duration: number; }
interface Notifications { notify: (message: string, tone?: Tone, key?: string) => void; }

const Context = createContext<Notifications>({ notify: () => undefined });

export function NotificationProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<Notice[]>([]);
  const notify = useCallback((message: string, tone: Tone = "info", key = message) => {
    const id = crypto.randomUUID();
    const duration = tone === "info" || tone === "success" ? 5000 : 8000;
    setItems((current) => [...current.filter((item) => item.key !== key), { id, key, tone, message, duration }].slice(-3));
  }, []);
  const value = useMemo(() => ({ notify }), [notify]);
  const dismiss = useCallback((id: string) => setItems((current) => current.filter((entry) => entry.id !== id)), []);
  return <Context.Provider value={value}>{children}<div className="notification-stack" aria-live="polite">{items.map((item) => <NotificationCard key={item.id} item={item} onDismiss={dismiss} />)}</div></Context.Provider>;
}

export function useNotifications(): Notifications {
  return useContext(Context);
}

function NotificationCard({ item, onDismiss }: { item: Notice; onDismiss: (id: string) => void }) {
  const { t, locale } = useI18n();
  const remaining = useRef(item.duration);
  const started = useRef(Date.now());
  const timer = useRef<number | null>(null);
  function resume() { started.current = Date.now(); timer.current = window.setTimeout(() => onDismiss(item.id), remaining.current); }
  function pause() { if (timer.current !== null) window.clearTimeout(timer.current); remaining.current = Math.max(0, remaining.current - (Date.now() - started.current)); }
  useEffect(() => { resume(); return pause; }, [item.id]);
  return <div className={`notification ${item.tone}`} role={item.tone === "error" || item.tone === "warning" ? "alert" : "status"} onMouseEnter={pause} onMouseLeave={resume} onFocus={pause} onBlur={resume}><span>{item.message}</span><button type="button" aria-label={t("Dismiss notification")} onClick={() => onDismiss(item.id)}>×</button></div>;
}
