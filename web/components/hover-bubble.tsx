"use client";

import { useId, useEffect, useLayoutEffect, useRef, useState, type ReactNode, type CSSProperties } from "react";
import { X } from "lucide-react";
import { createPortal } from "react-dom";
import "./hover-bubble.css";
import { useI18n } from "@/lib/i18n";

const BUBBLE_WIDTH = 280;

/** A speech bubble that follows the pointer or keyboard focus over its child and leaves with it.
 *
 * The bubble is portaled to the document body and positioned from the trigger's viewport rectangle,
 * so sidebars, dialogs and scroll panes with clipped overflow never cut it off.
 */
export function HoverBubble({ bubble, children, inline = false, pinnable = false, showClose = true, width = BUBBLE_WIDTH, label, align = "start", placement }: { bubble: ReactNode; children: ReactNode; inline?: boolean; pinnable?: boolean; showClose?: boolean; width?: number; label?: string; align?: "start" | "end"; placement?: "above" | "below" }) {
  const { t } = useI18n();
  const [pinned, setPinned] = useState(false);
  const dialog = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [style, setStyle] = useState<{ left: number; width: number; arrow: number; top?: number; bottom?: number; placement: "above" | "below" } | null>(null);
  const wrap = useRef<HTMLDivElement>(null);
  const id = useId();
  useLayoutEffect(() => {
    if (!(open || pinned) || !wrap.current) { setStyle(null); return; }
    function position() {
      if (!wrap.current) return;
      const rect = wrap.current.getBoundingClientRect();
      const boundary = wrap.current.closest('[role="dialog"]')?.getBoundingClientRect();
      const minLeft = Math.max(8, (boundary?.left ?? 0) + 8);
      const maxRight = Math.min(window.innerWidth - 8, (boundary?.right ?? window.innerWidth) - 8);
      const renderedWidth = Math.min(width, maxRight - minLeft);
      const anchorLeft = align === "end" ? rect.right - renderedWidth : rect.left;
      const left = Math.max(minLeft, Math.min(anchorLeft, maxRight - renderedWidth));
      const arrow = Math.max(12, Math.min(rect.left + rect.width / 2 - left - 5, renderedWidth - 22));
      if (placement !== "below" && rect.top > 160) setStyle({ left, width: renderedWidth, arrow, bottom: window.innerHeight - rect.top + 10, placement: "above" });
      else setStyle({ left, width: renderedWidth, arrow, top: rect.bottom + 10, placement: "below" });
    }
    position();
    window.addEventListener("resize", position);
    window.addEventListener("scroll", position, true);
    return () => { window.removeEventListener("resize", position); window.removeEventListener("scroll", position, true); };
  }, [open, pinned, width, align, placement]);
  useEffect(() => {
    if (!pinnable || !(open || pinned)) return;
    const outside = (event: PointerEvent) => { if (!wrap.current?.contains(event.target as Node) && !dialog.current?.contains(event.target as Node)) { setPinned(false); setOpen(false); } };
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") { setPinned(false); setOpen(false); } };
    document.addEventListener("pointerdown", outside); document.addEventListener("keydown", escape);
    return () => { document.removeEventListener("pointerdown", outside); document.removeEventListener("keydown", escape); };
  }, [open, pinned, pinnable]);
  return <div ref={wrap} className={`hover-bubble-wrap${inline ? " is-inline" : ""}`} onClick={pinnable ? (event) => { if (wrap.current?.contains(event.target as Node)) { if (pinned) setOpen(false); setPinned((value) => !value); } } : undefined} onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)} onFocus={() => setOpen(true)} onBlur={() => setOpen(false)} aria-describedby={open || pinned ? id : undefined}>
    {children}
    {(open || pinned) && style && typeof document !== "undefined" && createPortal(<div ref={dialog} id={id} className={`hover-bubble${pinnable && showClose ? " has-close" : ""}`} data-placement={style.placement} data-align={align} role={pinned ? "dialog" : "tooltip"} aria-label={label} style={{ width: style.width, maxWidth: style.width, minWidth: 0, left: style.left, top: style.top, bottom: style.bottom, "--bubble-arrow-left": `${style.arrow}px` } as CSSProperties}>{pinnable && showClose && <button type="button" className="hover-bubble-close" aria-label={t("Close")} onClick={(event) => { event.stopPropagation(); setPinned(false); setOpen(false); }}><X size={15} aria-hidden="true" /></button>}{bubble}</div>, document.body)}
  </div>;
}
