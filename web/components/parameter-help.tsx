"use client";
import { Info } from "lucide-react";
import { createPortal } from "react-dom";
import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { useI18n } from "@/lib/i18n";
import { useRetainedPanelActive } from "./retained-panel";

/** Small, viewport-bounded parameter help supports hover, focus, touch, and Escape. */
export function ParameterHelp({ label, text }: { label: string; text: string }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false); const active = useRetainedPanelActive();
  const trigger = useRef<HTMLButtonElement>(null); const tip = useRef<HTMLDivElement>(null); const id = useId();
  const [position, setPosition] = useState({ left: 12, top: 12 });
  useEffect(() => { if (!active) setOpen(false); }, [active]);
  useLayoutEffect(() => {
    if (!open || !active) return;
    const align = () => { const rect = trigger.current?.getBoundingClientRect(); if (!rect) return; const height = tip.current?.getBoundingClientRect().height ?? 100; setPosition({ left: Math.max(12, Math.min(rect.left, window.innerWidth - 292)), top: rect.bottom + height + 16 < window.innerHeight ? rect.bottom + 6 : Math.max(12, rect.top - height - 6) }); };
    const close = () => setOpen(false);
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); setOpen(false); } };
    align(); window.addEventListener("resize", close); document.addEventListener("scroll", close, true); document.addEventListener("keydown", escape, true);
    return () => { window.removeEventListener("resize", close); document.removeEventListener("scroll", close, true); document.removeEventListener("keydown", escape, true); };
  }, [open, active]);
  return <><button className="parameter-help" type="button" aria-label={t("About {label}", { label: t(label) })} aria-expanded={open && active} aria-describedby={open && active ? id : undefined} ref={trigger} onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)} onFocus={() => setOpen(true)} onBlur={() => setOpen(false)} onClick={event => { event.preventDefault(); setOpen(true); }}><Info size={13} aria-hidden="true" /></button>{open && active && createPortal(<div id={id} ref={tip} className="parameter-help-tip" role="tooltip" style={position}>{t(text)}</div>, document.body)}</>;
}
