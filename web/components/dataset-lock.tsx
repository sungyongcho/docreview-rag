"use client";

import { LockKeyhole } from "lucide-react";
import { createPortal } from "react-dom";
import { useEffect, useId, useRef, useState } from "react";
import { useI18n } from "@/lib/i18n";
import { useRetainedPanelActive } from "./retained-panel";
import "./dataset-lock.css";

/** Non-clickable read-only marker with application-rendered hover and focus help. */
export function DatasetLock() {
  const { t } = useI18n();
  const active = useRetainedPanelActive();
  const id = useId();
  const marker = useRef<HTMLSpanElement>(null);
  const [position, setPosition] = useState<{ left: number; top: number } | null>(null);
  const message = t("Built-in datasets are read-only. Create a draft to edit.");
  const visible = active && position !== null;
  function show() {
    const rect = marker.current?.getBoundingClientRect();
    if (rect) setPosition({ left: Math.max(12, Math.min(rect.left, window.innerWidth - 292)), top: Math.max(12, Math.min(rect.bottom + 6, window.innerHeight - 92)) });
  }
  useEffect(() => { if (!active) setPosition(null); }, [active]);
  useEffect(() => {
    if (!visible) return;
    const close = () => setPosition(null);
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") close(); };
    window.addEventListener("resize", close);
    document.addEventListener("scroll", close, true);
    document.addEventListener("keydown", escape);
    return () => { window.removeEventListener("resize", close); document.removeEventListener("scroll", close, true); document.removeEventListener("keydown", escape); };
  }, [visible]);
  return <><span ref={marker} className="golden-file-lock" role="img" tabIndex={0} aria-label={message} aria-describedby={visible ? id : undefined} onMouseEnter={show} onMouseLeave={() => setPosition(null)} onFocus={show} onBlur={() => setPosition(null)}><LockKeyhole size={15} aria-hidden="true" /></span>{visible && createPortal(<div id={id} role="tooltip" className="dataset-lock-tooltip" style={position}>{message}</div>, document.body)}</>;
}
