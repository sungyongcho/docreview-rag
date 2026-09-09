"use client";

import { useId, useState, type ReactNode } from "react";
import "./hover-bubble.css";

/** A speech bubble that follows the pointer or keyboard focus over its child and leaves with it. */
export function HoverBubble({ bubble, children, inline = false, placement = "above" }: { bubble: ReactNode; children: ReactNode; inline?: boolean; placement?: "above" | "below" }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return <div className={`hover-bubble-wrap${inline ? " is-inline" : ""}`} onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)} onFocus={() => setOpen(true)} onBlur={() => setOpen(false)} aria-describedby={open ? id : undefined}>
    {children}
    {open && <div id={id} className="hover-bubble" data-placement={placement} role="tooltip">{bubble}</div>}
  </div>;
}
