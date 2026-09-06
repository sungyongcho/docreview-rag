"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { useNotifications } from "@/components/notifications";
import { cancelOperatorJob, getOperatorJobs, retryOperatorJob } from "./api";
import { useI18n } from "./i18n";
import { desktopJobNotificationsEnabled } from "./storage";
import type { OperatorJob, OperatorJobBoard } from "./types";

const EMPTY_BOARD: OperatorJobBoard = { jobs: [], active_count: 0, queued_count: 0 };
const POLL_WORKING_MS = 1_000;
const POLL_IDLE_MS = 5_000;
const POLL_HIDDEN_MS = 15_000;
const POLL_MAX_BACKOFF_MS = 10_000;

/**
 * Delay before the next board poll: 1 s while work runs, 5 s when idle, 15 s in a hidden tab.
 * Consecutive failed polls double the wait 2 → 4 → 8 → 10 s, never below those floors, so a
 * struggling API is not hammered every second while the last board stays on screen.
 */
export function pollDelay(failures: number, working: boolean, visible: boolean): number {
  const base = visible ? (working ? POLL_WORKING_MS : POLL_IDLE_MS) : POLL_HIDDEN_MS;
  const backoff = failures ? Math.min(POLL_WORKING_MS * 2 ** failures, POLL_MAX_BACKOFF_MS) : 0;
  return Math.max(base, backoff);
}

function jobLabel(job: OperatorJob): string {
  return job.kind.replaceAll("_", " ").replace(/\b\w/g, (value) => value.toUpperCase());
}

function desktopNotify(job: OperatorJob): void {
  if (!desktopJobNotificationsEnabled() || typeof Notification === "undefined") return;
  if (Notification.permission !== "granted") return;
  if (!(["succeeded", "failed", "interrupted", "cancelled"] as string[]).includes(job.status)) {
    return;
  }
  new Notification(`DocReview · ${jobLabel(job)}`, { body: `${job.status}: ${job.message}` });
}

export function useOperatorJobs(
  enabled: boolean,
  onTerminal?: () => void | Promise<void>,
  active = true,
) {
  const { t } = useI18n();
  const [board, setBoard] = useState<OperatorJobBoard>(EMPTY_BOARD);
  const [loading, setLoading] = useState(enabled && active);
  /** True while the newest poll failed after an earlier board loaded; the retained board may be out of date. */
  const [stale, setStale] = useState(false);
  const failures = useRef(0);
  const previous = useRef<Map<string, string>>(new Map());
  const initialized = useRef(false);
  const activity = useRef({ enabled, active });
  activity.current = { enabled, active };
  const request = useRef<AbortController | null>(null);
  const latestBoard = useRef(board);
  const mounted = useRef(true);
  const { notify } = useNotifications();

  const apply = useCallback((next: OperatorJobBoard) => {
    if (initialized.current) {
      for (const job of next.jobs) {
        const before = previous.current.get(job.job_id);
        if (before === job.status) continue;
        const tone = job.status === "succeeded"
          ? "success"
          : job.status === "failed" || job.status === "interrupted"
            ? "error"
            : job.status === "cancelled"
              ? "warning"
              : "info";
        notify(`${jobLabel(job)} · ${job.status}: ${job.message}`, tone, `job:${job.job_id}:${job.status}`);
        desktopNotify(job);
        if (["succeeded", "failed", "interrupted", "cancelled"].includes(job.status)) {
          void onTerminal?.();
        }
      }
    }
    previous.current = new Map(next.jobs.map((job) => [job.job_id, job.status]));
    initialized.current = true;
    latestBoard.current = next;
    setBoard(next);
    setLoading(false);
  }, [notify, onTerminal]);

  /** Load the board once; `manual` marks a user-initiated refresh, the only kind that reports its failure. */
  const refresh = useCallback(async (manual = false) => {
    if (!mounted.current || !activity.current.enabled || !activity.current.active || request.current) return;
    const current = new AbortController();
    request.current = current;
    try {
      const next = await getOperatorJobs(current.signal);
      if (request.current !== current || !mounted.current || !activity.current.active || !activity.current.enabled) return;
      failures.current = 0;
      setStale(false);
      // An unchanged board keeps its identity so consumers keyed on it do not refetch every tick.
      if (initialized.current && JSON.stringify(next) === JSON.stringify(latestBoard.current)) {
        setLoading(false);
        return;
      }
      apply(next);
    } catch (reason) {
      if (request.current !== current || current.signal.aborted || !mounted.current || !activity.current.active || !activity.current.enabled) return;
      failures.current += 1;
      setStale(true);
      setLoading(false);
      if (manual) notify(reason instanceof Error ? reason.message : t("Job activity could not be loaded."), "error", "jobs-refresh");
    } finally {
      if (request.current === current) request.current = null;
    }
  }, [apply, notify, t]);

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  useEffect(() => {
    if (!active) {
      setLoading(false);
      return;
    }
    if (!enabled) {
      setBoard(EMPTY_BOARD);
      latestBoard.current = EMPTY_BOARD;
      previous.current = new Map();
      initialized.current = false;
      setLoading(false);
      return;
    }
    let stopped = false;
    let timer = 0;
    const poll = async () => {
      await refresh();
      if (stopped) return;
      const working = latestBoard.current.active_count > 0 || latestBoard.current.queued_count > 0;
      timer = window.setTimeout(poll, pollDelay(failures.current, working, document.visibilityState === "visible"));
    };
    void poll();
    return () => {
      stopped = true;
      window.clearTimeout(timer);
      request.current?.abort();
      request.current = null;
    };
  }, [enabled, active, refresh]);

  const retry = useCallback(async (jobId: string) => {
    if (!mounted.current || !activity.current.enabled || !activity.current.active) return;
    try {
      await retryOperatorJob(jobId);
      await refresh();
    } catch (reason) {
      if (!mounted.current || !activity.current.active || !activity.current.enabled) return;
      notify(reason instanceof Error ? reason.message : t("Job retry failed."), "error", `job-retry:${jobId}`);
    }
  }, [notify, refresh, t]);

  const cancel = useCallback(async (jobId: string) => {
    if (!mounted.current || !activity.current.enabled || !activity.current.active) return;
    try {
      await cancelOperatorJob(jobId);
      await refresh();
    } catch (reason) {
      if (!mounted.current || !activity.current.active || !activity.current.enabled) return;
      notify(reason instanceof Error ? reason.message : t("Job cancellation failed."), "error", `job-cancel:${jobId}`);
    }
  }, [notify, refresh, t]);

  return { board, loading, stale, refresh, retry, cancel };
}
