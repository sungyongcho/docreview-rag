"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { useNotifications } from "@/components/notifications";
import { cancelOperatorJob, getOperatorJobs, retryOperatorJob } from "./api";
import { desktopJobNotificationsEnabled } from "./storage";
import type { OperatorJob, OperatorJobBoard } from "./types";

const EMPTY_BOARD: OperatorJobBoard = { jobs: [], active_count: 0, queued_count: 0 };

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
  const [board, setBoard] = useState<OperatorJobBoard>(EMPTY_BOARD);
  const [loading, setLoading] = useState(enabled && active);
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

  const refresh = useCallback(async () => {
    if (!mounted.current || !activity.current.enabled || !activity.current.active || request.current) return;
    const current = new AbortController();
    request.current = current;
    try {
      const next = await getOperatorJobs(current.signal);
      if (request.current !== current || !mounted.current || !activity.current.active || !activity.current.enabled) return;
      apply(next);
    } catch (reason) {
      if (request.current !== current || current.signal.aborted || !mounted.current || !activity.current.active || !activity.current.enabled) return;
      setLoading(false);
      notify(reason instanceof Error ? reason.message : "Job activity could not be loaded.", "error", "jobs-refresh");
    } finally {
      if (request.current === current) request.current = null;
    }
  }, [apply, notify]);

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
      const delay = document.visibilityState === "visible" ? working ? 1_000 : 5_000 : 15_000;
      timer = window.setTimeout(poll, delay);
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
      notify(reason instanceof Error ? reason.message : "Job retry failed.", "error", `job-retry:${jobId}`);
    }
  }, [notify, refresh]);

  const cancel = useCallback(async (jobId: string) => {
    if (!mounted.current || !activity.current.enabled || !activity.current.active) return;
    try {
      await cancelOperatorJob(jobId);
      await refresh();
    } catch (reason) {
      if (!mounted.current || !activity.current.active || !activity.current.enabled) return;
      notify(reason instanceof Error ? reason.message : "Job cancellation failed.", "error", `job-cancel:${jobId}`);
    }
  }, [notify, refresh]);

  return { board, loading, refresh, retry, cancel };
}
