"use client";

import { useEffect, useId, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, X } from "lucide-react";
import { disclosureNodes, type DisclosureStage } from "@/components/review-stage-details";
import { ExecutionPerformance } from "@/components/execution-performance";
import { useI18n } from "@/lib/i18n";
import type { ChatMessage } from "@/lib/types";
import "./run-details-panel.css";

type Section = "performance" | "settings" | "trace";
const SECTIONS: Array<{ id: Section; label: string }> = [
  { id: "performance", label: "Performance" },
  { id: "settings", label: "Server settings" },
  { id: "trace", label: "Trace" },
];

interface RunDetailsPanelProps {
  message: ChatMessage | null;
  stageRequest?: { stage: DisclosureStage | null };
  onClose: () => void;
  onOpenFix?: (category: "limits" | "runtime") => void;
}

/** Inspect one message beside its conversation, preserving its last selected section. */
export function RunDetailsPanel({ message, onClose, onOpenFix, stageRequest }: RunDetailsPanelProps) {
  const { t } = useI18n();
  const uid = useId();
  const panel = useRef<HTMLElement>(null);
  const content = useRef<HTMLDivElement>(null);
  const opener = useRef<HTMLElement | null>(null);
  const skipFocusReturn = useRef(false);
  const close = useRef(onClose);
  close.current = onClose;
  const [sections, setSections] = useState<Record<string, Section>>({});
  const [collapsed, setCollapsed] = useState(false);
  const [expandedQuestion, setExpandedQuestion] = useState<string | null>(null);
  const open = message !== null;
  const section = message ? sections[message.id] ?? "performance" : "performance";

  useEffect(() => {
    if (!open) return;
    opener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    skipFocusReturn.current = false;
    panel.current?.focus({ preventScroll: true });
    /** Give a modal settings dialog priority over the nonmodal run inspector. */
    function modalOwnsFocus() {
      return [...document.querySelectorAll<HTMLElement>('[role="dialog"][aria-modal="true"]')].some((element) => !element.closest("[hidden], [inert]"));
    }
    /** Close the inspector with Escape without intercepting an active modal. */
    function keydown(event: KeyboardEvent) {
      if (event.defaultPrevented || modalOwnsFocus() || event.key !== "Escape") return;
      event.preventDefault();
      close.current();
    }
    /** Let the clicked conversation control keep its focus and native behavior. */
    function pointerdown(event: PointerEvent) {
      const target = event.target instanceof Element ? event.target : null;
      if (!target || panel.current?.contains(target) || target.closest("[data-run-details-open]") || modalOwnsFocus()) return;
      if (!target.closest(".review-workspace") || !target.closest(".messages, .composer-wrap")) return;
      skipFocusReturn.current = true;
      close.current();
    }
    window.addEventListener("keydown", keydown);
    document.addEventListener("pointerdown", pointerdown);
    return () => {
      window.removeEventListener("keydown", keydown);
      document.removeEventListener("pointerdown", pointerdown);
      const previous = opener.current;
      if (!skipFocusReturn.current && previous?.isConnected && !previous.closest("[hidden], [inert]") && !modalOwnsFocus()) previous.focus({ preventScroll: true });
    };
  }, [open]);

  useEffect(() => {
    if (!message) return;
    const active = document.activeElement;
    if (active instanceof HTMLElement && !panel.current?.contains(active)) opener.current = active;
    setCollapsed(false);
    setExpandedQuestion(null);
    panel.current?.focus({ preventScroll: true });
  }, [message?.id]);

  useEffect(() => {
    if (content.current) content.current.scrollTop = 0;
  }, [message?.id, section]);

  useEffect(() => {
    if (!message || !stageRequest?.stage) return;
    setSections((previous) => ({ ...previous, [message.id]: "performance" }));
    setCollapsed(false);
  }, [message?.id, stageRequest]);

  /** Activate and focus a neighboring section using the standard tab keyboard pattern. */
  function moveTab(event: React.KeyboardEvent<HTMLButtonElement>, current: number) {
    const next = event.key === "Home" ? 0 : event.key === "End" ? SECTIONS.length - 1 : event.key === "ArrowRight" ? (current + 1) % SECTIONS.length : event.key === "ArrowLeft" ? (current + SECTIONS.length - 1) % SECTIONS.length : null;
    if (next === null || !message) return;
    event.preventDefault();
    setSections((previous) => ({ ...previous, [message.id]: SECTIONS[next].id }));
    document.getElementById(`${uid}-${SECTIONS[next].id}-tab`)?.focus();
  }

  if (!message) return null;
  const question = message.question?.trim() || t("Question unavailable");
  const settings = message.performance?.effective_settings as Record<string, unknown> | null | undefined;
  const fullQuestion = expandedQuestion === message.id;

  return <aside ref={panel} className={`run-details-panel${collapsed ? " is-collapsed" : ""}`} role="dialog" aria-modal="false" aria-label={t("Run details")} tabIndex={-1}>
    <button className="run-details-edge" type="button" aria-label={t(collapsed ? "Expand run details" : "Collapse run details")} aria-expanded={!collapsed} aria-controls={`${uid}-body`} onClick={() => setCollapsed(!collapsed)}>{collapsed ? <ChevronLeft size={18} aria-hidden="true" /> : <ChevronRight size={18} aria-hidden="true" />}</button>
    <div id={`${uid}-body`} className="run-details-body" hidden={collapsed}>
      <header className="run-details-header">
        <div className="run-details-toolbar"><p>{t("Run details")}</p><button className="run-details-close" type="button" aria-label={t("Close run details")} onClick={onClose}><X size={21} aria-hidden="true" /></button></div>
        <div className="run-details-question-line"><h2 className={fullQuestion ? "is-expanded" : ""} title={`Q. ${question}`}>Q. {question}</h2><code className="run-details-message-id" title={message.id}>{message.id.slice(0, 8)}</code></div>
        <button className="run-details-question-toggle" type="button" aria-expanded={fullQuestion} onClick={() => setExpandedQuestion(fullQuestion ? null : message.id)}>{t(fullQuestion ? "Collapse question" : "Show full question")}</button>
        <div className="run-details-tabs" role="tablist" aria-label={t("Run detail sections")}>{SECTIONS.map((item, index) => <button key={item.id} id={`${uid}-${item.id}-tab`} role="tab" type="button" aria-selected={section === item.id} aria-controls={`${uid}-${item.id}`} tabIndex={section === item.id ? 0 : -1} onClick={() => setSections((previous) => ({ ...previous, [message.id]: item.id }))} onKeyDown={(event) => moveTab(event, index)}>{t(item.label)}</button>)}</div>
      </header>
      <div className="run-details-content" ref={content}>
        <section id={`${uid}-performance`} role="tabpanel" aria-labelledby={`${uid}-performance-tab`} hidden={section !== "performance"} tabIndex={0}>
          <h3>{t("Execution performance")}</h3>
          {message.execution ? <ExecutionPerformance data={message.performance} state={message.execution} selectedNodes={stageRequest?.stage ? disclosureNodes(stageRequest.stage, message.execution) : []} embedded /> : <p className="helper">{t("Execution measurements were not recorded for this message.")}</p>}
        </section>
        <section id={`${uid}-settings`} role="tabpanel" aria-labelledby={`${uid}-settings-tab`} hidden={section !== "settings"} tabIndex={0}>
          <h3>{t("Server-applied settings")}</h3>
          {settings?.retrieval_applicable === false && <p className="helper">{t("This conversation reply did not use retrieval settings.")}</p>}
          {settings ? <pre className="run-details-json">{JSON.stringify(settings, null, 2)}</pre> : <p className="helper">{t("Server-applied settings were not recorded for this message.")}</p>}
        </section>
        <section id={`${uid}-trace`} role="tabpanel" aria-labelledby={`${uid}-trace-tab`} hidden={section !== "trace"} tabIndex={0} data-help="review.run-trace">
          <h3>{t("Run trace")}{message.failureFix ? t(" · why it stopped") : ""}</h3>
          {message.diagnostics?.length ? <dl className="status-list run-diagnostics">{message.diagnostics.map((row) => <div key={row.label}><dt>{t(row.label)}</dt><dd>{row.label === "Status" ? t(row.value) : row.value}</dd></div>)}</dl> : message.trace ? <pre className="trace run-details-json">{message.trace}</pre> : <p className="helper">{t("A run trace was not recorded for this message.")}</p>}
          {message.failureFix && onOpenFix && <button className="button" type="button" onClick={() => onOpenFix(message.failureFix!.category)}>{t(message.failureFix.label)}</button>}
        </section>
      </div>
    </div>
  </aside>;
}
