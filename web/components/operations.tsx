"use client";

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

export function Operations() {
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
      notify(reason instanceof Error ? reason.message : "Operations refresh failed.", "error", "operations-refresh");
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
      notify(`${command.label} started.`, "success", "operations-run");
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Command could not start.", "error", "operations-run");
    }
  }

  async function cancel() {
    if (!active) return;
    try {
      const job = await cancelOperatorJob(active.job_id);
      setJobs((current) => current.map((item) => item.job_id === job.job_id ? job : item));
      notify("Command cancelled.", "success", "operations-cancel");
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Command could not be cancelled.", "error", "operations-cancel");
    }
  }

  const latest = jobs[0] ?? null;
  return (
    <section className="operations-page">
      <header className="page-heading">
        <div><p className="eyebrow">Local checkout only</p><h1>Operations</h1><p>Run fixed verification and service commands without exposing a shell.</p></div>
        <button className="button" type="button" disabled={loading} onClick={() => void refresh()}><RefreshCw size={15} /> Refresh</button>
      </header>
      <div className="command-grid">
        {commands.map((command) => (
          <article className="command-card" key={command.command_id}>
            <div className="command-heading"><TerminalSquare size={16} /><span className={`command-kind ${command.category}`}>{command.category}</span></div>
            <h2>{command.label}</h2><p>{command.description}</p>
            {command.confirmation && <small>Confirmation required</small>}
            <button className="button primary" type="button" disabled={Boolean(active)} onClick={() => void run(command)}><Play size={14} /> Run</button>
          </article>
        ))}
      </div>
      <section className="surface operation-output">
        <div className="operation-output-heading"><h2>Latest run</h2>{active && <button className="button" type="button" onClick={() => void cancel()}><CircleStop size={14} /> Cancel</button>}</div>
        {latest ? <><p className="helper">{latest.label} · {latest.status}{latest.exit_code !== null ? ` · exit ${latest.exit_code}` : ""}</p><pre>{latest.output || "Waiting for output…"}</pre></> : <p className="helper">No local command has run in this session.</p>}
      </section>
    </section>
  );
}
