"use client";

import { RefreshCw, LoaderCircle, CheckCircle2, Circle, TriangleAlert } from "lucide-react";
import { useEffect, useId, useState } from "react";
import { useI18n } from "@/lib/i18n";
import "./terminal-handoff.css";

import type { Diagnosis, TerminalStep } from "@/lib/preparation-diagnostics";
export type { TerminalStep } from "@/lib/preparation-diagnostics";

/** Present terminal prerequisites compactly beside the affected preparation step. */
export function TerminalHandoff({ steps, onRefresh, blocking = true, diagnosis, onNavigate, technicalDetail, compact = false }: { compact?: boolean; steps: TerminalStep[]; onRefresh: () => unknown | Promise<unknown>; blocking?: boolean; diagnosis?: Diagnosis; technicalDetail?: string | null; onNavigate?: (target: NonNullable<Diagnosis["returnTo"]>) => void }) {
  const { t } = useI18n();
  const tooltipId = useId();
  const [tooltip, setTooltip] = useState<"state" | "refresh" | null>(null);
  const [checking, setChecking] = useState(false);
  const [checked, setChecked] = useState(false);
  const [expanded, setExpanded] = useState(blocking);
  const [message, setMessage] = useState("");
  useEffect(() => setExpanded(blocking), [blocking]);
  async function recheck() {
    setChecking(true); setMessage("");
    try {
      const result = await onRefresh(); setChecked(result !== false);
      if (result === false) setMessage(t("Could not refresh status. Check the connection and try again."));
    } catch { setChecked(false); setMessage(t("Could not refresh status. Check the connection and try again.")); }
    finally { setChecking(false); }
  }
  async function copy(command: string) {
    try { await navigator.clipboard.writeText(command); setMessage(t("Command copied.")); }
    catch { setMessage(t("Copy the command manually from the block above.")); }
  }
  if (!diagnosis && !steps.length && !checked && !message) return null;
  const state = diagnosis?.state ?? "checking";
  const label = state === "running" ? t(diagnosis?.title === "This step is queued" ? "Queued" : "Running")
    : state === "complete" ? t("Complete") : state === "ready" ? t("Ready to run")
    : state === "blocked" ? t("Needs attention") : t("Checking status");
  const Icon = state === "running" ? LoaderCircle : state === "complete" ? CheckCircle2
    : state === "blocked" ? TriangleAlert : Circle;
  return <section className={`terminal-handoff${blocking ? " is-blocking" : ""}${compact ? " is-compact" : ""}`} aria-label={t("Terminal preparation")}>
    <div className="terminal-handoff-heading" onMouseLeave={() => setTooltip(null)} onKeyDown={(event) => { if (event.key === "Escape") setTooltip(null); }}>
      <strong className="preparation-state" data-state={state} tabIndex={compact && diagnosis ? 0 : undefined} aria-describedby={tooltip === "state" ? tooltipId : undefined} onMouseEnter={() => diagnosis && setTooltip("state")} onFocus={() => diagnosis && setTooltip("state")} onBlur={() => setTooltip(null)}>{compact ? <><Icon size={14} className={state === "running" ? "preparation-spinner" : undefined} aria-hidden="true" />{label}</> : t(diagnosis?.title ?? (steps.length ? blocking ? "Run in terminal" : "Next step preparation" : checked ? "Preparation state updated" : "Check updated status"))}</strong>
      <button className="button ghost" type="button" disabled={checking} aria-label={t(checking ? "Checking runtime…" : "Check updated status")} aria-describedby={tooltip === "refresh" ? tooltipId : undefined} onMouseEnter={() => setTooltip("refresh")} onFocus={() => setTooltip("refresh")} onBlur={() => setTooltip(null)} onClick={() => void recheck()}>{compact ? checking ? <RefreshCw size={15} className="preparation-spinner" aria-hidden="true" /> : checked && !message ? <CheckCircle2 size={15} aria-hidden="true" /> : <RefreshCw size={15} aria-hidden="true" /> : t(checking ? "Checking runtime…" : "Check updated status")}</button>
      {diagnosis?.returnTo && onNavigate && diagnosis.state === "blocked" && <button className="button ghost" type="button" onClick={() => onNavigate(diagnosis.returnTo!)}>{t(diagnosis.returnTo === "setup" ? "Open setup checks" : "Go to prerequisite step")}</button>}
      {tooltip && <div id={tooltipId} role="tooltip" className="preparation-tooltip">{tooltip === "state" && diagnosis ? <><strong>{t(diagnosis.title)}</strong><span>{t(diagnosis.detail)}</span></> : t(checking ? "Checking runtime…" : checked && !message ? "Preparation state updated" : "Check updated status")}</div>}
    </div>
    {diagnosis && !compact && <p className="helper">{t(diagnosis.detail)}</p>}
    {technicalDetail && <details className="schema-technical-detail"><summary>{t("Schema technical details")}</summary><pre>{technicalDetail}</pre></details>}
    {steps.length > 0 && <details open={expanded} onToggle={(event) => setExpanded(event.currentTarget.open)}>
      <summary>{t("Terminal instructions")}</summary>
      <p className="helper">{t("Run the command in this checkout, return to this step, then check the updated status.")}</p>
      {steps.map((step) => <div className={`terminal-handoff-step${step.danger ? " is-danger" : ""}`} key={step.command}>
        <p>{t(step.reason)}</p>
        <div className="terminal-command"><pre><code>{step.command}</code></pre><button className="button ghost" type="button" onClick={() => void copy(step.command)}>{t("Copy command")}</button></div>
        <p className="helper">{t(step.expected)}</p>
      </div>)}
    </details>}
    <p className="terminal-handoff-status" role="status">{message || (!compact && checked ? t("Preparation state updated") : "")}</p>
  </section>;
}
