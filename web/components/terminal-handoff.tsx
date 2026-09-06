"use client";

import { useEffect, useState } from "react";
import { useI18n } from "@/lib/i18n";
import "./terminal-handoff.css";

import type { Diagnosis, TerminalStep } from "@/lib/preparation-diagnostics";
export type { TerminalStep } from "@/lib/preparation-diagnostics";

/** Present terminal prerequisites compactly beside the affected preparation step. */
export function TerminalHandoff({ steps, onRefresh, blocking = true, diagnosis, onNavigate, technicalDetail }: { steps: TerminalStep[]; onRefresh: () => unknown | Promise<unknown>; blocking?: boolean; diagnosis?: Diagnosis; technicalDetail?: string | null; onNavigate?: (target: NonNullable<Diagnosis["returnTo"]>) => void }) {
  const { t } = useI18n();
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
  return <section className={`terminal-handoff${blocking ? " is-blocking" : ""}`} aria-label={t("Terminal preparation")}>
    <div className="terminal-handoff-heading">
      <strong>{t(diagnosis?.title ?? (steps.length ? blocking ? "Run in terminal" : "Next step preparation" : checked ? "Preparation state updated" : "Check updated status"))}</strong>
      <button className="button ghost" type="button" disabled={checking} onClick={() => void recheck()}>{t(checking ? "Checking runtime…" : "Check updated status")}</button>
    </div>
    {diagnosis && <p className="helper">{t(diagnosis.detail)}</p>}
    {diagnosis?.returnTo && onNavigate && diagnosis.state === "blocked" && <button className="button ghost" type="button" onClick={() => onNavigate(diagnosis.returnTo!)}>{t(diagnosis.returnTo === "setup" ? "Open setup checks" : "Go to prerequisite step")}</button>}
    {technicalDetail && <details className="schema-technical-detail"><summary>{t("Schema technical details")}</summary><pre>{technicalDetail}</pre></details>}
    {steps.length > 0 && <details open={expanded} onToggle={(event) => setExpanded(event.currentTarget.open)}>
      <summary>{t("Terminal instructions")}</summary>
      <p className="helper">{t("Run the command in this checkout, return to this step, then check the updated status.")}</p>
      {steps.map((step) => <div className="terminal-handoff-step" key={step.command}>
        <p>{t(step.reason)}</p>
        <div className="terminal-command"><pre><code>{step.command}</code></pre><button className="button ghost" type="button" onClick={() => void copy(step.command)}>{t("Copy command")}</button></div>
        <p className="helper">{t(step.expected)}</p>
      </div>)}
    </details>}
    <p className="terminal-handoff-status" role="status">{message || (checked ? t("Preparation state updated") : "")}</p>
  </section>;
}
