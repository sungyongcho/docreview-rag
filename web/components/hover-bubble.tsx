"use client";

import { useId, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import "./hover-bubble.css";
import { useI18n } from "@/lib/i18n";

const BUBBLE_WIDTH = 280;

/** A speech bubble that follows the pointer or keyboard focus over its child and leaves with it.
 *
 * The bubble is portaled to the document body and positioned from the trigger's viewport rectangle,
 * so sidebars, dialogs and scroll panes with clipped overflow never cut it off.
 */
export function HoverBubble({ bubble, children, inline = false, pinnable = false, width = BUBBLE_WIDTH, label }: { bubble: ReactNode; children: ReactNode; inline?: boolean; pinnable?: boolean; width?: number; label?: string; placement?: "above" | "below" }) {
  const { t } = useI18n();
  const [pinned, setPinned] = useState(false);
  const dialog = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [style, setStyle] = useState<{ left: number; top?: number; bottom?: number; placement: "above" | "below" } | null>(null);
  const wrap = useRef<HTMLDivElement>(null);
  const id = useId();
  useLayoutEffect(() => {
    if (!(open || pinned) || !wrap.current) { setStyle(null); return; }
    const rect = wrap.current.getBoundingClientRect();
    const left = Math.max(8, Math.min(rect.left, window.innerWidth - Math.min(width, window.innerWidth - 16) - 8));
    // Prefer above; fall back below when the trigger sits near the top of the viewport.
    if (rect.top > 160) setStyle({ left, bottom: window.innerHeight - rect.top + 10, placement: "above" });
    else setStyle({ left, top: rect.bottom + 10, placement: "below" });
  }, [open, pinned, width]);
  useEffect(() => {
    if (!pinnable || !(open || pinned)) return;
    const outside = (event: PointerEvent) => { if (!wrap.current?.contains(event.target as Node) && !dialog.current?.contains(event.target as Node)) { setPinned(false); setOpen(false); } };
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") { setPinned(false); setOpen(false); } };
    document.addEventListener("pointerdown", outside); document.addEventListener("keydown", escape);
    return () => { document.removeEventListener("pointerdown", outside); document.removeEventListener("keydown", escape); };
  }, [open, pinned, pinnable]);
  return <div ref={wrap} className={`hover-bubble-wrap${inline ? " is-inline" : ""}`} onClick={pinnable ? (event) => { if (wrap.current?.contains(event.target as Node)) { if (pinned) setOpen(false); setPinned((value) => !value); } } : undefined} onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)} onFocus={() => setOpen(true)} onBlur={() => setOpen(false)} aria-describedby={open || pinned ? id : undefined}>
    {children}
    {(open || pinned) && style && typeof document !== "undefined" && createPortal(<div ref={dialog} id={id} className="hover-bubble" data-placement={style.placement} role={pinned ? "dialog" : "tooltip"} aria-label={label} style={{ width: Math.min(width, window.innerWidth - 16), left: style.left, top: style.top, bottom: style.bottom }}>{pinnable && <button type="button" className="button ghost" aria-label={t("Close")} onClick={(event) => { event.stopPropagation(); setPinned(false); setOpen(false); }}>{t("Close")}</button>}{bubble}</div>, document.body)}
  </div>;
}
