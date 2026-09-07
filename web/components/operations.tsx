"use client";
import { useI18n } from "@/lib/i18n";


import { CircleStop, Play, RefreshCw, TerminalSquare, TriangleAlert } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import {
  cancelOperatorJob,
  getOperatorCommands,
  getOperatorJobs,
  OPERATION_CATEGORIES,
  type OperationsFilter,
  type OperationsTargetFilter,
  type OperatorTarget,
  type OperatorCommand,
  type OperatorJob,
  startOperatorJob,
} from "@/lib/operator-api";
import { loadOperationsFilter, saveOperationsFilter, loadOperationsTargetFilter, saveOperationsTargetFilter } from "@/lib/storage";
import { useNotifications } from "@/components/notifications";
import { Segmented } from "@/components/segmented";

/** Consecutive failed polls tolerated before one persistent waiting notice replaces per-failure toasts. */
export const POLL_NOTICE_AFTER_FAILURES = 3;
const POLL_INTERVAL_MS = 1_000;
const POLL_HIDDEN_INTERVAL_MS = 5_000;
const POLL_MAX_BACKOFF_MS = 10_000;

const CATEGORY_LABELS: Record<OperatorCommand["category"], string> = { inspect: "Inspect", verify: "Verify", service: "Service" };
const FILTER_OPTIONS: Array<{ value: OperationsFilter; label: string }> = [
  { value: "all", label: "All" },
  { value: "inspect", label: "Inspect" },
  { value: "verify", label: "Verify" },
  { value: "service", label: "Service" },
];

const TARGET_LABELS: Record<OperatorTarget, string> = { python: "Python", web: "Web", database: "Database", app: "App" };
const TARGET_FILTER_OPTIONS: Array<{ value: OperationsTargetFilter; label: string }> = [
  { value: "all", label: "All targets" },
  { value: "python", label: "Python" },
  { value: "web", label: "Web" },
  { value: "database", label: "Database" },
  { value: "app", label: "App" },
];

export interface CommandGroup {
  category: OperatorCommand["category"];
  commands: OperatorCommand[];
}

/**
 * Group commands by category in display order, appending any category the registry adds later
 * so nothing is hidden. Inside a group read-only commands come first and confirmation-required
 * commands last; the stable sort keeps registry order within each half.
 */
export function groupCommands(commands: OperatorCommand[]): CommandGroup[] {
  const categories = [...OPERATION_CATEGORIES, ...commands.map((command) => command.category)];
  return [...new Set(categories)]
    .map((category) => ({
      category,
      commands: commands
        .filter((command) => command.category === category)
        .sort((a, b) => Number(Boolean(a.confirmation)) - Number(Boolean(b.confirmation))),
    }))
    .filter((group) => group.commands.length > 0);
}

/** Delay before the next job poll: 1 s while healthy, doubling per consecutive failure up to 10 s, never under 5 s in a hidden tab. */
export function pollDelay(failures: number, visible: boolean): number {
  const delay = failures ? Math.min(POLL_INTERVAL_MS * 2 ** failures, POLL_MAX_BACKOFF_MS) : POLL_INTERVAL_MS;
  return visible ? delay : Math.max(POLL_HIDDEN_INTERVAL_MS, delay);
}

/** `embedded` drops the page heading so a host workspace keeps the only h1; `helpId` is the Help mode hook. */
export function Operations({ embedded = false, helpId }: { embedded?: boolean; helpId?: string } = {}) {
  const { t } = useI18n();
  const [commands, setCommands] = useState<OperatorCommand[]>([]);
  const [jobs, setJobs] = useState<OperatorJob[]>([]);
  const { notify, dismissNotice } = useNotifications();
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<OperationsFilter>("all");
  const [targetFilter, setTargetFilter] = useState<OperationsTargetFilter>("all");
  const active = useMemo(() => jobs.find((job) => job.status === "running") ?? null, [jobs]);
  const groups = useMemo(() => groupCommands(commands), [commands]);
  const visibleGroups = groups
    .filter((group) => filter === "all" || group.category === filter)
    .map((group) => ({ ...group, commands: group.commands.filter((command) => targetFilter === "all" || command.target === targetFilter) }))
    .filter((group) => group.commands.length > 0);

  // Read the remembered filter after mount so server and first client render agree.
  useEffect(() => { setFilter(loadOperationsFilter()); setTargetFilter(loadOperationsTargetFilter()); }, []);

  function changeFilter(next: OperationsFilter) {
    setFilter(next);
    saveOperationsFilter(next);
  }

  /** Combine the target with the category while leaving execution independent of presentation. */
  function changeTargetFilter(next: OperationsTargetFilter) {
    setTargetFilter(next);
    saveOperationsTargetFilter(next);
  }

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

  // Follow a running job with one request in flight at a time. Transient failures back off and,
  // after a few in a row, raise a single persistent notice instead of a toast per failure.
  useEffect(() => {
    if (!active) return;
    let stopped = false;
    let failures = 0;
    let noticed = false;
    let timer = 0;
    let request: AbortController | null = null;
    const visible = () => document.visibilityState === "visible";
    const poll = async () => {
      const current = new AbortController();
      request = current;
      try {
        const next = await getOperatorJobs(current.signal);
        if (stopped) return;
        failures = 0;
        if (noticed) {
          dismissNotice("operations-poll");
          noticed = false;
        }
        setJobs(next);
      } catch {
        if (stopped || current.signal.aborted) return;
        failures += 1;
        if (failures === POLL_NOTICE_AFTER_FAILURES) {
          notify(t("Local Operations is not responding. Retrying status checks."), "info", "operations-poll", 0);
          noticed = true;
        }
      }
      timer = window.setTimeout(poll, pollDelay(failures, visible()));
    };
    timer = window.setTimeout(poll, pollDelay(0, visible()));
    return () => {
      stopped = true;
      window.clearTimeout(timer);
      request?.abort();
      if (noticed) dismissNotice("operations-poll");
    };
  }, [active?.job_id, notify, dismissNotice, t]);

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
      <div className="chip-group command-filter">
        <Segmented<OperationsFilter> label="Command category" options={FILTER_OPTIONS} value={filter} onChange={changeFilter} />
        <Segmented<OperationsTargetFilter> label="Command target" options={TARGET_FILTER_OPTIONS} value={targetFilter} onChange={changeTargetFilter} />
      </div>
      {!loading && commands.length > 0 && visibleGroups.length === 0 && <p className="helper" role="status">{t("No commands match these filters.")}</p>}
      {visibleGroups.map((group) => (
        <section className="command-group" key={group.category}>
          <h3 className="command-group-heading">{t(CATEGORY_LABELS[group.category] ?? group.category)}</h3>
          <div className="command-grid">
            {group.commands.map((command) => (
              <article className="command-card" key={command.command_id}>
                <div className="command-heading">
                  <TerminalSquare size={16} />
                  <span className="command-badges">
                    <span className={`command-kind ${command.category}`}>{t(command.category)}</span>
                    <span className="command-kind target">{t(TARGET_LABELS[command.target] ?? "Target not reported")}</span>
                    {command.confirmation && <span className="command-kind confirmation" title={command.confirmation}><TriangleAlert size={11} aria-hidden="true" />{t("Confirmation required")}</span>}
                  </span>
                </div>
                <h4>{t(command.label)}</h4><p>{t(command.description)}</p>
                <button className="button primary" type="button" disabled={Boolean(active)} onClick={() => void run(command)}><Play size={14} />{t("Run")}</button>
              </article>
            ))}
          </div>
        </section>
      ))}
      <section className="surface operation-output">
        <div className="operation-output-heading"><h2>{t("Latest run")}</h2>{active && <button className="button" type="button" onClick={() => void cancel()}><CircleStop size={14} />{t("Cancel")}</button>}</div>
        {latest ? <><p className="helper">{t(latest.label)} · {t(latest.status)}{latest.exit_code !== null ? t(" · exit {p0}", { p0: latest.exit_code }) : ""}</p><pre>{latest.output || t("Waiting for output…")}</pre></> : <p className="helper">{t("No local command has run in this session.")}</p>}
      </section>
    </section>
  );
}
