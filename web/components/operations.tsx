"use client";
import { useI18n } from "@/lib/i18n";


import { CircleStop, Play, RefreshCw, TerminalSquare } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import {
  cancelOperatorJob,
  getOperatorCommands,
  getOperatorJobs,
  type OperatorCommand,
  type OperatorJob,
  startOperatorJob,
} from "@/lib/operator-api";
import { useNotifications } from "@/components/notifications";

/** `embedded` drops the page heading so a host workspace keeps the only h1; `helpId` is the Help mode hook. */
export function Operations({ embedded = false, helpId }: { embedded?: boolean; helpId?: string } = {}) {
  const { t, locale } = useI18n();
  const [commands, setCommands] = useState<OperatorCommand[]>([]);
  const [jobs, setJobs] = useState<OperatorJob[]>([]);
  const { notify } = useNotifications();
  const [loading, setLoading] = useState(true);
  const active = useMemo(() => jobs.find((job) => job.status === "running") ?? null, [jobs]);

  async function refresh() {
    try {
      const [nextCommands, nextJobs] = await Promise.all([getOperatorCommands(), getOperatorJobs()]);
      setCommands(nextCommands);
      setJobs(nextJobs);
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : t("Operations refresh failed."), "error", "operations-refresh");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void refresh(); }, []);
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => void getOperatorJobs().then(setJobs).catch((reason) => notify(String(reason), "error", "operations-poll")), 1000);
    return () => window.clearInterval(timer);
  }, [active?.job_id]);

  async function run(command: OperatorCommand) {
    if (command.confirmation && !window.confirm(command.confirmation)) return;
    try {
      const job = await startOperatorJob(command.command_id);
      setJobs((current) => [job, ...current.filter((item) => item.job_id !== job.job_id)]);
      notify(t("{p0} started.", { p0: t(command.label) }), "success", "operations-run");
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : t("Command could not start."), "error", "operations-run");
    }
  }

  async function cancel() {
    if (!active) return;
    try {
      const job = await cancelOperatorJob(active.job_id);
      setJobs((current) => current.map((item) => item.job_id === job.job_id ? job : item));
      notify(t("Command cancelled."), "success", "operations-cancel");
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : t("Command could not be cancelled."), "error", "operations-cancel");
    }
  }

  const latest = jobs[0] ?? null;
  return (
    <section className={`operations-page${embedded ? " embedded" : ""}`} data-help={helpId}>
      {embedded
        ? <div className="surface-heading"><div><h2>{t("Operations")}</h2><p className="helper">{t("Local checkout only. Run fixed verification and service commands without exposing a shell.")}</p></div><button className="button" type="button" disabled={loading} onClick={() => void refresh()}><RefreshCw size={15} />{t("Refresh")}</button></div>
        : <header className="page-heading">
            <div><p className="eyebrow">{t("Local checkout only")}</p><h1>{t("Operations")}</h1><p>{t("Run fixed verification and service commands without exposing a shell.")}</p></div>
            <button className="button" type="button" disabled={loading} onClick={() => void refresh()}><RefreshCw size={15} />{t("Refresh")}</button>
          </header>}
      <div className="command-grid">
        {commands.map((command) => (
          <article className="command-card" key={command.command_id}>
            <div className="command-heading"><TerminalSquare size={16} /><span className={`command-kind ${command.category}`}>{t(command.category)}</span></div>
            <h2>{t(command.label)}</h2><p>{t(command.description)}</p>
            {command.confirmation && <small>{t("Confirmation required")}</small>}
            <button className="button primary" type="button" disabled={Boolean(active)} onClick={() => void run(command)}><Play size={14} />{t("Run")}</button>
          </article>
        ))}
      </div>
      <section className="surface operation-output">
        <div className="operation-output-heading"><h2>{t("Latest run")}</h2>{active && <button className="button" type="button" onClick={() => void cancel()}><CircleStop size={14} />{t("Cancel")}</button>}</div>
        {latest ? <><p className="helper">{t(latest.label)} · {t(latest.status)}{latest.exit_code !== null ? t(" · exit {p0}", { p0: latest.exit_code }) : ""}</p><pre>{latest.output || t("Waiting for output…")}</pre></> : <p className="helper">{t("No local command has run in this session.")}</p>}
      </section>
    </section>
  );
}
