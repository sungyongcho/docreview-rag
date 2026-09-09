"use client";

import { useId, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import "./hover-bubble.css";

const BUBBLE_WIDTH = 280;

/** A speech bubble that follows the pointer or keyboard focus over its child and leaves with it.
 *
 * The bubble is portaled to the document body and positioned from the trigger's viewport rectangle,
 * so sidebars, dialogs and scroll panes with clipped overflow never cut it off.
 */
export function HoverBubble({ bubble, children, inline = false }: { bubble: ReactNode; children: ReactNode; inline?: boolean; placement?: "above" | "below" }) {
  const [open, setOpen] = useState(false);
  const [style, setStyle] = useState<{ left: number; top?: number; bottom?: number; placement: "above" | "below" } | null>(null);
  const wrap = useRef<HTMLDivElement>(null);
  const id = useId();
  useLayoutEffect(() => {
    if (!open || !wrap.current) { setStyle(null); return; }
    const rect = wrap.current.getBoundingClientRect();
    const left = Math.max(8, Math.min(rect.left, window.innerWidth - BUBBLE_WIDTH - 8));
    // Prefer above; fall back below when the trigger sits near the top of the viewport.
    if (rect.top > 160) setStyle({ left, bottom: window.innerHeight - rect.top + 10, placement: "above" });
    else setStyle({ left, top: rect.bottom + 10, placement: "below" });
  }, [open]);
  return <div ref={wrap} className={`hover-bubble-wrap${inline ? " is-inline" : ""}`} onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)} onFocus={() => setOpen(true)} onBlur={() => setOpen(false)} aria-describedby={open ? id : undefined}>
    {children}
    {open && style && typeof document !== "undefined" && createPortal(<div id={id} className="hover-bubble" data-placement={style.placement} role="tooltip" style={{ left: style.left, top: style.top, bottom: style.bottom }}>{bubble}</div>, document.body)}
  </div>;
}
