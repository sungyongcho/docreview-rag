"use client";

import { CircleHelp } from "lucide-react";
import { createPortal } from "react-dom";
import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { developmentHelpTopic, type HelpAccess, type HelpScreen } from "@/lib/help-content";
import { helpEntriesForAccess } from "@/lib/help-search";
import { DevelopmentBadge } from "@/components/development-badge";
import { useI18n } from "@/lib/i18n";
import "./workflow-help.css";

/** Keep page help inside the visible workspace and close it whenever its owner changes. */
export function WorkflowHelp({ screen, capabilities, publicPreview, active = true }: { screen: HelpScreen; active?: boolean } & HelpAccess) {
  const { t, locale } = useI18n();
  const topics = helpEntriesForAccess({ capabilities, publicPreview }).filter((entry) => entry.screen === screen).slice(0, 3);
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const id = useId();
  const [position, setPosition] = useState({ left: 12, top: 12, width: 430, maxHeight: 440 });
  useLayoutEffect(() => { setOpen(false); }, [screen, active, publicPreview, topics.length]);
  useLayoutEffect(() => {
    if (!open || !active) return;
    const align = () => {
      const rect = trigger.current?.getBoundingClientRect();
      if (!rect) return;
      if (rect.bottom < 0 || rect.top > window.innerHeight) { setOpen(false); return; }
      const workspace = trigger.current?.closest(".workspace")?.getBoundingClientRect();
      const start = Math.max(12, (workspace?.left ?? 0) + 12);
      const end = Math.min(window.innerWidth - 12, (workspace?.right ?? window.innerWidth) - 12);
      const width = Math.max(0, Math.min(430, end - start));
      const below = window.innerHeight - rect.bottom - 20;
      const above = below < 180 && rect.top > below;
      const maxHeight = Math.max(80, Math.min(440, above ? rect.top - 20 : below));
      setPosition({ left: Math.max(start, Math.min(rect.left, end - width)), top: above ? Math.max(12, rect.top - maxHeight - 8) : Math.max(12, rect.bottom + 8), width, maxHeight });
    };
    align(); panel.current?.focus({ preventScroll: true });
    window.addEventListener("resize", align);
    document.addEventListener("scroll", align, true);
    return () => { window.removeEventListener("resize", align); document.removeEventListener("scroll", align, true); };
  }, [open, active, locale]);
  useEffect(() => {
    if (!open) return;
    const outside = (event: PointerEvent) => { const target = event.target as Node; if (!trigger.current?.contains(target) && !panel.current?.contains(target)) setOpen(false); };
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape" && !event.defaultPrevented) { event.preventDefault(); setOpen(false); trigger.current?.focus(); } };
    document.addEventListener("pointerdown", outside); document.addEventListener("keydown", escape);
    return () => { document.removeEventListener("pointerdown", outside); document.removeEventListener("keydown", escape); };
  }, [open]);
  if (!topics.length) return null;
  return <div className="workflow-help"><button ref={trigger} type="button" className="workflow-help-trigger" aria-label={t("How to use this page")} aria-expanded={open && active} aria-controls={open && active ? id : undefined} onClick={() => setOpen(value => !value)}><CircleHelp size={18} aria-hidden="true" /></button>{open && active && createPortal(<div id={id} ref={panel} className="workflow-help-panel workflow-help-floating" role="dialog" aria-modal="false" aria-label={t("How to use this page")} tabIndex={-1} style={{ ...position, position: "fixed" }}><strong>{t("How to use this page")}</strong>{topics.map(({ topic }) => <section key={topic.id}><h3>{t(topic.title)}{developmentHelpTopic(topic) && <DevelopmentBadge locale={locale} compact />}</h3>{topic.body.map(text => <p key={text}>{t(text)}</p>)}</section>)}</div>, document.body)}</div>;
}
